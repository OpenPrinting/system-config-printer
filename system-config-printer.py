#!/usr/bin/env python

## system-config-printer

## Copyright (C) 2006, 2007, 2008 Red Hat, Inc.
## Copyright (C) 2006, 2007 Florian Festi <ffesti@redhat.com>
## Copyright (C) 2006, 2007, 2008 Tim Waugh <twaugh@redhat.com>

## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.

## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.

## You should have received a copy of the GNU General Public License
## along with this program; if not, write to the Free Software
## Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.

# config is generated from config.py.in by configure
import config

import errno
import sys, os, tempfile, time, traceback, re, httplib
import subprocess
import signal, thread
try:
    import gtk.glade
except RuntimeError, e:
    print "system-config-printer:", e
    print "This is a graphical application and requires DISPLAY to be set."
    sys.exit (1)

import gnome
gtk.about_dialog_set_url_hook (lambda x, y: gnome.url_show (y))
gtk.about_dialog_set_email_hook (lambda x, y: gnome.url_show ("mailto:" + y))

def show_help():
    print ("\nThis is system-config-printer, " \
           "a CUPS server configuration program.\n\n"
           "Options:\n\n"
           "  --configure-printer NAME\n"
           "            Select the named printer on start-up.\n\n"
           "  --choose-driver NAME\n"
           "            Select the named printer on start-up, and display\n"
           "            a list of drivers.\n")

if len(sys.argv)>1 and sys.argv[1] == '--help':
    show_help ()
    sys.exit (0)

import cups
cups.require ("1.9.27")

import pysmb
import cupshelpers, options
import gobject # for TYPE_STRING and TYPE_PYOBJECT
from optionwidgets import OptionWidget
from debug import *
import probe_printer
import gtk_label_autowrap
from gtk_treeviewtooltips import TreeViewTooltips
import urllib
import troubleshoot
import contextmenu
import authconn
import monitor
from smburi import SMBURI
import errordialogs
from errordialogs import *
import userdefault
from AdvancedServerSettings import AdvancedServerSettingsDialog
from PhysicalDevice import PhysicalDevice

domain='system-config-printer'
import locale
try:
    locale.setlocale (locale.LC_ALL, "")
except locale.Error:
    os.environ['LC_ALL'] = 'C'
    locale.setlocale (locale.LC_ALL, "")
from gettext import gettext as _
monitor.set_gettext_function (_)
errordialogs.set_gettext_function (_)
contextmenu.set_gettext_function (_)
import gettext
gettext.textdomain (domain)
gtk.glade.bindtextdomain (domain)
pkgdata = config.Paths ().get_path ('pkgdatadir')
iconpath = os.path.join (pkgdata, 'icons/')
sys.path.append (pkgdata)

busy_cursor = gtk.gdk.Cursor(gtk.gdk.WATCH)
ready_cursor = gtk.gdk.Cursor(gtk.gdk.LEFT_PTR)
ellipsis = unichr(0x2026)

TEXT_start_firewall_tool = _("To do this, select "
                             "System->Administration->Firewall "
                             "from the main menu.")

try:
    try_CUPS_SERVER_REMOTE_ANY = cups.CUPS_SERVER_REMOTE_ANY
except AttributeError:
    # cups module was compiled with CUPS < 1.3
    try_CUPS_SERVER_REMOTE_ANY = "_remote_any"

def validDeviceURI (uri):
    """Returns True is the provided URI is valid."""
    (scheme, rest) = urllib.splittype (uri)
    if scheme == None or scheme == '':
        return False
    if rest == None or rest.strip ('/') == '':
        return False
    return True

def CUPS_server_hostname ():
    host = cups.getServer ()
    if host[0] == '/':
        return 'localhost'
    return host

class GtkGUI:

    def getWidgets(self, *names):
        for name in names:
            widget = self.xml.get_widget(name)
            if widget is None:
                raise ValueError, "Widget '%s' not found" % name
            setattr(self, name, widget)

    def moveClassMembers(self, treeview_from, treeview_to):
        selection = treeview_from.get_selection()
        model_from, rows = selection.get_selected_rows()
        rows = [gtk.TreeRowReference(model_from, row) for row in rows]

        model_to = treeview_to.get_model()
        
        for row in rows:
            path = row.get_path()
            iter = model_from.get_iter(path)
            
            row_data = model_from.get(iter, 0)
            model_to.append(row_data)
            model_from.remove(iter)

    def getCurrentClassMembers(self, treeview):
        model = treeview.get_model()
        iter = model.get_iter_root()
        result = []
        while iter:
            result.append(model.get(iter, 0)[0])
            iter = model.iter_next(iter)
        result.sort()
        return result

def on_delete_just_hide (widget, event):
    widget.hide ()
    return True # stop other handlers

class GUI(GtkGUI, monitor.Watcher):

    printer_states = { cups.IPP_PRINTER_IDLE: _("Idle"),
                       cups.IPP_PRINTER_PROCESSING: _("Processing"),
                       cups.IPP_PRINTER_BUSY: _("Busy"),
                       cups.IPP_PRINTER_STOPPED: _("Stopped") }

    def __init__(self, configure_printer = None, change_ppd = False):

        try:
            self.language = locale.getlocale(locale.LC_MESSAGES)
            self.encoding = locale.getlocale(locale.LC_CTYPE)
        except:
            nonfatalException()
            os.environ['LC_ALL'] = 'C'
            locale.setlocale (locale.LC_ALL, "")
            self.language = locale.getlocale(locale.LC_MESSAGES)
            self.encoding = locale.getlocale(locale.LC_CTYPE)
        
        self.printer = None
        self.conflicts = set() # of options
        self.connect_server = (self.printer and self.printer.getServer()) \
                               or cups.getServer()	
        self.connect_encrypt = cups.getEncryption ()
        self.connect_user = cups.getUser()

        self.changed = set() # of options

        self.servers = set((self.connect_server,))
        self.server_is_publishing = False

        # WIDGETS
        # =======
        self.updating_widgets = False
        glade_dir = os.environ.get ("SYSTEM_CONFIG_PRINTER_GLADE", pkgdata)
        xml = os.path.join (glade_dir, domain + '.glade')
        self.xml = gtk.glade.XML(xml, domain = domain)

        self.getWidgets("MainWindow", "dests_iconview",
                        "PrinterPropertiesDialog",
                        "tvPrinterProperties",
                        "btnPrinterPropertiesCancel",
                        "btnPrinterPropertiesOK",
                        "btnPrinterPropertiesApply",
                        "btnPrinterPropertiesClose",
                        "ServerSettingsDialog",
                        "server_settings",
                        "statusbarMain",
                        "new_printer", "new_class",
                        "rename", "copy", "delete",
                        "enabled", "shared", "set_as_default",
                        "view_discovered_printers",

                        "toolbar",

                        "chkServerBrowse", "chkServerShare",
                        "chkServerShareAny",
                        "chkServerRemoteAdmin", "chkServerAllowCancelAll",
                        "chkServerLogDebug", "hboxServerBrowse",

                        "ntbkPrinter",
                         "entPDescription", "entPLocation",
                          "lblPMakeModel", "lblPMakeModel2",
                          "lblPState", "entPDevice", "lblPDevice2",
                          "btnSelectDevice", "btnChangePPD",
                          "chkPEnabled", "chkPAccepting", "chkPShared",
                        "lblNotPublished",
                        "btnPrintTestPage", "btnSelfTest", "btnCleanHeads",
                        "btnConflict",
           
                         "cmbPStartBanner", "cmbPEndBanner",
                          "cmbPErrorPolicy", "cmbPOperationPolicy",

                         "rbtnPAllow", "rbtnPDeny", "tvPUsers",
                          "entPUser", "btnPAddUser", "btnPDelUser", 

                        "lblPInstallOptions",
                         "swPInstallOptions", "vbPInstallOptions", 
                         "swPOptions",
                          "lblPOptions", "vbPOptions",
                         "algnClassMembers", "vbClassMembers",
                          "lblClassMembers",
                          "tvClassMembers", "tvClassNotMembers",
                          "btnClassAddMember", "btnClassDelMember",
                        # Job options
                        "sbJOCopies", "btnJOResetCopies",
                        "cmbJOOrientationRequested", "btnJOResetOrientationRequested",
                        "cbJOFitplot", "btnJOResetFitplot",
                        "cmbJONumberUp", "btnJOResetNumberUp",
                        "cmbJONumberUpLayout", "btnJOResetNumberUpLayout",
                        "sbJOBrightness", "btnJOResetBrightness",
                        "cmbJOFinishings", "btnJOResetFinishings",
                        "sbJOJobPriority", "btnJOResetJobPriority",
                        "cmbJOMedia", "btnJOResetMedia",
                        "cmbJOSides", "btnJOResetSides",
                        "cmbJOHoldUntil", "btnJOResetHoldUntil",
                        "cbJOMirror", "btnJOResetMirror",
                        "sbJOScaling", "btnJOResetScaling",
                        "sbJOSaturation", "btnJOResetSaturation",
                        "sbJOHue", "btnJOResetHue",
                        "sbJOGamma", "btnJOResetGamma",
                        "sbJOCpi", "btnJOResetCpi",
                        "sbJOLpi", "btnJOResetLpi",
                        "sbJOPageLeft", "btnJOResetPageLeft",
                        "sbJOPageRight", "btnJOResetPageRight",
                        "sbJOPageTop", "btnJOResetPageTop",
                        "sbJOPageBottom", "btnJOResetPageBottom",
                        "cbJOPrettyPrint", "btnJOResetPrettyPrint",
                        "cbJOWrap", "btnJOResetWrap",
                        "sbJOColumns", "btnJOResetColumns",
                        "tblJOOther",
                        "entNewJobOption", "btnNewJobOption",
                        # small dialogs
                        "ConnectDialog", "chkEncrypted", "cmbServername",
                        "btnConnect",
                        "ConnectingDialog", "lblConnecting",
                        "NewPrinterName", "entCopyName", "btnCopyOk",
                        "AboutDialog",
                        "WaitWindow", "lblWait",
                        )

        # Since some dialogs are reused we can't let the delete-event's
        # default handler destroy them
        for dialog in [self.PrinterPropertiesDialog,
                       self.ServerSettingsDialog,
                       self.ConnectingDialog]:
            dialog.connect ("delete-event", on_delete_just_hide)

        self.tooltips = gtk.Tooltips()
        self.tooltips.enable()
        gtk.window_set_default_icon_name ('printer')

        self.view_discovered_printers.set_sensitive (False)

        # Toolbar
        # Glade-2 doesn't have support for MenuToolButton, so we do that here.
        self.btnNew = gtk.MenuToolButton ('gtk-new')
        self.btnNew.set_is_important (True)
        newmenu = gtk.Menu ()
        newprinter = gtk.ImageMenuItem (_("Printer"))
        printericon = gtk.Image ()
        printericon.set_from_icon_name ("printer", gtk.ICON_SIZE_MENU)
        newprinter.set_image (printericon)
        newprinter.connect ('activate', self.on_new_printer_activate)
        self.btnNew.connect ('clicked', self.on_new_printer_activate)
        newclass = gtk.ImageMenuItem (_("Class"))
        classicon = gtk.Image ()
        classicon.set_from_icon_name ("gtk-dnd-multiple", gtk.ICON_SIZE_MENU)
        newclass.set_image (classicon)
        newclass.connect ('activate', self.on_new_class_activate)
        newprinter.show ()
        newclass.show ()
        newmenu.attach (newprinter, 0, 1, 0, 1)
        newmenu.attach (newclass, 0, 1, 1, 2)
        self.btnNew.set_menu (newmenu)
        self.toolbar.add (self.btnNew)
        self.toolbar.add (gtk.SeparatorToolItem ())
        refreshbutton = gtk.ToolButton ('gtk-refresh')
        refreshbutton.connect ('clicked', self.on_btnRefresh_clicked)
        self.toolbar.add (refreshbutton)
        self.toolbar.show_all ()

        # Printer Context Menu
        self.printer_context_menu = contextmenu.PrinterContextMenu (self)

        # New Printer Dialog
        self.newPrinterGUI = np = NewPrinterGUI(self)
        np.NewPrinterWindow.set_transient_for(self.MainWindow)

        # Set up "About" dialog
        self.AboutDialog.set_program_name(domain)
        self.AboutDialog.set_version(config.VERSION)
        self.AboutDialog.set_icon_name('printer')

        # Set up "Problems?" link button
        problems = gtk.LinkButton ('', label=_("Problems?"))
        self.hboxServerBrowse.pack_end (problems, False, False, 0)
        problems.connect ('clicked', self.on_problems_linkbutton_clicked)
        problems.show ()

        self.static_tabs = 3

        gtk_label_autowrap.set_autowrap(self.MainWindow)

        try:
            self.cups = authconn.Connection(self.MainWindow)
        except RuntimeError:
            self.cups = None

        self.status_context_id = self.statusbarMain.get_context_id(
            "Connection")
        self.setConnected()

        # Setup icon view
        self.mainlist = gtk.ListStore(gobject.TYPE_PYOBJECT, # Object
                                      gtk.gdk.Pixbuf,        # Pixbuf
                                      gobject.TYPE_STRING,   # Name
                                      gobject.TYPE_STRING)   # Tooltip
        
        self.dests_iconview.set_model(self.mainlist)
        self.dests_iconview.set_pixbuf_column (1)
        self.dests_iconview.set_text_column (2)
        self.dests_iconview.set_tooltip_column (3)
        self.dests_iconview.connect ('item-activated',
                                     self.dests_iconview_item_activated)
        self.dests_iconview.connect ('selection-changed',
                                     self.dests_iconview_selection_changed)
        self.dests_iconview.connect ('button_release_event',
                                     self.dests_iconview_button_release_event)
        self.dests_iconview.connect ('popup-menu',
                                     self.dests_iconview_popup_menu)
        self.dests_iconview_selection_changed (self.dests_iconview)

        # setup some lists
        m = gtk.SELECTION_MULTIPLE
        s = gtk.SELECTION_SINGLE
        for name, treeview, selection_mode in (
            (_("Members of this class"), self.tvClassMembers, m),
            (_("Others"), self.tvClassNotMembers, m),
            (_("Members of this class"), np.tvNCMembers, m),
            (_("Others"), np.tvNCNotMembers, m),
            (_("Devices"), np.tvNPDevices, s),
            (_("Connections"), np.tvNPDeviceURIs, s),
            (_("Makes"), np.tvNPMakes,s),
            (_("Models"), np.tvNPModels,s),
            (_("Drivers"), np.tvNPDrivers,s),
            (_("Downloadable Drivers"), np.tvNPDownloadableDrivers,s),
            (_("Users"), self.tvPUsers, m),
            ):
            
            model = gtk.ListStore(str)
            cell = gtk.CellRendererText()
            column = gtk.TreeViewColumn(name, cell, text=0)
            treeview.set_model(model)
            treeview.append_column(column)
            treeview.get_selection().set_mode(selection_mode)

        # Server Settings dialog
        self.ServerSettingsDialog.connect ('response',
                                           self.server_settings_response)

        self.conflict_dialog = gtk.MessageDialog(
            parent=None, flags=0, type=gtk.MESSAGE_WARNING,
            buttons=gtk.BUTTONS_OK)
        
        self.xml.signal_autoconnect(self)

        # Printer Properties dialog
        self.PrinterPropertiesDialog.connect ('response',
                                              self.printer_properties_response)

        # Printer Properties tree view
        col = gtk.TreeViewColumn ('', gtk.CellRendererText (), markup=0)
        self.tvPrinterProperties.append_column (col)
        sel = self.tvPrinterProperties.get_selection ()
        sel.connect ('changed', self.on_tvPrinterProperties_selection_changed)
        sel.set_mode (gtk.SELECTION_SINGLE)

        # Job Options widgets.
        opts = [ options.OptionAlwaysShown ("copies", int, 1,
                                            self.sbJOCopies,
                                            self.btnJOResetCopies),

                 options.OptionAlwaysShownSpecial \
                 ("orientation-requested", int, 3,
                  self.cmbJOOrientationRequested,
                  self.btnJOResetOrientationRequested,
                  combobox_map = [3, 4, 5, 6],
                  special_choice=_("Automatic rotation")),

                 options.OptionAlwaysShown ("fitplot", bool, False,
                                            self.cbJOFitplot,
                                            self.btnJOResetFitplot),

                 options.OptionAlwaysShown ("number-up", int, 1,
                                            self.cmbJONumberUp,
                                            self.btnJOResetNumberUp,
                                            combobox_map=[1, 2, 4, 6, 9, 16]),

                 options.OptionAlwaysShown ("number-up-layout", str, "lrtb",
                                            self.cmbJONumberUpLayout,
                                            self.btnJOResetNumberUpLayout,
                                            combobox_map = [ "lrtb",
                                                             "lrbt",
                                                             "rltb",
                                                             "rlbt",
                                                             "tblr",
                                                             "tbrl",
                                                             "btlr",
                                                             "btrl" ]),

                 options.OptionAlwaysShown ("brightness", int, 100,
                                            self.sbJOBrightness,
                                            self.btnJOResetBrightness),

                 options.OptionAlwaysShown ("finishings", int, 3,
                                            self.cmbJOFinishings,
                                            self.btnJOResetFinishings,
                                            combobox_map = [ 3, 4, 5, 6,
                                                             7, 8, 9, 10,
                                                             11, 12, 13, 14,
                                                             20, 21, 22, 23,
                                                             24, 25, 26, 27,
                                                             28, 29, 30, 31,
                                                             50, 51, 52, 53 ],
                                            use_supported = True),

                 options.OptionAlwaysShown ("job-priority", int, 50,
                                            self.sbJOJobPriority,
                                            self.btnJOResetJobPriority),

                 options.OptionAlwaysShown ("media", str,
                                            "A4", # This is the default for
                                                  # when media-default is
                                                  # not supplied by the IPP
                                                  # server.  Fortunately it
                                                  # is a mandatory attribute.
                                            self.cmbJOMedia,
                                            self.btnJOResetMedia,
                                            use_supported = True),

                 options.OptionAlwaysShown ("sides", str, "one-sided",
                                            self.cmbJOSides,
                                            self.btnJOResetSides,
                                            combobox_map =
                                            [ "one-sided",
                                              "two-sided-long-edge",
                                              "two-sided-short-edge" ]),

                 options.OptionAlwaysShown ("job-hold-until", str,
                                            "no-hold",
                                            self.cmbJOHoldUntil,
                                            self.btnJOResetHoldUntil,
                                            use_supported = True),

                 options.OptionAlwaysShown ("mirror", bool, False,
                                            self.cbJOMirror,
                                            self.btnJOResetMirror),

                 options.OptionAlwaysShown ("scaling", int, 100,
                                            self.sbJOScaling,
                                            self.btnJOResetScaling),

                 options.OptionAlwaysShown ("saturation", int, 100,
                                            self.sbJOSaturation,
                                            self.btnJOResetSaturation),

                 options.OptionAlwaysShown ("hue", int, 0,
                                            self.sbJOHue,
                                            self.btnJOResetHue),

                 options.OptionAlwaysShown ("gamma", int, 1000,
                                            self.sbJOGamma,
                                            self.btnJOResetGamma),

                 options.OptionAlwaysShown ("cpi", float, 10.0,
                                            self.sbJOCpi, self.btnJOResetCpi),

                 options.OptionAlwaysShown ("lpi", float, 6.0,
                                            self.sbJOLpi, self.btnJOResetLpi),

                 options.OptionAlwaysShown ("page-left", int, 18,
                                            self.sbJOPageLeft,
                                            self.btnJOResetPageLeft),

                 options.OptionAlwaysShown ("page-right", int, 18,
                                            self.sbJOPageRight,
                                            self.btnJOResetPageRight),

                 options.OptionAlwaysShown ("page-top", int, 36,
                                            self.sbJOPageTop,
                                            self.btnJOResetPageTop),

                 options.OptionAlwaysShown ("page-bottom", int, 36,
                                            self.sbJOPageBottom,
                                            self.btnJOResetPageBottom),

                 options.OptionAlwaysShown ("prettyprint", bool, False,
                                            self.cbJOPrettyPrint,
                                            self.btnJOResetPrettyPrint),

                 options.OptionAlwaysShown ("wrap", bool, False, self.cbJOWrap,
                                            self.btnJOResetWrap),

                 options.OptionAlwaysShown ("columns", int, 1,
                                            self.sbJOColumns,
                                            self.btnJOResetColumns),
                 ]
        self.job_options_widgets = {}
        self.job_options_buttons = {}
        for option in opts:
            self.job_options_widgets[option.widget] = option
            self.job_options_buttons[option.button] = option

        self.monitor = monitor.Monitor (self, monitor_jobs=False)

        try:
            self.populateList()
        except cups.HTTPError, (s,):
            self.cups = None
            self.setConnected()
            self.populateList()
            show_HTTP_Error(s, self.MainWindow)

        # Attempt to size the window appropriately.
        try:
            (max_width, max_height) = (600, 400)
            self.dests_iconview.resize_children ()
            (width, height) = self.dests_iconview.size_request ()
            if height > max_height:
                # Too tall.  Try at maximum width.
                self.dests_iconview.set_size_request (max_width, -1)
                self.dests_iconview.resize_children ()
                while gtk.events_pending ():
                    gtk.main_iteration ()
                (width, height) = self.dests_iconview.size_request ()

                # Finally, limit both the width and height.
                (width, height) = map (min,
                                       (width, height),
                                       (max_width, max_height))

            self.dests_iconview.set_size_request (width, height)
            while gtk.events_pending ():
                gtk.main_iteration ()
            (width, height) = self.MainWindow.get_size ()
            self.dests_iconview.set_size_request (-1, -1)
            self.MainWindow.resize (width, height)
        except:
            nonfatalException ()

        if configure_printer:
            # Need to find the entry in the iconview model and activate it.
            model = self.dests_iconview.get_model ()
            iter = model.get_iter_first ()
            while iter != None:
                name = model.get_value (iter, 2)
                if name == configure_printer:
                    path = model.get_path (iter)
                    self.dests_iconview.item_activated (path)
                    if change_ppd:
                        self.btnChangePPD.clicked ()
                    break
                iter = model.iter_next (iter)

    def dests_iconview_item_activated (self, iconview, path):
        model = iconview.get_model ()
        iter = model.get_iter (path)
        name = model.get_value (iter, 2)
        object = model.get_value (iter, 0)
        try:
            self.fillPrinterTab (name)
        except cups.IPPError, (e, m):
            show_IPP_Error (e, m, self.MainWindow)
            if e == cups.IPP_SERVICE_UNAVAILABLE:
                self.cups = None
                self.setConnected ()
                self.populateList ()
            return
        except RuntimeError:
            # Perhaps cupsGetPPD2 failed for a browsed printer.
            return

        self.PrinterPropertiesDialog.set_transient_for (self.MainWindow)
        for button in [self.btnPrinterPropertiesCancel,
                       self.btnPrinterPropertiesOK,
                       self.btnPrinterPropertiesApply]:
            if object.discovered:
                button.hide ()
            else:
                button.show ()
        if object.discovered:
            self.btnPrinterPropertiesClose.show ()
        else:
            self.btnPrinterPropertiesClose.hide ()
        self.setDataButtonState ()
        treeview = self.tvPrinterProperties
        sel = treeview.get_selection ()
        sel.select_path ((0,))
        self.on_tvPrinterProperties_selection_changed (sel)
        self.on_tvPrinterProperties_cursor_changed (treeview)
        host = CUPS_server_hostname ()
        self.PrinterPropertiesDialog.set_title (_("Printer Properties - "
                                                  "`%s' on %s") % (name, host))
        self.PrinterPropertiesDialog.show ()

    def printer_properties_response (self, dialog, response):
        if (response == gtk.RESPONSE_OK or
            response == gtk.RESPONSE_APPLY):
            success = self.save_printer (self.printer)

        if response == gtk.RESPONSE_APPLY:
            try:
                self.fillPrinterTab (self.printer.name)
            except:
                pass

            self.setDataButtonState ()

        if ((response == gtk.RESPONSE_OK and not success) or
            response == gtk.RESPONSE_CANCEL):
            dialog.hide ()

    def dests_iconview_selection_changed (self, iconview):
        self.updating_widgets = True
        paths = iconview.get_selected_items ()
        any_disabled = False
        any_enabled = False
        any_discovered = False
        any_shared = False
        any_unshared = False
        n = len (paths)
        for i in range (n):
            model = iconview.get_model ()
            iter = model.get_iter (paths[i])
            object = model.get_value (iter, 0)
            name = model.get_value (iter, 2)
            if object.discovered:
                any_discovered = True
            if object.enabled:
                any_enabled = True
            else:
                any_disabled = True
            if object.is_shared:
                any_shared = True
            else:
                any_unshared = True
            if (any_discovered and any_enabled and any_disabled and
                any_shared and any_unshared):
                break

        self.copy.set_sensitive(n == 1)
        self.rename.set_sensitive(n == 1 and not any_discovered)
        self.set_as_default.set_sensitive(n == 1 and
                                          self.default_printer != name)
        self.enabled.set_sensitive(n > 0 and not any_discovered)
        self.enabled.set_inconsistent (n > 1 and any_enabled and any_disabled)
        self.enabled.set_active (any_discovered or not any_disabled)
        self.shared.set_sensitive(n > 0 and not any_discovered)
        self.shared.set_inconsistent (n > 1 and any_enabled and any_disabled)
        self.shared.set_active (any_discovered or not any_unshared)
        self.delete.set_sensitive(n > 0 and not any_discovered)
        self.updating_widgets = False

    def dests_iconview_popup_menu (self, iconview):
        paths = iconview.get_selected_items ()
        self.printer_context_menu.popup (None, iconview, paths)

    def dests_iconview_button_release_event (self, iconview, event):
        if event.button > 1:
            click_path = iconview.get_path_at_pos (int (event.x),
                                                   int (event.y))
            paths = iconview.get_selected_items ()
            if click_path == None:
                iconview.unselect_all ()
                paths = []
            elif click_path not in paths:
                iconview.unselect_all ()
                iconview.select_path (click_path)
                cells = iconview.get_cells ()
                for cell in cells:
                    if type (cell) == gtk.CellRendererText:
                        break
                iconview.set_cursor (click_path, cell)
                paths = [click_path]
            self.printer_context_menu.popup (event, iconview, paths)
        return False

    def on_server_settings_activate (self, menuitem):
        try:
            self.fillServerTab ()
        except cups.IPPError:
            # Not authorized.
            return

        self.ServerSettingsDialog.set_transient_for (self.MainWindow)
        self.ServerSettingsDialog.show ()

    def server_settings_response (self, dialog, response):
        if response == gtk.RESPONSE_OK:
            # OK
            if not self.save_serversettings ():
                dialog.hide ()
        elif response == gtk.RESPONSE_YES:
            # Advanced
            AdvancedServerSettingsDialog (self.cups, dialog)
        else:
            dialog.hide ()

    def busy (self, win = None):
        try:
            if not win:
                win = self.MainWindow
            gdkwin = win.window
            if gdkwin:
                gdkwin.set_cursor (busy_cursor)
                while gtk.events_pending ():
                    gtk.main_iteration ()
        except:
            nonfatalException ()
            
    def ready (self, win = None):
        try:
            if not win:
                win = self.MainWindow
            gdkwin = win.window
            if gdkwin:
                gdkwin.set_cursor (ready_cursor)
                while gtk.events_pending ():
                    gtk.main_iteration ()
        except:
            nonfatalException ()

    def setConnected(self):
        connected = bool(self.cups)

        host = CUPS_server_hostname ()
        self.MainWindow.set_title(_("Printer configuration - %s") % host)

        if connected:
            status_msg = _("Connected to %s") % host
        else:
            status_msg = _("Not connected")
        self.statusbarMain.push(self.status_context_id, status_msg)

        for widget in (self.btnNew,
                       self.new_printer, self.new_class,
                       self.chkServerBrowse, self.chkServerShare,
                       self.chkServerRemoteAdmin,
                       self.chkServerAllowCancelAll,
                       self.chkServerLogDebug):
            widget.set_sensitive(connected)

        sharing = self.chkServerShare.get_active ()
        self.chkServerShareAny.set_sensitive (sharing)

        try:
            del self.server_settings
        except:
            pass
        
    def getServers(self):
        self.servers.discard(None)
        known_servers = list(self.servers)
        known_servers.sort()
        return known_servers

    def populateList(self, prompt_allowed=True):
        # Save selection of printers.
        selected_printers = set()
        paths = self.dests_iconview.get_selected_items ()
        model = self.dests_iconview.get_model ()
        for path in paths:
            iter = model.get_iter (path)
            name = model.get_value (iter, 2)
            selected_printers.add (name)

        if self.cups:
            self.cups._set_prompt_allowed (prompt_allowed)
            try:
                # get Printers
                self.printers = cupshelpers.getPrinters(self.cups)

                # Get default printer.
                try:
                    self.default_printer = self.cups.getDefault ()
                except AttributeError: # getDefault appeared in pycups-1.9.31
                    # This fetches the list of printers and classes *again*,
                    # just to find out the default printer.
                    dests = self.cups.getDests ()
                    if dests.has_key ((None,None)):
                        self.default_printer = dests[(None,None)].name
                    else:
                        self.default_printer = None
            except cups.IPPError, (e, m):
                show_IPP_Error(e, m, self.MainWindow)
                self.printers = {}
                self.default_printer = None
        else:
            self.printers = {}
            self.default_printer = None

        userdef = userdefault.UserDefaultPrinter ().get ()
        
        local_printers = []
        local_classes = []
        remote_printers = []
        remote_classes = []

        for name, printer in self.printers.iteritems():
            self.servers.add(printer.getServer())

            if printer.remote:
                if printer.is_class: remote_classes.append(name)
                else: remote_printers.append(name)
            else:
                if printer.is_class: local_classes.append(name)
                else: local_printers.append(name)

        local_printers.sort()
        local_classes.sort()
        remote_printers.sort()
        remote_classes.sort()

        # remove old printers/classes
        self.mainlist.clear ()
        
        # add new
        PRINTER_TYPE = { 'discovered-printer':
                             (_("Network printer (discovered)"),
                              'i-network-printer'),
                         'discovered-class':
                             (_("Network class (discovered)"),
                              'i-network-printer'),
                         'local-printer':
                             (_("Printer"),
                              'gnome-dev-printer'),
                         'local-fax':
                             (_("Fax"),
                              'gnome-dev-printer'),
                         'local-class':
                             (_("Class"),
                              'gnome-dev-printer'),
                         'ipp-printer':
                             (_("Network printer"),
                              'i-network-printer'),
                         'smb-printer':
                             (_("Network print share"),
                              'gnome-dev-printer'),
                         'network-printer':
                             (_("Network printer"),
                              'i-network-printer'),
                         }
        theme = gtk.icon_theme_get_default ()
        for printers in (local_printers,
                         local_classes,
                         remote_printers,
                         remote_classes):
            if not printers: continue
            for name in printers:
                type = 'local-printer'
                object = self.printers[name]
                if object.discovered:
                    if object.is_class:
                        type = 'discovered-class'
                    else:
                        type = 'discovered-printer'
                elif object.is_class:
                    type = 'local-class'
                else:
                    (scheme, rest) = urllib.splittype (object.device_uri)
                    if scheme == 'ipp':
                        type = 'ipp-printer'
                    elif scheme == 'smb':
                        type = 'smb-printer'
                    elif scheme == 'hpfax':
                        type = 'local-fax'
                    elif scheme in ['socket', 'lpd']:
                        type = 'network-printer'

                (tip, icon) = PRINTER_TYPE[type]
                (w, h) = gtk.icon_size_lookup (gtk.ICON_SIZE_DIALOG)
                try:
                    pixbuf = theme.load_icon (icon, w, 0)
                except gobject.GError:
                    # Not in theme.
                    pixbuf = None
                    for p in [iconpath, 'icons/']:
                        try:
                            pixbuf = gtk.gdk.pixbuf_new_from_file ("%s%s.png" %
                                                                   (p, icon))
                            break
                        except gobject.GError:
                            pass

                    if pixbuf == None:
                        try:
                            pixbuf = theme.load_icon ('printer', w, 0)
                        except:
                            # Just create an empty pixbuf.
                            pixbuf = gtk.gdk.Pixbuf (gtk.gdk.COLORSPACE_RGB,
                                                     True, 8, w, h)
                            pixbuf.fill (0)

                emblem = None
                if name == self.default_printer:
                    emblem = 'emblem-default'
                elif name == userdef:
                    emblem = 'emblem-favorite'

                if emblem:
                    (w, h) = gtk.icon_size_lookup (gtk.ICON_SIZE_DIALOG)
                    default_emblem = theme.load_icon (emblem, w/2, 0)
                    copy = pixbuf.copy ()
                    default_emblem.composite (copy, 0, 0,
                                              copy.get_width (),
                                              copy.get_height (),
                                              0, 0,
                                              1.0, 1.0,
                                              gtk.gdk.INTERP_NEAREST, 255)
                    pixbuf = copy

                self.mainlist.append (row=[object, pixbuf, name, tip])

        # Restore selection of printers.
        model = self.dests_iconview.get_model ()
        def maybe_select (model, path, iter):
            name = model.get_value (iter, 2)
            if name in selected_printers:
                self.dests_iconview.select_path (path)
        model.foreach (maybe_select)

    # Connect to Server

    def on_connect_servername_changed(self, widget):
        self.btnConnect.set_sensitive (len (widget.get_active_text ()) > 0)

    def on_connect_activate(self, widget):
        # Use browsed queues to build up a list of known IPP servers
        servers = self.getServers()
        current_server = (self.printer and self.printer.getServer()) \
                         or cups.getServer()

        store = gtk.ListStore (gobject.TYPE_STRING)
        self.cmbServername.set_model(store)
        for server in servers:
            self.cmbServername.append_text(server)
        self.cmbServername.show()

        self.cmbServername.child.set_text (current_server)
        self.chkEncrypted.set_active (cups.getEncryption() ==
                                      cups.HTTP_ENCRYPT_ALWAYS)

        self.cmbServername.grab_focus ()
        self.ConnectDialog.set_transient_for (self.MainWindow)
        response = self.ConnectDialog.run()

        self.ConnectDialog.hide()

        if response != gtk.RESPONSE_OK:
            return

        if self.chkEncrypted.get_active():
            cups.setEncryption(cups.HTTP_ENCRYPT_ALWAYS)
        else:
            cups.setEncryption(cups.HTTP_ENCRYPT_IF_REQUESTED)
        self.connect_encrypt = cups.getEncryption ()

        servername = self.cmbServername.child.get_text()

        self.lblConnecting.set_text(_("Connecting to server:\n%s") %
                                    servername)
        self.newPrinterGUI.dropPPDs()
        self.ConnectingDialog.set_transient_for(self.MainWindow)
        self.ConnectingDialog.show()
        self.connect_server = servername
        # We need to set the connecting user in this thread as well.
        cups.setServer(self.connect_server)
        cups.setUser('')
        self.connect_user = cups.getUser()
        # Now start a new thread for connection.
        self.connect_thread = thread.start_new_thread(self.connect,
                                                      (self.MainWindow,))

    def on_cancel_connect_clicked(self, widget):
        """
        Stop connection to new server
        (Doesn't really stop but sets flag for the connecting thread to
        ignore the connection)
        """
        self.connect_thread = None
        self.ConnectingDialog.hide()

    def connect(self, parent=None):
        """
        Open a connection to a new server. Is executed in a separate thread!
        """
        cups.setUser(self.connect_user)
        if self.connect_server[0] == '/':
            # UNIX domain socket.  This may potentially fail if the server
            # settings have been changed and cupsd has written out a
            # configuration that does not include a Listen line for the
            # UNIX domain socket.  To handle this special case, try to
            # connect once and fall back to "localhost" on failure.
            try:
                try:
                    connection = cups.Connection (host=self.connect_server,
                                                  encryption=self.connect_encrypt)
                except TypeError:
                    # Parameters to Connection() require pycups >= 1.9.40.
                    cups.setServer(self.connect_server)
                    cups.setEncryption (self.connect_encrypt)
                    connection = cups.Connection ()

                # Worked fine.  Disconnect, and we'll connect for real
                # shortly.
                del connection
            except RuntimeError:
                # When we connect, avoid the domain socket.
                cups.setServer ("localhost")
            except:
                nonfatalException ()

        try:
            connection = authconn.Connection(parent,
                                             host=self.connect_server,
                                             encryption=self.connect_encrypt)
            self.newPrinterGUI.dropPPDs ()
        except RuntimeError, s:
            if self.connect_thread != thread.get_ident(): return
            gtk.gdk.threads_enter()
            self.ConnectingDialog.hide()
            show_IPP_Error(None, s, parent)
            gtk.gdk.threads_leave()
            return        
        except cups.IPPError, (e, s):
            if self.connect_thread != thread.get_ident(): return
            gtk.gdk.threads_enter()
            self.ConnectingDialog.hide()
            show_IPP_Error(e, s, parent)
            gtk.gdk.threads_leave()
            return
        except:
            nonfatalException ()

        if self.connect_thread != thread.get_ident(): return
        gtk.gdk.threads_enter()

        try:
            self.ConnectingDialog.hide()
            self.cups = connection
            self.setConnected()
            self.populateList()
	except cups.HTTPError, (s,):
            self.cups = None
            self.setConnected()
            self.populateList()
            show_HTTP_Error(s, parent)
        except:
            nonfatalException ()

        gtk.gdk.threads_leave()

    def reconnect (self):
        """Reconnect to CUPS after the server has reloaded."""
        # libcups would handle the reconnection if we just told it to
        # do something, for example fetching a list of classes.
        # However, our local authentication certificate would be
        # invalidated by a server restart, so it is better for us to
        # handle the reconnection ourselves.

        attempt = 1
        while attempt <= 5:
            try:
                self.cups._connect ()
                break
            except RuntimeError:
                # Connection failed.
                time.sleep(1)
                attempt += 1

    def on_btnCancelConnect_clicked(self, widget):
        """Close Connect dialog"""
        self.ConnectWindow.hide()

    # refresh
    
    def on_btnRefresh_clicked(self, button):
        if self.cups == None:
            try:
                self.cups = authconn.Connection(self.MainWindow)
            except RuntimeError:
                pass

            self.setConnected()

        self.populateList()

    # Data handling

    def on_printer_changed(self, widget):
        if isinstance(widget, gtk.CheckButton):
            value = widget.get_active()
        elif isinstance(widget, gtk.Entry):
            value = widget.get_text()
        elif isinstance(widget, gtk.RadioButton):
            value = widget.get_active()
        elif isinstance(widget, gtk.ComboBox):
            value = widget.get_active_text()
        else:
            raise ValueError, "Widget type not supported (yet)"

        p = self.printer
        old_values = {
            self.entPDescription : p.info,
            self.entPLocation : p.location,
            self.entPDevice : p.device_uri,
            self.chkPEnabled : p.enabled,
            self.chkPAccepting : not p.rejecting,
            self.chkPShared : p.is_shared,
            self.cmbPStartBanner : p.job_sheet_start,
            self.cmbPEndBanner : p.job_sheet_end,
            self.cmbPErrorPolicy : p.error_policy,
            self.cmbPOperationPolicy : p.op_policy,
            self.rbtnPAllow: p.default_allow,
            }
        
        old_value = old_values[widget]
        
        if old_value == value:
            self.changed.discard(widget)
        else:
            self.changed.add(widget)
        self.setDataButtonState()
        
    def option_changed(self, option):
        if option.is_changed():
            self.changed.add(option)
        else:
            self.changed.discard(option)

        if option.conflicts:
            self.conflicts.add(option)
        else:
            self.conflicts.discard(option)
        self.setDataButtonState()

        if (self.option_manualfeed and self.option_inputslot and
            option == self.option_manualfeed):
            if option.get_current_value() == "True":
                self.option_inputslot.disable ()
            else:
                self.option_inputslot.enable ()

    # Access control
    def getPUsers(self):
        """return list of usernames from the GUI"""
        model = self.tvPUsers.get_model()
        result = []
        model.foreach(lambda model, path, iter:
                      result.append(model.get(iter, 0)[0]))
        result.sort()
        return result

    def setPUsers(self, users):
        """write list of usernames inot the GUI"""
        model = self.tvPUsers.get_model()
        model.clear()
        for user in users:
            model.append((user,))
            
        self.on_entPUser_changed(self.entPUser)
        self.on_tvPUsers_cursor_changed(self.tvPUsers)

    def checkPUsersChanged(self):
        """check if users in GUI and printer are different
        and set self.changed"""
        if self.getPUsers() != self.printer.except_users:
            self.changed.add(self.tvPUsers)
        else:
            self.changed.discard(self.tvPUsers)

        self.on_tvPUsers_cursor_changed(self.tvPUsers)
        self.setDataButtonState()

    def on_btnPAddUser_clicked(self, button):
        user = self.entPUser.get_text()
        if user:
            self.tvPUsers.get_model().insert(0, (user,))
            self.entPUser.set_text("")
        self.checkPUsersChanged()
        
    def on_btnPDelUser_clicked(self, button):
        model, rows = self.tvPUsers.get_selection().get_selected_rows()
        rows = [gtk.TreeRowReference(model, row) for row in rows]
        for row in rows:
            path = row.get_path()
            iter = model.get_iter(path)
            model.remove(iter)
        self.checkPUsersChanged()

    def on_entPUser_changed(self, widget):
        self.btnPAddUser.set_sensitive(bool(widget.get_text()))

    def on_tvPUsers_cursor_changed(self, widget):
        model, rows = widget.get_selection().get_selected_rows()
        self.btnPDelUser.set_sensitive(bool(rows))

    # Server side options
    def on_job_option_reset(self, button):
        option = self.job_options_buttons[button]
        option.reset ()
        # Remember to set this option for removal in the IPP request.
        if self.server_side_options.has_key (option.name):
            del self.server_side_options[option.name]
        if option.is_changed ():
            self.changed.add(option)
        else:
            self.changed.discard(option)
        self.setDataButtonState()

    def on_job_option_changed(self, widget):
        if not self.printer:
            return
        option = self.job_options_widgets[widget]
        option.changed ()
        if option.is_changed ():
            self.server_side_options[option.name] = option
            self.changed.add(option)
        else:
            if self.server_side_options.has_key (option.name):
                del self.server_side_options[option.name]
            self.changed.discard(option)
        self.setDataButtonState()
        # Don't set the reset button insensitive if the option hasn't
        # changed from the original value: it's still meaningful to
        # reset the option to the system default.

    def draw_other_job_options (self, editable=True):
        n = len (self.other_job_options)
        if n == 0:
            self.tblJOOther.hide_all ()
            return

        self.tblJOOther.resize (n, 3)
        children = self.tblJOOther.get_children ()
        for child in children:
            self.tblJOOther.remove (child)
        i = 0
        for opt in self.other_job_options:
            self.tblJOOther.attach (opt.label, 0, 1, i, i + 1,
                                    xoptions=gtk.FILL,
                                    yoptions=gtk.FILL)
            opt.label.set_alignment (0.0, 0.5)
            self.tblJOOther.attach (opt.selector, 1, 2, i, i + 1,
                                    xoptions=gtk.FILL,
                                    yoptions=0)
            opt.selector.set_sensitive (editable)

            btn = gtk.Button(stock="gtk-remove")
            btn.connect("clicked", self.on_btnJOOtherRemove_clicked)
            btn.set_data("pyobject", opt)
            btn.set_sensitive (editable)
            self.tblJOOther.attach(btn, 2, 3, i, i + 1,
                                   xoptions=0,
                                   yoptions=0)
            i += 1

        self.tblJOOther.show_all ()

    def add_job_option(self, name, value = "", supported = "", is_new=True,
                       editable=True):
        option = options.OptionWidget(name, value, supported,
                                      self.option_changed)
        option.is_new = is_new
        self.other_job_options.append (option)
        self.draw_other_job_options (editable=editable)
        self.server_side_options[name] = option
        if name in self.changed: # was deleted before
            option.is_new = False
        self.changed.add(option)
        self.setDataButtonState()
        if is_new:
            option.selector.grab_focus ()

    def on_btnJOOtherRemove_clicked(self, button):
        option = button.get_data("pyobject")
        self.other_job_options.remove (option)
        self.draw_other_job_options ()
        if option.is_new:
            self.changed.discard(option)
        else:
            # keep name as reminder that option got deleted
            self.changed.add(option.name)
        del self.server_side_options[option.name]
        self.setDataButtonState()

    def on_btnNewJobOption_clicked(self, button):
        name = self.entNewJobOption.get_text()
        self.add_job_option(name)
        self.tblJOOther.show_all()
        self.entNewJobOption.set_text ('')
        self.btnNewJobOption.set_sensitive (False)
        self.setDataButtonState()

    def on_entNewJobOption_changed(self, widget):
        text = self.entNewJobOption.get_text()
        active = (len(text) > 0) and text not in self.server_side_options
        self.btnNewJobOption.set_sensitive(active)

    def on_entNewJobOption_activate(self, widget):
        self.on_btnNewJobOption_clicked (widget) # wrong widget but ok

    # set buttons sensitivity
    def setDataButtonState(self):
        try: # Might not be a printer selected
            possible = (self.ppd and
                        not bool (self.changed) and
                        self.printer.enabled and
                        not self.printer.rejecting)

            self.btnPrintTestPage.set_sensitive (possible)

            commands = (self.printer.type & cups.CUPS_PRINTER_COMMANDS) != 0
            self.btnSelfTest.set_sensitive (commands and possible)
            self.btnCleanHeads.set_sensitive (commands and possible)
        except:
            pass

        installablebold = False
        optionsbold = False
        if self.conflicts:
            debugprint ("Conflicts detected")
            self.btnConflict.show()
            for option in self.conflicts:
                if option.tab_label == self.lblPInstallOptions:
                    installablebold = True
                else:
                    optionsbold = True
        else:
            self.btnConflict.hide()
        installabletext = _("Installable Options")
        optionstext = _("Printer Options")
        if installablebold:
            installabletext = "<b>%s</b>" % installabletext
        if optionsbold:
            optionstext = "<b>%s</b>" % optionstext
        self.lblPInstallOptions.set_markup (installabletext)
        self.lblPOptions.set_markup (optionstext)

        store = self.tvPrinterProperties.get_model ()
        if store:
            for n in range (self.ntbkPrinter.get_n_pages ()):
                page = self.ntbkPrinter.get_nth_page (n)
                label = self.ntbkPrinter.get_tab_label (page)
                if label == self.lblPInstallOptions:
                    iter = store.get_iter ((n,))
                    store.set_value (iter, 0, installabletext)
                elif label == self.lblPOptions:
                    iter = store.get_iter ((n,))
                    store.set_value (iter, 0, optionstext)

        self.btnPrinterPropertiesApply.set_sensitive (len (self.changed) > 0)

    def on_btnConflict_clicked(self, button):
        message = _("There are conflicting options.\n"
                    "Changes can only be applied after\n"
                    "these conflicts are resolved.")
        message += "\n\n"
        for option in self.conflicts:
            message += option.option.text + "\n"
        self.conflict_dialog.set_markup(message)
        self.conflict_dialog.run()
        self.conflict_dialog.hide()

    def save_printer(self, printer, saveall=False, parent=None):
        if parent == None:
            parent = self.PrinterPropertiesDialog
        class_deleted = False
        name = printer.name
        
        try:
            if not printer.is_class and self.ppd: 
                self.getPrinterSettings()
                if self.ppd.nondefaultsMarked() or saveall:
                    self.cups.addPrinter(name, ppd=self.ppd)

            if printer.is_class:
                # update member list
                new_members = self.getCurrentClassMembers(self.tvClassMembers)
                if not new_members:
                    dialog = gtk.MessageDialog(
                        flags=0, type=gtk.MESSAGE_WARNING,
                        buttons=gtk.BUTTONS_YES_NO,
                        message_format=_("This will delete this class!"))
                    dialog.format_secondary_text(_("Proceed anyway?"))
                    result = dialog.run()
                    dialog.destroy()
                    if result==gtk.RESPONSE_NO:
                        return True
                    class_deleted = True

                # update member list
                old_members = printer.class_members[:]
                
                for member in new_members:
                    if member in old_members:
                        old_members.remove(member)
                    else:
                        self.cups.addPrinterToClass(member, name)
                for member in old_members:
                    self.cups.deletePrinterFromClass(member, name)    

            location = self.entPLocation.get_text()
            info = self.entPDescription.get_text()
            device_uri = self.entPDevice.get_text()
            if device_uri.find (ellipsis) != -1:
                # The URI is sanitized and not editable.
                device_uri = printer.device_uri

            enabled = self.chkPEnabled.get_active()
            accepting = self.chkPAccepting.get_active()
            shared = self.chkPShared.get_active()

            if info!=printer.info or saveall:
                self.cups.setPrinterInfo(name, info)
            if location!=printer.location or saveall:
                self.cups.setPrinterLocation(name, location)
            if (not printer.is_class and
                (device_uri!=printer.device_uri or saveall)):
                self.cups.setPrinterDevice(name, device_uri)

            if enabled != printer.enabled or saveall:
                self.printer.setEnabled(enabled)
            if accepting == printer.rejecting or saveall:
                self.printer.setAccepting(accepting)
            if shared != printer.is_shared or saveall:
                self.printer.setShared(shared)
                
            job_sheet_start = self.cmbPStartBanner.get_active_text()
            job_sheet_end = self.cmbPEndBanner.get_active_text()
            error_policy = self.cmbPErrorPolicy.get_active_text()
            op_policy = self.cmbPOperationPolicy.get_active_text()

            if (job_sheet_start != printer.job_sheet_start or
                job_sheet_end != printer.job_sheet_end) or saveall:
                printer.setJobSheets(job_sheet_start, job_sheet_end)
            if error_policy != printer.error_policy or saveall:
                printer.setErrorPolicy(error_policy)
            if op_policy != printer.op_policy or saveall:
                printer.setOperationPolicy(op_policy)

            default_allow = self.rbtnPAllow.get_active()
            except_users = self.getPUsers()

            if (default_allow != printer.default_allow or
                except_users != printer.except_users) or saveall:
                printer.setAccess(default_allow, except_users)

            for option in printer.attributes:
                if option not in self.server_side_options:
                    printer.unsetOption(option)
            for option in self.server_side_options.itervalues():
                if (option.is_changed() or
                    saveall and
                    option.get_current_value () != option.system_default):
                    printer.setOption(option.name, option.get_current_value())

        except cups.IPPError, (e, s):
            show_IPP_Error(e, s, parent)
            return True
        self.changed = set() # of options

        if not self.__dict__.has_key ("server_settings"):
            # We can authenticate with the server correctly at this point,
            # but we have never fetched the server settings to see whether
            # the server is publishing shared printers.  Fetch the settings
            # now so that we can update the "not published" label if necessary.
            try:
                self.server_settings = self.cups.adminGetServerSettings()
            except:
                nonfatalException()

        if class_deleted:
            self.populateList ()
        else:
            # Update our copy of the printer's settings.
            try:
                printers = cupshelpers.getPrinters (self.cups)
                this_printer = { name: printers[name] }
                self.printers.update (this_printer)
            except cups.IPPError, (e, s):
                show_IPP_Error(e, s, self.PrinterPropertiesDialog)

        return False

    def getPrinterSettings(self):
        #self.ppd.markDefaults()
        for option in self.options.itervalues():
            option.writeback()

    ### Printer Properties tree view signal handlers
    def on_tvPrinterProperties_selection_changed (self, selection):
        # Prevent selection from being de-selected.
        (model, iter) = selection.get_selected ()
        if iter:
            self.printer_properties_last_iter_selected = iter
        else:
            try:
                iter = self.printer_properties_last_iter_selected
            except AttributeError:
                # Not set yet.
                return

            if model.iter_is_valid (iter):
                selection.select_iter (iter)

    def on_tvPrinterProperties_cursor_changed (self, treeview):
        # Adjust notebook to reflect selected item.
        (store, iter) = treeview.get_selection ().get_selected ()
        n = store.get_value (iter, 1)
        self.ntbkPrinter.set_current_page (n)

    # set default printer
    def set_system_or_user_default_printer (self, name):
        # First, decide if this is already the system default, in which
        # case we only need to clear the user default.
        userdef = userdefault.UserDefaultPrinter ()
        if name == self.default_printer:
            userdef.clear ()
            self.populateList ()
            return

        userdefault.UserDefaultPrompt (self.set_default_printer,
                                       self.populateList,
                                       name,
                                       _("Set Default Printer"),
                                       self.MainWindow,
                                       _("Do you want to set this as "
                                         "the system-wide default printer?"),
                                       _("Set as the _system-wide "
                                         "default printer"),
                                       _("_Clear my personal default setting"),
                                       _("Set as my _personal default printer"))

    def set_default_printer (self, name):
        printer = self.printers[name]
        try:
            printer.setAsDefault ()
        except cups.HTTPError, (s,):
            show_HTTP_Error (s, self.MainWindow)
            return
        except cups.IPPError, (e, msg):
            show_IPP_Error(e, msg, self.MainWindow)
            return

        # Now reconnect in case the server needed to reload.  This may
        # happen if we replaced the lpoptions file.
        self.reconnect ()

        try:
            self.populateList()
        except cups.HTTPError, (s,):
            self.cups = None
            self.setConnected()
            self.populateList()
            show_HTTP_Error(s, self.MainWindow)
    
    # print test page
    
    def on_btnPrintTestPage_clicked(self, button):
        user = cups.getUser ()
        try:
            # if we have a page size specific custom test page, use it;
            # otherwise use cups' default one
            custom_testpage = None
            opt = self.ppd.findOption ("PageSize")
            if opt:
                custom_testpage = os.path.join(pkgdata, 'testpage-%s.ps' % opt.defchoice.lower())


            # Connect as the current user so that the test page can be managed
            # as a normal job.
            cups.setUser ('')
            c = authconn.Connection (self.MainWindow, try_as_root=False,
                                     host=self.connect_server,
                                     encryption=self.connect_encrypt)
            if custom_testpage and os.path.exists(custom_testpage):
                debugprint ('Printing custom test page ' + custom_testpage)
                job_id = c.printTestPage(self.printer.name,
                                         file=custom_testpage)
            else:
                debugprint ('Printing default test page')
                job_id = c.printTestPage(self.printer.name)

            show_info_dialog (_("Submitted"),
                              _("Test page submitted as job %d") % job_id,
                              parent=self.MainWindow)
        except cups.IPPError, (e, msg):
            if (e == cups.IPP_NOT_AUTHORIZED and
                self.connect_server != 'localhost' and
                self.connect_server[0] != '/'):
                show_error_dialog (_("Not possible"),
                                   _("The remote server did not accept "
                                     "the print job, most likely "
                                     "because the printer is not "
                                     "shared."),
                                   self.MainWindow)
            else:
                show_IPP_Error(e, msg, self.MainWindow)

        cups.setUser (user)

    def maintenance_command (self, command):
        (tmpfd, tmpfname) = tempfile.mkstemp ()
        os.write (tmpfd, "#CUPS-COMMAND\n%s\n" % command)
        os.close (tmpfd)
        try:
            format = "application/vnd.cups-command"
            job_id = self.cups.printTestPage (self.printer.name,
                                              format=format,
                                              file=tmpfname,
                                              user=self.connect_user)
            show_info_dialog (_("Submitted"),
                              _("Maintenance command submitted as "
                                "job %d") % job_id,
                              parent=self.MainWindow)
        except cups.IPPError, (e, msg):
            if (e == cups.IPP_NOT_AUTHORIZED and
                self.printer.name != 'localhost'):
                show_error_dialog (_("Not possible"),
                                   _("The remote server did not accept "
                                     "the print job, most likely "
                                     "because the printer is not "
                                     "shared."),
                                   self.MainWindow)
            else:
                show_IPP_Error(e, msg, self.MainWindow)

    def on_btnSelfTest_clicked(self, button):
        self.maintenance_command ("PrintSelfTestPage")

    def on_btnCleanHeads_clicked(self, button):
        self.maintenance_command ("Clean all")

    def fillComboBox(self, combobox, values, value):
        combobox.get_model().clear()
        for nr, val in enumerate(values):
            combobox.append_text(val)
            if val == value: combobox.set_active(nr)
                                

    def fillPrinterTab(self, name):
        self.changed = set() # of options
        self.options = {} # keyword -> Option object
        self.conflicts = set() # of options

        printer = self.printers[name] 
        self.printer = printer
        printer.getAttributes ()
        try:
            # CUPS 1.4
            publishing = printer.other_attributes['server-is-sharing-printers']
            self.server_is_publishing = publishing
        except KeyError:
            pass

        editable = not self.printer.discovered
        editablePPD = not self.printer.remote

        try:
            self.ppd = printer.getPPD()
        except cups.IPPError, (e, m):
            # Some IPP error other than IPP_NOT_FOUND.
            show_IPP_Error(e, m, self.MainWindow)
            # Treat it as a raw queue.
            self.ppd = False
        except RuntimeError:
            # The underlying cupsGetPPD2() function returned NULL without
            # setting an IPP error, so it'll be something like a failed
            # connection.
            show_error_dialog (_("Error"),
                               _("There was a problem connecting to "
                                 "the CUPS server."),
                               self.MainWindow)
            raise

        for widget in (self.entPDescription, self.entPLocation,
                       self.entPDevice):
            widget.set_editable(editable)

        for widget in (self.btnSelectDevice, self.btnChangePPD,
                       self.chkPEnabled, self.chkPAccepting, self.chkPShared,
                       self.cmbPStartBanner, self.cmbPEndBanner,
                       self.cmbPErrorPolicy, self.cmbPOperationPolicy,
                       self.rbtnPAllow, self.rbtnPDeny, self.tvPUsers,
                       self.entPUser, self.btnPAddUser, self.btnPDelUser):
            widget.set_sensitive(editable)

        # Description page
        self.entPDescription.set_text(printer.info)
        self.entPLocation.set_text(printer.location)

        uri = printer.device_uri
        if uri.startswith("smb://"):
            (group, host, share,
             user, password) = SMBURI (uri=uri[6:]).separate ()
            if password:
                uri = "smb://"
                if len (user) or len (password):
                    uri += ellipsis
                uri += SMBURI (group=group, host=host, share=share).get_uri ()
                self.entPDevice.set_sensitive(False)
            else:
                self.entPDevice.set_sensitive(True)
        self.entPDevice.set_text(uri)
        self.changed.discard(self.entPDevice)
        
        # Hide make/model and Device URI for classes
        for widget in (self.lblPMakeModel2, self.lblPMakeModel,
                       self.btnChangePPD, self.lblPDevice2,
                       self.entPDevice, self.btnSelectDevice):
            if printer.is_class:
                widget.hide()
            else:
                widget.show()
            

        # Policy tab
        # ----------

        try:
            if printer.is_shared:
                if self.server_is_publishing:
                    self.lblNotPublished.hide_all ()
                else:
                    self.lblNotPublished.show_all ()
            else:
                self.lblNotPublished.hide_all ()
        except:
            nonfatalException()
            self.lblNotPublished.hide_all ()

        # Job sheets
        self.cmbPStartBanner.set_sensitive(editable)
        self.cmbPEndBanner.set_sensitive(editable)

        # Policies
        self.cmbPErrorPolicy.set_sensitive(editable)
        self.cmbPOperationPolicy.set_sensitive(editable)

        # Access control
        self.entPUser.set_text("")

        # Server side options (Job options)
        self.server_side_options = {}
        for option in self.job_options_widgets.values ():
            if option.name == "media" and self.ppd:
                # Slightly special case because the 'system default'
                # (i.e. what you get when you press Reset) depends
                # on the printer's PageSize.
                opt = self.ppd.findOption ("PageSize")
                if opt:
                    option.set_default (opt.defchoice)

            option_editable = editable
            try:
                value = self.printer.attributes[option.name]
            except KeyError:
                option.reinit (None)
            else:
                try:
                    if self.printer.possible_attributes.has_key (option.name):
                        supported = self.printer.\
                                    possible_attributes[option.name][1]
                        # Set the option widget.
                        # In CUPS 1.3.x the orientation-requested-default
                        # attribute may have the value None; this means there
                        # is no value set.  This suits our needs here, as None
                        # resets the option to the system default and makes the
                        # Reset button insensitive.
                        option.reinit (value, supported=supported)
                    else:
                        option.reinit (value)

                    self.server_side_options[option.name] = option
                except:
                    option_editable = False
                    show_error_dialog (_("Error"),
                                       _("Option '%s' has value '%s' "
                                         "and cannot be edited.") %
                                       (option.name, value),
                                       self.MainWindow)
            option.widget.set_sensitive (option_editable)
            if not editable:
                option.button.set_sensitive (False)
        self.other_job_options = []
        self.draw_other_job_options (editable=editable)
        for option in self.printer.attributes.keys ():
            if self.server_side_options.has_key (option):
                continue
            value = self.printer.attributes[option]
            if self.printer.possible_attributes.has_key (option):
                supported = self.printer.possible_attributes[option][1]
            else:
                if isinstance (value, bool):
                    supported = ["true", "false"]
                    value = str (value).lower ()
                else:
                    supported = ""
                    value = str (value)

            self.add_job_option (option, value=value,
                                 supported=supported, is_new=False,
                                 editable=editable)
        self.entNewJobOption.set_text ('')
        self.entNewJobOption.set_sensitive (editable)
        self.btnNewJobOption.set_sensitive (False)

        if printer.is_class:
            # remove InstallOptions tab
            tab_nr = self.ntbkPrinter.page_num(self.swPInstallOptions)
            if tab_nr != -1:
                self.ntbkPrinter.remove_page(tab_nr)
            self.fillClassMembers(name, editable)
        else:
            # real Printer
            self.fillPrinterOptions(name, editablePPD)

        # Now update the tree view (which we use instead of the notebook tabs).
        store = gtk.ListStore (gobject.TYPE_STRING, gobject.TYPE_INT)
        self.ntbkPrinter.set_show_tabs (False)
        for n in range (self.ntbkPrinter.get_n_pages ()):
            page = self.ntbkPrinter.get_nth_page (n)
            label = self.ntbkPrinter.get_tab_label (page)
            iter = store.append (None)
            store.set_value (iter, 0, label.get_text ())
            store.set_value (iter, 1, n)
        sel = self.tvPrinterProperties.get_selection ()
        self.tvPrinterProperties.set_model (store)

        self.changed = set() # of options
        self.updatePrinterProperties ()
        self.setDataButtonState()

    def updatePrinterProperties(self):
        debugprint ("update printer properties")
        printer = self.printer
        self.lblPMakeModel.set_text(printer.make_and_model)
        state = self.printer_states.get (printer.state, _("Unknown"))
        reason = printer.other_attributes.get ('printer-state-message', '')
        if len (reason) > 0:
            state += ' - ' + reason
        self.lblPState.set_text(state)
        if len (self.changed) == 0:
            debugprint ("no changes yet: full printer properties update")
            # State
            self.chkPEnabled.set_active(printer.enabled)
            self.chkPAccepting.set_active(not printer.rejecting)
            self.chkPShared.set_active(printer.is_shared)

            # Job sheets
            self.fillComboBox(self.cmbPStartBanner,
                              printer.job_sheets_supported,
                              printer.job_sheet_start),
            self.fillComboBox(self.cmbPEndBanner, printer.job_sheets_supported,
                              printer.job_sheet_end)

            # Policies
            self.fillComboBox(self.cmbPErrorPolicy,
                              printer.error_policy_supported,
                              printer.error_policy)
            self.fillComboBox(self.cmbPOperationPolicy,
                              printer.op_policy_supported,
                              printer.op_policy)

            # Access control
            self.rbtnPAllow.set_active(printer.default_allow)
            self.rbtnPDeny.set_active(not printer.default_allow)
            self.setPUsers(printer.except_users)

    def fillPrinterOptions(self, name, editable):
        # remove Class membership tab
        tab_nr = self.ntbkPrinter.page_num(self.algnClassMembers)
        if tab_nr != -1:
            self.ntbkPrinter.remove_page(tab_nr)

        # clean Installable Options Tab
        for widget in self.vbPInstallOptions.get_children():
            self.vbPInstallOptions.remove(widget)

        # clean Options Tab
        for widget in self.vbPOptions.get_children():
            self.vbPOptions.remove(widget)

        # insert Options Tab
        if self.ntbkPrinter.page_num(self.swPOptions) == -1:
            self.ntbkPrinter.insert_page(
                self.swPOptions, self.lblPOptions, self.static_tabs)

        if not self.ppd:
            tab_nr = self.ntbkPrinter.page_num(self.swPInstallOptions)
            if tab_nr != -1:
                self.ntbkPrinter.remove_page(tab_nr)
            tab_nr = self.ntbkPrinter.page_num(self.swPOptions)
            if tab_nr != -1:
                self.ntbkPrinter.remove_page(tab_nr)           
            return
        ppd = self.ppd
        ppd.markDefaults()

        hasInstallableOptions = False
        
        # build option tabs
        for group in ppd.optionGroups:
            if group.name == "InstallableOptions":
                hasInstallableOptions = True
                container = self.vbPInstallOptions
                tab_nr = self.ntbkPrinter.page_num(self.swPInstallOptions)
                if tab_nr == -1:
                    self.ntbkPrinter.insert_page(
                        self.swPInstallOptions, gtk.Label(group.text),
                        self.static_tabs)
                tab_label = self.lblPInstallOptions
            else:
                frame = gtk.Frame("<b>%s</b>" % group.text)
                frame.get_label_widget().set_use_markup(True)
                frame.set_shadow_type (gtk.SHADOW_NONE)
                self.vbPOptions.pack_start (frame, False, False, 0)
                container = gtk.Alignment (0.5, 0.5, 1.0, 1.0)
                # We want a left padding of 12, but there is a Table with
                # spacing 6, and the left-most column of it (the conflict
                # icon) is normally hidden, so just use 6 here.
                container.set_padding (6, 12, 6, 0)
                frame.add (container)
                tab_label = self.lblPOptions

            table = gtk.Table(1, 3, False)
            table.set_col_spacings(6)
            table.set_row_spacings(6)
            container.add(table)

            rows = 0

            # InputSlot and ManualFeed need special handling.  With
            # libcups, if ManualFeed is True, InputSlot gets unset.
            # Likewise, if InputSlot is set, ManualFeed becomes False.
            # We handle it by toggling the sensitivity of InputSlot
            # based on ManualFeed.
            self.option_inputslot = self.option_manualfeed = None

            for nr, option in enumerate(group.options):
                if option.keyword == "PageRegion":
                    continue
                rows += 1
                table.resize (rows, 3)
                o = OptionWidget(option, ppd, self, tab_label=tab_label)
                table.attach(o.conflictIcon, 0, 1, nr, nr+1, 0, 0, 0, 0)

                hbox = gtk.HBox()
                if o.label:
                    a = gtk.Alignment (0.5, 0.5, 1.0, 1.0)
                    a.set_padding (0, 0, 0, 6)
                    a.add (o.label)
                    table.attach(a, 1, 2, nr, nr+1, gtk.FILL, 0, 0, 0)
                    table.attach(hbox, 2, 3, nr, nr+1, gtk.FILL, 0, 0, 0)
                else:
                    table.attach(hbox, 1, 3, nr, nr+1, gtk.FILL, 0, 0, 0)
                hbox.pack_start(o.selector, False)
                self.options[option.keyword] = o
                o.selector.set_sensitive(editable)
                if option.keyword == "InputSlot":
                    self.option_inputslot = o
                elif option.keyword == "ManualFeed":
                    self.option_manualfeed = o

        # remove Installable Options tab if not needed
        if not hasInstallableOptions:
            tab_nr = self.ntbkPrinter.page_num(self.swPInstallOptions)
            if tab_nr != -1:
                self.ntbkPrinter.remove_page(tab_nr)

        # check for conflicts
        for option in self.options.itervalues():
            conflicts = option.checkConflicts()
            if conflicts:
                self.conflicts.add(option)

        self.swPInstallOptions.show_all()
        self.swPOptions.show_all()

    # Class members
    
    def fillClassMembers(self, name, editable):
        printer = self.printers[name]

        self.btnClassAddMember.set_sensitive(editable)
        self.btnClassDelMember.set_sensitive(editable)

        # remove Options tab
        tab_nr = self.ntbkPrinter.page_num(self.swPOptions)
        if tab_nr != -1:
            self.ntbkPrinter.remove_page(tab_nr)

        # insert Member Tab
        if self.ntbkPrinter.page_num(self.algnClassMembers) == -1:
            self.ntbkPrinter.insert_page(
                self.algnClassMembers, self.lblClassMembers,
                self.static_tabs)

        model_members = self.tvClassMembers.get_model()
        model_not_members = self.tvClassNotMembers.get_model()
        model_members.clear()
        model_not_members.clear()

        names = self.printers.keys()
        names.sort()
        for name in names:
            p = self.printers[name]
            if p is not printer:
                if name in printer.class_members:
                    model_members.append((name, ))
                else:
                    model_not_members.append((name, ))
                
    def on_btnClassAddMember_clicked(self, button):
        self.moveClassMembers(self.tvClassNotMembers,
                              self.tvClassMembers)
        if self.getCurrentClassMembers(self.tvClassMembers) != self.printer.class_members:
            self.changed.add(self.tvClassMembers)
        else:
            self.changed.discard(self.tvClassMembers)
        self.setDataButtonState()
        
    def on_btnClassDelMember_clicked(self, button):
        self.moveClassMembers(self.tvClassMembers,
                              self.tvClassNotMembers)
        if self.getCurrentClassMembers(self.tvClassMembers) != self.printer.class_members:
            self.changed.add(self.tvClassMembers)
        else:
            self.changed.discard(self.tvClassMembers)
        self.setDataButtonState()
        
    # Quit
    
    def on_quit_activate(self, widget, event=None):
        self.monitor.cleanup ()
        self.printer_context_menu.cleanup ()
        gtk.main_quit()

    # Rename
    def is_rename_possible (self, name):
        jobs = self.printers[name].jobsQueued ()
        if len (jobs) > 0:
            show_error_dialog (_("Cannot Rename"),
                               _("There are queued jobs."),
                               parent=self.MainWindow)
            return False

        return True

    def on_rename_activate(self, widget):
        tuple = self.dests_iconview.get_cursor ()
        if tuple == None:
            return

        (path, cell) = tuple
        model = self.dests_iconview.get_model ()
        iter = model.get_iter (path)
        name = model.get_value (iter, 2)
        if not self.is_rename_possible (name):
            return
        cell.set_property ('editable', True)
        self.dests_iconview.set_cursor (path, cell, start_editing=True)
        ids = []
        ids.append (cell.connect ('edited', self.printer_name_edited))
        ids.append (cell.connect ('editing-canceled',
                                 self.printer_name_edit_cancel))
        self.rename_sigids = ids

    def printer_name_edited (self, cell, path, newname):
        model = self.dests_iconview.get_model ()
        iter = model.get_iter (path)
        name = model.get_value (iter, 2)
        debugprint ("edited: %s -> %s" % (name, newname))
        try:
            self.rename_printer (name, newname)
        finally:
            cell.stop_editing (canceled=False)
            cell.set_property ('editable', False)
            for id in self.rename_sigids:
                cell.disconnect (id)

    def printer_name_edit_cancel (self, cell):
        debugprint ("editing-canceled")
        cell.stop_editing (canceled=True)
        cell.set_property ('editable', False)
        for id in self.rename_sigids:
            cell.disconnect (id)

    def rename_printer (self, old_name, new_name):
        if old_name == new_name:
            return

        try:
            self.fillPrinterTab (old_name)
        except RuntimeError:
            # Perhaps cupsGetPPD2 failed for a browsed printer
            pass

        if not self.is_rename_possible (old_name):
            return

        rejecting = self.printer.rejecting
        if not rejecting:
            try:
                self.printer.setAccepting (False)
                if not self.is_rename_possible (old_name):
                    self.printer.setAccepting (True)
                    return
            except cups.IPPError, (e, msg):
                show_IPP_Error (e, msg, self.MainWindow)
                return

        if self.copy_printer (new_name):
            # Failure.
            self.populateList ()

            # Restore original accepting/rejecting state.
            if not rejecting:
                try:
                    self.printers[old_name].setAccepting (True)
                except cups.HTTPError, (s,):
                    show_HTTP_Error (s, self.MainWindow)
                except cups.IPPError, (e, msg):
                    show_IPP_Error (e, msg, self.MainWindow)

            return

        # Restore rejecting state.
        if not rejecting:
            try:
                self.printer.setAccepting (True)
            except cups.HTTPError, (s,):
                show_HTTP_Error (s, self.MainWindow)
                # Not fatal.
            except cups.IPPError, (e, msg):
                show_IPP_Error (e, msg, self.MainWindow)
                # Not fatal.

        # Fix up default printer.
        if self.default_printer == old_name:
            try:
                self.printer.setAsDefault ()
            except cups.HTTPError, (s,):
                show_HTTP_Error (s, self.MainWindow)
                # Not fatal.
            except CUPS.IPPError, (e, msg):
                show_IPP_Error (e, msg, self.MainWindow)
                # Not fatal.

        # Finally, delete the old printer.
        try:
            self.cups.deletePrinter (old_name)
        except cups.HTTPError, (s,):
            show_HTTP_Error (s, self.MainWindow)
            # Not fatal
        except cups.IPPError, (e, msg):
            show_IPP_Error (e, msg, self.MainWindow)
            # Not fatal.

        # ..and select the new printer.
        def select_new_printer (model, path, iter):
            name = model.get_value (iter, 2)
            print name, new_name
            if name == new_name:
                self.dests_iconview.select_path (path)
        self.populateList ()
        model = self.dests_iconview.get_model ()
        model.foreach (select_new_printer)

    # Copy

    def copy_printer (self, new_name):
        self.printer.name = new_name
        self.printer.class_members = [] # for classes make sure all members
                                        # will get added 

        return self.save_printer(self.printer, saveall=True,
                                 parent=self.MainWindow)

    def on_copy_activate(self, widget):
        iconview = self.dests_iconview
        paths = iconview.get_selected_items ()
        model = self.dests_iconview.get_model ()
        iter = model.get_iter (paths[0])
        name = model.get_value (iter, 2)
        self.entCopyName.set_text(name)
        self.NewPrinterName.set_transient_for (self.MainWindow)
        result = self.NewPrinterName.run()
        self.NewPrinterName.hide()

        if result == gtk.RESPONSE_CANCEL:
            return

        try:
            self.fillPrinterTab (name)
        except RuntimeError:
            # Perhaps cupsGetPPD2 failed for a browsed printer
            pass

        self.copy_printer (self.entCopyName.get_text ())
        self.populateList()

    def on_entCopyName_changed(self, widget):
        # restrict
        text = widget.get_text()
        new_text = text
        new_text = new_text.replace("/", "")
        new_text = new_text.replace("#", "")
        new_text = new_text.replace(" ", "")
        if text!=new_text:
            widget.set_text(new_text)
        self.btnCopyOk.set_sensitive(
            self.checkNPName(new_text))

    # Delete

    def on_delete_activate(self, widget):
        paths = self.dests_iconview.get_selected_items ()
        model = self.dests_iconview.get_model ()
        n = len (paths)
        if n == 1:
            iter = model.get_iter (paths[0])
            object = model.get_value (iter, 0)
            name = model.get_value (iter, 2)
            if object.is_class:
                message_format = _("Really delete class `%s'?") % name
            else:
                message_format = _("Really delete printer `%s'?") % name
        else:
            message_format = _("Really delete selected destinations?")

        dialog = gtk.MessageDialog(self.MainWindow,
                                   buttons=gtk.BUTTONS_OK_CANCEL,
                                   message_format=message_format)
        result = dialog.run()
        dialog.destroy()

        if result == gtk.RESPONSE_CANCEL:
            return

        try:
            for i in range (n):
                iter = model.get_iter (paths[i])
                name = model.get_value (iter, 2)
                self.cups.deletePrinter (name)
        except cups.IPPError, (e, msg):
            show_IPP_Error(e, msg, self.MainWindow)

        self.changed = set()
        self.populateList()

    # Enable/disable
    def on_enabled_activate(self, menuitem):
        if self.updating_widgets:
            return
        enable = menuitem.get_active ()
        iconview = self.dests_iconview
        paths = iconview.get_selected_items ()
        model = iconview.get_model ()
        for i in range (len (paths)):
            iter = model.get_iter (paths[i])
            printer = model.get_value (iter, 0)
            try:
                printer.setEnabled (enable)
            except cups.IPPError, (e, m):
                show_IPP_Error(e, m, self.MainWindow)
                # Give up on this operation.
                break
        self.populateList ()

    # Shared
    def on_shared_activate(self, menuitem):
        if self.updating_widgets:
            return
        share = menuitem.get_active ()
        iconview = self.dests_iconview
        paths = iconview.get_selected_items ()
        model = iconview.get_model ()
        success = False
        for i in range (len (paths)):
            iter = model.get_iter (paths[i])
            printer = model.get_value (iter, 0)
            try:
                printer.setShared (share)
                success = True
            except cups.IPPError, (e, m):
                show_IPP_Error(e, m, self.MainWindow)
                # Give up on this operation.
                break
        if success and share:
            self.advise_publish ()
        self.populateList ()

    def advise_publish(self):
        if not self.server_is_publishing:
            show_info_dialog (_("Publish Shared Printers"),
                              _("Shared printers are not available "
                                "to other people unless the "
                                "'Publish shared printers' option is "
                                "enabled in the server settings."),
                              parent=self.MainWindow)

    # Set As Default
    def on_set_as_default_activate(self, menuitem):
        iconview = self.dests_iconview
        paths = iconview.get_selected_items ()
        model = iconview.get_model ()
        iter = model.get_iter (paths[0])
        name = model.get_value (iter, 2)
        self.set_system_or_user_default_printer (name)

    def on_troubleshoot_activate(self, widget):
        if not self.__dict__.has_key ('troubleshooter'):
            self.troubleshooter = troubleshoot.run (self.on_troubleshoot_quit,
                                                    parent=self.MainWindow)

    def on_troubleshoot_quit(self, troubleshooter):
        del self.troubleshooter

    # About dialog
    def on_about_activate(self, widget):
        self.AboutDialog.set_transient_for (self.MainWindow)
        self.AboutDialog.run()
        self.AboutDialog.hide()

    ##########################################################################
    ### Server settings
    ##########################################################################

    def fillServerTab(self):
        self.changed = set()
        try:
            self.server_settings = self.cups.adminGetServerSettings()
        except cups.IPPError, (e, m):
            show_IPP_Error(e, m, self.MainWindow)
            raise

        for widget, setting in [
            (self.chkServerBrowse, cups.CUPS_SERVER_REMOTE_PRINTERS),
            (self.chkServerShare, cups.CUPS_SERVER_SHARE_PRINTERS),
            (self.chkServerShareAny, try_CUPS_SERVER_REMOTE_ANY),
            (self.chkServerRemoteAdmin, cups.CUPS_SERVER_REMOTE_ADMIN),
            (self.chkServerAllowCancelAll, cups.CUPS_SERVER_USER_CANCEL_ANY),
            (self.chkServerLogDebug, cups.CUPS_SERVER_DEBUG_LOGGING),]:
            widget.set_data("setting", setting)
            if self.server_settings.has_key(setting):
                widget.set_active(int(self.server_settings[setting]))
                widget.set_sensitive(True)
            else:
                widget.set_active(False)
                widget.set_sensitive(False)
        self.setDataButtonState()

        try:
            flag = cups.CUPS_SERVER_SHARE_PRINTERS
            publishing = int (self.server_settings[flag])
            self.server_is_publishing = publishing
        except AttributeError:
            pass

        # Set sensitivity of 'Allow printing from the Internet'.
        self.on_server_changed (self.chkServerShare) # (any will do here)
        
    def on_server_changed(self, widget):
        setting = widget.get_data("setting")
        if self.server_settings.has_key (setting):
            if str(int(widget.get_active())) == self.server_settings[setting]:
                self.changed.discard(widget)
            else:
                self.changed.add(widget)

        sharing = self.chkServerShare.get_active ()
        self.chkServerShareAny.set_sensitive (
            sharing and self.server_settings.has_key(try_CUPS_SERVER_REMOTE_ANY))

        self.setDataButtonState()

    def save_serversettings(self):
        setting_dict = self.server_settings.copy()
        for widget, setting in [
            (self.chkServerBrowse, cups.CUPS_SERVER_REMOTE_PRINTERS),
            (self.chkServerShare, cups.CUPS_SERVER_SHARE_PRINTERS),
            (self.chkServerShareAny, try_CUPS_SERVER_REMOTE_ANY),
            (self.chkServerRemoteAdmin, cups.CUPS_SERVER_REMOTE_ADMIN),
            (self.chkServerAllowCancelAll, cups.CUPS_SERVER_USER_CANCEL_ANY),
            (self.chkServerLogDebug, cups.CUPS_SERVER_DEBUG_LOGGING),]:
            if not self.server_settings.has_key(setting): continue
            setting_dict[setting] = str(int(widget.get_active()))
        try:
            self.cups.adminSetServerSettings(setting_dict)
        except cups.IPPError, (e, m):
            show_IPP_Error(e, m, self.ServerSettingsDialog)
            return True
        except RuntimeError, s:
            show_IPP_Error(None, s, self.ServerSettingsDialog)
            return True
        self.changed = set()
        self.setDataButtonState()

        old_setting = self.server_settings.get (cups.CUPS_SERVER_SHARE_PRINTERS,
                                                '0')
        new_setting = setting_dict.get (cups.CUPS_SERVER_SHARE_PRINTERS, '0')
        if (old_setting == '0' and new_setting != '0'):
            # We have just enabled print queue sharing.
            # Ideally, this is the time we would check the firewall
            # settings on this machine and request that the IPP TCP port
            # be unblocked.  Unfortunately, this is not yet possible
            # (bug #440469).  However, we can display a dialog to suggest
            # that now might be a good time to review the firewall settings.
            show_info_dialog (_("Review Firewall"),
                              _("You may need to adjust the firewall "
                                "to allow network printing to this "
                                "computer.") + '\n\n' +
                              TEXT_start_firewall_tool,
                              parent=self.ServerSettingsDialog)

        time.sleep(1) # give the server a chance to process our request

        # Now reconnect, in case the server needed to reload.
        self.reconnect ()

        # Refresh the server settings in case they have changed in the
        # mean time.
        try:
            self.fillServerTab()
        except:
            nonfatalException()

    ### The "Problems?" clickable label
    def on_problems_linkbutton_clicked (self, *args):
        if not self.__dict__.has_key ('troubleshooter'):
            self.troubleshooter = troubleshoot.run (self.on_troubleshoot_quit,
                                                    parent=self.ServerSettingsDialog)

    # ====================================================================
    # == New Printer Dialog ==============================================
    # ====================================================================

    # new printer
    def on_new_printer_activate(self, widget):
        self.busy (self.MainWindow)
        self.newPrinterGUI.init("printer")
        self.ready (self.MainWindow)

    # new class
    def on_new_class_activate(self, widget):
        self.newPrinterGUI.init("class")

    # change device
    def on_btnSelectDevice_clicked(self, button):
        self.busy (self.MainWindow)
        self.newPrinterGUI.init("device")
        self.ready (self.MainWindow)

    # change PPD
    def on_btnChangePPD_clicked(self, button):
        self.busy (self.MainWindow)
        self.newPrinterGUI.init("ppd")
        self.ready (self.MainWindow)

    def checkNPName(self, name):
        if not name: return False
        name = name.lower()
        for printer in self.printers.values():
            if not printer.discovered and printer.name.lower()==name:
                return False
        return True
    
    def makeNameUnique(self, name):
        """Make a suggested queue name valid and unique."""
        name = name.replace (" ", "-")
        name = name.replace ("/", "-")
        name = name.replace ("#", "-")
        if not self.checkNPName (name):
            suffix=2
            while not self.checkNPName (name + str (suffix)):
                suffix += 1
                if suffix == 100:
                    break
            name += str (suffix)
        return name

    ## Watcher interface helpers
    def printer_added_or_removed (self):
        # Just fetch the list of printers again.  This is too simplistic.
        self.populateList (prompt_allowed=False)

    ## Watcher interface
    def printer_added (self, mon, printer):
        monitor.Watcher.printer_added (self, mon, printer)
        self.printer_added_or_removed ()

    def printer_event (self, mon, printer, eventname, event):
        monitor.Watcher.printer_event (self, mon, printer, eventname, event)
        self.printer_added_or_removed ()

        if self.PrinterPropertiesDialog.get_property('visible'):
            self.printer.getAttributes ()
            self.updatePrinterProperties ()

    def printer_removed (self, mon, printer):
        monitor.Watcher.printer_removed (self, mon, printer)
        self.printer_added_or_removed ()

    def cups_connection_error (self, mon):
        monitor.Watcher.cups_connection_error (self, mon)
        try:
            self.cups.getClasses ()
        except:
            self.cups = None
            self.setConnected ()
            self.populateList ()

class NewPrinterGUI(GtkGUI):

    new_printer_device_tabs = {
        "parallel" : 0, # empty tab
        "usb" : 0,
        "hal" : 0,
        "beh" : 0,
        "hp" : 0,
        "hpfax" : 0,
        "socket": 2,
        "ipp" : 3,
        "http" : 3,
        "lpd" : 4,
        "scsi" : 5,
        "serial" : 6,
        "smb" : 7,
        }

    def __init__(self, mainapp):
        self.mainapp = mainapp
        self.xml = mainapp.xml
        self.tooltips = mainapp.tooltips
        self.language = mainapp.language
        
        self.options = {} # keyword -> Option object
        self.changed = set()
        self.conflicts = set()
        self.ppd = None

        # Synchronisation objects.
        self.ppds_lock = thread.allocate_lock()
        self.devices_lock = thread.allocate_lock()
        self.ipp_lock = thread.allocate_lock()
        self.drivers_lock = thread.allocate_lock()

        self.getWidgets("NewPrinterWindow", "ntbkNewPrinter",
                        "ntbkPPDSource",
                         "btnNPBack", "btnNPForward", "btnNPApply",
                          "entNPName", "entNPDescription", "entNPLocation",
                          "tvNPDevices", "ntbkNPType",
                        "lblNPDeviceDescription",
                        "expNPDeviceURIs",
                        "tvNPDeviceURIs",
                           "cmbNPTSerialBaud", "cmbNPTSerialParity",
                            "cmbNPTSerialBits", "cmbNPTSerialFlow",
                           "cmbentNPTLpdHost", "cmbentNPTLpdQueue",
                           "entNPTIPPHostname", "btnIPPFindQueue",
                        "lblIPPURI", "entNPTIPPQueuename",
                        "btnIPPVerify",
                        "IPPBrowseDialog", "tvIPPBrowser",
                        "btnIPPBrowseOk",
                        "entNPTDirectJetHostname", "entNPTDirectJetPort",
                        "SMBBrowseDialog", "entSMBURI", "tvSMBBrowser", "tblSMBAuth",
                        "rbtnSMBAuthPrompt", "rbtnSMBAuthSet",
                        "entSMBUsername", "entSMBPassword",
                        "btnSMBBrowseOk", "btnSMBVerify",
                           "entNPTDevice",
                           "tvNCMembers", "tvNCNotMembers",
                          "rbtnNPPPD", "tvNPMakes", 
                          "rbtnNPFoomatic", "filechooserPPD",
                          "rbtnNPDownloadableDriverSearch",
                          "entNPDownloadableDriverSearch",
                        "btnNPDownloadableDriverSearch",
                        "cmbNPDownloadableDriverFoundPrinters",
                        
                          "tvNPModels", "tvNPDrivers",
                          "rbtnChangePPDasIs", "rbtnChangePPDKeepSettings",
                        "scrNPInstallableOptions", "vbNPInstallOptions",
                        "tvNPDownloadableDrivers",
                        "ntbkNPDownloadableDriverProperties",
                        "lblNPDownloadableDriverSupplier",
                        "lblNPDownloadableDriverLicense",
                        "lblNPDownloadableDriverDescription",
                        "frmNPDownloadableDriverLicenseTerms",
                        "tvNPDownloadableDriverLicense",
                        "rbtnNPDownloadLicenseYes",
                        "rbtnNPDownloadLicenseNo",
                        "NewPrinterName", "entCopyName", "btnCopyOk",
                        "InstallDialog", "lblInstall")

        # Since some dialogs are reused we can't let the delete-event's
        # default handler destroy them
        for dialog in [self.IPPBrowseDialog,
                       self.SMBBrowseDialog]:
            dialog.connect ("delete-event", on_delete_just_hide)

        # share with mainapp
        self.WaitWindow = mainapp.WaitWindow
        self.lblWait = mainapp.lblWait
        self.busy = mainapp.busy
        self.ready = mainapp.ready

        gtk_label_autowrap.set_autowrap(self.NewPrinterWindow)

        self.ntbkNewPrinter.set_show_tabs(False)
        self.ntbkPPDSource.set_show_tabs(False)
        self.ntbkNPType.set_show_tabs(False)
        self.ntbkNPDownloadableDriverProperties.set_show_tabs(False)

        # Set up OpenPrinting widgets.
        self.openprinting = cupshelpers.openprinting.OpenPrinting ()
        self.openprinting_query_handle = None
        combobox = self.cmbNPDownloadableDriverFoundPrinters
        cell = gtk.CellRendererText()
        combobox.pack_start (cell, True)
        combobox.add_attribute(cell, 'text', 0)

        # Devices expander
        self.expNPDeviceURIs.connect ("notify::expanded",
                                      self.on_expNPDeviceURIs_expanded)

        # SMB browser
        if pysmb.USE_OLD_CODE:
            self.smb_store = gtk.TreeStore (str, # host or share
                                            str, # comment
                                            gobject.TYPE_PYOBJECT, # domain dict
                                            gobject.TYPE_PYOBJECT) # host dict
        else:
            self.smb_store = gtk.TreeStore (gobject.TYPE_PYOBJECT)

        self.tvSMBBrowser.set_model (self.smb_store)

        # SMB list columns
        if pysmb.USE_OLD_CODE:
            self.smb_store.set_sort_column_id (0, gtk.SORT_ASCENDING)
            col = gtk.TreeViewColumn (_("Share"), gtk.CellRendererText (),
                                      text=0)
            col.set_resizable (True)
            col.set_sort_column_id (0)
            self.tvSMBBrowser.append_column (col)

            col = gtk.TreeViewColumn (_("Comment"), gtk.CellRendererText (),
                                      text=1)
            self.tvSMBBrowser.append_column (col)
        else:
            col = gtk.TreeViewColumn (_("Share"))
            cell = gtk.CellRendererText ()
            col.pack_start (cell, False)
            col.set_cell_data_func (cell, self.smbbrowser_cell_share)
            self.tvSMBBrowser.append_column (col)

            col = gtk.TreeViewColumn (_("Comment"))
            cell = gtk.CellRendererText ()
            col.pack_start (cell, False)
            col.set_cell_data_func (cell, self.smbbrowser_cell_comment)
            self.tvSMBBrowser.append_column (col)

        slct = self.tvSMBBrowser.get_selection ()
        slct.set_select_function (self.smb_select_function)
        
        self.SMBBrowseDialog.set_transient_for(self.NewPrinterWindow)

        # IPP browser
        self.ipp_store = gtk.TreeStore (str, # queue
                                        str, # location
                                        gobject.TYPE_PYOBJECT) # dict
        self.tvIPPBrowser.set_model (self.ipp_store)
        self.ipp_store.set_sort_column_id (0, gtk.SORT_ASCENDING)

        # IPP list columns
        col = gtk.TreeViewColumn (_("Queue"), gtk.CellRendererText (),
                                  text=0)
        col.set_resizable (True)
        col.set_sort_column_id (0)
        self.tvIPPBrowser.append_column (col)

        col = gtk.TreeViewColumn (_("Location"), gtk.CellRendererText (),
                                  text=1)
        self.tvIPPBrowser.append_column (col)
        self.IPPBrowseDialog.set_transient_for(self.NewPrinterWindow)

        self.tvNPDriversTooltips = TreeViewTooltips(self.tvNPDrivers, self.NPDriversTooltips)

        ppd_filter = gtk.FileFilter()
        ppd_filter.set_name(_("PostScript Printer Description files (*.ppd, *.PPD, *.ppd.gz, *.PPD.gz, *.PPD.GZ)"))
        ppd_filter.add_pattern("*.ppd")
        ppd_filter.add_pattern("*.PPD")
        ppd_filter.add_pattern("*.ppd.gz")
        ppd_filter.add_pattern("*.PPD.gz")
        ppd_filter.add_pattern("*.PPD.GZ")
        self.filechooserPPD.add_filter(ppd_filter)

        ppd_filter = gtk.FileFilter()
        ppd_filter.set_name(_("All files (*)"))
        ppd_filter.add_pattern("*")
        self.filechooserPPD.add_filter(ppd_filter)

        self.xml.signal_autoconnect(self)

    def show_IPP_Error (self, exception, message):
        return show_IPP_Error (exception, message, parent=self.NewPrinterWindow)

    def option_changed(self, option):
        if option.is_changed():
            self.changed.add(option)
        else:
            self.changed.discard(option)

        if option.conflicts:
            self.conflicts.add(option)
        else:
            self.conflicts.discard(option)
        self.setDataButtonState()

        return

    def setDataButtonState(self):
        self.btnNPForward.set_sensitive(not bool(self.conflicts))

    def init(self, dialog_mode):
        self.dialog_mode = dialog_mode
        self.options = {} # keyword -> Option object
        self.changed = set()
        self.conflicts = set()

        combobox = self.cmbNPDownloadableDriverFoundPrinters
        combobox.set_model (gtk.ListStore (str, str))
        self.entNPDownloadableDriverSearch.set_text ('')
        button = self.btnNPDownloadableDriverSearch
        label = button.get_children ()[0].get_children ()[0].get_children ()[1]
        self.btnNPDownloadableDriverSearch_label = label
        label.set_text (_("Search"))

        if self.dialog_mode in ("printer", "class"):
            self.entNPName.set_text (self.mainapp.makeNameUnique(self.dialog_mode))
            self.entNPName.grab_focus()
            for widget in [self.entNPLocation,
                           self.entNPDescription,
                           self.entSMBURI, self.entSMBUsername,
                           self.entSMBPassword]:
                widget.set_text('')

        self.entNPTDirectJetPort.set_text('9100')

        if self.dialog_mode == "printer":
            self.NewPrinterWindow.set_title(_("New Printer"))
            # Start on devices page (1, not 0)
            self.ntbkNewPrinter.set_current_page(1)
            self.fillDeviceTab()
            self.rbtnNPFoomatic.set_active (True)
            self.on_rbtnNPFoomatic_toggled(self.rbtnNPFoomatic)
            # Start fetching information from CUPS in the background
            self.new_printer_PPDs_loaded = False
            self.queryPPDs ()

        elif self.dialog_mode == "class":
            self.NewPrinterWindow.set_title(_("New Class"))
            self.fillNewClassMembers()
            # Start on name page
            self.ntbkNewPrinter.set_current_page(0)
        elif self.dialog_mode == "device":
            self.NewPrinterWindow.set_title(_("Change Device URI"))
            self.ntbkNewPrinter.set_current_page(1)
            self.fillDeviceTab(self.mainapp.printer.device_uri)
        elif self.dialog_mode == "ppd":
            self.NewPrinterWindow.set_title(_("Change Driver"))
            self.ntbkNewPrinter.set_current_page(2)
            self.rbtnNPFoomatic.set_active (True)
            self.on_rbtnNPFoomatic_toggled(self.rbtnNPFoomatic)
            self.rbtnChangePPDKeepSettings.set_active(True)

            self.auto_model = ""
            ppd = self.mainapp.ppd
            if ppd:
                attr = ppd.findAttr("Manufacturer")
                if attr:
                    mfr = attr.value
                else:
                    mfr = ""
                makeandmodel = mfr
                attr = ppd.findAttr("ModelName")
                if not attr: attr = ppd.findAttr("ShortNickName")
                if not attr: attr = ppd.findAttr("NickName")
                if attr:
                    if attr.value.startswith(mfr):
                        makeandmodel = attr.value
                    else:
                        makeandmodel += ' ' + attr.value
                else:
                    makeandmodel = ''

                (self.auto_make,
                 self.auto_model) = \
                 cupshelpers.ppds.ppdMakeModelSplit (makeandmodel)
            else:
                # Special CUPS names for a raw queue.
                self.auto_make = 'Raw'
                self.auto_model = 'Queue'

            try:
                self.loadPPDs ()
            except cups.IPPError, (e, m):
                show_IPP_Error (e, m, parent=self.mainapp.MainWindow)
                return
            except:
                return

            self.fillMakeList()

        self.setNPButtons()
        self.NewPrinterWindow.show()

    # get PPDs

    def queryPPDs(self):
        debugprint ("queryPPDs")
        if not self.ppds_lock.acquire(0):
            debugprint ("queryPPDs: in progress")
            return
        debugprint ("Lock acquired for PPDs thread")
        # Start new thread
        thread.start_new_thread (self.getPPDs_thread, (self.language[0],))
        debugprint ("PPDs thread started")

    def getPPDs_thread(self, language):
        try:
            debugprint ("Connecting (PPDs)")
            cups.setUser (self.mainapp.connect_user)
            cups.setPasswordCB (lambda x: '')
            try:
                c = cups.Connection (host=self.mainapp.connect_server,
                                     encryption=self.mainapp.connect_encrypt)
            except TypeError:
                # Parameters for Connection() require pycups >= 1.9.40.
                cups.setServer (self.mainapp.connect_server)
                cups.setEncryption (self.mainapp.connect_encrypt)
                c = cups.Connection ()

            debugprint ("Fetching PPDs")
            ppds_dict = c.getPPDs()
            self.ppds_result = cupshelpers.ppds.PPDs(ppds_dict,
                                                     language=language)
            debugprint ("Closing connection (PPDs)")
            del c
        except cups.IPPError, (e, msg):
            self.ppds_result = cups.IPPError (e, msg)
        except Exception, e:
            nonfatalException()
            self.ppds_result = e

        debugprint ("Releasing PPDs lock")
        self.ppds_lock.release ()

    def fetchPPDs(self, parent=None):
        debugprint ("fetchPPDs")
        self.queryPPDs()
        time.sleep (0.1)

        # Keep the UI refreshed while we wait for the devices to load.
        waiting = False
        while (self.ppds_lock.locked()):
            if not waiting:
                waiting = True
                self.lblWait.set_markup ('<span weight="bold" size="larger">' +
                                         _('Searching') + '</span>\n\n' +
                                         _('Searching for drivers'))
                if not parent:
                    parent = self.mainapp.MainWindow
                self.WaitWindow.set_transient_for (parent)
                self.WaitWindow.show ()

            while gtk.events_pending ():
                gtk.main_iteration ()

            time.sleep (0.1)

        if waiting:
            self.WaitWindow.hide ()

        debugprint ("Got PPDs")
        result = self.ppds_result # atomic operation
        if isinstance (result, Exception):
            # Propagate exception.
            raise result
        return result

    def loadPPDs(self, parent=None):
        try:
            return self.ppds
        except:
            self.ppds = self.fetchPPDs (parent=parent)
            return self.ppds

    def dropPPDs(self):
        try:
            del self.ppds
        except:
            pass

    # Class members

    def fillNewClassMembers(self):
        model = self.tvNCMembers.get_model()
        model.clear()
        model = self.tvNCNotMembers.get_model()
        model.clear()
        for printer in self.mainapp.printers.itervalues():
            model.append((printer.name,))

    def on_btnNCAddMember_clicked(self, button):
        self.moveClassMembers(self.tvNCNotMembers, self.tvNCMembers)
        self.btnNPApply.set_sensitive(
            bool(self.getCurrentClassMembers(self.tvNCMembers)))
        
    def on_btnNCDelMember_clicked(self, button):
        self.moveClassMembers(self.tvNCMembers, self.tvNCNotMembers)        
        self.btnNPApply.set_sensitive(
            bool(self.getCurrentClassMembers(self.tvNCMembers)))

    # Navigation buttons

    def on_NPCancel(self, widget, event=None):
        self.NewPrinterWindow.hide()
        if self.openprinting_query_handle != None:
            self.openprinting.cancelOperation (self.openprinting_query_handle)
            self.openprinting_query_handle = None
        return True

    def on_btnNPBack_clicked(self, widget):
        self.nextNPTab(-1)

    def on_btnNPForward_clicked(self, widget):
        self.nextNPTab()

    def nextNPTab(self, step=1):
        page_nr = self.ntbkNewPrinter.get_current_page()

        if self.dialog_mode == "class":
            order = [0, 4, 5]
        elif self.dialog_mode == "printer":
            self.busy (self.NewPrinterWindow)
            if page_nr == 1: # Device (first page)
                self.auto_make, self.auto_model = None, None
                self.device.uri = self.getDeviceURI()
                if self.device.type in ("socket", "lpd", "ipp", "bluetooth"):
                    host = self.getNetworkPrinterMakeModel(self.device)
                    faxuri = None
                    if host:
                        faxuri = self.get_hplip_uri_for_network_printer(host,
                                                                        "fax")
                    if faxuri:
                        dialog = gtk.Dialog(self.device.info,
                                            self.NewPrinterWindow,
                                            gtk.DIALOG_MODAL |
                                            gtk.DIALOG_DESTROY_WITH_PARENT,
                                            (_("Printer"), 1,
                                             _("Fax"), 2))
                        label = gtk.Label(_("This printer supports both "
                                            "printing and sending faxes.  "
                                            "Which functionality should be "
                                            "used for this queue?"))
                        dialog.vbox.pack_start(label, True, True, 0)
                        label.show()
                        queue_type = dialog.run()
                        dialog.destroy()
                        if (queue_type == 2):
                            self.device.id_dict = \
                               self.get_hpfax_device_id(faxuri)
                            self.device.uri = faxuri
                            self.auto_make = self.device.id_dict["MFG"]
                            self.auto_model = self.device.id_dict["MDL"]
                            self.device.id = "MFG:" + self.auto_make + \
                                             ";MDL:" + self.auto_model + \
                                             ";DES:" + \
                                             self.device.id_dict["DES"] + ";"
                uri = self.device.uri
                if uri and uri.startswith ("smb://"):
                    uri = SMBURI (uri=uri[6:]).sanitize_uri ()

                # Try to access the PPD, in this case our detected IPP
                # printer is a queue on a remote CUPS server which is
                # not automatically set up on our local CUPS server
                # (for example DNS-SD broadcasted queue from Mac OS X)
                self.remotecupsqueue = None
                res = re.search ("ipp://(\S+(:\d+|))/printers/(\S+)", uri)
                if res:
                    resg = res.groups()
                    try:
                        conn = httplib.HTTPConnection(resg[0])
                        conn.request("GET", "/printers/%s.ppd" % resg[2])
                        resp = conn.getresponse()
                        if resp.status == 200: self.remotecupsqueue = resg[2]
                    except:
                        pass

                    # We also want to fetch the printer-info and
                    # printer-location attributes, to pre-fill those
                    # fields for this new queue.
                    oldserver = cups.getServer()
                    oldport = cups.getPort()
                    oldencrypt = cups.getEncryption ()
                    try:
                        server = resg[0]
                        if len (resg[1]) > 0:
                            port = int (resg[1])
                        else:
                            port = 631

                        try:
                            c = cups.Connection (host=server,
                                                 port=port,
                                                 encryption=cups.HTTP_ENCRYPT_IF_REQUESTED)
                        except TypeError:
                            # Connection() parameters require pycups >= 1.9.40.
                            cups.setServer (server)
                            cups.setPort (port)
                            cups.setEncryption (cups.HTTP_ENCRYPT_IF_REQUESTED)
                            c = cups.Connection ()

                        r = ['printer-info', 'printer-location']
                        attrs = c.getPrinterAttributes (uri=uri,
                                                        requested_attributes=r)
                        info = attrs.get ('printer-info', '')
                        location = attrs.get ('printer-location', '')
                        if len (info) > 0:
                            self.entNPDescription.set_text (info)
                        if len (location) > 0:
                            self.entNPLocation.set_text (location)
                    except:
                        nonfatalException ()

                    cups.setServer (oldserver)
                    cups.setPort (oldport)
                    cups.setEncryption (oldencrypt)

                if (not self.remotecupsqueue and
                    not self.new_printer_PPDs_loaded):
                    try:
                        self.loadPPDs(self.NewPrinterWindow)
                    except cups.IPPError, (e, msg):
                        self.ready (self.NewPrinterWindow)
                        self.show_IPP_Error(e, msg)
                        return
                    except:
                        self.ready (self.NewPrinterWindow)
                        return
                    self.new_printer_PPDs_loaded = True

                ppdname = None
                try:
                    if self.remotecupsqueue:
                        # We have a remote CUPS queue, let the client queue
                        # stay raw so that the driver on the server gets used
                        ppdname = 'raw'
                        self.ppd = ppdname
                        name = self.remotecupsqueue
                        name = self.mainapp.makeNameUnique (name)
                        self.entNPName.set_text (name)
                    elif self.device.id:
                        id_dict = self.device.id_dict
                        (status, ppdname) = self.ppds.\
                            getPPDNameFromDeviceID (id_dict["MFG"],
                                                    id_dict["MDL"],
                                                    id_dict["DES"],
                                                    id_dict["CMD"],
                                                    self.device.uri)
                    else:
                        (status, ppdname) = self.ppds.\
                            getPPDNameFromDeviceID ("Generic",
                                                    "Printer",
                                                    "Generic Printer",
                                                    [],
                                                    self.device.uri)
                        
                    if ppdname and not self.remotecupsqueue:
                        ppddict = self.ppds.getInfoFromPPDName (ppdname)
                        make_model = ppddict['ppd-make-and-model']
                        (make, model) = \
                            cupshelpers.ppds.ppdMakeModelSplit (make_model)
                        self.auto_make = make
                        self.auto_model = model
                except:
                    nonfatalException ()

                if not self.remotecupsqueue:
                    self.fillMakeList()
            elif page_nr == 3: # Model has been selected
                if not self.device.id:
                    # Choose an appropriate name when no Device ID
                    # is available, based on the model the user has
                    # selected.
                    try:
                        model, iter = self.tvNPModels.get_selection ().\
                                      get_selected ()
                        name = model.get(iter, 0)[0]
                        name = self.mainapp.makeNameUnique (name)
                        self.entNPName.set_text (name)
                    except:
                        nonfatalException ()

            self.ready (self.NewPrinterWindow)
            if self.remotecupsqueue:
                order = [1, 0]
            elif self.rbtnNPFoomatic.get_active():
                order = [1, 2, 3, 6, 0]
            elif self.rbtnNPPPD.get_active():
                order = [1, 2, 6, 0]
            else:
                # Downloadable driver
                order = [1, 2, 7, 6, 0]
        elif self.dialog_mode == "device":
            order = [1]
        elif self.dialog_mode == "ppd":
            if self.rbtnNPFoomatic.get_active():
                order = [2, 3, 5, 6]
            elif self.rbtnNPPPD.get_active():
                order = [2, 5, 6]
            else:
                # Downloadable driver
                order = [2, 7, 5, 6]

        next_page_nr = order[order.index(page_nr)+step]

        # fill Installable Options tab
        fetch_ppd = False
        try:
            if order.index (5) > -1:
                # There is a copy settings page in this set
                fetch_ppd = next_page_nr == 5 and step > 0
        except ValueError:
            fetch_ppd = next_page_nr == 6 and step > 0
    
        debugprint ("Will fetch ppd? %d" % fetch_ppd)
        if fetch_ppd:
            self.ppd = self.getNPPPD()
            self.installable_options = False
            if self.ppd == None:
                return

            # Prepare Installable Options screen.
            if isinstance(self.ppd, cups.PPD):
                self.fillNPInstallableOptions()
            else:
                # Put a label there explaining why the page is empty.
                ppd = self.ppd
                self.ppd = None
                self.fillNPInstallableOptions()
                self.ppd = ppd

            if not self.installable_options:
                if next_page_nr == 6:
                    # step over if empty
                    next_page_nr = order[order.index(next_page_nr)+1]

        # Step over empty Installable Options tab when moving backwards.
        if next_page_nr == 6 and not self.installable_options and step<0:
            next_page_nr = order[order.index(next_page_nr)-1]

        if step > 0 and next_page_nr == 7: # About to show downloadable drivers
            if self.drivers_lock.locked ():
                # Still searching for drivers.
                self.lblWait.set_markup ('<span weight="bold" size="larger">' +
                                         _('Searching') + '</span>\n\n' +
                                         _('Searching for drivers'))
                self.WaitWindow.set_transient_for (self.NewPrinterWindow)
                self.WaitWindow.show ()
                self.busy (self.NewPrinterWindow)

                # Keep the UI refreshed while we wait for the drivers
                # query to complete.
                while self.drivers_lock.locked ():
                    while gtk.events_pending ():
                        gtk.main_iteration ()
                    time.sleep (0.1)

                self.ready (self.NewPrinterWindow)
                self.WaitWindow.hide ()

            self.fillDownloadableDrivers()

        if step > 0 and next_page_nr == 0: # About to choose a name.
            # Suggest an appropriate name.
            name = None
            try:
                if self.device.id:
                    name = self.device.id_dict["MDL"]
            except:
                nonfatalException ()

            if name == None:
                name = 'printer'

            name = self.mainapp.makeNameUnique (name)
            self.entNPName.set_text (name)

        self.ntbkNewPrinter.set_current_page(next_page_nr)

        self.setNPButtons()

    def setNPButtons(self):
        nr = self.ntbkNewPrinter.get_current_page()

        if self.dialog_mode == "device":
            self.btnNPBack.hide()
            self.btnNPForward.hide()
            self.btnNPApply.show()
            try:
                uri = self.getDeviceURI ()
                valid = validDeviceURI (uri)
            except AttributeError:
                # No device selected yet.
                valid = False
            self.btnNPApply.set_sensitive (valid)
            return

        if self.dialog_mode == "ppd":
            if nr == 5: # Apply
                if not self.installable_options:
                    # There are no installable options, so this is the
                    # last page.
                    debugprint ("No installable options")
                    self.btnNPForward.hide ()
                    self.btnNPApply.show ()
                else:
                    self.btnNPForward.show ()
                    self.btnNPApply.hide ()
                return
            elif nr == 6:
                self.btnNPForward.hide()
                self.btnNPApply.show()
                return
            else:
                self.btnNPForward.show()
                self.btnNPApply.hide()
            if nr == 2:
                self.btnNPBack.hide()
                self.btnNPForward.show()
                downloadable_selected = False
                if self.rbtnNPDownloadableDriverSearch.get_active ():
                    combobox = self.cmbNPDownloadableDriverFoundPrinters
                    iter = combobox.get_active_iter ()
                    if iter and combobox.get_model ().get_value (iter, 1):
                        downloadable_selected = True

                self.btnNPForward.set_sensitive(bool(
                        self.rbtnNPFoomatic.get_active() or
                        self.filechooserPPD.get_filename() or
                        downloadable_selected))
                return
            else:
                self.btnNPBack.show()

        # class/printer

        if nr == 1: # Device
            valid = False
            try:
                uri = self.getDeviceURI ()
                valid = validDeviceURI (uri)
            except:
                pass
            self.btnNPForward.set_sensitive(valid)
            self.btnNPBack.hide ()
        else:
            self.btnNPBack.show()

        self.btnNPForward.show()
        self.btnNPApply.hide()

        if nr == 0: # Name
            self.btnNPBack.show()
            if self.dialog_mode == "printer":
                self.btnNPForward.hide()
                self.btnNPApply.show()
                self.btnNPApply.set_sensitive(
                    self.mainapp.checkNPName(self.entNPName.get_text()))
            if self.dialog_mode == "class":
                # This is the first page for the New Class dialog, so
                # hide the Back button.
                self.btnNPBack.hide ()
        if nr == 2: # Make/PPD file
            downloadable_selected = False
            if self.rbtnNPDownloadableDriverSearch.get_active ():
                combobox = self.cmbNPDownloadableDriverFoundPrinters
                iter = combobox.get_active_iter ()
                if iter and combobox.get_model ().get_value (iter, 1):
                    downloadable_selected = True

            self.btnNPForward.set_sensitive(bool(
                self.rbtnNPFoomatic.get_active() or
                self.filechooserPPD.get_filename() or
                downloadable_selected))
        if nr == 3: # Model/Driver
            model, iter = self.tvNPDrivers.get_selection().get_selected()
            self.btnNPForward.set_sensitive(bool(iter))
        if nr == 4: # Class Members
            self.btnNPForward.hide()
            self.btnNPApply.show()
            self.btnNPApply.set_sensitive(
                bool(self.getCurrentClassMembers(self.tvNCMembers)))
        if nr == 7: # Downloadable drivers
            if self.ntbkNPDownloadableDriverProperties.get_current_page() == 1:
                accepted = self.rbtnNPDownloadLicenseYes.get_active ()
            else:
                treeview = self.tvNPDownloadableDrivers
                model, iter = treeview.get_selection ().get_selected ()
                accepted = (iter != None)

            self.btnNPForward.set_sensitive(accepted)
            
    def on_entNPName_changed(self, widget):
        # restrict
        text = widget.get_text()
        new_text = text
        new_text = new_text.replace("/", "")
        new_text = new_text.replace("#", "")
        new_text = new_text.replace(" ", "")
        if text!=new_text:
            widget.set_text(new_text)
        if self.dialog_mode == "printer":
            self.btnNPApply.set_sensitive(
                self.mainapp.checkNPName(new_text))
        else:
            self.btnNPForward.set_sensitive(
                self.mainapp.checkNPName(new_text))

    # Device URI
    def queryDevices(self):
        if not self.devices_lock.acquire(0):
            debugprint ("queryDevices: in progress")
            return
        debugprint ("Lock acquired for devices thread")
        # Start new thread
        thread.start_new_thread (self.getDevices_thread, ())
        debugprint ("Devices thread started")

    def getDevices_thread(self):
        try:
            debugprint ("Connecting (devices)")
            cups.setUser (self.mainapp.connect_user)
            cups.setPasswordCB (lambda x: '')
            try:
                c = cups.Connection (host=self.mainapp.connect_server,
                                     encryption=self.mainapp.connect_encrypt)
            except TypeError:
                # Parameters to Connection() require pycups >= 1.9.40.
                cups.setServer (self.mainapp.connect_server)
                cups.setEncryption (self.mainapp.connect_encrypt)
                c = cups.Connection ()
            debugprint ("Fetching devices")
            self.devices_result = cupshelpers.getDevices(c)
        except cups.IPPError, (e, msg):
            self.devices_result = cups.IPPError (e, msg)
        except:
            nonfatalException ()
            self.devices_result = {}

        try:
            debugprint ("Closing connection (devices)")
            del c
        except:
            pass

        debugprint ("Releasing devices lock")
        self.devices_lock.release ()

    def fetchDevices(self, parent=None):
        debugprint ("fetchDevices")
        self.queryDevices ()

        try:
            if not isinstance (self.devices_result, cups.IPPError):
                # Return the result we got last time.
                return self.devices_result.copy ()
        except AttributeError:
            pass

        time.sleep (0.1)

        # Keep the UI refreshed while we wait for the devices to load.
        waiting = False
        while (self.devices_lock.locked()):
            if not waiting:
                waiting = True
                self.lblWait.set_markup ('<span weight="bold" size="larger">' +
                                         _('Searching') + '</span>\n\n' +
                                         _('Searching for printers'))
                if not parent:
                    parent = self.mainapp.MainWindow
                self.WaitWindow.set_transient_for (parent)
                self.WaitWindow.show ()

            while gtk.events_pending ():
                gtk.main_iteration ()

            time.sleep (0.1)

        if waiting:
            self.WaitWindow.hide ()

        debugprint ("Got devices")
        result = self.devices_result # atomic operation
        if isinstance (result, cups.IPPError):
            # Propagate exception.
            raise result
        return result.copy ()

    def get_hpfax_device_id(self, faxuri):
        os.environ["URI"] = faxuri
        cmd = 'LC_ALL=C DISPLAY= hp-info -d "${URI}"'
        debugprint (faxuri + ": " + cmd)
        try:
            p = subprocess.Popen (cmd, shell=True,
                                  stdin=file("/dev/null"),
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
            (stdout, stderr) = p.communicate ()
        except:
            # Problem executing command.
            return None

        for line in stdout.split ("\n"):
            if line.find ("fax-type") == -1:
                continue
            faxtype = -1
            res = re.search ("(\d+)", line)
            if res:
                resg = res.groups()
                faxtype = resg[0]
            if faxtype >= 0: break
        if faxtype < 0:
            return None
        elif faxtype == 4:
            return cupshelpers.parseDeviceID ('MFG:HP;MDL:Fax 2;DES:HP Fax 2;')
        else:
            return cupshelpers.parseDeviceID ('MFG:HP;MDL:Fax;DES:HP Fax;')

    def get_hplip_uri_for_network_printer(self, host, mode):
        os.environ["HOST"] = host
        if mode == "print": mod = "-c"
        elif mode == "fax": mod = "-f"
        else: mod = "-c"
        cmd = 'hp-makeuri ' + mod + ' "${HOST}"'
        debugprint (host + ": " + cmd)
        uri = None
        try:
            p = subprocess.Popen (cmd, shell=True,
                                  stdin=file("/dev/null"),
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
            (stdout, stderr) = p.communicate ()
        except:
            # Problem executing command.
            return None

        uri = stdout.strip ()
        return uri

    def getNetworkPrinterMakeModel(self, device):
        # Determine host name/IP
        host = None
        s = device.uri.find ("://")
        if s != -1:
            s += 3
            e = device.uri[s:].find (":")
            if e == -1: e = device.uri[s:].find ("/")
            if e == -1: e = device.uri[s:].find ("?")
            if e == -1: e = len (device.uri)
            host = device.uri[s:s+e]
        # Try to get make and model via SNMP
        if host:
            os.environ["HOST"] = host
            cmd = '/usr/lib/cups/backend/snmp "${HOST}"'
            debugprint (host + ": " + cmd)
            stdout = None
            try:
                p = subprocess.Popen (cmd, shell=True,
                                      stdin=file("/dev/null"),
                                      stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE)
                (stdout, stderr) = p.communicate ()
            except:
                # Problem executing command.
                pass

            if stdout != None:
                mm = re.sub("^\s*\S+\s+\S+\s+\"", "", stdout)
                mm = re.sub("\"\s+.*$", "", mm)
                if mm and mm != "": device.make_and_model = mm
        # Extract make and model and create a pseudo device ID, so
        # that a PPD/driver can be assigned to the device
        make_and_model = None
        if len (device.make_and_model) > 7:
            make_and_model = device.make_and_model
        elif len (device.info) > 7:
            make_and_model = device.info
            make_and_model = re.sub("\s*(\(|\d+\.\d+\.\d+\.\d+).*$", "", make_and_model)
        if make_and_model and not device.id:
            mk = None
            md = None
            (mk, md) = cupshelpers.ppds.ppdMakeModelSplit (make_and_model)
            device.id = "MFG:" + mk + ";MDL:" + md + ";DES:" + mk + " " + md + ";"
            device.id_dict = cupshelpers.parseDeviceID (device.id)
        # Check whether the device is supported by HPLIP and replace
        # its URI by an HPLIP URI
        if host:
            hplipuri = self.get_hplip_uri_for_network_printer(host, "print")
            if hplipuri:
                device.uri = hplipuri
                s = hplipuri.find ("/usb/")
                if s == -1: s = hplipuri.find ("/par/")
                if s == -1: s = hplipuri.find ("/net/")
                if s != -1:
                    s += 5
                    e = hplipuri[s:].find ("?")
                    if e == -1: e = len (hplipuri)
                    mdl = hplipuri[s:s+e].replace ("_", " ")
                    if mdl.startswith ("hp ") or mdl.startswith ("HP "):
                        mdl = mdl[3:]
                        device.make_and_model = "HP " + mdl
                        device.id = "MFG:HP;MDL:" + mdl + ";DES:HP " + mdl + ";"
                        device.id_dict = cupshelpers.parseDeviceID (device.id)
        # Return the host name/IP for further actions
        return host

    def fillDeviceTab(self, current_uri=None):
        try:
            devices = self.fetchDevices()
        except cups.IPPError, (e, msg):
            self.show_IPP_Error(e, msg)
            devices = {}
        except:
            nonfatalException()
            devices = {}

        if current_uri:
            if devices.has_key (current_uri):
                current = devices.pop(current_uri)
                current.info += _(" (Current)")
            else:
                current = cupshelpers.Device (current_uri)
                current.info = "Current device"

        devices = devices.values()

        for device in devices:
            if device.type == "socket":
                # Remove default port to more easily find duplicate URIs
                device.uri = device.uri.replace (":9100", "")
            try:
                ## XXX This needs to be moved to *after* the device is
                # selected.  Looping through all the network printers like
                # this is far too slow.
                if False and device.type in ("socket", "lpd", "ipp", "bluetooth"):
                    host = self.getNetworkPrinterMakeModel(device)
                    faxuri = None
                    if host:
                        faxuri = self.get_hplip_uri_for_network_printer(host,
                                                                        "fax")
                    if faxuri:
                        fax_id_dict = \
                            self.get_hpfax_device_id(faxuri)
                        devices.append(cupshelpers.Device(faxuri,
                              **{'device-class' : "direct",
                                 'device-info' : device.info + " HP Fax HPLIP",
                                 'device-device-make-and-model' : \
                                     fax_id_dict["MFG"] + " " + \
                                     fax_id_dict["MDL"],
                                 'device-id' : \
                                     "MFG:" + fax_id_dict["MFG"] + \
                                     ";MDL:" + fax_id_dict["MDL"] + \
                                     ";DES:" + \
                                     fax_id_dict["DES"] + ";"}))
                    if device.uri.startswith ("hp:"):
                        device.type = "hp" 
                        device.info += (" HPLIP")
            except:
                nonfatalException ()
        # Mark duplicate URIs for deletion
        for i in range (len (devices) - 1):
            for j in range (i + 1, len (devices)):
                device1 = devices[i]
                device2 = devices[j]
                if device1.uri == "delete" or device2.uri == "delete":
                    continue
                if device1.uri == device2.uri:
                    # Keep the one with the longer (better) device ID
                    if (not device1.id):
                        device1.uri = "delete"
                    elif (not device2.id):
                        device2.uri = "delete"
                    elif (len (device1.id) < len (device2.id)):
                        device1.uri = "delete"
                    else:
                        device2.uri = "delete"
        devices = filter(lambda x: x.uri not in ("hp:/no_device_found",
                                                 "hpfax:/no_device_found",
                                                 "hp", "hpfax",
                                                 "hal", "beh",
                                                 "scsi", "http", "delete"),
                         devices)
        self.devices = []
        for device in devices:
            physicaldevice = PhysicalDevice (device)
            try:
                i = self.devices.index (physicaldevice)
                self.devices[i].add_device (device)
            except ValueError:
                self.devices.append (physicaldevice)

        self.devices.sort()
        other = cupshelpers.Device('', **{'device-info' :_("Other")})
        self.devices.append (PhysicalDevice (other))
        device_select_path = 0
        connection_select_path = 0
        if current_uri:
            current_device = PhysicalDevice (current)
            try:
                i = self.devices.index (current_device)
                self.devices[i].add_device (current)
                device_select_path = i
                devs = self.devices[i].get_devices ()
                for i in xrange (len (devs)):
                    if devs[i].uri == current_uri:
                        connection_select_path = i
                        break
            except ValueError:
                self.devices.insert(0, current_device)

        model = self.tvNPDevices.get_model()
        model.clear()

        for device in self.devices:
            model.append((device.get_info (),))
            
        column = self.tvNPDevices.get_column (0)
        self.tvNPDevices.set_cursor (device_select_path, column)
        column = self.tvNPDeviceURIs.get_column (0)
        self.tvNPDeviceURIs.set_cursor (connection_select_path, column)

    def on_entNPTDevice_changed(self, entry):
        self.setNPButtons()

    ## SMB browsing

    def browse_smb_hosts(self):
        """Initialise the SMB tree store."""
        store = self.smb_store
        store.clear ()
        self.busy(self.SMBBrowseDialog)
        if pysmb.USE_OLD_CODE:
            store.append(None, (_('Scanning...'), '', None, None))
            while gtk.events_pending ():
                gtk.main_iteration ()
            domains = pysmb.get_domain_list ()
            store.clear ()
            for domain in domains.keys ():
                d = domains[domain]
                iter = store.append (None)
                if iter:
                    dummy = store.append (iter)
                store.set_value (iter, 0, d['DOMAIN'])
                store.set_value (iter, 2, d)
        else:
            class X:
                pass
            dummy = X()
            dummy.smbc_type = pysmb.smbc.PRINTER_SHARE
            dummy.name = _('Scanning...')
            dummy.comment = ''
            store.append(None, [dummy])
            while gtk.events_pending ():
                gtk.main_iteration ()

            debug = 0
            if get_debugging ():
                debug = 10
            smbc_auth = pysmb.AuthContext (self.SMBBrowseDialog)
            ctx = pysmb.smbc.Context (debug=debug,
                                      auth_fn=smbc_auth.callback)
            entries = None
            try:
                while smbc_auth.perform_authentication () > 0:
                    try:
                        entries = ctx.opendir ("smb://").getdents ()
                    except Exception, e:
                        smbc_auth.failed (e)
            except RuntimeError, (e, s):
                if e != errno.ENOENT:
                    debugprint ("Runtime error: %s" % repr ((e, s)))
            except:
                nonfatalException ()

            store.clear ()
            if entries:
                for entry in entries:
                    if entry.smbc_type in [pysmb.smbc.WORKGROUP,
                                           pysmb.smbc.SERVER]:
                        iter = store.append (None, [entry])
                        i = store.append (iter)

        specified_uri = SMBURI (uri=self.entSMBURI.get_text ())
        (group, host, share, user, password) = specified_uri.separate ()
        if len (host) > 0 and not pysmb.USE_OLD_CODE:
            # The user has specified a server before clicking Browse.
            # Append the server as a top-level entry.
            class FakeEntry:
                pass
            toplevel = FakeEntry ()
            toplevel.smbc_type = pysmb.smbc.SERVER
            toplevel.name = host
            toplevel.comment = ''
            iter = store.append (None, [toplevel])
            i = store.append (iter)

            # Now expand it.
            path = store.get_path (iter)
            self.tvSMBBrowser.expand_row (path, 0)

        self.ready(self.SMBBrowseDialog)

        if store.get_iter_first () == None:
            self.SMBBrowseDialog.hide ()
            show_info_dialog (_("No Print Shares"),
                              _("There were no print shares found.  "
                                "Please check that the Samba service is "
                                "marked as trusted in your firewall "
                                "configuration.") + '\n\n' +
                              TEXT_start_firewall_tool,
                              parent=self.NewPrinterWindow)

    def smb_select_function (self, path):
        """Don't allow this path to be selected unless it is a leaf."""
        iter = self.smb_store.get_iter (path)
        return not self.smb_store.iter_has_child (iter)

    def smbbrowser_cell_share (self, column, cell, model, iter):
        entry = model.get_value (iter, 0)
        share = ''
        if entry != None:
            share = entry.name
        cell.set_property ('text', share)

    def smbbrowser_cell_comment (self, column, cell, model, iter):
        entry = model.get_value (iter, 0)
        comment = ''
        if entry != None:
            comment = entry.comment
        cell.set_property ('text', comment)

    def on_tvSMBBrowser_row_activated (self, view, path, column):
        """Handle double-clicks in the SMB tree view."""
        store = self.smb_store
        iter = store.get_iter (path)
        is_share = False
        if (pysmb.USE_OLD_CODE and store.iter_depth (iter) == 2):
            is_share = True
        elif not pysmb.USE_OLD_CODE:
            entry = store.get_value (iter, 0)
            if entry and entry.smbc_type == pysmb.smbc.PRINTER_SHARE:
                is_share = True

        if is_share:
            # This is a share, not a host.
            self.btnSMBBrowseOk.clicked ()
            return

        if view.row_expanded (path):
            view.collapse_row (path)
        else:
            self.on_tvSMBBrowser_row_expanded (view, iter, path)

    def on_tvSMBBrowser_row_expanded (self, view, iter, path):
        """Handler for expanding a row in the SMB tree view."""
        if pysmb.USE_OLD_CODE:
            store = self.smb_store
            if len (path) == 2:
                # Click on host, look for shares
                try:
                    if self.expanding_row:
                        return
                except:
                    self.expanding_row = 1

                host = store.get_value (iter, 3)
                if host:
                    self.busy (self.NewPrinterWindow)
                    printers = pysmb.get_printer_list (host)
                    while store.iter_has_child (iter):
                        i = store.iter_nth_child (iter, 0)
                        store.remove (i)
                    for printer in printers.keys():
                        i = store.append (iter)
                        store.set_value (i, 0, printer)
                        store.set_value (i, 1, printers[printer])
                    self.ready (self.NewPrinterWindow)

                view.expand_row (path, 1)
                del self.expanding_row
            else:
                # Click on domain, look for hosts
                try:
                    if self.expanding_row:
                        return
                except:
                    self.expanding_row = 1

                domain = store.get_value (iter, 2)
                if domain:
                    self.busy (self.NewPrinterWindow)
                    hosts = pysmb.get_host_list_from_domain (domain['DOMAIN'])
                    if len(hosts) <= 0:
                        hosts = pysmb.get_host_list (domain['IP'])
                    while store.iter_has_child (iter):
                        i = store.iter_nth_child (iter, 0)
                        store.remove (i)
                    i = None
                    for host in hosts.keys():
                        h = hosts[host]
                        i = store.append (iter)
                        if i:
                            dummy = store.append (i)
                        store.set_value (i, 0, h['NAME'])
                        store.set_value (i, 3, h)
                    self.ready (self.NewPrinterWindow)
                view.expand_row (path, 0)
                del self.expanding_row
        else:
            model = view.get_model ()
            entry = model.get_value (iter, 0)
            if entry == None:
                return

            if entry.smbc_type == pysmb.smbc.WORKGROUP:
                # Workgroup.
                # Be careful though: if there is a server with the
                # same name as the workgroup we will get a list of its
                # shares, not the workgroup's servers.
                try:
                    if self.expanding_row:
                        return
                except:
                    self.expanding_row = 1

                self.busy (self.SMBBrowseDialog)
                uri = "smb://%s/" % entry.name
                debug = 0
                if get_debugging ():
                    debug = 10
                smbc_auth = pysmb.AuthContext (self.SMBBrowseDialog)
                ctx = pysmb.smbc.Context (debug=debug,
                                          auth_fn=smbc_auth.callback)
                entries = []
                try:
                    while smbc_auth.perform_authentication () > 0:
                        try:
                            entries = ctx.opendir (uri).getdents ()
                        except Exception, e:
                            smbc_auth.failed (e)
                except RuntimeError, (e, s):
                    if e != errno.ENOENT:
                        debugprint ("Runtime error: %s" % repr ((e, s)))
                except:
                    nonfatalException()

                while model.iter_has_child (iter):
                    i = model.iter_nth_child (iter, 0)
                    model.remove (i)

                for entry in entries:
                    if entry.smbc_type in [pysmb.smbc.SERVER,
                                           pysmb.smbc.PRINTER_SHARE]:
                        i = model.append (iter, [entry])
                    if entry.smbc_type == pysmb.smbc.SERVER:
                        n = model.append (i)

                view.expand_row (path, 0)
                del self.expanding_row
                self.ready (self.SMBBrowseDialog)

            elif entry.smbc_type == pysmb.smbc.SERVER:
                # Server
                try:
                    if self.expanding_row:
                        return
                except:
                    self.expanding_row = 1

                self.busy (self.SMBBrowseDialog)
                uri = "smb://%s/" % entry.name
                debug = 0
                if get_debugging ():
                    debug = 10
                smbc_auth = pysmb.AuthContext (self.SMBBrowseDialog)
                ctx = pysmb.smbc.Context (debug=debug,
                                          auth_fn=smbc_auth.callback)
                shares = []
                try:
                    while smbc_auth.perform_authentication () > 0:
                        try:
                            shares = ctx.opendir (uri).getdents ()
                        except Exception, e:
                            smbc_auth.failed (e)
                except RuntimeError, (e, s):
                    if e != errno.EACCES and e != errno.EPERM:
                        debugprint ("Runtime error: %s" % repr ((e, s)))
                except:
                    nonfatalException()

                while model.iter_has_child (iter):
                    i = model.iter_nth_child (iter, 0)
                    model.remove (i)

                for share in shares:
                    if share.smbc_type == pysmb.smbc.PRINTER_SHARE:
                        i = model.append (iter, [share])
                        debugprint (repr (share))

                view.expand_row (path, 0)
                del self.expanding_row
                self.ready (self.SMBBrowseDialog)

    def on_entSMBURI_changed (self, ent):
        uri = ent.get_text ()
        (group, host, share, user, password) = SMBURI (uri=uri).separate ()
        if user:
            self.entSMBUsername.set_text (user)
        if password:
            self.entSMBPassword.set_text (password)
        if user or password:
            uri = SMBURI (group=group, host=host, share=share).get_uri ()
            ent.set_text(uri)
            self.rbtnSMBAuthSet.set_active(True)
        elif self.entSMBUsername.get_text () == '':
            self.rbtnSMBAuthPrompt.set_active(True)

        self.btnSMBVerify.set_sensitive(bool(uri))
        self.setNPButtons ()

    def on_tvSMBBrowser_cursor_changed(self, widget):
        store, iter = self.tvSMBBrowser.get_selection().get_selected()
        is_share = False
        if iter:
            if pysmb.USE_OLD_CODE:
                is_share = store.iter_depth (iter)
            else:
                entry = store.get_value (iter, 0)
                if entry:
                    is_share = entry.smbc_type == pysmb.smbc.PRINTER_SHARE

        self.btnSMBBrowseOk.set_sensitive(iter != None and is_share)

    def on_btnSMBBrowse_clicked(self, button):
        self.btnSMBBrowseOk.set_sensitive(False)
        self.SMBBrowseDialog.show()
        self.browse_smb_hosts()

    def on_btnSMBBrowseOk_clicked(self, button):
        store, iter = self.tvSMBBrowser.get_selection().get_selected()
        is_share = False
        if iter:
            if pysmb.USE_OLD_CODE:
                is_share = store.iter_depth (iter) == 2
            else:
                entry = store.get_value (iter, 0)
                if entry:
                    is_share = entry.smbc_type == pysmb.smbc.PRINTER_SHARE

        if not iter or not is_share:
            self.SMBBrowseDialog.hide()
            return

        parent_iter = store.iter_parent (iter)
        domain_iter = store.iter_parent (parent_iter)
        share = store.get_value (iter, 0)
        host = store.get_value (parent_iter, 0)
        if pysmb.USE_OLD_CODE:
            group = store.get_value (domain_iter, 0)
            uri = SMBURI (group=group, host=host, share=share).get_uri ()
        else:
            if domain_iter:
                group = store.get_value (domain_iter, 0).name
            else:
                group = ''
            uri = SMBURI (group=group,
                          host=host.name,
                          share=share.name).get_uri ()

        self.entSMBUsername.set_text ('')
        self.entSMBPassword.set_text ('')
        self.entSMBURI.set_text (uri)

        self.SMBBrowseDialog.hide()

    def on_btnSMBBrowseCancel_clicked(self, widget, *args):
        self.SMBBrowseDialog.hide()

    def on_btnSMBBrowseRefresh_clicked(self, button):
        self.browse_smb_hosts()

    def on_rbtnSMBAuthSet_toggled(self, widget):
        self.tblSMBAuth.set_sensitive(widget.get_active())

    def on_btnSMBVerify_clicked(self, button):
        uri = self.entSMBURI.get_text ()
        (group, host, share, u, p) = SMBURI (uri=uri).separate ()
        user = ''
        passwd = ''
        reason = None
        auth_set = self.rbtnSMBAuthSet.get_active()
        if auth_set:
            user = self.entSMBUsername.get_text ()
            passwd = self.entSMBPassword.get_text ()

        if pysmb.USE_OLD_CODE:
            accessible = pysmb.printer_share_accessible ("//%s/%s" %
                                                         (host, share),
                                                         group = group,
                                                         user = user,
                                                         passwd = passwd)
        else:
            accessible = False
            self.busy ()
            try:
                debug = 0
                if get_debugging ():
                    debug = 10

                if auth_set:
                    # No prompting.
                    def do_auth (svr, shr, wg, un, pw):
                        return (group, user, passwd)
                    ctx = pysmb.smbc.Context (debug=debug, auth_fn=do_auth)
                    f = ctx.open ("smb://%s/%s" % (host, share),
                                  os.O_RDWR, 0777)
                    accessible = True
                else:
                    # May need to prompt.
                    smbc_auth = pysmb.AuthContext (self.NewPrinterWindow,
                                                        workgroup=group,
                                                        user=user,
                                                        passwd=passwd)
                    ctx = pysmb.smbc.Context (debug=debug,
                                              auth_fn=smbc_auth.callback)
                    while smbc_auth.perform_authentication () > 0:
                        try:
                            f = ctx.open ("smb://%s/%s" % (host, share),
                                          os.O_RDWR, 0777)
                            accessible = True
                        except Exception, e:
                            smbc_auth.failed (e)
            except RuntimeError, (e, s):
                debugprint ("Error accessing share: %s" % repr ((e, s)))
                reason = s
            except:
                nonfatalException()
            self.ready ()

        if accessible:
            show_info_dialog (_("Print Share Verified"),
                              _("This print share is accessible."),
                              parent=self.NewPrinterWindow)
            return

        text = _("This print share is not accessible.")
        if reason:
            text = reason
        show_error_dialog (_("Print Share Inaccessible"), text,
                           parent=self.NewPrinterWindow)

    ### IPP Browsing
    def update_IPP_URI_label(self):
        hostname = self.entNPTIPPHostname.get_text ()
        queue = self.entNPTIPPQueuename.get_text ()
        valid = len (hostname) > 0 and queue != '/printers/'

        if valid:
            uri = "ipp://%s%s" % (hostname, queue)
            self.lblIPPURI.set_text (uri)
            self.lblIPPURI.show ()
            self.entNPTIPPQueuename.show ()
        else:
            self.lblIPPURI.hide ()

        self.btnIPPVerify.set_sensitive (valid)
        self.setNPButtons ()

    def on_entNPTIPPHostname_changed(self, ent):
        valid = len (ent.get_text ()) > 0
        self.btnIPPFindQueue.set_sensitive (valid)
        self.update_IPP_URI_label ()

    def on_entNPTIPPQueuename_changed(self, ent):
        self.update_IPP_URI_label ()

    def on_btnIPPFindQueue_clicked(self, button):
        self.btnIPPBrowseOk.set_sensitive(False)
        self.IPPBrowseDialog.show()
        self.browse_ipp_queues()

    def on_btnIPPVerify_clicked(self, button):
        uri = self.lblIPPURI.get_text ()
        match = re.match ("(ipp|https?)://([^/]+)(.*)/([^/]*)", uri)
        verified = False
        if match:
            oldserver = cups.getServer ()
            try:
                try:
                    c = cups.Connection (host=match.group (2))
                except TypeError:
                    # host parameter requires pycups >= 1.9.40.
                    cups.setServer (match.group (2))
                    c = cups.Connection ()

                try:
                    attributes = c.getPrinterAttributes (uri = uri)
                except TypeError: # uri keyword introduced in pycups 1.9.32
                    debugprint ("Fetching printer attributes by name")
                    attributes = c.getPrinterAttributes (match.group (4))
                verified = True
            except cups.IPPError, (e, msg):
                debugprint ("Failed to get attributes: %s (%d)" % (msg, e))
            except:
                nonfatalException ()
            cups.setServer (oldserver)
        else:
            debugprint (uri)

        if verified:
            show_info_dialog (_("Print Share Verified"),
                              _("This print share is accessible."),
                              parent=self.NewPrinterWindow)
        else:
            show_error_dialog (_("Inaccessible"),
                               _("This print share is not accessible."),
                               self.NewPrinterWindow)

    def browse_ipp_queues(self):
        if not self.ipp_lock.acquire(0):
            return
        thread.start_new_thread(self.browse_ipp_queues_thread, ())

    def browse_ipp_queues_thread(self):
        gtk.gdk.threads_enter()
        try:
            store = self.ipp_store
            store.clear ()
            store.append(None, (_('Scanning...'), '', None))
            try:
                self.busy(self.IPPBrowseDialog)
            except:
                nonfatalException()

            host = self.entNPTIPPHostname.get_text()
        except:
            nonfatalException()
        gtk.gdk.threads_leave()

        oldserver = cups.getServer ()
        printers = classes = {}
        failed = False
        try:
            try:
                c = cups.Connection (host=host)
            except TypeError:
                # host parameter requires pycups >= 1.9.40.
                cups.setServer (host)
                c = cups.Connection()

            printers = c.getPrinters ()
            del c
        except cups.IPPError, (e, m):
            debugprint ("IPP browser: %s" % m)
            failed = True
        except:
            nonfatalException()
            failed = True
        cups.setServer (oldserver)

        gtk.gdk.threads_enter()
        try:
            store.clear ()
            for printer, dict in printers.iteritems ():
                iter = store.append (None)
                store.set_value (iter, 0, printer)
                store.set_value (iter, 1, dict.get ('printer-location', ''))
                store.set_value (iter, 2, dict)

            if len (printers) + len (classes) == 0:
                # Display 'No queues' dialog
                if failed:
                    title = _("Not possible")
                    text = (_("It is not possible to obtain a list of queues "
                              "from `%s'.") % host + '\n\n' +
                            _("Obtaining a list of queues is a CUPS extension "
                              "to IPP.  Network printers do not support it."))
                else:
                    title = _("No queues")
                    text = _("There are no queues available.")

                self.IPPBrowseDialog.hide ()
                show_error_dialog (title, text, self.NewPrinterWindow)

            try:
                self.ready(self.IPPBrowseDialog)
            except:
                nonfatalException()

            self.ipp_lock.release()
        except:
            nonfatalException()
        gtk.gdk.threads_leave()

    def on_tvIPPBrowser_cursor_changed(self, widget):
        self.btnIPPBrowseOk.set_sensitive(True)

    def on_btnIPPBrowseOk_clicked(self, button):
        store, iter = self.tvIPPBrowser.get_selection().get_selected()
        self.IPPBrowseDialog.hide()
        queue = store.get_value (iter, 0)
        dict = store.get_value (iter, 2)
        self.entNPTIPPQueuename.set_text (queue)
        self.entNPTIPPQueuename.show()
        uri = dict.get('printer-uri-supported', 'ipp')
        match = re.match ("(ipp|https?)://([^/]+)(.*)", uri)
        if match:
            self.entNPTIPPHostname.set_text (match.group (2))
            self.entNPTIPPQueuename.set_text (match.group (3))

        self.lblIPPURI.set_text (uri)
        self.lblIPPURI.show()
        self.setNPButtons()

    def on_btnIPPBrowseCancel_clicked(self, widget, *args):
        self.IPPBrowseDialog.hide()

    def on_btnIPPBrowseRefresh_clicked(self, button):
        self.browse_ipp_queues()

    def on_expNPDeviceURIs_expanded (self, widget, UNUSED):
        # When the expanded is not expanded we want its packing to be
        # 'expand = false' so that it aligns at the bottom (it packs
        # to the end of its vbox).  But when it is expanded we'd like
        # it to expand with the window.
        #
        # Adjust its 'expand' packing state depending on whether the
        # widget is expanded.

        parent = widget.get_parent ()
        (expand, fill,
         padding, pack_type) = parent.query_child_packing (widget)
        expand = widget.get_expanded ()
        parent.set_child_packing (widget, expand, fill,
                                  padding, pack_type)

    def on_tvNPDevices_cursor_changed(self, widget):
        model, iter = widget.get_selection ().get_selected()
        path = model.get_path (iter)
        physicaldevice = self.devices[path[0]]
        model = gtk.ListStore (str,                    # printer-info
                               gobject.TYPE_PYOBJECT)  # cupshelpers.Device
        self.tvNPDeviceURIs.set_model (model)
        n = 0
        for device in physicaldevice.get_devices ():
            model.append ((device.info, device))
            n += 1
        column = self.tvNPDeviceURIs.get_column (0)
        self.tvNPDeviceURIs.set_cursor (0, column)
        if n > 1:
            self.expNPDeviceURIs.show_all ()
        else:
            self.expNPDeviceURIs.hide ()

    def on_tvNPDeviceURIs_cursor_changed(self, widget):
        model, iter = widget.get_selection().get_selected()
        device = model.get_value(iter, 1)
        self.device = device
        self.lblNPDeviceDescription.set_text ('')
        page = self.new_printer_device_tabs.get(device.type, 1)
        self.ntbkNPType.set_current_page(page)

        location = ''
        type = device.type
        url = device.uri.split(":", 1)[-1]
        if page == 0:
            # This is the "no options" page, with just a label to describe
            # the selected device.
            if device.type == "parallel":
                text = _("A printer connected to the parallel port.")
            elif device.type == "usb":
                text = _("A printer connected to a USB port.")
            elif device.type == "hp":
                text = _("HPLIP software driving a printer, "
                         "or the printer function of a multi-function device.")
            elif device.type == "hpfax":
                text = _("HPLIP software driving a fax machine, "
                         "or the fax function of a multi-function device.")
            elif device.type == "hal":
                text = _("Local printer detected by the "
                         "Hardware Abstraction Layer (HAL).")
            else:
                text = device.uri

            self.lblNPDeviceDescription.set_text (text)
        elif device.type=="socket":
            (scheme, rest) = urllib.splittype (device.uri)
            host = ''
            port = 9100
            debugprint ("socket: scheme is %s" % scheme)
            if scheme == "socket":
                (hostport, rest) = urllib.splithost (rest)
                (host, port) = urllib.splitnport (hostport, defport=port)
                debugprint ("socket: host is %s, port is %s" % (host,
                                                                repr (port)))
                location = host
            self.entNPTDirectJetHostname.set_text (host)
            self.entNPTDirectJetPort.set_text (str (port))
        elif device.type=="serial":
            if not device.is_class:
                options = device.uri.split("?")[1]
                options = options.split("+")
                option_dict = {}
                for option in options:
                    name, value = option.split("=")
                    option_dict[name] = value
                    
                for widget, name, optionvalues in (
                    (self.cmbNPTSerialBaud, "baud", None),
                    (self.cmbNPTSerialBits, "bits", None),
                    (self.cmbNPTSerialParity, "parity",
                     ["none", "odd", "even"]),
                    (self.cmbNPTSerialFlow, "flow",
                     ["none", "soft", "hard", "hard"])):
                    if option_dict.has_key(name): # option given in URI?
                        if optionvalues is None: # use text in widget
                            model = widget.get_model()
                            iter = model.get_iter_first()
                            nr = 0
                            while iter:
                                value = model.get(iter,0)[0]
                                if value == option_dict[name]:
                                    widget.set_active(nr)
                                    break
                                iter = model.iter_next(iter)
                                nr += 1
                        else: # use optionvalues
                            nr = optionvalues.index(
                                option_dict[name])
                            widget.set_active(nr+1) # compensate "Default"
                    else:
                        widget.set_active(0)
                                            
        # XXX FILL TABS FOR VALID DEVICE URIs
        elif device.type in ("ipp", "http"):
            if (device.uri.startswith ("ipp:") or
                device.uri.startswith ("http:")):
                match = re.match ("(ipp|https?)://([^/]+)(.*)", device.uri)
                if match:
                    server = match.group (2)
                    printer = match.group (3)
                else:
                    server = ""
                    printer = ""

                self.entNPTIPPHostname.set_text(server)
                self.entNPTIPPQueuename.set_text(printer)
                self.lblIPPURI.set_text(device.uri)
                self.lblIPPURI.show()
                self.entNPTIPPQueuename.show()
                location = server
            else:
                self.entNPTIPPHostname.set_text('')
                self.entNPTIPPQueuename.set_text('/printers/')
                self.entNPTIPPQueuename.show()
                self.lblIPPURI.hide()
        elif device.type=="lpd":
            if device.uri.startswith ("lpd"):
                host = device.uri[6:]
                i = host.find ("/")
                if i != -1:
                    printer = host[i + 1:]
                    host = host[:i]
                else:
                    printer = ""
                self.cmbentNPTLpdHost.child.set_text (host)
                self.cmbentNPTLpdQueue.child.set_text (printer)
                location = host
        elif device.uri == "lpd":
            pass
        elif device.uri == "smb":
            self.entSMBURI.set_text('')
            self.btnSMBVerify.set_sensitive(False)
        elif device.type == "smb":
            self.entSMBUsername.set_text ('')
            self.entSMBPassword.set_text ('')
            self.entSMBURI.set_text(device.uri[6:])
            self.btnSMBVerify.set_sensitive(True)
        else:
            self.entNPTDevice.set_text(device.uri)

        try:
            if len (location) == 0 and self.device.device_class == "direct":
                # Set location to the name of this host.
                u = os.uname ()
                location = u[1]

            # Pre-fill location field.
            self.entNPLocation.set_text (location)
        except:
            nonfatalException ()

        self.setNPButtons()

    def on_btnNPTLpdProbe_clicked(self, button):
        # read hostname, probe, fill printer names
        hostname = self.cmbentNPTLpdHost.get_active_text()
        server = probe_printer.LpdServer(hostname)
        printers = server.probe()
        model = self.cmbentNPTLpdQueue.get_model()
        model.clear()
        for printer in printers:
            self.cmbentNPTLpdQueue.append_text(printer)
        if printers:
            self.cmbentNPTLpdQueue.set_active(0)

    def getDeviceURI(self):
        type = self.device.type
        if type == "socket": # DirectJet
            host = self.entNPTDirectJetHostname.get_text()
            port = self.entNPTDirectJetPort.get_text()
            device = "socket://" + host
            if host and port:
                device = device + ':' + port
        elif type in ("http", "ipp"): # IPP
            if self.lblIPPURI.get_property('visible'):
                device = self.lblIPPURI.get_text()
            else:
                device = "ipp"
        elif type == "lpd": # LPD
            host = self.cmbentNPTLpdHost.get_active_text()
            printer = self.cmbentNPTLpdQueue.get_active_text()
            device = "lpd://" + host
            if printer:
                device = device + "/" + printer
        elif type == "parallel": # Parallel
            device = self.device.uri
        elif type == "scsi": # SCSII
            device = ""
        elif type == "serial": # Serial
            options = []
            for widget, name, optionvalues in (
                (self.cmbNPTSerialBaud, "baud", None),
                (self.cmbNPTSerialBits, "bits", None),
                (self.cmbNPTSerialParity, "parity",
                 ("none", "odd", "even")),
                (self.cmbNPTSerialFlow, "flow",
                 ("none", "soft", "hard", "hard"))):
                nr = widget.get_active()
                if nr:
                    if optionvalues is not None:
                        option = optionvalues[nr-1]
                    else:
                        option = widget.get_active_text()
                    options.append(name + "=" + option)
            options = "+".join(options)
            device =  self.device.uri.split("?")[0] #"serial:/dev/ttyS%s" 
            if options:
                device = device + "?" + options
        elif type == "smb":
            uri = self.entSMBURI.get_text ()
            (group, host, share, u, p) = SMBURI (uri=uri).separate ()
            user = ''
            password = ''
            if self.rbtnSMBAuthSet.get_active ():
                user = self.entSMBUsername.get_text ()
                password = self.entSMBPassword.get_text ()
            uri = SMBURI (group=group, host=host, share=share,
                          user=user, password=password).get_uri ()
            device = "smb://" + uri
        elif not self.device.is_class:
            device = self.device.uri
        else:
            device = self.entNPTDevice.get_text()
        return device
    
    # PPD

    def on_rbtnNPFoomatic_toggled(self, widget):
        rbtn1 = self.rbtnNPFoomatic.get_active()
        rbtn2 = self.rbtnNPPPD.get_active()
        rbtn3 = self.rbtnNPDownloadableDriverSearch.get_active()
        self.tvNPMakes.set_sensitive(rbtn1)
        self.filechooserPPD.set_sensitive(rbtn2)

        if rbtn1:
            page = 0
        if rbtn2:
            page = 1
        if rbtn3:
            page = 2
        self.ntbkPPDSource.set_current_page (page)

        if not rbtn3 and self.openprinting_query_handle:
            # Need to cancel a search in progress.
            self.openprinting.cancelOperation (self.openprinting_query_handle)
            self.openprinting_query_handle = None
            self.btnNPDownloadableDriverSearch_label.set_text (_("Search"))
            # Clear printer list.
            model = gtk.ListStore (str, str)
            combobox = self.cmbNPDownloadableDriverFoundPrinters
            combobox.set_model (model)
            combobox.set_sensitive (False)

        for widget in [self.entNPDownloadableDriverSearch,
                       self.cmbNPDownloadableDriverFoundPrinters]:
            widget.set_sensitive(rbtn3)
        self.btnNPDownloadableDriverSearch.\
            set_sensitive (rbtn3 and (self.openprinting_query_handle == None))

        self.setNPButtons()

    def on_filechooserPPD_selection_changed(self, widget):
        self.setNPButtons()

    def on_btnNPDownloadableDriverSearch_clicked(self, widget):
        if self.openprinting_query_handle != None:
            self.openprinting.cancelOperation (self.openprinting_query_handle)
            self.openprinting_query_handle = None

        widget.set_sensitive (False)
        label = self.btnNPDownloadableDriverSearch_label
        label.set_text (_("Searching"))
        searchterm = self.entNPDownloadableDriverSearch.get_text ()
        self.openprinting_query_handle = \
            self.openprinting.searchPrinters (searchterm,
                                              self.openprinting_printers_found)
        self.cmbNPDownloadableDriverFoundPrinters.set_sensitive (False)

    def openprinting_printers_found (self, status, user_data, printers):
        self.openprinting_query_handle = None
        button = self.btnNPDownloadableDriverSearch
        label = self.btnNPDownloadableDriverSearch_label
        gtk.gdk.threads_enter ()
        try:
            label.set_text (_("Search"))
            button.set_sensitive (True)
            if status != 0:
                # Should report error.
                print printers
                print traceback.extract_tb(printers[2], limit=None)
                gtk.gdk.threads_leave ()
                return

            model = gtk.ListStore (str, str)
            if len (printers) != 1:
                if len (printers) > 1:
                    first = _("-- Select from search results --")
                else:
                    first = _("-- No matches found --")

                iter = model.append (None)
                model.set_value (iter, 0, first)
                model.set_value (iter, 1, None)

            sorted_list = []
            for id, name in printers.iteritems ():
                sorted_list.append ((id, name))

            sorted_list.sort (lambda x, y: cups.modelSort (x[1], y[1]))
            sought = self.entNPDownloadableDriverSearch.get_text ().lower ()
            select_index = 0
            for id, name in sorted_list:
                iter = model.append (None)
                model.set_value (iter, 0, name)
                model.set_value (iter, 1, id)
                if name.lower () == sought:
                    select_index = model.get_path (iter)[0]
            combobox = self.cmbNPDownloadableDriverFoundPrinters
            combobox.set_model (model)
            combobox.set_active (select_index)
            combobox.set_sensitive (True)
            self.setNPButtons ()
        except:
            nonfatalException()
        gtk.gdk.threads_leave ()

    def on_cmbNPDownloadableDriverFoundPrinters_changed(self, widget):
        self.setNPButtons ()

        if self.openprinting_query_handle != None:
            self.openprinting.cancelOperation (self.openprinting_query_handle)
            self.openprinting_query_handle = None
            self.drivers_lock.release()

        model = widget.get_model ()
        iter = widget.get_active_iter ()
        if iter:
            id = model.get_value (iter, 1)
        else:
            id = None

        if id == None:
            return

        # A model has been selected, so start the query to find out
        # which drivers are available.
        debugprint ("Query drivers for %s" % id)
        self.drivers_lock.acquire(0)
        self.openprinting_query_handle = \
            self.openprinting.listDrivers (id,
                                           self.openprinting_drivers_found,
                                           extra_options={'onlyppdfiles':'1'})

    def openprinting_drivers_found (self, status, user_data, drivers):
        if status != 0:
            # Should report error.
            print drivers
            print traceback.extract_tb(drivers[2], limit=None)
            return

        self.openprinting_query_handle = None
        self.downloadable_drivers = drivers
        debugprint ("Drivers query completed: %s" % drivers.keys ())
        self.drivers_lock.release()

    def fillDownloadableDrivers(self):
        # Clear out the properties.
        self.lblNPDownloadableDriverSupplier.set_text ('')
        self.lblNPDownloadableDriverLicense.set_text ('')
        self.lblNPDownloadableDriverDescription.set_text ('')
        self.rbtnNPDownloadLicenseNo.set_active (True)
        self.frmNPDownloadableDriverLicenseTerms.hide ()

        drivers = self.downloadable_drivers
        model = gtk.ListStore (str,                     # driver name
                               gobject.TYPE_PYOBJECT)   # driver data
        recommended_iter = None
        first_iter = None
        for driver in drivers.values ():
            iter = model.append (None)
            if first_iter == None:
                first_iter = iter

            model.set_value (iter, 0, driver['name'])
            model.set_value (iter, 1, driver)

            if driver['recommended']:
                recommended_iter = iter

        if recommended_iter == None:
            recommended_iter = first_iter

        treeview = self.tvNPDownloadableDrivers
        treeview.set_model (model)
        if recommended_iter != None:
            treeview.get_selection ().select_iter (recommended_iter)

    def on_rbtnNPDownloadLicense_toggled(self, widget):
        self.setNPButtons ()

    # PPD from foomatic

    def fillMakeList(self):
        makes = self.ppds.getMakes()
        model = self.tvNPMakes.get_model()
        model.clear()
        found = False
        for make in makes:            
            iter = model.append((make,))
            if make==self.auto_make:
                self.tvNPMakes.get_selection().select_iter(iter)
                path = model.get_path(iter)
                self.tvNPMakes.scroll_to_cell(path, None,
                                              True, 0.5, 0.5)
                found = True

        if not found:
            self.tvNPMakes.get_selection().select_path(0)
            self.tvNPMakes.scroll_to_cell(0, None, True, 0.0, 0.0)
            
        self.on_tvNPMakes_cursor_changed(self.tvNPMakes)

        # Also pre-fill the OpenPrinting.org search box.
        search = ''
        if self.auto_make != None:
            search += self.auto_make
            if self.auto_model != None:
                search += " " + self.auto_model
        self.entNPDownloadableDriverSearch.set_text (search)

    def on_tvNPMakes_cursor_changed(self, tvNPMakes):
        selection = tvNPMakes.get_selection()
        model, iter = selection.get_selected()
        if not iter:
            # Interactively searching.
            path, column = tvNPMakes.get_cursor()
            iter = model.get_iter (path)
        self.NPMake = model.get(iter, 0)[0]
        self.fillModelList()

    def fillModelList(self):
        models = self.ppds.getModels(self.NPMake)
        model = self.tvNPModels.get_model()
        model.clear()
        selected = False
        for pmodel in models:
            iter = model.append((pmodel,))
            if self.NPMake==self.auto_make and pmodel==self.auto_model:
                path = model.get_path(iter)
                self.tvNPModels.scroll_to_cell(path, None,
                                               True, 0.5, 0.5)
                self.tvNPModels.get_selection().select_iter(iter)
                selected = True
        if not selected:
            self.tvNPModels.get_selection().select_path(0)
            self.tvNPModels.scroll_to_cell(0, None, True, 0.0, 0.0)
        self.tvNPModels.columns_autosize()
        self.on_tvNPModels_cursor_changed(self.tvNPModels)
        
    def fillDriverList(self, pmake, pmodel):
        self.NPModel = pmodel
        model = self.tvNPDrivers.get_model()
        model.clear()

        ppds = self.ppds.getInfoFromModel(pmake, pmodel)

        self.NPDrivers = self.ppds.orderPPDNamesByPreference(ppds.keys()) 
        for i in range (len(self.NPDrivers)):
            ppd = ppds[self.NPDrivers[i]]
            driver = ppd["ppd-make-and-model"]
            driver = driver.replace(" (recommended)", "")

            try:
                lpostfix = " [%s]" % ppd["ppd-natural-language"]
                driver += lpostfix
            except KeyError:
                pass

            if i == 0:
                iter = model.append ((driver + _(" (recommended)"),))
                path = model.get_path (iter)
                self.tvNPDrivers.get_selection().select_path(path)
                self.tvNPDrivers.scroll_to_cell(path, None, True, 0.5, 0.0)
            else:
                model.append((driver, ))
        self.tvNPDrivers.columns_autosize()

    def NPDriversTooltips(self, model, path, col):
        drivername = self.NPDrivers[path[0]]
        ppddict = self.ppds.getInfoFromPPDName(drivername)
        markup = ppddict['ppd-make-and-model']
        if (drivername.startswith ("foomatic:")):
            markup += " "
            markup += _("This PPD is generated by foomatic.")
        return markup

    def on_tvNPModels_cursor_changed(self, widget):        
        model, iter = widget.get_selection().get_selected()
        if not iter:
            # Interactively searching.
            path, column = widget.get_cursor()
            iter = model.get_iter (path)
        pmodel = model.get(iter, 0)[0]
        self.fillDriverList(self.NPMake, pmodel)

        self.on_tvNPDrivers_cursor_changed(self.tvNPDrivers)

    def on_tvNPDrivers_cursor_changed(self, widget):
        self.setNPButtons()

    def on_tvNPDownloadableDrivers_cursor_changed(self, widget):
        model, iter = widget.get_selection ().get_selected ()
        if not iter:
            path, column = widget.get_cursor()
            iter = model.get_iter (path)
        driver = model.get_value (iter, 1)
        import pprint
        pprint.pprint (driver)
        self.ntbkNPDownloadableDriverProperties.set_current_page(1)
        supplier = driver.get('supplier', _("OpenPrinting"))
        self.lblNPDownloadableDriverSupplier.set_text (supplier)
        license = driver.get('license', _("Distributable"))
        self.lblNPDownloadableDriverLicense.set_text (license)
        description = driver.get('shortdescription', _("None"))
        self.lblNPDownloadableDriverDescription.set_text (description)
        if not driver['nonfreesoftware'] and not driver['patents']:
            self.rbtnNPDownloadLicenseYes.set_active (True)
            self.frmNPDownloadableDriverLicenseTerms.hide ()
        else:
            self.rbtnNPDownloadLicenseNo.set_active (True)
            self.frmNPDownloadableDriverLicenseTerms.show ()
            terms = driver.get('licensetext', _("Not specified."))
            self.tvNPDownloadableDriverLicense.get_buffer ().set_text (terms)

        self.setNPButtons()

    def getNPPPD(self):
        try:
            if self.rbtnNPFoomatic.get_active():
                model, iter = self.tvNPDrivers.get_selection().get_selected()
                nr = model.get_path(iter)[0]
                ppd = self.NPDrivers[nr]
            elif self.rbtnNPPPD.get_active():
                ppd = cups.PPD(self.filechooserPPD.get_filename())
            else:
                # PPD of the driver downloaded from OpenPrinting XXX
                treeview = self.tvNPDownloadableDrivers
                model, iter = treeview.get_selection ().get_selected ()
                driver = model.get_value (iter, 1)
                if driver.has_key ('ppds'):
                    # Only need to download a PPD.
                    if (len(driver['ppds']) > 0):
                        file_to_download = driver['ppds'][0]
                        debugprint ("ppd file to download [" + file_to_download+ "]")
                        file_to_download = file_to_download.strip()
                        if (len(file_to_download) > 0):
                            ppdurlobj = urllib.urlopen(file_to_download)
                            ppdcontent = ppdurlobj.read()
                            ppdurlobj.close()
                            (tmpfd, ppdname) = tempfile.mkstemp()
                            debugprint(ppdname)
                            ppdfile = os.fdopen(tmpfd, 'w')
                            ppdfile.write(ppdcontent)
                            ppdfile.close()
                            ppd = cups.PPD(ppdname)
                            os.unlink(ppdname)

        except RuntimeError, e:
            debugprint ("RuntimeError: " + str(e))
            if self.rbtnNPFoomatic.get_active():
                # Foomatic database problem of some sort.
                err_title = _('Database error')
                err_text = _("The '%s' driver cannot be "
                             "used with printer '%s %s'.")
                model, iter = (self.tvNPDrivers.get_selection().
                               get_selected())
                nr = model.get_path(iter)[0]
                driver = self.NPDrivers[nr]
                if driver.startswith ("gutenprint"):
                    # This printer references some XML that is not
                    # installed by default.  Point the user at the
                    # package they need to install.
                    err = _("You will need to install the '%s' package "
                            "in order to use this driver.") % \
                            "gutenprint-foomatic"
                else:
                    err = err_text % (driver, self.NPMake, self.NPModel)
            elif self.rbtnNPPPD.get_active():
                # This error came from trying to open the PPD file.
                err_title = _('PPD error')
                filename = self.filechooserPPD.get_filename()
                err = _('Failed to read PPD file.  Possible reason '
                        'follows:') + '\n'
                try:
                    # We want this to be in the current natural language,
                    # so we intentionally don't set LC_ALL=C here.
                    p = subprocess.Popen (['/usr/bin/cupstestppd',
                                           '-rvv', filename],
                                          stdin=file("/dev/null"),
                                          stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE)
                    (stdout, stderr) = p.communicate ()
                    err += stdout
                except:
                    # Problem executing command.
                    raise
            else:
                # Failed to get PPD downloaded from OpenPrinting XXX
                err_title = _('Downloadable drivers')
                err = _("Failed to download PPD.")

            show_error_dialog (err_title, err, self.NewPrinterWindow)
            return None

        debugprint("ppd: " + repr(ppd))
        if isinstance(ppd, str) or isinstance(ppd, unicode):
            try:
                if (ppd != "raw"):
                    f = self.mainapp.cups.getServerPPD(ppd)
                    ppd = cups.PPD(f)
                    os.unlink(f)
            except AttributeError:
                nonfatalException()
                debugprint ("pycups function getServerPPD not available: never mind")
            except RuntimeError:
                nonfatalException()
                debugprint ("libcups from CUPS 1.3 not available: never mind")
            except cups.IPPError:
                nonfatalException()
                debugprint ("CUPS 1.3 server not available: never mind")

        return ppd

    # Installable Options

    def fillNPInstallableOptions(self):
        debugprint ("Examining installable options")
        self.installable_options = False
        self.options = { }

        container = self.vbNPInstallOptions
        for child in container.get_children():
            container.remove(child)

        if not self.ppd:
            l = gtk.Label(_("No Installable Options"))
            container.add(l)
            l.show()
            debugprint ("No PPD so no installable options")
            return

        # build option tabs
        for group in self.ppd.optionGroups:
            if group.name != "InstallableOptions":
                continue
            self.installable_options = True

            table = gtk.Table(1, 3, False)
            table.set_col_spacings(6)
            table.set_row_spacings(6)
            container.add(table)
            rows = 0

            for nr, option in enumerate(group.options):
                if option.keyword == "PageRegion":
                    continue
                rows += 1
                table.resize (rows, 3)
                o = OptionWidget(option, self.ppd, self)
                table.attach(o.conflictIcon, 0, 1, nr, nr+1, 0, 0, 0, 0)

                hbox = gtk.HBox()
                if o.label:
                    a = gtk.Alignment (0.5, 0.5, 1.0, 1.0)
                    a.set_padding (0, 0, 0, 6)
                    a.add (o.label)
                    table.attach(a, 1, 2, nr, nr+1, gtk.FILL, 0, 0, 0)
                    table.attach(hbox, 2, 3, nr, nr+1, gtk.FILL, 0, 0, 0)
                else:
                    table.attach(hbox, 1, 3, nr, nr+1, gtk.FILL, 0, 0, 0)
                hbox.pack_start(o.selector, False)
                self.options[option.keyword] = o
        if not self.installable_options:
            l = gtk.Label(_("No Installable Options"))
            container.add(l)
            l.show()
        self.scrNPInstallableOptions.hide()
        self.scrNPInstallableOptions.show_all()

            
    # Create new Printer
    def on_btnNPApply_clicked(self, widget):
        if self.dialog_mode in ("class", "printer"):
            name = self.entNPName.get_text()
            location = self.entNPLocation.get_text()
            info = self.entNPDescription.get_text()
        else:
            name = self.mainapp.printer.name

        # Whether to check for missing drivers.
        check = False
        checkppd = None
        ppd = self.ppd

        if self.dialog_mode=="class":
            members = self.getCurrentClassMembers(self.tvNCMembers)
            try:
                for member in members:
                    self.mainapp.cups.addPrinterToClass(member, name)
            except cups.IPPError, (e, msg):
                self.show_IPP_Error(e, msg)
                return
        elif self.dialog_mode=="printer":
            uri = None
            if self.device.uri:
                uri = self.device.uri
            else:
                uri = self.getDeviceURI()
            if not self.ppd: # XXX needed?
                # Go back to previous page to re-select driver.
                self.nextNPTab(-1)
                return

            # write Installable Options to ppd
            for option in self.options.itervalues():
                option.writeback()

            self.busy (self.NewPrinterWindow)
            self.lblWait.set_markup ('<span weight="bold" size="larger">' +
                                     _('Adding') + '</span>\n\n' +
                                     _('Adding printer'))
            self.WaitWindow.set_transient_for (self.NewPrinterWindow)
            self.WaitWindow.show ()
            while gtk.events_pending ():
                gtk.main_iteration ()
            try:
                if isinstance(ppd, str) or isinstance(ppd, unicode):
                    self.mainapp.cups.addPrinter(name, ppdname=ppd,
                         device=uri, info=info, location=location)
                    check = True
                elif ppd is None: # raw queue
                    self.mainapp.cups.addPrinter(name, device=uri,
                                         info=info, location=location)
                else:
                    cupshelpers.setPPDPageSize(ppd, self.language[0])
                    self.mainapp.cups.addPrinter(name, ppd=ppd,
                         device=uri, info=info, location=location)
                    check = True
                    checkppd = ppd
                cupshelpers.activateNewPrinter (self.mainapp.cups, name)
            except cups.IPPError, (e, msg):
                self.ready (self.NewPrinterWindow)
                self.WaitWindow.hide ()
                self.show_IPP_Error(e, msg)
                return
            except:
                self.ready (self.NewPrinterWindow)
                self.WaitWindow.hide ()
                fatalException (1)
            self.WaitWindow.hide ()
            self.ready (self.NewPrinterWindow)
        if self.dialog_mode in ("class", "printer"):
            try:
                self.mainapp.cups.setPrinterLocation(name, location)
                self.mainapp.cups.setPrinterInfo(name, info)
            except cups.IPPError, (e, msg):
                self.show_IPP_Error(e, msg)
                return
        elif self.dialog_mode == "device":
            try:
                uri = self.getDeviceURI()
                self.mainapp.cups.addPrinter(name, device=uri)
            except cups.IPPError, (e, msg):
                self.show_IPP_Error(e, msg)
                return
        elif self.dialog_mode == "ppd":
            if not ppd:
                ppd = self.ppd = self.getNPPPD()
                if not ppd:
                    # Go back to previous page to re-select driver.
                    self.nextNPTab(-1)
                    return

            # set ppd on server and retrieve it
            # cups doesn't offer a way to just download a ppd ;(=
            raw = False
            if isinstance(ppd, str) or isinstance(ppd, unicode):
                if self.rbtnChangePPDasIs.get_active():
                    # To use the PPD as-is we need to prevent CUPS copying
                    # the old options over.  Do this by setting it to a
                    # raw queue (no PPD) first.
                    try:
                        self.mainapp.cups.addPrinter(name, ppdname='raw')
                    except cups.IPPError, (e, msg):
                        self.show_IPP_Error(e, msg)
                try:
                    self.mainapp.cups.addPrinter(name, ppdname=ppd)
                except cups.IPPError, (e, msg):
                    self.show_IPP_Error(e, msg)
                    return

                try:
                    filename = self.mainapp.cups.getPPD(name)
                    ppd = cups.PPD(filename)
                    os.unlink(filename)
                except cups.IPPError, (e, msg):
                    if e == cups.IPP_NOT_FOUND:
                        raw = True
                    else:
                        self.show_IPP_Error(e, msg)
                        return
            else:
                # We have an actual PPD to upload, not just a name.
                if not self.rbtnChangePPDasIs.get_active():
                    cupshelpers.copyPPDOptions(self.mainapp.ppd, ppd) # XXX
                else:
                    # write Installable Options to ppd
                    for option in self.options.itervalues():
                        option.writeback()
                    cupshelpers.setPPDPageSize(ppd, self.language[0])

                try:
                    self.mainapp.cups.addPrinter(name, ppd=ppd)
                except cups.IPPError, (e, msg):
                    self.show_IPP_Error(e, msg)

            if not raw:
                check = True
                checkppd = ppd

        self.NewPrinterWindow.hide()
        self.mainapp.populateList()
        self.mainapp.fillPrinterTab (name)
        if check:
            try:
                self.checkDriverExists (name, ppd=checkppd)
            except:
                nonfatalException()

            # Also check to see whether the media option has become
            # invalid.  This can happen if it had previously been
            # explicitly set to a page size that is not offered with
            # the new PPD (see bug #441836).
            try:
                option = self.mainapp.server_side_options['media']
                if option.get_current_value () == None:
                    debugprint ("Invalid media option: resetting")
                    option.reset ()
                    self.mainapp.changed.add (option)
                    self.mainapp.save_printer (self.mainapp.printer)
            except KeyError:
                pass
            except:
                nonfatalException()

    def checkDriverExists(self, name, ppd=None):
        """Check that the driver for an existing queue actually
        exists, and prompt to install the appropriate package
        if not.

        ppd: cups.PPD object, if already created"""

        # Is this queue on the local machine?  If not, we can't check
        # anything at all.
        server = cups.getServer ()
        if not (server == 'localhost' or server == '127.0.0.1' or
                server == '::1' or server[0] == '/'):
            return

        # Fetch the PPD if we haven't already.
        if not ppd:
            try:
                filename = self.mainapp.cups.getPPD(name)
            except cups.IPPError, (e, msg):
                if e == cups.IPP_NOT_FOUND:
                    # This is a raw queue.  Nothing to check.
                    return
                else:
                    self.show_IPP_Error(e, msg)
                    return

            ppd = cups.PPD(filename)
            os.unlink(filename)

        (pkgs, exes) = cupshelpers.missingPackagesAndExecutables (ppd)
        if len (pkgs) > 0 or len (exes) > 0:
            # We didn't find a necessary executable.  Complain.
            install = "/usr/bin/system-install-packages"
            if len (pkgs) > 0 and os.access (install, os.X_OK):
                pkg = pkgs[0]
                install_text = ('<span weight="bold" size="larger">' +
                                _('Install driver') + '</span>\n\n' +
                                _("Printer '%s' requires the %s package but "
                                  "it is not currently installed.") %
                                (name, pkg))
                dialog = self.InstallDialog
                self.lblInstall.set_markup(install_text)
                dialog.set_transient_for (self.mainapp.MainWindow)
                response = dialog.run ()
                dialog.hide ()
                if response == gtk.RESPONSE_OK:
                    # Install the package.
                    def wait_child (sig, stack):
                        (pid, status) = os.wait ()

                    signal.signal (signal.SIGCHLD, wait_child)
                    pid = os.fork ()
                    if pid == 0:
                        # Child.
                        try:
                            os.execv (install, [install, pkg])
                        except:
                            pass
                        sys.exit (1)
                    elif pid == -1:
                        pass # should handle error
            else:
                show_error_dialog (_('Missing driver'),
                                   _("Printer '%s' requires the '%s' program "
                                     "but it is not currently installed.  "
                                     "Please install it before using this "
                                     "printer.") % (name, (exes + pkgs)[0]),
                                   self.mainapp.MainWindow)


def main(configure_printer = None, change_ppd = False):
    cups.setUser (os.environ.get ("CUPS_USER", cups.getUser()))
    gtk.gdk.threads_init()

    mainwindow = GUI(configure_printer, change_ppd)
    if gtk.__dict__.has_key("main"):
        gtk.main()
    else:
        gtk.mainloop()


if __name__ == "__main__":
    import getopt
    try:
        opts, args = getopt.gnu_getopt (sys.argv[1:], '',
                                        ['configure-printer=',
                                         'choose-driver=',
                                         'debug'])
    except getopt.GetoptError:
        show_help ()
        sys.exit (1)

    configure_printer = None
    change_ppd = False
    for opt, optarg in opts:
        if (opt == "--configure-printer" or
            opt == "--choose-driver"):
            configure_printer = optarg
            if opt == "--choose-driver":
                change_ppd = True

        elif opt == '--debug':
            set_debugging (True)

    main(configure_printer, change_ppd)

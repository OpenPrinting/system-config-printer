#!/usr/bin/env python

## system-config-printer

## Copyright (C) 2006, 2007 Red Hat, Inc.
## Copyright (C) 2006, 2007 Florian Festi <ffesti@redhat.com>
## Copyright (C) 2006, 2007 Tim Waugh <twaugh@redhat.com>

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

import sys, os, tempfile, time, traceback, re
import signal, thread
try:
    import gtk.glade
except RuntimeError, e:
    print "system-config-printer:", e
    print "This is a graphical application and requires DISPLAY to be set."
    sys.exit (1)

def show_help():
    print ("\nThis is system-config-printer, " \
           "a CUPS server configuration program.\n")

if len(sys.argv)>1 and sys.argv[1] == '--help':
    show_help ()
    sys.exit (0)

import cups
import pysmb
import cupshelpers, options
import gobject # for TYPE_STRING and TYPE_PYOBJECT
from optionwidgets import OptionWidget
import ppds
from cupsd import CupsConfig
import probe_printer
import gtk_label_autowrap
from gtk_treeviewtooltips import TreeViewTooltips
import urllib

domain='system-config-printer'
import locale
locale.setlocale (locale.LC_ALL, "")
from gettext import gettext as _
import gettext
gettext.textdomain (domain)
gtk.glade.bindtextdomain (domain)
pkgdata = '/usr/share/' + domain
glade_file = pkgdata + '/' + domain + '.glade'
sys.path.append (pkgdata)

busy_cursor = gtk.gdk.Cursor(gtk.gdk.WATCH)
ready_cursor = gtk.gdk.Cursor(gtk.gdk.LEFT_PTR)
ellipsis = unichr(0x2026)

try:
    try_CUPS_SERVER_REMOTE_ANY = cups.CUPS_SERVER_REMOTE_ANY
except AttributeError:
    # cups module was compiled with CUPS < 1.3
    try_CUPS_SERVER_REMOTE_ANY = "_remote_any"

def nonfatalException ():
    print "Caught non-fatal exception.  Traceback:"
    (type, value, tb) = sys.exc_info ()
    tblast = traceback.extract_tb (tb, limit=None)
    if len (tblast):
        tblast = tblast[:len (tblast) - 1]
    extxt = traceback.format_exception_only (type, value)
    for line in traceback.format_tb(tb):
        print line.strip ()
    print extxt[0].strip ()
    print "Continuing anyway.."

def validDeviceURI (uri):
    """Returns True is the provided URI is valid."""
    if uri.find (":/") > 0:
        return True
    return False

class GUI:

    def __init__(self, start_printer = None, change_ppd = False):

        self.language = locale.getlocale(locale.LC_MESSAGES)
        self.encoding = locale.getlocale(locale.LC_CTYPE)
        
        self.printer = None
        self.conflicts = set() # of options
        self.connect_server = (self.printer and self.printer.getServer()) \
                               or cups.getServer()	
        self.connect_user = cups.getUser()
        self.password = ''
        self.passwd_retry = False
        cups.setPasswordCB(self.cupsPasswdCallback)        

        self.changed = set() # of options

        self.servers = set((self.connect_server,))

        # Synchronisation objects.
        self.ppds_lock = thread.allocate_lock()
        self.devices_lock = thread.allocate_lock()
        self.smb_lock = thread.allocate_lock()

        try:
            self.cups = cups.Connection()
        except RuntimeError:
            self.cups = None

        # WIDGETS
        # =======
        xml = os.environ.get ("SYSTEM_CONFIG_PRINTER_GLADE", glade_file)
        self.xml = gtk.glade.XML(xml, domain = domain)

        self.getWidgets("MainWindow", "tvMainList", "ntbkMain",
                        "statusbarMain",
                        "btnNewPrinter", "btnNewClass", "btnCopy", "btnDelete",
                        "new_printer", "new_class", "copy", "delete",
                        "btnGotoServer",

                        "btnApply", "btnRevert", "btnConflict",

                        "chkServerBrowse", "chkServerShare",
                        "chkServerShareAny",
                        "chkServerRemoteAdmin", "chkServerAllowCancelAll",
                        "chkServerLogDebug",

                        "ntbkPrinter",
                         "entPDescription", "entPLocation",
                          "lblPMakeModel", "lblPMakeModel2",
                          "lblPState", "entPDevice", "lblPDevice2",
                          "btnSelectDevice", "btnChangePPD",
                          "chkPEnabled", "chkPAccepting", "chkPShared",
                        "lblNotPublished",
                          "btnPMakeDefault", "lblPDefault",
                        "btnPrintTestPage", "btnSelfTest", "btnCleanHeads",
           
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
                        
                        "ConnectDialog", "chkEncrypted", "cmbServername",
                         "entUser",
                        "ConnectingDialog", "lblConnecting",
                        "PasswordDialog", "lblPasswordPrompt", "entPasswd",

                        "ErrorDialog", "lblError",
                        "InfoDialog", "lblInfo",
                        "InstallDialog", "lblInstall",

                        "ApplyDialog",

                        "NewPrinterWindow", "ntbkNewPrinter",
                         "btnNPBack", "btnNPForward", "btnNPApply",
                          "entNPName", "entNPDescription", "entNPLocation",
                          "tvNPDevices", "ntbkNPType",
                        "lblNPDeviceDescription",
                           "cmbNPTSerialBaud", "cmbNPTSerialParity",
                            "cmbNPTSerialBits", "cmbNPTSerialFlow",
                           "cmbentNPTLpdHost", "cmbentNPTLpdQueue",
                           "entNPTIPPHostname", "entNPTIPPPrintername",
                        "entNPTDirectJetHostname", "entNPTDirectJetPort",
                        "entNPTIPPHostname", "entNPTIPPPrintername",
                        "SMBBrowseDialog", "entSMBURI", "tvSMBBrowser", "tblSMBAuth",
                        "entSMBUsername", "entSMBPassword", "btnSMBBrowseOk", "btnSMBVerify",
                           "entNPTDevice",
                           "tvNCMembers", "tvNCNotMembers",
                          "rbtnNPPPD", "tvNPMakes", 
                          "rbtnNPFoomatic", "filechooserPPD",
                        
                          "tvNPModels", "tvNPDrivers",
                          "rbtnChangePPDasIs",
                        "NewPrinterName", "entCopyName", "btnCopyOk",

                        "AboutDialog",

                        "WaitWindow", "lblWait",
                        )

        # Set up "About" dialog
        self.AboutDialog.set_version(config.VERSION)

        self.static_tabs = 3

        gtk_label_autowrap.set_autowrap(self.MainWindow)
        gtk_label_autowrap.set_autowrap(self.NewPrinterWindow)

        self.status_context_id = self.statusbarMain.get_context_id(
            "Connection")
        self.setConnected()
        self.ntbkMain.set_show_tabs(False)
        self.ntbkNewPrinter.set_show_tabs(False)
        self.ntbkNPType.set_show_tabs(False)
        self.prompt_primary = self.lblPasswordPrompt.get_label ()

        # Setup main list
        column = gtk.TreeViewColumn()
        cell = gtk.CellRendererText()
        cell.markup = True
        column.pack_start(cell, True)
        self.tvMainList.append_column(column)
        self.mainlist = gtk.TreeStore(str, str)
        
        self.tvMainList.set_model(self.mainlist)
        column.set_attributes(cell, text=0)
        selection = self.tvMainList.get_selection()
        selection.set_mode(gtk.SELECTION_BROWSE)
        selection.set_select_function(self.maySelectItem)

        self.mainlist.append(None, (_("Server Settings"), 'Settings'))

        self.tooltips = gtk.Tooltips()
        self.tooltips.enable()

        # setup some lists
        m = gtk.SELECTION_MULTIPLE
        s = gtk.SELECTION_SINGLE
        for name, treeview, selection_mode in (
            (_("Members of this class"), self.tvClassMembers, m),
            (_("Others"), self.tvClassNotMembers, m),
            (_("Members of this class"), self.tvNCMembers, m),
            (_("Others"), self.tvNCNotMembers, m),
            (_("Devices"), self.tvNPDevices, s),
            (_("Makes"), self.tvNPMakes,s),
            (_("Models"), self.tvNPModels,s),
            (_("Drivers"), self.tvNPDrivers,s),
            (_("Users"), self.tvPUsers, m),
            ):
            
            model = gtk.ListStore(str)
            cell = gtk.CellRendererText()
            column = gtk.TreeViewColumn(name, cell, text=0)
            treeview.set_model(model)
            treeview.append_column(column)
            treeview.get_selection().set_mode(selection_mode)

        self.tvNPDriversTooltips = TreeViewTooltips(self.tvNPDrivers, self.NPDriversTooltips)

        ppd_filter = gtk.FileFilter()
        ppd_filter.set_name(_("PostScript Printer Description (*.ppd[.gz])"))
        ppd_filter.add_pattern("*.ppd")
        ppd_filter.add_pattern("*.PPD")
        ppd_filter.add_pattern("*.ppd.gz")
        
        self.filechooserPPD.add_filter(ppd_filter)

        self.conflict_dialog = gtk.MessageDialog(
            parent=None, flags=0, type=gtk.MESSAGE_WARNING,
            buttons=gtk.BUTTONS_OK)
        
        # SMB browser
        self.smb_store = gtk.TreeStore (str, # host or share
                                        str, # comment
                                        gobject.TYPE_PYOBJECT, # domain dict
                                        gobject.TYPE_PYOBJECT) # host dict
        self.tvSMBBrowser.set_model (self.smb_store)
        self.smb_store.set_sort_column_id (0, gtk.SORT_ASCENDING)

        # SMB list columns
        col = gtk.TreeViewColumn (_("Share"), gtk.CellRendererText (),
                                  text=0)
        col.set_resizable (True)
        col.set_sort_column_id (0)
        self.tvSMBBrowser.append_column (col)

        col = gtk.TreeViewColumn (_("Comment"), gtk.CellRendererText (),
                                  text=1)
        self.tvSMBBrowser.append_column (col)
        slct = self.tvSMBBrowser.get_selection ()
        slct.set_select_function (self.smb_select_function)
        
        self.SMBBrowseDialog.set_transient_for(self.NewPrinterWindow)

        self.xml.signal_autoconnect(self)

        # Job Options widgets.
        opts = [ options.OptionAlwaysShown ("copies", int, 1,
                                            self.sbJOCopies,
                                            self.btnJOResetCopies),

                 options.OptionAlwaysShown \
                 ("orientation-requested", int, 3,
                  self.cmbJOOrientationRequested,
                  self.btnJOResetOrientationRequested,
                  combobox_map = [3, 4, 5, 6]),

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
                                                             50, 51, 52, 53 ]),

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

        try:
            self.populateList(start_printer, change_ppd)
        except cups.HTTPError, (s,):
            self.cups = None
            self.setConnected()
            self.populateList()
            self.show_HTTP_Error(s)

    def getWidgets(self, *names):
        for name in names:
            widget = self.xml.get_widget(name)
            if widget is None:
                raise ValueError, "Widget '%s' not found" % name
            setattr(self, name, widget)

    def busy (self, win = None):
        if not win:
            win = self.MainWindow
        win.window.set_cursor (busy_cursor)
        while gtk.events_pending ():
            gtk.main_iteration ()
            
    def ready (self, win = None):
        if not win:
            win = self.MainWindow
        win.window.set_cursor (ready_cursor)
        while gtk.events_pending ():
            gtk.main_iteration ()

    def queryPPDs(self):
        print "queryPPDs"
        if not self.ppds_lock.acquire(0):
            print "queryPPDs: in progress"
            return
        print "Lock acquired for PPDs thread"
        # Start new thread
        thread.start_new_thread (self.getPPDs_thread, (self.language[0],))
        print "PPDs thread started"

    def getPPDs_thread(self, language):
        try:
            print "Connecting (PPDs)"
            cups.setServer (self.connect_server)
            cups.setUser (self.connect_user)
            cups.setPasswordCB (self.cupsPasswdCallback)
            # cups.setEncryption (...)
            c = cups.Connection ()
            print "Fetching PPDs"
            ppds_dict = c.getPPDs()
            self.ppds_result = ppds.PPDs(ppds_dict, language=language)
            print "Closing connection (PPDs)"
            del c
        except cups.IPPError, (e, msg):
            self.ppds_result = cups.IPPError (e, msg)
        except:
            self.ppds_result = None

        print "Releasing PPDs lock"
        self.ppds_lock.release ()

    def fetchPPDs(self, parent=None):
        print "fetchPPDs"
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
                    parent = self.MainWindow
                self.WaitWindow.set_transient_for (parent)
                self.WaitWindow.show ()

            while gtk.events_pending ():
                gtk.main_iteration ()

            time.sleep (0.1)

        if waiting:
            self.WaitWindow.hide ()

        print "Got PPDs"
        result = self.ppds_result # atomic operation
        if isinstance (result, cups.IPPError):
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

    def setConnected(self):
        connected = bool(self.cups)

        host = cups.getServer()

        if host[0] == '/':
            host = 'localhost'
        self.MainWindow.set_title(_("Printer configuration - %s") % host)

        if connected:
            status_msg = _("Connected to %s") % host
        else:
            status_msg = _("Not connected")
        self.statusbarMain.push(self.status_context_id, status_msg)

        for widget in (self.btnNewPrinter, self.btnNewClass,
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

    def populateList(self, start_printer = None, change_ppd = False):
        old_name, old_type = self.getSelectedItem()

        select_path = None

        # get Printers
        if self.cups:
            try:
                self.printers = cupshelpers.getPrinters(self.cups)
            except cups.IPPError, (e, m):
                self.show_IPP_Error(e, m)
                self.printers = {}
        else:
            self.printers = {}
        
        self.default_printer = ""

        local_printers = []
        local_classes = []
        remote_printers = []
        remote_classes = []

        for name, printer in self.printers.iteritems():
            if printer.default:
                self.default_printer = name
                if start_printer == None:
                    start_printer = self.default_printer
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

        expanded = {
            "_printers" : True,
            "_classes" : True,
            "_remote_printers" : True,
            "_remote_classes" : True,
            }

        # remove old printers/classes
        iter = self.mainlist.get_iter_first()
        iter = self.mainlist.iter_next(iter) # step over server settings
        while iter:
            entry = self.mainlist.get_value(iter, 1)
            path = self.mainlist.get_path(iter)
            expanded[entry] = self.tvMainList.row_expanded(path)
            more_entries =  self.mainlist.remove(iter)
            if not more_entries: break
        
        # add new
        for printers, text, name in (
            (local_printers, _("Local Printers"), "_printers"),
            (local_classes, _("Local Classes"), "_classes"),
            (remote_printers, _("Remote Printers"), "_remote_printers"),
            (remote_classes, _("Remote Classes"), "_remote_classes")):
            if not printers: continue
            iter = self.mainlist.append(None, (text, name))
            path = self.mainlist.get_path(iter)

            for printer_name in printers:
                if start_printer == None:
                    start_printer = printer_name
                p_iter = self.mainlist.append(iter, (printer_name, "Printer"))
                if (printer_name==old_name or
                    printer_name==start_printer):
                    select_path = self.mainlist.get_path(p_iter)
                    expanded[name] = True
            if expanded[name]:
                self.tvMainList.expand_row(path, False)

        # Selection
        selection = self.tvMainList.get_selection()
        if old_type == "Settings":
            select_path = (0,)
        if select_path:
            selection.select_path(select_path)
        else:
            selection.select_path((0,))

        self.on_tvMainList_cursor_changed(self.tvMainList)

        if change_ppd:
            self.on_btnChangePPD_clicked (self.btnChangePPD)

    def maySelectItem(self, selection):
        result = self.mainlist.get_value(
            self.mainlist.get_iter(selection), 1)
        if result[0] == "_":
            if self.tvMainList.row_expanded(selection):
                self.tvMainList.collapse_row(selection)
            else:
                self.tvMainList.expand_row(selection, False)
            return False
        if self.changed:
            response = self.ApplyDialog.run()
            self.ApplyDialog.hide()
            err = False
            if response == gtk.RESPONSE_APPLY:
                err = self.apply()
            if err or response == gtk.RESPONSE_CANCEL:
                return False
        self.changed = set() # of options
        return True

    def getSelectedItem(self):
        model, iter = self.tvMainList.get_selection().get_selected()
        if iter is None:
            return ("", 'None')
        name, type = model.get_value(iter, 0), model.get_value(iter, 1)
        return name.strip(), type

    # Connect to Server

    def on_connect_activate(self, widget):
        # check for unapplied changes
        if self.changed:
            response = self.ApplyDialog.run()
            self.ApplyDialog.hide()
            err = False
            if response == gtk.RESPONSE_APPLY:
                err = self.apply()
            if err or response == gtk.RESPONSE_CANCEL:
                return

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
        self.entUser.set_text (cups.getUser())
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

        servername = self.cmbServername.child.get_text()
        user = self.entUser.get_text()

        self.lblConnecting.set_text(_("Connecting to server:\n%s") %
                                    servername)
        self.dropPPDs()
        self.ConnectingDialog.set_transient_for(self.MainWindow)
        self.ConnectingDialog.show()
        self.connect_server = servername
        self.connect_user = user
        # We need to set the connecting user in this thread as well.
        cups.setServer(self.connect_server)
        cups.setUser(self.connect_user)
        # Now start a new thread for connection.
        args = ()
        if self.printer:
            args = (self.printer.name,)
        self.connect_thread = thread.start_new_thread(self.connect, args)

    def on_cancel_connect_clicked(self, widget):
        """
        Stop connection to new server
        (Doesn't really stop but sets flag for the connecting thread to
        ignore the connection)
        """
        self.connect_thread = None
        self.ConnectingDialog.hide()

    def connect(self, start_printer=None):
        """
        Open a connection to a new server. Is executed in a separate thread!
        """
        cups.setServer(self.connect_server)
        cups.setUser(self.connect_user)
        cups.setPasswordCB(self.cupsPasswdCallback)
        # cups.setEncryption (...)

        self.password = ''

        if self.connect_server[0] == '/':
            # UNIX domain socket.  This may potentially fail if the server
            # settings have been changed and cupsd has written out a
            # configuration that does not include a Listen line for the
            # UNIX domain socket.  To handle this special case, try to
            # connect once and fall back to "localhost" on failure.
            try:
                connection = cups.Connection ()

                # Worked fine.  Disconnect, and we'll connect for real
                # shortly.
                del connection
            except RuntimeError:
                # When we connect, avoid the domain socket.
                cups.setServer ("localhost")

        try:
            connection = cups.Connection()
            self.dropPPDs ()
        except RuntimeError, s:
            if self.connect_thread != thread.get_ident(): return
            gtk.gdk.threads_enter()
            self.ConnectingDialog.hide()
            self.show_IPP_Error(None, s)
            gtk.gdk.threads_leave()
            return        
        except cups.IPPError, (e, s):
            if self.connect_thread != thread.get_ident(): return
            gtk.gdk.threads_enter()
            self.ConnectingDialog.hide()
            self.show_IPP_Error(e, s)
            gtk.gdk.threads_leave()
            return

        if self.connect_thread != thread.get_ident(): return
        gtk.gdk.threads_enter()

        try:
            self.ConnectingDialog.hide()
            self.cups = connection
            self.setConnected()
            self.populateList(start_printer=start_printer)
	except cups.HTTPError, (s,):
            self.cups = None
            self.setConnected()
            self.populateList()
            self.show_HTTP_Error(s)

        gtk.gdk.threads_leave()

    def reconnect (self):
        """Reconnect to CUPS after the server has reloaded."""
        # libcups will handle the reconnection; we just need to tell it
        # to do something.
        try:
            self.cups.getClasses ()
        except cups.IPPError, (e, s):
            self.show_IPP_Error(e, s)
        except cups.HTTPError, (s,):
            self.cups = None
            self.setConnected()
            self.populateList()
            self.show_HTTP_Error(s)

    def on_btnCancelConnect_clicked(self, widget):
        """Close Connect dialog"""
        self.ConnectWindow.hide()

    # Password handling

    def cupsPasswdCallback(self, querystring):
        if self.passwd_retry or len(self.password) == 0:
            waiting = self.WaitWindow.get_property('visible')
            if waiting:
                self.WaitWindow.hide ()
            self.lblPasswordPrompt.set_label (self.prompt_primary +
                                              querystring)
            self.PasswordDialog.set_transient_for (self.MainWindow)
            self.entPasswd.grab_focus ()

            result = self.PasswordDialog.run()
            self.PasswordDialog.hide()
            if waiting:
                self.WaitWindow.show ()
            while gtk.events_pending ():
                gtk.main_iteration ()
            if result == gtk.RESPONSE_OK:
                self.password = self.entPasswd.get_text()
            else:
                self.password = ''
            self.passwd_retry = False
        else:
            self.passwd_retry = True
        return self.password
    
    def on_btnPasswdOk_clicked(self, widget):
        self.PasswordDialog.response(0)

    def on_btnPasswdCancel_clicked(self, widget):
        self.PasswordDialog.response(1)

    # refresh
    
    def on_btnRefresh_clicked(self, button):
        self.populateList()

    # Unapplied changes dialog

    def on_btnApplyApply_clicked(self, button):
        self.ApplyDialog.response(gtk.RESPONSE_APPLY)

    def on_btnApplyCancel_clicked(self, button):
        self.ApplyDialog.response(gtk.RESPONSE_CANCEL)

    def on_btnApplyDiscard_clicked(self, button):
        self.ApplyDialog.response(gtk.RESPONSE_REJECT)

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

    # set Apply/Revert buttons sensitive    
    def setDataButtonState(self):
        for button in [self.btnApply, self.btnRevert]:
            button.set_sensitive(bool(self.changed) and
                                 not bool(self.conflicts))

        try: # Might not be a printer selected
            if not self.test_button_cancels:
                self.btnPrintTestPage.set_sensitive (not bool (self.changed) and
                                                     self.printer.enabled and
                                                     not self.printer.rejecting)
        except:
            pass

        installablebold = False
        optionsbold = False
        if self.conflicts:
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

    # Apply Changes
    
    def on_btnApply_clicked(self, widget):
        err = self.apply()
        if not err:
            self.populateList()
        else:
            nonfatalException()
        
    def apply(self):
        name, type = self.getSelectedItem()
        if type in ("Printer", "Class"):
            return self.save_printer(self.printer)
        elif type == "Settings":
            return self.save_serversettings()
        
    def show_IPP_Error(self, exception, message):
        if exception == cups.IPP_NOT_AUTHORIZED:
            error_text = ('<span weight="bold" size="larger">' +
                          _('Not authorized') + '</span>\n\n' +
                          _('The password may be incorrect.'))
        else:
            error_text = ('<span weight="bold" size="larger">' +
                          _('CUPS server error') + '</span>\n\n' +
                          _("There was an error during the CUPS "\
                            "operation: '%s'.")) % message
        self.lblError.set_markup(error_text)
        self.ErrorDialog.set_transient_for (self.MainWindow)
        self.ErrorDialog.run()
        self.ErrorDialog.hide()        
            
    def show_HTTP_Error(self, status):
        if (status == cups.HTTP_UNAUTHORIZED or
            status == cups.HTTP_FORBIDDEN):
            error_text = ('<span weight="bold" size="larger">' +
                          _('Not authorized') + '</span>\n\n' +
                          _('The password may be incorrect, or the '
                            'server may be configured to deny '
                            'remote administration.'))
        else:
            if status == cups.HTTP_BAD_REQUEST:
                msg = _("Bad request")
            elif status == cups.HTTP_NOT_FOUND:
                msg = _("Not found")
            elif status == cups.HTTP_REQUEST_TIMEOUT:
                msg = _("Request timeout")
            elif status == cups.HTTP_UPGRADE_REQUIRED:
                msg = _("Upgrade required")
            elif status == cups.HTTP_SERVER_ERROR:
                msg = _("Server error")
            elif status == -1:
                msg = _("Not connected")
            else:
                msg = _("status %d") % status

            error_text = ('<span weight="bold" size="larger">' +
                          _('CUPS server error') + '</span>\n\n' +
                          _("There was an HTTP error: %s.")) % msg
        self.lblError.set_markup(error_text)
        self.ErrorDialog.set_transient_for (self.MainWindow)
        self.ErrorDialog.run()
        self.ErrorDialog.hide()        
            
    def save_printer(self, printer, saveall=False):
        name = printer.name
        
        try:
            if not printer.is_class and self.ppd: 
                self.getPrinterSettings()
                if self.ppd.nondefaultsMarked() or saveall:
                    self.passwd_retry = False # use cached Passwd 
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
                self.passwd_retry = False # use cached Passwd 
                self.cups.setPrinterInfo(name, info)
            if location!=printer.location or saveall:
                self.passwd_retry = False # use cached Passwd 
                self.cups.setPrinterLocation(name, location)
            if (not printer.is_class and
                (device_uri!=printer.device_uri or saveall)):
                self.passwd_retry = False # use cached Passwd 
                self.cups.setPrinterDevice(name, device_uri)

            if enabled != printer.enabled or saveall:
                self.passwd_retry = False # use cached Passwd 
                self.printer.setEnabled(enabled)
            if accepting == printer.rejecting or saveall:
                self.passwd_retry = False # use cached Passwd 
                self.printer.setAccepting(accepting)
            if shared != printer.is_shared or saveall:
                self.passwd_retry = False # use cached Passwd 
                self.printer.setShared(shared)
                
            job_sheet_start = self.cmbPStartBanner.get_active_text()
            job_sheet_end = self.cmbPEndBanner.get_active_text()
            error_policy = self.cmbPErrorPolicy.get_active_text()
            op_policy = self.cmbPOperationPolicy.get_active_text()

            if (job_sheet_start != printer.job_sheet_start or
                job_sheet_end != printer.job_sheet_end) or saveall:
                self.passwd_retry = False # use cached Passwd
                printer.setJobSheets(job_sheet_start, job_sheet_end)
            if error_policy != printer.error_policy or saveall:
                self.passwd_retry = False # use cached Passwd
                printer.setErrorPolicy(error_policy)
            if op_policy != printer.op_policy or saveall:
                self.passwd_retry = False # use cached Passwd
                printer.setOperationPolicy(op_policy)

            default_allow = self.rbtnPAllow.get_active()
            except_users = self.getPUsers()

            if (default_allow != printer.default_allow or
                except_users != printer.except_users) or saveall:
                self.passwd_retry = False # use cached Passwd
                printer.setAccess(default_allow, except_users)

            for option in printer.attributes:
                if option not in self.server_side_options:
                    printer.unsetOption(option)
            for option in self.server_side_options.itervalues():
                if option.is_changed() or saveall:
                    printer.setOption(option.name, option.get_current_value())

        except cups.IPPError, (e, s):
            self.show_IPP_Error(e, s)
            return True
        self.changed = set() # of options

        # Update our copy of the printer's settings.
        printers = cupshelpers.getPrinters (self.cups)
        this_printer = { name: printers[name] }
        self.printers.update (this_printer)

        return False

    def getPrinterSettings(self):
        #self.ppd.markDefaults()
        for option in self.options.itervalues():
            option.writeback()

    # revert changes

    def on_btnRevert_clicked(self, button):
        self.changed = set() # avoid asking the user
        self.on_tvMainList_cursor_changed(self.tvMainList)

    # set default printer
    
    def on_btnPMakeDefault_clicked(self, button):
        try:
            self.cups.setDefault(self.printer.name)
        except cups.IPPError, (e, msg):
            self.show_IPP_Error(e, msg)
            return

        # Also need to check system-wide lpoptions because that's how
        # previous Fedora versions set the default (bug #217395).
        (tmpfd, tmpfname) = tempfile.mkstemp ()
        success = False
        try:
            resource = "/admin/conf/lpoptions"
            self.cups.getFile(resource, tmpfname)
            success = True
        except cups.HTTPError, (s,):
            try:
                os.remove (tmpfname)
            except OSError:
                pass

            if s != cups.HTTP_NOT_FOUND:
                self.show_HTTP_Error(s)
                return

        if success:
            lines = file (tmpfname).readlines ()
            changed = False
            i = 0
            for line in lines:
                if line.startswith ("Default "):
                    # This is the system-wide default.
                    name = line.split (' ')[1]
                    if name != self.printer.name:
                        # Stop it from over-riding the server default.
                        lines[i] = "Dest " + line[8:]
                        changed = True
                i += 1

            if changed:
                file (tmpfname, 'w').writelines (lines)
                try:
                    self.cups.putFile (resource, tmpfname)
                except cups.HTTPError, (s,):
                    os.remove (tmpfname)
                    print s
                    self.show_HTTP_Error(s)
                    return

                # Now reconnect because the server needs to reload.
                self.reconnect ()

        try:
            os.remove (tmpfname)
        except OSError:
            pass

        try:
            self.populateList()
        except cups.HTTPError, (s,):
            self.cups = None
            self.setConnected()
            self.populateList()
            self.show_HTTP_Error(s)

    # print test page
    
    def on_btnPrintTestPage_clicked(self, button):
        if self.test_button_cancels:
            jobs = self.printer.testsQueued ()
            for job in jobs:
                print "Canceling job %s" % job
                try:
                    self.cups.cancelJob (job)
                except cups.IPPError, (e, msg):
                    self.show_IPP_Error(e, msg)
            self.setTestButton (self.printer)
            return
        try:
            # if we have a page size specific custom test page, use it;
            # otherwise use cups' default one
            custom_testpage = None
            opt = self.ppd.findOption ("PageSize")
            if opt:
                custom_testpage = os.path.join(pkgdata, 'testpage-%s.ps' % opt.defchoice.lower())

            if custom_testpage and os.path.exists(custom_testpage):
                print 'Printing custom test page', custom_testpage
                job_id = self.cups.printTestPage(self.printer.name,
                    file=custom_testpage)
            else:
                print 'Printing default test page'
                job_id = self.cups.printTestPage(self.printer.name)

            self.lblInfo.set_markup ('<span weight="bold" size="larger">' +
                                     _("Submitted") + '</span>\n\n' +
                                     _("Test page submitted as "
                                       "job %d") % job_id)
            self.InfoDialog.set_transient_for (self.MainWindow)
            self.setTestButton (self.printer)
            self.InfoDialog.run ()
            self.InfoDialog.hide ()
        except cups.IPPError, (e, msg):
            if (e == cups.IPP_NOT_AUTHORIZED and
                self.printer.name != 'localhost'):
                self.lblError.set_markup ('<span weight="bold" size="larger">'+
                                          _("Not possible") + '</span>\n\n' +
                                          _("The remote server did not accept "
                                            "the print job, most likely "
                                            "because the printer is not "
                                            "shared."))
                self.ErrorDialog.set_transient_for (self.MainWindow)
                self.ErrorDialog.run ()
                self.ErrorDialog.hide ()
            else:
                self.show_IPP_Error(e, msg)

    def maintenance_command (self, command):
        (tmpfd, tmpfname) = tempfile.mkstemp ()
        os.write (tmpfd, "#CUPS-COMMAND\n%s\n" % command)
        os.close (tmpfd)
        try:
            job_id = self.cups.printTestPage (self.printer.name, file=tmpfname)
            self.lblInfo.set_markup ('<span weight="bold" size="larger">' +
                                     _("Submitted") + '</span>\n\n' +
                                     _("Maintenance command submitted as "
                                       "job %d") % job_id)
            self.InfoDialog.set_transient_for (self.MainWindow)
            self.InfoDialog.run ()
            self.InfoDialog.hide ()
        except cups.IPPError, (e, msg):
            if (e == cups.IPP_NOT_AUTHORIZED and
                self.printer.name != 'localhost'):
                self.lblError.set_markup ('<span weight="bold" size="larger">'+
                                          _("Not possible") + '</span>\n\n' +
                                          _("THe remote server did not accept "
                                            "the print job, most likely "
                                            "because the printer is not "
                                            "shared."))
                self.ErrorDialog.set_transient_for (self.MainWindow)
                self.ErrorDialog.run ()
                self.ErrorDialog.hide ()
            else:
                self.show_IPP_Error(e, msg)

    def on_btnSelfTest_clicked(self, button):
        self.maintenance_command ("PrintSelfTestPage")

    def on_btnCleanHeads_clicked(self, button):
        self.maintenance_command ("Clean all")

    # select Item

    def on_tvMainList_cursor_changed(self, list):
        if self.changed:
            # The unapplied changes for this item have not been saved,
            # and the user just pressed "Cancel".
            return
        name, type = self.getSelectedItem()
        model, self.mainListSelected = self.tvMainList.get_selection().get_selected()
        item_selected = True
        if type == "Settings":
            self.ntbkMain.set_current_page(0)
            if self.cups:
                self.fillServerTab()
            item_selected = False
        elif type in ['Printer', 'Class']:
            self.fillPrinterTab(name)
            self.ntbkMain.set_current_page(1)
        elif type == "None":
            self.ntbkMain.set_current_page(2)
            self.setDataButtonState()
            item_selected = False

        is_local = item_selected and not self.printers[name].remote
        for widget in [self.copy, self.btnCopy]:
            widget.set_sensitive(item_selected)
        for widget in [self.delete, self.btnDelete]:
            widget.set_sensitive(is_local)

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

        editable = not self.printer.remote

        try:
            self.ppd = printer.getPPD()
        except cups.IPPError, (e, m):
            # Some IPP error other than IPP_NOT_FOUND.
            self.show_IPP_Error(e, m)
            # Treat it as a raw queue.
            self.ppd = False
        except RuntimeError:
            # The underlying cupsGetPPD2() function returned NULL without
            # setting an IPP error, so it'll be something like a failed
            # connection.
            self.lblError.set_markup('<span weight="bold" size="larger">' +
                                     _("Error") + '</span>\n\n' +
                                     _("There was a problem connecting to "
                                       "the CUPS server."))
            self.ErrorDialog.set_transient_for(self.NewPrinterWindow)
            self.ErrorDialog.run()
            self.ErrorDialog.hide()
            sys.exit (1)

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
        self.lblPMakeModel.set_text(printer.make_and_model)
        self.lblPState.set_text(printer.state_description)

        uri = printer.device_uri
        if uri.startswith("smb://"):
            group, host, share, user, password = self.parse_SMBURI(uri[6:])
            if password:
                uri = "smb://"
                if len (user) or len (password):
                    uri += ellipsis
                uri += self.construct_SMBURI(group, host, share)
                self.entPDevice.set_sensitive(False)
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
            

        # default printer
        self.btnPMakeDefault.set_sensitive(not printer.default)
        if printer.default:
            self.lblPDefault.set_text(_("This is the default printer"))
        elif self.default_printer:
            self.lblPDefault.set_text(self.default_printer)
        else:
            self.lblPDefault.set_text(_("No default printer set."))

        self.setTestButton (printer)

        commands = (printer.type & cups.CUPS_PRINTER_COMMANDS) != 0
        commands = False # Needs better pycups support; disabled for now
        self.btnSelfTest.set_sensitive (commands)
        self.btnCleanHeads.set_sensitive (commands)

        # Policy tab
        # ----------

        # State
        self.chkPEnabled.set_active(printer.enabled)
        self.chkPAccepting.set_active(not printer.rejecting)
        self.chkPShared.set_active(printer.is_shared)
        try:
            if printer.is_shared:
                flag = cups.CUPS_SERVER_SHARE_PRINTERS
                publishing = int (self.server_settings[flag])
                if publishing:
                    self.lblNotPublished.hide_all ()
                else:
                    self.lblNotPublished.show_all ()
            else:
                self.lblNotPublished.hide_all ()
        except:
            self.lblNotPublished.hide_all ()

        # Job sheets
        self.fillComboBox(self.cmbPStartBanner, printer.job_sheets_supported,
                          printer.job_sheet_start),
        self.fillComboBox(self.cmbPEndBanner, printer.job_sheets_supported,
                          printer.job_sheet_end)
        self.cmbPStartBanner.set_sensitive(editable)
        self.cmbPEndBanner.set_sensitive(editable)

        # Policies
        self.fillComboBox(self.cmbPErrorPolicy, printer.error_policy_supported,
                          printer.error_policy)
        self.fillComboBox(self.cmbPOperationPolicy,
                          printer.op_policy_supported,
                          printer.op_policy)
        self.cmbPErrorPolicy.set_sensitive(editable)
        self.cmbPOperationPolicy.set_sensitive(editable)

        # Access control
        self.rbtnPAllow.set_active(printer.default_allow)
        self.rbtnPDeny.set_active(not printer.default_allow)
        self.setPUsers(printer.except_users)

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

            try:
                value = self.printer.attributes[option.name]
            except KeyError:
                option.reinit (None)
            else:
                if self.printer.possible_attributes.has_key (option.name):
                    supported = self.printer.possible_attributes[option.name][1]
                    option.reinit (value, supported=supported)
                else:
                    option.reinit (value)
                self.server_side_options[option.name] = option
            option.widget.set_sensitive (editable)
            if not editable:
                option.button.set_sensitive (editable)
        self.other_job_options = []
        self.draw_other_job_options (editable=editable)
        for option in self.printer.attributes.keys ():
            if self.server_side_options.has_key (option):
                continue
            supported = ""
            if self.printer.possible_attributes.has_key (option):
                supported = self.printer.possible_attributes[option][1]
            self.add_job_option (option, value=self.printer.attributes[option],
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
            self.fillPrinterOptions(name, editable)

        self.changed = set() # of options
        self.setDataButtonState()

    def setTestButton (self, printer):
        if printer.testsQueued ():
            self.test_button_cancels = True
            self.btnPrintTestPage.set_label (_('Cancel Tests'))
            self.btnPrintTestPage.set_sensitive (True)
        else:
            self.test_button_cancels = False
            self.btnPrintTestPage.set_label (_('Print Test Page'))
            self.setDataButtonState ()

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

    # Quit
    
    def on_quit_activate(self, widget, event=None):
        # check for unapplied changes
        if self.changed:
            response = self.ApplyDialog.run()
            self.ApplyDialog.hide()
            err = False
            if response == gtk.RESPONSE_APPLY:
                err = self.apply()
            if err or response == gtk.RESPONSE_CANCEL:
                # TODO: how do we just carry on as normal?
                return
        gtk.main_quit()

    # Copy
        
    def on_copy_activate(self, widget):
        # check for unapplied changes
        if self.changed:
            response = self.ApplyDialog.run()
            self.ApplyDialog.hide()
            err = False

            if response == gtk.RESPONSE_REJECT:
                self.changed = set() # avoid asking the user
                self.on_tvMainList_cursor_changed(self.tvMainList)
            elif response == gtk.RESPONSE_APPLY:
                err = self.apply()
            if err or response == gtk.RESPONSE_CANCEL:
                return

        self.entCopyName.set_text(self.printer.name)
        result = self.NewPrinterName.run()
        self.NewPrinterName.hide()

        if result == gtk.RESPONSE_CANCEL:
            return

        self.printer.name = self.entCopyName.get_text()
        self.printer.class_members = [] # for classes make shure all members
                                        # will get added 
        
        self.save_printer(self.printer, saveall=True)
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
            self.check_NPName(new_text))

    # Delete

    def on_delete_activate(self, widget):
        name, type = self.getSelectedItem()

        # Confirm
        if type == "Printer":
            message_format = _("Really delete printer %s?")
        else:
            message_format = _("Really delete class %s?")

        dialog = gtk.MessageDialog(
            self.MainWindow,
            buttons=gtk.BUTTONS_OK_CANCEL,
            message_format=message_format % name)
        result = dialog.run()
        dialog.destroy()

        if result == gtk.RESPONSE_CANCEL:
            return

        try:
            self.cups.deletePrinter(name)
        except cups.IPPError, (e, msg):
            self.show_IPP_Error(e, msg)

        self.changed = set()
        self.populateList()

    # About dialog
    def on_about_activate(self, widget):
        self.AboutDialog.run()
        self.AboutDialog.hide()

    # ====================================================================
    # == New Printer Dialog ==============================================
    # ====================================================================

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

    # new printer
    def on_new_printer_activate(self, widget):
        self.dialog_mode = "printer"
        self.NewPrinterWindow.set_title(_("New Printer"))
        
        self.busy (self.MainWindow)
        self.fillDeviceTab ()
        self.initNewPrinterWindow()
        self.on_rbtnNPFoomatic_toggled(self.rbtnNPFoomatic)
        self.ready (self.MainWindow)

        # Start fetching information from CUPS in the background
        self.new_printer_PPDs_loaded = False
        self.queryPPDs ()

    # new class
    def on_new_class_activate(self, widget):
        self.dialog_mode = "class"
        self.NewPrinterWindow.set_title(_("New Class"))

        self.fillNewClassMembers()

        self.initNewPrinterWindow()

    # change device
    def on_btnSelectDevice_clicked(self, button):
        self.busy (self.MainWindow)
        self.queryDevices ()
        self.loadPPDs()
        self.dialog_mode = "device"
        self.fillDeviceTab(self.printer.device_uri)
        self.initNewPrinterWindow()
        self.NewPrinterWindow.set_title(_("Change Device URI"))

        self.ntbkNewPrinter.set_current_page(1)

        self.initNewPrinterWindow()
        self.ready (self.MainWindow)

    # change PPD
    def on_btnChangePPD_clicked(self, button):
        self.busy (self.MainWindow)
        self.dialog_mode = "ppd"
        self.initNewPrinterWindow()
        self.NewPrinterWindow.set_title(_("Change Driver"))

        self.ntbkNewPrinter.set_current_page(2)
        self.on_rbtnNPFoomatic_toggled(self.rbtnNPFoomatic)

        self.auto_model = ""
        if self.ppd:
            attr = self.ppd.findAttr("Manufacturer")
            if attr:
                self.auto_make = attr.value
            else:
                self.auto_make = ""
            attr = self.ppd.findAttr("ModelName")
            if not attr: attr = self.ppd.findAttr("ShortNickName")
            if not attr: attr = self.ppd.findAttr("NickName")
            if attr:
                if attr.value.startswith(self.auto_make):
                    self.auto_model = attr.value[len(self.auto_make):].strip ()
                else:
                    try:
                        self.auto_model = attr.value.split(" ", 1)[1]
                    except IndexError:
                        self.auto_model = ""
            else:
                self.auto_model = ""
        else:
            # Special CUPS names for a raw queue.
            self.auto_make = 'Raw'
            self.auto_model = 'Queue'

        self.loadPPDs ()
        self.fillMakeList()
        self.initNewPrinterWindow()
        self.ready (self.MainWindow)

    def initNewPrinterWindow(self):
        if self.dialog_mode == "printer":
            # Start on devices page (1, not 0)
            self.ntbkNewPrinter.set_current_page(1)
        elif self.dialog_mode == "class":
            # Start on name page
            self.ntbkNewPrinter.set_current_page(0)

        if self.dialog_mode in ("printer", "class"):
            self.entNPName.set_text (self.makeNameUnique(self.dialog_mode))
            self.entNPName.grab_focus()
            for widget in [self.entNPLocation,
                           self.entNPDescription,
                           self.entSMBURI, self.entSMBUsername,
                           self.entSMBPassword, self.entNPTDirectJetHostname]:
                widget.set_text('')

            try:
                p = os.popen ('/bin/hostname', 'r')
                hostname = p.read ().strip ()
                p.close ()
                self.entNPLocation.set_text (hostname)
            except:
                nonfatalException ()

        self.entNPTDirectJetPort.set_text('9100')
        self.setNPButtons()
        self.NewPrinterWindow.set_transient_for(self.MainWindow)
        self.NewPrinterWindow.show()
    

    # Class members

    def fillNewClassMembers(self):
        model = self.tvNCMembers.get_model()
        model.clear()
        model = self.tvNCNotMembers.get_model()
        model.clear()
        for printer in self.printers.itervalues():
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
                # Choose an appropriate name.
                name = 'printer'
                try:
                    if self.device.id:
                        name = self.device.id_dict["MDL"]
                    name = self.makeNameUnique (name)
                    self.entNPName.set_text (name)
                except:
                    nonfatalException ()

                if not self.new_printer_PPDs_loaded:
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

                self.auto_make, self.auto_model = None, None
                self.device.uri = self.getDeviceURI()
                if self.device.type in ("socket", "lpd", "ipp", "bluetooth"):
                    host = self.getNetworkPrinterMakeModel(self.device)
                try:
                    ppdname = None
                    if self.device.id:
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
                        
                    if ppdname:
                        ppddict = self.ppds.getInfoFromPPDName (ppdname)
                        make_model = ppddict['ppd-make-and-model']
                        (make, model) = ppds.ppdMakeModelSplit (make_model)
                        self.auto_make = make
                        self.auto_model = model
                except:
                    nonfatalException ()

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
                        name = self.makeNameUnique (name)
                        self.entNPName.set_text (name)
                    except:
                        nonfatalException ()

            self.ready (self.NewPrinterWindow)
            if self.rbtnNPFoomatic.get_active():
                order = [1, 2, 3, 0]
            else:
                order = [1, 2, 0]
        elif self.dialog_mode == "device":
            order = [1]
        elif self.dialog_mode == "ppd":
            if self.rbtnNPFoomatic.get_active():
                order = [2, 3, 5]
            else:
                order = [2, 5]
            
        page_nr = self.ntbkNewPrinter.set_current_page(
            order[order.index(page_nr)+step])
        self.setNPButtons()

    def setNPButtons(self):
        nr = self.ntbkNewPrinter.get_current_page()

        if self.dialog_mode == "device":
            self.btnNPBack.hide()
            self.btnNPForward.hide()
            self.btnNPApply.show()
            uri = self.getDeviceURI ()
            self.btnNPApply.set_sensitive (validDeviceURI (uri))
            return

        if self.dialog_mode == "ppd":
            if nr == 5: # Apply
                self.btnNPForward.hide()
                self.btnNPApply.show()
                return
            else:
                self.btnNPForward.show()
                self.btnNPApply.hide()
            if nr == 2:
                self.btnNPBack.hide()
                self.btnNPForward.show()
                self.btnNPForward.set_sensitive(True)
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
                    self.check_NPName(self.entNPName.get_text()))
        if nr == 2: # Make/PPD file
            self.btnNPForward.set_sensitive(bool(
                self.rbtnNPFoomatic.get_active() or
                self.filechooserPPD.get_filename()))
        if nr == 3: # Model/Driver
            model, iter = self.tvNPDrivers.get_selection().get_selected()
            self.btnNPForward.set_sensitive(bool(iter))
        if nr == 4: # Class Members
            self.btnNPForward.hide()
            self.btnNPApply.show()
            self.btnNPApply.set_sensitive(
                bool(self.getCurrentClassMembers(self.tvNCMembers)))
            
    def check_NPName(self, name):
        if not name: return False
        name = name.lower()
        for printer in self.printers.values():
            if not printer.remote and printer.name.lower()==name:
                return False
        return True
    
    def makeNameUnique(self, name):
        """Make a suggested queue name valid and unique."""
        name = name.replace (" ", "_")
        name = name.replace ("/", "_")
        name = name.replace ("#", "_")
        if not self.check_NPName (name):
            suffix=2
            while not self.check_NPName (name + str (suffix)):
                suffix += 1
                if suffix == 100:
                    break
            name += str (suffix)
        return name

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
                self.check_NPName(new_text))
        else:
            self.btnNPForward.set_sensitive(
                self.check_NPName(new_text))

    # Device URI
    def queryDevices(self):
        if not self.devices_lock.acquire(0):
            print "queryDevices: in progress"
            return
        print "Lock acquired for devices thread"
        # Start new thread
        thread.start_new_thread (self.getDevices_thread, ())
        print "Devices thread started"

    def getDevices_thread(self):
        try:
            print "Connecting (devices)"
            cups.setServer (self.connect_server)
            cups.setUser (self.connect_user)
            cups.setPasswordCB (self.cupsPasswdCallback)
            # cups.setEncryption (...)
            c = cups.Connection ()
            print "Fetching devices"
            self.devices_result = cupshelpers.getDevices(c)
        except cups.IPPError, (e, msg):
            self.devices_result = cups.IPPError (e, msg)
        except:
            print "Exception in getDevices_thread"
            self.devices_result = None

        try:
            print "Closing connection (devices)"
            del c
        except:
            pass

        print "Releasing devices lock"
        self.devices_lock.release ()

    def fetchDevices(self, parent=None):
        print "fetchDevices"
        self.queryDevices ()
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
                    parent = self.MainWindow
                self.WaitWindow.set_transient_for (parent)
                self.WaitWindow.show ()

            while gtk.events_pending ():
                gtk.main_iteration ()

            time.sleep (0.1)

        if waiting:
            self.WaitWindow.hide ()

        print "Got devices"
        result = self.devices_result # atomic operation
        if isinstance (result, cups.IPPError):
            # Propagate exception.
            raise result
        return result

    def get_hplip_uri_for_network_printer(self, host, mode):
        if mode == "print": mod = "-c"
        elif mode == "fax": mod = "-f"
        else: mod = "-c"
        uri = None
        os.environ["HOST"] = host
        cmd = 'hp-makeuri ' + mod + ' "${HOST}" 2> /dev/null'
        p = os.popen(cmd, 'r')
        uri = p.read()
        p.close()
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
            cmd = '/usr/lib/cups/backend/snmp "${HOST}" 2>/dev/null'
            p = os.popen(cmd, 'r')
            output = p.read()
            p.close()
            mm = re.sub("^\s*\S+\s+\S+\s+\"", "", output)
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
        if make_and_model:
            mk = None
            md = None
            (mk, md) = ppds.ppdMakeModelSplit (make_and_model)
            device.id = "MFG:" + mk + ";MDL:" + md + ";DES:" + mk + " " + md + ";"
            device.id_dict = cupshelpers.parseDeviceID (device.id)
        # Check whether the device is supported by HPLIP and replace
        # its URI by an HPLIP URI. Add an entry for fax is needed
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

    def fillDeviceTab(self, current_uri=None, query=True):
        if query:
            try:
                devices = self.fetchDevices()
            except cups.IPPError, (e, msg):
                self.show_IPP_Error(e, msg)
                devices = {}
            except:
                devices = {}

            if current_uri:
                print current_uri
                if devices.has_key (current_uri):
                    current = devices.pop(current_uri)
                else:
                    current = cupshelpers.Device (current_uri)
                    current.info = "Current device"
                    if current.type == "smb":
                        self.browse_smb_hosts ()
                print current.info

            self.devices = devices.values()

        for device in self.devices:
            if device.type == "usb":
                # Find USB URIs with corresponding HPLIP URIs and mark them
                # for deleting, so that the user will only get the HPLIP
                # URIs for full device support in the list
                ser = None
                s = device.uri.find ("?serial=")
                if s != -1:
                    s += 8
                    e = device.uri[s:].find ("?")
                    if e == -1: e = len (device.uri)
                    ser = device.uri[s:s+e]
                mod = None
                s = device.uri[6:].find ("/")
                if s != -1:
                    s += 7
                    e = device.uri[s:].find ("?")
                    if e == -1: e = len (device.uri)
                    mod = device.uri[s:s+e].lower ().replace ("%20", "_")
                    if mod.startswith ("hp_"):
                        mod = mod[3:]
                matchfound = 0
                for hpdevice in self.devices:
                    hpser = None
                    hpmod = None
                    uri = hpdevice.uri
                    if not uri.startswith ("hp:"): continue
                    if ser:
                        s = uri.find ("?serial=")
                        if s != -1:
                            s += 8
                            e = uri[s:].find ("?")
                            if e == -1: e = len (uri)
                            hpser = uri[s:s+e]
                            if hpser != ser: continue
                            matchfound = 1
                    if mod and not (ser and hpser):
                        s = uri.find ("/usb/")
                        if s != -1:
                            s += 5
                            e = uri[s:].find ("?")
                            if e == -1: e = len (uri)
                            hpmod = uri[s:s+e].lower ()
                            if hpmod.startswith ("hp_"):
                                hpmod = hpmod[3:]
                            if hpmod != mod: continue
                            matchfound = 1
                    if matchfound == 1: break
                if matchfound == 1:
                    device.uri = "delete"
            if device.type == "hal":
                # Remove HAL USB URIs, for these printers there are already
                # USB URIs
                if device.uri.startswith("hal:///org/freedesktop/Hal/devices/usb_device"):
                    device.uri = "delete"
            try:
                if device.type in ("socket", "lpd", "ipp", "bluetooth"):
                    host = self.getNetworkPrinterMakeModel(device)
                    faxuri = None
                    if host:
                        faxuri = self.get_hplip_uri_for_network_printer(host,
                                                                        "fax")
                    if faxuri:
                        self.devices.append(cupshelpers.Device(faxuri,
                              **{'device-class' : "direct",
                                 'device-info' : device.info + " HP Fax HPLIP",
                                 'device-device-make-and-model' : "HP Fax",
                                 'device-id' : "MFG:HP;MDL:Fax;DES:HP Fax;"}))
                    if device.uri.startswith ("hp:"):
                        device.type = "hp" 
                        device.info += (" HPLIP")
            except:
                nonfatalException ()
        self.devices = filter(lambda x: x.uri not in ("hp:/no_device_found",
                                                      "hpfax:/no_device_found",
                                                      "hp", "hpfax",
                                                      "hal", "beh",
                                                      "scsi", "http", "delete"),
                              self.devices)
        self.devices.sort()

        self.devices.append(cupshelpers.Device('',
             **{'device-info' :_("Other")}))
        if current_uri:
            current.info += _(" (Current)")
            self.devices.insert(0, current)
            self.device = current
        model = self.tvNPDevices.get_model()
        model.clear()

        for device in self.devices:
            model.append((device.info,))
            
        self.tvNPDevices.get_selection().select_path(0)
        self.on_tvNPDevices_cursor_changed(self.tvNPDevices)

    def browse_smb_hosts(self):
        if not self.smb_lock.acquire(0):
            return
        thread.start_new_thread(self.browse_smb_hosts_thread, ())

    def browse_smb_hosts_thread(self):
        """Initialise the SMB tree store."""

        gtk.gdk.threads_enter()
        store = self.smb_store
        store.clear ()
        store.append(None, ('Scanning...', '', None, None))
        try:
            self.busy(self.SMBBrowseDialog)
        except:
            nonfatalException()
        gtk.gdk.threads_leave()



        iter = None
        domains = pysmb.get_domain_list ()

        gtk.gdk.threads_enter()
        store.clear ()
        for domain in domains.keys ():
            d = domains[domain]
            iter = store.append (None)
            if iter:
                dummy = store.append (iter)
            store.set_value (iter, 0, d['DOMAIN'])
            store.set_value (iter, 2, d)

        try:
            self.ready(self.SMBBrowseDialog)
        except:
            nonfatalException()

        self.smb_lock.release()
        gtk.gdk.threads_leave()


    def smb_select_function (self, path):
        """Don't allow this path to be selected unless it is a leaf."""
        iter = self.smb_store.get_iter (path)
        return not self.smb_store.iter_has_child (iter)

    def on_tvSMBBrowser_row_activated (self, view, path, column):
        """Handle double-clicks in the SMB tree view."""
        store = self.smb_store
        iter = store.get_iter (path)
        if store.iter_depth (iter) == 2:
            # This is a share, not a host.
            return

        if view.row_expanded (path):
            view.collapse_row (path)
        else:
            self.on_tvSMBBrowser_row_expanded (view, iter, path)

    def on_tvSMBBrowser_row_expanded (self, view, iter, path):
        """Handler for expanding a row in the SMB tree view."""
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

    def parse_SMBURI (self, uri):
        user = ''
        password = ''
        auth = uri.find ('@')
        if auth != -1:
            u = uri[:auth].find(':')
            if u != -1:
                user = uri[:u]
                password = uri[u + 1:auth]
            else:
                user = uri[:auth]
            uri = uri[auth + 1:]
        sep = uri.count ('/')
        group = ''
        if sep == 2:
            g = uri.find('/')
            group = uri[:g]
            uri = uri[g + 1:]
        if sep < 1:
            host = 'localhost'
        else:
            h = uri.find('/')
            host = uri[:h]
            uri = uri[h + 1:]
            p = host.find(':')
            if p != -1:
                host = host[:p]
        share = uri
        return (urllib.unquote (group), urllib.unquote (host),
                urllib.unquote (share),
                urllib.unquote (user), urllib.unquote (password))

    def construct_SMBURI (self, group, host, share,
                          user = '', password = ''):
        uri_password = ''
        if password:
            uri_password = ':' + urllib.quote (password)
        if user:
            uri_password += '@'
        return "%s%s%s/%s/%s" % (urllib.quote (user),
                                 uri_password, urllib.quote (group),
                                 urllib.quote (host), urllib.quote (share))

    def on_entSMBURI_changed (self, ent):
        try:
            if self.ignore_signals:
                return
        except:
            pass

        uri = ent.get_text ()
        (group, host, share, user, password) = self.parse_SMBURI (uri)
        if user:
            self.entSMBUsername.set_text (user)
        if password:
            self.entSMBPassword.set_text (password)
        self.tvSMBBrowser.get_selection ().unselect_all ()
        if user or password:
            uri = self.construct_SMBURI(group, host, share)
            ent.set_text(uri)
            self.chkSMBAuth.set_active(True)
        
        self.btnSMBVerify.set_sensitive(bool(uri))

    def on_tvSMBBrowser_cursor_changed(self, widget):
        store, iter = self.tvSMBBrowser.get_selection().get_selected()
        self.btnSMBBrowseOk.set_sensitive(iter != None
                                          and store.iter_depth(iter) == 2)

    def on_btnSMBBrowse_clicked(self, button):
        self.btnSMBBrowseOk.set_sensitive(False)
        self.SMBBrowseDialog.show()
        self.browse_smb_hosts()

    def on_btnSMBBrowseOk_clicked(self, button):
        store, iter = self.tvSMBBrowser.get_selection().get_selected()
        if not iter or store.iter_depth(iter) != 2:
            self.SMBBrowseDialog.hide()
            return

        parent_iter = store.iter_parent (iter)
        domain_iter = store.iter_parent (parent_iter)
        group = store.get_value (domain_iter, 0)
        host = store.get_value (parent_iter, 0)
        share = store.get_value (iter, 0)
        uri = self.construct_SMBURI (group, host, share)
        self.ignore_signals = True # Avoid 'changed' signal from Entry
        self.entSMBURI.set_text (uri)
        del self.ignore_signals

        self.SMBBrowseDialog.hide()

    def on_btnSMBBrowseCancel_clicked(self, widget, *args):
        self.SMBBrowseDialog.hide()

    def on_btnSMBBrowseRefresh_clicked(self, button):
        self.browse_smb_hosts()

    def on_chkSMBAuth_toggled(self, widget):
        self.tblSMBAuth.set_sensitive(widget.get_active())

    def on_btnSMBVerify_clicked(self, button):
        uri = self.entSMBURI.get_text ()
        (group, host, share, u, p) = self.parse_SMBURI (uri)
        user = ''
        passwd = ''
        if self.tblSMBAuth.get_property("sensitive"):
            user = self.entSMBUsername.get_text ()
            passwd = self.entSMBPassword.get_text ()
        accessible = pysmb.printer_share_accessible ("//%s/%s" %
                                                     (host, share),
                                                     group = group,
                                                     user = user,
                                                     passwd = passwd)
        if accessible:
            self.lblInfo.set_markup ('<span weight="bold" size="larger">' +
                                     _("Verified") + '</span>\n\n' +
                                     _("This print share is accessible."))
            self.InfoDialog.set_transient_for (self.NewPrinterWindow)
            self.InfoDialog.run()
            self.InfoDialog.hide ()
            return

        self.lblError.set_markup ('<span weight="bold" size="larger">' +
                                  _("Inaccessible") + '</span>\n\n' +
                                  _("This print share is not accessible."))
        self.ErrorDialog.set_transient_for (self.NewPrinterWindow)
        self.ErrorDialog.run()
        self.ErrorDialog.hide ()

    def on_tvNPDevices_cursor_changed(self, widget):
        model, iter = widget.get_selection().get_selected()
        path = model.get_path(iter)
        device = self.devices[path[0]]
        self.device = device
        self.lblNPDeviceDescription.set_text ('')
        page = self.new_printer_device_tabs.get(device.type, 1)
        self.ntbkNPType.set_current_page(page)

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
            if device.uri.startswith ("socket"):
                host = device.uri[9:]
                i = host.find (":")
                if i != -1:
                    port = int (host[i + 1:])
                    host = host[:i]
                else:
                    port = 9100

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
            if device.uri.startswith ("ipp") or device.uri.startswith ("http"):
                server = ""
                printer = ""
                if url[:2] == "//":
                    p = url[2:]
                    t = p.find ('/')
                    if t != -1:
                        server = p[:t]
                        p = p[t + 1:]

                        # Skip over 'printers/' or 'classes/'
                        t = p.find ('/')
                        if t != -1:
                            printer = p[t + 1:]

                self.entNPTIPPHostname.set_text(server)
                self.entNPTIPPPrintername.set_text(printer)
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
        elif device.uri == "lpd":
            pass
        elif device.uri == "smb":
            self.entSMBURI.set_text('')
            self.btnSMBVerify.set_sensitive(False)
        elif device.type == "smb":
            self.entSMBURI.set_text(device.uri[6:])
            self.btnSMBVerify.set_sensitive(True)
        else:
            self.entNPTDevice.set_text(device.uri)

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
            if port:
                device = device + ':' + port
        elif type in ("http", "ipp"): # IPP
            host = self.entNPTIPPHostname.get_text()
            printer = self.entNPTIPPPrintername.get_text()
            device = "ipp://" + host
            if printer:
                device = device + "/printers/" + printer
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
            (group, host, share, u, p) = self.parse_SMBURI (uri)
            user = self.entSMBUsername.get_text ()
            password = self.entSMBPassword.get_text ()
            uri = self.construct_SMBURI (group, host, share, user, password)
            device = "smb://" + uri
        elif not self.device.is_class:
            device = self.device.uri
        else:
            device = self.entNPTDevice.get_text()
        return device
    
    # PPD

    def on_rbtnNPFoomatic_toggled(self, widget):
        foo = self.rbtnNPFoomatic.get_active()
        self.tvNPMakes.set_sensitive(foo)
        self.filechooserPPD.set_sensitive(not foo)
        self.setNPButtons()

    def on_filechooserPPD_selection_changed(self, widget):
        self.setNPButtons()

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
            driver = ppds[self.NPDrivers[i]]["ppd-make-and-model"]
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

    def getNPPPD(self):
        if self.rbtnNPFoomatic.get_active():
            model, iter = self.tvNPDrivers.get_selection().get_selected()
            nr = model.get_path(iter)[0]
            driver = self.NPDrivers[nr]
            return driver
        else:
            return cups.PPD(self.filechooserPPD.get_filename())
            
    # Create new Printer
    def on_btnNPApply_clicked(self, widget):
        if self.dialog_mode in ("class", "printer"):
            name = self.entNPName.get_text()
            location = self.entNPLocation.get_text()
            info = self.entNPDescription.get_text()
        else:
            name = self.printer.name

        # Whether to check for missing drivers.
        check = False
        checkppd = None

        def get_PPD_but_handle_errors ():
            try:
                ppd = self.getNPPPD()
            except RuntimeError, e:
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
                else:
                    # This error came from trying to open the PPD file.
                    err_title = _('PPD error')
                    filename = self.filechooserPPD.get_filename()
                    err = _('Failed to read PPD file.  Possible reason '
                            'follows:') + '\n'
                    os.environ["PPD"] = filename
                    # We want this to be in the current natural language,
                    # so we intentionally don't set LC_ALL=C here.
                    p = os.popen ('/usr/bin/cupstestppd -rvv "$PPD"', 'r')
                    output = p.readlines ()
                    p.close ()
                    err += reduce (lambda x, y: x + y, output)

                error_text = ('<span weight="bold" size="larger">' +
                              err_title + '</span>\n\n' + err)
                self.lblError.set_markup(error_text)
                self.ErrorDialog.set_transient_for(self.NewPrinterWindow)
                self.ErrorDialog.run()
                self.ErrorDialog.hide()
                return None
            return ppd

        if self.dialog_mode=="class":
            members = self.getCurrentClassMembers(self.tvNCMembers)
            try:
                for member in members:
                    self.passwd_retry = False # use cached Passwd 
                    self.cups.addPrinterToClass(member, name)
            except cups.IPPError, (e, msg):
                self.show_IPP_Error(e, msg)
                return
        elif self.dialog_mode=="printer":
            uri = None
            if self.device.uri:
                uri = self.device.uri
            else:
                uri = self.getDeviceURI()
            ppd = get_PPD_but_handle_errors ()
            if not ppd:
                # Go back to previous page to re-select driver.
                self.nextNPTab(-1)
                return

            self.busy (self.NewPrinterWindow)
            self.lblWait.set_markup ('<span weight="bold" size="larger">' +
                                     _('Adding') + '</span>\n\n' +
                                     _('Adding printer'))
            self.WaitWindow.set_transient_for (self.NewPrinterWindow)
            self.WaitWindow.show ()
            while gtk.events_pending ():
                gtk.main_iteration ()
            try:
                self.passwd_retry = False # use cached Passwd
                if isinstance(ppd, str) or isinstance(ppd, unicode):
                    self.cups.addPrinter(name, ppdname=ppd,
                         device=uri, info=info, location=location)
                    check = True
                elif ppd is None: # raw queue
                    self.cups.addPrinter(name, device=uri,
                                         info=info, location=location)
                else:
                    cupshelpers.setPPDPageSize(ppd, self.language[0])
                    self.cups.addPrinter(name, ppd=ppd,
                         device=uri, info=info, location=location)
                    check = True
                    checkppd = ppd

                cupshelpers.activateNewPrinter (self.cups, name)
            except cups.IPPError, (e, msg):
                self.ready (self.NewPrinterWindow)
                self.show_IPP_Error(e, msg)
                self.WaitWindow.hide ()
                return
            self.WaitWindow.hide ()
            self.ready (self.NewPrinterWindow)
        if self.dialog_mode in ("class", "printer"):
            try:
                self.passwd_retry = False # use cached Passwd 
                self.cups.setPrinterLocation(name, location)
                self.passwd_retry = False # use cached Passwd 
                self.cups.setPrinterInfo(name, info)
            except cups.IPPError, (e, msg):
                self.show_IPP_Error(e, msg)
                return
        elif self.dialog_mode == "device":
            try:
                uri = None
                if self.device.uri:
                    uri = self.device.uri
                else:
                    uri = self.getDeviceURI()
                self.passwd_retry = False # use cached Passwd 
                self.cups.addPrinter(name, device=uri)
            except cups.IPPError, (e, msg):
                self.show_IPP_Error(e, msg)
                return
        elif self.dialog_mode == "ppd":
            ppd = get_PPD_but_handle_errors ()
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
                        self.passwd_retry = False # use cached Passwd
                        self.cups.addPrinter(name, ppdname='raw')
                    except cups.IPPError, (e, msg):
                        self.show_IPP_Error(e, msg)
                try:
                    self.passwd_retry = False # use cached Passwd
                    self.cups.addPrinter(name, ppdname=ppd)
                except cups.IPPError, (e, msg):
                    self.show_IPP_Error(e, msg)
                    return

                try:
                    self.passwd_retry = False # use cached Passwd
                    filename = self.cups.getPPD(name)
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
                    cupshelpers.copyPPDOptions(self.ppd, ppd)
                else:
                    cupshelpers.setPPDPageSize(ppd, self.language[0])

                try:
                    self.passwd_retry = False # use cached Passwd
                    self.cups.addPrinter(name, ppd=ppd)
                except cups.IPPError, (e, msg):
                    self.show_IPP_Error(e, msg)

            if not raw:
                check = True
                checkppd = ppd

        self.NewPrinterWindow.hide()
        self.populateList(start_printer=name)
        if check:
            try:
                self.checkDriverExists (name, ppd=checkppd)
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
                filename = self.cups.getPPD(name)
            except cups.IPPError, (e, msg):
                if e == cups.IPP_NOT_FOUND:
                    # This is a raw queue.  Nothing to check.
                    return
                else:
                    self.show_IPP_Error(e, msg)
                    return

            ppd = cups.PPD(filename)
            os.unlink(filename)

        # How to check that something exists in a path:
        def pathcheck (name, path="/usr/bin:/bin"):
            # Strip out foomatic '%'-style place-holders.
            p = name.find ('%')
            if p != -1:
                name = name[:p]
            if len (name) == 0:
                return "true"
            if name[0] == '/':
                if os.access (name, os.X_OK):
                    print "%s: found" % name
                    return name
                else:
                    print "%s: NOT found" % name
                    return None
            if name.find ("=") != -1:
                return "builtin"
            if name in [ ":", ".", "[", "alias", "bind", "break", "cd",
                         "continue", "declare", "echo", "else", "eval",
                         "exec", "exit", "export", "fi", "if", "kill", "let",
                         "local", "popd", "printf", "pushd", "pwd", "read",
                         "readonly", "set", "shift", "shopt", "source",
                         "test", "then", "trap", "type", "ulimit", "umask",
                         "unalias", "unset", "wait" ]:
                return "builtin"
            for component in path.split (':'):
                file = component.rstrip (os.path.sep) + os.path.sep + name
                if os.access (file, os.X_OK):
                    print "%s: found" % file
                    return file
            print "%s: NOT found in %s" % (name,path)
            return None

        # Find a 'FoomaticRIPCommandLine' attribute.
        exe = exepath = None
        attr = ppd.findAttr ('FoomaticRIPCommandLine')
        if attr:
            # Foomatic RIP command line to check.
            cmdline = attr.value.replace ('&&\n', '')
            cmdline = cmdline.replace ('&quot;', '"')
            cmdline = cmdline.replace ('&lt;', '<')
            cmdline = cmdline.replace ('&gt;', '>')
            if (cmdline.find ("(") != -1 or
                cmdline.find ("&") != -1):
                # Don't try to handle sub-shells or unreplaced HTML entities.
                cmdline = ""

            # Strip out foomatic '%'-style place-holders
            pipes = cmdline.split (';')
            for pipe in pipes:
                cmds = pipe.strip ().split ('|')
                for cmd in cmds:
                    args = cmd.strip ().split (' ')
                    exe = args[0]
                    exepath = pathcheck (exe)
                    if not exepath:
                        break

                    # Main executable found.  But if it's 'gs',
                    # perhaps there is an IJS server we also need
                    # to check.
                    if os.path.basename (exepath) == 'gs':
                        argn = len (args)
                        argi = 1
                        search = "-sIjsServer="
                        while argi < argn:
                            arg = args[argi]
                            if arg.startswith (search):
                                exe = arg[len (search):]
                                exepath = pathcheck (exe)
                                break

                            argi += 1

                if not exepath:
                    # Next pipe.
                    break

        if exepath or not exe:
            # Look for '*cupsFilter' lines in the PPD and check that
            # the filters are installed.
            (tmpfd, tmpfname) = tempfile.mkstemp ()
            ppd.writeFd (tmpfd)
            search = "*cupsFilter:"
            for line in file (tmpfname).readlines ():
                if line.startswith (search):
                    line = line[len (search):].strip ().strip ('"')
                    try:
                        (mimetype, cost, exe) = line.split (' ')
                    except:
                        continue

                    exepath = pathcheck (exe,
                                         "/usr/lib/cups/filter:"
                                         "/usr/lib64/cups/filter")

        if exe and not exepath:
            # We didn't find a necessary executable.  Complain.

            # Strip out foomatic '%'-style place-holders.
            p = exe.find ('%')
            if p != -1:
                exe = exe[:p]

            pkgs = {
                # Foomatic command line executables
                'gs': 'ghostscript',
                'perl': 'perl',
                'foo2oak-wrapper': None,
                'pnm2ppa': 'pnm2ppa',
                'c2050': 'c2050',
                'c2070': 'c2070',
                'cjet': 'cjet',
                'lm1100': 'lx',
                'esc-m': 'min12xxw',
                'min12xxw': 'min12xxw',
                'pbm2l2030': 'pbm2l2030',
                'pbm2l7k': 'pbm2l7k',
                'pbm2lex': 'pbm2l7k',
                # IJS servers (used by foomatic)
                'hpijs': 'hpijs',
                'ijsgutenprint.5.0': 'gutenprint',
                # CUPS filters
                'rastertogutenprint.5.0': 'gutenprint-cups',
                'commandtoepson': 'gutenprint-cups',
                'commandtocanon': 'gutenprint-cups',
                }
            try:
                pkg = pkgs[exe]
            except:
                pkg = None

            install = "/usr/bin/system-install-packages"
            if pkg and os.access (install, os.X_OK):
                print "%s included in package %s" % (exe, pkg)
                install_text = ('<span weight="bold" size="larger">' +
                                _('Install driver') + '</span>\n\n' +
                                _("Printer '%s' requires the %s package but "
                                  "it is not currently installed.") %
                                (name, pkg))
                dialog = self.InstallDialog
                self.lblInstall.set_markup(install_text)
            else:
                error_text = ('<span weight="bold" size="larger">' +
                              _('Missing driver') + '</span>\n\n' +
                              _("Printer '%s' requires the '%s' program but "
                                "it is not currently installed.  Please "
                                "install it before using this printer.") %
                              (name, exe))
                dialog = self.ErrorDialog
                self.lblError.set_markup(error_text)

            dialog.set_transient_for (self.MainWindow)
            response = dialog.run ()
            dialog.hide ()
            if pkg and response == gtk.RESPONSE_OK:
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

    ##########################################################################
    ### Server settings
    ##########################################################################

    def fillServerTab(self):
        self.changed = set()
        try:
            self.server_settings = self.cups.adminGetServerSettings()
        except cups.IPPError, (e, m):
            self.show_IPP_Error(e, m)
            self.tvMainList.get_selection().unselect_all()
            self.on_tvMainList_cursor_changed(self.tvMainList)
            return

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
        
    def on_server_changed(self, widget):
        if (str(int(widget.get_active())) ==
            self.server_settings[widget.get_data("setting")]):
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
            self.show_IPP_Error(e, m)
            return True
        except RuntimeError, s:
            self.show_IPP_Error(None, s)
            return True
        self.changed = set()
        self.setDataButtonState()
        time.sleep(1) # give the server a chance to process our request

        # Now reconnect, in case the server needed to reload.
        self.reconnect ()

def main(start_printer = None, change_ppd = False):
    cups.setUser (os.environ.get ("CUPS_USER", cups.getUser()))
    gtk.gdk.threads_init()

    mainwindow = GUI(start_printer, change_ppd)
    if gtk.__dict__.has_key("main"):
        gtk.main()
    else:
        gtk.mainloop()


if __name__ == "__main__":
    import getopt
    try:
        opts, args = getopt.gnu_getopt (sys.argv[1:], '',
                                        ['configure-printer=',
                                         'choose-driver='])
    except getopt.GetoptError:
        show_help ()
        sys.exit (1)

    start_printer = None
    change_ppd = False
    for opt, optarg in opts:
        if (opt == "--configure-printer" or
            opt == "--choose-driver"):
            start_printer = optarg
            if opt == "--choose-driver":
                change_ppd = True

    main(start_printer, change_ppd)

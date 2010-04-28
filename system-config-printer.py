#!/usr/bin/env python

## system-config-printer

## Copyright (C) 2006, 2007, 2008, 2009, 2010 Red Hat, Inc.
## Authors:
##  Tim Waugh <twaugh@redhat.com>
##  Florian Festi <ffesti@redhat.com>

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

import sys, os, tempfile, time, re
import thread
import dbus
try:
    import gtk
except RuntimeError, e:
    print "system-config-printer:", e
    print "This is a graphical application and requires DISPLAY to be set."
    sys.exit (1)

def show_uri (uri):
    gtk.show_uri (gtk.gdk.screen_get_default (),
                  uri,
                  gtk.get_current_event_time ())

gtk.about_dialog_set_url_hook (lambda x, y: show_uri (y))
gtk.about_dialog_set_email_hook (lambda x, y: show_uri ("mailto:" + y))

def show_help():
    print ("\nThis is system-config-printer, " \
           "a CUPS server configuration program.\n\n"
           "Options:\n\n"
           "  --setup-printer URI\n"
           "            Select the (detected) CUPS device URI on start-up,\n"
           "            and run the new-printer wizard for it.\n\n"
           "  --configure-printer NAME\n"
           "            Select the named printer on start-up, and open its\n"
           "            properties dialog.\n\n"
           "  --choose-driver NAME\n"
           "            Select the named printer on start-up, and display\n"
           "            the list of drivers.\n\n"
           "  --print-test-page NAME\n"
           "            Select the named printer on start-up and print a\n"
           "            test page to it.\n\n"
           "  --no-focus-on-map\n"
           "            Do not focus the main window, to prevent focus \n"
           "            stealing\n\n"
           "  --debug   Enable debugging output.\n")

if len(sys.argv)>1 and sys.argv[1] == '--help':
    show_help ()
    sys.exit (0)

import cups
cups.require ("1.9.46")
cups.ppdSetConformance (cups.PPD_CONFORM_RELAXED)

import locale
try:
    locale.setlocale (locale.LC_ALL, "")
except locale.Error:
    os.environ['LC_ALL'] = 'C'
    locale.setlocale (locale.LC_ALL, "")
import gettext
from gettext import gettext as _
gettext.textdomain (config.PACKAGE)
gettext.bindtextdomain (config.PACKAGE, config.localedir)

import cupshelpers, options
import gobject # for TYPE_STRING and TYPE_PYOBJECT
from gui import GtkGUI
from optionwidgets import OptionWidget
from debug import *
import gtk_label_autowrap
import urllib
import troubleshoot
import jobviewer
import authconn
import monitor
import errordialogs
from errordialogs import *
import userdefault
from AdvancedServerSettings import AdvancedServerSettings
from ToolbarSearchEntry import *
from GroupsPane import *
from GroupsPaneModel import *
from SearchCriterion import *
import gtkinklevel
import statereason
import firewall
import newprinter

import ppdippstr
ppdippstr.init ()
pkgdata = config.pkgdatadir
iconpath = os.path.join (pkgdata, 'icons/')
sys.path.append (pkgdata)

busy_cursor = gtk.gdk.Cursor(gtk.gdk.WATCH)

TEXT_start_firewall_tool = _("To do this, select "
                             "System->Administration->Firewall "
                             "from the main menu.")

try:
    try_CUPS_SERVER_REMOTE_ANY = cups.CUPS_SERVER_REMOTE_ANY
except AttributeError:
    # cups module was compiled with CUPS < 1.3
    try_CUPS_SERVER_REMOTE_ANY = "_remote_any"

def CUPS_server_hostname ():
    host = cups.getServer ()
    if host[0] == '/':
        return 'localhost'
    return host

def on_delete_just_hide (widget, event):
    widget.hide ()
    return True # stop other handlers

class GUI(GtkGUI):

    printer_states = { cups.IPP_PRINTER_IDLE: _("Idle"),
                       cups.IPP_PRINTER_PROCESSING: _("Processing"),
                       cups.IPP_PRINTER_BUSY: _("Busy"),
                       cups.IPP_PRINTER_STOPPED: _("Stopped") }

    def __init__(self, setup_printer = None, configure_printer = None,
                 change_ppd = False, devid = "", print_test_page = False,
                 focus_on_map = True):

        try:
            self.language = locale.getlocale(locale.LC_MESSAGES)
            self.encoding = locale.getlocale(locale.LC_CTYPE)
        except:
            nonfatalException()
            os.environ['LC_ALL'] = 'C'
            locale.setlocale (locale.LC_ALL, "")
            self.language = locale.getlocale(locale.LC_MESSAGES)
            self.encoding = locale.getlocale(locale.LC_CTYPE)

        self.printer = self.ppd = None
        self.conflicts = set() # of options
        self.connect_server = (self.printer and self.printer.getServer()) \
                               or cups.getServer()
        self.connect_encrypt = cups.getEncryption ()
        self.connect_user = cups.getUser()

        self.changed = set() # of options

        self.servers = set((self.connect_server,))
        self.server_is_publishing = None # not known
        self.devid = devid
        self.focus_on_map = focus_on_map

        # WIDGETS
        # =======
        self.updating_widgets = False
        self.getWidgets({"PrintersWindow":
                             ["PrintersWindow",
                              "view_area_vbox",
                              "view_area_scrolledwindow",
                              "dests_iconview",
                              "statusbarMain",
                              "toolbar",
                              "server_settings_menu_entry",
                              "new_printer",
                              "new_class",
                              "group_menubar_item",
                              "printer_menubar_item",
                              "view_discovered_printers",
                              "view_groups"],
                         "AboutDialog":
                             ["AboutDialog"],
                         "ConnectDialog":
                             ["ConnectDialog",
                              "chkEncrypted",
                              "cmbServername",
                              "btnConnect"],
                         "ConnectingDialog":
                             ["ConnectingDialog",
                              "lblConnecting",
                              "pbarConnecting"],
                         "NewPrinterName":
                             ["NewPrinterName",
                              "entDuplicateName",
                              "btnDuplicateOk"],
                         "ServerSettingsDialog":
                             ["ServerSettingsDialog",
                              "chkServerBrowse",
                              "chkServerShare",
                              "chkServerShareAny",
                              "chkServerRemoteAdmin",
                              "chkServerAllowCancelAll",
                              "chkServerLogDebug",
                              "hboxServerBrowse",
                              "rbPreserveJobFiles",
                              "rbPreserveJobHistory",
                              "rbPreserveJobNone",
                              "tvBrowseServers",
                              "frameBrowseServers",
                              "btAdvServerAdd",
                              "btAdvServerRemove"],
                         "PrinterPropertiesDialog":
                             ["PrinterPropertiesDialog",
                              "tvPrinterProperties",
                              "btnPrinterPropertiesCancel",
                              "btnPrinterPropertiesOK",
                              "btnPrinterPropertiesApply",
                              "btnPrinterPropertiesClose",
                              "ntbkPrinter",
                              "entPDescription",
                              "entPLocation",
                              "lblPMakeModel",
                              "lblPMakeModel2",
                              "lblPState",
                              "entPDevice",
                              "lblPDevice2",
                              "btnSelectDevice",
                              "btnChangePPD",
                              "chkPEnabled",
                              "chkPAccepting",
                              "chkPShared",
                              "lblNotPublished",
                              "btnPrintTestPage",
                              "btnSelfTest",
                              "btnCleanHeads",
                              "btnConflict",

                              "cmbPStartBanner",
                              "cmbPEndBanner",
                              "cmbPErrorPolicy",
                              "cmbPOperationPolicy",

                              "rbtnPAllow",
                              "rbtnPDeny",
                              "tvPUsers",
                              "entPUser",
                              "btnPAddUser",
                              "btnPDelUser",

                              "lblPInstallOptions",
                              "swPInstallOptions",
                              "vbPInstallOptions",
                              "swPOptions",
                              "lblPOptions",
                              "vbPOptions",
                              "algnClassMembers",
                              "vbClassMembers",
                              "lblClassMembers",
                              "tvClassMembers",
                              "tvClassNotMembers",
                              "btnClassAddMember",
                              "btnClassDelMember",
                              "btnRefreshMarkerLevels",
                              "tvPrinterStateReasons",
                              "ntbkPrinterStateReasons",

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
                              "cmbJOOutputOrder", "btnJOResetOutputOrder",
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

                              # Marker levels
                              "vboxMarkerLevels",
                              "btnRefreshMarkerLevels"]},

                        domain=config.PACKAGE)


        # Ensure the default PrintersWindow is shown despite
        # the --no-focus-on-map option
        self.PrintersWindow.set_focus_on_map (self.focus_on_map)

        # Since some dialogs are reused we can't let the delete-event's
        # default handler destroy them
        for dialog in [self.PrinterPropertiesDialog,
                       self.ServerSettingsDialog]:
            dialog.connect ("delete-event", on_delete_just_hide)

        self.ConnectingDialog.connect ("delete-event",
                                       self.on_connectingdialog_delete)

        gtk.window_set_default_icon_name ('printer')

        # Toolbar
        # Glade-2 doesn't have support for MenuToolButton, so we do that here.
        self.btnNew = gtk.MenuToolButton (gtk.STOCK_ADD)
        self.btnNew.set_is_important (True)
        newmenu = gtk.Menu ()
        newprinteritem = gtk.ImageMenuItem (_("Printer"))
        printericon = gtk.Image ()
        printericon.set_from_icon_name ("printer", gtk.ICON_SIZE_MENU)
        newprinteritem.set_image (printericon)
        newprinteritem.connect ('activate', self.on_new_printer_activate)
        self.btnNew.connect ('clicked', self.on_new_printer_activate)
        newclassitem = gtk.ImageMenuItem (_("Class"))
        classicon = gtk.Image ()
        classicon.set_from_icon_name (gtk.STOCK_DND_MULTIPLE,
                                      gtk.ICON_SIZE_MENU)
        newclassitem.set_image (classicon)
        newclassitem.connect ('activate', self.on_new_class_activate)
        newprinteritem.show ()
        newclassitem.show ()
        newmenu.attach (newprinteritem, 0, 1, 0, 1)
        newmenu.attach (newclassitem, 0, 1, 1, 2)
        self.btnNew.set_menu (newmenu)
        self.toolbar.add (self.btnNew)
        self.toolbar.add (gtk.SeparatorToolItem ())
        refreshbutton = gtk.ToolButton (gtk.STOCK_REFRESH)
        refreshbutton.connect ('clicked', self.on_btnRefresh_clicked)
        self.toolbar.add (refreshbutton)
        self.toolbar.show_all ()

        # Printer Actions
        printer_manager_action_group = \
            gtk.ActionGroup ("PrinterManagerActionGroup")
        printer_manager_action_group.add_actions ([
                ("rename-printer", None, _("_Rename"),
                 None, None, self.on_rename_activate),
                ("duplicate-printer", gtk.STOCK_COPY, _("_Duplicate"),
                 "<Ctrl>d", None, self.on_duplicate_activate),
                ("delete-printer", gtk.STOCK_DELETE, None,
                 None, None, self.on_delete_activate),
                ("set-default-printer", gtk.STOCK_HOME, _("Set As De_fault"),
                 None, None, self.on_set_as_default_activate),
                ("edit-printer", gtk.STOCK_PROPERTIES, None,
                 None, None, self.on_edit_activate),
                ("create-class", gtk.STOCK_DND_MULTIPLE, _("_Create class"),
                 None, None, self.on_create_class_activate),
                ("view-print-queue", gtk.STOCK_FIND, _("View Print _Queue"),
                 None, None, self.on_view_print_queue_activate),
                ("add-to-group", None, _("_Add to Group"),
                 None, None, None),
                ("save-as-group", None, _("Save Results as _Group"),
                 None, None, self.on_save_as_group_activate),
                ("save-as-search-group", None, _("Save Filter as _Search Group"),
                 None, None, self.on_save_as_search_group_activate),
                ])
        printer_manager_action_group.add_toggle_actions ([
                ("enable-printer", None, _("E_nabled"),
                 None, None, self.on_enabled_activate),
                ("share-printer", None, _("_Shared"),
                 None, None, self.on_shared_activate),
                ])
        printer_manager_action_group.add_radio_actions ([
                ("filter-name", None, _("Name")),
                ("filter-description", None, _("Description")),
                ("filter-location", None, _("Location")),
                ("filter-manufacturer", None, _("Manufacturer / Model")),
                ], 1, self.on_filter_criterion_changed)
        for action in printer_manager_action_group.list_actions ():
            action.set_sensitive (False)
        printer_manager_action_group.get_action ("view-print-queue").set_sensitive (True)
        printer_manager_action_group.get_action ("filter-name").set_sensitive (True)
        printer_manager_action_group.get_action ("filter-description").set_sensitive (True)
        printer_manager_action_group.get_action ("filter-location").set_sensitive (True)
        printer_manager_action_group.get_action ("filter-manufacturer").set_sensitive (True)

        self.ui_manager = gtk.UIManager ()
        self.ui_manager.insert_action_group (printer_manager_action_group, -1)
        self.ui_manager.add_ui_from_string (
"""
<ui>
 <accelerator action="rename-printer"/>
 <accelerator action="duplicate-printer"/>
 <accelerator action="delete-printer"/>
 <accelerator action="set-default-printer"/>
 <accelerator action="edit-printer"/>
 <accelerator action="create-class"/>
 <accelerator action="view-print-queue"/>
 <accelerator action="add-to-group"/>
 <accelerator action="save-as-group"/>
 <accelerator action="save-as-search-group"/>
 <accelerator action="enable-printer"/>
 <accelerator action="share-printer"/>
 <accelerator action="filter-name"/>
 <accelerator action="filter-description"/>
 <accelerator action="filter-location"/>
 <accelerator action="filter-manufacturer"/>
</ui>
"""
)
        self.ui_manager.ensure_update ()
        self.PrintersWindow.add_accel_group (self.ui_manager.get_accel_group ())

        self.printer_context_menu = gtk.Menu ()
        for action_name in ["edit-printer",
                            "duplicate-printer",
                            "rename-printer",
                            "delete-printer",
                            None,
                            "enable-printer",
                            "share-printer",
                            "create-class",
                            "set-default-printer",
                            None,
                            "add-to-group",
                            "view-print-queue"]:
            if not action_name:
                item = gtk.SeparatorMenuItem ()
            else:
                action = printer_manager_action_group.get_action (action_name)
                item = action.create_menu_item ()
            item.show ()
            self.printer_context_menu.append (item)
        self.printer_menubar_item.set_submenu (self.printer_context_menu)

        self.jobviewers = [] # to keep track of jobviewer windows

        # Printer properties combo boxes
        for combobox in [self.cmbPStartBanner,
                         self.cmbPEndBanner,
                         self.cmbPErrorPolicy,
                         self.cmbPOperationPolicy]:
            cell = gtk.CellRendererText ()
            combobox.clear ()
            combobox.pack_start (cell, True)
            combobox.add_attribute (cell, 'text', 0)

        btn = self.btnRefreshMarkerLevels
        btn.connect ("clicked", self.on_btnRefreshMarkerLevels_clicked)

        # Printer state reasons list
        column = gtk.TreeViewColumn (_("Message"))
        icon = gtk.CellRendererPixbuf ()
        column.pack_start (icon, False)
        text = gtk.CellRendererText ()
        column.pack_start (text, False)
        column.set_cell_data_func (icon, self.set_printer_state_reason_icon)
        column.set_cell_data_func (text, self.set_printer_state_reason_text)
        column.set_resizable (True)
        self.tvPrinterStateReasons.append_column (column)
        selection = self.tvPrinterStateReasons.get_selection ()
        selection.set_mode (gtk.SELECTION_NONE)
        store = gtk.ListStore (int, str)
        self.tvPrinterStateReasons.set_model (store)

        # New Printer Dialog
        self.newPrinterGUI = np = newprinter.NewPrinterGUI(self)
        np.connect ("printer-added", self.new_printer_added)

        # Set up "About" dialog
        self.AboutDialog.set_program_name(config.PACKAGE)
        self.AboutDialog.set_version(config.VERSION)
        self.AboutDialog.set_icon_name('printer')

        # Set up "Problems?" link button
        class UnobtrusiveButton(gtk.Button):
            def __init__ (self, **args):
                gtk.Button.__init__ (self, **args)
                self.set_relief (gtk.RELIEF_NONE)
                label = self.get_child ()
                text = label.get_text ()
                label.set_use_markup (True)
                label.set_markup ('<span size="small" ' +
                                  'underline="single" ' +
                                  'color="#0000ee">%s</span>' % text)

        problems = UnobtrusiveButton (label=_("Problems?"))
        self.hboxServerBrowse.pack_end (problems, False, False, 0)
        problems.connect ('clicked', self.on_problems_button_clicked)
        problems.show ()

        self.static_tabs = 3

        gtk_label_autowrap.set_autowrap(self.PrintersWindow)

        try:
            self.cups = authconn.Connection(self.PrintersWindow)
        except RuntimeError:
            self.cups = None

        self.status_context_id = self.statusbarMain.get_context_id(
            "Connection")
        self.setConnected()

        # Setup search and printer groups
        self.setup_toolbar_for_search_entry ()
        self.current_filter_text = ""
        self.current_filter_mode = "filter-name"

        self.groups_pane = GroupsPane ()
        self.current_groups_pane_item = self.groups_pane.get_selected_item ()
        self.groups_pane.connect ('item-activated',
                                  self.on_groups_pane_item_activated)
        self.groups_pane.connect ('items-changed',
                                  self.on_groups_pane_items_changed)
        self.PrintersWindow.add_accel_group (
            self.groups_pane.ui_manager.get_accel_group ())
        self.view_area_hpaned = gtk.HPaned ()
        self.view_area_hpaned.add1 (self.groups_pane)
        self.groups_pane_visible = False
        if self.groups_pane.n_groups () > 0:
            self.view_groups.set_active (True)

        # Group menubar item
        self.group_menubar_item.set_submenu (self.groups_pane.groups_menu)

        # "Add to Group" submenu
        self.add_to_group_menu = gtk.Menu ()
        self.update_add_to_group_menu ()
        action = printer_manager_action_group.get_action ("add-to-group")
        for proxy in action.get_proxies ():
            if isinstance (proxy, gtk.MenuItem):
                item = proxy
                break
        item.set_submenu (self.add_to_group_menu)

        # Search entry drop down menu
        menu = gtk.Menu ()
        for action_name in ["filter-name",
                            "filter-description",
                            "filter-location",
                            "filter-manufacturer",
                            None,
                            "save-as-group",
                            "save-as-search-group"]:
            if not action_name:
                item = gtk.SeparatorMenuItem ()
            else:
                action = printer_manager_action_group.get_action (action_name)
                item = action.create_menu_item ()
            menu.append (item)
        menu.show_all ()
        self.search_entry.set_drop_down_menu (menu)

        # Setup icon view
        self.mainlist = gtk.ListStore(gobject.TYPE_PYOBJECT, # Object
                                      gtk.gdk.Pixbuf,        # Pixbuf
                                      gobject.TYPE_STRING,   # Name
                                      gobject.TYPE_STRING)   # Tooltip

        self.dests_iconview.set_model(self.mainlist)
        self.dests_iconview.set_column_spacing (30)
        self.dests_iconview.set_row_spacing (20)
        self.dests_iconview.set_pixbuf_column (1)
        self.dests_iconview.set_text_column (2)
        self.dests_iconview.set_tooltip_column (3)
        self.dests_iconview.set_has_tooltip(True)
        self.dests_iconview.connect ('key-press-event',
                                     self.dests_iconview_key_press_event)
        self.dests_iconview.connect ('item-activated',
                                     self.dests_iconview_item_activated)
        self.dests_iconview.connect ('selection-changed',
                                     self.dests_iconview_selection_changed)
        self.dests_iconview.connect ('button-press-event',
                                     self.dests_iconview_button_press_event)
        self.dests_iconview.connect ('popup-menu',
                                     self.dests_iconview_popup_menu)
        self.dests_iconview_selection_changed (self.dests_iconview)
        self.dests_iconview.enable_model_drag_source (gtk.gdk.BUTTON1_MASK,
                                                      # should use a variable
                                                      # instead of 0
                                                      [("queue", 0, 0)],
                                                      gtk.gdk.ACTION_COPY)
        self.dests_iconview.connect ("drag-data-get",
                                     self.dests_iconview_drag_data_get)

        # setup some lists
        m = gtk.SELECTION_MULTIPLE
        s = gtk.SELECTION_SINGLE
        b = gtk.SELECTION_BROWSE
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
            (_("Downloadable Drivers"), np.tvNPDownloadableDrivers, b),
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
        for (widget,
             opts) in [(self.cmbJOOrientationRequested,
                        [[_("Portrait (no rotation)")],
                         [_("Landscape (90 degrees)")],
                         [_("Reverse landscape (270 degrees)")],
                         [_("Reverse portrait (180 degrees)")]]),

                       (self.cmbJONumberUp,
                        [["1"], ["2"], ["4"], ["6"], ["9"], ["16"]]),

                       (self.cmbJONumberUpLayout,
                        [[_("Left to right, top to bottom")],
                         [_("Left to right, bottom to top")],
                         [_("Right to left, top to bottom")],
                         [_("Right to left, bottom to top")],
                         [_("Top to bottom, left to right")],
                         [_("Top to bottom, right to left")],
                         [_("Bottom to top, left to right")],
                         [_("Bottom to top, right to left")]]),

                       (self.cmbJOFinishings,
  # See section 4.2.6 of this document for explanation of finishing types:
  # ftp://ftp.pwg.org/pub/pwg/candidates/cs-ippfinishings10-20010205-5100.1.pdf
                        [[_("None")],
                         [_("Staple")],
                         [_("Punch")],
                         [_("Cover")],
                         [_("Bind")],
                         [_("Saddle stitch")],
                         [_("Edge stitch")],
                         [_("Fold")],
                         [_("Trim")],
                         [_("Bale")],
                         [_("Booklet maker")],
                         [_("Job offset")],
                         [_("Staple (top left)")],
                         [_("Staple (bottom left)")],
                         [_("Staple (top right)")],
                         [_("Staple (bottom right)")],
                         [_("Edge stitch (left)")],
                         [_("Edge stitch (top)")],
                         [_("Edge stitch (right)")],
                         [_("Edge stitch (bottom)")],
                         [_("Staple dual (left)")],
                         [_("Staple dual (top)")],
                         [_("Staple dual (right)")],
                         [_("Staple dual (bottom)")],
                         [_("Bind (left)")],
                         [_("Bind (top)")],
                         [_("Bind (right)")],
                         [_("Bind (bottom)")]]),

                       (self.cmbJOMedia, []),

                       (self.cmbJOSides,
                        [[_("One-sided")],
                         [_("Two-sided (long edge)")],
                         [_("Two-sided (short edge)")]]),

                       (self.cmbJOHoldUntil, []),

                       (self.cmbJOOutputOrder,
                        [[_("Normal")],
                         [_("Reverse")]]),

                       ]:
            model = gtk.ListStore (gobject.TYPE_STRING)
            for row in opts:
                model.append (row=row)

            cell = gtk.CellRendererText ()
            widget.pack_start (cell, True)
            widget.add_attribute (cell, 'text', 0)
            widget.set_model (model)

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

                 options.OptionAlwaysShown ("outputorder", str,
                                            "normal",
                                            self.cmbJOOutputOrder,
                                            self.btnJOResetOutputOrder,
                                            combobox_map =
                                            [ "normal",
                                              "reverse" ]),

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

                 options.OptionAlwaysShown ("page-left", int, 0,
                                            self.sbJOPageLeft,
                                            self.btnJOResetPageLeft),

                 options.OptionAlwaysShown ("page-right", int, 0,
                                            self.sbJOPageRight,
                                            self.btnJOResetPageRight),

                 options.OptionAlwaysShown ("page-top", int, 0,
                                            self.sbJOPageTop,
                                            self.btnJOResetPageTop),

                 options.OptionAlwaysShown ("page-bottom", int, 0,
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

        self.monitor = monitor.Monitor (monitor_jobs=False)
        self.monitor.connect ('printer-added', self.printer_added)
        self.monitor.connect ('printer-event', self.printer_event)
        self.monitor.connect ('printer-removed', self.printer_removed)
        self.monitor.connect ('state-reason-added', self.state_reason_added)
        self.monitor.connect ('state-reason-removed', self.state_reason_removed)
        self.monitor.connect ('cups-connection-error',
                              self.cups_connection_error)
        self.monitor.refresh ()

        try:
            self.populateList()
        except cups.HTTPError, (s,):
            self.cups = None
            self.setConnected()
            self.populateList()
            show_HTTP_Error(s, self.PrintersWindow)

        if len (self.printers) > 3:
            self.PrintersWindow.set_default_size (550, 400)

        self.PrintersWindow.show()

        if setup_printer:
            self.device_uri = setup_printer
            self.devid = devid
            self.ppd = None
            try:
                self.on_autodetected_printer_without_driver(None)
            except RuntimeError:
                pass

        if configure_printer:
            # Need to find the entry in the iconview model and activate it.
            try:
                self.display_properties_dialog_for (configure_printer)
                if print_test_page:
                    self.btnPrintTestPage.clicked ()
                if change_ppd:
                    self.btnChangePPD.clicked ()
            except RuntimeError:
                pass

    def display_properties_dialog_for (self, queue):
        model = self.dests_iconview.get_model ()
        iter = model.get_iter_first ()
        while iter != None:
            name = unicode (model.get_value (iter, 2))
            if name == queue:
                path = model.get_path (iter)
                self.dests_iconview.scroll_to_path (path, True, 0.5, 0.5)
                self.dests_iconview.set_cursor (path)
                self.dests_iconview.item_activated (path)
                break
            iter = model.iter_next (iter)

        if iter == None:
            raise RuntimeError

    def setup_toolbar_for_search_entry (self):
        separator = gtk.SeparatorToolItem ()
        separator.set_draw (False)

        self.toolbar.insert (separator, -1)
        self.toolbar.child_set_property (separator, "expand", True)

        self.search_entry = ToolbarSearchEntry ()
        self.search_entry.connect ('search', self.on_search_entry_search)

        tool_item = gtk.ToolItem ()
        tool_item.add (self.search_entry)
        self.toolbar.insert (tool_item, -1)
        self.toolbar.show_all ()

    def on_search_entry_search (self, UNUSED, text):
        self.ui_manager.get_action ("/save-as-group").set_sensitive (
            text and True or False)
        self.ui_manager.get_action ("/save-as-search-group").set_sensitive (
            text and True or False)
        self.current_filter_text = text
        self.populateList ()

    def on_groups_pane_item_activated (self, UNUSED, item):
        self.search_entry.clear ()

        if isinstance (item, SavedSearchGroupItem):
            crit = item.criteria[0]
            if crit.subject == SearchCriterion.SUBJECT_NAME:
                self.ui_manager.get_action ("/filter-name").activate ()
            elif crit.subject == SearchCriterion.SUBJECT_DESC:
                self.ui_manager.get_action ("/filter-description").activate ()
            elif crit.subject == SearchCriterion.SUBJECT_LOCATION:
                self.ui_manager.get_action ("/filter-location").activate ()
            elif crit.subject == SearchCriterion.SUBJECT_MANUF:
                self.ui_manager.get_action ("/filter-manufacturer").activate ()
            else:
                nonfatalException ()

            self.search_entry.set_text (crit.value)

        self.current_groups_pane_item = item
        self.populateList ()

    def on_add_to_group_menu_item_activate (self, menuitem, group):
        group.add_queues (self.groups_pane.currently_selected_queues)

    def update_add_to_group_menu (self):
        for child in self.add_to_group_menu.get_children ():
            self.add_to_group_menu.remove (child)
        static_groups = self.groups_pane.get_static_groups ()
        for group in static_groups:
            item = gtk.MenuItem (group.name, False)
            item.connect ("activate",
                          self.on_add_to_group_menu_item_activate, group)
            self.add_to_group_menu.append (item)
        if len (static_groups) > 0:
            item = gtk.SeparatorMenuItem ()
            self.add_to_group_menu.append (item)
        action = self.groups_pane.ui_manager.get_action ("/new-group-from-selection")
        item = action.create_menu_item ()
        self.add_to_group_menu.append (item)
        self.add_to_group_menu.show_all ()

    def on_groups_pane_items_changed (self, UNUSED):
        if not self.groups_pane_visible:
            self.view_groups.set_active (True)
        self.update_add_to_group_menu ()

    def on_filter_criterion_changed (self, UNUSED, selected_action):
        self.current_filter_mode = selected_action.get_name ()
        self.populateList ()

    def dests_iconview_item_activated (self, iconview, path):
        model = iconview.get_model ()
        iter = model.get_iter (path)
        name = unicode (model.get_value (iter, 2))
        object = model.get_value (iter, 0)

        try:
            self.fillPrinterTab (name)
        except cups.IPPError, (e, m):
            show_IPP_Error (e, m, self.PrintersWindow)
            if e == cups.IPP_SERVICE_UNAVAILABLE:
                self.cups = None
                self.setConnected ()
                self.populateList ()
            return
        except RuntimeError:
            # Perhaps cupsGetPPD2 failed for a browsed printer.
            return

        self.PrinterPropertiesDialog.set_transient_for (self.PrintersWindow)
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
        self.btnPrintTestPage.set_tooltip_text(_("CUPS test page"))
        self.btnSelfTest.set_tooltip_text(_("Typically shows whether all jets "
                                            "on a print head are functioning "
                                            "and that the print feed mechanisms"
                                            " are working properly."))
        treeview = self.tvPrinterProperties
        treeview.set_cursor ((0,))
        host = CUPS_server_hostname ()
        self.PrinterPropertiesDialog.set_title (_("Printer Properties - "
                                                  "'%s' on %s") % (name, host))
        self.PrinterPropertiesDialog.set_focus_on_map (self.focus_on_map)
        self.PrinterPropertiesDialog.show ()

    def printer_properties_response (self, dialog, response):
        if response == gtk.RESPONSE_REJECT:
            # The Conflict button was pressed.
            message = _("There are conflicting options.\n"
                        "Changes can only be applied after\n"
                        "these conflicts are resolved.")
            message += "\n\n"
            for option in self.conflicts:
                message += option.option.text + "\n"

            dialog = gtk.MessageDialog(self.PrinterPropertiesDialog,
                                       gtk.DIALOG_DESTROY_WITH_PARENT |
                                       gtk.DIALOG_MODAL,
                                       gtk.MESSAGE_WARNING,
                                       gtk.BUTTONS_CLOSE,
                                       message)
            dialog.run()
            dialog.destroy()
            return

        if (response == gtk.RESPONSE_OK or
            response == gtk.RESPONSE_APPLY):
            failed = self.save_printer (self.printer)

        if response == gtk.RESPONSE_APPLY and not failed:
            try:
                self.fillPrinterTab (self.printer.name)
            except:
                pass

            self.setDataButtonState ()

        if ((response == gtk.RESPONSE_OK and not failed) or
            response == gtk.RESPONSE_CANCEL):
            self.printer = None
            dialog.hide ()

            if self.newPrinterGUI.NewPrinterWindow.get_property ("visible"):
                self.newPrinterGUI.on_NPCancel (None)

    def dests_iconview_selection_changed (self, iconview):
        self.updating_widgets = True
        paths = iconview.get_selected_items ()
        any_disabled = False
        any_enabled = False
        any_discovered = False
        any_shared = False
        any_unshared = False
        self.groups_pane.currently_selected_queues = []
        model = iconview.get_model ()
        for path in paths:
            iter = model.get_iter (path)
            object = model.get_value (iter, 0)
            name = unicode (model.get_value (iter, 2))
            self.groups_pane.currently_selected_queues.append (name)
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

        n = len (paths)
        self.groups_pane.ui_manager.get_action (
            "/new-group-from-selection").set_sensitive (n > 0)

        self.ui_manager.get_action ("/edit-printer").set_sensitive (n == 1)

        self.ui_manager.get_action ("/duplicate-printer").set_sensitive (n == 1)

        self.ui_manager.get_action ("/rename-printer").set_sensitive (
            n == 1 and not any_discovered)

        userdef = userdefault.UserDefaultPrinter ().get ()
        if (n != 1 or
            (userdef == None and self.default_printer == name)):
            set_default_sensitivity = False
        else:
            set_default_sensitivity = True

        self.ui_manager.get_action ("/set-default-printer").set_sensitive (
            set_default_sensitivity)

        action = self.ui_manager.get_action ("/enable-printer")
        action.set_sensitive (n > 0 and not any_discovered)
        for widget in action.get_proxies ():
            if isinstance (widget, gtk.CheckMenuItem):
                widget.set_inconsistent (n > 1 and any_enabled and any_disabled)
        action.set_active (any_discovered or not any_disabled)

        action = self.ui_manager.get_action ("/share-printer")
        action.set_sensitive (n > 0 and not any_discovered)
        for widget in action.get_proxies ():
            if isinstance (widget, gtk.CheckMenuItem):
                widget.set_inconsistent (n > 1 and any_shared and any_unshared)
        action.set_active (any_discovered or not any_unshared)

        self.ui_manager.get_action ("/delete-printer").set_sensitive (
            n > 0 and not any_discovered)

        self.ui_manager.get_action ("/create-class").set_sensitive (n > 1)

        self.ui_manager.get_action ("/add-to-group").set_sensitive (n > 0)

        self.updating_widgets = False

    def dests_iconview_popup_menu (self, iconview):
        self.printer_context_menu.popup (None, None, None, 0, 0L)

    def dests_iconview_button_press_event (self, iconview, event):
        if event.button > 1:
            click_path = iconview.get_path_at_pos (int (event.x),
                                                   int (event.y))
            paths = iconview.get_selected_items ()
            if click_path == None:
                iconview.unselect_all ()
            elif click_path not in paths:
                iconview.unselect_all ()
                iconview.select_path (click_path)
                cells = iconview.get_cells ()
                for cell in cells:
                    if type (cell) == gtk.CellRendererText:
                        break
                iconview.set_cursor (click_path, cell)
            self.printer_context_menu.popup (None, None, None,
                                             event.button, event.time)
        return False

    def dests_iconview_key_press_event (self, iconview, event):
        modifiers = gtk.accelerator_get_default_mod_mask ()

        if ((event.keyval == gtk.keysyms.BackSpace or
             event.keyval == gtk.keysyms.Delete or
             event.keyval == gtk.keysyms.KP_Delete) and
            ((event.state & modifiers) == 0)):

            self.ui_manager.get_action ("/delete-printer").activate ()
            return True

        if ((event.keyval == gtk.keysyms.F2) and
            ((event.state & modifiers) == 0)):

            self.ui_manager.get_action ("/rename-printer").activate ()
            return True

        return False

    def dests_iconview_drag_data_get (self, iconview, context,
                                      selection_data, info, timestamp):
        if info == 0: # FIXME: should use an "enum" here
            model = iconview.get_model ()
            paths = iconview.get_selected_items ()
            selected_printer_names = ""
            for path in paths:
                selected_printer_names += \
                    model.get_value (model.get_iter (path), 2) + "\n"

            if len (selected_printer_names) > 0:
                selection_data.set ("queue", 8, selected_printer_names)
        else:
            nonfatalException ()

    def on_server_settings_activate (self, menuitem):
        try:
            self.fillServerTab ()
            self.advancedServerSettings = AdvancedServerSettings(self,
                                             self.on_adv_server_settings_apply)
        except cups.IPPError:
            # Not authorized.
            return

        self.ServerSettingsDialog.set_transient_for (self.PrintersWindow)
        self.ServerSettingsDialog.show ()

    def server_settings_response (self, dialog, response):
        self.advancedServerSettings.on_response(dialog, response)
        if response == gtk.RESPONSE_OK:
            if not self.save_serversettings ():
                dialog.hide ()
        else:
            dialog.hide ()

    # Add button on 'Advanced Server Settings' clicked
    def on_adv_server_add_clicked (self, button):
        self.advancedServerSettings.on_add_clicked(button)

    # Remove button on 'Advanced Server Settings' clicked
    def on_adv_server_remove_clicked (self, button):
        self.advancedServerSettings.on_remove_clicked(button)

    def on_adv_server_settings_apply (self):
        self.cups._begin_operation (_("fetching server settings"))
        try:
            self.server_settings = self.cups.adminGetServerSettings()
        except cups.IPPError, (e, m):
            show_IPP_Error(e, m, self.PrintersWindow)
            self.cups._end_operation ()
            raise
        self.cups._end_operation ()

    def busy (self, win = None):
        try:
            if not win:
                win = self.PrintersWindow
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
                win = self.PrintersWindow
            gdkwin = win.window
            if gdkwin:
                gdkwin.set_cursor (None)
                while gtk.events_pending ():
                    gtk.main_iteration ()
        except:
            nonfatalException ()

    def setConnected(self):
        connected = bool(self.cups)

        host = CUPS_server_hostname ()
        self.PrintersWindow.set_title(_("Printing - %s") % host)
        self.PrintersWindow.set_focus_on_map (self.focus_on_map)

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
                       self.chkServerLogDebug,
                       self.server_settings_menu_entry):
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
            name = unicode (model.get_value (iter, 2))
            selected_printers.add (name)

        if self.cups:
            self.cups._set_prompt_allowed (prompt_allowed)
            self.cups._begin_operation (_("obtaining queue details"))
            try:
                # get Printers
                self.printers = cupshelpers.getPrinters(self.cups)

                # Get default printer.
                self.default_printer = self.cups.getDefault ()
            except cups.IPPError, (e, m):
                show_IPP_Error(e, m, self.PrintersWindow)
                self.printers = {}
                self.default_printer = None

            self.cups._end_operation ()
            self.cups._set_prompt_allowed (True)
        else:
            self.printers = {}
            self.default_printer = None

        for name, printer in self.printers.iteritems():
            self.servers.add(printer.getServer())

        userdef = userdefault.UserDefaultPrinter ().get ()

        local_printers = []
        local_classes = []
        remote_printers = []
        remote_classes = []

        # Choose a view according to the groups pane item
        if (isinstance (self.current_groups_pane_item, AllPrintersItem) or
            isinstance (self.current_groups_pane_item, SavedSearchGroupItem)):
            delete_action = self.ui_manager.get_action ("/delete-printer")
            delete_action.set_properties (label = None)
            printers_set = self.printers
        elif isinstance (self.current_groups_pane_item, FavouritesItem):
            printers_set = {} # FIXME
        elif isinstance (self.current_groups_pane_item, StaticGroupItem):
            delete_action = self.ui_manager.get_action ("/delete-printer")
            delete_action.set_properties (label = _("Remove from Group"))
            printers_set = {}
            deleted_printers = []
            for printer_name in self.current_groups_pane_item.printer_queues:
                try:
                    printer = self.printers[printer_name]
                    printers_set[printer_name] = printer
                except KeyError:
                    deleted_printers.append (printer_name)
            self.current_groups_pane_item.remove_queues (deleted_printers)
        else:
            printers_set = self.printers
            nonfatalException ()

        # Filter printers
        if len (self.current_filter_text) > 0:
            printers_subset = {}
            pattern = re.compile (self.current_filter_text, re.I) # ignore case

            if self.current_filter_mode == "filter-name":
                for name in printers_set.keys ():
                    if pattern.search (name) != None:
                        printers_subset[name] = printers_set[name]
            elif self.current_filter_mode == "filter-description":
                for name, printer in printers_set.iteritems ():
                    if pattern.search (printer.info) != None:
                        printers_subset[name] = printers_set[name]
            elif self.current_filter_mode == "filter-location":
                for name, printer in printers_set.iteritems ():
                    if pattern.search (printer.location) != None:
                        printers_subset[name] = printers_set[name]
            elif self.current_filter_mode == "filter-manufacturer":
                for name, printer in printers_set.iteritems ():
                    if pattern.search (printer.make_and_model) != None:
                        printers_subset[name] = printers_set[name]
            else:
                nonfatalException ()

            printers_set = printers_subset

        if not self.view_discovered_printers.get_active ():
            printers_subset = {}
            for name, printer in printers_set.iteritems ():
                if not printer.discovered:
                    printers_subset[name] = printer

            printers_set = printers_subset

        for name, printer in printers_set.iteritems():
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
                              'printer'),
                         'local-fax':
                             (_("Fax"),
                              'printer'),
                         'local-class':
                             (_("Class"),
                              'printer'),
                         'ipp-printer':
                             (_("Network printer"),
                              'i-network-printer'),
                         'smb-printer':
                             (_("Network print share"),
                              'printer'),
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
                object = printers_set[name]
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

                def_emblem = None
                emblem = None
                if name == self.default_printer:
                    def_emblem = 'emblem-default'
                elif name == userdef:
                    def_emblem = 'emblem-favorite'

                if not emblem:
                    attrs = object.other_attributes
                    reasons = attrs.get ('printer-state-reasons', [])
                    worst_reason = None
                    for reason in reasons:
                        if reason == "none":
                            break

                        if reason == "paused":
                            emblem = gtk.STOCK_MEDIA_PAUSE
                            continue

                        r = statereason.StateReason (object.connection,
                                                     object.name, reason)
                        if worst_reason == None:
                            worst_reason = r
                        elif r > worst_reason:
                            worst_reason = r

                    if worst_reason:
                        level = worst_reason.get_level ()
                        emblem = worst_reason.LEVEL_ICON[level]

                if not emblem and not object.enabled:
                    emblem = gtk.STOCK_MEDIA_PAUSE

                if object.rejecting:
                    # Show the icon as insensitive
                    copy = pixbuf.copy ()
                    copy.fill (0)
                    pixbuf.composite (copy, 0, 0,
                                      copy.get_width(), copy.get_height(),
                                      0, 0, 1.0, 1.0,
                                      gtk.gdk.INTERP_BILINEAR, 127)
                    pixbuf = copy

                if def_emblem:
                    (w, h) = gtk.icon_size_lookup (gtk.ICON_SIZE_DIALOG)
                    try:
                        default_emblem = theme.load_icon (def_emblem, w/2, 0)
                        copy = pixbuf.copy ()
                        default_emblem.composite (copy, 0, 0,
                                                  copy.get_width (),
                                                  copy.get_height (),
                                                  0, 0,
                                                  1.0, 1.0,
                                                  gtk.gdk.INTERP_NEAREST, 255)
                        pixbuf = copy
                    except gobject.GError:
                        debugprint ("No %s icon available" % def_emblem)

                if emblem:
                    (w, h) = gtk.icon_size_lookup (gtk.ICON_SIZE_DIALOG)
                    try:
                        other_emblem = theme.load_icon (emblem, w/2, 0)
                        copy = pixbuf.copy ()
                        other_emblem.composite (copy, 0, 0,
                                                copy.get_width (),
                                                copy.get_height (),
                                                copy.get_width () / 2,
                                                copy.get_height () / 2,
                                                1.0, 1.0,
                                                gtk.gdk.INTERP_NEAREST, 255)
                        pixbuf = copy
                    except gobject.GError:
                        debugprint ("No %s icon available" % emblem)

                self.mainlist.append (row=[object, pixbuf, name, tip])

        # Restore selection of printers.
        model = self.dests_iconview.get_model ()
        def maybe_select (model, path, iter):
            name = unicode (model.get_value (iter, 2))
            if name in selected_printers:
                self.dests_iconview.select_path (path)
        model.foreach (maybe_select)

        if (self.printer != None and
            self.printer.name not in self.printers.keys ()):
            # The printer we're editing has been deleted.
            self.PrinterPropertiesDialog.response (gtk.RESPONSE_CANCEL)

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
        self.cmbServername.set_text_column (0)
        for server in servers:
            self.cmbServername.append_text(server)
        self.cmbServername.show()

        self.cmbServername.child.set_text (current_server)
        self.chkEncrypted.set_active (cups.getEncryption() ==
                                      cups.HTTP_ENCRYPT_ALWAYS)

        self.cmbServername.child.set_activates_default (True)
        self.cmbServername.grab_focus ()
        self.ConnectDialog.set_transient_for (self.PrintersWindow)
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

        self.lblConnecting.set_markup(_("<i>Opening connection to %s</i>") %
                                      servername)
        self.newPrinterGUI.dropPPDs()
        self.ConnectingDialog.set_transient_for(self.PrintersWindow)
        self.ConnectingDialog.show()
        gobject.timeout_add (40, self.update_connecting_pbar)
        self.connect_server = servername
        # We need to set the connecting user in this thread as well.
        cups.setServer(self.connect_server)
        cups.setUser('')
        self.connect_user = cups.getUser()
        # Now start a new thread for connection.
        self.connect_thread = thread.start_new_thread(self.connect,
                                                      (self.PrintersWindow,))

    def update_connecting_pbar (self):
        if not self.ConnectingDialog.get_property ("visible"):
            return False # stop animation

        self.pbarConnecting.pulse ()
        return True

    def on_connectingdialog_delete (self, widget, event):
        self.on_cancel_connect_clicked (widget)
        return True

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
                connection = cups.Connection (host=self.connect_server,
                                              encryption=self.connect_encrypt)

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
                time.sleep(1)
                self.cups._connect ()
                break
            except RuntimeError:
                # Connection failed.
                attempt += 1

    def on_btnCancelConnect_clicked(self, widget):
        """Close Connect dialog"""
        self.ConnectWindow.hide()

    # refresh

    def on_btnRefresh_clicked(self, button):
        if self.cups == None:
            try:
                self.cups = authconn.Connection(self.PrintersWindow)
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
            model = widget.get_model ()
            iter = widget.get_active_iter()
            value = model.get_value (iter, 1)
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

            btn = gtk.Button(stock=gtk.STOCK_REMOVE)
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
        try:
            printable = (self.ppd != None and
                         not bool (self.changed) and
                         self.printer.enabled and
                         not self.printer.rejecting)

            self.btnPrintTestPage.set_sensitive (printable)
            adjustable = not (self.printer.discovered or bool (self.changed))
            for button in [self.btnChangePPD,
                           self.btnSelectDevice]:
                button.set_sensitive (adjustable)

            commands = (self.printer.type & cups.CUPS_PRINTER_COMMANDS) != 0
            self.btnSelfTest.set_sensitive (commands and printable)
            self.btnCleanHeads.set_sensitive (commands and printable)
        except:
            nonfatalException()

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
                try:
                    if label == self.lblPInstallOptions:
                        iter = store.get_iter ((n,))
                        store.set_value (iter, 0, installabletext)
                    elif label == self.lblPOptions:
                        iter = store.get_iter ((n,))
                        store.set_value (iter, 0, optionstext)
                except ValueError:
                    # If we get here, the store has not yet been set
                    # up (trac #111).
                    pass

        self.btnPrinterPropertiesApply.set_sensitive (len (self.changed) > 0 and
                                                      not self.conflicts)
        self.btnPrinterPropertiesOK.set_sensitive (len (self.changed) > 0 and
                                                   not self.conflicts)

    def save_printer(self, printer, saveall=False, parent=None):
        if parent == None:
            parent = self.PrinterPropertiesDialog
        class_deleted = False
        name = printer.name

        if printer.is_class:
            self.cups._begin_operation (_("modifying class %s") % name)
        else:
            self.cups._begin_operation (_("modifying printer %s") % name)

        try:
            if not printer.is_class and self.ppd:
                self.getPrinterSettings()
                if self.ppd.nondefaultsMarked() or saveall:
                    self.cups.addPrinter(name, ppd=self.ppd)

            if printer.is_class:
                # update member list
                new_members = newprinter.getCurrentClassMembers(self.tvClassMembers)
                if not new_members:
                    dialog = gtk.MessageDialog(
                        flags=0, type=gtk.MESSAGE_WARNING,
                        buttons=gtk.BUTTONS_NONE,
                        message_format=_("This will delete this class!"))
                    dialog.format_secondary_text(_("Proceed anyway?"))
                    dialog.add_buttons (gtk.STOCK_CANCEL, gtk.RESPONSE_NO,
                                        gtk.STOCK_DELETE, gtk.RESPONSE_YES)
                    result = dialog.run()
                    dialog.destroy()
                    if result==gtk.RESPONSE_NO:
                        self.cups._end_operation ()
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

            def get_combo_value (cmb):
                model = cmb.get_model ()
                iter = cmb.get_active_iter ()
                return model.get_value (iter, 1)

            job_sheet_start = get_combo_value (self.cmbPStartBanner)
            job_sheet_end = get_combo_value (self.cmbPEndBanner)
            error_policy = get_combo_value (self.cmbPErrorPolicy)
            op_policy = get_combo_value (self.cmbPOperationPolicy)

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
                    (saveall and
                     option.get_current_value () != option.get_default())):
                    printer.setOption(option.name, option.get_current_value())

        except cups.IPPError, (e, s):
            show_IPP_Error(e, s, parent)
            self.cups._end_operation ()
            return True
        self.cups._end_operation ()
        self.changed = set() # of options

        if not self.cups._use_pk and not self.__dict__.has_key ("server_settings"):
            # We can authenticate with the server correctly at this point,
            # but we have never fetched the server settings to see whether
            # the server is publishing shared printers.  Fetch the settings
            # now so that we can update the "not published" label if necessary.
            self.cups._begin_operation (_("fetching server settings"))
            try:
                self.server_settings = self.cups.adminGetServerSettings()
            except:
                nonfatalException()

            self.cups._end_operation ()

        if class_deleted:
            self.monitor.update ()
        else:
            # Update our copy of the printer's settings.
            self.cups._begin_operation (_("obtaining queue details"))
            try:
                printers = cupshelpers.getPrinters (self.cups)
                this_printer = { name: printers[name] }
                self.printers.update (this_printer)
            except cups.IPPError, (e, s):
                show_IPP_Error(e, s, self.PrinterPropertiesDialog)
            except KeyError:
                # The printer was deleted in the mean time and the
                # user made no changes.
                self.populateList ()

            self.cups._end_operation ()
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
        (path, column) = treeview.get_cursor ()
        if path != None:
            model = treeview.get_model ()
            iter = model.get_iter (path)
            n = model.get_value (iter, 1)
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
                                       self.PrintersWindow,
                                       _("Do you want to set this as "
                                         "the system-wide default printer?"),
                                       _("Set as the _system-wide "
                                         "default printer"),
                                       _("_Clear my personal default setting"),
                                       _("Set as my _personal default printer"))

    def set_default_printer (self, name):
        printer = self.printers[name]
        reload = False
        self.cups._begin_operation (_("setting default printer"))
        try:
            reload = printer.setAsDefault ()
        except cups.HTTPError, (s,):
            show_HTTP_Error (s, self.PrintersWindow)
            self.cups._end_operation ()
            return
        except cups.IPPError, (e, msg):
            show_IPP_Error(e, msg, self.PrintersWindow)
            self.cups._end_operation ()
            return

        self.cups._end_operation ()

        # Now reconnect in case the server needed to reload.  This may
        # happen if we replaced the lpoptions file.
        if reload:
            self.reconnect ()

        try:
            self.populateList()
        except cups.HTTPError, (s,):
            self.cups = None
            self.setConnected()
            self.populateList()
            show_HTTP_Error(s, self.PrintersWindow)

    # print test page

    def on_btnPrintTestPage_clicked(self, button):
        if self.ppd == False:
            # Can't print a test page for a raw queue.
            return

        # if we have a page size specific custom test page, use it;
        # otherwise use cups' default one
        custom_testpage = None
        if self.ppd != False:
            opt = self.ppd.findOption ("PageSize")
            if opt:
                custom_testpage = os.path.join(pkgdata,
                                               'testpage-%s.ps' %
                                               opt.defchoice.lower())

        # Connect as the current user so that the test page can be managed
        # as a normal job.
        user = cups.getUser ()
        cups.setUser ('')
        try:
            c = authconn.Connection (self.PrintersWindow, try_as_root=False,
                                     host=self.connect_server,
                                     encryption=self.connect_encrypt)
        except RuntimeError, s:
            show_IPP_Error (None, s, self.PrintersWindow)
            return

        job_id = None
        c._begin_operation (_("printing test page"))
        try:
            if custom_testpage and os.path.exists(custom_testpage):
                debugprint ('Printing custom test page ' + custom_testpage)
                job_id = c.printTestPage(self.printer.name,
                                         file=custom_testpage)
            else:
                debugprint ('Printing default test page')
                job_id = c.printTestPage(self.printer.name)
        except cups.IPPError, (e, msg):
            if (e == cups.IPP_NOT_AUTHORIZED and
                self.connect_server != 'localhost' and
                self.connect_server[0] != '/'):
                show_error_dialog (_("Not possible"),
                                   _("The remote server did not accept "
                                     "the print job, most likely "
                                     "because the printer is not "
                                     "shared."),
                                   self.PrintersWindow)
            else:
                show_IPP_Error(e, msg, self.PrintersWindow)

        c._end_operation ()
        cups.setUser (user)

        if job_id != None:
            show_info_dialog (_("Submitted"),
                              _("Test page submitted as job %d") % job_id,
                              parent=self.PrintersWindow)

    def maintenance_command (self, command):
        (tmpfd, tmpfname) = tempfile.mkstemp ()
        os.write (tmpfd, "#CUPS-COMMAND\n%s\n" % command)
        os.close (tmpfd)
        self.cups._begin_operation (_("sending maintenance command"))
        try:
            format = "application/vnd.cups-command"
            job_id = self.cups.printTestPage (self.printer.name,
                                              format=format,
                                              file=tmpfname,
                                              user=self.connect_user)
            show_info_dialog (_("Submitted"),
                              _("Maintenance command submitted as "
                                "job %d") % job_id,
                              parent=self.PrintersWindow)
        except cups.IPPError, (e, msg):
            if (e == cups.IPP_NOT_AUTHORIZED and
                self.printer.name != 'localhost'):
                show_error_dialog (_("Not possible"),
                                   _("The remote server did not accept "
                                     "the print job, most likely "
                                     "because the printer is not "
                                     "shared."),
                                   self.PrintersWindow)
            else:
                show_IPP_Error(e, msg, self.PrintersWindow)

        self.cups._end_operation ()

        os.unlink (tmpfname)

    def on_btnSelfTest_clicked(self, button):
        self.maintenance_command ("PrintSelfTestPage")

    def on_btnCleanHeads_clicked(self, button):
        self.maintenance_command ("Clean all")

    def fillComboBox(self, combobox, values, value, translationdict=None):
        if translationdict == None:
            translationdict = ppdippstr.TranslactionDict ()

        model = gtk.ListStore (gobject.TYPE_STRING,
                               gobject.TYPE_STRING)
        combobox.set_model (model)
        set_active = False
        for nr, val in enumerate(values):
            model.append ([(translationdict.get (val)), val])
            if val == value:
                combobox.set_active(nr)
                set_active = True

        if not set_active:
            combobox.set_active (0)

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

        try:
            self.ppd = printer.getPPD()
            self.ppd_local = printer.getPPD()
            if self.ppd_local != False:
                self.ppd_local.localize()
        except cups.IPPError, (e, m):
            # We might get IPP_INTERNAL_ERROR if this is a memberless
            # class.
            if e != cups.IPP_INTERNAL_ERROR:
                # Some IPP error other than IPP_NOT_FOUND.
                show_IPP_Error(e, m, self.PrintersWindow)

            # Treat it as a raw queue.
            self.ppd = False
        except RuntimeError:
            # The underlying cupsGetPPD2() function returned NULL without
            # setting an IPP error, so it'll be something like a failed
            # connection.
            show_error_dialog (_("Error"),
                               _("There was a problem connecting to "
                                 "the CUPS server."),
                               self.PrintersWindow)
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
                                       self.PrintersWindow)
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
            self.fillPrinterOptions(name, editable)

        self.updateMarkerLevels()
        self.updateStateReasons()
        self.updatePrinterPropertiesTreeView()

        self.changed = set() # of options
        self.updatePrinterProperties ()
        self.setDataButtonState()

    def updatePrinterPropertiesTreeView (self):
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

    def updateMarkerLevels (self):
        printer = self.printer

        # Marker levels
        for widget in self.vboxMarkerLevels.get_children ():
            self.vboxMarkerLevels.remove (widget)

        marker_info = dict()
        num_markers = 0
        for (attr, typ) in [('marker-colors', str),
                            ('marker-names', str),
                            ('marker-types', str),
                            ('marker-levels', float)]:
            val = printer.other_attributes.get (attr, [])
            if typ != str and len (val) > 0:
                try:
                    # Can the value be coerced into the right type?
                    typ (val[0])
                except TypeError, s:
                    debugprint ("%s value not coercible to %s: %s" %
                                (attr, typ, s))
                    val = map (lambda x: 0.0, val)

            marker_info[attr] = val
            if num_markers == 0 or len (val) < num_markers:
                num_markers = len (val)

        for attr in ['marker-colors', 'marker-names',
                     'marker-types', 'marker-levels']:
            if len (marker_info[attr]) > num_markers:
                debugprint ("Trimming %s from %s" %
                            (marker_info[attr][num_markers:], attr))
                del marker_info[attr][num_markers:]

        markers = map (lambda color, name, type, level:
                           (color, name, type, level),
                       marker_info['marker-colors'],
                       marker_info['marker-names'],
                       marker_info['marker-types'],
                       marker_info['marker-levels'])
        debugprint (markers)

        can_refresh = (self.printer.type & cups.CUPS_PRINTER_COMMANDS) != 0
        self.btnRefreshMarkerLevels.set_sensitive (can_refresh)
        if len (markers) == 0:
            label = gtk.Label(_("Marker levels are not reported "
                                "for this printer."))
            label.set_line_wrap (True)
            label.set_alignment (0.0, 0.0)
            self.vboxMarkerLevels.pack_start (label, False, False, 0)
        else:
            num_markers = 0
            cols = len (markers)
            rows = 1 + (cols - 1) / 4
            if cols > 4:
                cols = 4
            table = gtk.Table (rows=rows,
                               columns=cols,
                               homogeneous=True)
            table.set_col_spacings (6)
            table.set_row_spacings (12)
            self.vboxMarkerLevels.pack_start (table)
            for color, name, marker_type, level in markers:
                if name == None:
                    name = ''
                else:
                    ppd = printer.getPPD()
                    if ppd != False:
                        localized_name = ppd.localizeMarkerName(name)
                        if localized_name != None:
                            name = localized_name

                row = num_markers / 4
                col = num_markers % 4

                vbox = gtk.VBox (spacing=6)
                subhbox = gtk.HBox ()
                inklevel = gtkinklevel.GtkInkLevel (color, level)
                inklevel.set_tooltip_text ("%d%%" % level)
                subhbox.pack_start (inklevel, True, False, 0)
                vbox.pack_start (subhbox, False, False, 0)
                label = gtk.Label (name)
                label.set_width_chars (10)
                label.set_line_wrap (True)
                vbox.pack_start (label, False, False, 0)
                table.attach (vbox, col, col + 1, row, row + 1)
                num_markers += 1

        self.vboxMarkerLevels.show_all ()

    def on_btnRefreshMarkerLevels_clicked (self, button):
        self.maintenance_command ("ReportLevels")

    def updateStateReasons (self):
        printer = self.printer
        reasons = printer.other_attributes.get ('printer-state-reasons', [])
        store = gtk.ListStore (str, str)
        any = False
        for reason in reasons:
            if reason == "none":
                break

            any = True
            iter = store.append (None)
            r = statereason.StateReason (printer.connection, printer.name, reason)
            if r.get_reason () == "paused":
                icon = gtk.STOCK_MEDIA_PAUSE
            else:
                icon = statereason.StateReason.LEVEL_ICON[r.get_level ()]
            store.set_value (iter, 0, icon)
            (title, text) = r.get_description ()
            store.set_value (iter, 1, text)

        self.tvPrinterStateReasons.set_model (store)
        page = 0
        if any:
            page = 1

        self.ntbkPrinterStateReasons.set_current_page (page)

    def set_printer_state_reason_icon (self, column, cell, model, iter, *data):
        icon = model.get_value (iter, 0)
        theme = gtk.icon_theme_get_default ()
        try:
            pixbuf = theme.load_icon (icon, 22, 0)
            cell.set_property ("pixbuf", pixbuf)
        except gobject.GError, exc:
            pass # Couldn't load icon

    def set_printer_state_reason_text (self, column, cell, model, iter, *data):
        cell.set_property ("text", model.get_value (iter, 1))

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
                              printer.job_sheet_start,
                              ppdippstr.job_sheets)
            self.fillComboBox(self.cmbPEndBanner, printer.job_sheets_supported,
                              printer.job_sheet_end,
                              ppdippstr.job_sheets)

            # Policies
            self.fillComboBox(self.cmbPErrorPolicy,
                              printer.error_policy_supported,
                              printer.error_policy,
                              ppdippstr.printer_error_policy)
            self.fillComboBox(self.cmbPOperationPolicy,
                              printer.op_policy_supported,
                              printer.op_policy,
                              ppdippstr.printer_op_policy)

            # Access control
            self.rbtnPAllow.set_active(printer.default_allow)
            self.rbtnPDeny.set_active(not printer.default_allow)
            self.setPUsers(printer.except_users)

            # Marker levels
            self.updateMarkerLevels ()
            self.updateStateReasons ()

            self.updatePrinterPropertiesTreeView ()

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
        self.ppd_local.markDefaults()

        hasInstallableOptions = False

        # build option tabs
        for group in self.ppd_local.optionGroups:
            if group.name == "InstallableOptions":
                hasInstallableOptions = True
                container = self.vbPInstallOptions
                tab_nr = self.ntbkPrinter.page_num(self.swPInstallOptions)
                if tab_nr == -1:
                    self.ntbkPrinter.insert_page(self.swPInstallOptions,
                                                 gtk.Label(group.text),
                                                 self.static_tabs)
                tab_label = self.lblPInstallOptions
            else:
                frame = gtk.Frame("<b>%s</b>" % ppdippstr.ppd.get (group.text))
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
        newprinter.moveClassMembers(self.tvClassNotMembers,
                                    self.tvClassMembers)
        if newprinter.getCurrentClassMembers(self.tvClassMembers) != self.printer.class_members:
            self.changed.add(self.tvClassMembers)
        else:
            self.changed.discard(self.tvClassMembers)
        self.setDataButtonState()

    def on_btnClassDelMember_clicked(self, button):
        newprinter.moveClassMembers(self.tvClassMembers,
                                    self.tvClassNotMembers)
        if newprinter.getCurrentClassMembers(self.tvClassMembers) != self.printer.class_members:
            self.changed.add(self.tvClassMembers)
        else:
            self.changed.discard(self.tvClassMembers)
        self.setDataButtonState()

    # Quit

    def on_quit_activate(self, widget, event=None):
        self.monitor.cleanup ()
        while len (self.jobviewers) > 0:
            # this will call on_jobviewer_exit
            self.jobviewers[0].on_delete_event ()
        del self.mainlist
        del self.printers
        gtk.main_quit()

    # Rename
    def is_rename_possible (self, name):
        jobs = self.printers[name].jobsQueued (limit=1)
        if len (jobs) > 0:
            show_error_dialog (_("Cannot Rename"),
                               _("There are queued jobs."),
                               parent=self.PrintersWindow)
            return False

        return True

    def rename_confirmed_by_user (self, name):
        """
        Renaming deletes job history. So if we have some completed jobs,
        inform the user and let him confirm the renaming.
        """
        preserved_jobs = self.printers[name].jobsPreserved(limit=1)
        if len (preserved_jobs) > 0:
            dialog = gtk.MessageDialog (self.PrintersWindow,
                                        gtk.DIALOG_MODAL |
                                        gtk.DIALOG_DESTROY_WITH_PARENT,
                                        gtk.MESSAGE_WARNING,
                                        gtk.BUTTONS_OK_CANCEL,
                                        _("Renaming will lose history"))

            dialog.format_secondary_text (_("Completed jobs will no longer "
                                            "be available for re-printing."))
            result = dialog.run()
            dialog.destroy ()
            if result == gtk.RESPONSE_CANCEL:
                return False

        return True

    def on_rename_activate(self, UNUSED):
        tuple = self.dests_iconview.get_cursor ()
        if tuple == None:
            return

        (path, cell) = tuple
        if type (cell) != gtk.CellRendererText:
            cells = self.dests_iconview.get_cells ()
            for cell in cells:
                if type (cell) == gtk.CellRendererText:
                    break
            if type (cell) != gtk.CellRendererText:
                return

        model = self.dests_iconview.get_model ()
        iter = model.get_iter (path)
        name = unicode (model.get_value (iter, 2))
        if not self.is_rename_possible (name):
            return
        if not self.rename_confirmed_by_user (name):
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
        name = unicode (model.get_value (iter, 2))
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
        except cups.IPPError, (e, m):
            show_IPP_Error (e, m, self.PrintersWindow)
            self.populateList ()
            return

        if not self.is_rename_possible (old_name):
            return

        self.cups._begin_operation (_("renaming printer"))
        rejecting = self.printer.rejecting
        if not rejecting:
            try:
                self.printer.setAccepting (False)
                if not self.is_rename_possible (old_name):
                    self.printer.setAccepting (True)
                    self.cups._end_operation ()
                    return
            except cups.IPPError, (e, msg):
                show_IPP_Error (e, msg, self.PrintersWindow)
                self.cups._end_operation ()
                return

        if self.duplicate_printer (new_name):
            # Failure.
            self.monitor.update ()

            # Restore original accepting/rejecting state.
            if not rejecting:
                try:
                    self.printer.name = old_name
                    self.printer.setAccepting (True)
                except cups.HTTPError, (s,):
                    show_HTTP_Error (s, self.PrintersWindow)
                except cups.IPPError, (e, msg):
                    show_IPP_Error (e, msg, self.PrintersWindow)

            self.cups._end_operation ()
            self.populateList ()
            return

        # Restore rejecting state.
        if not rejecting:
            try:
                self.printer.setAccepting (True)
            except cups.HTTPError, (s,):
                show_HTTP_Error (s, self.PrintersWindow)
                # Not fatal.
            except cups.IPPError, (e, msg):
                show_IPP_Error (e, msg, self.PrintersWindow)
                # Not fatal.

        # Fix up default printer.
        if self.default_printer == old_name:
            reload = False
            try:
                reload = self.printer.setAsDefault ()
            except cups.HTTPError, (s,):
                show_HTTP_Error (s, self.PrintersWindow)
                # Not fatal.
            except cups.IPPError, (e, msg):
                show_IPP_Error (e, msg, self.PrintersWindow)
                # Not fatal.

            if reload:
                self.reconnect ()

        # Finally, delete the old printer.
        try:
            self.cups.deletePrinter (old_name)
        except cups.HTTPError, (s,):
            show_HTTP_Error (s, self.PrintersWindow)
            # Not fatal
        except cups.IPPError, (e, msg):
            show_IPP_Error (e, msg, self.PrintersWindow)
            # Not fatal.

        self.cups._end_operation ()

        # ..and select the new printer.
        def select_new_printer (model, path, iter):
            name = unicode (model.get_value (iter, 2))
            print name, new_name
            if name == new_name:
                self.dests_iconview.select_path (path)
        self.populateList ()
        model = self.dests_iconview.get_model ()
        model.foreach (select_new_printer)

    # Duplicate

    def duplicate_printer (self, new_name):
        self.printer.name = new_name
        self.printer.class_members = [] # for classes make sure all members
                                        # will get added

        self.cups._begin_operation (_("duplicating printer"))
        ret = self.save_printer(self.printer, saveall=True,
                                parent=self.PrintersWindow)
        self.cups._end_operation ()
        return ret

    def on_duplicate_activate(self, UNUSED):
        iconview = self.dests_iconview
        paths = iconview.get_selected_items ()
        model = self.dests_iconview.get_model ()
        iter = model.get_iter (paths[0])
        name = unicode (model.get_value (iter, 2))
        self.entDuplicateName.set_text(name)
        self.NewPrinterName.set_transient_for (self.PrintersWindow)
        result = self.NewPrinterName.run()
        self.NewPrinterName.hide()

        if result == gtk.RESPONSE_CANCEL:
            return

        try:
            self.fillPrinterTab (name)
        except RuntimeError:
            # Perhaps cupsGetPPD2 failed for a browsed printer
            pass

        self.duplicate_printer (self.entDuplicateName.get_text ())
        self.monitor.update ()

    def on_entDuplicateName_changed(self, widget):
        # restrict
        text = unicode (widget.get_text())
        new_text = text
        new_text = new_text.replace("/", "")
        new_text = new_text.replace("#", "")
        new_text = new_text.replace(" ", "")
        if text!=new_text:
            widget.set_text(new_text)
        self.btnDuplicateOk.set_sensitive(
            self.checkNPName(new_text))

    # Delete

    def on_delete_activate(self, UNUSED):
        if isinstance (self.current_groups_pane_item, StaticGroupItem):
            paths = self.dests_iconview.get_selected_items ()
            model = self.dests_iconview.get_model ()
            selected_names = []
            for path in paths:
                selected_names.append (model[path][2])
            self.current_groups_pane_item.remove_queues (selected_names)
            self.populateList ()
        else:
            self.delete_selected_printer_queues ()

    def delete_selected_printer_queues (self):
        paths = self.dests_iconview.get_selected_items ()
        model = self.dests_iconview.get_model ()
        n = len (paths)
        if n == 1:
            iter = model.get_iter (paths[0])
            object = model.get_value (iter, 0)
            name = model.get_value (iter, 2)
            if object.is_class:
                message_format = _("Really delete class '%s'?") % name
            else:
                message_format = _("Really delete printer '%s'?") % name
        else:
            message_format = _("Really delete selected destinations?")

        dialog = gtk.MessageDialog(self.PrintersWindow,
                                   gtk.DIALOG_DESTROY_WITH_PARENT |
                                   gtk.DIALOG_MODAL,
                                   gtk.MESSAGE_WARNING,
                                   gtk.BUTTONS_NONE,
                                   message_format)
        dialog.add_buttons (gtk.STOCK_CANCEL, gtk.RESPONSE_REJECT,
                            gtk.STOCK_DELETE, gtk.RESPONSE_ACCEPT)
        dialog.set_default_response (gtk.RESPONSE_REJECT)
        result = dialog.run()
        dialog.destroy()

        if result != gtk.RESPONSE_ACCEPT:
            return

        try:
            for path in paths:
                iter = model.get_iter (path)
                name = model.get_value (iter, 2)
                self.cups._begin_operation (_("deleting printer %s") % name)
                name = unicode (name)
                self.cups.deletePrinter (name)
                self.cups._end_operation ()
        except cups.IPPError, (e, msg):
            self.cups._end_operation ()
            show_IPP_Error(e, msg, self.PrintersWindow)

        self.changed = set()
        self.monitor.update ()

    # Enable/disable
    def on_enabled_activate(self, toggle_action):
        if self.updating_widgets:
            return
        enable = toggle_action.get_active ()
        iconview = self.dests_iconview
        paths = iconview.get_selected_items ()
        model = iconview.get_model ()
        for path in paths:
            iter = model.get_iter (path)
            printer = model.get_value (iter, 0)
            name = unicode (model.get_value (iter, 2), 'utf-8')
            self.cups._begin_operation (_("modifying printer %s") % name)
            try:
                printer.setEnabled (enable)
            except cups.IPPError, (e, m):
                errordialogs.show_IPP_Error (e, m, self.PrintersWindow)
                # Give up on this operation.
                self.cups._end_operation ()
                break

            self.cups._end_operation ()

        self.monitor.update ()

    # Shared
    def on_shared_activate(self, menuitem):
        if self.updating_widgets:
            return
        share = menuitem.get_active ()
        iconview = self.dests_iconview
        paths = iconview.get_selected_items ()
        model = iconview.get_model ()
        success = False
        for path in paths:
            iter = model.get_iter (path)
            printer = model.get_value (iter, 0)
            self.cups._begin_operation (_("modifying printer %s") %
                                        printer.name)
            try:
                printer.setShared (share)
                success = True
            except cups.IPPError, (e, m):
                show_IPP_Error(e, m, self.PrintersWindow)
                self.cups._end_operation ()
                # Give up on this operation.
                break

            self.cups._end_operation ()

        if success and share:
            if self.server_is_publishing == None:
                # We haven't yet seen a server-is-sharing-printers attribute.
                # Assuming CUPS 1.4, this means we haven't opened a
                # properties dialog yet.  Fetch the attributes now and
                # look for it.
                try:
                    printer.getAttributes ()
                    p = printer.other_attributes['server-is-sharing-printers']
                    self.server_is_publishing = p
                except (cups.IPPError, KeyError):
                    pass

            self.advise_publish ()

        # For some reason CUPS doesn't give us a notification about
        # printers changing 'shared' state, so refresh instead of
        # update.  We have to defer this to prevent signal problems.
        def deferred_refresh ():
            self.populateList ()
            return False
        gobject.idle_add (deferred_refresh)

    def advise_publish(self):
        if not self.server_is_publishing:
            show_info_dialog (_("Publish Shared Printers"),
                              _("Shared printers are not available "
                                "to other people unless the "
                                "'Publish shared printers' option is "
                                "enabled in the server settings."),
                              parent=self.PrintersWindow)

    # Set As Default
    def on_set_as_default_activate(self, UNUSED):
        iconview = self.dests_iconview
        paths = iconview.get_selected_items ()
        model = iconview.get_model ()
        iter = model.get_iter (paths[0])
        name = unicode (model.get_value (iter, 2))
        self.set_system_or_user_default_printer (name)

    def on_edit_activate (self, UNUSED):
        paths = self.dests_iconview.get_selected_items ()
        self.dests_iconview_item_activated (self.dests_iconview, paths[0])

    def on_create_class_activate (self, UNUSED):
        paths = self.dests_iconview.get_selected_items ()
        class_members = []
        model = self.dests_iconview.get_model ()
        for path in paths:
            iter = model.get_iter (path)
            name = unicode (model.get_value (iter, 2), 'utf-8')
            class_members.append (name)
        self.newPrinterGUI.init ("class", parent=self.PrintersWindow)
        out_model = self.newPrinterGUI.tvNCNotMembers.get_model ()
        in_model = self.newPrinterGUI.tvNCMembers.get_model ()
        iter = out_model.get_iter_first ()
        while iter != None:
            next = out_model.iter_next (iter)
            data = out_model.get (iter, 0)
            if data[0] in class_members:
                in_model.append (data)
                out_model.remove (iter)
            iter = next

    def on_view_print_queue_activate (self, UNUSED):
        paths = self.dests_iconview.get_selected_items ()
        if len (paths):
            specific_dests = []
            model = self.dests_iconview.get_model ()
            for path in paths:
                iter = model.get_iter (path)
                name = unicode (model.get_value (iter, 2), 'utf-8')
                specific_dests.append (name)
            viewer = jobviewer.JobViewer (None, None, my_jobs=False,
                                          specific_dests=specific_dests,
                                          exit_handler=self.on_jobviewer_exit,
                                          parent=self.PrintersWindow)
        else:
            viewer = jobviewer.JobViewer (None, None, my_jobs=False,
                                          exit_handler=self.on_jobviewer_exit,
                                          parent=self.PrintersWindow)

        self.jobviewers.append (viewer)

    def on_jobviewer_exit (self, viewer):
        i = self.jobviewers.index (viewer)
        del self.jobviewers[i]

    def on_view_groups_activate (self, widget):
        if widget.get_active ():
            if not self.groups_pane_visible:
                # Show it.
                self.view_area_vbox.remove (self.view_area_scrolledwindow)
                self.view_area_hpaned.add2 (self.view_area_scrolledwindow)
                self.view_area_vbox.add (self.view_area_hpaned)
                self.view_area_vbox.show_all ()
                self.groups_pane_visible = True
        else:
            if self.groups_pane_visible:
                # Hide it.
                self.view_area_vbox.remove (self.view_area_hpaned)
                self.view_area_hpaned.remove (self.view_area_scrolledwindow)
                self.view_area_vbox.add (self.view_area_scrolledwindow)
                self.view_area_vbox.show_all ()
                self.groups_pane_visible = False

    def on_view_discovered_printers_activate (self, UNUSED):
        self.populateList ()

    def on_troubleshoot_activate(self, widget):
        if not self.__dict__.has_key ('troubleshooter'):
            self.troubleshooter = troubleshoot.run (self.on_troubleshoot_quit)

    def on_troubleshoot_quit(self, troubleshooter):
        del self.troubleshooter

    def on_save_as_group_activate (self, UNUSED):
        model = self.dests_iconview.get_model ()
        printer_queues = []
        for object in model:
            printer_queues.append (object[2])
        self.groups_pane.create_new_group (printer_queues,
                                           self.current_filter_text)

    def on_save_as_search_group_activate (self, UNUSED):
        criterion = None
        if self.current_filter_mode == "filter-name":
            criterion = SearchCriterion (subject = SearchCriterion.SUBJECT_NAME,
                                         value   = self.current_filter_text)
        elif self.current_filter_mode == "filter-description":
            criterion = SearchCriterion (subject = SearchCriterion.SUBJECT_DESC,
                                         value   = self.current_filter_text)
        elif self.current_filter_mode == "filter-location":
            criterion = SearchCriterion (subject = SearchCriterion.SUBJECT_LOCATION,
                                         value   = self.current_filter_text)
        elif self.current_filter_mode == "filter-manufacturer":
            criterion = SearchCriterion (subject = SearchCriterion.SUBJECT_MANUF,
                                         value   = self.current_filter_text)
        else:
            nonfatalException ()
            return

        self.groups_pane.create_new_search_group (criterion,
                                                  self.current_filter_text)

    # About dialog
    def on_about_activate(self, widget):
        self.AboutDialog.set_transient_for (self.PrintersWindow)
        self.AboutDialog.run()
        self.AboutDialog.hide()

    ##########################################################################
    ### Server settings
    ##########################################################################

    def fillServerTab(self):
        self.changed = set()
        self.cups._begin_operation (_("fetching server settings"))
        try:
            self.server_settings = self.cups.adminGetServerSettings()
        except cups.IPPError, (e, m):
            show_IPP_Error(e, m, self.PrintersWindow)
            self.cups._end_operation ()
            raise

        self.cups._end_operation ()

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

    def save_serversettings(self):
        setting_dict = dict()
        for widget, setting in [
            (self.chkServerBrowse, cups.CUPS_SERVER_REMOTE_PRINTERS),
            (self.chkServerShare, cups.CUPS_SERVER_SHARE_PRINTERS),
            (self.chkServerShareAny, try_CUPS_SERVER_REMOTE_ANY),
            (self.chkServerRemoteAdmin, cups.CUPS_SERVER_REMOTE_ADMIN),
            (self.chkServerAllowCancelAll, cups.CUPS_SERVER_USER_CANCEL_ANY),
            (self.chkServerLogDebug, cups.CUPS_SERVER_DEBUG_LOGGING),]:
            if not self.server_settings.has_key(setting): continue
            setting_dict[setting] = str(int(widget.get_active()))
        self.cups._begin_operation (_("modifying server settings"))
        try:
            self.cups.adminSetServerSettings(setting_dict)
        except cups.IPPError, (e, m):
            show_IPP_Error(e, m, self.ServerSettingsDialog)
            self.cups._end_operation ()
            return True
        except RuntimeError, s:
            show_IPP_Error(None, s, self.ServerSettingsDialog)
            self.cups._end_operation ()
            return True
        self.cups._end_operation ()
        self.changed = set()

        old_setting = self.server_settings.get (cups.CUPS_SERVER_SHARE_PRINTERS,
                                                '0')
        new_setting = setting_dict.get (cups.CUPS_SERVER_SHARE_PRINTERS, '0')
        if (old_setting == '0' and new_setting != '0'):
            # We have just enabled print queue sharing.
            # Let's see if the firewall will allow IPP TCP packets in.
            try:
                if (self.connect_server == 'localhost' or
                    self.connect_server[0] == '/'):
                    f = firewall.Firewall ()
                    allowed = f.check_ipp_server_allowed ()
                else:
                    # This is a remote server.  Nothing we can do
                    # about the firewall there.
                    allowed = True

                if not allowed:
                    dialog = gtk.MessageDialog (self.ServerSettingsDialog,
                                                gtk.DIALOG_MODAL |
                                                gtk.DIALOG_DESTROY_WITH_PARENT,
                                                gtk.MESSAGE_QUESTION,
                                                gtk.BUTTONS_NONE,
                                                _("Adjust Firewall"))
                    dialog.format_secondary_text (_("Adjust the firewall now "
                                                    "to allow all incoming IPP "
                                                    "connections?"))
                    dialog.add_buttons (gtk.STOCK_CANCEL, gtk.RESPONSE_NO,
                                        _("Adjust Firewall"), gtk.RESPONSE_YES)
                    response = dialog.run ()
                    dialog.destroy ()

                    if response == gtk.RESPONSE_YES:
                        f.add_rule (f.ALLOW_IPP_SERVER)
                        f.write ()
            except (dbus.DBusException, Exception):
                nonfatalException ()

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
    def on_problems_button_clicked (self, *args):
        if not self.__dict__.has_key ('troubleshooter'):
            self.troubleshooter = troubleshoot.run (self.on_troubleshoot_quit,
                                                    parent=self.ServerSettingsDialog)

    # ====================================================================
    # == New Printer Dialog ==============================================
    # ====================================================================

    # new printer
    def on_new_printer_activate(self, widget):
        self.busy (self.PrintersWindow)
        self.newPrinterGUI.init("printer", parent=self.PrintersWindow)
        self.ready (self.PrintersWindow)

    # new printer, auto-detected, but now driver found
    def on_autodetected_printer_without_driver(self, widget):
        self.busy (self.PrintersWindow)
        self.newPrinterGUI.init("printer_with_uri", device_uri=self.device_uri,
                                parent=self.PrintersWindow)
        self.ready (self.PrintersWindow)

    # new class
    def on_new_class_activate(self, widget):
        self.newPrinterGUI.init("class", parent=self.PrintersWindow)

    # change device
    def on_btnSelectDevice_clicked(self, button):
        self.busy (self.PrintersWindow)
        self.newPrinterGUI.init("device", device_uri=self.printer.device_uri,
                                parent=self.PrinterPropertiesDialog)
        self.ready (self.PrintersWindow)

    # change PPD
    def on_btnChangePPD_clicked(self, button):
        self.busy (self.PrintersWindow)
        self.newPrinterGUI.init("ppd", device_uri=self.printer.device_uri,
                                parent=self.PrinterPropertiesDialog)
        self.ready (self.PrintersWindow)

    def checkNPName(self, name):
        if not name: return False
        name = unicode (name.lower())
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
            while not self.checkNPName (name + "-" + str (suffix)):
                suffix += 1
                if suffix == 100:
                    break
            name += "-" + str (suffix)
        return name

    def new_printer_added (self, obj, name):
        debugprint ("New printer added: %s" % name)
        self.populateList ()

        if not self.printers.has_key (name):
            # At this stage the printer has disappeared even though we
            # only added it moments ago.
            debugprint ("New printer disappeared")
            return

        # Now select it.
        model = self.dests_iconview.get_model ()
        iter = model.get_iter_first ()
        while iter != None:
            queue = unicode (model.get_value (iter, 2))
            if queue == name:
                path = model.get_path (iter)
                self.dests_iconview.scroll_to_path (path, True, 0.5, 0.5)
                self.dests_iconview.unselect_all ()
                self.dests_iconview.set_cursor (path)
                self.dests_iconview.select_path (path)
                break

            iter = model.iter_next (iter)

    ## Monitor signal helpers
    def printer_added_or_removed (self):
        # Just fetch the list of printers again.  This is too simplistic.
        gtk.gdk.threads_enter ()
        self.populateList (prompt_allowed=False)
        gtk.gdk.threads_leave ()

    ## Monitor signal handlers
    def printer_added (self, mon, printer):
        self.printer_added_or_removed ()

    def printer_event (self, mon, printer, eventname, event):
        def deferred_refresh ():
            self.populateList ()
            return False

        gtk.gdk.threads_enter ()
        if self.printers.has_key (printer):
            self.printers[printer].update (**event)
            self.dests_iconview_selection_changed (self.dests_iconview)
            gobject.idle_add (deferred_refresh)
            if self.PrinterPropertiesDialog.get_property('visible'):
                try:
                    self.printer.getAttributes ()
                    self.updatePrinterProperties ()
                except cups.IPPError:
                    pass

        gtk.gdk.threads_leave ()

    def printer_removed (self, mon, printer):
        self.printer_added_or_removed ()

    def state_reason_added (self, mon, reason):
        gtk.gdk.threads_enter ()
        if self.PrinterPropertiesDialog.get_property('visible'):
            try:
                self.printer.getAttributes ()
                self.updatePrinterProperties ()
            except cups.IPPError:
                pass

        gtk.gdk.threads_leave ()

    def state_reason_removed (self, mon, reason):
        gtk.gdk.threads_enter ()
        if self.PrinterPropertiesDialog.get_property('visible'):
            try:
                self.printer.getAttributes ()
                self.updatePrinterProperties ()
            except cups.IPPError:
                pass

        gtk.gdk.threads_leave ()

    def cups_connection_error (self, mon):
        try:
            self.cups.getClasses ()
        except:
            self.cups = None
            gtk.gdk.threads_enter ()
            self.setConnected ()
            self.populateList (prompt_allowed=False)
            gtk.gdk.threads_leave ()


def main(setup_printer = None, configure_printer = None, change_ppd = False,
         devid = "", print_test_page = False, focus_on_map = True):
    cups.setUser (os.environ.get ("CUPS_USER", cups.getUser()))
    gobject.threads_init()
    gtk.gdk.threads_init()

    mainwindow = GUI(setup_printer, configure_printer, change_ppd, devid,
                     print_test_page, focus_on_map)

    if gtk.__dict__.has_key("main"):
        gtk.main()
    else:
        gtk.mainloop()


if __name__ == "__main__":
    import getopt
    try:
        opts, args = getopt.gnu_getopt (sys.argv[1:], '',
                                        ['setup-printer=',
                                         'configure-printer=',
                                         'choose-driver=',
                                         'devid=',
                                         'print-test-page=',
                                         'no-focus-on-map',
                                         'debug'])
    except getopt.GetoptError:
        show_help ()
        sys.exit (1)

    setup_printer = None
    configure_printer = None
    change_ppd = False
    print_test_page = False
    focus_on_map = True
    devid = ""
    for opt, optarg in opts:
        if (opt == "--configure-printer" or
            opt == "--choose-driver" or
            opt == "--print-test-page"):
            configure_printer = optarg
            if opt == "--choose-driver":
                change_ppd = True
            elif opt == "--print-test-page":
                print_test_page = True

        elif opt == '--setup-printer':
            setup_printer = optarg

        elif opt == '--devid':
            devid = optarg

        elif opt == '--no-focus-on-map':
            focus_on_map = False

        elif opt == '--debug':
            set_debugging (True)

    main(setup_printer, configure_printer, change_ppd, devid, print_test_page,
         focus_on_map)

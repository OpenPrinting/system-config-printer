#!/usr/bin/python3

## system-config-printer

## Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014, 2015 Red Hat, Inc.
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
## Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

# config is generated from config.py.in by configure
import config

import sys, os, time, re
import _thread
import dbus
import gi
try:
    gi.require_version('Polkit', '1.0')
    from gi.repository import Polkit
except:
    Polkit = False

gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf
try:
    gi.require_version('Gdk', '3.0')
    from gi.repository import Gdk
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
    Gtk.init (sys.argv)
except RuntimeError as e:
    print ("system-config-printer:", e)
    print ("This is a graphical application and requires DISPLAY to be set.")
    sys.exit (1)

def show_help():
    print ("\nThis is system-config-printer, " \
           "a CUPS server configuration program.\n\n"
           "Options:\n\n"
           "  --debug                 Enable debugging output.\n"
           "  --show-jobs <printer>   Show the print queue for <printer>\n"
           "  --embedded              Enable to start in Embedded mode.\n "
           "  --help                  Show this message.\n")

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
gettext.install(domain=config.PACKAGE, localedir=config.localedir)

import cupshelpers
from gi.repository import GObject
from gi.repository import GLib
from gui import GtkGUI
from debug import *
import urllib.request, urllib.parse, urllib.error
import troubleshoot
import installpackage
import jobviewer
import authconn
import monitor
import errordialogs
from errordialogs import *
import userdefault
from serversettings import ServerSettings
from ToolbarSearchEntry import *
from SearchCriterion import *
import statereason
import newprinter
from newprinter import busy, ready
import printerproperties

import ppdippstr
ppdippstr.init ()
pkgdata = config.pkgdatadir
iconpath = os.path.join (pkgdata, 'icons/')
sys.path.append (pkgdata)

PlugWindow = None
PlugWindowId = None

#set program name
GLib.set_prgname("system-config-printer")

def CUPS_server_hostname ():
    host = cups.getServer ()
    if host[0] == '/':
        return 'localhost'
    return host

class ServiceStart:

    def _get_iface (self, iface):
        bus = dbus.SystemBus ()
        obj = bus.get_object (self.NAME, self.PATH)
        proxy = dbus.Interface (obj, iface)
        return proxy

    def can_start (self):
        try:
            proxy = self._get_iface (dbus.INTROSPECTABLE_IFACE)
            introspect = proxy.Introspect()
        except:
            return False
        return True

    def start(self, reply_handler, error_handler):
        proxy = self._get_iface(self.IFACE)
        self._start(proxy, reply_handler, error_handler)


class SysVServiceStart(ServiceStart):
    NAME="org.fedoraproject.Config.Services"
    PATH="/org/fedoraproject/Config/Services/ServiceHerders/SysVServiceHerder/Services/cups"
    IFACE="org.fedoraproject.Config.Services.SysVService"

    def _start(self, proxy, reply_handler, error_handler):
        proxy.start(reply_handler=reply_handler,
                    error_handler=error_handler)


class SystemDServiceStart(ServiceStart):
    NAME="org.freedesktop.systemd1"
    PATH="/org/freedesktop/systemd1"
    IFACE="org.freedesktop.systemd1.Manager"
    CUPS_SERVICE="org.cups.cupsd.service"

    def _start(self, proxy, reply_handler, error_handler):
        proxy.StartUnit(self.CUPS_SERVICE, 'fail',
                        reply_handler=reply_handler,
                        error_handler=error_handler)



class GUI(GtkGUI):

    printer_states = { cups.IPP_PRINTER_IDLE: _("Idle"),
                       cups.IPP_PRINTER_PROCESSING: _("Processing"),
                       cups.IPP_PRINTER_BUSY: _("Busy"),
                       cups.IPP_PRINTER_STOPPED: _("Stopped") }

    DESTS_PAGE_DESTS=0
    DESTS_PAGE_NO_PRINTERS=1
    DESTS_PAGE_NO_SERVICE=2

    def __init__(self):

        super (GtkGUI, self).__init__ ()

        try:
            self.language = locale.getlocale(locale.LC_MESSAGES)
            self.encoding = locale.getlocale(locale.LC_CTYPE)
        except:
            nonfatalException()
            os.environ['LC_ALL'] = 'C'
            locale.setlocale (locale.LC_ALL, "")
            self.language = locale.getlocale(locale.LC_MESSAGES)
            self.encoding = locale.getlocale(locale.LC_CTYPE)

        self.printers = {}
        self.connect_server = cups.getServer()
        self.connect_encrypt = cups.getEncryption ()
        self.connect_user = cups.getUser()
        self.monitor = None
        self.populateList_timer = None

        self.servers = set((self.connect_server,))
        self.server_is_publishing = None # not known
        self.changed = set() # of options

        # WIDGETS
        # =======
        self.updating_widgets = False
        self.getWidgets({"PrintersWindow":
                             ["PrintersWindow",
                              "hboxMenuBar",
                              "view_area_vbox",
                              "view_area_scrolledwindow",
                              "dests_notebook",
                              "dests_iconview",
                              "btnAddFirstPrinter",
                              "btnStartService",
                              "btnConnectNoService",
                              "statusbarMain",
                              "toolbar",
                              "server_menubar_item",
                              "printer_menubar_item",
                              "view_discovered_printers"],
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
                         "InstallDialog":
                             ["InstallDialog",
                              "lblInstall"]},

                        domain=config.PACKAGE)

        if PlugWindowId:
            self.PrintersWindow.hide()
            # the "vbox4" widget
            vbox = self.PrintersWindow.get_children()[0]
            PlugWindow = Gtk.Plug.new(PlugWindowId)
            Gtk.Container.remove(self.PrintersWindow, vbox)
            PlugWindow.add(vbox)
            self.PrintersWindow.set_transient_for(PlugWindow)
            PlugWindow.show_all()
            self.PrintersWindow = PlugWindow

        # Since some dialogs are reused we can't let the delete-event's
        # default handler destroy them
        self.ConnectingDialog.connect ("delete-event",
                                       self.on_connectingdialog_delete)

        Gtk.Window.set_default_icon_name ('printer')

        edit_action = 'org.opensuse.cupspkhelper.mechanism.all-edit'
        self.edit_permission = None
        if Polkit:
            try:
                self.edit_permission = Polkit.Permission.new_sync (edit_action,
                                                                   None, None)
            except GLib.GError:
                pass # Maybe cups-pk-helper isn't installed.

        self.unlock_button = Gtk.LockButton ()
        if self.edit_permission is not None:
            self.edit_permission.connect ("notify::allowed",
                                          self.polkit_permission_changed)

        self.unlock_button.connect ("notify::permission",
                                    self.polkit_permission_changed)
        self.hboxMenuBar.pack_start (self.unlock_button, False, False, 12)

        # Printer Actions
        printer_manager_action_group = \
            Gtk.ActionGroup (name="PrinterManagerActionGroup")
        printer_manager_action_group.add_actions ([
                ("connect-to-server", Gtk.STOCK_CONNECT, _("_Connect..."),
                 None, _("Choose a different CUPS server"),
                 self.on_connect_activate),
                ("server-settings", Gtk.STOCK_PREFERENCES, _("_Settings..."),
                 None, _("Adjust server settings"),
                 self.on_server_settings_activate),
                ("new-printer", Gtk.STOCK_PRINT, _("_Printer"),
                 None, None, self.on_new_printer_activate),
                ("new-class", Gtk.STOCK_DND_MULTIPLE, _("_Class"),
                 None, None, self.on_new_class_activate),
                ("quit", Gtk.STOCK_QUIT, None, None, None,
                 self.on_quit_activate)])
        printer_manager_action_group.add_actions ([
                ("rename-printer", None, _("_Rename"),
                 None, None, self.on_rename_activate),
                ("duplicate-printer", Gtk.STOCK_COPY, _("_Duplicate"),
                 "<Ctrl>d", None, self.on_duplicate_activate),
                ("delete-printer", Gtk.STOCK_DELETE, None,
                 None, None, self.on_delete_activate),
                ("set-default-printer", Gtk.STOCK_HOME, _("Set As De_fault"),
                 None, None, self.on_set_as_default_activate),
                ("edit-printer", Gtk.STOCK_PROPERTIES, None,
                 None, None, self.on_edit_activate),
                ("create-class", Gtk.STOCK_DND_MULTIPLE, _("_Create class"),
                 None, None, self.on_create_class_activate),
                ("view-print-queue", Gtk.STOCK_FIND, _("View Print _Queue"),
                 None, None, self.on_view_print_queue_activate),
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
        for action in ["connect-to-server",
                       "quit",
                       "view-print-queue",
                       "filter-name",
                       "filter-description",
                       "filter-location",
                       "filter-manufacturer"]:
            act = printer_manager_action_group.get_action (action)
            act.set_sensitive (True)

        self.ui_manager = Gtk.UIManager ()
        self.ui_manager.insert_action_group (printer_manager_action_group, -1)
        self.ui_manager.add_ui_from_string (
"""
<ui>
 <accelerator action="connect-to-server"/>
 <accelerator action="server-settings"/>
 <accelerator action="new-printer"/>
 <accelerator action="new-class"/>
 <accelerator action="quit"/>

 <accelerator action="rename-printer"/>
 <accelerator action="duplicate-printer"/>
 <accelerator action="delete-printer"/>
 <accelerator action="set-default-printer"/>
 <accelerator action="edit-printer"/>
 <accelerator action="create-class"/>
 <accelerator action="view-print-queue"/>
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

        # Toolbar
        # Glade-3 doesn't have support for MenuToolButton, so we do that here.
        self.btnNew = Gtk.MenuToolButton ()
        self.btnNew.set_label (_("Add"))
        self.btnNew.set_icon_name ("list-add")
        self.btnNew.set_is_important (True)
        newmenu = Gtk.Menu ()
        action = self.ui_manager.get_action ("/new-printer")
        newprinteritem = action.create_menu_item ()
        action = self.ui_manager.get_action ("/new-class")
        newclassitem = action.create_menu_item ()
        newprinteritem.show ()
        newclassitem.show ()
        newmenu.attach (newprinteritem, 0, 1, 0, 1)
        newmenu.attach (newclassitem, 0, 1, 1, 2)
        self.btnNew.set_menu (newmenu)
        self.btnNew.connect ('clicked', self.on_new_printer_activate)
        self.toolbar.add (self.btnNew)
        self.toolbar.add (Gtk.SeparatorToolItem ())
        self.refreshbutton = Gtk.ToolButton ()
        self.refreshbutton.set_label (_("Refresh"))
        self.refreshbutton.set_icon_name ("view-refresh")
        self.refreshbutton.connect ('clicked', self.on_btnRefresh_clicked)
        self.toolbar.add (self.refreshbutton)
        self.toolbar.show_all ()

        server_context_menu = Gtk.Menu ()
        for action_name in ["connect-to-server",
                            "server-settings",
                            None,
                            "new",
                            None,
                            "quit"]:
            if action_name == "new":
                item = Gtk.MenuItem.new_with_mnemonic(_("_New"))
                item.set_sensitive (True)
                self.menuItemNew = item
            elif not action_name:
                item = Gtk.SeparatorMenuItem ()
            else:
                action = printer_manager_action_group.get_action (action_name)
                item = action.create_menu_item ()
            item.show ()
            server_context_menu.append (item)
        self.server_menubar_item.set_submenu (server_context_menu)

        new_menu = Gtk.Menu ()
        for action_name in ["new-printer",
                            "new-class"]:
            action = printer_manager_action_group.get_action (action_name)
            item = action.create_menu_item ()
            item.show ()
            new_menu.append (item)
        self.menuItemNew.set_submenu (new_menu)

        self.printer_context_menu = Gtk.Menu ()
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
                            "view-print-queue"]:
            if not action_name:
                item = Gtk.SeparatorMenuItem ()
            else:
                action = printer_manager_action_group.get_action (action_name)
                item = action.create_menu_item ()
            item.show ()
            self.printer_context_menu.append (item)
        self.printer_menubar_item.set_submenu (self.printer_context_menu)

        self.jobviewers = [] # to keep track of jobviewer windows

        # New Printer Dialog
        self.newPrinterGUI = np = newprinter.NewPrinterGUI()
        np.connect ("printer-added", self.on_new_printer_added)
        np.connect ("printer-modified", self.on_printer_modified)
        np.connect ("dialog-canceled", self.on_new_printer_not_added)

        # Set up "About" dialog
        self.AboutDialog.set_program_name(config.PACKAGE)
        self.AboutDialog.set_version(config.VERSION)
        self.AboutDialog.set_icon_name('printer')

        try:
            self.cups = authconn.Connection(self.PrintersWindow)
        except RuntimeError:
            self.cups = None

        self.status_context_id = self.statusbarMain.get_context_id(
            "Connection")

        # Setup search
        self.setup_toolbar_for_search_entry ()
        self.current_filter_text = ""
        self.current_filter_mode = "filter-name"

        # Search entry drop down menu
        menu = Gtk.Menu ()
        for action_name in ["filter-name",
                            "filter-description",
                            "filter-location",
                            "filter-manufacturer"]:
            action = printer_manager_action_group.get_action (action_name)
            item = action.create_menu_item ()
            menu.append (item)
        menu.show_all ()
        self.search_entry.set_drop_down_menu (menu)

        if os.path.exists("/usr/lib/systemd"):
            self.servicestart = SystemDServiceStart()
        else:
            self.servicestart = SysVServiceStart()

        # Setup icon view
        self.mainlist = Gtk.ListStore(GObject.TYPE_PYOBJECT,    # Object
                                      GdkPixbuf.Pixbuf,         # Pixbuf
                                      str,                      # Name
                                      str)                      # Tooltip

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
        self.dests_iconview.enable_model_drag_source (Gdk.ModifierType.BUTTON1_MASK,
                                                      # should use a variable
                                                      # instead of 0
                                                      [Gtk.TargetEntry.new("queue", 0, 0)],
                                                      Gdk.DragAction.COPY)
        self.dests_iconview.connect ("drag-data-get",
                                     self.dests_iconview_drag_data_get)
        self.btnStartService.connect ('clicked', self.on_start_service_clicked)
        self.btnConnectNoService.connect ('clicked', self.on_connect_activate)
        self.btnAddFirstPrinter.connect ('clicked',
                                         self.on_new_printer_activate)

        # Printer Properties dialog
        self.propertiesDlg = printerproperties.PrinterPropertiesDialog ()
        self.propertiesDlg.connect ("dialog-closed",
                                    self.on_properties_dialog_closed)

        self.connect_signals ()

        try:
            self.populateList()
        except cups.HTTPError as e:
            (s,) = e.args
            self.cups = None
            self.populateList()
            show_HTTP_Error(s, self.PrintersWindow)

        self.setConnected()

        if len (self.printers) > 4:
            self.PrintersWindow.set_default_size (720, 345)
        elif len (self.printers) > 2:
            self.PrintersWindow.set_default_size (500, 345)
        elif len (self.printers) > 1:
            self.PrintersWindow.set_default_size (500, 180)


        self.PrintersWindow.show()

    def display_properties_dialog_for (self, queue):
        model = self.dests_iconview.get_model ()
        iter = model.get_iter_first ()
        while iter is not None:
            name = model.get_value (iter, 2)
            if name == queue:
                path = model.get_path (iter)
                self.dests_iconview.scroll_to_path (path, True, 0.5, 0.5)
                self.dests_iconview.set_cursor (path=path, cell=None,
                                                start_editing=False)
                self.dests_iconview.item_activated (path)
                break
            iter = model.iter_next (iter)

        if iter is None:
            raise RuntimeError

    def setup_toolbar_for_search_entry (self):
        separator = Gtk.SeparatorToolItem ()
        separator.set_draw (False)

        self.toolbar.insert (separator, -1)
        self.toolbar.child_set_property (separator, "expand", True)

        self.search_entry = ToolbarSearchEntry ()
        self.search_entry.connect ('search', self.on_search_entry_search)

        tool_item = Gtk.ToolItem ()
        tool_item.add (self.search_entry)
        self.toolbar.insert (tool_item, -1)
        self.toolbar.show_all ()

    def on_search_entry_search (self, UNUSED, text):
        self.current_filter_text = text
        self.populateList ()

    def on_filter_criterion_changed (self, UNUSED, selected_action):
        self.current_filter_mode = selected_action.get_name ()
        self.populateList ()

    def dests_iconview_item_activated (self, iconview, path):
        model = iconview.get_model ()
        iter = model.get_iter (path)
        name = model.get_value (iter, 2)
        object = model.get_value (iter, 0)

        self.desensitise_main_window_widgets ()
        try:
            self.propertiesDlg.show (name, host=self.connect_server,
                                     encryption=self.connect_encrypt,
                                     parent=self.PrintersWindow)
        except cups.IPPError as e:
            (e, m) = e.args
            self.sensitise_main_window_widgets ()
            show_IPP_Error (e, m, self.PrintersWindow)
            if e == cups.IPP_SERVICE_UNAVAILABLE:
                self.cups = None
                self.setConnected ()
                self.populateList ()
            return
        except RuntimeError:
            self.sensitise_main_window_widgets ()
            # Perhaps cupsGetPPD2 failed for a browsed printer.

            # Check that we're still connected.
            self.monitor.update ()
            return

    def on_properties_dialog_closed (self, obj):
        self.sensitise_main_window_widgets ()

    def dests_iconview_selection_changed (self, iconview):
        self.updating_widgets = True
        permission = self.unlock_button.get_permission ()
        if permission:
            can_edit = permission.get_allowed ()
        else:
            can_edit = True

        if not can_edit:
            return

        paths = iconview.get_selected_items ()
        any_disabled = False
        any_enabled = False
        any_discovered = False
        any_shared = False
        any_unshared = False
        model = iconview.get_model ()
        for path in paths:
            iter = model.get_iter (path)
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

        n = len (paths)
        self.ui_manager.get_action ("/edit-printer").set_sensitive (n == 1)

        self.ui_manager.get_action ("/duplicate-printer").set_sensitive (n == 1)

        self.ui_manager.get_action ("/rename-printer").set_sensitive (
            n == 1 and not any_discovered)

        userdef = userdefault.UserDefaultPrinter ().get ()
        if (n != 1 or
            (userdef is None and self.default_printer == name)):
            set_default_sensitivity = False
        else:
            set_default_sensitivity = True

        self.ui_manager.get_action ("/set-default-printer").set_sensitive (
            set_default_sensitivity)

        action = self.ui_manager.get_action ("/enable-printer")
        action.set_sensitive (n > 0 and not any_discovered)
        for widget in action.get_proxies ():
            if isinstance (widget, Gtk.CheckMenuItem):
                widget.set_inconsistent (n > 1 and any_enabled and any_disabled)
        action.set_active (any_discovered or not any_disabled)

        action = self.ui_manager.get_action ("/share-printer")
        action.set_sensitive (n > 0 and not any_discovered)
        for widget in action.get_proxies ():
            if isinstance (widget, Gtk.CheckMenuItem):
                widget.set_inconsistent (n > 1 and any_shared and any_unshared)
        action.set_active (any_discovered or not any_unshared)

        self.ui_manager.get_action ("/delete-printer").set_sensitive (
            n > 0 and not any_discovered)

        self.ui_manager.get_action ("/create-class").set_sensitive (n > 1)

        self.updating_widgets = False

    def dests_iconview_popup_menu (self, iconview):
        self.printer_context_menu.popup_for_device (None, None, None, None,
                                            None, 0, 0)

    def dests_iconview_button_press_event (self, iconview, event):
        if event.button > 1:
            click_path = iconview.get_path_at_pos (int (event.x),
                                                   int (event.y))
            paths = iconview.get_selected_items ()
            if click_path is None:
                iconview.unselect_all ()
            elif click_path not in paths:
                iconview.unselect_all ()
                iconview.select_path (click_path)
                cells = iconview.get_cells ()
                for cell in cells:
                    if type (cell) == Gtk.CellRendererText:
                        break
                iconview.set_cursor (click_path, cell, False)
            self.printer_context_menu.popup_for_device (None, None, None, None,
                                             None, event.button, event.time)
        return False

    def dests_iconview_key_press_event (self, iconview, event):
        modifiers = Gtk.accelerator_get_default_mod_mask ()

        if ((event.keyval == Gdk.KEY_BackSpace or
             event.keyval == Gdk.KEY_Delete or
             event.keyval == Gdk.KEY_KP_Delete) and
            ((event.get_state() & modifiers) == 0)):

            self.ui_manager.get_action ("/delete-printer").activate ()
            return True

        if ((event.keyval == Gdk.KEY_F2) and
            ((event.get_state() & modifiers) == 0)):

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
            self.serverSettings = ServerSettings (host=self.connect_server,
                                                  encryption=self.connect_encrypt,
                                                  parent=self.PrintersWindow)
            self.serverSettings.connect ('problems-clicked',
                                         self.on_problems_button_clicked)
        except (cups.IPPError, cups.HTTPError):
            # Not authorized.
            return
        except RuntimeError:
            self.monitor.update ()

    def setConnected(self):
        connected = bool(self.cups)

        host = CUPS_server_hostname ()
        self.PrintersWindow.set_title(_("Print Settings - %s") % host)

        if connected:
            status_msg = _("Connected to %s") % host
        else:
            status_msg = _("Not connected")
        self.statusbarMain.push(self.status_context_id, status_msg)

        for widget in (self.btnNew,
                       self.menuItemNew):
            widget.set_sensitive(connected)

        for action_name in ["/server-settings",
                            "/new-printer",
                            "/new-class"]:
            action = self.ui_manager.get_action (action_name)
            action.set_sensitive (connected)

        if connected:
            if self.monitor:
                self.monitor.cleanup ()

            self.monitor = monitor.Monitor (monitor_jobs=False,
                                            host=self.connect_server,
                                            encryption=self.connect_encrypt)
            self.monitor.connect ('printer-added', self.printer_added)
            self.monitor.connect ('printer-event', self.printer_event)
            self.monitor.connect ('printer-removed', self.printer_removed)
            self.monitor.connect ('cups-connection-error',
                                  self.cups_connection_error)
            self.monitor.connect ('cups-connection-recovered',
                                  self.cups_connection_recovered)
            GLib.idle_add (self.monitor.refresh)
            self.propertiesDlg.set_monitor (self.monitor)

        if connected:
            if self.cups._using_polkit ():
                self.unlock_button.set_permission (self.edit_permission)
            else:
                self.unlock_button.set_permission (None)

        else:
            self.unlock_button.set_permission (None)

    def polkit_permission_changed (self, widget, UNUSED):
        permission = self.unlock_button.get_permission ()
        if permission:
            can_edit = permission.get_allowed ()
        else:
            can_edit = True

        self.btnNew.set_sensitive (can_edit)
        self.btnAddFirstPrinter.set_sensitive (can_edit)
        for action in ["/new-printer",
                       "/new-class"]:
            act = self.ui_manager.get_action (action)
            act.set_sensitive (can_edit)

        if can_edit:
            self.dests_iconview_selection_changed (self.dests_iconview)
        else:
            for action in ["/rename-printer",
                           "/duplicate-printer",
                           "/delete-printer",
                           "/edit-printer",
                           "/create-class",
                           "/enable-printer",
                           "/share-printer"]:
                act = self.ui_manager.get_action (action)
                act.set_sensitive (False)

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
            kill_connection = False
            self.cups._set_prompt_allowed (prompt_allowed)
            self.cups._begin_operation (_("obtaining queue details"))
            try:
                # get Printers
                self.printers = cupshelpers.getPrinters(self.cups)

                # Get default printer.
                self.default_printer = self.cups.getDefault ()
            except cups.IPPError as e:
                (e, m) = e.args
                show_IPP_Error(e, m, self.PrintersWindow)
                self.printers = {}
                self.default_printer = None
                if e == cups.IPP_SERVICE_UNAVAILABLE:
                    kill_connection = True

            self.cups._end_operation ()
            self.cups._set_prompt_allowed (True)
            if kill_connection:
                self.cups = None
        else:
            self.printers = {}
            self.default_printer = None

        for name, printer in self.printers.items():
            self.servers.add(printer.getServer())

        userdef = userdefault.UserDefaultPrinter ().get ()

        local_printers = []
        local_classes = []
        remote_printers = []
        remote_classes = []

        delete_action = self.ui_manager.get_action ("/delete-printer")
        delete_action.set_properties (label = None)
        printers_set = self.printers

        # Filter printers
        if len (self.current_filter_text) > 0:
            printers_subset = {}
            pattern = re.compile (self.current_filter_text, re.I) # ignore case

            if self.current_filter_mode == "filter-name":
                for name in printers_set.keys ():
                    if pattern.search (name) is not None:
                        printers_subset[name] = printers_set[name]
            elif self.current_filter_mode == "filter-description":
                for name, printer in printers_set.items ():
                    if pattern.search (printer.info) is not None:
                        printers_subset[name] = printers_set[name]
            elif self.current_filter_mode == "filter-location":
                for name, printer in printers_set.items ():
                    if pattern.search (printer.location) is not None:
                        printers_subset[name] = printers_set[name]
            elif self.current_filter_mode == "filter-manufacturer":
                for name, printer in printers_set.items ():
                    if pattern.search (printer.make_and_model) is not None:
                        printers_subset[name] = printers_set[name]
            else:
                nonfatalException ()

            printers_set = printers_subset

        if not self.view_discovered_printers.get_active ():
            printers_subset = {}
            for name, printer in printers_set.items ():
                if not printer.discovered:
                    printers_subset[name] = printer

            printers_set = printers_subset

        for name, printer in list(printers_set.items()):
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
                              'i-network-printer'),
                         'network-printer':
                             (_("Network printer"),
                              'i-network-printer'),
                         }
        theme = Gtk.IconTheme.get_default ()
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
                    (scheme, rest) = urllib.parse.splittype (object.device_uri)
                    if scheme in ['ipp', 'ipps']:
                        if rest.startswith("//localhost"): # IPP-over-USB
                            type = 'local-printer'
                        else: # IPP network printer
                            type = 'ipp-printer'
                    elif scheme == 'smb':
                        type = 'smb-printer'
                    elif scheme == 'hpfax':
                        type = 'local-fax'
                    elif scheme in ['socket', 'lpd', 'dnssd']:
                        type = 'network-printer'
                    elif object.device_uri.startswith('hp:/net/'):
                        type = 'network-printer'
                    elif object.device_uri.startswith('hpfax:/net/'):
                        type = 'network-printer'
                    elif scheme == 'implicitclass': # cups-browsed-discovered
                        type = 'discovered-printer'

                (tip, icon) = PRINTER_TYPE[type]
                (result, w, h) = Gtk.icon_size_lookup (Gtk.IconSize.DIALOG)
                try:
                    pixbuf = theme.load_icon (icon, w, 0)
                except GLib.GError:
                    # Not in theme.
                    pixbuf = None
                    for p in [iconpath, 'icons/']:
                        try:
                            pixbuf = GdkPixbuf.Pixbuf.new_from_file ("%s%s.png" %
                                                                   (p, icon))
                            break
                        except GLib.GError:
                            pass

                    if pixbuf is None:
                        try:
                            pixbuf = theme.load_icon ('printer', w, 0)
                        except:
                            # Just create an empty pixbuf.
                            pixbuf = GdkPixbuf.Pixbuf.new (GdkPixbuf.Colorspace.RGB,
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
                            emblem = "media-playback-pause"
                            continue

                        r = statereason.StateReason (object.name, reason)
                        if worst_reason is None:
                            worst_reason = r
                        elif r > worst_reason:
                            worst_reason = r

                    if worst_reason:
                        level = worst_reason.get_level ()
                        emblem = worst_reason.LEVEL_ICON[level]

                if not emblem and not object.enabled:
                    emblem = "media-playback-pause"

                if object.rejecting:
                    # Show the icon as insensitive
                    copy = pixbuf.copy ()
                    copy.fill (0)
                    pixbuf.composite (copy, 0, 0,
                                      pixbuf.get_width(), pixbuf.get_height(),
                                      0, 0, 1.0, 1.0,
                                      GdkPixbuf.InterpType.BILINEAR, 127)
                    pixbuf = copy

                if def_emblem:
                    (result, w, h) = Gtk.icon_size_lookup (Gtk.IconSize.DIALOG)
                    try:
                        default_emblem = theme.load_icon (def_emblem, w/2, 0)
                        copy = pixbuf.copy ()
                        default_emblem.composite (copy, 0, 0,
                                                  default_emblem.get_width (),
                                                  default_emblem.get_height (),
                                                  0, 0,
                                                  1.0, 1.0,
                                                  GdkPixbuf.InterpType.BILINEAR,
                                                  255)
                        pixbuf = copy
                    except GLib.GError:
                        debugprint ("No %s icon available" % def_emblem)

                if emblem:
                    (result, w, h) = Gtk.icon_size_lookup (Gtk.IconSize.DIALOG)
                    try:
                        other_emblem = theme.load_icon (emblem, w/2, 0)
                        copy = pixbuf.copy ()
                        other_emblem.composite (copy,
                                                copy.get_width () / 2,
                                                copy.get_height () / 2,
                                                other_emblem.get_width (),
                                                other_emblem.get_height (),
                                                copy.get_width () / 2,
                                                copy.get_height () / 2,
                                                1.0, 1.0,
                                                GdkPixbuf.InterpType.BILINEAR,
                                                255)
                        pixbuf = copy
                    except GLib.GError:
                        debugprint ("No %s icon available" % emblem)

                self.mainlist.append (row=[object, pixbuf, name, tip])

        # Restore selection of printers.
        model = self.dests_iconview.get_model ()
        def maybe_select (model, path, iter, UNUSED):
            name = model.get_value (iter, 2)
            if name in selected_printers:
                self.dests_iconview.select_path (path)
        model.foreach (maybe_select, None)

        # Set up the dests_notebook page.
        page = self.DESTS_PAGE_DESTS
        if self.cups:
            if (not self.current_filter_text and
                not self.mainlist.get_iter_first ()):
                page = self.DESTS_PAGE_NO_PRINTERS
        else:
            page = self.DESTS_PAGE_NO_SERVICE
            can_start = (self.connect_server == 'localhost' or
                         self.connect_server[0] != '/')
            tooltip_text = None
            if can_start:
                can_start = self.servicestart.can_start ()
                if not can_start:
                    tooltip_text = _("Service framework not available")
            else:
                tooltip_text = _("Cannot start service on remote server")

            self.btnStartService.set_sensitive (can_start)
            self.btnStartService.set_tooltip_text (tooltip_text)

        self.dests_notebook.set_current_page (page)

    # Connect to Server

    def on_connect_servername_changed(self, widget):
        self.btnConnect.set_sensitive (len (widget.get_active_text () or '') > 0)

    def on_connect_activate(self, widget):
        # Use browsed queues to build up a list of known IPP servers
        servers = self.getServers()
        current_server = (self.propertiesDlg.printer and
                          self.propertiesDlg.printer.getServer()) \
                          or cups.getServer()

        store = Gtk.ListStore (str)
        self.cmbServername.set_model(store)
        self.cmbServername.set_entry_text_column (0)
        for server in servers:
            self.cmbServername.append_text(server)
        self.cmbServername.show()

        self.cmbServername.get_child().set_text (current_server)
        self.chkEncrypted.set_active (cups.getEncryption() ==
                                      cups.HTTP_ENCRYPT_ALWAYS)

        self.cmbServername.get_child().set_activates_default (True)
        self.cmbServername.grab_focus ()
        self.ConnectDialog.set_transient_for (self.PrintersWindow)
        response = self.ConnectDialog.run()

        self.ConnectDialog.hide()

        if response != Gtk.ResponseType.OK:
            return

        if self.chkEncrypted.get_active():
            cups.setEncryption(cups.HTTP_ENCRYPT_ALWAYS)
        else:
            cups.setEncryption(cups.HTTP_ENCRYPT_IF_REQUESTED)
        self.connect_encrypt = cups.getEncryption ()

        servername = self.cmbServername.get_child().get_text()

        self.lblConnecting.set_markup(_("<i>Opening connection to %s</i>")
                                       % servername)
        self.ConnectingDialog.set_transient_for(self.PrintersWindow)
        self.ConnectingDialog.show()
        GLib.timeout_add (40, self.update_connecting_pbar)
        self.connect_server = servername
        # We need to set the connecting user in this thread as well.
        cups.setServer(self.connect_server)
        cups.setUser('')
        self.connect_user = cups.getUser()
        # Now start a new thread for connection.
        self.connect_thread = _thread.start_new_thread(self.connect,
                                                      (self.PrintersWindow,))

    def update_connecting_pbar (self):
        ret = True
        Gdk.threads_enter ()
        try:
            if not self.ConnectingDialog.get_property ("visible"):
                ret = False # stop animation
            else:
                self.pbarConnecting.pulse ()
        finally:
            Gdk.threads_leave ()

        return ret

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
        except RuntimeError as s:
            if self.connect_thread != _thread.get_ident(): return
            Gdk.threads_enter()
            try:
                self.ConnectingDialog.hide()
                self.cups = None
                self.setConnected()
                self.populateList()
                show_IPP_Error(None, s, parent)
            finally:
                Gdk.threads_leave()
            return
        except cups.IPPError as e:
            (e, s) = e.args
            if self.connect_thread != _thread.get_ident(): return
            Gdk.threads_enter()
            try:
                self.ConnectingDialog.hide()
                self.cups = None
                self.setConnected()
                self.populateList()
                show_IPP_Error(e, s, parent)
            finally:
                Gdk.threads_leave()
            return
        except:
            nonfatalException ()

        if self.connect_thread != _thread.get_ident(): return
        Gdk.threads_enter()

        try:
            self.ConnectingDialog.hide()
            self.cups = connection
            self.setConnected()
            self.populateList()
        except cups.HTTPError as e:
            (s,) = e.args
            self.cups = None
            self.setConnected()
            self.populateList()
            show_HTTP_Error(s, parent)
        except:
            nonfatalException ()

        Gdk.threads_leave()

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
        if self.cups is None:
            try:
                self.cups = authconn.Connection(self.PrintersWindow)
            except RuntimeError:
                pass

            self.setConnected()

        self.populateList()

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
        except cups.HTTPError as e:
            (s,) = e.args
            show_HTTP_Error (s, self.PrintersWindow)
            self.cups._end_operation ()
            return
        except cups.IPPError as e:
            (e, msg) = e.args
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
        except cups.HTTPError as e:
            (s,) = e.args
            self.cups = None
            self.setConnected()
            self.populateList()
            show_HTTP_Error(s, self.PrintersWindow)

    # Quit

    def on_quit_activate(self, widget, event=None):
        if self.populateList_timer:
            GLib.source_remove (self.populateList_timer)

        self.populateList_timer = None
        if self.monitor:
            self.monitor.cleanup ()

        while len (self.jobviewers) > 0:
            # this will call on_jobviewer_exit
            self.jobviewers[0].on_delete_event ()
        self.propertiesDlg.destroy ()
        self.newPrinterGUI.destroy ()
        Gtk.main_quit()
        del self.mainlist
        del self.printers

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
            dialog = Gtk.MessageDialog (parent=self.PrintersWindow,
                                        modal=True, destroy_with_parent=True,
                                        message_type=Gtk.MessageType.WARNING,
                                        buttons=Gtk.ButtonsType.OK_CANCEL,
                                        text=_("Renaming will lose history"))

            dialog.format_secondary_text (_("Completed jobs will no longer "
                                            "be available for re-printing."))
            result = dialog.run()
            dialog.destroy ()
            if result == Gtk.ResponseType.CANCEL:
                return False

        return True

    def on_rename_activate(self, *UNUSED):
        tuple = self.dests_iconview.get_cursor ()
        if tuple is None:
            return

        (res, path, cell) = tuple
        if path is None:
            # Printer removed?
            return

        if type (cell) != Gtk.CellRendererText:
            cells = self.dests_iconview.get_cells ()
            for cell in cells:
                if type (cell) == Gtk.CellRendererText:
                    break
            if type (cell) != Gtk.CellRendererText:
                return

        model = self.dests_iconview.get_model ()
        iter = model.get_iter (path)
        name = model.get_value (iter, 2)
        if not self.is_rename_possible (name):
            return
        if not self.rename_confirmed_by_user (name):
            return
        cell.set_property ('editable', True)
        ids = []
        ids.append (cell.connect ('editing-started',
                                 self.printer_name_edit_start))
        ids.append (cell.connect ('editing-canceled',
                                 self.printer_name_edit_cancel))
        self.rename_sigids = ids
        self.rename_entry_sigids = []
        self.dests_iconview.set_cursor (path, cell, True)

    def printer_name_edit_start (self, cell, editable, path):
        debugprint ("editing-started with cell=%s, editable=%s" %
                    (repr (cell),
                     repr (editable)))
        if isinstance(editable, Gtk.Entry):
            id = editable.connect('changed', self.printer_name_editing)
            self.rename_entry_sigids.append ((editable, id))

            model = self.dests_iconview.get_model ()
            iter = model.get_iter (path)
            name = model.get_value (iter, 2)
            id = editable.connect('editing-done',
                                  self.printer_name_editing_done,
                                  cell, name)
            self.rename_entry_sigids.append ((editable, id))

    def printer_name_editing (self, entry):
        newname = origname = entry.get_text()
        newname = newname.replace("/", "")
        newname = newname.replace("#", "")
        newname = newname.replace(" ", "")
        if origname != newname:
            debugprint ("removed disallowed character %s" % origname[-1])
            entry.set_text(newname)

    def printer_name_editing_done (self, entry, cell, name):
        debugprint (repr (cell))
        newname = entry.get_text ()
        debugprint ("edited: %s -> %s" % (name, newname))
        try:
            self.rename_printer (name, newname)
        finally:
            cell.stop_editing (False)
            cell.set_property ('editable', False)
            for id in self.rename_sigids:
                cell.disconnect (id)
            for obj, id in self.rename_entry_sigids:
                obj.disconnect (id)

    def printer_name_edit_cancel (self, cell):
        debugprint ("editing-canceled (%s)" % repr (cell))
        cell.stop_editing (True)
        cell.set_property ('editable', False)
        for id in self.rename_sigids:
            cell.disconnect (id)
        for obj, id in self.rename_entry_sigids:
            obj.disconnect (id)

    def rename_printer (self, old_name, new_name):
        if old_name.lower() == new_name.lower():
            return

        try:
            self.propertiesDlg.load (old_name,
                                     host=self.connect_server,
                                     encryption=self.connect_encrypt,
                                     parent=self.PrintersWindow)
        except RuntimeError:
            # Perhaps cupsGetPPD2 failed for a browsed printer
            pass
        except cups.IPPError as e:
            (e, m) = e.args
            show_IPP_Error (e, m, self.PrintersWindow)
            self.populateList ()
            return

        if not self.is_rename_possible (old_name):
            return

        self.cups._begin_operation (_("renaming printer"))
        rejecting = self.propertiesDlg.printer.rejecting
        if not rejecting:
            try:
                self.propertiesDlg.printer.setAccepting (False)
                if not self.is_rename_possible (old_name):
                    self.propertiesDlg.printer.setAccepting (True)
                    self.cups._end_operation ()
                    return
            except cups.IPPError as e:
                (e, msg) = e.args
                show_IPP_Error (e, msg, self.PrintersWindow)
                self.cups._end_operation ()
                return

        if self.duplicate_printer (new_name):
            # Failure.
            self.monitor.update ()

            # Restore original accepting/rejecting state.
            if not rejecting and self.propertiesDlg.printer:
                try:
                    self.propertiesDlg.printer.name = old_name
                    self.propertiesDlg.printer.setAccepting (True)
                except cups.HTTPError as e:
                    (s,) = e.args
                    show_HTTP_Error (s, self.PrintersWindow)
                except cups.IPPError as e:
                    (e, msg) = e.args
                    show_IPP_Error (e, msg, self.PrintersWindow)

            self.cups._end_operation ()
            self.populateList ()
            return

        if not self.propertiesDlg.printer:
            self.cups._end_operation ()
            self.populateList ()
            return

        # Restore rejecting state.
        if not rejecting:
            try:
                self.propertiesDlg.printer.setAccepting (True)
            except cups.HTTPError as e:
                (s,) = e.args
                show_HTTP_Error (s, self.PrintersWindow)
                # Not fatal.
            except cups.IPPError as e:
                (e, msg) = e.args
                show_IPP_Error (e, msg, self.PrintersWindow)
                # Not fatal.

        # Fix up default printer.
        if self.default_printer == old_name:
            reload = False
            try:
                reload = self.propertiesDlg.printer.setAsDefault ()
            except cups.HTTPError as e:
                (s,) = e.args
                show_HTTP_Error (s, self.PrintersWindow)
                # Not fatal.
            except cups.IPPError as e:
                (e, msg) = e.args
                show_IPP_Error (e, msg, self.PrintersWindow)
                # Not fatal.

            if reload:
                self.reconnect ()

        # Finally, delete the old printer.
        try:
            self.cups.deletePrinter (old_name)
        except cups.HTTPError as e:
            (s,) = e.args
            show_HTTP_Error (s, self.PrintersWindow)
            # Not fatal
        except cups.IPPError as e:
            (e, msg) = e.args
            show_IPP_Error (e, msg, self.PrintersWindow)
            # Not fatal.

        self.cups._end_operation ()

        # ..and select the new printer.
        def select_new_printer (model, path, iter, UNUSED):
            name = model.get_value (iter, 2)
            if name == new_name:
                self.dests_iconview.select_path (path)
        self.populateList ()
        model = self.dests_iconview.get_model ()
        model.foreach (select_new_printer, None)

    # Duplicate

    def duplicate_printer (self, new_name):
        self.propertiesDlg.printer.name = new_name
        self.propertiesDlg.printer.class_members = [] # for classes make sure all members
                                        # will get added

        ret = self.propertiesDlg.save_printer(self.propertiesDlg.printer,
                                              saveall=True,
                                              parent=self.PrintersWindow)
        return ret

    def on_duplicate_activate(self, *UNUSED):
        iconview = self.dests_iconview
        paths = iconview.get_selected_items ()
        model = self.dests_iconview.get_model ()
        iter = model.get_iter (paths[0])
        name = model.get_value (iter, 2)
        self.entDuplicateName.set_text(name)
        self.NewPrinterName.set_transient_for (self.PrintersWindow)
        result = self.NewPrinterName.run()
        self.NewPrinterName.hide()

        if result == Gtk.ResponseType.CANCEL:
            return

        try:
            self.propertiesDlg.load (name,
                                     host=self.connect_server,
                                     encryption=self.connect_encrypt,
                                     parent=self.PrintersWindow)
        except RuntimeError:
            # Perhaps cupsGetPPD2 failed for a browsed printer
            pass
        except cups.IPPError as e:
            (e, m) = e.args
            show_IPP_Error (e, m, self.PrintersWindow)
            self.populateList ()
            return

        self.duplicate_printer (self.entDuplicateName.get_text ())
        self.monitor.update ()

    def on_entDuplicateName_changed(self, widget):
        # restrict
        text = widget.get_text()
        new_text = text
        new_text = new_text.replace("/", "")
        new_text = new_text.replace("#", "")
        new_text = new_text.replace(" ", "")
        if text!=new_text:
            widget.set_text(new_text)
        self.btnDuplicateOk.set_sensitive(
            newprinter.checkNPName(self.printers, new_text))

    # Delete

    def on_delete_activate(self, *UNUSED):
        self.delete_selected_printer_queues ()

    def delete_selected_printer_queues (self):
        paths = self.dests_iconview.get_selected_items ()
        model = self.dests_iconview.get_model ()
        to_delete = []
        n = len (paths)
        if n == 1:
            itr = model.get_iter (paths[0])
            obj = model.get_value (itr, 0)
            name = model.get_value (itr, 2)
            if obj.is_class:
                message_format = (_("Really delete class '%s'?") % name)
            else:
                message_format = (_("Really delete printer '%s'?") % name)

            to_delete.append (name)
        else:
            message_format = _("Really delete selected destinations?")
            for path in paths:
                itr = model.get_iter (path)
                name = model.get_value (itr, 2)
                to_delete.append (name)
        dialog = Gtk.MessageDialog(parent=self.PrintersWindow,
                                   modal=True, destroy_with_parent=True,
                                   message_type=Gtk.MessageType.WARNING,
                                   buttons=Gtk.ButtonsType.NONE,
                                   text=message_format)
        dialog.add_buttons (_("_Cancel"), Gtk.ResponseType.REJECT,
                            _("_Delete"), Gtk.ResponseType.ACCEPT)
        dialog.set_default_response (Gtk.ResponseType.REJECT)
        result = dialog.run()
        dialog.destroy()

        if result != Gtk.ResponseType.ACCEPT:
            return

        try:
            for name in to_delete:
                self.cups._begin_operation (_("deleting printer %s") % name)
                self.cups.deletePrinter (name)
                self.cups._end_operation ()
        except cups.IPPError as e:
            (e, msg) = e.args
            self.cups._end_operation ()
            show_IPP_Error(e, msg, self.PrintersWindow)

        self.monitor.update ()

    # Enable/disable
    def on_enabled_activate(self, toggle_action):
        if self.updating_widgets:
            return
        enable = toggle_action.get_active ()
        iconview = self.dests_iconview
        paths = iconview.get_selected_items ()
        model = iconview.get_model ()
        printers = []
        for path in paths:
            itr = model.get_iter (path)
            printer = model.get_value (itr, 0)
            printers.append (printer)

        for printer in printers:
            self.cups._begin_operation (_("modifying printer %s") % printer.name)
            try:
                printer.setEnabled (enable)
            except cups.IPPError as e:
                (e, m) = e.args
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
        printers = []
        for path in paths:
            itr = model.get_iter (path)
            printer = model.get_value (itr, 0)
            printers.append (printer)

        success = False
        for printer in printers:
            self.cups._begin_operation (_("modifying printer %s")
                                        % printer.name)
            try:
                printer.setShared (share)
                success = True
            except cups.IPPError as e:
                (e, m) = e.args
                show_IPP_Error(e, m, self.PrintersWindow)
                self.cups._end_operation ()
                # Give up on this operation.
                break

            self.cups._end_operation ()

        if success and share:
            if self.server_is_publishing is None:
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
        self.defer_refresh ()

    def advise_publish(self):
        if not self.server_is_publishing:
            show_info_dialog (_("Publish Shared Printers"),
                              _("Shared printers are not available "
                                "to other people unless the "
                                "'Publish shared printers' option is "
                                "enabled in the server settings."),
                              parent=self.PrintersWindow)

    # Set As Default
    def on_set_as_default_activate(self, *UNUSED):
        iconview = self.dests_iconview
        paths = iconview.get_selected_items ()
        model = iconview.get_model ()
        try:
            iter = model.get_iter (paths[0])
        except IndexError:
            return

        name = model.get_value (iter, 2)
        self.set_system_or_user_default_printer (name)

    def on_edit_activate (self, *UNUSED):
        paths = self.dests_iconview.get_selected_items ()
        self.dests_iconview_item_activated (self.dests_iconview, paths[0])

    def on_create_class_activate (self, UNUSED):
        paths = self.dests_iconview.get_selected_items ()
        class_members = []
        model = self.dests_iconview.get_model ()
        for path in paths:
            iter = model.get_iter (path)
            name = model.get_value (iter, 2)
            class_members.append (name)
        if not self.newPrinterGUI.init ("class",
                                        host=self.connect_server,
                                        encryption=self.connect_encrypt,
                                        parent=self.PrintersWindow):
            self.monitor.update ()
            return

        out_model = self.newPrinterGUI.tvNCNotMembers.get_model ()
        in_model = self.newPrinterGUI.tvNCMembers.get_model ()
        iter = out_model.get_iter_first ()
        while iter is not None:
            next = out_model.iter_next (iter)
            data = out_model.get (iter, 0)
            if data[0] in class_members:
                in_model.append (data)
                out_model.remove (iter)
            iter = next

    def on_view_print_queue_activate (self, *UNUSED):
        paths = self.dests_iconview.get_selected_items ()
        if len (paths):
            specific_dests = []
            model = self.dests_iconview.get_model ()
            for path in paths:
                iter = model.get_iter (path)
                name = model.get_value (iter, 2)
                specific_dests.append (name)
            viewer = jobviewer.JobViewer (None, None, my_jobs=False,
                                          specific_dests=specific_dests,
                                          parent=self.PrintersWindow)
            viewer.connect ('finished', self.on_jobviewer_exit)
        else:
            viewer = jobviewer.JobViewer (None, None, my_jobs=False,
                                          parent=self.PrintersWindow)
            viewer.connect ('finished', self.on_jobviewer_exit)

        self.jobviewers.append (viewer)

    def on_jobviewer_exit (self, viewer):
        try:
            i = self.jobviewers.index (viewer)
            del self.jobviewers[i]
        except ValueError:
            # This shouldn't happen, but does (bug #757520).
            debugprint ("Jobviewer exited but not in list:\n"
                        "%s\n%s" % (repr (viewer), repr (self.jobviewers)))

    def on_view_discovered_printers_activate (self, UNUSED):
        self.populateList ()

    def on_troubleshoot_activate(self, widget):
        if 'troubleshooter' not in self.__dict__:
            self.troubleshooter = troubleshoot.run (self.on_troubleshoot_quit)

    def on_troubleshoot_quit(self, troubleshooter):
        del self.troubleshooter

    def sensitise_main_window_widgets (self, sensitive=True):
        self.dests_iconview.set_sensitive (sensitive)
        self.btnNew.set_sensitive (sensitive)
        self.btnAddFirstPrinter.set_sensitive (sensitive)
        self.refreshbutton.set_sensitive (sensitive)
        self.view_discovered_printers.set_sensitive (sensitive)
        self.search_entry.set_sensitive (sensitive)
        for action in ["/connect-to-server",
                       "/server-settings",
                       "/new-printer",
                       "/new-class",
                       "/rename-printer",
                       "/duplicate-printer",
                       "/delete-printer",
                       "/set-default-printer",
                       "/edit-printer",
                       "/create-class",
                       "/enable-printer",
                       "/share-printer",
                       "/filter-name",
                       "/filter-description",
                       "/filter-location",
                       "/filter-manufacturer"]:
            self.ui_manager.get_action (action).set_sensitive (sensitive)

        self.polkit_permission_changed (None, None)

    def desensitise_main_window_widgets (self):
        self.sensitise_main_window_widgets (False)

    # About dialog
    def on_about_activate(self, widget):
        self.AboutDialog.set_transient_for (self.PrintersWindow)
        self.AboutDialog.run()
        self.AboutDialog.hide()

    ##########################################################################
    ### Server settings
    ##########################################################################

    ### The "Problems?" clickable label
    def on_problems_button_clicked (self, serversettings):
        if 'troubleshooter' not in self.__dict__:
            self.troubleshooter = troubleshoot.run (self.on_troubleshoot_quit,
                                                    parent=serversettings.get_dialog ())

    # ====================================================================
    # == New Printer Dialog ==============================================
    # ====================================================================

    def sensitise_new_printer_widgets(self, sensitive=True):
        self.btnNew.set_sensitive (sensitive)
        self.btnAddFirstPrinter.set_sensitive (sensitive)
        self.ui_manager.get_action ("/new-printer").set_sensitive (sensitive)
        self.ui_manager.get_action ("/new-class").set_sensitive (sensitive)
        self.polkit_permission_changed (None, None)

    def desensitise_new_printer_widgets(self):
        self.sensitise_new_printer_widgets (False)

    # new printer
    def on_new_printer_activate(self, widget, *UNUSED):
        busy (self.PrintersWindow)
        self.desensitise_new_printer_widgets ()
        if not self.newPrinterGUI.init("printer",
                                       host=self.connect_server,
                                       encryption=self.connect_encrypt,
                                       parent=self.PrintersWindow):
            self.sensitise_new_printer_widgets ()
            self.monitor.update ()
        ready (self.PrintersWindow)

    # new class
    def on_new_class_activate(self, widget, *UNUSED):
        self.desensitise_new_printer_widgets ()
        if not self.newPrinterGUI.init("class",
                                       host=self.connect_server,
                                       encryption=self.connect_encrypt,
                                       parent=self.PrintersWindow):
            self.sensitise_new_printer_widgets ()
            self.monitor.update ()

    def on_new_printer_not_added (self, obj):
        self.sensitise_new_printer_widgets ()

    def on_new_printer_added (self, obj, name):
        debugprint ("New printer added: %s" % name)

        self.sensitise_new_printer_widgets ()
        self.populateList ()

        if name not in self.printers:
            # At this stage the printer has disappeared even though we
            # only added it moments ago.
            debugprint ("New printer disappeared")
            return

        # Now select it.
        model = self.dests_iconview.get_model ()
        iter = model.get_iter_first ()
        while iter is not None:
            queue = model.get_value (iter, 2)
            if queue == name:
                path = model.get_path (iter)
                self.dests_iconview.scroll_to_path (path, True, 0.5, 0.5)
                self.dests_iconview.unselect_all ()
                self.dests_iconview.set_cursor (path=path, cell=None,
                                                start_editing=False)
                self.dests_iconview.select_path (path)
                break

            iter = model.iter_next (iter)

        # Any missing drivers?
        self.propertiesDlg.load (name)
        if (self.propertiesDlg.ppd and
            not (self.propertiesDlg.printer.discovered or
                 self.propertiesDlg.printer.remote)):
            try:
                self.checkDriverExists (self.PrintersWindow, name,
                                        ppd=self.propertiesDlg.ppd)
            except:
                nonfatalException()

        # Finally, suggest printing a test page.
        if self.propertiesDlg.ppd:
            q = Gtk.MessageDialog (parent=self.PrintersWindow,
                                   modal=True, destroy_with_parent=True,
                                   message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.NONE,
                                   text=_("Would you like to print a test page?"))
            q.add_buttons (Gtk.STOCK_CANCEL, Gtk.ResponseType.NO,
                           _("Print Test Page"), Gtk.ResponseType.YES)
            response = q.run ()
            q.destroy ()
            if response == Gtk.ResponseType.YES:
                self.propertiesDlg.dialog.hide ()

                properties_shown = False
                try:
                    # Load the printer details but hide the properties dialog.
                    self.display_properties_dialog_for (name)
                    properties_shown = True
                except RuntimeError:
                    pass

                if properties_shown:
                    # Click the test button.
                    self.propertiesDlg.btnPrintTestPage.clicked ()

    ## Service start-up
    def on_start_service_clicked (self, button):
        button.set_sensitive (False)
        self.servicestart.start (reply_handler=self.on_start_service_reply,
                                 error_handler=self.on_start_service_reply)

    def on_start_service_reply (self, *args):
        GLib.timeout_add_seconds (1, self.service_started_try)

    def service_started_try (self):
        Gdk.threads_enter ()
        try:
            self.on_btnRefresh_clicked (None)
        finally:
            Gdk.threads_leave ()

        GLib.timeout_add_seconds (1, self.service_started_retry)
        return False

    def service_started_retry (self):
        if not self.cups:
            Gdk.threads_enter ()
            try:
                self.on_btnRefresh_clicked (None)
                self.btnStartService.set_sensitive (True)
            finally:
                Gdk.threads_leave ()

        return False

    def checkDriverExists(self, parent, name, ppd=None):
        """Check that the driver for an existing queue actually
        exists, and prompt to install the appropriate package
        if not.

        ppd: cups.PPD object, if already created"""

        # Is this queue on the local machine?  If not, we can't check
        # anything at all.
        server = cups.getServer ()
        if not (self.connect_server == 'localhost' or
                self.connect_server[0] == '/'):
            return

        # Fetch the PPD if we haven't already.
        if not ppd:
            try:
                filename = self.cups.getPPD(name)
            except cups.IPPError as e:
                (e, msg) = e.args
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
            can_install = False
            if len (pkgs) > 0:
                try:
                    pk = installpackage.PackageKit ()
                    can_install = True
                except:
                    pass

            if can_install and len (pkgs) > 0:
                pkg = pkgs[0]
                install_text = ('<span weight="bold" size="larger">' +
                                _('Install driver') + '</span>\n\n' +
                                _("Printer '%s' requires the %s package but "
                                  "it is not currently installed.")
                                % (name, pkg))
                dialog = self.InstallDialog
                self.lblInstall.set_markup(install_text)
                dialog.set_transient_for (parent)
                response = dialog.run ()
                dialog.hide ()
                if response == Gtk.ResponseType.OK:
                    # Install the package.
                    try:
                        pk.InstallPackageName (0, 0, pkg)
                    except:
                        pass # should handle error
            else:
                show_error_dialog (_('Missing driver'),
                                   _("Printer '%s' requires the '%s' program "
                                     "but it is not currently installed.  "
                                     "Please install it before using this "
                                     "printer.") %
                                   (name,
                                    (exes + pkgs)[0]),
                                   parent)

    def on_printer_modified (self, obj, name, ppd_has_changed):
        debugprint ("Printer modified by user: %s" % name)
        # Load information about the printer,
        # e.g. self.propertiesDlg.server_side_options and self.propertiesDlg.ppd
        # (both used below).
        self.propertiesDlg.load (name)

        if self.propertiesDlg.ppd:
            try:
                self.checkDriverExists (self.propertiesDlg.dialog,
                                        name, ppd=self.propertiesDlg.ppd)
            except:
                nonfatalException()

            # Also check to see whether the media option has become
            # invalid.  This can happen if it had previously been
            # explicitly set to a page size that is not offered with
            # the new PPD (see bug #441836).
            try:
                option = self.propertiesDlg.server_side_options['media']
                if option.get_current_value () is None:
                    debugprint ("Invalid media option: resetting")
                    option.reset ()
                    self.propertiesDlg.changed.add (option)
                    self.propertiesDlg.save_printer (self.printer)
            except KeyError:
                pass
            except:
                nonfatalException()

    def defer_refresh (self):
        def deferred_refresh ():
            self.populateList_timer = None
            Gdk.threads_enter ()
            try:
                self.populateList (prompt_allowed=False)
            finally:
                Gdk.threads_leave ()
            return False

        if self.populateList_timer:
            GLib.source_remove (self.populateList_timer)

        self.populateList_timer = GLib.timeout_add (200, deferred_refresh)
        debugprint ("Deferred populateList by 200ms")

        ## Monitor signal helpers
    def printer_added_or_removed (self):
        # Just fetch the list of printers again.  This is too simplistic.
        self.defer_refresh ()

    ## Monitor signal handlers
    def printer_added (self, mon, printer):
        self.printer_added_or_removed ()

    def printer_event (self, mon, printer, eventname, event):
        if printer in self.printers:
            self.printers[printer].update (**event)
            self.dests_iconview_selection_changed (self.dests_iconview)
            self.printer_added_or_removed ()

    def printer_removed (self, mon, printer):
        self.printer_added_or_removed ()

    def cups_connection_error (self, mon):
        self.cups = None
        self.setConnected ()
        self.populateList (prompt_allowed=False)

    def cups_connection_recovered (self, mon):
        debugprint ("Trying to recover connection")
        GLib.idle_add (self.service_started_try)

def main(show_jobs):
    cups.setUser (os.environ.get ("CUPS_USER", cups.getUser()))
    Gdk.threads_init ()
    from dbus.glib import DBusGMainLoop
    DBusGMainLoop (set_as_default=True)

    if show_jobs:
        viewer = jobviewer.JobViewer (None, None, my_jobs=False,
                                      specific_dests=[show_jobs])
        viewer.connect ('finished', Gtk.main_quit)
    else:
        mainwindow = GUI()

    Gdk.threads_enter ()
    try:
        Gtk.main()
    finally:
        Gdk.threads_leave ()

if __name__ == "__main__":
    import getopt
    try:
        opts, args = getopt.gnu_getopt (sys.argv[1:], '',
                                        ['embedded=',
                                            'debug', 'show-jobs='])
    except getopt.GetoptError:
        show_help ()
        sys.exit (1)

    show_jobs = False

    for opt, optarg in opts:
        if opt == '--debug':
            set_debugging (True)
            cupshelpers.set_debugprint_fn (debugprint)
        elif opt == '--show-jobs':
            show_jobs = optarg

        if opt == "--embedded":
            PlugWindowId = int(optarg)

    main(show_jobs)

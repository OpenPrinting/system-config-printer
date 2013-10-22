
## Copyright (C) 2007, 2008, 2009, 2010, 2011, 2012, 2013 Red Hat, Inc.
## Authors:
##  Tim Waugh <twaugh@redhat.com>
##  Jiri Popelka <jpopelka@redhat.com>

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

import asyncconn
import authconn
import cups
import dbus
import dbus.glib
import dbus.service
from gi.repository import Notify
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import Gtk
from gui import GtkGUI
import monitor
import os, shutil
from gi.repository import Pango
import pwd
import smburi
import subprocess
import sys
import time
import urllib
from xml.sax import saxutils

from debug import *
import config
import statereason
import errordialogs

cups.require("1.9.47")

try:
    from gi.repository import GnomeKeyring
    USE_KEYRING=True
except ImportError:
    USE_KEYRING=False

import gettext
gettext.install(domain=config.PACKAGE, localedir=config.localedir, unicode=True)

from statereason import StateReason

pkgdata = config.pkgdatadir
ICON="printer"
ICON_SIZE=22
SEARCHING_ICON="document-print-preview"

# We need to call Notify.init before we can check the server for caps
Notify.init('System Config Printer Notification')

class PrinterURIIndex:
    def __init__ (self, names=[]):
        self.printer = {}
        self.names = names
        self._collect_names ()

    def _collect_names (self, connection=None):
        if not self.names:
            return

        if not connection:
            try:
                c = cups.Connection ()
            except RuntimeError:
                return

        for name in self.names:
            self.add_printer (name, connection=c)

        self.names = []

    def add_printer (self, printer, connection=None):
        try:
            self._map_printer (name=printer, connection=connection)
        except KeyError:
            return

    def update_from_attrs (self, printer, attrs):
        uris = []
        if attrs.has_key ('printer-uri-supported'):
            uri_supported = attrs['printer-uri-supported']
            if type (uri_supported) != list:
                uri_supported = [uri_supported]
            uris.extend (uri_supported)
        if attrs.has_key ('notify-printer-uri'):
            uris.append (attrs['notify-printer-uri'])
        if attrs.has_key ('printer-more-info'):
            uris.append (attrs['printer-more-info'])

        for uri in uris:
            self.printer[uri] = printer

    def remove_printer (self, printer):
        # Remove references to this printer in the URI map.
        self._collect_names ()
        uris = self.printer.keys ()
        for uri in uris:
            if self.printer[uri] == printer:
                del self.printer[uri]

    def lookup (self, uri, connection=None):
        self._collect_names ()
        try:
            return self.printer[uri]
        except KeyError:
            return self._map_printer (uri=uri, connection=connection)

    def all_printer_names (self):
        self._collect_names ()
        return set (self.printer.values ())

    def lookup_cached_by_name (self, name):
        self._collect_names ()
        for uri, printer in self.printer.iteritems ():
            if printer == name:
                return uri

        raise KeyError

    def _map_printer (self, uri=None, name=None, connection=None):
        try:
            if connection == None:
                connection = cups.Connection ()
            if isinstance(name, bytes):
                name = name.decode ('utf-8')

            r = ['printer-name', 'printer-uri-supported', 'printer-more-info']
            if uri != None:
                attrs = connection.getPrinterAttributes (uri=uri,
                                                         requested_attributes=r)
            else:
                attrs = connection.getPrinterAttributes (name,
                                                         requested_attributes=r)
        except RuntimeError:
            # cups.Connection() failed
            raise KeyError
        except cups.IPPError:
            # URI not known.
            raise KeyError

        name = attrs['printer-name']
        self.update_from_attrs (name, attrs)
        if uri != None:
            self.printer[uri] = name
        return name


class CancelJobsOperation(GObject.GObject):
    __gsignals__ = {
        'destroy':     (GObject.SIGNAL_RUN_LAST, None, ()),
        'job-deleted': (GObject.SIGNAL_RUN_LAST, None, (int,)),
        'ipp-error':   (GObject.SIGNAL_RUN_LAST, None,
                        (int, GObject.TYPE_PYOBJECT)),
        'finished':    (GObject.SIGNAL_RUN_LAST, None, ())
        }

    def __init__ (self, parent, host, port, encryption, jobids, purge_job):
        GObject.GObject.__init__ (self)
        self.jobids = list (jobids)
        self.purge_job = purge_job
        self.host = host
        self.port = port
        self.encryption = encryption
        if purge_job:
            if len(self.jobids) > 1:
                dialog_title = _("Delete Jobs")
                dialog_label = _("Do you really want to delete these jobs?")
            else:
                dialog_title = _("Delete Job")
                dialog_label = _("Do you really want to delete this job?")
        else:
            if len(self.jobids) > 1:
                dialog_title = _("Cancel Jobs")
                dialog_label = _("Do you really want to cancel these jobs?")
            else:
                dialog_title = _("Cancel Job")
                dialog_label = _("Do you really want to cancel this job?")

        dialog = Gtk.Dialog (dialog_title, parent,
                             Gtk.DialogFlags.MODAL |
                             Gtk.DialogFlags.DESTROY_WITH_PARENT,
                             (_("Keep Printing"), Gtk.ResponseType.NO,
                              dialog_title, Gtk.ResponseType.YES))
        dialog.set_default_response (Gtk.ResponseType.NO)
        dialog.set_border_width (6)
        dialog.set_resizable (False)
        hbox = Gtk.HBox.new (False, 12)
        image = Gtk.Image ()
        image.set_from_stock (Gtk.STOCK_DIALOG_QUESTION, Gtk.IconSize.DIALOG)
        image.set_alignment (0.0, 0.0)
        hbox.pack_start (image, False, False, 0)
        label = Gtk.Label(label=dialog_label)
        label.set_line_wrap (True)
        label.set_alignment (0.0, 0.0)
        hbox.pack_start (label, False, False, 0)
        dialog.vbox.pack_start (hbox, False, False, 0)
        dialog.connect ("response", self.on_job_cancel_prompt_response)
        dialog.connect ("delete-event", self.on_job_cancel_prompt_delete)
        dialog.show_all ()
        self.dialog = dialog
        self.connection = None
        debugprint ("+%s" % self)

    def __del__ (self):
        debugprint ("-%s" % self)

    def do_destroy (self):
        if self.connection:
            self.connection.destroy ()
            self.connection = None

        if self.dialog:
            self.dialog.destroy ()
            self.dialog = None

        debugprint ("DESTROY: %s" % self)

    def destroy (self):
        self.emit ('destroy')

    def on_job_cancel_prompt_delete (self, dialog, event):
        self.on_job_cancel_prompt_response (dialog, Gtk.ResponseType.NO)

    def on_job_cancel_prompt_response (self, dialog, response):
        dialog.destroy ()
        self.dialog = None

        if response != Gtk.ResponseType.YES:
            self.emit ('finished')
            return

        if len(self.jobids) == 0:
            self.emit ('finished')
            return

        asyncconn.Connection (host=self.host,
                              port=self.port,
                              encryption=self.encryption,
                              reply_handler=self._connected,
                              error_handler=self._connect_failed)

    def _connect_failed (self, connection, exc):
        debugprint ("CancelJobsOperation._connect_failed %s:%s" % (connection, repr (exc)))

    def _connected (self, connection, result):
        self.connection = connection

        if self.purge_job:
            operation = _("deleting job")
        else:
            operation = _("canceling job")

        self.connection._begin_operation (operation)
        self.connection.cancelJob (self.jobids[0], self.purge_job,
                                   reply_handler=self.cancelJob_finish,
                                   error_handler=self.cancelJob_error)

    def cancelJob_error (self, connection, exc):
        debugprint ("cancelJob_error %s:%s" % (connection, repr (exc)))
        if type (exc) == cups.IPPError:
            (e, m) = exc.args
            if (e != cups.IPP_NOT_POSSIBLE and
                e != cups.IPP_NOT_FOUND):
                self.emit ('ipp-error', self.jobids[0], exc)
            self.cancelJob_finish(connection, None)
        else:
            self.connection._end_operation ()
            self.connection.destroy ()
            self.connection = None
            self.emit ('ipp-error', self.jobids[0], exc)
            # Give up.
            self.emit ('finished')
            return

    def cancelJob_finish (self, connection, result):
        debugprint ("cancelJob_finish %s:%s" % (connection, repr (result)))
        self.emit ('job-deleted', self.jobids[0])
        del self.jobids[0]
        if not self.jobids:
            # Last job canceled.
            self.connection._end_operation ()
            self.connection.destroy ()
            self.connection = None
            self.emit ('finished')
            return
        else:
            # there are other jobs to cancel/delete
            connection.cancelJob (self.jobids[0], self.purge_job,
                                  reply_handler=self.cancelJob_finish,
                                  error_handler=self.cancelJob_error)

class JobViewer (GtkGUI):
    required_job_attributes = set(['job-k-octets',
                                   'job-name',
                                   'job-originating-user-name',
                                   'job-printer-uri',
                                   'job-state',
                                   'time-at-creation',
                                   'job-preserved'])

    __gsignals__ = {
        'finished':    (GObject.SIGNAL_RUN_LAST, None, ())
        }

    def __init__(self, bus=None, loop=None,
                 applet=False, suppress_icon_hide=False,
                 my_jobs=True, specific_dests=None,
                 parent=None):
        GObject.GObject.__init__ (self)
        self.loop = loop
        self.applet = applet
        self.suppress_icon_hide = suppress_icon_hide
        self.my_jobs = my_jobs
        self.specific_dests = specific_dests
        notify_caps = Notify.get_server_caps ()
        self.notify_has_actions = "actions" in notify_caps
        self.notify_has_persistence = "persistence" in notify_caps

        self.jobs = {}
        self.jobiters = {}
        self.jobids = []
        self.jobs_attrs = {} # dict of jobid->(GtkListStore, page_index)
        self.active_jobs = set() # of job IDs
        self.stopped_job_prompts = set() # of job IDs
        self.printer_state_reasons = {}
        self.num_jobs_when_hidden = 0
        self.connecting_to_device = {} # dict of printer->time first seen
        self.state_reason_notifications = {}
        self.auth_info_dialogs = {} # by job ID
        self.job_creation_times_timer = None
        self.new_printer_notifications = {}
        self.completed_job_notifications = {}
        self.authenticated_jobs = set() # of job IDs
        self.ops = []

        self.getWidgets ({"JobsWindow":
                              ["JobsWindow",
                               "treeview",
                               "statusbar",
                               "toolbar"],
                          "statusicon_popupmenu":
                              ["statusicon_popupmenu"]},

                         domain=config.PACKAGE)

        job_action_group = Gtk.ActionGroup ("JobActionGroup")
        job_action_group.add_actions ([
                ("cancel-job", Gtk.STOCK_CANCEL, _("_Cancel"), None,
                 _("Cancel selected jobs"), self.on_job_cancel_activate),
                ("delete-job", Gtk.STOCK_DELETE, _("_Delete"), None,
                 _("Delete selected jobs"), self.on_job_delete_activate),
                ("hold-job", Gtk.STOCK_MEDIA_PAUSE, _("_Hold"), None,
                 _("Hold selected jobs"), self.on_job_hold_activate),
                ("release-job", Gtk.STOCK_MEDIA_PLAY, _("_Release"), None,
                 _("Release selected jobs"), self.on_job_release_activate),
                ("reprint-job", Gtk.STOCK_REDO, _("Re_print"), None,
                 _("Reprint selected jobs"), self.on_job_reprint_activate),
                ("retrieve-job", Gtk.STOCK_SAVE_AS, _("Re_trieve"), None,
                 _("Retrieve selected jobs"), self.on_job_retrieve_activate),
                ("move-job", None, _("_Move To"), None, None, None),
                ("authenticate-job", None, _("_Authenticate"), None, None,
                 self.on_job_authenticate_activate),
                ("job-attributes", None, _("_View Attributes"), None, None,
                 self.on_job_attributes_activate),
                ("close", Gtk.STOCK_CLOSE, None, "<ctrl>w",
                 _("Close this window"), self.on_delete_event)
                ])
        self.job_ui_manager = Gtk.UIManager ()
        self.job_ui_manager.insert_action_group (job_action_group, -1)
        self.job_ui_manager.add_ui_from_string (
"""
<ui>
 <accelerator action="cancel-job"/>
 <accelerator action="delete-job"/>
 <accelerator action="hold-job"/>
 <accelerator action="release-job"/>
 <accelerator action="reprint-job"/>
 <accelerator action="retrieve-job"/>
 <accelerator action="move-job"/>
 <accelerator action="authenticate-job"/>
 <accelerator action="job-attributes"/>
 <accelerator action="close"/>
</ui>
"""
)
        self.job_ui_manager.ensure_update ()
        self.JobsWindow.add_accel_group (self.job_ui_manager.get_accel_group ())
        self.job_context_menu = Gtk.Menu ()
        for action_name in ["cancel-job",
                            "delete-job",
                            "hold-job",
                            "release-job",
                            "reprint-job",
                            "retrieve-job",
                            "move-job",
                            None,
                            "authenticate-job",
                            "job-attributes"]:
            if not action_name:
                item = Gtk.SeparatorMenuItem ()
            else:
                action = job_action_group.get_action (action_name)
                action.set_sensitive (False)
                item = action.create_menu_item ()

                if action_name == 'move-job':
                    self.move_job_menuitem = item
                    printers = Gtk.Menu ()
                    item.set_submenu (printers)

            item.show ()
            self.job_context_menu.append (item)

        for action_name in ["cancel-job",
                            "delete-job",
                            "hold-job",
                            "release-job",
                            "reprint-job",
                            "retrieve-job",
                            "close"]:
            action = job_action_group.get_action (action_name)
            action.set_sensitive (action_name == "close")
            action.set_is_important (action_name == "close")
            item = action.create_tool_item ()
            item.show ()
            self.toolbar.insert (item, -1)

        for skip, ellipsize, name, setter in \
                [(False, False, _("Job"), self._set_job_job_number_text),
                 (True, False, _("User"), self._set_job_user_text),
                 (False, True, _("Document"), self._set_job_document_text),
                 (False, True, _("Printer"), self._set_job_printer_text),
                 (False, False, _("Size"), self._set_job_size_text)]:
            if applet and skip:
                # Skip the user column when running as applet.
                continue

            cell = Gtk.CellRendererText()
            if ellipsize:
                # Ellipsize the 'Document' and 'Printer' columns.
                cell.set_property ("ellipsize", Pango.EllipsizeMode.END)
                cell.set_property ("width-chars", 20)
            column = Gtk.TreeViewColumn(name, cell)
            column.set_cell_data_func (cell, setter, None)
            column.set_resizable(True)
            self.treeview.append_column(column)

        cell = Gtk.CellRendererText ()
        column = Gtk.TreeViewColumn (_("Time submitted"), cell, text=1)
        column.set_resizable (True)
        self.treeview.append_column (column)

        column = Gtk.TreeViewColumn (_("Status"))
        icon = Gtk.CellRendererPixbuf ()
        column.pack_start (icon, False)
        text = Gtk.CellRendererText ()
        text.set_property ("ellipsize", Pango.EllipsizeMode.END)
        text.set_property ("width-chars", 20)
        column.pack_start (text, True)
        column.set_cell_data_func (icon, self._set_job_status_icon, None)
        column.set_cell_data_func (text, self._set_job_status_text, None)
        self.treeview.append_column (column)

        self.store = Gtk.TreeStore(int, str)
        self.store.set_sort_column_id (0, Gtk.SortType.DESCENDING)
        self.treeview.set_model(self.store)
        self.treeview.set_rules_hint (True)
        self.selection = self.treeview.get_selection()
        self.selection.set_mode(Gtk.SelectionMode.MULTIPLE)
        self.selection.connect('changed', self.on_selection_changed)
        self.treeview.connect ('button_release_event',
                               self.on_treeview_button_release_event)
        self.treeview.connect ('popup-menu', self.on_treeview_popup_menu)

        self.JobsWindow.set_icon_name (ICON)
        self.JobsWindow.hide ()

        if specific_dests:
            the_dests = reduce (lambda x, y: x + ", " + y, specific_dests)

        if my_jobs:
            if specific_dests:
                title = _("my jobs on %s") % the_dests
            else:
                title = _("my jobs")
        else:
            if specific_dests:
                title = "%s" % the_dests
            else:
                title = _("all jobs")
        self.JobsWindow.set_title (_("Document Print Status (%s)") % title)

        if parent:
            self.JobsWindow.set_transient_for (parent)

        def load_icon(theme, icon):
            try:
                pixbuf = theme.load_icon (icon, ICON_SIZE, 0)
            except GObject.GError:
                debugprint ("No %s icon available" % icon)
                # Just create an empty pixbuf.
                pixbuf = GdkPixbuf.Pixbuf.new (GdkPixbuf.Colorspace.RGB,
                                         True, 8, ICON_SIZE, ICON_SIZE)
                pixbuf.fill (0)
            return pixbuf

        theme = Gtk.IconTheme.get_default ()
        self.icon_jobs = load_icon (theme, ICON)
        self.icon_jobs_processing = load_icon (theme, "printer-printing")
        self.icon_no_jobs = self.icon_jobs.copy ()
        self.icon_no_jobs.fill (0)
        self.icon_jobs.composite (self.icon_no_jobs,
                                  0, 0,
                                  self.icon_no_jobs.get_width(),
                                  self.icon_no_jobs.get_height(),
                                  0, 0,
                                  1.0, 1.0,
                                  GdkPixbuf.InterpType.BILINEAR,
                                  127)
        if self.applet and not self.notify_has_persistence:
            self.statusicon = Gtk.StatusIcon ()
            self.statusicon.set_from_pixbuf (self.icon_no_jobs)
            self.statusicon.connect ('activate', self.toggle_window_display)
            self.statusicon.connect ('popup-menu', self.on_icon_popupmenu)
            self.statusicon.set_visible (False)

        # D-Bus
        if bus == None:
            bus = dbus.SystemBus ()

        self.connect_signals ()
        self.set_process_pending (True)
        self.host = cups.getServer ()
        self.port = cups.getPort ()
        self.encryption = cups.getEncryption ()
        self.monitor = monitor.Monitor (bus=bus, my_jobs=my_jobs,
                                        host=self.host, port=self.port,
                                        encryption=self.encryption)
        self.monitor.connect ('refresh', self.on_refresh)
        self.monitor.connect ('job-added', self.job_added)
        self.monitor.connect ('job-event', self.job_event)
        self.monitor.connect ('job-removed', self.job_removed)
        self.monitor.connect ('state-reason-added', self.state_reason_added)
        self.monitor.connect ('state-reason-removed', self.state_reason_removed)
        self.monitor.connect ('still-connecting', self.still_connecting)
        self.monitor.connect ('now-connected', self.now_connected)
        self.monitor.connect ('printer-added', self.printer_added)
        self.monitor.connect ('printer-event', self.printer_event)
        self.monitor.connect ('printer-removed', self.printer_removed)
        self.monitor.refresh ()

        self.my_monitor = None
        if not my_jobs:
            self.my_monitor = monitor.Monitor(bus=bus, my_jobs=True,
                                              host=self.host, port=self.port,
                                              encryption=self.encryption)
            self.my_monitor.connect ('job-added', self.job_added)
            self.my_monitor.connect ('job-event', self.job_event)
            self.my_monitor.refresh ()

        if not self.applet:
            self.JobsWindow.show ()

        self.JobsAttributesWindow = Gtk.Window()
        self.JobsAttributesWindow.set_title (_("Job attributes"))
        self.JobsAttributesWindow.set_position(Gtk.WindowPosition.MOUSE)
        self.JobsAttributesWindow.set_default_size(600, 600)
        self.JobsAttributesWindow.set_transient_for (self.JobsWindow)
        self.JobsAttributesWindow.connect("delete_event",
                                          self.job_attributes_on_delete_event)
        self.JobsAttributesWindow.add_accel_group (self.job_ui_manager.get_accel_group ())
        attrs_action_group = Gtk.ActionGroup ("AttrsActionGroup")
        attrs_action_group.add_actions ([
                ("close", Gtk.STOCK_CLOSE, None, "<ctrl>w",
                 _("Close this window"), self.job_attributes_on_delete_event)
                ])
        self.attrs_ui_manager = Gtk.UIManager ()
        self.attrs_ui_manager.insert_action_group (attrs_action_group, -1)
        self.attrs_ui_manager.add_ui_from_string (
"""
<ui>
 <accelerator action="close"/>
</ui>
"""
)
        self.attrs_ui_manager.ensure_update ()
        self.JobsAttributesWindow.add_accel_group (self.attrs_ui_manager.get_accel_group ())
        vbox = Gtk.VBox ()
        self.JobsAttributesWindow.add (vbox)
        toolbar = Gtk.Toolbar ()
        action = self.attrs_ui_manager.get_action ("/close")
        item = action.create_tool_item ()
        item.set_is_important (True)
        toolbar.insert (item, 0)
        vbox.pack_start (toolbar, False, False, 0)
        self.notebook = Gtk.Notebook()
        vbox.pack_start (self.notebook, True, True, 0)

    def cleanup (self):
        self.monitor.cleanup ()
        if self.my_monitor:
            self.my_monitor.cleanup ()

        self.JobsWindow.hide ()

        # Close any open notifications.
        for l in [self.new_printer_notifications.values (),
                  self.state_reason_notifications.values ()]:
            for notification in l:
                if getattr (notification, 'closed', None) != True:
                    try:
                        notification.close ()
                    except GLib.GError:
                        # Can fail if the notification wasn't even shown
                        # yet (as in bug #571603).
                        pass
                    notification.closed = True

        if self.job_creation_times_timer != None:
            GLib.source_remove (self.job_creation_times_timer)
            self.job_creation_times_timer = None

        for op in self.ops:
            op.destroy ()

        if self.applet and not self.notify_has_persistence:
            self.statusicon.set_visible (False)

        self.emit ('finished')

    def set_process_pending (self, whether):
        self.process_pending_events = whether

    def on_delete_event(self, *args):
        if self.applet or not self.loop:
            self.JobsWindow.hide ()
            self.JobsWindow.visible = False
            if not self.applet:
                # Being run from main app, not applet
                self.cleanup ()
        else:
            self.loop.quit ()
        return True

    def job_attributes_on_delete_event(self, widget, event=None):
        for page in range(self.notebook.get_n_pages()):
            self.notebook.remove_page(-1)
        self.jobs_attrs = {}
        self.JobsAttributesWindow.hide()
        return True

    def show_IPP_Error(self, exception, message):
        return errordialogs.show_IPP_Error (exception, message, self.JobsWindow)

    def toggle_window_display(self, icon, force_show=False):
        visible = getattr (self.JobsWindow, 'visible', None)
        if force_show:
            visible = False

        if self.notify_has_persistence:
            if visible:
                self.JobsWindow.hide ()
            else:
                self.JobsWindow.show ()
        else:
            if visible:
                w = self.JobsWindow.get_window()
                aw = self.JobsAttributesWindow.get_window()
                (loc, s, area, o) = self.statusicon.get_geometry ()

                if loc:
                    w.set_skip_taskbar_hint (True)
                    if aw != None:
                        aw.set_skip_taskbar_hint (True)
                    self.JobsWindow.iconify ()
                else:
                    self.JobsWindow.set_visible (False)
            else:
                self.JobsWindow.present ()
                self.JobsWindow.set_skip_taskbar_hint (False)
                aw = self.JobsAttributesWindow.get_window()
                if aw != None:
                    aw.set_skip_taskbar_hint (False)

        self.JobsWindow.visible = not visible

    def on_show_completed_jobs_clicked(self, toggletoolbutton):
        if toggletoolbutton.get_active():
            which_jobs = "all"
        else:
            which_jobs = "not-completed"
        self.monitor.refresh(which_jobs=which_jobs, refresh_all=False)
        if self.my_monitor:
            self.my_monitor.refresh(which_jobs=which_jobs, refresh_all=False)

    def update_job_creation_times(self):
        now = time.time ()
        need_update = False
        for job, data in self.jobs.iteritems():
            t = _("Unknown")
            if data.has_key ('time-at-creation'):
                created = data['time-at-creation']
                ago = now - created
                need_update = True
                if ago < 2 * 60:
                    t = _("a minute ago")
                elif ago < 60 * 60:
                    mins = int (ago / 60)
                    t = _("%d minutes ago") % mins
                elif ago < 24 * 60 * 60:
                    hours = int (ago / (60 * 60))
                    if hours == 1:
                        t = _("an hour ago")
                    else:
                        t = _("%d hours ago") % hours
                elif ago < 7 * 24 * 60 * 60:
                    days = int (ago / (24 * 60 * 60))
                    if days == 1:
                        t = _("yesterday")
                    else:
                        t = _("%d days ago") % days
                elif ago < 6 * 7 * 24 * 60 * 60:
                    weeks = int (ago / (7 * 24 * 60 * 60))
                    if weeks == 1:
                        t = _("last week")
                    else:
                        t = _("%d weeks ago") % weeks
                else:
                    need_update = False
                    t = time.strftime ("%B %Y", time.localtime (created))

            if self.jobiters.has_key (job):
                iter = self.jobiters[job]
                self.store.set_value (iter, 1, t)

        if need_update and not self.job_creation_times_timer:
            def update_times_with_locking ():
                Gdk.threads_enter ()
                ret = self.update_job_creation_times ()
                Gdk.threads_leave ()
                return ret

            t = GLib.timeout_add_seconds (60, update_times_with_locking)
            self.job_creation_times_timer = t

        if not need_update:
            if self.job_creation_times_timer:
                GLib.source_remove (self.job_creation_times_timer)
                self.job_creation_times_timer = None

        # Return code controls whether the timeout will recur.
        return need_update

    def print_error_dialog_response(self, dialog, response, jobid):
        dialog.hide ()
        dialog.destroy ()
        self.stopped_job_prompts.remove (jobid)
        if response == Gtk.ResponseType.NO:
            # Diagnose
            if not self.__dict__.has_key ('troubleshooter'):
                import troubleshoot
                troubleshooter = troubleshoot.run (self.on_troubleshoot_quit)
                self.troubleshooter = troubleshooter

    def on_troubleshoot_quit(self, troubleshooter):
        del self.troubleshooter

    def add_job (self, job, data, connection=None):
        self.update_job (job, data, connection=connection)

        # There may have been an error fetching additional attributes,
        # in which case we need to give up.
        if not self.jobs.has_key (job):
            return

        store = self.store
        iter = self.store.append (None)
        store.set_value (iter, 0, job)
        debugprint ("Job %d added" % job)
        self.jobiters[job] = iter

        range = self.treeview.get_visible_range ()
        if range != None:
            (start, end) = range
            if (self.store.get_sort_column_id () == (0,
                                                     Gtk.SortType.DESCENDING) and
                start == Gtk.TreePath(1)):
                # This job was added job above the visible range, and
                # we are sorting by descending job ID.  Scroll to it.
                self.treeview.scroll_to_cell (Gtk.TreePath(), None,
                                              False, 0.0, 0.0)

        if not self.job_creation_times_timer:
            def start_updating_job_creation_times():
                Gdk.threads_enter ()
                self.update_job_creation_times ()
                Gdk.threads_leave ()
                return False

            GLib.timeout_add (500, start_updating_job_creation_times)

    def update_monitor (self):
        self.monitor.update ()
        if self.my_monitor:
            self.my_monitor.update ()

    def update_job (self, job, data, connection=None):
        # Fetch required attributes for this job if they are missing.
        r = self.required_job_attributes - set (data.keys ())

        # If we are showing attributes of this job at this moment, update them.
        if job in self.jobs_attrs:
            self.update_job_attributes_viewer(job)

        if r:
            attrs = None
            try:
                if connection == None:
                    connection = cups.Connection (host=self.host,
                                                  port=self.port,
                                                  encryption=self.encryption)

                debugprint ("requesting %s" % r)
                r = list (r)
                attrs = connection.getJobAttributes (job,
                                                     requested_attributes=r)
            except RuntimeError:
                pass
            except AttributeError:
                pass
            except cups.IPPError:
                # someone else may have purged the job
                return

            if attrs:
                data.update (attrs)

        self.jobs[job] = data

        job_requires_auth = False
        try:
            jstate = data.get ('job-state', cups.IPP_JOB_PROCESSING)
            s = int (jstate)

            if s in [cups.IPP_JOB_HELD, cups.IPP_JOB_STOPPED]:
                jattrs = ['job-state', 'job-hold-until']
                pattrs = ['auth-info-required', 'device-uri']
                uri = data.get ('job-printer-uri')
                c = authconn.Connection (self.JobsWindow,
                                         host=self.host,
                                         port=self.port,
                                         encryption=self.encryption)
                attrs = c.getPrinterAttributes (uri = uri,
                                                requested_attributes=pattrs)

                try:
                    auth_info_required = attrs['auth-info-required']
                except KeyError:
                    debugprint ("No auth-info-required attribute; "
                                "guessing instead")
                    auth_info_required = ['username', 'password']

                if not isinstance (auth_info_required, list):
                    auth_info_required = [auth_info_required]
                    attrs['auth-info-required'] = auth_info_required

                data.update (attrs)

                attrs = c.getJobAttributes (job,
                                            requested_attributes=jattrs)
                data.update (attrs)
                jstate = data.get ('job-state', cups.IPP_JOB_PROCESSING)
                s = int (jstate)
        except ValueError:
            pass
        except RuntimeError:
            pass
        except cups.IPPError:
            pass

        # Invalidate the cached status description and redraw the treeview.
        try:
            del data['_status_text']
        except KeyError:
            pass
        self.treeview.queue_draw ()

        # Check whether authentication is required.
        if self.applet:
            job_requires_auth = (s == cups.IPP_JOB_HELD and
                                 data.get ('job-hold-until', 'none') ==
                                 'auth-info-required')

            if (job_requires_auth and
                not self.auth_info_dialogs.has_key (job)):
                try:
                    cups.require ("1.9.37")
                except:
                    debugprint ("Authentication required but "
                                "authenticateJob() not available")
                    return

                # Find out which auth-info is required.
                try_keyring = USE_KEYRING
                keyring_attrs = dict()
                auth_info = None
                if try_keyring and 'password' in auth_info_required:
                    auth_info_required = data.get ('auth-info-required', [])
                    device_uri = data.get ("device-uri")
                    (scheme, rest) = urllib.splittype (device_uri)
                    if scheme == 'smb':
                        uri = smburi.SMBURI (uri=device_uri)
                        (group, server, share,
                         user, password) = uri.separate ()
                        keyring_attrs["domain"] = str (group)
                    else:
                        (serverport, rest) = urllib.splithost (rest)
                        if serverport == None:
                            server = None
                        else:
                            (server, port) = urllib.splitnport (serverport)

                    if scheme == None or server == None:
                        try_keyring = False
                    else:
                        keyring_attrs.update ({ "server": str (server.lower ()),
                                                "protocol": str (scheme)})

                if job in self.authenticated_jobs:
                    # We've already tried to authenticate this job before.
                    try_keyring = False

                if try_keyring and 'password' in auth_info_required:
                    type = GnomeKeyring.ItemType.NETWORK_PASSWORD
                    attrs = GnomeKeyring.Attribute.list_new ()
                    for key, val in keyring_attrs.iteritems ():
                        GnomeKeyring.Attribute.list_append_string (attrs,
                                                                   key,
                                                                   val)
                    (result, items) = GnomeKeyring.find_items_sync (type,
                                                                    attrs)
                    if result == GnomeKeyring.Result.OK:
                        auth_info = map (lambda x: '', auth_info_required)
                        ind = auth_info_required.index ('username')

                        for attr in GnomeKeyring.attribute_list_to_glist (
                                items[0].attributes):
                            # It might be safe to assume here that the
                            # user element is always the second item in a
                            # NETWORK_PASSWORD element but lets make sure.
                            if attr.name == 'user':
                                auth_info[ind] = attr.get_string()
                                break
                        else:
                            debugprint ("Did not find username keyring "
                                        "attributes.")

                        ind = auth_info_required.index ('password')
                        auth_info[ind] = items[0].secret
                    else:
                        debugprint ("gnomekeyring: look-up result %s" %
                                    repr (result))

                if try_keyring and c == None:
                    try:
                        c = authconn.Connection (self.JobsWindow,
                                                 host=self.host,
                                                 port=self.port,
                                                 encryption=self.encryption)
                    except RuntimeError:
                        try_keyring = False

                if try_keyring and auth_info != None:
                    try:
                        c._begin_operation (_("authenticating job"))
                        c.authenticateJob (job, auth_info)
                        c._end_operation ()
                        self.update_monitor ()
                        debugprint ("Automatically authenticated job %d" % job)
                        self.authenticated_jobs.add (job)
                        return
                    except cups.IPPError:
                        c._end_operation ()
                        nonfatalException ()
                        return
                    except:
                        c._end_operation ()
                        nonfatalException ()

                if data.has_key ('auth-info-required'):
                    username = pwd.getpwuid (os.getuid ())[0]
                    keyring_attrs["user"] = str (username)
                    self.display_auth_info_dialog (job, keyring_attrs)
        self.update_sensitivity ()

    def display_auth_info_dialog (self, job, keyring_attrs=None):
        data = self.jobs[job]
        auth_info_required = data['auth-info-required']
        dialog = authconn.AuthDialog (auth_info_required=auth_info_required,
                                      allow_remember=USE_KEYRING)
        dialog.keyring_attrs = keyring_attrs
        dialog.auth_info_required = auth_info_required
        dialog.set_position (Gtk.WindowPosition.CENTER)

        # Pre-fill 'username' field.
        auth_info = map (lambda x: '', auth_info_required)
        username = pwd.getpwuid (os.getuid ())[0]
        if 'username' in auth_info_required:
            try:
                ind = auth_info_required.index ('username')
                auth_info[ind] = username
                dialog.set_auth_info (auth_info)
            except:
                nonfatalException ()

        # Focus on the first empty field.
        index = 0
        for field in auth_info_required:
            if auth_info[index] == '':
                dialog.field_grab_focus (field)
                break
            index += 1

        dialog.set_prompt (_("Authentication required for "
                             "printing document `%s' (job %d)") %
                           (data.get('job-name', _("Unknown")),
                            job))
        self.auth_info_dialogs[job] = dialog
        dialog.connect ('response', self.auth_info_dialog_response)
        dialog.connect ('delete-event', self.auth_info_dialog_delete)
        dialog.job_id = job
        dialog.show_all ()
        dialog.set_keep_above (True)
        dialog.show_now ()

    def auth_info_dialog_delete (self, dialog, event):
        self.auth_info_dialog_response (dialog, Gtk.ResponseType.CANCEL)

    def auth_info_dialog_response (self, dialog, response):
        jobid = dialog.job_id
        del self.auth_info_dialogs[jobid]

        if response != Gtk.ResponseType.OK:
            dialog.destroy ()
            return

        auth_info = dialog.get_auth_info ()
        try:
            c = authconn.Connection (self.JobsWindow,
                                     host=self.host,
                                     port=self.port,
                                     encryption=self.encryption)
        except RuntimeError:
            debugprint ("Error connecting to CUPS for authentication")
            return

        remember = False
        c._begin_operation (_("authenticating job"))
        try:
            c.authenticateJob (jobid, auth_info)
            remember = dialog.get_remember_password ()
            self.authenticated_jobs.add (jobid)
            self.update_monitor ()
        except cups.IPPError as e:
            (e, m) = e.args
            self.show_IPP_Error (e, m)

        c._end_operation ()

        if remember:
            try:
                (result, keyring) = GnomeKeyring.get_default_keyring_sync ()
                type = GnomeKeyring.ItemType.NETWORK_PASSWORD
                keyring_attrs = getattr (dialog,
                                         "keyring_attrs",
                                         None)
                auth_info_required = getattr (dialog,
                                              "auth_info_required",
                                              None)
                if keyring_attrs != None and auth_info_required != None:
                    try:
                        ind = auth_info_required.index ('username')
                        keyring_attrs['user'] = auth_info[ind]
                    except IndexError:
                        pass

                    name = "%s@%s (%s)" % (keyring_attrs.get ("user"),
                                           keyring_attrs.get ("server"),
                                           keyring_attrs.get ("protocol"))
                    ind = auth_info_required.index ('password')
                    secret = auth_info[ind]
                    attrs = GnomeKeyring.Attribute.list_new ()
                    for key, val in keyring_attrs.iteritems ():
                        GnomeKeyring.Attribute.list_append_string (attrs,
                                                                   key,
                                                                   val)
                    (result, id) = GnomeKeyring.item_create_sync (keyring,
                                                                  type,
                                                                  name,
                                                                  attrs,
                                                                  secret,
                                                                  True)
                    debugprint ("keyring: created id %d for %s" % (id, name))
            except:
                nonfatalException ()

        dialog.destroy ()

    def set_statusicon_visibility (self):
        if not self.applet:
            return

        if self.suppress_icon_hide:
            # Avoid hiding the icon if we've been woken up to notify
            # about a new printer.
            self.suppress_icon_hide = False
            return

        open_notifications = len (self.new_printer_notifications.keys ())
        open_notifications += len (self.completed_job_notifications.keys ())
        for reason, notification in self.state_reason_notifications.iteritems():
            if getattr (notification, 'closed', None) != True:
                open_notifications += 1
        num_jobs = len (self.active_jobs)

        debugprint ("open notifications: %d" % open_notifications)
        debugprint ("num_jobs: %d" % num_jobs)
        debugprint ("num_jobs_when_hidden: %d" % self.num_jobs_when_hidden)

        if self.notify_has_persistence:
            return

        # Don't handle tooltips during the mainloop recursion at the
        # end of this function as it seems to cause havoc (bug #664044,
        # bug #739745).
        self.statusicon.set_has_tooltip (False)

        self.statusicon.set_visible (open_notifications > 0 or
                                     num_jobs > self.num_jobs_when_hidden)

        # Let the icon show/hide itself before continuing.
        while self.process_pending_events and Gtk.events_pending ():
            Gtk.main_iteration ()

    def on_treeview_popup_menu (self, treeview):
        event = Gdk.Event (Gdk.NOTHING)
        self.show_treeview_popup_menu (treeview, event, 0)

    def on_treeview_button_release_event(self, treeview, event):
        if event.button == 3:
            self.show_treeview_popup_menu (treeview, event, event.button)

    def update_sensitivity (self, selection = None):
        if (selection is None):
            selection = self.treeview.get_selection () 
        (model, pathlist) = selection.get_selected_rows()
        cancel = self.job_ui_manager.get_action ("/cancel-job")
        delete = self.job_ui_manager.get_action ("/delete-job")
        hold = self.job_ui_manager.get_action ("/hold-job")
        release = self.job_ui_manager.get_action ("/release-job")
        reprint = self.job_ui_manager.get_action ("/reprint-job")
        retrieve = self.job_ui_manager.get_action ("/retrieve-job")
        authenticate = self.job_ui_manager.get_action ("/authenticate-job")
        attributes = self.job_ui_manager.get_action ("/job-attributes")
        move = self.job_ui_manager.get_action ("/move-job")
        if len (pathlist) == 0:
            for widget in [cancel, delete, hold, release, reprint, retrieve,
                           move, authenticate, attributes]:
                widget.set_sensitive (False)
            return

        cancel_sensitive = True
        hold_sensitive = True
        release_sensitive = True
        reprint_sensitive = True
        authenticate_sensitive = True
        move_sensitive = False
        other_printers = self.printer_uri_index.all_printer_names ()
        job_printers = dict()

        self.jobids = []
        for path in pathlist:
            iter = self.store.get_iter (path)
            jobid = self.store.get_value (iter, 0)
            self.jobids.append(jobid)
            job = self.jobs[jobid]

            if job.has_key ('job-state'):
                s = job['job-state']
                if s >= cups.IPP_JOB_CANCELED:
                    cancel_sensitive = False
                if s != cups.IPP_JOB_PENDING:
                    hold_sensitive = False
                if s != cups.IPP_JOB_HELD:
                    release_sensitive = False
                if (not job.get('job-preserved', False)):
                    reprint_sensitive = False

            if (job.get ('job-state',
                         cups.IPP_JOB_CANCELED) != cups.IPP_JOB_HELD or
                job.get ('job-hold-until', 'none') != 'auth-info-required'):
                authenticate_sensitive = False

            uri = job.get ('job-printer-uri', None)
            if uri:
                try:
                    printer = self.printer_uri_index.lookup (uri)
                except KeyError:
                    printer = uri
                job_printers[printer] = uri

        if len (job_printers.keys ()) == 1:
            try:
                other_printers.remove (job_printers.keys ()[0])
            except KeyError:
                pass

        if len (other_printers) > 0:
            printers_menu = Gtk.Menu ()
            other_printers = list (other_printers)
            other_printers.sort ()
            for printer in other_printers:
                try:
                    uri = self.printer_uri_index.lookup_cached_by_name (printer)
                except KeyError:
                    uri = None
                menuitem = Gtk.MenuItem (label=printer)
                menuitem.set_sensitive (uri != None)
                menuitem.show ()
                menuitem.connect ('activate', self.on_job_move_activate, uri)
                printers_menu.append (menuitem)

            self.move_job_menuitem.set_submenu (printers_menu)
            move_sensitive = True

        cancel.set_sensitive(cancel_sensitive)
        delete.set_sensitive(not cancel_sensitive)
        hold.set_sensitive(hold_sensitive)
        release.set_sensitive(release_sensitive)
        reprint.set_sensitive(reprint_sensitive)
        retrieve.set_sensitive(reprint_sensitive)
        move.set_sensitive (move_sensitive)
        authenticate.set_sensitive(authenticate_sensitive)
        attributes.set_sensitive(True)

    def on_selection_changed (self, selection):
        self.update_sensitivity (selection)

    def show_treeview_popup_menu (self, treeview, event, event_button):
        # Right-clicked.
        self.job_context_menu.popup (None, None, None, None, event_button,
                                     event.get_time ())

    def on_icon_popupmenu(self, icon, button, time):
        self.statusicon_popupmenu.popup (None, None, None, None, button, time)

    def on_icon_hide_activate(self, menuitem):
        self.num_jobs_when_hidden = len (self.jobs.keys ())
        self.set_statusicon_visibility ()

    def on_icon_configure_printers_activate(self, menuitem):
        env = {}
        for name, value in os.environ.iteritems ():
            if name == "SYSTEM_CONFIG_PRINTER_UI":
                continue
            env[name] = value
        p = subprocess.Popen ([ "system-config-printer" ],
                              close_fds=True, env=env)
        GLib.timeout_add_seconds (10, self.poll_subprocess, p)

    def poll_subprocess(self, process):
        returncode = process.poll ()
        return returncode == None

    def on_icon_quit_activate (self, menuitem):
        self.cleanup ()
        if self.loop:
            self.loop.quit ()

    def on_job_cancel_activate(self, menuitem):
        self.on_job_cancel_activate2(False)

    def on_job_delete_activate(self, menuitem):
        self.on_job_cancel_activate2(True)

    def on_job_cancel_activate2(self, purge_job):
        if self.jobids:
            op = CancelJobsOperation (self.JobsWindow, self.host, self.port,
                                      self.encryption, self.jobids, purge_job)
            self.ops.append (op)
            op.connect ('finished', self.on_canceljobs_finished)
            op.connect ('ipp-error', self.on_canceljobs_error)

    def on_canceljobs_finished (self, canceljobsoperation):
        canceljobsoperation.destroy ()
        i = self.ops.index (canceljobsoperation)
        del self.ops[i]
        self.update_monitor ()

    def on_canceljobs_error (self, canceljobsoperation, jobid, exc):
        self.update_monitor ()
        if type (exc) == cups.IPPError:
            (e, m) = exc.args
            if (e != cups.IPP_NOT_POSSIBLE and
                e != cups.IPP_NOT_FOUND):
                self.show_IPP_Error (e, m)

            return

        raise exc

    def on_job_hold_activate(self, menuitem):
        try:
            c = authconn.Connection (self.JobsWindow,
                                     host=self.host,
                                     port=self.port,
                                     encryption=self.encryption)
        except RuntimeError:
            return

        for jobid in self.jobids:
            c._begin_operation (_("holding job"))
            try:
                c.setJobHoldUntil (jobid, "indefinite")
            except cups.IPPError as e:
                (e, m) = e.args
                if (e != cups.IPP_NOT_POSSIBLE and
                    e != cups.IPP_NOT_FOUND):
                    self.show_IPP_Error (e, m)
                self.update_monitor ()
                c._end_operation ()
                return
            c._end_operation ()

        del c
        self.update_monitor ()

    def on_job_release_activate(self, menuitem):
        try:
            c = authconn.Connection (self.JobsWindow,
                                     host=self.host,
                                     port=self.port,
                                     encryption=self.encryption)
        except RuntimeError:
            return

        for jobid in self.jobids:
            c._begin_operation (_("releasing job"))
            try:
                c.setJobHoldUntil (jobid, "no-hold")
            except cups.IPPError as e:
                (e, m) = e.args
                if (e != cups.IPP_NOT_POSSIBLE and
                    e != cups.IPP_NOT_FOUND):
                    self.show_IPP_Error (e, m)
                self.update_monitor ()
                c._end_operation ()
                return
            c._end_operation ()

        del c
        self.update_monitor ()

    def on_job_reprint_activate(self, menuitem):
        try:
            c = authconn.Connection (self.JobsWindow,
                                     host=self.host,
                                     port=self.port,
                                     encryption=self.encryption)
            for jobid in self.jobids:
                c.restartJob (jobid)
            del c
        except cups.IPPError as e:
            (e, m) = e.args
            self.show_IPP_Error (e, m)
            self.update_monitor ()
            return
        except RuntimeError:
            return

        self.update_monitor ()

    def on_job_retrieve_activate(self, menuitem):
        try:
            c = authconn.Connection (self.JobsWindow,
                                     host=self.host,
                                     port=self.port,
                                     encryption=self.encryption)
        except RuntimeError:
            return

        for jobid in self.jobids:
            try:
                attrs=c.getJobAttributes(jobid)
                printer_uri=attrs['job-printer-uri']
                document_count=attrs.get ('document-count', 0)
                for document_number in range(1, document_count+1):
                    document=c.getDocument(printer_uri, jobid, document_number)
                    tempfile = document.get('file')
                    name = document.get('document-name')
                    format = document.get('document-format', '')

                    # if there's no document-name retrieved
                    if name == None:
                        # give the default filename some meaningful name
                        name = _("retrieved")+str(document_number)
                        # add extension according to format
                        if format == 'application/postscript':
                            name = name + ".ps"
                        elif format.find('application/vnd.') != -1:
                            name = name + format.replace('application/vnd', '')
                        elif format.find('application/') != -1:
                            name = name + format.replace('application/', '.')

                    if tempfile != None:
                        dialog = Gtk.FileChooserDialog (_("Save File"),
                                                        self.JobsWindow,
                                                  Gtk.FileChooserAction.SAVE,
                                        (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                                         Gtk.STOCK_SAVE, Gtk.ResponseType.OK))
                        dialog.set_current_name(name)
                        dialog.set_do_overwrite_confirmation(True)

                        response = dialog.run()
                        if response == Gtk.ResponseType.OK:
                            file_to_save = dialog.get_filename()
                            try:
                                shutil.copyfile(tempfile, file_to_save)
                            except (IOError, shutil.Error):
                                debugprint("Unable to save file "+file_to_save)
                        elif response == Gtk.ResponseType.CANCEL:
                            pass
                        dialog.destroy()
                        os.unlink(tempfile)
                    else:
                        debugprint("Unable to retrieve file from job file")
                        return

            except cups.IPPError as e:
                (e, m) = e.args
                self.show_IPP_Error (e, m)
                self.update_monitor ()
                return

        del c
        self.update_monitor ()

    def on_job_move_activate(self, menuitem, job_printer_uri):
        try:
            c = authconn.Connection (self.JobsWindow,
                                     host=self.host,
                                     port=self.port,
                                     encryption=self.encryption)
            for jobid in self.jobids:
                c.moveJob (job_id=jobid, job_printer_uri=job_printer_uri)
            del c
        except cups.IPPError as e:
            (e, m) = e.args
            self.show_IPP_Error (e, m)
            self.update_monitor ()
            return
        except RuntimeError:
            return

        self.update_monitor ()

    def on_job_authenticate_activate(self, menuitem):
        for jobid in self.jobids:
            self.display_auth_info_dialog (jobid)

    def on_refresh_clicked(self, toolbutton):
        self.monitor.refresh ()
        if self.my_monitor:
            self.my_monitor.refresh ()

        self.update_job_creation_times ()

    def on_job_attributes_activate(self, menuitem):
        """ For every selected job create notebook page with attributes. """
        try:
            c = cups.Connection (host=self.host,
                                 port=self.port,
                                 encryption=self.encryption)
        except RuntimeError:
            return False

        for jobid in self.jobids:
            if jobid not in self.jobs_attrs:
                # add new notebook page with scrollable treeview
                scrolledwindow = Gtk.ScrolledWindow()
                label = Gtk.Label(label=str(jobid)) # notebook page has label with jobid
                page_index = self.notebook.append_page(scrolledwindow, label)
                attr_treeview = Gtk.TreeView()
                scrolledwindow.add(attr_treeview)
                cell = Gtk.CellRendererText ()
                attr_treeview.insert_column_with_attributes(0, _("Name"),
                                                            cell, text=0)
                cell = Gtk.CellRendererText ()
                attr_treeview.insert_column_with_attributes(1, _("Value"),
                                                            cell, text=1)
                attr_store = Gtk.ListStore(str, str)
                attr_treeview.set_model(attr_store)
                attr_treeview.get_selection().set_mode(Gtk.SelectionMode.NONE)
                attr_store.set_sort_column_id (0, Gtk.SortType.ASCENDING)
                self.jobs_attrs[jobid] = (attr_store, page_index)
                self.update_job_attributes_viewer (jobid, conn=c)

        self.JobsAttributesWindow.show_all ()

    def update_job_attributes_viewer(self, jobid, conn=None):
        """ Update attributes store with new values. """
        if conn != None:
            c = conn
        else:
            try:
                c = cups.Connection (host=self.host,
                                     port=self.port,
                                     encryption=self.encryption)
            except RuntimeError:
                return False

        if jobid in self.jobs_attrs:
            (attr_store, page) = self.jobs_attrs[jobid]
            try:
                attrs = c.getJobAttributes(jobid)       # new attributes
            except AttributeError:
                return
            except cups.IPPError:
                # someone else may have purged the job,
                # remove jobs notebook page
                self.notebook.remove_page(page)
                del self.jobs_attrs[jobid]
                return

            attr_store.clear()                          # remove old attributes
            for name, value in attrs.iteritems():
                if name in ['job-id', 'job-printer-up-time']:
                    continue
                attr_store.append([name, str(value)])

    def job_is_active (self, jobdata):
        state = jobdata.get ('job-state', cups.IPP_JOB_CANCELED)
        if state >= cups.IPP_JOB_CANCELED:
            return False

        return True

    ## Icon manipulation
    def add_state_reason_emblem (self, pixbuf, printer=None):
        worst_reason = None
        if printer == None and self.worst_reason != None:
            # Check that it's valid.
            printer = self.worst_reason.get_printer ()
            found = False
            for reason in self.printer_state_reasons.get (printer, []):
                if reason == self.worst_reason:
                    worst_reason = self.worst_reason
                    break
            if worst_reason == None:
                self.worst_reason = None

        if printer != None:
            for reason in self.printer_state_reasons.get (printer, []):
                if worst_reason == None:
                    worst_reason = reason
                elif reason > worst_reason:
                    worst_reason = reason

        if worst_reason != None:
            level = worst_reason.get_level ()
            if level > StateReason.REPORT:
                # Add an emblem to the icon.
                icon = StateReason.LEVEL_ICON[level]
                pixbuf = pixbuf.copy ()
                try:
                    theme = Gtk.IconTheme.get_default ()
                    emblem = theme.load_icon (icon, 22, 0)
                    emblem.composite (pixbuf,
                                      pixbuf.get_width () / 2,
                                      pixbuf.get_height () / 2,
                                      emblem.get_width () / 2,
                                      emblem.get_height () / 2,
                                      pixbuf.get_width () / 2,
                                      pixbuf.get_height () / 2,
                                      0.5, 0.5,
                                      GdkPixbuf.InterpType.BILINEAR, 255)
                except GObject.GError:
                    debugprint ("No %s icon available" % icon)

        return pixbuf

    def get_icon_pixbuf (self, have_jobs=None):
        if not self.applet:
            return

        if have_jobs == None:
            have_jobs = len (self.jobs.keys ()) > 0

        if have_jobs:
            pixbuf = self.icon_jobs
            for jobid, jobdata in self.jobs.iteritems ():
                jstate = jobdata.get ('job-state', cups.IPP_JOB_PENDING)
                if jstate == cups.IPP_JOB_PROCESSING:
                    pixbuf = self.icon_jobs_processing
                    break
        else:
            pixbuf = self.icon_no_jobs

        try:
            pixbuf = self.add_state_reason_emblem (pixbuf)
        except:
            nonfatalException ()

        return pixbuf

    def set_statusicon_tooltip (self, tooltip=None):
        if not self.applet:
            return

        if tooltip == None:
            num_jobs = len (self.jobs)
            if num_jobs == 0:
                tooltip = _("No documents queued")
            elif num_jobs == 1:
                tooltip = _("1 document queued")
            else:
                tooltip = _("%d documents queued") % num_jobs

        self.statusicon.set_tooltip_markup (tooltip)

    def update_status (self, have_jobs=None):
        # Found out which printer state reasons apply to our active jobs.
        upset_printers = set()
        for printer, reasons in self.printer_state_reasons.iteritems ():
            if len (reasons) > 0:
                upset_printers.add (printer)
        debugprint ("Upset printers: %s" % upset_printers)

        my_upset_printers = set()
        if len (upset_printers):
            my_upset_printers = set()
            for jobid in self.active_jobs:
                # 'job-printer-name' is set by job_added/job_event
                printer = self.jobs[jobid]['job-printer-name']
                if printer in upset_printers:
                    my_upset_printers.add (printer)
            debugprint ("My upset printers: %s" % my_upset_printers)

        my_reasons = []
        for printer in my_upset_printers:
            my_reasons.extend (self.printer_state_reasons[printer])

        # Find out which is the most problematic.
        self.worst_reason = None
        if len (my_reasons) > 0:
            worst_reason = my_reasons[0]
            for reason in my_reasons:
                if reason > worst_reason:
                    worst_reason = reason
            self.worst_reason = worst_reason
            debugprint ("Worst reason: %s" % worst_reason)

        Gdk.threads_enter ()
        self.statusbar.pop (0)
        if self.worst_reason != None:
            (title, tooltip) = self.worst_reason.get_description ()
            self.statusbar.push (0, tooltip)
        else:
            tooltip = None
            status_message = ""
            processing = 0
            pending = 0
            for jobid in self.active_jobs:
                try:
                    job_state = self.jobs[jobid]['job-state']
                except KeyError:
                    continue
                if job_state == cups.IPP_JOB_PROCESSING:
                    processing = processing + 1
                elif job_state == cups.IPP_JOB_PENDING:
                    pending = pending + 1
            if ((processing > 0) or (pending > 0)):
                status_message = _("processing / pending:   %d / %d") % (processing, pending)
                self.statusbar.push(0, status_message)

        if self.applet and not self.notify_has_persistence:
            pixbuf = self.get_icon_pixbuf (have_jobs=have_jobs)
            self.statusicon.set_from_pixbuf (pixbuf)
            self.set_statusicon_visibility ()
            self.set_statusicon_tooltip (tooltip=tooltip)

        Gdk.threads_leave ()

    ## Notifications
    def notify_printer_state_reason_if_important (self, reason):
        level = reason.get_level ()
        if level < StateReason.WARNING:
            # Not important enough to justify a notification.
            return

        blacklist = [
            # Some printers report 'other-warning' for no apparent
            # reason, e.g.  Canon iR 3170C, Epson AL-CX11NF.
            # See bug #520815.
            "other",

            # This seems to be some sort of 'magic' state reason that
            # is for internal use only.
            "com.apple.print.recoverable",

            # Human-readable text for this reason has misleading wording,
            # suppress it.
            "connecting-to-device",

            # "cups-remote-..." reasons have no human-readable text yet and
            # so get considered as errors, suppress them, too.
            "cups-remote-pending",
            "cups-remote-pending-held",
            "cups-remote-processing",
            "cups-remote-stopped",
            "cups-remote-canceled",
            "cups-remote-aborted",
            "cups-remote-completed"
            ]

        if reason.get_reason () in blacklist:
            return

        self.notify_printer_state_reason (reason)

    def notify_printer_state_reason (self, reason):
        tuple = reason.get_tuple ()
        if self.state_reason_notifications.has_key (tuple):
            debugprint ("Already sent notification for %s" % repr (reason))
            return

        level = reason.get_level ()
        if (level == StateReason.ERROR or
            reason.get_reason () == "connecting-to-device"):
            urgency = Notify.Urgency.NORMAL
        else:
            urgency = Notify.Urgency.LOW

        (title, text) = reason.get_description ()
        notification = Notify.Notification.new (title, text, 'printer')
        reason.user_notified = True
        notification.set_urgency (urgency)
        if self.notify_has_actions:
            notification.set_timeout (Notify.EXPIRES_NEVER)
        notification.connect ('closed',
                              self.on_state_reason_notification_closed)
        self.state_reason_notifications[reason.get_tuple ()] = notification
        self.set_statusicon_visibility ()
        try:
            notification.show ()
        except GObject.GError:
            nonfatalException ()

    def on_state_reason_notification_closed (self, notification, reason=None):
        debugprint ("Notification %s closed" % repr (notification))
        notification.closed = True
        self.set_statusicon_visibility ()
        return

    def notify_completed_job (self, jobid):
        job = self.jobs.get (jobid, {})
        document = job.get ('job-name', _("Unknown"))
        printer_uri = job.get ('job-printer-uri')
        if printer_uri != None:
            # Determine if this printer is remote.  There's no need to
            # show a notification if the printer is connected to this
            # machine.

            # Find out the device URI.  We might already have
            # determined this if authentication was required.
            device_uri = job.get ('device-uri')

            if device_uri == None:
                pattrs = ['device-uri']
                c = authconn.Connection (self.JobsWindow,
                                         host=self.host,
                                         port=self.port,
                                         encryption=self.encryption)
                try:
                    attrs = c.getPrinterAttributes (uri=printer_uri,
                                                    requested_attributes=pattrs)
                except cups.IPPError:
                    return

                device_uri = attrs.get ('device-uri')

            if device_uri != None:
                (scheme, rest) = urllib.splittype (device_uri)
                if scheme not in ['socket', 'ipp', 'http', 'smb']:
                    return

        printer = job.get ('job-printer-name', _("Unknown"))
        notification = Notify.Notification.new (_("Document printed"),
                                              _("Document `%s' has been sent "
                                                "to `%s' for printing.") %
                                              (document,
                                               printer),
                                              'printer')
        notification.set_urgency (Notify.Urgency.LOW)
        notification.connect ('closed',
                              self.on_completed_job_notification_closed)
        notification.jobid = jobid
        self.completed_job_notifications[jobid] = notification
        self.set_statusicon_visibility ()
        try:
            notification.show ()
        except GObject.GError:
            nonfatalException ()

    def on_completed_job_notification_closed (self, notification, reason=None):
        jobid = notification.jobid
        del self.completed_job_notifications[jobid]
        self.set_statusicon_visibility ()

    ## Monitor signal handlers
    def on_refresh (self, mon):
        self.store.clear ()
        self.jobs = {}
        self.active_jobs = set()
        self.jobiters = {}
        self.printer_uri_index = PrinterURIIndex ()

    def job_added (self, mon, jobid, eventname, event, jobdata):
        uri = jobdata.get ('job-printer-uri', '')
        try:
            printer = self.printer_uri_index.lookup (uri)
        except KeyError:
            printer = uri

        if self.specific_dests and printer not in self.specific_dests:
            return

        jobdata['job-printer-name'] = printer

        # We may be showing this job already, perhaps because we are showing
        # completed jobs and one was reprinted.
        if not self.jobiters.has_key (jobid):
            self.add_job (jobid, jobdata)
        elif mon == self.my_monitor:
            # Copy over any missing attributes such as user and title.
            for attr, value in jobdata.iteritems ():
                if not self.jobs[jobid].has_key (attr):
                    self.jobs[jobid][attr] = value
                    debugprint ("Add %s=%s (my job)" % (attr, value))

        # If we failed to get required attributes for the job, bail.
        if not self.jobiters.has_key (jobid):
            return

        if self.job_is_active (jobdata):
            self.active_jobs.add (jobid)
        elif jobid in self.active_jobs:
            self.active_jobs.remove (jobid)

        self.update_status (have_jobs=True)
        if self.applet:
            if not self.job_is_active (jobdata):
                return

            for reason in self.printer_state_reasons.get (printer, []):
                if not reason.user_notified:
                    self.notify_printer_state_reason_if_important (reason)

    def job_event (self, mon, jobid, eventname, event, jobdata):
        uri = jobdata.get ('job-printer-uri', '')
        try:
            printer = self.printer_uri_index.lookup (uri)
        except KeyError:
            printer = uri

        if self.specific_dests and printer not in self.specific_dests:
            return

        jobdata['job-printer-name'] = printer

        if self.job_is_active (jobdata):
            self.active_jobs.add (jobid)
        elif jobid in self.active_jobs:
            self.active_jobs.remove (jobid)

        self.update_job (jobid, jobdata)
        self.update_status ()

        # Check that the job still exists, as update_status re-enters
        # the main loop in order to paint/hide the tray icon.  Really
        # that should probably be deferred to the idle handler, but
        # for the moment just deal with the fact that the job might
        # have gone (bug #640904).
        if not self.jobs.has_key (jobid):
            return

        jobdata = self.jobs[jobid]

        # If the job has finished, let the user know.
        if self.applet and (eventname == 'job-completed' or
                            (eventname == 'job-state-changed' and
                             event['job-state'] == cups.IPP_JOB_COMPLETED)):
            reasons = event['job-state-reasons']
            if type (reasons) != list:
                reasons = [reasons]

            canceled = False
            for reason in reasons:
                if reason.startswith ("job-canceled"):
                    canceled = True
                    break

            if not canceled:
                self.notify_completed_job (jobid)

        # Look out for stopped jobs.
        if (self.applet and
            (eventname == 'job-stopped' or
             (eventname == 'job-state-changed' and
              event['job-state'] in [cups.IPP_JOB_STOPPED,
                                     cups.IPP_JOB_PENDING])) and
            not jobid in self.stopped_job_prompts):
            # Why has the job stopped?  It might be due to a job error
            # of some sort, or it might be that the backend requires
            # authentication.  If the latter, the job will be held not
            # stopped, and the job-hold-until attribute will be
            # 'auth-info-required'.  This was already checked for in
            # update_job.
            may_be_problem = True
            jstate = jobdata['job-state']
            if (jstate == cups.IPP_JOB_PROCESSING or
                (jstate == cups.IPP_JOB_HELD and
                 jobdata['job-hold-until'] == 'auth-info-required')):
                # update_job already dealt with this.
                may_be_problem = False
            else:
                # Other than that, unfortunately the only
                # clue we get is the notify-text, which is not
                # translated into our native language.  We'd better
                # try parsing it.  In CUPS-1.3.6 the possible strings
                # are:
                #
                # "Job stopped due to filter errors; please consult
                # the error_log file for details."
                #
                # "Job stopped due to backend errors; please consult
                # the error_log file for details."
                #
                # "Job held due to backend errors; please consult the
                # error_log file for details."
                #
                # "Authentication is required for job %d."
                # [This case is handled in the update_job method.]
                #
                # "Job stopped due to printer being paused"
                # [This should be ignored, as the job was doing just
                # fine until the printer was stopped for other reasons.]
                notify_text = event['notify-text']
                document = jobdata['job-name']
                if notify_text.find ("backend errors") != -1:
                    message = (_("There was a problem sending document `%s' "
                                 "(job %d) to the printer.") %
                               (document, jobid))
                elif notify_text.find ("filter errors") != -1:
                    message = _("There was a problem processing document `%s' "
                                "(job %d).") % (document, jobid)
                elif (notify_text.find ("being paused") != -1 or
                      jstate != cups.IPP_JOB_STOPPED):
                    may_be_problem = False
                else:
                    # Give up and use the provided message untranslated.
                    message = (_("There was a problem printing document `%s' "
                                 "(job %d): `%s'.") %
                               (document, jobid, notify_text))

            if may_be_problem:
                debugprint ("Problem detected")
                self.toggle_window_display (None, force_show=True)
                dialog = Gtk.Dialog (_("Print Error"), self.JobsWindow, 0,
                                     (_("_Diagnose"), Gtk.ResponseType.NO,
                                        Gtk.STOCK_OK, Gtk.ResponseType.OK))
                dialog.set_default_response (Gtk.ResponseType.OK)
                dialog.set_border_width (6)
                dialog.set_resizable (False)
                dialog.set_icon_name (ICON)
                hbox = Gtk.HBox.new (False, 12)
                hbox.set_border_width (6)
                image = Gtk.Image ()
                image.set_from_stock (Gtk.STOCK_DIALOG_ERROR,
                                      Gtk.IconSize.DIALOG)
                hbox.pack_start (image, False, False, 0)
                vbox = Gtk.VBox.new (False, 12)

                markup = ('<span weight="bold" size="larger">' +
                          _("Print Error") + '</span>\n\n' +
                          saxutils.escape (message))
                try:
                    if event['printer-state'] == cups.IPP_PRINTER_STOPPED:
                        name = event['printer-name']
                        markup += ' '
                        markup += (_("The printer called `%s' has "
                                     "been disabled.") % name)
                except KeyError:
                    pass

                label = Gtk.Label(label=markup)
                label.set_use_markup (True)
                label.set_line_wrap (True)
                label.set_alignment (0, 0)
                vbox.pack_start (label, False, False, 0)
                hbox.pack_start (vbox, False, False, 0)
                dialog.vbox.pack_start (hbox, False, False, 0)
                dialog.connect ('response',
                                self.print_error_dialog_response, jobid)
                self.stopped_job_prompts.add (jobid)
                dialog.show_all ()

    def job_removed (self, mon, jobid, eventname, event):
        # If the job has finished, let the user know.
        if self.applet and (eventname == 'job-completed' or
                            (eventname == 'job-state-changed' and
                             event['job-state'] == cups.IPP_JOB_COMPLETED)):
            reasons = event['job-state-reasons']
            debugprint (reasons)
            if type (reasons) != list:
                reasons = [reasons]

            canceled = False
            for reason in reasons:
                if reason.startswith ("job-canceled"):
                    canceled = True
                    break

            if not canceled:
                self.notify_completed_job (jobid)

        if self.jobiters.has_key (jobid):
            self.store.remove (self.jobiters[jobid])
            del self.jobiters[jobid]
            del self.jobs[jobid]

        if jobid in self.active_jobs:
            self.active_jobs.remove (jobid)

        if self.jobs_attrs.has_key (jobid):
            del self.jobs_attrs[jobid]

        self.update_status ()

    def state_reason_added (self, mon, reason):
        (title, text) = reason.get_description ()
        printer = reason.get_printer ()

        try:
            l = self.printer_state_reasons[printer]
        except KeyError:
            l = []
            self.printer_state_reasons[printer] = l

        reason.user_notified = False
        l.append (reason)
        self.update_status ()
        self.treeview.queue_draw ()

        if not self.applet:
            return

        # Find out if the user has jobs queued for that printer.
        for job, data in self.jobs.iteritems ():
            if not self.job_is_active (data):
                continue
            if data['job-printer-name'] == printer:
                # Yes!  Notify them of the state reason, if necessary.
                self.notify_printer_state_reason_if_important (reason)
                break

    def state_reason_removed (self, mon, reason):
        printer = reason.get_printer ()
        try:
            reasons = self.printer_state_reasons[printer]
        except KeyError:
            debugprint ("Printer not found")
            return

        try:
            i = reasons.index (reason)
        except IndexError:
            debugprint ("Reason not found")
            return

        del reasons[i]

        self.update_status ()
        self.treeview.queue_draw ()

        if not self.applet:
            return

        tuple = reason.get_tuple ()
        try:
            notification = self.state_reason_notifications[tuple]
            if getattr (notification, 'closed', None) != True:
                try:
                    notification.close ()
                except GLib.GError:
                    # Can fail if the notification wasn't even shown
                    # yet (as in bug #545733).
                    pass

            del self.state_reason_notifications[tuple]
            self.set_statusicon_visibility ()
        except KeyError:
            pass

    def still_connecting (self, mon, reason):
        if not self.applet:
            return

        self.notify_printer_state_reason (reason)

    def now_connected (self, mon, printer):
        if not self.applet:
            return

        # Find the connecting-to-device state reason.
        try:
            reasons = self.printer_state_reasons[printer]
            reason = None
            for r in reasons:
                if r.get_reason () == "connecting-to-device":
                    reason = r
                    break
        except KeyError:
            debugprint ("Couldn't find state reason (no reasons)!")

        if reason != None:
            tuple = reason.get_tuple ()
        else:
            debugprint ("Couldn't find state reason in list!")
            tuple = None
            for (level,
                 p,
                 r) in self.state_reason_notifications.keys ():
                if p == printer and r == "connecting-to-device":
                    debugprint ("Found from notifications list")
                    tuple = (level, p, r)
                    break

            if tuple == None:
                debugprint ("Unexpected now_connected signal "
                            "(reason not in notifications list)")
                return

        try:
            notification = self.state_reason_notifications[tuple]
        except KeyError:
            debugprint ("Unexpected now_connected signal")
            return

        if getattr (notification, 'closed', None) != True:
            try:
                notification.close ()
            except GLib.GError:
                # Can fail if the notification wasn't even shown
                pass
            notification.closed = True

    def printer_added (self, mon, printer):
        self.printer_uri_index.add_printer (printer)

    def printer_event (self, mon, printer, eventname, event):
        self.printer_uri_index.update_from_attrs (printer, event)

    def printer_removed (self, mon, printer):
        self.printer_uri_index.remove_printer (printer)

    ### Cell data functions
    def _set_job_job_number_text (self, column, cell, model, iter, *data):
        cell.set_property("text", str (model.get_value (iter, 0)))

    def _set_job_user_text (self, column, cell, model, iter, *data):
        jobid = model.get_value (iter, 0)
        job = self.jobs[jobid]
        cell.set_property("text", job.get ('job-originating-user-name',
                                           _("Unknown")))

    def _set_job_document_text (self, column, cell, model, iter, *data):
        jobid = model.get_value (iter, 0)
        job = self.jobs[jobid]
        cell.set_property("text", job.get('job-name', _("Unknown")))

    def _set_job_printer_text (self, column, cell, model, iter, *data):
        jobid = model.get_value (iter, 0)
        reasons = self.jobs[jobid].get('job-state-reasons')
        if reasons == 'printer-stopped':
            reason = ' - ' + _("disabled")
        else:
            reason = ''
        cell.set_property("text", self.jobs[jobid]['job-printer-name']+reason)

    def _set_job_size_text (self, column, cell, model, iter, *data):
        jobid = model.get_value (iter, 0)
        job = self.jobs[jobid]
        size = _("Unknown")
        if job.has_key ('job-k-octets'):
            size = str (job['job-k-octets']) + 'k'
        cell.set_property("text", size)

    def _find_job_state_text (self, job):
        data = self.jobs[job]
        jstate = data.get ('job-state', cups.IPP_JOB_PROCESSING)
        s = int (jstate)
        job_requires_auth = (s == cups.IPP_JOB_HELD and
                             data.get ('job-hold-until', 'none') ==
                             'auth-info-required')
        state = None
        if job_requires_auth:
            state = _("Held for authentication")
        elif s == cups.IPP_JOB_HELD:
            state = _("Held")
            until = data.get ('job-hold-until')
            if until != None:
                try:
                    colon1 = until.find (':')
                    if colon1 != -1:
                        now = time.gmtime ()
                        hh = int (until[:colon1])
                        colon2 = until[colon1 + 1:].find (':')
                        if colon2 != -1:
                            colon2 += colon1 + 1
                            mm = int (until[colon1 + 1:colon2])
                            ss = int (until[colon2 + 1:])
                        else:
                            mm = int (until[colon1 + 1:])
                            ss = 0

                        day = now.tm_mday
                        if (hh < now.tm_hour or
                            (hh == now.tm_hour and
                             (mm < now.tm_min or
                              (mm == now.tm_min and ss < now.tm_sec)))):
                            day += 1

                        hold = (now.tm_year, now.tm_mon, day,
                                hh, mm, ss, 0, 0, -1)
                        old_tz = os.environ.get("TZ")
                        os.environ["TZ"] = "UTC"
                        simpletime = time.mktime (hold)

                        if old_tz == None:
                            del os.environ["TZ"]
                        else:
                            os.environ["TZ"] = old_tz

                        local = time.localtime (simpletime)
                        state = (_("Held until %s") %
                                 time.strftime ("%X", local))
                except ValueError:
                    pass
            if until == "day-time":
                state = _("Held until day-time")
            elif until == "evening":
                state = _("Held until evening")
            elif until == "night":
                state = _("Held until night-time")
            elif until == "second-shift":
                state = _("Held until second shift")
            elif until == "third-shift":
                state = _("Held until third shift")
            elif until == "weekend":
                state = _("Held until weekend")
        else:
            try:
                state = { cups.IPP_JOB_PENDING: _("Pending"),
                          cups.IPP_JOB_PROCESSING: _("Processing"),
                          cups.IPP_JOB_STOPPED: _("Stopped"),
                          cups.IPP_JOB_CANCELED: _("Canceled"),
                          cups.IPP_JOB_ABORTED: _("Aborted"),
                          cups.IPP_JOB_COMPLETED: _("Completed") }[s]
            except IndexError:
                pass

        if state == None:
            state = _("Unknown")

        return state

    def _set_job_status_icon (self, column, cell, model, iter, *data):
        jobid = model.get_value (iter, 0)
        data = self.jobs[jobid]
        jstate = data.get ('job-state', cups.IPP_JOB_PROCESSING)
        s = int (jstate)
        if s == cups.IPP_JOB_PROCESSING:
            icon = self.icon_jobs_processing
        else:
            icon = self.icon_jobs

        if s == cups.IPP_JOB_HELD:
            try:
                theme = Gtk.IconTheme.get_default ()
                emblem = theme.load_icon (Gtk.STOCK_MEDIA_PAUSE, 22 / 2, 0)
                copy = icon.copy ()
                emblem.composite (copy, 0, 0,
                                  copy.get_width (),
                                  copy.get_height (),
                                  copy.get_width () / 2 - 1,
                                  copy.get_height () / 2 - 1,
                                  1.0, 1.0,
                                  GdkPixbuf.InterpType.NEAREST, 255)
                icon = copy
            except GObject.GError:
                debugprint ("No %s icon available" % Gtk.STOCK_MEDIA_PAUSE)
        else:
            # Check state reasons.
            printer = data['job-printer-name']
            icon = self.add_state_reason_emblem (icon, printer=printer)

        cell.set_property ("pixbuf", icon)

    def _set_job_status_text (self, column, cell, model, iter, *data):
        jobid = model.get_value (iter, 0)
        data = self.jobs[jobid]
        try:
            text = data['_status_text']
        except KeyError:
            text = self._find_job_state_text (jobid)
            data['_status_text'] = text

        printer = data['job-printer-name']
        reasons = self.printer_state_reasons.get (printer, [])
        if len (reasons) > 0:
            worst_reason = reasons[0]
            for reason in reasons[1:]:
                if reason > worst_reason:
                    worst_reason = reason
            (title, unused) = worst_reason.get_description ()
            text += " - " + title

        cell.set_property ("text", text)

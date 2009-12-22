
## Copyright (C) 2007, 2008, 2009 Tim Waugh <twaugh@redhat.com>
## Copyright (C) 2007, 2008, 2009 Red Hat, Inc.

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

import authconn
import cups
import dbus
import dbus.glib
import dbus.service
import pynotify
import gettext
import gobject
import gtk
import gtk.gdk
import gtk.glade
from glade import GtkGUI
import monitor
import os
import pango
import pwd
import smburi
import subprocess
import sys
import time
import urllib

from debug import *
import config
import statereason
import errordialogs

try:
    import gnomekeyring
    USE_KEYRING=True
except ImportError:
    USE_KEYRING=False

from gettext import gettext as _
DOMAIN="system-config-printer"
gettext.textdomain (DOMAIN)
gtk.glade.textdomain (DOMAIN)
gtk.glade.bindtextdomain (DOMAIN)
from statereason import StateReason
statereason.set_gettext_function (_)
errordialogs.set_gettext_function (_)

pkgdata = config.pkgdatadir
GLADE="applet.glade"
ICON="printer"
SEARCHING_ICON="document-print-preview"

# We need to call pynotify.init before we can check the server for caps
pynotify.init('System Config Printer Notification')

class PrinterURIIndex:
    def __init__ (self, names=None):
        self.printer = {}
        self.names = names

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
        uris = self.printer.keys ()
        for uri in uris:
            if self.printer[uri] == printer:
                del self.printer[uri]

    def lookup (self, uri, connection=None):
        try:
            return self.printer[uri]
        except KeyError:
            if connection == None:
                connection = cups.Connection ()

            r = ['printer-name', 'printer-uri-supported', 'printer-more-info']
            try:
                attrs = connection.getPrinterAttributes (uri=uri,
                                                         requested_attributes=r)
            except cups.IPPError:
                # URI not known.
                raise KeyError

            name = attrs['printer-name']
            self.update_from_attrs (name, attrs)
            self.printer[uri] = name
            try:
                return self.printer[uri]
            except KeyError:
                pass
        raise KeyError


class JobViewer (GtkGUI, monitor.Watcher):
    required_job_attributes = set(['job-k-octets',
                                   'job-name',
                                   'job-originating-user-name',
                                   'job-printer-uri',
                                   'job-state',
                                   'time-at-creation'])

    def __init__(self, bus=None, loop=None, service_running=False,
                 trayicon=False, suppress_icon_hide=False,
                 my_jobs=True, specific_dests=None, exit_handler=None,
                 parent=None):
        self.loop = loop
        self.service_running = service_running
        self.trayicon = trayicon
        self.suppress_icon_hide = suppress_icon_hide
        self.my_jobs = my_jobs
        self.specific_dests = specific_dests
        self.exit_handler = exit_handler

        self.jobs = {}
        self.jobiters = {}
        self.active_jobs = set() # of job IDs
        self.stopped_job_prompts = set() # of job IDs
        self.printer_state_reasons = {}
        self.num_jobs_when_hidden = 0
        self.connecting_to_device = {} # dict of printer->time first seen
        self.state_reason_notifications = {}
        self.auth_info_dialogs = {} # by job ID
        self.job_creation_times_timer = None
        self.special_status_icon = False
        self.new_printer_notifications = {}
        self.authenticated_jobs = set() # of job IDs

        self.getWidgets ({"JobsWindow":
                              ["JobsWindow",
                               "job_menubar_item",
                               "treeview",
                               "statusbar"],
                          "statusicon_popupmenu":
                              ["statusicon_popupmenu"]})

        job_action_group = gtk.ActionGroup ("JobActionGroup")
        job_action_group.add_actions ([
                ("cancel-job", gtk.STOCK_CANCEL, None, None, None,
                 self.on_job_cancel_activate),
                ("hold-job", gtk.STOCK_MEDIA_PAUSE, _("_Hold"), None, None,
                 self.on_job_hold_activate),
                ("release-job", gtk.STOCK_MEDIA_PLAY, _("_Release"), None, None,
                 self.on_job_release_activate),
                ("reprint-job", gtk.STOCK_REDO, _("Re_print"), None, None,
                 self.on_job_reprint_activate),
                ("authenticate-job", None, _("_Authenticate"), None, None,
                 self.on_job_authenticate_activate)
                ])
        self.job_ui_manager = gtk.UIManager ()
        self.job_ui_manager.insert_action_group (job_action_group, -1)
        self.job_ui_manager.add_ui_from_string (
"""
<ui>
 <accelerator action="cancel-job"/>
 <accelerator action="hold-job"/>
 <accelerator action="release-job"/>
 <accelerator action="reprint-job"/>
 <accelerator action="authenticate-job"/>
</ui>
"""
)
        self.job_ui_manager.ensure_update ()
        self.JobsWindow.add_accel_group (self.job_ui_manager.get_accel_group ())
        self.job_context_menu = gtk.Menu ()
        for action_name in ["cancel-job",
                            "hold-job",
                            "release-job",
                            "reprint-job",
                            None,
                            "authenticate-job"]:
            if not action_name:
                item = gtk.SeparatorMenuItem ()
            else:
                action = job_action_group.get_action (action_name)
                action.set_sensitive (False)
                item = action.create_menu_item ()

            item.show ()
            self.job_context_menu.append (item)

        self.job_menubar_item.set_submenu (self.job_context_menu)

        for skip, ellipsize, name, setter in \
                [(False, False, _("Job"), self._set_job_job_number_text),
                 (True, False, _("User"), self._set_job_user_text),
                 (False, True, _("Document"), self._set_job_document_text),
                 (False, True, _("Printer"), self._set_job_printer_text),
                 (False, False, _("Size"), self._set_job_size_text)]:
            if trayicon and skip:
                # Skip the user column for the trayicon.
                continue

            cell = gtk.CellRendererText()
            if ellipsize:
                # Ellipsize the 'Document' and 'Printer' columns.
                cell.set_property ("ellipsize", pango.ELLIPSIZE_END)
                cell.set_property ("width-chars", 20)
            column = gtk.TreeViewColumn(name, cell)
            column.set_cell_data_func (cell, setter)
            column.set_resizable(True)
            self.treeview.append_column(column)

        cell = gtk.CellRendererText ()
        column = gtk.TreeViewColumn (_("Time submitted"), cell, text=1)
        column.set_resizable (True)
        self.treeview.append_column (column)

        column = gtk.TreeViewColumn (_("Status"))
        icon = gtk.CellRendererPixbuf ()
        column.pack_start (icon, False)
        text = gtk.CellRendererText ()
        text.set_property ("ellipsize", pango.ELLIPSIZE_END)
        text.set_property ("width-chars", 20)
        column.pack_start (text, True)
        column.set_cell_data_func (icon, self._set_job_status_icon)
        column.set_cell_data_func (text, self._set_job_status_text)
        self.treeview.append_column (column)

        self.treeview.get_selection().set_mode(gtk.SELECTION_SINGLE)
        self.store = gtk.TreeStore(int, str)
        self.store.set_sort_column_id (0, gtk.SORT_DESCENDING)
        self.treeview.set_model(self.store)
        self.treeview.set_rules_hint (True)
        self.treeview.connect ('button_release_event',
                               self.on_treeview_button_release_event)
        self.treeview.connect ('popup-menu', self.on_treeview_popup_menu)
        self.treeview.connect ('cursor-changed',
                               self.on_treeview_cursor_changed)
        self.store.connect ('row-changed',
                            self.on_treemodel_row_changed)

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

        self.statusbar_set = False

        theme = gtk.icon_theme_get_default ()
        self.icon_jobs = theme.load_icon (ICON, 22, 0)
        self.icon_jobs_processing = theme.load_icon ("printer-printing",
                                                     22, 0)
        self.icon_no_jobs = self.icon_jobs.copy ()
        self.icon_no_jobs.fill (0)
        self.icon_jobs.composite (self.icon_no_jobs,
                                  0, 0,
                                  self.icon_no_jobs.get_width(),
                                  self.icon_no_jobs.get_height(),
                                  0, 0,
                                  1.0, 1.0,
                                  gtk.gdk.INTERP_BILINEAR,
                                  127)
        if self.trayicon:
            self.statusicon = gtk.StatusIcon ()
            pixbuf = theme.load_icon (ICON, 22, 0)
            self.statusicon.set_from_pixbuf (pixbuf)    
            self.set_statusicon_from_pixbuf (self.icon_no_jobs)
            self.statusicon.connect ('activate', self.toggle_window_display)
            self.statusicon.connect ('popup-menu', self.on_icon_popupmenu)
            self.statusicon.set_visible (False)

        # D-Bus
        if bus == None:
            bus = dbus.SystemBus ()

        self.set_process_pending (True)
        self.host = cups.getServer ()
        self.port = cups.getPort ()
        self.encryption = cups.getEncryption ()
        self.monitor = monitor.Monitor (self, bus=bus, my_jobs=my_jobs,
                                        specific_dests=specific_dests,
                                        host=self.host, port=self.port,
                                        encryption=self.encryption)

        if not self.trayicon:
            self.JobsWindow.show ()

    def cleanup (self):
        self.monitor.cleanup ()

        # Close any open notifications.
        for l in [self.new_printer_notifications.values (),
                  self.state_reason_notifications.values ()]:
            for notification in l:
                if notification.get_data ('closed') != True:
                    notification.close ()
                    notification.set_data ('closed', True)

        if self.job_creation_times_timer != None:
            gobject.source_remove (self.job_creation_times_timer)
            self.job_creation_times_timer = None

        if self.exit_handler:
            self.exit_handler (self)

    def set_process_pending (self, whether):
        self.process_pending_events = whether

    # Handle "special" status icon
    def set_special_statusicon (self, iconname, tooltip=None):
        self.special_status_icon = True
        self.statusicon.set_from_icon_name (iconname)
        self.set_statusicon_visibility ()
        if tooltip != None:
            self.set_statusicon_tooltip (tooltip=tooltip)

    def unset_special_statusicon (self):
        self.special_status_icon = False
        self.statusicon.set_from_pixbuf (self.saved_statusicon_pixbuf)
        self.set_statusicon_visibility ()
        self.set_statusicon_tooltip ()

    def notify_new_printer (self, printer, notification):
        self.new_printer_notifications[printer] = notification
        notification.set_data ('printer-name', printer)
        notification.connect ('closed', self.on_new_printer_notification_closed)
        self.set_statusicon_visibility ()
        notification.attach_to_status_icon (self.statusicon)
        try:
            notification.show ()
        except gobject.GError:
            nonfatalException ()

    def on_new_printer_notification_closed (self, notification, reason=None):
        printer = notification.get_data ('printer-name')
        del self.new_printer_notifications[printer]
        self.set_statusicon_visibility ()

    def set_statusicon_from_pixbuf (self, pb):
        self.saved_statusicon_pixbuf = pb
        if not self.special_status_icon:
            self.statusicon.set_from_pixbuf (pb)

    def on_delete_event(self, *args):
        if self.trayicon or not self.loop:
            self.JobsWindow.hide ()
            self.JobsWindow.set_data ('visible', False)
            if not self.loop:
                # Being run from main app, not applet
                self.cleanup ()
        else:
            self.loop.quit ()
        return True

    def show_IPP_Error(self, exception, message):
        return errordialogs.show_IPP_Error (exception, message, self.JobsWindow)

    def toggle_window_display(self, icon, force_show=False):
        visible = self.JobsWindow.get_data('visible')
        if force_show:
            visible = False

        if visible:
            w = self.JobsWindow.window
            (s, area, o) = self.statusicon.get_geometry ()
            w.set_skip_taskbar_hint (True)
            w.property_change ("_NET_WM_ICON_GEOMETRY",
                               "CARDINAL", 32,
                               gtk.gdk.PROP_MODE_REPLACE,
                               list (area))
            self.JobsWindow.iconify ()
        else:
            self.JobsWindow.present ()
            self.JobsWindow.window.set_skip_taskbar_hint (False)

        self.JobsWindow.set_data ('visible', not visible)

    def on_show_completed_jobs_activate(self, menuitem):
        if menuitem.get_active():
            which_jobs = "all"
        else:
            which_jobs = "not-completed"
        self.monitor.refresh(which_jobs=which_jobs, refresh_all=False)

    def update_job_creation_times(self):
        now = time.time ()
        need_update = False
        for job, data in self.jobs.iteritems():
            if self.jobs.has_key (job):
                iter = self.jobiters[job]

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

            self.store.set_value (iter, 1, t)

        if need_update and not self.job_creation_times_timer:
            t = gobject.timeout_add_seconds (60, self.update_job_creation_times)
            self.job_creation_times_timer = t

        if not need_update:
            if self.job_creation_times_timer:
                gobject.source_remove (self.job_creation_times_timer)
                self.job_creation_times_timer = None

        # Return code controls whether the timeout will recur.
        return need_update

    def print_error_dialog_response(self, dialog, response, jobid):
        dialog.hide ()
        dialog.destroy ()
        self.stopped_job_prompts.remove (jobid)
        if response == gtk.RESPONSE_NO:
            # Diagnose
            if not self.__dict__.has_key ('troubleshooter'):
                import troubleshoot
                troubleshooter = troubleshoot.run (self.on_troubleshoot_quit)
                self.troubleshooter = troubleshooter

    def on_troubleshoot_quit(self, troubleshooter):
        del self.troubleshooter

    def add_job (self, job, data, connection=None):
        self.update_job (job, data, connection=connection)

        store = self.store
        iter = self.store.append (None)
        store.set_value (iter, 0, job)
        debugprint ("Job %d added" % job)
        self.jobiters[job] = iter

        range = self.treeview.get_visible_range ()
        if range != None:
            (start, end) = range
            if (self.store.get_sort_column_id () == (0,
                                                     gtk.SORT_DESCENDING) and
                start == (1,)):
                # This job was added job above the visible range, and
                # we are sorting by descending job ID.  Scroll to it.
                self.treeview.scroll_to_cell ((0,), None, False, 0.0, 0.0)

        if not self.job_creation_times_timer:
            def start_updating_job_creation_times():
                self.update_job_creation_times ()
                return False

            gobject.timeout_add (500, start_updating_job_creation_times)

    def update_job (self, job, data, connection=None):
        # Fetch required attributes for this job if they are missing.
        r = self.required_job_attributes - set (data.keys ())

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
        except cups.IPPError, (e, m):
            pass

        # Invalidate the cached status description and redraw the treeview.
        try:
            del data['_status_text']
        except KeyError:
            pass
        self.treeview.queue_draw ()

        # Check whether authentication is required.
        if self.trayicon:
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
                keyring_attrs = None
                auth_info = None
                if try_keyring and 'password' in auth_info_required:
                    auth_info_required = data.get ('auth-info-required', [])
                    device_uri = data.get ("device-uri")
                    (scheme, rest) = urllib.splittype (device_uri)
                    keyring_attrs = dict ()
                    if scheme == 'smb':
                        uri = smburi.SMBURI (uri=device_uri)
                        (group, server, share,
                         user, password) = uri.separate ()
                        keyring_attrs["domain"] = str (group)
                    else:
                        (serverport, rest) = urllib.splithost (rest)
                        (server, port) = urllib.splitnport (serverport)
                    keyring_attrs.update ({ "server": str (server.lower ()),
                                            "protocol": str (scheme)})

                if job in self.authenticated_jobs:
                    # We've already tried to authenticate this job before.
                    try_keyring = False

                if try_keyring and 'password' in auth_info_required:
                    type = gnomekeyring.ITEM_NETWORK_PASSWORD
                    try:
                        items = gnomekeyring.find_items_sync (type,
                                                              keyring_attrs)
                        auth_info = map (lambda x: '', auth_info_required)
                        ind = auth_info_required.index ('username')
                        auth_info[ind] = items[0].attributes.get ('user', '')
                        ind = auth_info_required.index ('password')
                        auth_info[ind] = items[0].secret
                    except gnomekeyring.NoMatchError:
                        debugprint ("gnomekeyring: no match for %s" %
                                    keyring_attrs)
                    except gnomekeyring.DeniedError:
                        debugprint ("gnomekeyring: denied for %s" %
                                    keyring_attrs)

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
                        self.monitor.update ()
                        debugprint ("Automatically authenticated job %d" % job)
                        self.authenticated_jobs.add (job)
                        return
                    except cups.IPPError, (e, m):
                        c._end_operation ()
                        nonfatalException ()
                        return
                    except:
                        c._end_operation ()
                        nonfatalException ()

                username = pwd.getpwuid (os.getuid ())[0]
                keyring_attrs["user"] = str (username)
                self.display_auth_info_dialog (job, keyring_attrs)

    def display_auth_info_dialog (self, job, keyring_attrs=None):
        data = self.jobs[job]
        auth_info_required = data['auth-info-required']
        dialog = authconn.AuthDialog (auth_info_required=auth_info_required,
                                      allow_remember=USE_KEYRING)
        dialog.set_data ('keyring-attrs', keyring_attrs)
        dialog.set_data ('auth-info-required', auth_info_required)
        dialog.set_position (gtk.WIN_POS_CENTER)

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
                           (data.get('job-name', _("Unknown")), job))
        self.auth_info_dialogs[job] = dialog
        dialog.connect ('response', self.auth_info_dialog_response)
        dialog.connect ('delete-event', self.auth_info_dialog_delete)
        dialog.set_data ('job-id', job)
        dialog.show_all ()
        dialog.set_keep_above (True)
        dialog.show_now ()

    def auth_info_dialog_delete (self, dialog, event):
        self.auth_info_dialog_response (dialog, gtk.RESPONSE_CANCEL)

    def auth_info_dialog_response (self, dialog, response):
        jobid = dialog.get_data ('job-id')
        del self.auth_info_dialogs[jobid]
        if response != gtk.RESPONSE_OK:
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
            self.monitor.update ()
        except cups.IPPError, (e, m):
            self.show_IPP_Error (e, m)

        c._end_operation ()

        if remember:
            try:
                keyring = gnomekeyring.get_default_keyring_sync ()
                type = gnomekeyring.ITEM_NETWORK_PASSWORD
                attrs = dialog.get_data ("keyring-attrs")
                auth_info_required = dialog.get_data ('auth-info-required')
                if attrs != None and auth_info_required != None:
                    try:
                        ind = auth_info_required.index ('username')
                        attrs['user'] = auth_info[ind]
                    except IndexError:
                        pass

                    name = "%s@%s (%s)" % (attrs.get ("user"),
                                           attrs.get ("server"),
                                           attrs.get ("protocol"))
                    ind = auth_info_required.index ('password')
                    secret = auth_info[ind]
                    id = gnomekeyring.item_create_sync (keyring, type, name,
                                                        attrs, secret, True)
                    debugprint ("keyring: created id %d for %s" % (id, name))
            except:
                nonfatalException ()

        dialog.destroy ()

    def set_statusicon_visibility (self):
        if not self.trayicon:
            return

        if self.suppress_icon_hide:
            # Avoid hiding the icon if we've been woken up to notify
            # about a new printer.
            self.suppress_icon_hide = False
            return

        open_notifications = len (self.new_printer_notifications.keys ())
        for reason, notification in self.state_reason_notifications.iteritems():
            if notification.get_data ('closed') != True:
                open_notifications += 1
        num_jobs = len (self.active_jobs)

        debugprint ("open notifications: %d" % open_notifications)
        debugprint ("num_jobs: %d" % num_jobs)
        debugprint ("num_jobs_when_hidden: %d" % self.num_jobs_when_hidden)

        self.statusicon.set_visible (self.special_status_icon or
                                     open_notifications > 0 or
                                     num_jobs > self.num_jobs_when_hidden)

        # Let the icon show/hide itself before continuing.
        while self.process_pending_events and gtk.events_pending ():
            gtk.main_iteration ()

    def on_treeview_popup_menu (self, treeview):
        event = gtk.gdk.Event (gtk.gdk.NOTHING)
        self.show_treeview_popup_menu (treeview, event, 0)

    def on_treeview_button_release_event(self, treeview, event):
        if event.button == 3:
            self.show_treeview_popup_menu (treeview, event, event.button)

    def on_treemodel_row_changed (self, model, path, iter):
        self.on_treeview_cursor_changed (self.treeview)

    def on_treeview_cursor_changed (self, treeview):
        path, column = treeview.get_cursor ()
        cancel = self.job_ui_manager.get_action ("/cancel-job")
        hold = self.job_ui_manager.get_action ("/hold-job")
        release = self.job_ui_manager.get_action ("/release-job")
        reprint = self.job_ui_manager.get_action ("/reprint-job")
        authenticate = self.job_ui_manager.get_action ("/authenticate-job")
        if path == None:
            for widget in [cancel, hold, release, reprint, authenticate]:
                widget.set_sensitive (False)
            return

        iter = self.store.get_iter (path)
        self.jobid = self.store.get_value (iter, 0)
        job = self.jobs[self.jobid]
        authenticate.set_sensitive (False)
        for widget in [cancel, hold, release, reprint]:
            widget.set_sensitive (True)

        if job.has_key ('job-state'):
            s = job['job-state']
            if s >= cups.IPP_JOB_CANCELED:
                cancel.set_sensitive (False)
            if s != cups.IPP_JOB_PENDING:
                hold.set_sensitive (False)
            if s != cups.IPP_JOB_HELD:
                release.set_sensitive (False)
            if (not job.get('job-preserved', False)):
                reprint.set_sensitive (False)

        if job.get ('job-state', cups.IPP_JOB_CANCELED) == cups.IPP_JOB_HELD:
            if job.get ('job-hold-until', 'none') == 'auth-info-required':
                authenticate.set_sensitive (True)

    def show_treeview_popup_menu (self, treeview, event, event_button):
        # Right-clicked.
        self.job_context_menu.popup (None, None, None, event_button,
                                     event.get_time ())

    def on_icon_popupmenu(self, icon, button, time):
        self.statusicon_popupmenu.popup (None, None, None, button, time)

    def on_icon_hide_activate(self, menuitem):
        self.num_jobs_when_hidden = len (self.jobs.keys ())
        self.set_statusicon_visibility ()

    def on_icon_configure_printers_activate(self, menuitem):
        if self.loop:
            env = {}
            for name, value in os.environ.iteritems ():
                if name == "SYSTEM_CONFIG_PRINTER_GLADE":
                    continue
                env[name] = value
            p = subprocess.Popen ([ "system-config-printer" ],
                                  close_fds=True, env=env)
            gobject.timeout_add_seconds (10, self.poll_subprocess, p)

    def poll_subprocess(self, process):
        returncode = process.poll ()
        return returncode == None

    def on_icon_quit_activate (self, menuitem):
        if self.loop:
            self.loop.quit ()

    def on_job_cancel_activate(self, menuitem):
        dialog = gtk.Dialog (_("Cancel Job"), self.JobsWindow,
                             gtk.DIALOG_MODAL |
                             gtk.DIALOG_DESTROY_WITH_PARENT |
                             gtk.DIALOG_NO_SEPARATOR,
                             (gtk.STOCK_NO, gtk.RESPONSE_NO,
                              gtk.STOCK_YES, gtk.RESPONSE_YES))
        dialog.set_default_response (gtk.RESPONSE_NO)
        dialog.set_border_width (6)
        dialog.set_resizable (False)
        hbox = gtk.HBox (False, 12)
        image = gtk.Image ()
        image.set_from_stock (gtk.STOCK_DIALOG_QUESTION, gtk.ICON_SIZE_DIALOG)
        image.set_alignment (0.0, 0.0)
        hbox.pack_start (image, False, False, 0)
        label = gtk.Label (_("Do you really want to cancel this job?"))
        label.set_line_wrap (True)
        label.set_alignment (0.0, 0.0)
        hbox.pack_start (label, False, False, 0)
        dialog.vbox.pack_start (hbox, False, False, 0)
        dialog.set_data ('job-id', self.jobid)
        dialog.connect ("response", self.on_job_cancel_prompt_response)
        dialog.connect ("delete-event", self.on_job_cancel_prompt_delete)
        dialog.show_all ()

    def on_job_cancel_prompt_delete (self, dialog, event):
        self.on_job_cancel_prompt_response (dialog, gtk.RESPONSE_NO)

    def on_job_cancel_prompt_response (self, dialog, response):
        jobid = dialog.get_data ('job-id')
        dialog.destroy ()

        if response != gtk.RESPONSE_YES:
            return

        try:
            c = authconn.Connection (self.JobsWindow,
                                     host=self.host,
                                     port=self.port,
                                     encryption=self.encryption)
        except RuntimeError:
            return

        c._begin_operation (_("canceling job"))
        try:
            c.cancelJob (jobid)
        except cups.IPPError, (e, m):
            if (e != cups.IPP_NOT_POSSIBLE and
                e != cups.IPP_NOT_FOUND):
                self.show_IPP_Error (e, m)
            self.monitor.update ()
            c._end_operation ()
            return

        c._end_operation ()
        del c
        self.monitor.update ()

    def on_job_hold_activate(self, menuitem):
        try:
            c = authconn.Connection (self.JobsWindow,
                                     host=self.host,
                                     port=self.port,
                                     encryption=self.encryption)
        except RuntimeError:
            return

        c._begin_operation (_("holding job"))
        try:
            c.setJobHoldUntil (self.jobid, "indefinite")
        except cups.IPPError, (e, m):
            if (e != cups.IPP_NOT_POSSIBLE and
                e != cups.IPP_NOT_FOUND):
                self.show_IPP_Error (e, m)
            self.monitor.update ()
            c._end_operation ()
            return

        c._end_operation ()
        del c
        self.monitor.update ()

    def on_job_release_activate(self, menuitem):
        try:
            c = authconn.Connection (self.JobsWindow,
                                     host=self.host,
                                     port=self.port,
                                     encryption=self.encryption)
        except RuntimeError:
            return

        c._begin_operation (_("releasing job"))
        try:
            c.setJobHoldUntil (self.jobid, "no-hold")
        except cups.IPPError, (e, m):
            if (e != cups.IPP_NOT_POSSIBLE and
                e != cups.IPP_NOT_FOUND):
                self.show_IPP_Error (e, m)
            self.monitor.update ()
            c._end_operation ()
            return

        c._end_operation ()
        del c
        self.monitor.update ()

    def on_job_reprint_activate(self, menuitem):
        try:
            c = authconn.Connection (self.JobsWindow,
                                     host=self.host,
                                     port=self.port,
                                     encryption=self.encryption)
            c.restartJob (self.jobid)
            del c
        except cups.IPPError, (e, m):
            self.show_IPP_Error (e, m)
            self.monitor.update ()
            return
        except RuntimeError:
            return

        self.monitor.update ()

    def on_job_authenticate_activate(self, menuitem):
        self.display_auth_info_dialog (self.jobid)

    def on_refresh_activate(self, menuitem):
        self.monitor.refresh ()

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
                    theme = gtk.icon_theme_get_default ()
                    emblem = theme.load_icon (icon, 22, 0)
                    emblem.composite (pixbuf,
                                      pixbuf.get_width () / 2,
                                      pixbuf.get_height () / 2,
                                      emblem.get_width () / 2,
                                      emblem.get_height () / 2,
                                      pixbuf.get_width () / 2,
                                      pixbuf.get_height () / 2,
                                      0.5, 0.5,
                                      gtk.gdk.INTERP_BILINEAR, 255)
                except gobject.GError:
                    debugprint ("No %s icon available" % icon)

        return pixbuf

    def get_icon_pixbuf (self, have_jobs=None):
        if not self.trayicon:
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
        if not self.trayicon:
            return

        if tooltip == None:
            num_jobs = len (self.jobs)
            if num_jobs == 0:
                tooltip = _("No documents queued")
            elif num_jobs == 1:
                tooltip = _("1 document queued")
            else:
                tooltip = _("%d documents queued") % num_jobs

        self.statusicon.set_tooltip (tooltip)

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

        if self.worst_reason != None:
            (title, tooltip) = self.worst_reason.get_description ()
            if self.statusbar_set:
                self.statusbar.pop (0)
            self.statusbar.push (0, tooltip)
            self.statusbar_set = True
        else:
            tooltip = None
            if self.statusbar_set:
                self.statusbar.pop (0)
                self.statusbar_set = False

        if self.trayicon:
            pixbuf = self.get_icon_pixbuf (have_jobs=have_jobs)
            self.set_statusicon_from_pixbuf (pixbuf)
            self.set_statusicon_visibility ()
            self.set_statusicon_tooltip (tooltip=tooltip)

    ## Notifications
    def notify_printer_state_reason_if_important (self, reason):
        level = reason.get_level ()
        if level < StateReason.WARNING:
            # Not important enough to justify a notification.
            return

        self.notify_printer_state_reason (reason)

    def notify_printer_state_reason (self, reason):
        tuple = reason.get_tuple ()
        if self.state_reason_notifications.has_key (tuple):
            debugprint ("Already sent notification for %s" % repr (reason))
            return

        if reason.get_reason () == "com.apple.print.recoverable":
            return

        level = reason.get_level ()
        if (level == StateReason.ERROR or
            reason.get_reason () == "connecting-to-device"):
            urgency = pynotify.URGENCY_NORMAL
        else:
            urgency = pynotify.URGENCY_LOW

        (title, text) = reason.get_description ()
        notification = pynotify.Notification (title, text, 'printer')
        reason.user_notified = True
        notification.set_urgency (urgency)
        if "actions" in pynotify.get_server_caps():
            notification.set_timeout (pynotify.EXPIRES_NEVER)
        notification.connect ('closed',
                              self.on_state_reason_notification_closed)
        self.state_reason_notifications[reason.get_tuple ()] = notification
        self.set_statusicon_visibility ()
        notification.attach_to_status_icon (self.statusicon)
        try:
            notification.show ()
        except gobject.GError:
            nonfatalException ()

    def on_state_reason_notification_closed (self, notification, reason=None):
        debugprint ("Notification %s closed" % repr (notification))
        notification.set_data ('closed', True)
        self.set_statusicon_visibility ()
        return

    ## monitor.Watcher interface
    def current_printers_and_jobs (self, mon, printers, jobs):
        monitor.Watcher.current_printers_and_jobs (self, mon, printers, jobs)
        self.set_process_pending (False)
        self.store.clear ()
        self.jobs = {}
        self.jobiters = {}
        self.printer_uri_index = PrinterURIIndex (names=printers)
        connection = None
        for jobid, jobdata in jobs.iteritems ():
            uri = jobdata.get ('job-printer-uri', '')
            try:
                printer = self.printer_uri_index.lookup (uri,
                                                         connection=connection)
            except KeyError:
                printer = uri
            jobdata['job-printer-name'] = printer

            self.add_job (jobid, jobdata, connection=connection)

        self.jobs = jobs
        self.active_jobs = set()
        for jobid, jobdata in jobs.iteritems ():
            if self.job_is_active (jobdata):
                self.active_jobs.add (jobid)

        self.set_process_pending (True)
        self.update_status ()

    def job_added (self, mon, jobid, eventname, event, jobdata):
        monitor.Watcher.job_added (self, mon, jobid, eventname, event, jobdata)

        uri = jobdata.get ('job-printer-uri', '')
        try:
            printer = self.printer_uri_index.lookup (uri)
        except KeyError:
            printer = uri
        jobdata['job-printer-name'] = printer

        # We may be showing this job already, perhaps because we are showing
        # completed jobs and one was reprinted.
        if not self.jobiters.has_key (jobid):
            self.add_job (jobid, jobdata)

        if self.job_is_active (jobdata):
            self.active_jobs.add (jobid)
        elif jobid in self.active_jobs:
            self.active_jobs.remove (jobid)

        self.update_status (have_jobs=True)
        if self.trayicon:
            if not self.job_is_active (jobdata):
                return

            for reason in self.printer_state_reasons.get (printer, []):
                if not reason.user_notified:
                    self.notify_printer_state_reason_if_important (reason)

    def job_event (self, mon, jobid, eventname, event, jobdata):
        monitor.Watcher.job_event (self, mon, jobid, eventname, event, jobdata)

        uri = jobdata.get ('job-printer-uri', '')
        try:
            printer = self.printer_uri_index.lookup (uri)
        except KeyError:
            printer = uri
        jobdata['job-printer-name'] = printer

        if self.job_is_active (jobdata):
            self.active_jobs.add (jobid)
        elif jobid in self.active_jobs:
            self.active_jobs.remove (jobid)

        self.update_job (jobid, jobdata)
        self.update_status ()
        jobdata = self.jobs[jobid]

        # Look out for stopped jobs.
        if (self.trayicon and
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
                    message = _("There was a problem sending document `%s' "
                                "(job %d) to the printer.") % (document, jobid)
                elif notify_text.find ("filter errors") != -1:
                    message = _("There was a problem processing document `%s' "
                                "(job %d).") % (document, jobid)
                elif (notify_text.find ("being paused") != -1 or
                      jstate != cups.IPP_JOB_STOPPED):
                    may_be_problem = False
                else:
                    # Give up and use the provided message untranslated.
                    message = _("There was a problem printing document `%s' "
                                "(job %d): `%s'.") % (document, jobid,
                                                      notify_text)

            if may_be_problem:
                debugprint ("Problem detected")
                self.toggle_window_display (self.statusicon, force_show=True)
                dialog = gtk.Dialog (_("Print Error"), self.JobsWindow, 0,
                                     (_("_Diagnose"), gtk.RESPONSE_NO,
                                        gtk.STOCK_OK, gtk.RESPONSE_OK))
                dialog.set_default_response (gtk.RESPONSE_OK)
                dialog.set_border_width (6)
                dialog.set_resizable (False)
                dialog.set_icon_name (ICON)
                hbox = gtk.HBox (False, 12)
                hbox.set_border_width (6)
                image = gtk.Image ()
                image.set_from_stock (gtk.STOCK_DIALOG_ERROR,
                                      gtk.ICON_SIZE_DIALOG)
                hbox.pack_start (image, False, False, 0)
                vbox = gtk.VBox (False, 12)

                markup = ('<span weight="bold" size="larger">' +
                          _("Print Error") + '</span>\n\n' +
                          message)
                try:
                    if event['printer-state'] == cups.IPP_PRINTER_STOPPED:
                        name = event['printer-name']
                        markup += ' '
                        markup += (_("The printer called `%s' has "
                                     "been disabled.") % name)
                except KeyError:
                    pass

                label = gtk.Label (markup)
                label.set_use_markup (True)
                label.set_line_wrap (True)
                label.set_alignment (0, 0)
                vbox.pack_start (label, False, False, 0)
                hbox.pack_start (vbox, False, False, 0)
                dialog.vbox.pack_start (hbox)
                dialog.connect ('response',
                                self.print_error_dialog_response, jobid)
                self.stopped_job_prompts.add (jobid)
                dialog.show_all ()

    def job_removed (self, mon, jobid, eventname, event):
        monitor.Watcher.job_removed (self, mon, jobid, eventname, event)

        if self.jobiters.has_key (jobid):
            self.store.remove (self.jobiters[jobid])
            del self.jobiters[jobid]
            del self.jobs[jobid]

        if jobid in self.active_jobs:
            self.active_jobs.remove (jobid)

        self.update_status ()

    def state_reason_added (self, mon, reason):
        monitor.Watcher.state_reason_added (self, mon, reason)

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

        if not self.trayicon:
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
        monitor.Watcher.state_reason_removed (self, mon, reason)

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

        if not self.trayicon:
            return

        tuple = reason.get_tuple ()
        try:
            notification = self.state_reason_notifications[tuple]
            if notification.get_data ('closed') != True:
                try:
                    notification.close ()
                except glib.GError:
                    # Can fail if the notification wasn't even shown
                    # yet (as in bug #545733).
                    pass

            del self.state_reason_notifications[tuple]
            self.set_statusicon_visibility ()
        except KeyError:
            pass

    def still_connecting (self, mon, reason):
        monitor.Watcher.still_connecting (self, mon, reason)
        if not self.trayicon:
            return

        self.notify_printer_state_reason (reason)

    def now_connected (self, mon, printer):
        monitor.Watcher.now_connected (self, mon, printer)

        if not self.trayicon:
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
            for (level,
                 p,
                 r) in self.state_reason_notifications.keys ():
                if p == printer and r == "connecting-to-device":
                    debugprint ("Found from notifications list")
                    tuple = (level, p, r)
                    break

        try:
            notification = self.state_reason_notifications[tuple]
        except KeyError:
            debugprint ("Unexpected now_connected signal")
            return

        if notification.get_data ('closed') != True:
            notification.close ()
            notification.set_data ('closed', True)

    def printer_event (self, mon, printer, eventname, event):
        monitor.Watcher.printer_event (self, mon, printer, eventname, event)
        self.printer_uri_index.update_from_attrs (printer, event)

    def printer_removed (self, mon, printer):
        monitor.Watcher.printer_removed (self, mon, printer)
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
        cell.set_property("text", self.jobs[jobid]['job-printer-name'])

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
                        state = _("Held until %s") % time.strftime ("%X", local)
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
            theme = gtk.icon_theme_get_default ()
            emblem = theme.load_icon (gtk.STOCK_MEDIA_PAUSE, 22 / 2, 0)
            copy = icon.copy ()
            emblem.composite (copy, 0, 0,
                              copy.get_width (),
                              copy.get_height (),
                              copy.get_width () / 2 - 1,
                              copy.get_height () / 2 - 1,
                              1.0, 1.0,
                              gtk.gdk.INTERP_NEAREST, 255)
            icon = copy
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

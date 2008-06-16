#!/usr/bin/env python

## Copyright (C) 2007, 2008 Tim Waugh <twaugh@redhat.com>
## Copyright (C) 2007, 2008 Red Hat, Inc.

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
import monitor
import os
import pango
import sys
import time

from debug import *
import config
import statereason
import errordialogs
import pprint

from gettext import gettext as _
DOMAIN="system-config-printer"
gettext.textdomain (DOMAIN)
gtk.glade.bindtextdomain (DOMAIN)
from statereason import StateReason
statereason.set_gettext_function (_)
errordialogs.set_gettext_function (_)

pkgdata = config.Paths ().get_path ('pkgdatadir')
GLADE="applet.glade"
ICON="printer"
SEARCHING_ICON="document-print-preview"

class JobViewer (monitor.Watcher):
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
        self.which_jobs = "not-completed"
        self.printer_state_reasons = {}
        self.num_jobs_when_hidden = 0
        self.connecting_to_device = {} # dict of printer->time first seen
        self.state_reason_notifications = {}
        self.job_creation_times_timer = None
        self.special_status_icon = False
        self.new_printer_notifications = {}
        self.reasoniters = {}
        self.auth_info_dialog = None

        glade_dir = os.environ.get ("SYSTEM_CONFIG_PRINTER_GLADE",
                                    pkgdata)
        xml = os.path.join (glade_dir, 'applet.glade')
        self.xml = gtk.glade.XML (xml, domain = DOMAIN)
        self.xml.signal_autoconnect(self)
        self.treeview = self.xml.get_widget ('treeview')
        text=0
        for name in [_("Job"),
                     _("User"),
                     _("Document"),
                     _("Printer"),
                     _("Size"),
                     _("Time submitted"),
                     _("Status")]:
            if text == 1 and trayicon:
                # Skip the user column for the trayicon.
                text += 1
                continue
            cell = gtk.CellRendererText()
            if text == 2 or text == 3:
                # Ellipsize the 'Document' and 'Printer' columns.
                cell.set_property ("ellipsize", pango.ELLIPSIZE_END)
                cell.set_property ("width-chars", 20)
            column = gtk.TreeViewColumn(name, cell, text=text)
            column.set_resizable(True)
            self.treeview.append_column(column)
            text += 1

        self.treeview.get_selection().set_mode(gtk.SELECTION_SINGLE)
        self.store = gtk.TreeStore(int, str, str, str, str, str, str)
        self.store.set_sort_column_id (0, gtk.SORT_DESCENDING)
        self.treeview.set_model(self.store)
        self.treeview.set_rules_hint (True)
        self.treeview.connect ('button_release_event',
                               self.on_treeview_button_release_event)
        self.treeview.connect ('popup-menu', self.on_treeview_popup_menu)

        self.MainWindow = self.xml.get_widget ('MainWindow')
        self.MainWindow.set_icon_name (ICON)
        self.MainWindow.hide ()

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
        self.MainWindow.set_title (_("Document Print Status (%s)") % title)

        if parent:
            self.MainWindow.set_transient_for (parent)

        self.statusbar = self.xml.get_widget ('statusbar')
        self.statusbar_set = False

        self.job_popupmenu = self.xml.get_widget ('job_popupmenu')
        self.icon_popupmenu = self.xml.get_widget ('icon_popupmenu')
        self.cancel = self.xml.get_widget ('cancel')
        self.hold = self.xml.get_widget ('hold')
        self.release = self.xml.get_widget ('release')
        self.reprint = self.xml.get_widget ('reprint')

        self.show_printer_status = self.xml.get_widget ('show_printer_status')
        self.PrintersWindow = self.xml.get_widget ('PrintersWindow')
        self.PrintersWindow.set_icon_name (ICON)
        self.PrintersWindow.hide ()
        self.treeview_printers = self.xml.get_widget ('treeview_printers')
        column = gtk.TreeViewColumn(_("Printer"))
        icon = gtk.CellRendererPixbuf()
        column.pack_start (icon, False)
        text = gtk.CellRendererText()
        column.set_resizable(True)
        column.pack_start (text, False)
        column.set_cell_data_func (icon, self.set_printer_status_icon)
        column.set_cell_data_func (text, self.set_printer_status_name)
        column.set_resizable (True)
        column.set_sort_column_id (1)
        column.set_sort_order (gtk.SORT_ASCENDING)
        self.treeview_printers.append_column(column)
        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn(_("Message"), cell, text=2)
        column.set_resizable(True)
        cell.set_property ("ellipsize", pango.ELLIPSIZE_END)
        self.treeview_printers.append_column(column)

        self.treeview_printers.get_selection().set_mode(gtk.SELECTION_NONE)
        self.store_printers = gtk.TreeStore (int, str, str)
        self.treeview_printers.set_model(self.store_printers)

        if self.trayicon:
            self.statusicon = gtk.StatusIcon ()
            theme = gtk.icon_theme_get_default ()
            pixbuf = theme.load_icon (ICON, 22, 0)
            self.statusicon.set_from_pixbuf (pixbuf)
            self.icon_jobs = self.statusicon.get_pixbuf ()
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
            self.set_statusicon_from_pixbuf (self.icon_no_jobs)
            self.statusicon.connect ('activate', self.toggle_window_display)
            self.statusicon.connect ('popup-menu', self.on_icon_popupmenu)
            self.statusicon.set_visible (False)

        # D-Bus
        if bus == None:
            bus = dbus.SystemBus ()

        self.monitor = monitor.Monitor (self, bus=bus, my_jobs=my_jobs,
                                        specific_dests=specific_dests)

        if not self.trayicon:
            self.MainWindow.show ()

    def cleanup (self):
        self.monitor.cleanup ()
        if self.exit_handler:
            self.exit_handler (self)

    # Handle "special" status icon
    def set_special_statusicon (self, iconname):
        self.special_status_icon = True
        self.statusicon.set_from_icon_name (iconname)
        self.set_statusicon_visibility ()

    def unset_special_statusicon (self):
        self.special_status_icon = False
        self.statusicon.set_from_pixbuf (self.saved_statusicon_pixbuf)

    def notify_new_printer (self, printer, notification):
        self.new_printer_notifications[printer] = notification
        notification.set_data ('printer-name', printer)
        notification.connect ('closed', self.on_new_printer_notification_closed)
        self.set_statusicon_visibility ()
        # Let the icon show itself, ready for the notification
        while gtk.events_pending ():
            gtk.main_iteration ()
        notification.attach_to_status_icon (self.statusicon)
        notification.show ()

    def on_new_printer_notification_closed (self, notification):
        printer = notification.get_data ('printer-name')
        del self.new_printer_notifications[printer]
        self.set_statusicon_visibility ()

    def set_statusicon_from_pixbuf (self, pb):
        self.saved_statusicon_pixbuf = pb
        if not self.special_status_icon:
            self.statusicon.set_from_pixbuf (pb)

    def on_delete_event(self, *args):
        if self.trayicon or not self.loop:
            self.MainWindow.hide ()
            if self.show_printer_status.get_active ():
                self.PrintersWindow.hide ()

            if not self.loop:
                # Being run from main app, not applet
                self.cleanup ()
        else:
            self.loop.quit ()
        return True

    def on_printer_status_delete_event(self, *args):
        self.show_printer_status.set_active (False)
        self.PrintersWindow.hide()
        return True

    def show_IPP_Error(self, exception, message):
        return errordialogs.show_IPP_Error (exception, message, self.MainWindow)

    def toggle_window_display(self, icon, force_show=False):
        visible = self.MainWindow.get_property('visible')
        if force_show:
            visible = False

        if visible:
            self.MainWindow.hide()
            if self.show_printer_status.get_active ():
                self.PrintersWindow.hide()
        else:
            self.MainWindow.show()
            if self.show_printer_status.get_active ():
                self.PrintersWindow.show()

    def on_show_completed_jobs_activate(self, menuitem):
        if menuitem.get_active():
            self.monitor.which_jobs = "all"
        else:
            self.monitor.which_jobs = "not-completed"
        self.monitor.refresh()

    def on_show_printer_status_activate(self, menuitem):
        if self.show_printer_status.get_active ():
            self.PrintersWindow.show()
        else:
            self.PrintersWindow.hide()

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
                if ago > 86400:
                    t = time.ctime (created)
                elif ago > 3600:
                    need_update = True
                    hours = int (ago / 3600)
                    mins = int ((ago % 3600) / 60)
                    if hours == 1:
                        if mins == 0:
                            t = _("1 hour ago")
                        elif mins == 1:
                            t = _("1 hour and 1 minute ago")
                        else:
                            t = _("1 hour and %d minutes ago") % mins
                    else:
                        if mins == 0:
                            t = _("%d hours ago") % hours
                        elif mins == 1:
                            t = _("%d hours and 1 minute ago") % hours
                        else:
                            t = _("%d hours and %d minutes ago") % \
                                (hours, mins)
                else:
                    need_update = True
                    mins = ago / 60
                    if mins < 2:
                        t = _("a minute ago")
                    else:
                        t = _("%d minutes ago") % mins

            self.store.set_value (iter, 5, t)

        if need_update and not self.job_creation_times_timer:
            t = gobject.timeout_add (60 * 1000, self.update_job_creation_times)
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

    def add_job (self, job, data):
        store = self.store
        iter = self.store.append (None)
        store.set_value (iter, 0, job)
        store.set_value (iter, 1, data.get('job-originating-user-name',
                                           _("Unknown")))
        store.set_value (iter, 2, data.get('job-name', _("Unknown")))
        self.jobiters[job] = iter
        self.update_job (job, data)
        self.update_job_creation_times ()

    def update_job (self, job, data):
        store = self.store
        iter = self.jobiters[job]
        self.jobs[job] = data

        printer = data['job-printer-name']
        store.set_value (iter, 3, printer)

        size = _("Unknown")
        if data.has_key ('job-k-octets'):
            size = str (data['job-k-octets']) + 'k'
        store.set_value (iter, 4, size)

        state = None
        if data.has_key ('job-state'):
            try:
                jstate = data['job-state']
                s = int (jstate)
                state = { cups.IPP_JOB_PENDING: _("Pending"),
                          cups.IPP_JOB_HELD: _("Held"),
                          cups.IPP_JOB_PROCESSING: _("Processing"),
                          cups.IPP_JOB_STOPPED: _("Stopped"),
                          cups.IPP_JOB_CANCELED: _("Canceled"),
                          cups.IPP_JOB_ABORTED: _("Aborted"),
                          cups.IPP_JOB_COMPLETED: _("Completed") }[s]
            except ValueError:
                pass
            except IndexError:
                pass

        if state == None:
            state = _("Unknown")
        store.set_value (iter, 6, state)

        # Check whether authentication is required.
        if (self.trayicon and
            data['job-state'] == cups.IPP_JOB_HELD and
            data.get ('job-hold-until', 'none') == 'auth-info-required' and
            not self.auth_info_dialog):
            try:
                cups.require ("1.9.37")
            except:
                debugprint ("Authentication required but "
                            "authenticateJob() not available")
                return

            # Find out which auth-info is required.
            try:
                c = authconn.Connection (self.MainWindow)
                try:
                    uri = data['job-printer-uri']
                    attributes = c.getPrinterAttributes (uri = uri)
                except TypeError: # uri keyword introduced in pycups-1.9.32
                    debugprint ("Fetching printer attributes by name")
                    attributes = c.getPrinterAttributes (printer)
            except cups.IPPError, (e, m):
                self.show_IPP_Error (e, m)
                return
            except RuntimeError:
                debugprint ("Failed to connect when fetching printer attrs")
                return

            try:
                auth_info_required = attributes['auth-info-required']
            except KeyError:
                debugprint ("No auth-info-required attribute; guessing instead")
                auth_info_required = ['username', 'password']

            if not isinstance (auth_info_required, list):
                auth_info_required = [auth_info_required]

            if auth_info_required == ['negotiate']:
                # Try Kerberos authentication.
                try:
                    debugprint ("Trying Kerberos auth for job %d" % jobid)
                    c.authenticateJob (jobid)
                except TypeError:
                    # Requires pycups-1.9.39 for optional auth parameter.
                    # Treat this as a normal job error.
                    debugprint ("... need newer pycups for that")
                    return
                except cups.IPPError, (e, m):
                    self.show_IPP_Error (e, m)
                    return

            dialog = authconn.AuthDialog (auth_info_required=auth_info_required)
            dialog.set_prompt (_("Authentication required for "
                                 "printing document `%s' (job %d)") %
                               (data.get('job-name', _("Unknown")), job))
            self.auth_info_dialog = dialog
            dialog.connect ('response', self.auth_info_dialog_response)
            dialog.set_data ('job-id', job)
            dialog.show_all ()

    def auth_info_dialog_response (self, dialog, response):
        dialog.hide ()
        self.auth_info_dialog = None
        if response != gtk.RESPONSE_OK:
            return

        auth_info = dialog.get_auth_info ()
        jobid = dialog.get_data ('job-id')
        try:
            c = authconn.Connection (self.MainWindow)
            c.authenticateJob (jobid, auth_info)
        except RuntimeError:
            debugprint ("Error connecting to CUPS for authentication")
        except cups.IPPError, (e, m):
            self.show_IPP_Error (e, m)
            pass

    def set_statusicon_visibility (self):
        if not self.trayicon:
            return

        if self.suppress_icon_hide:
            # Avoid hiding the icon if we've been woken up to notify
            # about a new printer.
            self.suppress_icon_hide = False
            return

        open_notifications = len (self.new_printer_notifications.keys ())
        open_notifications += len (self.state_reason_notifications.keys ())
        num_jobs = len (self.jobs.keys ())

        debugprint ("open notifications: %d" % open_notifications)
        debugprint ("num_jobs: %d" % num_jobs)
        debugprint ("num_jobs_when_hidden: %d" % self.num_jobs_when_hidden)

        self.statusicon.set_visible (self.special_status_icon or
                                     open_notifications > 0 or
                                     num_jobs > self.num_jobs_when_hidden)

    def on_treeview_popup_menu (self, treeview):
        event = gtk.gdk.Event (gtk.gdk.NOTHING)
        self.show_treeview_popup_menu (treeview, event, 0)

    def on_treeview_button_release_event(self, treeview, event):
        if event.button == 3:
            self.show_treeview_popup_menu (treeview, event, event.button)

    def show_treeview_popup_menu (self, treeview, event, event_button):
        # Right-clicked.
        store, iter = treeview.get_selection ().get_selected ()
        if iter == None:
            return

        self.jobid = self.store.get_value (iter, 0)
        job = self.jobs[self.jobid]
        self.cancel.set_sensitive (True)
        self.hold.set_sensitive (True)
        self.release.set_sensitive (True)
        self.reprint.set_sensitive (True)
        if job.has_key ('job-state'):
            s = job['job-state']
            if s >= cups.IPP_JOB_CANCELED:
                self.cancel.set_sensitive (False)
            if s != cups.IPP_JOB_PENDING:
                self.hold.set_sensitive (False)
            if s != cups.IPP_JOB_HELD:
                self.release.set_sensitive (False)
            if (not job.get('job-preserved', False)):
                self.reprint.set_sensitive (False)
        self.job_popupmenu.popup (None, None, None, event_button,
                                  event.get_time ())

    def on_icon_popupmenu(self, icon, button, time):
        self.icon_popupmenu.popup (None, None, None, button, time)

    def on_icon_hide_activate(self, menuitem):
        self.num_jobs_when_hidden = len (self.jobs.keys ())
        self.set_statusicon_visibility ()

    def on_icon_quit_activate (self, menuitem):
        if self.loop:
            self.loop.quit ()

    def on_job_cancel_activate(self, menuitem):
        try:
            c = authconn.Connection (self.MainWindow)
            c.cancelJob (self.jobid)
            del c
        except cups.IPPError, (e, m):
            self.show_IPP_Error (e, m)
            return
        except RuntimeError:
            return

    def on_job_hold_activate(self, menuitem):
        try:
            c = authconn.Connection (self.MainWindow)
            c.setJobHoldUntil (self.jobid, "indefinite")
            del c
        except cups.IPPError, (e, m):
            self.show_IPP_Error (e, m)
            return
        except RuntimeError:
            return

    def on_job_release_activate(self, menuitem):
        try:
            c = authconn.Connection (self.MainWindow)
            c.setJobHoldUntil (self.jobid, "no-hold")
            del c
        except cups.IPPError, (e, m):
            self.show_IPP_Error (e, m)
            return
        except RuntimeError:
            return

    def on_job_reprint_activate(self, menuitem):
        try:
            c = authconn.Connection (self.MainWindow)
            c.restartJob (self.jobid)
            del c
        except cups.IPPError, (e, m):
            self.show_IPP_Error (e, m)
            return
        except RuntimeError:
            return

    def on_refresh_activate(self, menuitem):
        self.monitor.refresh ()

    def job_is_active (self, jobdata):
        state = jobdata.get ('job-state', cups.IPP_JOB_CANCELED)
        if state >= cups.IPP_JOB_CANCELED:
            return False

        return True

    ## Icon manipulation
    def add_state_reason_emblem (self, pixbuf):
        if self.worst_reason != None:
            # Check that it's valid.
            printer = self.worst_reason.get_printer ()
            found = False
            for reason in self.printer_state_reasons[printer]:
                if reason == self.worst_reason:
                    found = True
                    break
            if not found:
                self.worst_reason = None

        if self.worst_reason != None:
            level = self.worst_reason.get_level ()
            if level > StateReason.REPORT:
                # Add an emblem to the icon.
                icon = StateReason.LEVEL_ICON[level]
                pixbuf = pixbuf.copy ()
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

        return pixbuf

    def get_icon_pixbuf (self, have_jobs=None):
        if not self.trayicon:
            return

        if have_jobs == None:
            have_jobs = len (self.jobs.keys ()) > 0

        if have_jobs:
            pixbuf = self.icon_jobs
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

        level = reason.get_level ()
        if (level == StateReason.ERROR or
            reason.get_reason () == "connecting-to-device"):
            urgency = pynotify.URGENCY_NORMAL
        else:
            urgency = pynotify.URGENCY_LOW

        (title, text) = reason.get_description ()
        notification = pynotify.Notification (title, text, 'printer')
        reason.user_notified = True
        notification.set_data ('printer-state-reason', reason)
        notification.set_urgency (urgency)
        notification.set_timeout (pynotify.EXPIRES_NEVER)
        notification.connect ('closed',
                              self.on_state_reason_notification_closed)
        self.state_reason_notifications[reason.get_tuple ()] = notification
        self.set_statusicon_visibility ()
        # Let the icon show itself, ready for the notification
        while gtk.events_pending ():
            gtk.main_iteration ()
        notification.attach_to_status_icon (self.statusicon)
        notification.show ()

    def on_state_reason_notification_closed (self, notification):
        debugprint ("Notification %s closed" % repr (notification))
        reason = notification.get_data ('printer-state-reason')
        tuple = reason.get_tuple ()
        if self.state_reason_notifications[tuple] == notification:
            del self.state_reason_notifications[tuple]
            self.set_statusicon_visibility ()
            return

        debugprint ("Unable to find closed notification")

    ## monitor.Watcher interface
    def current_printers_and_jobs (self, mon, printers, jobs):
        self.store.clear ()
        self.jobiters = {}
        for jobid, jobdata in jobs.iteritems ():
            uri = jobdata.get ('job-printer-uri', '')
            i = uri.rfind ('/')
            if i != -1:
                printer = uri[i + 1:]
            else:
                printer = _("Unknown")
            jobdata['job-printer-name'] = printer

            self.add_job (jobid, jobdata)

            # Fetch complete attributes for these jobs.
            attrs = None
            try:
                c = cups.Connection ()
                attrs = c.getJobAttributes (jobid)
            except RuntimeError:
                pass
            except AttributeError:
                pass

            if attrs:
                jobdata.update (attrs)
                self.update_job (jobid, jobdata)

        self.jobs = jobs
        self.active_jobs = set()
        for jobid, jobdata in jobs.iteritems ():
            if self.job_is_active (jobdata):
                self.active_jobs.add (jobid)

        self.update_status ()

    def job_added (self, mon, jobid, eventname, event, jobdata):
        monitor.Watcher.job_added (self, mon, jobid, eventname, event, jobdata)

        uri = jobdata.get ('job-printer-uri', '')
        i = uri.rfind ('/')
        if i != -1:
            printer = uri[i + 1:]
        else:
            printer = _("Unknown")
        jobdata['job-printer-name'] = printer

        # We may be showing this job already, perhaps because we are showing
        # completed jobs and one was reprinted.
        if not self.jobiters.has_key (jobid):
            self.add_job (jobid, jobdata)

        self.active_jobs.add (jobid)
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
        i = uri.rfind ('/')
        if i != -1:
            printer = uri[i + 1:]
        else:
            printer = _("Unknown")
        jobdata['job-printer-name'] = printer

        if self.job_is_active (jobdata):
            self.active_jobs.add (jobid)
        elif jobid in self.active_jobs:
            self.active_jobs.remove (jobid)

        # Look out for stopped jobs.
        if (self.trayicon and eventname == 'job-stopped' and
            not jobid in self.stopped_job_prompts):
            # Why has the job stopped?  It might be due to a job error
            # of some sort, or it might be that the backend requires
            # authentication.  If the latter, the job will be held not
            # stopped, and the job-hold-until attribute will be
            # 'auth-info-required'.  This will be checked for in
            # update_job.
            if jobdata['job-state'] == cups.IPP_JOB_HELD:
                try:
                    # Fetch the job-hold-until attribute, as this is
                    # not provided in the notification attributes.
                    c = cups.Connection ()
                    attrs = c.getJobAttributes (jobid)
                    jobdata.update (attrs)
                except cups.IPPError:
                    pass
                except RuntimeError:
                    pass

            may_be_problem = True
            if (jobdata['job-state'] == cups.IPP_JOB_HELD and
                jobdata['job-hold-until'] == 'auth-info-required'):
                # Leave this to update_job to deal with.
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
                elif notify_text.find ("being paused") != -1:
                    may_be_problem = False
                else:
                    # Give up and use the provided message untranslated.
                    message = _("There was a problem printing document `%s' "
                                "(job %d): `%s'.") % (document, jobid,
                                                      notify_text)

            if may_be_problem:
                self.toggle_window_display (self.statusicon, force_show=True)
                dialog = gtk.Dialog (_("Print Error"), self.MainWindow, 0,
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

        self.update_job (jobid, jobdata)

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
        iter = self.store_printers.append (None)
        self.store_printers.set_value (iter, 0, reason.get_level ())
        self.store_printers.set_value (iter, 1, printer)
        self.store_printers.set_value (iter, 2, text)
        self.reasoniters[reason.get_tuple ()] = iter

        try:
            l = self.printer_state_reasons[printer]
        except KeyError:
            l = []
            self.printer_state_reasons[printer] = l

        reason.user_notified = False
        l.append (reason)
        self.update_status ()

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

        try:
            iter = self.reasoniters[reason.get_tuple ()]
            self.store_printers.remove (iter)
        except KeyError:
            debugprint ("Reason iter not found")

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

        if not self.trayicon:
            return

        tuple = reason.get_tuple ()
        try:
            notification = self.state_reason_notifications[tuple]
            notification.close ()
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

        notification.close ()

    ## Printer status window
    def set_printer_status_icon (self, column, cell, model, iter, *user_data):
        level = model.get_value (iter, 0)
        icon = StateReason.LEVEL_ICON[level]
        theme = gtk.icon_theme_get_default ()
        try:
            pixbuf = theme.load_icon (icon, 22, 0)
            cell.set_property("pixbuf", pixbuf)
        except gobject.GError, exc:
            pass # Couldn't load icon

    def set_printer_status_name (self, column, cell, model, iter, *user_data):
        cell.set_property("text", model.get_value (iter, 1))

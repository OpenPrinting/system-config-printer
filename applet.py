#!/usr/bin/env python

## Copyright (C) 2007 Tim Waugh <twaugh@redhat.com>
## Copyright (C) 2007 Red Hat, Inc.

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

import cups
import sys

APPDIR="/usr/share/system-config-printer"
DOMAIN="system-config-printer"
GLADE="applet.glade"
ICON="applet.png"

CONNECTING_TIMEOUT = 60 # seconds
MIN_REFRESH_INTERVAL = 1 # seconds

class StateReason:
    REPORT=1
    WARNING=2
    ERROR=3

    LEVEL_FILE={
        REPORT: "/usr/share/icons/gnome/22x22/status/info.png",
        WARNING: "/usr/share/icons/gnome/22x22/status/important.png",
        ERROR: "/usr/share/icons/gnome/22x22/status/error.png"
        }

    def __init__(self, printer, reason):
        self.printer = printer
        self.reason = reason
        self.level = None
        self.canonical_reason = None

    def get_printer (self):
        return self.printer

    def get_level (self):
        if self.level != None:
            return self.level

        if (self.reason.endswith ("-report") or
            self.reason == "connecting-to-device"):
            self.level = self.REPORT
        elif self.reason.endswith ("-warning"):
            self.level = self.WARNING
        else:
            self.level = self.ERROR
        return self.level

    def get_reason (self):
        if self.canonical_reason:
            return self.canonical_reason

        level = self.get_level ()
        reason = self.reason
        if level == self.WARNING and reason.endswith ("-warning"):
            reason = reason[:-8]
        elif level == self.ERROR and reason.endswith ("-error"):
            reason = reason[:-6]
        self.canonical_reason = reason
        return self.canonical_reason

    def get_description (self):
        messages = {
            'toner-low': (_("Toner low"),
                          _("Printer '%s' is low on toner.")),
            'toner-empty': (_("Toner empty"),
                            _("Printer '%s' has no toner left.")),
            'cover-open': (_("Cover open"),
                           _("The cover is open on printer '%s'.")),
            'door-open': (_("Door open"),
                          _("The door is open on printer '%s'.")),
            'media-low': (_("Paper low"),
                          _("Printer '%s' is low on paper.")),
            'media-empty': (_("Out of paper"),
                            _("Printer '%s' is out of paper.")),
            'marker-supply-low': (_("Ink low"),
                                  _("Printer '%s' is low on ink.")),
            'marker-supply-empty': (_("Ink empty"),
                                    _("Printer '%s' has no ink left.")),
            'connecting-to-device': (_("Not connected?"),
                                     _("Printer '%s' may not be connected.")),
            }
        try:
            (title, text) = messages[self.get_reason ()]
            text = text % self.get_printer ()
        except KeyError:
            if self.get_level () == self.REPORT:
                title = _("Printer report")
            elif self.get_level () == self.WARNING:
                title = _("Printer warning")
            elif self.get_level () == self.ERROR:
                title = _("Printer error")
            text = _("Printer '%s': '%s'.") % (self.get_printer (),
                                               self.get_reason ())
        return (title, text)

    def get_tuple (self):
        return (self.get_level (), self.get_printer (), self.get_reason ())

    def __cmp__(self, other):
        if other == None:
            return 1
        if other.get_level () != self.get_level ():
            return int.__cmp__ (self.get_level (), other.get_level ())
        if other.printer () != self.printer ():
            return str.__cmp__ (other.get_printer (), self.get_printer ())
        return str.__cmp__ (other.get_reason (), self.get_reason ())

def collect_printer_state_reasons (connection):
    result = []
    printers = connection.getPrinters ()
    for name, printer in printers.iteritems ():
        reasons = printer["printer-state-reasons"]
        if type (reasons) == str:
            # Work around a bug that was fixed in pycups-1.9.20.
            reasons = [reasons]
        for reason in reasons:
            if reason == "none":
                break
            if (reason.startswith ("moving-to-paused") or
                reason.startswith ("paused") or
                reason.startswith ("shutdown") or
                reason.startswith ("stopping") or
                reason.startswith ("stopped-partly")):
                continue
            result.append (StateReason (name, reason))
    return result

def worst_printer_state_reason (connection, printer_reasons=None):
    """Fetches the printer list and checks printer-state-reason for
    each printer, returning a StateReason for the most severe
    printer-state-reason, or None."""
    worst_reason = None
    if printer_reasons == None:
        printer_reasons = collect_printer_state_reasons (connection)
    for reason in printer_reasons:
        if worst_reason == None:
            worst_reason = reason
            continue
        if reason > worst_reason:
            worst_reason = reason

    return worst_reason

class JobManager:
    def __init__(self, bus, loop, service_running=False, trayicon=True):
        self.loop = loop
        self.service_running = service_running
        self.trayicon = trayicon

        self.jobs = {}
        self.jobiters = {}
        self.which_jobs = "not-completed"
        self.hidden = False
        self.connecting_to_device = {} # dict of printer->time first seen
        self.still_connecting = set()
        self.will_update_job_creation_times = False # whether timeout is set
        self.will_refresh = False # whether timeout is set
        self.last_refreshed = 0
        self.special_status_icon = False

        self.xml = gtk.glade.XML(APPDIR + "/" + GLADE)
        self.xml.signal_autoconnect(self)
        self.treeview = self.xml.get_widget ('treeview')
        text=0
        for name in [_("Job"),
                     _("Document"),
                     _("Printer"),
                     _("Size"),
                     _("Time submitted"),
                     _("Status")]:
            cell = gtk.CellRendererText()
            if text == 1 or text == 2:
                # Ellipsize the 'Document' and 'Printer' columns.
                cell.set_property ("ellipsize", pango.ELLIPSIZE_END)
                cell.set_property ("width-chars", 20)
            column = gtk.TreeViewColumn(name, cell, text=text)
            column.set_resizable(True)
            self.treeview.append_column(column)
            text += 1

        self.treeview.get_selection().set_mode(gtk.SELECTION_SINGLE)
        self.store = gtk.TreeStore(int, str, str, str, str, str)
        self.store.set_sort_column_id (0, gtk.SORT_DESCENDING)
        self.treeview.set_model(self.store)
        self.treeview.set_rules_hint (True)

        self.MainWindow = self.xml.get_widget ('MainWindow')
        self.MainWindow.set_icon_from_file (APPDIR + "/" + ICON)
        self.MainWindow.hide ()

        self.statusbar = self.xml.get_widget ('statusbar')
        self.statusbar_set = False
        self.reasons_seen = {}

        self.job_popupmenu = self.xml.get_widget ('job_popupmenu')
        self.icon_popupmenu = self.xml.get_widget ('icon_popupmenu')
        self.cancel = self.xml.get_widget ('cancel')
        self.hold = self.xml.get_widget ('hold')
        self.release = self.xml.get_widget ('release')
        self.reprint = self.xml.get_widget ('reprint')

        self.show_printer_status = self.xml.get_widget ('show_printer_status')
        self.PrintersWindow = self.xml.get_widget ('PrintersWindow')
        self.PrintersWindow.set_icon_from_file (APPDIR + "/" + ICON)
        self.PrintersWindow.hide ()
        self.treeview_printers = self.xml.get_widget ('treeview_printers')
        column = gtk.TreeViewColumn(_("Printer"))
        icon = gtk.CellRendererPixbuf()
        column.pack_start (icon, False)
        text = gtk.CellRendererText()
        text.set_property ("ellipsize", pango.ELLIPSIZE_END)
        text.set_property ("width-chars", 10)
        column.pack_start (text, False)
        column.set_cell_data_func (icon, self.set_printer_status_icon)
        column.set_cell_data_func (text, self.set_printer_status_name)
        column.set_resizable (True)
        column.set_sort_column_id (1)
        column.set_sort_order (gtk.SORT_ASCENDING)
        self.treeview_printers.append_column(column)
        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn(_("Message"), cell, text=2)
        cell.set_property ("ellipsize", pango.ELLIPSIZE_END)
        cell.set_property ("width-chars", 35)
        self.treeview_printers.append_column(column)

        self.treeview_printers.get_selection().set_mode(gtk.SELECTION_NONE)
        self.store_printers = gtk.TreeStore (int, str, str)
        self.treeview_printers.set_model(self.store_printers)

        self.lblPasswordPrompt = self.xml.get_widget('lblPasswordPrompt')
        self.PasswordDialog = self.xml.get_widget('PasswordDialog')
        self.entPasswd = self.xml.get_widget('entPasswd')
        self.prompt_primary = self.lblPasswordPrompt.get_label ()
        self.lblError = self.xml.get_widget('lblError')
        self.ErrorDialog = self.xml.get_widget('ErrorDialog')

        cups.setPasswordCB(self.cupsPasswdCallback)

        # D-Bus
        bus.add_signal_receiver (self.handle_dbus_signal,
                                 path="/com/redhat/PrinterSpooler",
                                 dbus_interface="com.redhat.PrinterSpooler")

        if self.trayicon:
            self.statusicon = gtk.StatusIcon ()
            self.statusicon.set_from_file (APPDIR + "/" + ICON)
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

            # We need the statusicon to actually get placed on the screen
            # in case refresh() wants to attach a notification to it.
            while gtk.events_pending ():
                gtk.main_iteration ()

            self.notify = None
            self.notified_reason = None

            if not pynotify.init (PROGRAM_NAME):
                print >> sys.stderr, ("%s: unable to initialize pynotify" %
                                      PROGRAM_NAME)

        self.refresh ()

        if not self.trayicon:
            self.MainWindow.show ()

    # Handle "special" status icon
    def set_special_statusicon (self, filename):
        self.special_status_icon = True
        self.statusicon.set_from_file (filename)

    def unset_special_statusicon (self):
        self.special_status_icon = False
        self.statusicon.set_from_pixbuf (self.saved_statusicon_pixbuf)

    def set_statusicon_from_pixbuf (self, pb):
        self.saved_statusicon_pixbuf = pb
        if not self.special_status_icon:
            self.statusicon.set_from_pixbuf (pb)

    def on_delete_event(self, *args):
        if self.trayicon:
            self.MainWindow.hide ()
            if self.show_printer_status.get_active ():
                self.PrintersWindow.hide ()
        else:
            self.loop.quit ()
        return True

    def on_printer_status_delete_event(self, *args):
        self.show_printer_status.set_active (False)
        self.PrintersWindow.hide()
        return True

    def cupsPasswdCallback(self, querystring):
        self.lblPasswordPrompt.set_label (self.prompt_primary + querystring)
        self.PasswordDialog.set_transient_for (self.MainWindow)
        self.entPasswd.grab_focus ()
        result = self.PasswordDialog.run()
        self.PasswordDialog.hide()
        if result == gtk.RESPONSE_OK:
            return self.entPasswd.get_text()
        return ''

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

    def toggle_window_display(self, icon):
        if self.MainWindow.get_property('visible'):
            self.MainWindow.hide()
            if self.show_printer_status.get_active ():
                self.PrintersWindow.hide()
        else:
            self.MainWindow.show()
            if self.show_printer_status.get_active ():
                self.PrintersWindow.show()

    def on_show_completed_jobs_activate(self, menuitem):
        if menuitem.get_active():
            self.which_jobs = "all"
        else:
            self.which_jobs = "not-completed"
        self.refresh()

    def on_show_printer_status_activate(self, menuitem):
        if self.show_printer_status.get_active ():
            self.PrintersWindow.show()
        else:
            self.PrintersWindow.hide()

    def check_still_connecting(self):
        """Timer callback to check on connecting-to-device reasons."""
        c = cups.Connection ()
        printer_reasons = collect_printer_state_reasons (c)
        del c

        if self.update_connecting_devices (printer_reasons):
            self.refresh ()

        # Don't run this callback again.
        return False

    def update_connecting_devices(self, printer_reasons=[]):
        """Updates connecting_to_device dict and still_connecting set.
        Returns True if a device has been connecting too long."""
        time_now = time.time ()
        connecting_to_device = {}
        trouble = False
        for reason in printer_reasons:
            if reason.get_reason () == "connecting-to-device":
                # Build a new connecting_to_device dict.  If our existing
                # dict already has an entry for this printer, use that.
                printer = reason.get_printer ()
                t = self.connecting_to_device.get (printer, time_now)
                connecting_to_device[printer] = t
                if time_now - t >= CONNECTING_TIMEOUT:
                    trouble = True

        # Clear any previously-notified errors that are now fine.
        remove = set()
        for printer in self.still_connecting:
            if not self.connecting_to_device.has_key (printer):
                remove.add (printer)
                if self.trayicon and self.notify:
                    r = self.notified_reason
                    if (r.get_printer () == printer and
                        r.get_reason () == 'connecting-to-device'):
                        # We had sent a notification for this reason.
                        # Close it.
                        self.notify.close ()
                        self.notify = None

        self.still_connecting = self.still_connecting.difference (remove)

        self.connecting_to_device = connecting_to_device
        return trouble

    def check_state_reasons(self, connection, my_printers=set()):
        printer_reasons = collect_printer_state_reasons (connection)

        # Look for any new reasons since we last checked.
        old_reasons_seen_keys = self.reasons_seen.keys ()
        reasons_now = set()
        need_recheck = False
        for reason in printer_reasons:
            tuple = reason.get_tuple ()
            printer = reason.get_printer ()
            reasons_now.add (tuple)
            if not self.reasons_seen.has_key (tuple):
                # New reason.
                iter = self.store_printers.append (None)
                self.store_printers.set_value (iter, 0, reason.get_level ())
                self.store_printers.set_value (iter, 1, reason.get_printer ())
                title, text = reason.get_description ()
                self.store_printers.set_value (iter, 2, text)
                self.reasons_seen[tuple] = iter
                if (reason.get_reason () == "connecting-to-device" and
                    not self.connecting_to_device.has_key (printer)):
                    # First time we've seen this.
                    need_recheck = True

        if need_recheck:
            # Check on them again in a minute's time.
            gobject.timeout_add (CONNECTING_TIMEOUT * 1000,
                                 self.check_still_connecting)

        self.update_connecting_devices (printer_reasons)
        items = self.reasons_seen.keys ()
        for tuple in items:
            if not tuple in reasons_now:
                # Reason no longer present.
                iter = self.reasons_seen[tuple]
                self.store_printers.remove (iter)
                del self.reasons_seen[tuple]
                if (self.trayicon and self.notify and
                    self.notified_reason.get_tuple () == tuple):
                    # We had sent a notification for this reason.  Close it.
                    self.notify.close ()
                    self.notify = None

        # Update statusbar and icon with most severe printer reason
        # across all printers.
        reason = worst_printer_state_reason (connection, printer_reasons)
        if reason != None and reason.get_level () >= StateReason.WARNING:
            title, text = reason.get_description ()
            if self.statusbar_set:
                self.statusbar.pop (0)
            self.statusbar.push (0, text)
            self.statusbar_set = True

            if self.trayicon:
                icon = StateReason.LEVEL_FILE[reason.get_level ()]
                pixbuf = self.statusicon.get_pixbuf ().copy ()
                image = gtk.Image ()
                image.set_from_file (icon)
                emblem = image.get_pixbuf ()
                emblem.composite (pixbuf,
                                  pixbuf.get_width () / 2,
                                  pixbuf.get_height () / 2,
                                  emblem.get_width () / 2,
                                  emblem.get_height () / 2,
                                  pixbuf.get_width () / 2,
                                  pixbuf.get_height () / 2,
                                  0.5, 0.5,
                                  gtk.gdk.INTERP_BILINEAR, 255)
                self.set_statusicon_from_pixbuf (pixbuf)
        else:
            # No errors
            if self.statusbar_set:
                self.statusbar.pop (0)
                self.statusbar_set = False

        # Send notifications for printers we've got jobs queued for.
        my_reasons = []
        for reason in printer_reasons:
            if reason.get_printer () in my_printers:
                my_reasons.append (reason)
        reason = worst_printer_state_reason (connection, my_reasons)

        # If connecting-to-device is the worst reason, check if it's been
        # like that for more than a minute.  If so, let's put a warning
        # bubble up.
        if (self.trayicon and reason != None and
            reason.get_reason () == "connecting-to-device"):
            now = time.time ()
            printer = reason.get_printer ()
            start = self.connecting_to_device.get (printer, now)
            if now - start >= CONNECTING_TIMEOUT:
                # This will be in our list of reasons we've already seen,
                # which ordinarily stops us notifying the user.  In this
                # case, pretend we haven't seen it before.
                self.still_connecting.add (printer)
                old_reasons_seen_keys.remove (reason.get_tuple ())
                reason = StateReason (printer,
                                      reason.get_reason () + "-error")

        if (self.trayicon and reason != None and
            reason.get_level () >= StateReason.WARNING):
            if not reason.get_tuple () in old_reasons_seen_keys:
                level = reason.get_level ()
                if level == StateReason.WARNING:
                    notify_urgency = pynotify.URGENCY_LOW
                    timeout = pynotify.EXPIRES_DEFAULT
                else:
                    notify_urgency = pynotify.URGENCY_NORMAL
                    timeout = pynotify.EXPIRES_NEVER

                (title, text) = reason.get_description ()

                if self.notify:
                    self.notify.close ()
                self.notify = pynotify.Notification (title, text)
                self.notify.attach_to_status_icon (self.statusicon)
                self.notify.set_urgency (notify_urgency)
                self.notify.set_timeout (timeout)
                self.notify.show ()
                self.notified_reason = reason

    def update_job_creation_times(self):
        now = time.time ()
        need_update = False
        for job, data in self.jobs.iteritems():
            if self.jobs.has_key (job):
                iter = self.jobiters[job]

            t = "Unknown"
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
                            t = _("%d hours ago")
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

            self.store.set_value (iter, 4, t)

        if need_update and not self.will_update_job_creation_times:
            gobject.timeout_add (60 * 1000,
                                 self.update_job_creation_times)
            self.will_update_job_creation_times = True

        if not need_update:
            self.will_update_job_creation_times = False

        # Return code controls whether the timeout will recur.
        return self.will_update_job_creation_times

    def refresh(self):
        if self.hidden:
            return

        now = time.time ()
        if (now - self.last_refreshed) < MIN_REFRESH_INTERVAL:
            if self.will_refresh:
                return

            gobject.timeout_add (MIN_REFRESH_INTERVAL * 1000,
                                 self.refresh)
            self.will_refresh = True
            return

        self.will_refresh = False
        self.last_refreshed = now
        print "refresh"

        try:
            c = cups.Connection ()
            jobs = c.getJobs (which_jobs=self.which_jobs, my_jobs=True)
        except cups.IPPError, (e, m):
            self.show_IPP_Error (e, m)
            return
        except RuntimeError:
            return

        if self.which_jobs == "not-completed":
            num_jobs = len (jobs)
        else:
            try:
                num_jobs = len (c.getJobs (my_jobs=True))
            except cups.IPPError, (e, m):
                self.show_IPP_Error (e, m)
                return
            except RuntimeError:
                return

        if self.trayicon:
            if num_jobs == 0:
                self.statusicon.set_tooltip (_("No documents queued"))
                self.set_statusicon_from_pixbuf (self.icon_no_jobs)
            elif num_jobs == 1:
                self.statusicon.set_tooltip (_("1 document queued"))
                self.set_statusicon_from_pixbuf (self.icon_jobs)
            else:
                self.statusicon.set_tooltip (_("%d documents queued")
                                             % num_jobs)
                self.set_statusicon_from_pixbuf (self.icon_jobs)

        my_printers = set()
        for job, data in jobs.iteritems ():
            state = data.get ('job-state', cups.IPP_JOB_CANCELED)
            if state >= cups.IPP_JOB_CANCELED:
                continue
            uri = data.get ('job-printer-uri', '/')
            i = uri.rfind ('/')
            my_printers.add (uri[i + 1:])

        self.check_state_reasons (c, my_printers)
        del c
        for job in self.jobs:
            if not jobs.has_key (job):
                self.store.remove (self.jobiters[job])
                del self.jobiters[job]

        for job, data in jobs.iteritems():
            if self.jobs.has_key (job):
                iter = self.jobiters[job]
            else:
                iter = self.store.append (None)
                self.store.set_value (iter, 0, job)
                self.store.set_value (iter, 1, data.get('job-name', 'Unknown'))
                self.jobiters[job] = iter

            printer = "Unknown"
            uri = data.get('job-printer-uri', '')
            i = uri.rfind ('/')
            if i != -1:
                printer = uri[i + 1:]
            self.store.set_value (iter, 2, printer)

            if data.has_key ('job-k-octets'):
                size = str (data['job-k-octets']) + 'k'
            else:
                size = 'Unknown'
            self.store.set_value (iter, 3, size)

            state = None
            if data.has_key ('job-state'):
                try:
                    jstate = data['job-state']
                    s = int (jstate)
                    state = { cups.IPP_JOB_PENDING:_("Pending"),
                              cups.IPP_JOB_HELD:_("Held"),
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
            self.store.set_value (iter, 5, state)

        self.jobs = jobs
        self.update_job_creation_times ()

    def on_treeview_button_press_event(self, treeview, event):
        if event.button != 3:
            return

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
            if (s < cups.IPP_JOB_CANCELED or
                not job.get('job-preserved', False)):
                self.reprint.set_sensitive (False)
        self.job_popupmenu.popup (None, None, None, event.button,
                                  event.get_time ())

    def on_icon_popupmenu(self, icon, button, time):
        self.icon_popupmenu.popup (None, None, None, button, time)

    def on_icon_hide_activate(self, menuitem):
        bus.remove_signal_receiver (self.handle_dbus_signal,
                                    path="/com/redhat/PrinterSpooler",
                                    dbus_interface="com.redhat.PrinterSpooler")
        self.hidden = True
        self.statusicon.set_visible (False)
        if not self.service_running:
            self.loop.quit ()

    def on_job_cancel_activate(self, menuitem):
        try:
            c = cups.Connection ()
            c.cancelJob (self.jobid)
            del c
        except cups.IPPError, (e, m):
            self.show_IPP_Error (e, m)
            return
        except RuntimeError:
            return

    def on_job_hold_activate(self, menuitem):
        try:
            c = cups.Connection ()
            c.setJobHoldUntil (self.jobid, "indefinite")
            del c
        except cups.IPPError, (e, m):
            self.show_IPP_Error (e, m)
            return
        except RuntimeError:
            return

    def on_job_release_activate(self, menuitem):
        try:
            c = cups.Connection ()
            c.setJobHoldUntil (self.jobid, "no-hold")
            del c
        except cups.IPPError, (e, m):
            self.show_IPP_Error (e, m)
            return
        except RuntimeError:
            return

    def on_job_reprint_activate(self, menuitem):
        try:
            c = cups.Connection ()
            c.restartJob (self.jobid)
            del c
        except cups.IPPError, (e, m):
            self.show_IPP_Error (e, m)
            return
        except RuntimeError:
            return

        self.refresh ()

    def on_refresh_activate(self, menuitem):
        self.refresh ()

    def handle_dbus_signal(self, *args):
        self.refresh ()

    ## Printer status window
    def set_printer_status_icon (self, column, cell, model, iter, *user_data):
        level = model.get_value (iter, 0)
        file = StateReason.LEVEL_FILE[level]
        pixbuf = gtk.gdk.pixbuf_new_from_file (file)
        cell.set_property("pixbuf", pixbuf)

    def set_printer_status_name (self, column, cell, model, iter, *user_data):
        cell.set_property("text", model.get_value (iter, 1))

gtk_loaded = False
def do_imports():
    global gtk_loaded
    if not gtk_loaded:
        gtk_loaded = True
        global gtk, pango, pynotify, time, gettext, _
        import gtk, gtk.glade, pango
        import pynotify
        import time
        import gettext
        from gettext import gettext as _
        gettext.textdomain (DOMAIN)
        gtk.glade.bindtextdomain (DOMAIN)

PROGRAM_NAME="system-config-printer-applet"
def show_help ():
    print "usage: %s [--no-tray-icon]" % PROGRAM_NAME

def show_version ():
    import config
    print "%s %s" % (PROGRAM_NAME, config.VERSION)
    
####
#### Main program entry
####

trayicon = True
service_running = False

import sys, getopt
try:
    opts, args = getopt.gnu_getopt (sys.argv[1:], '',
                                    ['no-tray-icon',
                                     'help',
                                     'version'])
except getopt.GetoptError:
    show_help ()
    sys.exit (1)

for opt, optarg in opts:
    if opt == "--help":
        show_help ()
        sys.exit (0)
    if opt == "--version":
        show_version ()
        sys.exit (0)
    if opt == "--no-tray-icon":
        trayicon = False

import dbus
import dbus.glib
import dbus.service
import gobject

if trayicon:
    # Stop running when the session ends.
    def monitor_session (*args):
        pass

    try:
        bus = dbus.SessionBus()
        bus.add_signal_receiver (monitor_session)
    except:
        print >> sys.stderr, "%s: failed to connect to session D-Bus" % \
              PROGRAM_NAME
        sys.exit (1)

####
#### PrintDriverSelection DBus server
####
PDS_PATH="/com/redhat/PrintDriverSelection"
PDS_IFACE="com.redhat.PrintDriverSelection"
PDS_OBJ="com.redhat.PrintDriverSelection"
class PrintDriverSelection(dbus.service.Object):
    def __init__(self, bus_name):
        dbus.service.Object.__init__(self, bus_name, PDS_PATH)

    @dbus.service.method(PDS_IFACE, in_signature='ssss', out_signature='')
    def PromptPrintDriver (self, make, model, uid, name):
        do_imports ()
        print "Need to implement PromptPrintDriver"

    # Need to add an interface for providing a PPD.

try:
    bus = dbus.SystemBus()
except:
    print >> sys.stderr, "%s: failed to connect to system D-Bus" % PROGRAM_NAME
    sys.exit (1)

if trayicon:
    try:
        name = dbus.service.BusName (PDS_OBJ, bus=bus)
        PrintDriverSelection(name)
        service_running = True
    except:
        print >> sys.stderr, \
              "%s: failed to start PrintDriverSelection service" % PROGRAM_NAME

    # Start off just waiting for print jobs or printer errors.
    def any_jobs_or_errors ():
        try:
            c = cups.Connection ()
            if len (c.getJobs (my_jobs=True)):
                return True
            reason = worst_printer_state_reason (c)
            if reason != None and reason.get_level () >= StateReason.WARNING:
                return True
        except:
            pass

        return False

    if not any_jobs_or_errors ():
        def check_for_jobs (*args):
            if any_jobs_or_errors ():
                loop.quit ()

        bus.add_signal_receiver (check_for_jobs,
                                 path="/com/redhat/PrinterSpooler",
                                 dbus_interface="com.redhat.PrinterSpooler")
        loop = gobject.MainLoop ()
        loop.run()
        bus.remove_signal_receiver (check_for_jobs,
                                    path="/com/redhat/PrinterSpooler",
                                    dbus_interface="com.redhat.PrinterSpooler")

do_imports()
loop = gobject.MainLoop ()
JobManager(bus, loop, service_running=service_running, trayicon=trayicon)
loop.run()

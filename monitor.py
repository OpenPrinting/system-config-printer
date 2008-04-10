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

import cups
import dbus
import dbus.glib
import gobject
import time
from debug import *
import pprint

global _
_ = lambda x: x
def set_gettext_function (x):
    _ = x
import statereason
from statereason import StateReason
statereason.set_gettext_function (_)

CONNECTING_TIMEOUT = 10 # seconds
MIN_REFRESH_INTERVAL = 1 # seconds

def state_reason_is_harmless (reason):
    if (reason.startswith ("moving-to-paused") or
        reason.startswith ("paused") or
        reason.startswith ("shutdown") or
        reason.startswith ("stopping") or
        reason.startswith ("stopped-partly")):
        return True
    return False

def collect_printer_state_reasons (connection):
    result = {}
    printers = connection.getPrinters ()
    for name, printer in printers.iteritems ():
        reasons = printer["printer-state-reasons"]
        if type (reasons) != list:
            # Work around a bug that was fixed in pycups-1.9.20.
            reasons = [reasons]
        for reason in reasons:
            if reason == "none":
                break
            if state_reason_is_harmless (reason):
                continue
            if not result.has_key (name):
                result[name] = []
            result[name].append (StateReason (name, reason))
    return result

class Watcher:
    # Interface definition
    def monitor_exited (self, monitor):
        debugprint (repr (monitor) + " exited")

    def state_reason_added (self, monitor, reason):
        debugprint (repr (monitor) + ": +" + repr (reason))

    def state_reason_removed (self, monitor, reason):
        debugprint (repr (monitor) + ": -" + repr (reason))

    def still_connecting (self, monitor, reason):
        debugprint (repr (monitor) + ": `%s' still connecting" %
                    reason.get_printer ())

    def now_connected (self, monitor, printer):
        debugprint (repr (monitor) + ": `%s' now connected" % printer)

    def current_printers_and_jobs (self, monitor, printers, jobs):
        debugprint (repr (monitor) + ": printers and jobs lists provided")

    def job_added (self, monitor, jobid, eventname, event, jobdata):
        debugprint (repr (monitor) + ": job %d added" % jobid)

    def job_event (self, monitor, jobid, eventname, event, jobdata):
        debugprint (repr (monitor) + ": job %d has event `%s'" %
                    (jobid, eventname))

    def job_removed (self, monitor, jobid, eventname, event):
        debugprint (repr (monitor) + ": job %d removed" % jobid)

    def printer_added (self, monitor, printer):
        debugprint (repr (monitor) + ": printer `%s' added" % printer)

    def printer_event (self, monitor, printer, eventname, event):
        debugprint (repr (monitor) + ": printer `%s' has event `%s'" %
                    (printer, eventname))

    def printer_removed (self, monitor, printer):
        debugprint (repr (monitor) + ": printer `%s' removed" % printer)

    def cups_connection_error (self, monitor):
        debugprint (repr (monitor) + ": CUPS connection error")

    def cups_ipp_error (self, monitor, e, m):
        debugprint (repr (monitor) + ": CUPS IPP error (%d, %s)" %
                    (e, repr (m)))

class Monitor:
    # Monitor jobs and printers.
    DBUS_PATH="/com/redhat/PrinterSpooler"
    DBUS_IFACE="com.redhat.PrinterSpooler"

    def __init__(self, watcher, bus=None, my_jobs=True, specific_dests=None,
                 monitor_jobs=True):
        self.watcher = watcher
        self.my_jobs = my_jobs
        self.specific_dests = specific_dests
        self.monitor_jobs = monitor_jobs
        self.jobs = {}
        self.printer_state_reasons = {}
        self.printers = set()

        self.which_jobs = "not-completed"
        self.reasons_seen = {}
        self.connecting_timers = {}
        self.still_connecting = set()
        self.connecting_to_device = {}
        self.received_any_dbus_signals = False

        if bus == None:
            bus = dbus.SystemBus ()

        bus.add_signal_receiver (self.handle_dbus_signal,
                                 path=self.DBUS_PATH,
                                 dbus_interface=self.DBUS_IFACE)
        self.bus = bus

        self.sub_id = -1
        self.refresh ()

    def get_jobs (self):
        return self.jobs.copy ()

    def cleanup (self):
        if self.sub_id != -1:
            try:
                c = cups.Connection ()
                c.cancelSubscription (self.sub_id)
                debugprint ("Canceled subscription %d" % self.sub_id)
            except:
                pass

        self.bus.remove_signal_receiver (self.handle_dbus_signal,
                                         path=self.DBUS_PATH,
                                         dbus_interface=self.DBUS_IFACE)

        self.watcher.monitor_exited (self)

    def check_still_connecting(self, printer):
        """Timer callback to check on connecting-to-device reasons."""
        del self.connecting_timers[printer]
        debugprint ("Still-connecting timer fired for `%s'" % printer)
        (printer_jobs, my_printers) = self.sort_jobs_by_printer ()
        self.update_connecting_devices (printer_jobs)

        # Don't run this callback again.
        return False

    def update_connecting_devices(self, printer_jobs={}):
        """Updates connecting_to_device dict and still_connecting set."""
        time_now = time.time ()
        connecting_to_device = {}
        trouble = False
        for printer, reasons in self.printer_state_reasons.iteritems ():
            connected = True
            for reason in reasons:
                if reason.get_reason () == "connecting-to-device":
                    have_processing_job = False
                    for job, data in \
                            printer_jobs.get (printer, {}).iteritems ():
                        state = data.get ('job-state',
                                          cups.IPP_JOB_CANCELED)
                        if state == cups.IPP_JOB_PROCESSING:
                            have_processing_job = True
                            break

                    if not have_processing_job:
                        debugprint ("Ignoring stale connecting-to-device x")
                        continue

                    # Build a new connecting_to_device dict.  If our existing
                    # dict already has an entry for this printer, use that.
                    printer = reason.get_printer ()
                    t = self.connecting_to_device.get (printer, time_now)
                    connecting_to_device[printer] = t
                    debugprint ("Connecting time: %d" % (time_now - t))
                    if time_now - t >= CONNECTING_TIMEOUT:
                        if have_processing_job:
                            self.still_connecting.add (printer)
                            self.watcher.still_connecting (self, reason)
                            if self.connecting_timers.has_key (printer):
                                gobject.source_remove (self.connecting_timers
                                                       [printer])
                                del self.connecting_timers[printer]
                                debugprint ("Stopped connecting timer "
                                            "for `%s'" % printer)

                    connected = False
                    break

            if connected and self.connecting_timers.has_key (printer):
                gobject.source_remove (self.connecting_timers[printer])
                del self.connecting_timers[printer]
                debugprint ("Stopped connecting timer for `%s'" % printer)

        # Clear any previously-notified errors that are now fine.
        remove = set()
        for printer in self.still_connecting:
            if not connecting_to_device.has_key (printer):
                remove.add (printer)
                self.watcher.now_connected (self, printer)
                if self.connecting_timers.has_key (printer):
                    gobject.source_remove (self.connecting_timers[printer])
                    del self.connecting_timers[printer]
                    debugprint ("Stopped connecting timer for `%s'" % printer)

        self.still_connecting = self.still_connecting.difference (remove)
        self.connecting_to_device = connecting_to_device

    def check_state_reasons(self, my_printers=set(), printer_jobs={}):
        # Look for any new reasons since we last checked.
        old_reasons_seen_keys = self.reasons_seen.keys ()
        reasons_now = set()
        for printer, reasons in self.printer_state_reasons.iteritems ():
            for reason in reasons:
                tuple = reason.get_tuple ()
                printer = reason.get_printer ()
                reasons_now.add (tuple)
                if not self.reasons_seen.has_key (tuple):
                    # New reason.
                    self.watcher.state_reason_added (self, reason)
                    self.reasons_seen[tuple] = reason

                if (reason.get_reason () == "connecting-to-device" and
                    not self.connecting_to_device.has_key (printer)):
                    # First time we've seen this.

                    have_processing_job = False
                    for job, data in \
                            printer_jobs.get (printer, {}).iteritems ():
                        state = data.get ('job-state',
                                          cups.IPP_JOB_CANCELED)
                        if state == cups.IPP_JOB_PROCESSING:
                            have_processing_job = True
                            break

                    if have_processing_job:
                        t = gobject.timeout_add ((1 + CONNECTING_TIMEOUT)
                                                 * 1000,
                                                 self.check_still_connecting,
                                                 printer)
                        self.connecting_timers[printer] = t
                        debugprint ("Start connecting timer for `%s'" %
                                    printer)
                    else:
                        # Don't notify about this, as it must be stale.
                        debugprint ("Ignoring stale connecting-to-device")
                        debugprint (pprint.pformat (printer_jobs))

        self.update_connecting_devices (printer_jobs)
        items = self.reasons_seen.keys ()
        for tuple in items:
            if not tuple in reasons_now:
                # Reason no longer present.
                reason = self.reasons_seen[tuple]
                del self.reasons_seen[tuple]
                self.watcher.state_reason_removed (self, reason)

    def get_notifications(self):
        debugprint ("get_notifications")
        try:
            c = cups.Connection ()

            try:
                try:
                    notifications = c.getNotifications ([self.sub_id],
                                                        [self.sub_seq + 1])
                except AttributeError:
                    notifications = c.getNotifications ([self.sub_id])
            except cups.IPPError, (e, m):
                if e == cups.IPP_NOT_FOUND:
                    # Subscription lease has expired.
                    self.sub_id = -1
                    self.refresh ()
                    return False

                self.watcher.cups_ipp_error (self, e, m)
                return True
        except RuntimeError:
            self.watcher.cups_connection_error (self)
            return True

        deferred_calls = []
        jobs = self.jobs.copy ()
        for event in notifications['events']:
            seq = event['notify-sequence-number']
            try:
                if seq <= self.sub_seq:
                    # Work around a bug in pycups < 1.9.34
                    continue
            except AttributeError:
                pass
            self.sub_seq = seq
            nse = event['notify-subscribed-event']
            debugprint ("%d %s %s" % (seq, nse, event['notify-text']))
            debugprint (pprint.pformat (event))
            if nse.startswith ('printer-'):
                # Printer events
                name = event['printer-name']
                if nse == 'printer-added' and name not in self.printers:
                    self.printers.add (name)
                    deferred_calls.append ((self.watcher.printer_added,
                                            (self, name)))

                elif nse == 'printer-deleted' and name in self.printers:
                    self.printers.remove (name)
                    items = self.reasons_seen.keys ()
                    for tuple in items:
                        if tuple[1] == name:
                            reason = self.reasons_seen[tuple]
                            del self.reasons_seen[tuple]
                            deferred_calls.append ((self.watcher.state_reason_removed,
                                                    (self, reason)))
                            
                    if self.printer_state_reasons.has_key (name):
                        del self.printer_state_reasons[name]

                    deferred_calls.append ((self.watcher.printer_removed,
                                            (self, name)))
                elif name in self.printers:
                    printer_state_reasons = event['printer-state-reasons']
                    if type (printer_state_reasons) != list:
                        # Work around a bug in pycups < 1.9.36
                        printer_state_reasons = [printer_state_reasons]

                    reasons = []
                    for reason in printer_state_reasons:
                        if reason == "none":
                            break
                        if state_reason_is_harmless (reason):
                            continue
                        reasons.append (StateReason (name, reason))
                    self.printer_state_reasons[name] = reasons

                    deferred_calls.append ((self.watcher.printer_event,
                                            (self, name, nse, event)))
                continue

            # Job events
            jobid = event['notify-job-id']
            if (nse == 'job-created' or
                (nse == 'job-state-changed' and
                 not jobs.has_key (jobid) and
                 event['job-state'] == cups.IPP_JOB_PROCESSING)):
                if (self.specific_dests != None and
                    event['printer-name'] not in self.specific_dests):
                    continue

                try:
                    attrs = c.getJobAttributes (jobid)
                    if (self.my_jobs and
                        attrs['job-originating-user-name'] != cups.getUser ()):
                        continue

                    jobs[jobid] = attrs
                except AttributeError:
                    jobs[jobid] = {'job-k-octets': 0}
                except cups.IPPError, (e, m):
                    self.watcher.cups_ipp_error (self, e, m)
                    jobs[jobid] = {'job-k-octets': 0}

                deferred_calls.append ((self.watcher.job_added,
                                        (self, jobid, nse, event,
                                         jobs[jobid].copy ())))
            elif nse == 'job-completed':
                try:
                    del jobs[jobid]
                    deferred_calls.append ((self.watcher.job_removed,
                                            (self, jobid, nse, event)))
                except KeyError:
                    pass
                continue

            try:
                job = jobs[jobid]
            except KeyError:
                continue

            for attribute in ['job-state',
                              'job-name']:
                job[attribute] = event[attribute]
            if event.has_key ('notify-printer-uri'):
                job['job-printer-uri'] = event['notify-printer-uri']

            deferred_calls.append ((self.watcher.job_event,
                                   (self, jobid, nse, event, job.copy ())))

        self.update (jobs)
        self.jobs = jobs

        for (fn, args) in deferred_calls:
            fn (*args)

        # Update again when we're told to.  If we're getting CUPS
        # D-Bus signals, however, rely on those instead.
        if not self.received_any_dbus_signals:
            gobject.source_remove (self.update_timer)
            interval = 1000 * notifications['notify-get-interval']
            self.update_timer = gobject.timeout_add (interval,
                                                     self.get_notifications)

        return False

    def refresh(self):
        debugprint ("refresh")

        try:
            c = cups.Connection ()
        except RuntimeError:
            self.watcher.cups_connection_error (self)
            return

        if self.sub_id != -1:
            try:
                c.cancelSubscription (self.sub_id)
            except cups.IPPError, (e, m):
                self.watcher.cups_ipp_error (self, e, m)

            gobject.source_remove (self.update_timer)
            debugprint ("Canceled subscription %d" % self.sub_id)

        try:
            del self.sub_seq
        except AttributeError:
            pass

        events = ["printer-added",
                  "printer-deleted",
                  "printer-state-changed"]
        if self.monitor_jobs:
            events.extend (["job-created",
                            "job-completed",
                            "job-stopped",
                            "job-progress",
                            "job-state-changed"])

        try:
            self.sub_id = c.createSubscription ("/", events=events)
        except cups.IPPError, (e, m):
            self.watcher.cups_ipp_error (self, e, m)

        self.update_timer = gobject.timeout_add (MIN_REFRESH_INTERVAL * 1000,
                                                 self.get_notifications)
        debugprint ("Created subscription %d" % self.sub_id)

        try:
            if self.monitor_jobs:
                jobs = c.getJobs (which_jobs=self.which_jobs,
                                  my_jobs=self.my_jobs)
            else:
                jobs = {}
            self.printer_state_reasons = collect_printer_state_reasons (c)
            dests = c.getDests ()
            printers = set()
            for (printer, instance) in dests.keys ():
                if printer == None:
                    continue
                if instance != None:
                    continue
                printers.add (printer)
            self.printers = printers
        except cups.IPPError, (e, m):
            self.watcher.cups_ipp_error (self, e, m)
            return
        except RuntimeError:
            self.watcher.cups_connection_error (self)
            return

        if self.specific_dests != None:
            for jobid in jobs.keys ():
                uri = jobs[jobid].get('job-printer-uri', '/')
                i = uri.rfind ('/')
                printer = uri[i + 1:]
                if printer not in self.specific_dests:
                    del jobs[jobid]

        self.watcher.current_printers_and_jobs (self, self.printers.copy (),
                                                jobs.copy ())
        self.update (jobs)

        self.jobs = jobs
        return False

    def sort_jobs_by_printer (self, jobs=None):
        if jobs == None:
            jobs = self.jobs

        my_printers = set()
        printer_jobs = {}
        for job, data in jobs.iteritems ():
            state = data.get ('job-state', cups.IPP_JOB_CANCELED)
            if state >= cups.IPP_JOB_CANCELED:
                continue
            uri = data.get ('job-printer-uri', '')
            i = uri.rfind ('/')
            if i == -1:
                continue
            printer = uri[i + 1:]
            my_printers.add (printer)
            if not printer_jobs.has_key (printer):
                printer_jobs[printer] = {}
            printer_jobs[printer][job] = data

        return (printer_jobs, my_printers)

    def update(self, jobs):
        debugprint ("update")
        (printer_jobs, my_printers) = self.sort_jobs_by_printer (jobs)
        self.check_state_reasons (my_printers, printer_jobs)

    def handle_dbus_signal(self, *args):
        gobject.source_remove (self.update_timer)
        self.update_timer = gobject.timeout_add (200, self.get_notifications)
        if not self.received_any_signals:
            self.received_any_dbus_signals = True

if __name__ == '__main__':
    set_debugging (True)
    m = Monitor (Watcher ())
    loop = gobject.MainLoop ()
    try:
        loop.run ()
    finally:
        m.cleanup ()

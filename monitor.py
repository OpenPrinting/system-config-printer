#!/usr/bin/python

## Copyright (C) 2007, 2008, 2009, 2010, 2011, 2012 Red Hat, Inc.
## Author: Tim Waugh <twaugh@redhat.com>

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

import config
import cups
cups.require("1.9.50")
import dbus
import dbus.glib
from gi.repository import GObject
from gi.repository import GLib
import time
from debug import *
import pprint
import gettext
gettext.install(domain=config.PACKAGE, localedir=config.localedir, unicode=True)
import ppdcache
import statereason
from statereason import StateReason

CONNECTING_TIMEOUT = 60 # seconds
MIN_REFRESH_INTERVAL = 1 # seconds

def state_reason_is_harmless (reason):
    if (reason.startswith ("moving-to-paused") or
        reason.startswith ("paused") or
        reason.startswith ("shutdown") or
        reason.startswith ("stopping") or
        reason.startswith ("stopped-partly")):
        return True
    return False

def collect_printer_state_reasons (connection, ppdcache):
    result = {}
    try:
        printers = connection.getPrinters ()
    except cups.IPPError:
        return result

    for name, printer in printers.iteritems ():
        reasons = printer["printer-state-reasons"]
        for reason in reasons:
            if reason == "none":
                break
            if state_reason_is_harmless (reason):
                continue
            if not result.has_key (name):
                result[name] = []
            result[name].append (StateReason (name, reason, ppdcache))
    return result

class Monitor(GObject.GObject):
    __gsignals__ = {
        'refresh':               (GObject.SIGNAL_RUN_LAST, None, ()),
        'monitor-exited' :       (GObject.SIGNAL_RUN_LAST, None, ()),
        'state-reason-added':    (GObject.SIGNAL_RUN_LAST, None,
                                  (GObject.TYPE_PYOBJECT,)),
        'state-reason-removed':  (GObject.SIGNAL_RUN_LAST, None,
                                  (GObject.TYPE_PYOBJECT,)),
        'still-connecting':      (GObject.SIGNAL_RUN_LAST, None,
                                  (GObject.TYPE_PYOBJECT,)),
        'now-connected':         (GObject.SIGNAL_RUN_LAST, None,
                                  (str,)),
        'job-added':             (GObject.SIGNAL_RUN_LAST, None,
                                  (int, str,
                                   GObject.TYPE_PYOBJECT,
                                   GObject.TYPE_PYOBJECT,)),
        'job-event':             (GObject.SIGNAL_RUN_LAST, None,
                                  (int, str,
                                   GObject.TYPE_PYOBJECT,
                                   GObject.TYPE_PYOBJECT,)),
        'job-removed':           (GObject.SIGNAL_RUN_LAST, None,
                                  (int, str,
                                   GObject.TYPE_PYOBJECT,)),
        'printer-added':         (GObject.SIGNAL_RUN_LAST, None,
                                  (str,)),
        'printer-event':         (GObject.SIGNAL_RUN_LAST, None,
                                  (str, str,
                                   GObject.TYPE_PYOBJECT,)),
        'printer-removed':       (GObject.SIGNAL_RUN_LAST, None,
                                  (str,)),
        'cups-connection-error': (GObject.SIGNAL_RUN_LAST, None, ()),
        'cups-connection-recovered': (GObject.SIGNAL_RUN_LAST, None, ()),
        'cups-ipp-error':        (GObject.SIGNAL_RUN_LAST, None,
                                  (int, str,))
        }

    # Monitor jobs and printers.
    DBUS_PATH="/com/redhat/PrinterSpooler"
    DBUS_IFACE="com.redhat.PrinterSpooler"

    def __init__(self, bus=None, my_jobs=True,
                 specific_dests=None, monitor_jobs=True, host=None,
                 port=None, encryption=None):
        GObject.GObject.__init__ (self)
        self.my_jobs = my_jobs
        self.specific_dests = specific_dests
        self.monitor_jobs = monitor_jobs
        self.jobs = {}
        self.printer_state_reasons = {}
        self.printers = set()
        self.process_pending_events = True
        self.fetch_jobs_timer = None
        self.cups_connection_in_error = False

        if host:
            cups.setServer (host)
        if port:
            cups.setPort (port)
        if encryption:
            cups.setEncryption (encryption)
        self.user = cups.getUser ()
        self.host = cups.getServer ()
        self.port = cups.getPort ()
        self.encryption = cups.getEncryption ()
        self.ppdcache = ppdcache.PPDCache (host=self.host,
                                           port=self.port,
                                           encryption=self.encryption)

        self.which_jobs = "not-completed"
        self.reasons_seen = {}
        self.connecting_timers = {}
        self.still_connecting = set()
        self.connecting_to_device = {}
        self.received_any_dbus_signals = False
        self.update_timer = None

        if bus == None:
            try:
                bus = dbus.SystemBus ()
            except dbus.exceptions.DBusException:
                # System bus not running.
                pass

        self.bus = bus
        if bus != None:
            bus.add_signal_receiver (self.handle_dbus_signal,
                                     path=self.DBUS_PATH,
                                     dbus_interface=self.DBUS_IFACE)
        self.sub_id = -1

    def get_printers (self):
        return self.printers.copy ()

    def get_jobs (self):
        return self.jobs.copy ()

    def get_ppdcache (self):
        return self.ppdcache

    def cleanup (self):
        if self.sub_id != -1:
            user = cups.getUser ()
            try:
                cups.setUser (self.user)
                c = cups.Connection (host=self.host,
                                     port=self.port,
                                     encryption=self.encryption)
                c.cancelSubscription (self.sub_id)
                debugprint ("Canceled subscription %d" % self.sub_id)
            except:
                pass
            cups.setUser (user)

        if self.bus != None:
            self.bus.remove_signal_receiver (self.handle_dbus_signal,
                                             path=self.DBUS_PATH,
                                             dbus_interface=self.DBUS_IFACE)

        timers = self.connecting_timers.values ()
        for timer in [self.update_timer, self.fetch_jobs_timer]:
            if timer:
                timers.append (timer)
        for timer in timers:
            GLib.source_remove (timer)

        self.emit ('monitor-exited')

    def set_process_pending (self, whether):
        self.process_pending_events = whether

    def check_still_connecting(self, printer):
        """Timer callback to check on connecting-to-device reasons."""
        if not self.process_pending_events:
            # Defer the timer by setting a new one.
            timer = GLib.timeout_add (200, self.check_still_connecting,
                                      printer)
            self.connecting_timers[printer] = timer
            return False

        if self.connecting_timers.has_key (printer):
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
                            if printer not in self.still_connecting:
                                self.still_connecting.add (printer)
                                self.emit ('still-connecting', reason)
                            if self.connecting_timers.has_key (printer):
                                GLib.source_remove (self.connecting_timers
                                                    [printer])
                                del self.connecting_timers[printer]
                                debugprint ("Stopped connecting timer "
                                            "for `%s'" % printer)

                    connected = False
                    break

            if connected and self.connecting_timers.has_key (printer):
                GLib.source_remove (self.connecting_timers[printer])
                del self.connecting_timers[printer]
                debugprint ("Stopped connecting timer for `%s'" % printer)

        # Clear any previously-notified errors that are now fine.
        remove = set()
        for printer in self.still_connecting:
            if not connecting_to_device.has_key (printer):
                remove.add (printer)
                self.emit ('now-connected', printer)
                if self.connecting_timers.has_key (printer):
                    GLib.source_remove (self.connecting_timers[printer])
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
                    GLib.idle_add (lambda x:
                                       self.emit ('state-reason-added', x),
                                   reason)
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
                        t = GLib.timeout_add_seconds (
                            (1 + CONNECTING_TIMEOUT),
                            self.check_still_connecting,
                            printer)
                        self.connecting_timers[printer] = t
                        debugprint ("Start connecting timer for `%s'" %
                                    printer)
                    else:
                        # Don't notify about this, as it must be stale.
                        debugprint ("Ignoring stale connecting-to-device")
                        if get_debugging ():
                            debugprint (pprint.pformat (printer_jobs))

        self.update_connecting_devices (printer_jobs)
        items = self.reasons_seen.keys ()
        for tuple in items:
            if not tuple in reasons_now:
                # Reason no longer present.
                reason = self.reasons_seen[tuple]
                del self.reasons_seen[tuple]
                GLib.idle_add (lambda x: self.emit ('state-reason-removed', x),
                               reason)

    def get_notifications(self):
        if not self.process_pending_events:
            # Defer the timer callback.
            if self.update_timer:
                GLib.source_remove (self.update_timer)

            self.update_timer = GLib.timeout_add (200,
                                                     self.get_notifications)
            debugprint ("Deferred get_notifications by 200ms")
            return False

        debugprint ("get_notifications")
        user = cups.getUser ()
        try:
            cups.setUser (self.user)
            c = cups.Connection (host=self.host,
                                 port=self.port,
                                 encryption=self.encryption)

            try:
                try:
                    notifications = c.getNotifications ([self.sub_id],
                                                        [self.sub_seq + 1])
                except AttributeError:
                    notifications = c.getNotifications ([self.sub_id])
            except cups.IPPError as e:
                (e, m) = e.args
                cups.setUser (user)
                if e == cups.IPP_NOT_FOUND:
                    # Subscription lease has expired.
                    self.sub_id = -1
                    debugprint ("Subscription not found, will refresh")
                    self.refresh ()
                    return False

                self.emit ('cups-ipp-error', e, m)
                if e == cups.IPP_FORBIDDEN:
                    return False

                debugprint ("getNotifications failed with %d (%s)" % (e, m))
                return True
        except RuntimeError:
            cups.setUser (user)
            debugprint ("cups-connection-error, will retry")
            self.cups_connection_in_error = True
            self.emit ('cups-connection-error')
            return True

        if self.cups_connection_in_error:
            self.cups_connection_in_error = False
            debugprint ("cups-connection-recovered")
            self.emit ('cups-connection-recovered')

        cups.setUser (user)
        jobs = self.jobs.copy ()
        for event in notifications['events']:
            seq = event['notify-sequence-number']
            self.sub_seq = seq
            nse = event['notify-subscribed-event']
            debugprint ("%d %s %s" % (seq, nse, event['notify-text']))
            if get_debugging ():
                debugprint (pprint.pformat (event))
            if nse.startswith ('printer-'):
                # Printer events
                name = event['printer-name']
                if nse == 'printer-added' and name not in self.printers:
                    self.printers.add (name)
                    self.emit ('printer-added', name)

                elif nse == 'printer-deleted' and name in self.printers:
                    self.printers.remove (name)
                    items = self.reasons_seen.keys ()
                    for tuple in items:
                        if tuple[1] == name:
                            reason = self.reasons_seen[tuple]
                            del self.reasons_seen[tuple]
                            self.emit ('state-reason-removed', reason)
                            
                    if self.printer_state_reasons.has_key (name):
                        del self.printer_state_reasons[name]

                    self.emit ('printer-removed', name)
                elif name in self.printers:
                    printer_state_reasons = event['printer-state-reasons']
                    reasons = []
                    for reason in printer_state_reasons:
                        if reason == "none":
                            break
                        if state_reason_is_harmless (reason):
                            continue
                        reasons.append (StateReason (name, reason,
                                                     self.ppdcache))
                    self.printer_state_reasons[name] = reasons

                    self.emit ('printer-event', name, nse, event)
                continue

            # Job events
            if not nse.startswith ("job-"):
                # Some versions of CUPS give empty
                # notify-subscribed-event attributes (STR #3608).
                debugprint ("Unhandled nse %s" % repr (nse))
                continue

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
                except KeyError:
                    jobs[jobid] = {'job-k-octets': 0}
                except cups.IPPError as e:
                    (e, m) = e.args
                    self.emit ('cups-ipp-error', e, m)
                    jobs[jobid] = {'job-k-octets': 0}

                self.emit ('job-added', jobid, nse, event, jobs[jobid].copy ())
            elif (nse == 'job-completed' or
                  (nse == 'job-state-changed' and
                   event['job-state'] == cups.IPP_JOB_COMPLETED)):
                if not (self.which_jobs in ['completed', 'all']):
                    try:
                        del jobs[jobid]
                        self.emit ('job-removed', jobid, nse, event)
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

            self.emit ('job-event', jobid, nse, event, job.copy ())

        self.set_process_pending (False)
        self.update_jobs (jobs)
        self.jobs = jobs
        self.set_process_pending (True)

        # Update again when we're told to.  If we're getting CUPS
        # D-Bus signals, however, rely on those instead.
        if not self.received_any_dbus_signals:
            if self.update_timer:
                GLib.source_remove (self.update_timer)

            interval = notifications['notify-get-interval']
            t = GLib.timeout_add_seconds (interval,
                                          self.get_notifications)
            debugprint ("Next notifications fetch in %ds" % interval)
            self.update_timer = t

        return False

    def refresh(self, which_jobs=None, refresh_all=True):
        debugprint ("refresh")

        self.emit ('refresh')
        if which_jobs != None:
            self.which_jobs = which_jobs

        user = cups.getUser ()
        try:
            cups.setUser (self.user)
            c = cups.Connection (host=self.host,
                                 port=self.port,
                                 encryption=self.encryption)
        except RuntimeError:
            GLib.idle_add (self.emit, 'cups-connection-error')
            cups.setUser (user)
            return

        if self.sub_id != -1:
            try:
                c.cancelSubscription (self.sub_id)
            except cups.IPPError as e:
                (e, m) = e.args
                GLib.idle_add (lambda (e, m):
                                   self.emit ('cups-ipp-error', e, m),
                               (e, m))

            if self.update_timer:
                GLib.source_remove (self.update_timer)

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
                            "job-state-changed",
                            "job-progress"])

        try:
            self.sub_id = c.createSubscription ("/", events=events)
            debugprint ("Created subscription %d, events=%s" % (self.sub_id,
                                                                repr (events)))
        except cups.IPPError as e:
            (e, m) = e.args
            GLib.idle_add (lambda (e, m):
                               self.emit ('cups-ipp-error', e, m),
                           (e, m))

        cups.setUser (user)

        if self.sub_id != -1:
            self.update_timer = GLib.timeout_add_seconds (
                MIN_REFRESH_INTERVAL,
                self.get_notifications)
            debugprint ("Next notifications fetch in %ds" %
                        MIN_REFRESH_INTERVAL)

        if self.monitor_jobs:
            jobs = self.jobs.copy ()
            if self.which_jobs not in ['all', 'completed']:
                # Filter out completed jobs.
                filtered = {}
                for jobid, job in jobs.iteritems ():
                    if job.get ('job-state',
                                cups.IPP_JOB_CANCELED) < cups.IPP_JOB_CANCELED:
                        filtered[jobid] = job
                jobs = filtered

            self.fetch_first_job_id = 1
            if self.fetch_jobs_timer:
                GLib.source_remove (self.fetch_jobs_timer)
            self.fetch_jobs_timer = GLib.timeout_add (5, self.fetch_jobs,
                                                      refresh_all)
        else:
            jobs = {}

        try:
            r = collect_printer_state_reasons (c, self.ppdcache)
            self.printer_state_reasons = r
            dests = c.getPrinters ()
            self.printers = set(dests.keys ())
        except cups.IPPError as e:
            (e, m) = e.args
            GLib.idle_add (lambda (e, m):
                               self.emit ('cups-ipp-error', e, m),
                           (e, m))
            return
        except RuntimeError:
            GLib.idle_add (self.emit, 'cups-connection-error')
            return

        if self.specific_dests != None:
            for jobid in jobs.keys ():
                uri = jobs[jobid].get('job-printer-uri', '/')
                i = uri.rfind ('/')
                printer = uri[i + 1:]
                if printer not in self.specific_dests:
                    del jobs[jobid]

        self.set_process_pending (False)
        for printer in self.printers:
            GLib.idle_add (lambda x: self.emit ('printer-added', x), printer)
        for jobid, job in jobs.iteritems ():
            GLib.idle_add (lambda (jobid, job):
                               self.emit ('job-added', jobid, '', {}, job),
                           (jobid, job))
        self.update_jobs (jobs)
        self.jobs = jobs
        self.set_process_pending (True)
        return False

    def fetch_jobs (self, refresh_all):
        if not self.process_pending_events:
            # Skip this call.  We'll get called again soon.
            return True

        user = cups.getUser ()
        try:
            cups.setUser (self.user)
            c = cups.Connection (host=self.host,
                                 port=self.port,
                                 encryption=self.encryption)
        except RuntimeError:
            self.emit ('cups-connection-error')
            self.fetch_jobs_timer = None
            cups.setUser (user)
            return False

        limit = 1
        r = ["job-id",
             "job-printer-uri",
             "job-state",
             "job-originating-user-name",
             "job-k-octets",
             "job-name",
             "time-at-creation"]
        try:
            fetched = c.getJobs (which_jobs=self.which_jobs,
                                 my_jobs=self.my_jobs,
                                 first_job_id=self.fetch_first_job_id,
                                 limit=limit,
                                 requested_attributes=r)
        except cups.IPPError as e:
            (e, m) = e.args
            self.emit ('cups-ipp-error', e, m)
            self.fetch_jobs_timer = None
            cups.setUser (user)
            return False

        cups.setUser (user)
        got = len (fetched)
        debugprint ("Got %s jobs, asked for %s" % (got, limit))

        jobs = self.jobs.copy ()
        jobids = fetched.keys ()
        jobids.sort ()
        if got > 0:
            last_jobid = jobids[got - 1]
            if last_jobid < self.fetch_first_job_id:
                last_jobid = self.fetch_first_job_id + limit - 1
                debugprint ("Unexpected job IDs returned: %s" % repr (jobids))
                debugprint ("That's not what we asked for!")
        else:
            last_jobid = self.fetch_first_job_id + limit - 1
        for jobid in xrange (self.fetch_first_job_id, last_jobid + 1):
            try:
                job = fetched[jobid]
                if self.specific_dests != None:
                    uri = job.get('job-printer-uri', '/')
                    i = uri.rfind ('/')
                    printer = uri[i + 1:]
                    if printer not in self.specific_dests:
                        raise KeyError

                if jobs.has_key (jobid):
                    n = 'job-event'
                else:
                    n = 'job-added'

                jobs[jobid] = job
                self.emit (n, jobid, '', {}, job.copy ())
            except KeyError:
                # No job by that ID.
                if jobs.has_key (jobid):
                    del jobs[jobid]
                    self.emit ('job-removed', jobid, '', {})

        jobids = jobs.keys ()
        jobids.sort ()
        if got < limit:
            trim = False
            for i in range (len (jobids)):
                jobid = jobids[i]
                if not trim and jobid > last_jobid:
                    trim = True
            
                if trim:
                    del jobs[jobid]
                    self.emit ('job-removed', jobid, '', {})

        self.update_jobs (jobs)
        self.jobs = jobs

        if got < limit:
            # That's all.  Don't run this timer again.
            self.fetch_jobs_timer = None
            return False

        # Remember where we got up to and run this timer again.
        next = jobid + 1

        while not refresh_all and self.jobs.has_key (next):
            next += 1

        self.fetch_first_job_id = next
        return True

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

    def update_jobs(self, jobs):
        debugprint ("update_jobs")
        (printer_jobs, my_printers) = self.sort_jobs_by_printer (jobs)
        self.check_state_reasons (my_printers, printer_jobs)

    def update(self):
        if self.update_timer:
            GLib.source_remove (self.update_timer)

        self.update_timer = GLib.timeout_add (200, self.get_notifications)
        debugprint ("Next notifications fetch in 200ms (update called)")

    def handle_dbus_signal(self, *args):
        debugprint ("D-Bus signal from CUPS... calling update")
        self.update ()
        if not self.received_any_dbus_signals:
            self.received_any_dbus_signals = True

if __name__ == '__main__':
    class SignalWatcher:
        def __init__ (self, monitor):
            monitor.connect ('monitor-exited', self.on_monitor_exited)
            monitor.connect ('state-reason-added', self.on_state_reason_added)
            monitor.connect ('state-reason-removed',
                             self.on_state_reason_removed)
            monitor.connect ('still-connecting', self.on_still_connecting)
            monitor.connect ('now-connected', self.on_now_connected)
            monitor.connect ('job-added', self.on_job_added)
            monitor.connect ('job-event', self.on_job_event)
            monitor.connect ('job-removed', self.on_job_removed)
            monitor.connect ('printer-added', self.on_printer_added)
            monitor.connect ('printer-event', self.on_printer_event)
            monitor.connect ('printer-removed', self.on_printer_removed)
            monitor.connect ('cups-connection-error',
                             self.on_cups_connection_error)
            monitor.connect ('cups-ipp-error', self.on_cups_ipp_error)

        def on_monitor_exited (self, obj):
            print "*%s: monitor exited" % obj

        def on_state_reason_added (self, obj, reason):
            print "*%s: +%s" % (obj, reason)

        def on_state_reason_removed (self, obj, reason):
            print "*%s: -%s" % (obj, reason)

        def on_still_connecting (self, obj, reason):
            print "*%s: still connecting: %s" % (obj, reason)

        def on_now_connected (self, obj, printer):
            print "*%s: now connected: %s" % (obj, printer)

        def on_job_added (self, obj, jobid, eventname, event, jobdata):
            print "*%s: job %d added" % (obj, jobid)

        def on_job_event (self, obj, jobid, eventname, event, jobdata):
            print "*%s: job %d event: %s" % (obj, jobid, event)

        def on_job_removed (self, obj, jobid, eventname, event):
            print "*%s: job %d removed (%s)"% (obj, jobid, eventname)

        def on_printer_added (self, obj, name):
            print "*%s: printer added: %s" % (obj, name)

        def on_printer_event (self, obj, name, eventname, event):
            print "*%s: printer event: %s: %s" % (obj, name, eventname)

        def on_printer_removed (self, obj, name):
            print "*%s: printer %s removed" % (obj, name)

        def on_cups_connection_error (self, obj):
            print "*%s: cups connection error" % obj

        def on_cups_ipp_error (self, obj, err, errstring):
            # cups.IPPError message is (utf-8) encoded
            if isinstance(errstring, bytes):
                    errstring = errstring.decode('utf-8', 'replace')
            print "*%s: IPP error (%d): %s" % (obj, err, errstring)

    set_debugging (True)
    m = Monitor ()
    SignalWatcher (m)
    m.refresh ()
    loop = GObject.MainLoop ()
    try:
        loop.run ()
    finally:
        m.cleanup ()

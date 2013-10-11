#!/usr/bin/python

## Printing troubleshooter

## Copyright (C) 2008, 2009, 2010, 2012 Red Hat, Inc.
## Authors:
##  Tim Waugh <twaugh@redhat.com>

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

import cups
import dbus
import dbus.glib
from gi.repository import GLib
import os
from gi.repository import Gdk
from gi.repository import Gtk
from gi.repository import Pango
import tempfile
import time
from timedops import TimedOperation, OperationCanceled

from base import *

import errordialogs
from errordialogs import *

DBUS_PATH="/com/redhat/PrinterSpooler"
DBUS_IFACE="com.redhat.PrinterSpooler"
class PrintTestPage(Question):
    STATE = { cups.IPP_JOB_PENDING: _("Pending"),
              cups.IPP_JOB_HELD: _("Held"),
              cups.IPP_JOB_PROCESSING: _("Processing"),
              cups.IPP_JOB_STOPPED: _("Stopped"),
              cups.IPP_JOB_CANCELED: _("Canceled"),
              cups.IPP_JOB_ABORTED: _("Aborted"),
              cups.IPP_JOB_COMPLETED: _("Completed") }

    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Print test page")
        page = Gtk.VBox ()
        page.set_spacing (12)
        page.set_border_width (12)

        label = Gtk.Label ()
        label.set_alignment (0, 0)
        label.set_use_markup (True)
        label.set_line_wrap (True)
        page.pack_start (label, False, False, 0)
        self.main_label = label
        self.main_label_text = ('<span weight="bold" size="larger">' +
                                _("Test Page") + '</span>\n\n' +
                                _("Now print a test page.  If you are having "
                                  "problems printing a specific document, "
                                  "print that document now and mark the print "
                                  "job below."))

        hbox = Gtk.HButtonBox ()
        hbox.set_border_width (0)
        hbox.set_spacing (3)
        hbox.set_layout (Gtk.ButtonBoxStyle.START)
        self.print_button = Gtk.Button (_("Print Test Page"))
        hbox.pack_start (self.print_button, False, False, 0)

        self.cancel_button = Gtk.Button (_("Cancel All Jobs"))
        hbox.pack_start (self.cancel_button, False, False, 0)
        page.pack_start (hbox, False, False, 0)

        tv = Gtk.TreeView ()
        test_cell = Gtk.CellRendererToggle ()
        test = Gtk.TreeViewColumn (_("Test"), test_cell, active=0)
        job = Gtk.TreeViewColumn (_("Job"), Gtk.CellRendererText (), text=1)
        printer_cell = Gtk.CellRendererText ()
        printer = Gtk.TreeViewColumn (_("Printer"), printer_cell, text=2)
        name_cell = Gtk.CellRendererText ()
        name = Gtk.TreeViewColumn (_("Document"), name_cell, text=3)
        status = Gtk.TreeViewColumn (_("Status"), Gtk.CellRendererText (),
                                     text=4)
        test_cell.set_radio (False)
        self.test_cell = test_cell
        printer.set_resizable (True)
        printer_cell.set_property ("ellipsize", Pango.EllipsizeMode.END)
        printer_cell.set_property ("width-chars", 20)
        name.set_resizable (True)
        name_cell.set_property ("ellipsize", Pango.EllipsizeMode.END)
        name_cell.set_property ("width-chars", 20)
        status.set_resizable (True)
        tv.append_column (test)
        tv.append_column (job)
        tv.append_column (printer)
        tv.append_column (name)
        tv.append_column (status)
        tv.set_rules_hint (True)
        sw = Gtk.ScrolledWindow ()
        sw.set_policy (Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.set_shadow_type (Gtk.ShadowType.IN)
        sw.add (tv)
        self.treeview = tv
        page.pack_start (sw, False, False, 0)

        label = Gtk.Label(label=_("Did the marked print jobs print correctly?"))
        label.set_line_wrap (True)
        label.set_alignment (0, 0)
        page.pack_start (label, False, False, 0)

        vbox = Gtk.VBox ()
        vbox.set_spacing (6)
        self.yes = Gtk.RadioButton (label=_("Yes"))
        no = Gtk.RadioButton.new_with_label_from_widget (self.yes, _("No"))
        vbox.pack_start (self.yes, False, False, 0)
        vbox.pack_start (no, False, False, 0)
        page.pack_start (vbox, False, False, 0)
        self.persistent_answers = {}
        troubleshooter.new_page (page, self)

    def display (self):
        answers = self.troubleshooter.answers
        if not answers.has_key ('cups_queue'):
            return False

        parent = self.troubleshooter.get_window ()
        self.authconn = answers['_authenticated_connection']
        mediatype = None
        defaults = answers.get ('cups_printer_ppd_defaults', {})
        for opts in defaults.values ():
            for opt, value in opts.iteritems ():
                if opt == "MediaType":
                    mediatype = value
                    break

        if mediatype != None:
            mediatype_string = '\n\n' + (_("Remember to load paper of type "
                                           "'%s' into the printer first.") %
                                         mediatype)
        else:
            mediatype_string = ""

        label_text = self.main_label_text + mediatype_string
        self.main_label.set_markup (label_text)

        model = Gtk.ListStore (bool,
                               int,
                               str,
                               str,
                               str)
        self.treeview.set_model (model)
        self.job_to_iter = {}

        test_jobs = self.persistent_answers.get ('test_page_job_id', [])
        def get_jobs ():
            c = self.authconn
            try:
                r = ["job-id",
                     "job-name",
                     "job-state",
                     "job-printer-uri",
                     "printer-name"]
                jobs_dict = c.getJobs (which_jobs='not-completed',
                                       my_jobs=False,
                                       requested_attributes=r)
                completed_jobs_dict = c.getJobs (which_jobs='completed',
                                                 requested_attributes=r)
            except TypeError:
                # requested_attributes requires pycups 1.9.50
                jobs_dict = c.getJobs (which_jobs='not-completed',
                                       my_jobs=False)
                completed_jobs_dict = c.getJobs (which_jobs='completed')
            return (jobs_dict, completed_jobs_dict)

        self.op = TimedOperation (get_jobs, parent=parent)
        try:
            (jobs_dict, completed_jobs_dict) = self.op.run ()
        except (OperationCanceled, cups.IPPError):
            return False

        # We want to display the jobs in the queue for this printer...
        try:
            queue_uri_ending = "/" + self.troubleshooter.answers['cups_queue']
            jobs_on_this_printer = filter (lambda x:
                                               jobs_dict[x]['job-printer-uri'].\
                                               endswith (queue_uri_ending),
                                           jobs_dict.keys ())
        except:
            jobs_on_this_printer = []

        # ...as well as any other jobs we've previous submitted as test pages.
        jobs = list (set(test_jobs).union (set (jobs_on_this_printer)))

        completed_jobs_dict = None
        for job in jobs:
            try:
                j = jobs_dict[job]
            except KeyError:
                try:
                    j = completed_jobs_dict[job]
                except KeyError:
                    continue

            iter = model.append (None)
            self.job_to_iter[job] = iter
            model.set_value (iter, 0, job in test_jobs)
            model.set_value (iter, 1, job)
            self.update_job (job, j)

        return True

    def connect_signals (self, handler):
        self.print_sigid = self.print_button.connect ("clicked",
                                                      self.print_clicked)
        self.cancel_sigid = self.cancel_button.connect ("clicked",
                                                        self.cancel_clicked)
        self.test_sigid = self.test_cell.connect ('toggled',
                                                  self.test_toggled)

        def create_subscription ():
            c = self.authconn
            sub_id = c.createSubscription ("/",
                                           events=["job-created",
                                                   "job-completed",
                                                   "job-stopped",
                                                   "job-progress",
                                                   "job-state-changed"])
            return sub_id

        parent = self.troubleshooter.get_window ()
        self.op = TimedOperation (create_subscription, parent=parent)
        try:
            self.sub_id = self.op.run ()
        except (OperationCanceled, cups.IPPError):
            pass

        try:
            bus = dbus.SystemBus ()
        except:
            bus = None

        self.bus = bus
        if bus:
            bus.add_signal_receiver (self.handle_dbus_signal,
                                     path=DBUS_PATH,
                                     dbus_interface=DBUS_IFACE)

        self.timer = GLib.timeout_add_seconds (1, self.update_jobs_list)

    def disconnect_signals (self):
        if self.bus:
            self.bus.remove_signal_receiver (self.handle_dbus_signal,
                                             path=DBUS_PATH,
                                             dbus_interface=DBUS_IFACE)
                                             
        self.print_button.disconnect (self.print_sigid)
        self.cancel_button.disconnect (self.cancel_sigid)
        self.test_cell.disconnect (self.test_sigid)

        def cancel_subscription (sub_id):
            c = self.authconn
            c.cancelSubscription (sub_id)

        parent = self.troubleshooter.get_window ()
        self.op = TimedOperation (cancel_subscription,
                                  (self.sub_id,),
                                  parent=parent)
        try:
            self.op.run ()
        except (OperationCanceled, cups.IPPError):
            pass

        try:
            del self.sub_seq
        except:
            pass

        GLib.source_remove (self.timer)

    def collect_answer (self):
        if not self.displayed:
            return {}

        self.answers = self.persistent_answers.copy ()
        parent = self.troubleshooter.get_window ()
        success = self.yes.get_active ()
        self.answers['test_page_successful'] = success

        class collect_jobs:
            def __init__ (self, model):
                self.jobs = []
                model.foreach (self.each, None)

            def each (self, model, path, iter, user_data):
                self.jobs.append (model.get (iter, 0, 1, 2, 3, 4))

        model = self.treeview.get_model ()
        jobs = collect_jobs (model).jobs
        def collect_attributes (jobs):
            job_attrs = None
            c = self.authconn
            with_attrs = []
            for (test, jobid, printer, doc, status) in jobs:
                attrs = None
                if test:
                    try:
                        attrs = c.getJobAttributes (jobid)
                    except AttributeError:
                        # getJobAttributes was introduced in pycups 1.9.35.
                        if job_attrs == None:
                            job_attrs = c.getJobs (which_jobs='all')

                        attrs = self.job_attrs[jobid]

                with_attrs.append ((test, jobid, printer, doc, status, attrs))

            return with_attrs

        self.op = TimedOperation (collect_attributes,
                                  (jobs,),
                                  parent=parent)
        try:
            with_attrs = self.op.run ()
            self.answers['test_page_job_status'] = with_attrs
        except (OperationCanceled, cups.IPPError):
            pass

        return self.answers

    def cancel_operation (self):
        self.op.cancel ()

        # Abandon the CUPS connection and make another.
        answers = self.troubleshooter.answers
        factory = answers['_authenticated_connection_factory']
        self.authconn = factory.get_connection ()
        self.answers['_authenticated_connection'] = self.authconn

    def handle_dbus_signal (self, *args):
        debugprint ("D-Bus signal caught: updating jobs list soon")
        GLib.source_remove (self.timer)
        self.timer = GLib.timeout_add (200, self.update_jobs_list)

    def update_job (self, jobid, job_dict):
        iter = self.job_to_iter[jobid]
        model = self.treeview.get_model ()
        try:
            printer_name = job_dict['printer-name']
        except KeyError:
            try:
                uri = job_dict['job-printer-uri']
                r = uri.rfind ('/')
                printer_name = uri[r + 1:]
            except KeyError:
                printer_name = None

        if printer_name != None:
            model.set_value (iter, 2, printer_name)

        model.set_value (iter, 3, job_dict['job-name'])
        model.set_value (iter, 4, self.STATE[job_dict['job-state']])

    def print_clicked (self, widget):
        now = time.time ()
        tt = time.localtime (now)
        when = time.strftime ("%d/%b/%Y:%T %z", tt)
        self.persistent_answers['test_page_attempted'] = when
        answers = self.troubleshooter.answers
        parent = self.troubleshooter.get_window ()

        def print_test_page (*args, **kwargs):
            factory = answers['_authenticated_connection_factory']
            c = factory.get_connection ()
            return c.printTestPage (*args, **kwargs)

        tmpfname = None
        mimetypes = [None, 'text/plain']
        for mimetype in mimetypes:
            try:
                if mimetype == None:
                    # Default test page.
                    self.op = TimedOperation (print_test_page,
                                              (answers['cups_queue'],),
                                              parent=parent)
                    jobid = self.op.run ()
                elif mimetype == 'text/plain':
                    (tmpfd, tmpfname) = tempfile.mkstemp ()
                    os.write (tmpfd, "This is a test page.\n")
                    os.close (tmpfd)
                    self.op = TimedOperation (print_test_page,
                                              (answers['cups_queue'],),
                                              kwargs={'file': tmpfname,
                                                      'format': mimetype},
                                              parent=parent)
                    jobid = self.op.run ()
                    try:
                        os.unlink (tmpfname)
                    except OSError:
                        pass

                    tmpfname = None

                jobs = self.persistent_answers.get ('test_page_job_id', [])
                jobs.append (jobid)
                self.persistent_answers['test_page_job_id'] = jobs
                break
            except OperationCanceled:
                self.persistent_answers['test_page_submit_failure'] = 'cancel'
                break
            except RuntimeError:
                self.persistent_answers['test_page_submit_failure'] = 'connect'
                break
            except cups.IPPError as e:
                (e, s) = e.args
                if isinstance(s, bytes):
                    s = s.decode('utf-8', 'replace')
                if (e == cups.IPP_DOCUMENT_FORMAT and
                    mimetypes.index (mimetype) < (len (mimetypes) - 1)):
                    # Try next format.
                    if tmpfname != None:
                        os.unlink (tmpfname)
                        tmpfname = None
                    continue

                self.persistent_answers['test_page_submit_failure'] = (e, s)
                show_error_dialog (_("Error submitting test page"),
                                   _("There was an error during the CUPS "
                                     "operation: '%s'.") % s,
                                   self.troubleshooter.get_window ())
                break

    def cancel_clicked (self, widget):
        self.persistent_answers['test_page_jobs_cancelled'] = True
        jobids = []
        for jobid, iter in self.job_to_iter.iteritems ():
            jobids.append (jobid)

        def cancel_jobs (jobids):
            c = self.authconn
            for jobid in jobids:
                try:
                    c.cancelJob (jobid)
                except cups.IPPError as e:
                    (e, s) = e.args
                    if isinstance(s, bytes):
                        s = s.decode('utf-8', 'replace')
                    if e != cups.IPP_NOT_POSSIBLE:
                        self.persistent_answers['test_page_cancel_failure'] = (e, s)

        self.op = TimedOperation (cancel_jobs,
                                  (jobids,),
                                  parent=self.troubleshooter.get_window ())
        try:
            self.op.run ()
        except (OperationCanceled, cups.IPPError):
            pass

    def test_toggled (self, cell, path):
        model = self.treeview.get_model ()
        iter = model.get_iter (path)
        active = model.get_value (iter, 0)
        model.set_value (iter, 0, not active)

    def update_jobs_list (self):
        def get_notifications (self):
            c = self.authconn
            try:
                notifications = c.getNotifications ([self.sub_id],
                                                    [self.sub_seq + 1])
            except AttributeError:
                notifications = c.getNotifications ([self.sub_id])

            return notifications

        # Enter the GDK lock.  We need to do this because we were
        # called from a timeout.
        Gdk.threads_enter ()

        parent = self.troubleshooter.get_window ()
        self.op = TimedOperation (get_notifications,
                                  (self,),
                                  parent=parent)
        try:
            notifications = self.op.run ()
        except (OperationCanceled, cups.IPPError):
            Gdk.threads_leave ()
            return True

        answers = self.troubleshooter.answers
        model = self.treeview.get_model ()
        queue = answers['cups_queue']
        test_jobs = self.persistent_answers.get('test_page_job_id', [])
        for event in notifications['events']:
            seq = event['notify-sequence-number']
            try:
                if seq <= self.sub_seq:
                    # Work around a bug in pycups < 1.9.34
                    continue
            except AttributeError:
                pass
            self.sub_seq = seq
            job = event['notify-job-id']

            nse = event['notify-subscribed-event']
            if nse == 'job-created':
                if (job in test_jobs or
                    event['printer-name'] == queue):
                    iter = model.append (None)
                    self.job_to_iter[job] = iter
                    model.set_value (iter, 0, True)
                    model.set_value (iter, 1, job)
                else:
                    continue
            elif not self.job_to_iter.has_key (job):
                continue

            if (job in test_jobs and
                nse in ["job-stopped", "job-completed"]):
                comp = self.persistent_answers.get ('test_page_completions', [])
                comp.append ((job, event['notify-text']))
                self.persistent_answers['test_page_completions'] = comp

            self.update_job (job, event)

        # Update again when we're told to. (But we might update sooner if
        # there is a D-Bus signal.)
        GLib.source_remove (self.timer)
        self.timer = GLib.timeout_add_seconds (
            notifications['notify-get-interval'],
            self.update_jobs_list)
        debugprint ("Update again in %ds" %
                    notifications['notify-get-interval'])
        Gdk.threads_leave ()
        return False

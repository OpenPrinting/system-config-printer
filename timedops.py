#!/usr/bin/env python

## Copyright (C) 2008, 2009 Red Hat, Inc.
## Copyright (C) 2008, 2009 Tim Waugh <twaugh@redhat.com>

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

import gobject
import gtk
import subprocess
import threading
from gettext import gettext as _
from debug import *

class OperationCanceled(RuntimeError):
    pass

class Timed:
    def run (self):
        pass

    def cancel (self):
        return False

class TimedSubprocess(Timed):
    def __init__ (self, timeout=60000, parent=None, show_dialog=True,
                  **args):
        self.subp = subprocess.Popen (**args)
        self.output = dict()
        self.io_source = []
        self.watchers = 2
        self.timeout = timeout
        self.parent = parent
        self.show_dialog = show_dialog
        for f in [self.subp.stdout, self.subp.stderr]:
            if f != None:
                source = gobject.io_add_watch (f,
                                               gobject.IO_IN |
                                               gobject.IO_HUP |
                                               gobject.IO_ERR,
                                               self.watcher)
                self.io_source.append (source)

        self.wait_window = None

    def run (self):
        if self.show_dialog:
            self.wait_source = gobject.timeout_add_seconds (
                1,
                self.show_wait_window)

        self.timeout_source = gobject.timeout_add (self.timeout,
                                                   self.do_timeout)
        gtk.main ()
        gobject.source_remove (self.timeout_source)
        if self.show_dialog:
            gobject.source_remove (self.wait_source)
        for source in self.io_source:
            gobject.source_remove (source)
        if self.wait_window != None:
            self.wait_window.destroy ()
        return (self.output.get (self.subp.stdout, '').split ('\n'),
                self.output.get (self.subp.stderr, '').split ('\n'),
                self.subp.poll ())

    def do_timeout (self):
        gtk.main_quit ()
        return False

    def watcher (self, source, condition):
        if condition & gobject.IO_IN:
            buffer = self.output.get (source, '')
            buffer += source.read ()
            self.output[source] = buffer

        if condition & gobject.IO_HUP:
            self.watchers -= 1
            if self.watchers == 0:
                gtk.main_quit ()
                return False

        return True

    def show_wait_window (self):
        wait = gtk.MessageDialog (self.parent,
                                  gtk.DIALOG_MODAL |
                                  gtk.DIALOG_DESTROY_WITH_PARENT,
                                  gtk.MESSAGE_INFO,
                                  gtk.BUTTONS_CANCEL,
                                  _("Please wait"))
        wait.connect ("delete_event", lambda *args: False)
        wait.connect ("response", self.wait_window_response)
        if self.parent:
            wait.set_transient_for (self.parent)
        wait.set_position (gtk.WIN_POS_CENTER_ON_PARENT)
        wait.format_secondary_text (_("Gathering information"))
        wait.show_all ()
        self.wait_window = wait
        return False

    def wait_window_response (self, dialog, response):
        if response == gtk.RESPONSE_CANCEL:
            self.cancel ()

    def cancel (self):
        if self.watchers > 0:
            debugprint ("Command canceled")
            gtk.main_quit ()
            self.watchers = 0

        return False

class OperationThread(threading.Thread):
    def __init__ (self, target=None, args=(), kwargs={}):
        threading.Thread.__init__ (self)
        self.setDaemon (True)
        self.target = target
        self.args = args
        self.kwargs = kwargs
        self.exception = None
        self.result = None

    def run (self):
        try:
            debugprint ("Calling %s" % self.target)
            self.result = self.target (*self.args, **self.kwargs)
            debugprint ("Done")
        except Exception, e:
            debugprint ("Caught exception %s" % e)
            self.exception = e

    def collect_result (self):
        if self.isAlive ():
            # We've been canceled.
            raise OperationCanceled()

        if self.exception:
            raise self.exception

        return self.result

class TimedOperation(Timed):
    def __init__ (self, target, args=(), kwargs={}, parent=None,
                  show_dialog=False, callback=None, context=None):
        self.wait_window = None
        self.parent = parent
        self.show_dialog = show_dialog
        self.callback = callback
        self.context = context
        self.thread = OperationThread (target=target,
                                       args=args,
                                       kwargs=kwargs)
        self.thread.start ()

        self.use_callback = callback != None
        if self.use_callback:
            self.timeout_source = gobject.timeout_add (50, self._check_thread)

    def run (self):
        if self.use_callback:
            raise RuntimeError

        if self.show_dialog:
            wait = gtk.MessageDialog (self.parent,
                                      gtk.DIALOG_MODAL |
                                      gtk.DIALOG_DESTROY_WITH_PARENT,
                                      gtk.MESSAGE_INFO,
                                      gtk.BUTTONS_CANCEL,
                                      _("Please wait"))
            wait.connect ("delete_event", lambda *args: False)
            wait.connect ("response", self._wait_window_response)
            if self.parent:
                wait.set_transient_for (self.parent)

            wait.set_position (gtk.WIN_POS_CENTER_ON_PARENT)
            wait.format_secondary_text (_("Gathering information"))
            wait.show_all ()

        self.timeout_source = gobject.timeout_add (50, self._check_thread)
        gtk.main ()
        gobject.source_remove (self.timeout_source)
        if self.show_dialog:
            wait.destroy ()

        return self.thread.collect_result ()

    def _check_thread (self):
        if self.thread.isAlive ():
            # Thread still running.
            return True

        # Thread has finished.  Stop the sub-loop or trigger callback.
        if self.use_callback:
            if self.callback != None:
                if self.context != None:
                    self.callback (self.thread.result, self.thread.exception,
                                   self.context)
                else:
                    self.callback (self.thread.result, self.thread.exception)
        else:
            gtk.main_quit ()

        return False

    def _wait_window_response (self, dialog, response):
        if response == gtk.RESPONSE_CANCEL:
            self.cancel ()

    def cancel (self):
        debugprint ("Command canceled")
        if self.use_callback:
            self.callback = None
        else:
            gtk.main_quit ()

        return False

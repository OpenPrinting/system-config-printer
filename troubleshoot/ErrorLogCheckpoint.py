#!/usr/bin/python

## Printing troubleshooter

## Copyright (C) 2008, 2009 Red Hat, Inc.
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

from gi.repository import Gtk

import cups
import os
import tempfile
import time
from timedops import TimedOperation, OperationCanceled
from base import *
class ErrorLogCheckpoint(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Error log checkpoint")
        page = self.initial_vbox (_("Debugging"),
                                  _("This step will enable debugging output "
                                    "from the CUPS scheduler.  This may "
                                    "cause the scheduler to restart.  Click "
                                    "the button below to enable debugging."))
        button = Gtk.Button (_("Enable Debugging"))
        buttonbox = Gtk.HButtonBox ()
        buttonbox.set_border_width (0)
        buttonbox.set_layout (Gtk.ButtonBoxStyle.START)
        buttonbox.pack_start (button, False, False, 0)
        self.button = button
        page.pack_start (buttonbox, False, False, 0)
        self.label = Gtk.Label ()
        self.label.set_alignment (0, 0)
        self.label.set_line_wrap (True)
        page.pack_start (self.label, False, False, 0)
        troubleshooter.new_page (page, self)
        self.persistent_answers = {}

    def __del__ (self):
        if not self.persistent_answers.get ('error_log_debug_logging_set',
                                            False):
            return

        c = self.troubleshooter.answers['_authenticated_connection']
        c._set_lock (False)
        settings = c.adminGetServerSettings ()
        if len (settings.keys ()) == 0:
            return

        settings[cups.CUPS_SERVER_DEBUG_LOGGING] = '0'
        answers = self.troubleshooter.answers
        orig_settings = self.persistent_answers['cups_server_settings']
        settings['MaxLogSize'] = orig_settings.get ('MaxLogSize', '2000000')
        c.adminSetServerSettings (settings)

    def display (self):
        self.answers = {}
        answers = self.troubleshooter.answers
        if not answers['cups_queue_listed']:
            return False

        self.authconn = answers['_authenticated_connection']
        parent = self.troubleshooter.get_window ()

        def getServerSettings ():
            # Fail if auth required.
            cups.setPasswordCB (lambda x: '')
            cups.setServer ('')
            c = cups.Connection ()
            return c.adminGetServerSettings ()

        try:
            self.op = TimedOperation (getServerSettings, parent=parent)
            settings = self.op.run ()
        except RuntimeError:
            return False
        except cups.IPPError:
            settings = {}

        self.forward_allowed = False
        self.label.set_text ('')
        if len (settings.keys ()) == 0:
            # Requires root
            return True
        else:
            self.persistent_answers['cups_server_settings'] = settings

        try:
            if int (settings[cups.CUPS_SERVER_DEBUG_LOGGING]) != 0:
                # Already enabled
                return False
        except KeyError:
            pass
        except ValueError:
            pass

        return True

    def connect_signals (self, handler):
        self.button_sigid = self.button.connect ('clicked', self.enable_clicked,
                                                 handler)

    def disconnect_signals (self):
        self.button.disconnect (self.button_sigid)

    def collect_answer (self):
        answers = self.troubleshooter.answers
        if not answers['cups_queue_listed']:
            return {}

        parent = self.troubleshooter.get_window ()
        self.answers.update (self.persistent_answers)
        if self.answers.has_key ('error_log_checkpoint'):
            return self.answers

        (tmpfd, tmpfname) = tempfile.mkstemp ()
        os.close (tmpfd)
        try:
            self.op = TimedOperation (self.authconn.getFile,
                                      args=('/admin/log/error_log', tmpfname),
                                      parent=parent)
            self.op.run ()
        except RuntimeError:
            try:
                os.remove (tmpfname)
            except OSError:
                pass

            return self.answers
        except cups.IPPError:
            try:
                os.remove (tmpfname)
            except OSError:
                pass

            return self.answers

        statbuf = os.stat (tmpfname)
        os.remove (tmpfname)
        self.answers['error_log_checkpoint'] = statbuf[6]
        self.persistent_answers['error_log_checkpoint'] = statbuf[6]
        return self.answers

    def can_click_forward (self):
        return self.forward_allowed

    def enable_clicked (self, button, handler):
        parent = self.troubleshooter.get_window ()
        self.troubleshooter.busy ()
        try:
            self.op = TimedOperation (self.authconn.adminGetServerSettings,
                                      parent=parent)
            settings = self.op.run ()
        except (cups.IPPError, OperationCanceled):
            self.troubleshooter.ready ()
            self.forward_allowed = True
            handler (button)
            return

        self.persistent_answers['cups_server_settings'] = settings.copy ()
        MAXLOGSIZE='MaxLogSize'
        try:
            prev_debug = int (settings[cups.CUPS_SERVER_DEBUG_LOGGING])
        except KeyError:
            prev_debug = 0
        try:
            prev_logsize = int (settings[MAXLOGSIZE])
        except (KeyError, ValueError):
            prev_logsize = -1

        if prev_debug == 0 or prev_logsize != '0':
            settings[cups.CUPS_SERVER_DEBUG_LOGGING] = '1'
            settings[MAXLOGSIZE] = '0'
            success = False

            def set_settings (connection, settings):
                connection.adminSetServerSettings (settings)

                # Now reconnect.
                attempt = 1
                while attempt <= 5:
                    try:
                        time.sleep (1)
                        connection._connect ()
                        break
                    except RuntimeError:
                        # Connection failed
                        attempt += 1

            try:
                debugprint ("Settings to set: " + repr (settings))
                self.op = TimedOperation (set_settings,
                                          args=(self.authconn, settings,),
                                          parent=parent)
                self.op.run ()
                success = True
            except cups.IPPError:
                pass
            except RuntimeError:
                pass

            if success:
                self.persistent_answers['error_log_debug_logging_set'] = True
                self.label.set_text (_("Debug logging enabled."))
        else:
            self.label.set_text (_("Debug logging was already enabled."))

        self.forward_allowed = True
        self.troubleshooter.ready ()
        handler (button)

    def cancel_operation (self):
        self.op.cancel ()

        # Abandon the CUPS connection and make another.
        answers = self.troubleshooter.answers
        factory = answers['_authenticated_connection_factory']
        self.authconn = factory.get_connection ()
        self.answers['_authenticated_connection'] = self.authconn

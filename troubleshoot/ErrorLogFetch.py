#!/usr/bin/python

## Printing troubleshooter

## Copyright (C) 2008, 2010 Red Hat, Inc.
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

from gi.repository import Gtk

import cups
import os
import tempfile
import time
from timedops import TimedOperation
from base import *
class ErrorLogFetch(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Error log fetch")
        troubleshooter.new_page (Gtk.Label (), self)
        self.persistent_answers = {}

    def display (self):
        answers = self.troubleshooter.answers
        parent = self.troubleshooter.get_window ()
        self.answers = {}
        try:
            checkpoint = answers['error_log_checkpoint']
        except KeyError:
            checkpoint = None

        if self.persistent_answers.has_key ('error_log'):
            checkpoint = None

        def fetch_log (c):
            prompt = c._get_prompt_allowed ()
            c._set_prompt_allowed (False)
            c._connect ()
            (tmpfd, tmpfname) = tempfile.mkstemp ()
            os.close (tmpfd)
            success = False
            try:
                c.getFile ('/admin/log/error_log', tmpfname)
                success = True
            except cups.HTTPError:
                try:
                    os.remove (tmpfname)
                except OSError:
                    pass

            c._set_prompt_allowed (prompt)
            if success:
                return tmpfname
            return None

        self.authconn = self.troubleshooter.answers['_authenticated_connection']
        if answers.has_key ('error_log_debug_logging_set'):
            try:
                self.op = TimedOperation (self.authconn.adminGetServerSettings,
                                          parent=parent)
                settings = self.op.run ()
            except cups.IPPError:
                return False

            settings[cups.CUPS_SERVER_DEBUG_LOGGING] = '0'
            orig_settings = answers['cups_server_settings']
            settings['MaxLogSize'] = orig_settings.get ('MaxLogSize', '2000000')
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

                self.op = TimedOperation (set_settings,
                                          (self.authconn, settings),
                                          parent=parent)
                self.op.run ()
                self.persistent_answers['error_log_debug_logging_unset'] = True
            except cups.IPPError:
                pass

        if checkpoint != None:
            self.op = TimedOperation (fetch_log,
                                      (self.authconn,),
                                      parent=parent)
            tmpfname = self.op.run ()
            if tmpfname != None:
                f = file (tmpfname)
                f.seek (checkpoint)
                lines = f.readlines ()
                os.remove (tmpfname)
                self.answers = { 'error_log': map (lambda x: x.strip (),
                                                   lines) }

        return False

    def collect_answer (self):
        answers = self.persistent_answers.copy ()
        answers.update (self.answers)
        return answers

    def cancel_operation (self):
        self.op.cancel ()

        # Abandon the CUPS connection and make another.
        answers = self.troubleshooter.answers
        factory = answers['_authenticated_connection_factory']
        self.authconn = factory.get_connection ()
        self.answers['_authenticated_connection'] = self.authconn

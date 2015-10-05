#!/usr/bin/python3

## Printing troubleshooter

## Copyright (C) 2008, 2010, 2014 Red Hat, Inc.
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
from tempfile import NamedTemporaryFile
import datetime
import time
from timedops import TimedOperation
from .base import *

try:
    from systemd import journal
except:
    journal = False

class ErrorLogFetch(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Error log fetch")
        page = self.initial_vbox (_("Retrieve Journal Entries"),
                                  _("No system journal entries were found. "
                                    "This may be because you are not an "
                                    "administrator. To fetch journal entries "
                                    "please run this command:"))
        self.entry = Gtk.Entry ()
        self.entry.set_editable (False)
        page.pack_start (self.entry, False, False, 0)
        troubleshooter.new_page (page, self)
        self.persistent_answers = {}

    def display (self):
        answers = self.troubleshooter.answers
        parent = self.troubleshooter.get_window ()
        self.answers = {}
        checkpoint = answers.get ('error_log_checkpoint')
        cursor = answers.get ('error_log_cursor')
        timestamp = answers.get ('error_log_timestamp')

        if ('error_log' in self.persistent_answers or
            'journal' in self.persistent_answers):
            checkpoint = None
            cursor = None

        def fetch_log (c):
            prompt = c._get_prompt_allowed ()
            c._set_prompt_allowed (False)
            c._connect ()
            with NamedTemporaryFile (delete=False) as tmpf:
                success = False
                try:
                    c.getFile ('/admin/log/error_log', tmpf.file)
                    success = True
                except cups.HTTPError:
                    try:
                        os.remove (tmpf.file)
                    except OSError:
                        pass

                c._set_prompt_allowed (prompt)
                if success:
                    return tmpf.file

            return None

        now = datetime.datetime.fromtimestamp (time.time ()).strftime ("%F %T")
        self.authconn = self.troubleshooter.answers['_authenticated_connection']
        if 'error_log_debug_logging_set' in answers:
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

        self.answers = {}
        if journal and cursor is not None:
            def journal_format (x):
                try:
                    priority = "XACEWNIDd"[x['PRIORITY']]
                except (IndexError, TypeError):
                    priority = " "

                return (priority + " " +
                        x['__REALTIME_TIMESTAMP'].strftime("[%m/%b/%Y:%T]") +
                        " " + x['MESSAGE'])

            r = journal.Reader ()
            r.seek_cursor (cursor)
            r.add_match (_SYSTEMD_UNIT="cups.service")
            self.answers['journal'] = [journal_format (x) for x in r]

        if checkpoint is not None:
            self.op = TimedOperation (fetch_log,
                                      (self.authconn,),
                                      parent=parent)
            tmpfname = self.op.run ()
            if tmpfname is not None:
                f = open (tmpfname)
                f.seek (checkpoint)
                lines = f.readlines ()
                os.remove (tmpfname)
                self.answers = { 'error_log': [x.strip () for x in lines] }

        if (len (self.answers.get ('journal', [])) +
            len (self.answers.get ('error_log', []))) == 0:
            cmd = ("su -c 'journalctl -u cups.service "
                   "--since=\"%s\" --until=\"%s\"' > troubleshoot-logs.txt" %
                   (timestamp, now))
            self.entry.set_text (cmd)
            return True

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

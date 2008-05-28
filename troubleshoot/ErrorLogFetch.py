#!/usr/bin/env python

## Printing troubleshooter

## Copyright (C) 2008 Red Hat, Inc.
## Copyright (C) 2008 Tim Waugh <twaugh@redhat.com>

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
import os
import tempfile
from base import *
from base import _
class ErrorLogFetch(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Error log fetch")
        page = self.initial_vbox (_("Debugging"),
                                  _("I would like to disable debugging output "
                                    "from the CUPS scheduler.  This may "
                                    "cause the scheduler to restart.  Click "
                                    "the button below to disable debugging."))
        button = gtk.Button (_("Disable Debugging"))
        buttonbox = gtk.HButtonBox ()
        buttonbox.set_border_width (0)
        buttonbox.set_layout (gtk.BUTTONBOX_START)
        buttonbox.pack_start (button, False, False, 0)
        self.button = button
        page.pack_start (buttonbox, False, False, 0)
        self.label = gtk.Label ()
        self.label.set_alignment (0, 0)
        self.label.set_line_wrap (True)
        page.pack_start (self.label, False, False, 0)
        troubleshooter.new_page (page, self)
        self.persistent_answers = {}

    def display (self):
        answers = self.troubleshooter.answers
        self.answers = {}
        try:
            checkpoint = answers['error_log_checkpoint']
        except KeyError:
            checkpoint = None

        if self.persistent_answers.has_key ('error_log'):
            checkpoint = None

        if checkpoint != None:
            c = self.troubleshooter.answers['_authenticated_connection']
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
                os.remove (tmpfname)

            c._set_prompt_allowed (prompt)
            if success:
                f = file (tmpfname)
                f.seek (checkpoint)
                lines = f.readlines ()
                os.remove (tmpfname)
                self.answers = { 'error_log': map (lambda x: x.strip (),
                                                   lines) }

        if answers.has_key ('error_log_debug_logging_set'):
            self.label.set_text ('')
            return True

        return False

    def connect_signals (self, handler):
        self.button_sigid = self.button.connect ('clicked', self.button_clicked)

    def disconnect_signals (self):
        self.button.disconnect (self.button_sigid)

    def collect_answer (self):
        answers = self.persistent_answers.copy ()
        answers.update (self.answers)
        return answers

    def button_clicked (self, button):
        c = self.troubleshooter.answers['_authenticated_connection']
        try:
            settings = c.adminGetServerSettings ()
        except cups.IPPError:
            return

        settings[cups.CUPS_SERVER_DEBUG_LOGGING] = '0'
        answers = self.troubleshooter.answers
        orig_settings = answers['cups_server_settings']
        settings['MaxLogSize'] = orig_settings.get ('MaxLogSize', '2000000')
        success = False
        try:
            c.adminSetServerSettings (settings)
            success = True
        except cups.IPPError:
            pass

        if success:
            self.persistent_answers['error_log_debug_logging_unset'] = True
            self.label.set_text (_("Debug logging disabled."))

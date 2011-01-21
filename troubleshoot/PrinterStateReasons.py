#!/usr/bin/python

## Printing troubleshooter

## Copyright (C) 2008, 2009, 2010, 2011 Red Hat, Inc.
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
import ppdcache
import statereason
from timedops import TimedOperation
from base import *
class PrinterStateReasons(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Printer state reasons")
        page = self.initial_vbox (_("Status Messages"),
                                  _("There are status messages associated with "
                                    "this queue."))
        self.label = Gtk.Label ()
        self.label.set_alignment (0, 0)
        self.label.set_line_wrap (True)
        page.pack_start (self.label, False, False, 0)

        troubleshooter.new_page (page, self)

    def display (self):
        troubleshooter = self.troubleshooter
        try:
            queue = troubleshooter.answers['cups_queue']
        except KeyError:
            return False

        parent = self.troubleshooter.get_window ()
        cups.setServer ('')
        self.op = TimedOperation (cups.Connection, parent=parent)
        c = self.op.run ()
        self.op = TimedOperation (c.getPrinterAttributes,
                                  args=(queue,),
                                  parent=parent)
        dict = self.op.run ()

        the_ppdcache = ppdcache.PPDCache ()

        text = ''
        state_message = dict['printer-state-message']
        if state_message:
            text += _("The printer's state message is: '%s'.") % state_message
            text += '\n\n'

        state_reasons_list = dict['printer-state-reasons']
        if type (state_reasons_list) == unicode:
            state_reasons_list = [state_reasons_list]

        self.state_message = state_message
        self.state_reasons = state_reasons_list

        human_readable_errors = []
        human_readable_warnings = []
        for reason in state_reasons_list:
            if reason == "none":
                continue

            r = statereason.StateReason (queue, reason, the_ppdcache)
            (title, description) = r.get_description ()
            level = r.get_level ()
            if level == statereason.StateReason.ERROR:
                human_readable_errors.append (description)
            elif level == statereason.StateReason.WARNING:
                human_readable_warnings.append (description)

        if human_readable_errors:
            text += _("Errors are listed below:") + '\n'
            text += reduce (lambda x, y: x + "\n" + y, human_readable_errors)
            text += '\n\n'

        if human_readable_warnings:
            text += _("Warnings are listed below:") + '\n'
            text += reduce (lambda x, y: x + "\n" + y, human_readable_warnings)

        self.label.set_text (text)
        if (state_message == '' and
            len (human_readable_errors) == 0 and
            len (human_readable_warnings) == 0):
            return False

        # If this screen has been show before, don't show it again if
        # nothing changed.
        if troubleshooter.answers.has_key ('printer-state-message'):
            if (troubleshooter.answers['printer-state-message'] ==
                self.state_message and
                troubleshooter.answers['printer-state-reasons'] ==
                self.state_reasons):
                return False

        return True

    def collect_answer (self):
        if not self.displayed:
            return {}

        return { 'printer-state-message': self.state_message,
                 'printer-state-reasons': self.state_reasons }

    def cancel_operation (self):
        self.op.cancel ()

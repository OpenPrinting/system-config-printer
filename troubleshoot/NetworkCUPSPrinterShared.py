#!/usr/bin/python

## Printing troubleshooter

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
## Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import cups
from timedops import TimedOperation
from base import *
class NetworkCUPSPrinterShared(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Queue not shared?")
        page = self.initial_vbox (_("Queue Not Shared"),
                                  _("The CUPS printer on the server is not "
                                    "shared."))
        troubleshooter.new_page (page, self)

    def display (self):
        self.answers = {}
        answers = self.troubleshooter.answers
        if (answers.has_key ('remote_cups_queue_listed') and
            answers['remote_cups_queue_listed'] == False):
            return False

        parent = self.troubleshooter.get_window ()
        if not answers.has_key ('remote_cups_queue_attributes'):
            if not (answers.has_key ('remote_server_try_connect') and
                    answers.has_key ('remote_cups_queue')):
                return False

            try:
                host = answers['remote_server_try_connect']
                self.op = TimedOperation (cups.Connection,
                                          kwargs={"host": host},
                                          parent=parent)
                c = self.op.run ()
                self.op = TimedOperation (c.getPrinterAttributes,
                                          args=(answers['remote_cups_queue'],),
                                          parent=parent)
                attr = self.op.run ()
            except RuntimeError:
                return False
            except cups.IPPError:
                return False

            self.answers['remote_cups_queue_attributes'] = attr
        else:
            attr = answers['remote_cups_queue_attributes']

        if attr.has_key ('printer-is-shared'):
            # CUPS >= 1.2
            if not attr['printer-is-shared']:
                return True

        return False

    def can_click_forward (self):
        return False

    def collect_answer (self):
        return self.answers

    def cancel_operation (self):
        self.op.cancel ()

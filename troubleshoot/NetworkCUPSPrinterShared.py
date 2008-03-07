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
from base import *
from base import _
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

        if not answers.has_key ('remote_cups_queue_attributes'):
            if not (answers.has_key ('remote_server_try_connect') and
                    answers.has_key ('remote_cups_queue')):
                return False

            try:
                cups.setServer (answers['remote_server_try_connect'])
                c = cups.Connection ()
                attr = c.getPrinterAttributes (answers['remote_cups_queue'])
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

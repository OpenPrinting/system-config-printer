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
class SchedulerNotRunning(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Scheduler not running?")
        page = self.initial_vbox (_("CUPS Service Stopped"),
                                  _("The CUPS print spooler does not appear "
                                    "to be running.  To correct this, choose "
                                    "System->Administration->Services from "
                                    "the main menu and look for the `cups' "
                                    "service."))
        troubleshooter.new_page (page, self)

    def display (self):
        self.answers = {}
        if self.troubleshooter.answers['cups_queue_listed']:
            return False

        # Find out if CUPS is running.
        failure = False
        try:
            c = cups.Connection ()
        except RuntimeError:
            failure = True

        self.answers['cups_connection_failure'] = failure
        return failure

    def can_click_forward (self):
        return False

    def collect_answer (self):
        return self.answers

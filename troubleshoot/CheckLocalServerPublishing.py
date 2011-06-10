#!/usr/bin/python

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
## Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import cups
from timedops import TimedOperation
from base import *
class CheckLocalServerPublishing(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Is local server publishing?")
        vbox = self.initial_vbox (_("Server Not Exporting Printers"),
                                  _("Although one or more printers are marked "
                                    "as being shared, this print server is "
                                    "not exporting shared printers to the "
                                    "network.") + '\n\n' +
                                  _("Enable the 'Publish shared printers "
                                    "connected to this system' option in "
                                    "the server settings using the printing "
                                    "administration tool.") + ' ' +
                                  _(TEXT_start_print_admin_tool))
        troubleshooter.new_page (vbox, self)

    def display (self):
        self.answers = {}
        cups.setServer ('')
        parent = self.troubleshooter.get_window ()
        try:
            c = self.timedop (cups.Connection, parent=parent).run ()
            printers = self.timedop (c.getPrinters, parent=parent).run ()
            if len (printers) == 0:
                return False

            for name, printer in printers.iteritems ():
                if printer.get ('printer-is-shared', False):
                    break

            attr = self.timedop (c.getPrinterAttributes,
                                 args=(name,),
                                 parent=parent).run ()
        except RuntimeError:
            return False
        except cups.IPPError:
            return False

        if not printer.get ('printer-is-shared', False):
            return False

        if attr.get ('server-is-sharing-printers', True):
            # server-is-sharing-printers is in CUPS 1.4
            return False

        return True

    def collect_answer (self):
        if self.displayed:
            return { 'local_server_exporting_printers': False }

        return {}

    def cancel_operation (self):
        self.op.cancel ()

    def timedop (self, *args, **kwargs):
        self.op = TimedOperation (*args, **kwargs)
        return self.op

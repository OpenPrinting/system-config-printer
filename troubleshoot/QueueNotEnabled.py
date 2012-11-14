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

from gi.repository import Gtk

import cups
from base import *
class QueueNotEnabled(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Queue not enabled?")
        self.label = Gtk.Label ()
        solution = Gtk.VBox ()
        self.label.set_line_wrap (True)
        self.label.set_alignment (0, 0)
        solution.pack_start (self.label, False, False, 0)
        solution.set_border_width (12)
        troubleshooter.new_page (solution, self)

    def display (self):
        answers =  self.troubleshooter.answers
        if not answers['cups_queue_listed']:
            return False

        if answers['is_cups_class']:
            queue = answers['cups_class_dict']
        else:
            queue = answers['cups_printer_dict']

        enabled = queue['printer-state'] != cups.IPP_PRINTER_STOPPED
        if enabled:
            return False

        if answers['cups_printer_remote']:
            attrs = answers['remote_cups_queue_attributes']
            reason = attrs['printer-state-message']
        else:
            reason = queue['printer-state-message']

        if reason:
            reason = _("The reason given is: '%s'.") % reason
        else:
            reason = _("This may be due to the printer being disconnected or "
                       "switched off.")

        text = ('<span weight="bold" size="larger">' +
                _("Queue Not Enabled") + '</span>\n\n' +
                _("The queue '%s' is not enabled.") %
                answers['cups_queue'])

        if reason:
            text += ' ' + reason

        if not answers['cups_printer_remote']:
            text += '\n\n'
            text += _("To enable it, select the 'Enabled' checkbox in the "
                      "'Policies' tab for the printer in the printer "
                      "administration tool.")
            text += ' ' + _(TEXT_start_print_admin_tool)

        self.label.set_markup (text)
        return True

    def can_click_forward (self):
        return False

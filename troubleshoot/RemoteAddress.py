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

from gi.repository import Gtk

from base import *
class RemoteAddress(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Remote address")
        page = self.initial_vbox (_("Remote Address"),
                                  _("Please enter as many details as you "
                                    "can about the network address of this "
                                    "printer."))
        table = Gtk.Table (2, 2)
        table.set_row_spacings (6)
        table.set_col_spacings (6)
        page.pack_start (table, False, False, 0)

        label = Gtk.Label(label=_("Server name:"))
        label.set_alignment (0, 0)
        table.attach (label, 0, 1, 0, 1)
        self.server_name = Gtk.Entry ()
        self.server_name.set_activates_default (True)
        table.attach (self.server_name, 1, 2, 0, 1)

        label = Gtk.Label(label=_("Server IP address:"))
        label.set_alignment (0, 0)
        table.attach (label, 0, 1, 1, 2)
        self.server_ipaddr = Gtk.Entry ()
        self.server_ipaddr.set_activates_default (True)
        table.attach (self.server_ipaddr, 1, 2, 1, 2)

        troubleshooter.new_page (page, self)

    def display (self):
        answers = self.troubleshooter.answers
        if answers['cups_queue_listed']:
            return False

        return answers['printer_is_remote']

    def collect_answer (self):
        if not self.displayed:
            return {}

        return { 'remote_server_name': self.server_name.get_text (),
                 'remote_server_ip_address': self.server_ipaddr.get_text () }

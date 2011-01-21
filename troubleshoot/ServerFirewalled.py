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

from base import *
class ServerFirewalled(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Server firewalled")
        page = self.initial_vbox (_("Check Server Firewall"),
                                   _("It is not possible to connect to the "
                                     "server."))
        self.label = Gtk.Label ()
        self.label.set_alignment (0, 0)
        self.label.set_line_wrap (True)
        page.pack_start (self.label, False, False, 0)
        troubleshooter.new_page (page, self)

    def display (self):
        answers = self.troubleshooter.answers
        if not answers['cups_queue_listed']:
            return False

        if (answers.has_key ('remote_server_connect_ipp') and
            answers['remote_server_connect_ipp'] == False):
            self.label.set_text (_("Please check to see if a firewall or "
                                   "router configuration is blocking TCP "
                                   "port %d on server '%s'.")
                                 % (answers['remote_server_port'],
                                    answers['remote_server_try_connect']))
            return True
        return False

    def can_click_forward (self):
        return False

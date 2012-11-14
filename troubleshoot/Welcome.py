#!/usr/bin/python

## Printing troubleshooter

## Copyright (C) 2008, 2009 Red Hat, Inc.
## Author: Tim Waugh <twaugh@redhat.com>

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
from timedops import TimedOperation
import authconn

class AuthConnFactory:
    def __init__ (self, parent):
        self.parent = parent

    def get_connection (self):
        return authconn.Connection (self.parent, lock=True)

class Welcome(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Welcome")
        welcome = Gtk.HBox ()
        welcome.set_spacing (12)
        welcome.set_border_width (12)
        image = Gtk.Image ()
        image.set_alignment (0, 0)
        image.set_from_stock (Gtk.STOCK_PRINT, Gtk.IconSize.DIALOG)
        intro = Gtk.Label(label='<span weight="bold" size="larger">' +
                           _("Trouble-shooting Printing") +
                           '</span>\n\n' +
                           _("The next few screens will contain some "
                             "questions about your problem with printing. "
                             "Based on your answers a solution may be "
                             "suggested.") + '\n\n' +
                           _("Click 'Forward' to begin."))
        intro.set_alignment (0, 0)
        intro.set_use_markup (True)
        intro.set_line_wrap (True)
        welcome.pack_start (image, False, False, 0)
        welcome.pack_start (intro, True, True, 0)
        page = troubleshooter.new_page (welcome, self)

    def collect_answer (self):
        parent = self.troubleshooter.get_window ()
        # Store the authentication dialog instance in the answers.  This
        # allows the password to be cached.
        factory = AuthConnFactory (parent)
        self.op = TimedOperation (factory.get_connection, parent=parent)
        return {'_authenticated_connection_factory': factory,
                '_authenticated_connection': self.op.run () }

    def cancel_operation (self):
        self.op.cancel ()

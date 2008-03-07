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

from base import *
from base import _

class AuthenticationDialog:
    def __init__ (self, parent=None):
        self.parent = parent
        self.suppress = False

    def suppress_dialog (self):
        self.suppress = True

    def callback (self, prompt):
        if self.suppress:
            self.suppress = False
            try:
                return self.last_password
            except AttributeError:
                pass

        dialog = gtk.Dialog (_("Authentication"),
                             self.parent,
                             gtk.DIALOG_MODAL | gtk.DIALOG_NO_SEPARATOR,
                             (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                              gtk.STOCK_OK, gtk.RESPONSE_OK))
        dialog.set_default_response (gtk.RESPONSE_OK)
        dialog.set_border_width (6)
        dialog.set_resizable (False)
        hbox = gtk.HBox (False, 12)
        hbox.set_border_width (6)
        image = gtk.Image ()
        image.set_from_stock ('gtk-dialog-authentication', gtk.ICON_SIZE_DIALOG)
        hbox.pack_start (image, False, False, 0)
        vbox = gtk.VBox (False, 12)
        label = gtk.Label ('<span weight="bold" size="larger">' +
                           _("Password required") + '</span>\n\n' + prompt)
        label.set_use_markup (True)
        label.set_alignment (0, 0)
        vbox.pack_start (label, False, False, 0)
        hbox.pack_start (vbox, False, False, 0)

        box = gtk.HBox (False, 6)
        vbox.pack_start (box, False, False, 0)
        box.pack_start (gtk.Label (_("Password:")), False, False, 0)
        self.password = gtk.Entry ()
        self.password.set_activates_default (True)
        self.password.set_visibility (False)
        box.pack_start (self.password, False, False, 0)

        dialog.vbox.pack_start (hbox, True, True, 0)
        dialog.show_all ()
        response = dialog.run ()
        dialog.hide ()
        if response != gtk.RESPONSE_OK:
            # Give up.
            try:
                del self.last_password
            except AttributeError:
                pass
            return ''

        self.last_password = self.password.get_text ()
        return self.last_password

class Welcome(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Welcome")
        welcome = gtk.HBox ()
        welcome.set_spacing (12)
        welcome.set_border_width (12)
        image = gtk.Image ()
        image.set_alignment (0, 0)
        image.set_from_stock (gtk.STOCK_PRINT, gtk.ICON_SIZE_DIALOG)
        intro = gtk.Label ('<span weight="bold" size="larger">' +
                           _("Trouble-shooting Printing") +
                           '</span>\n\n' +
                           _("In the next few screens I will ask you some "
                             "questions about your problem with printing. "
                             "Based on your answers I will try to suggest "
                             "a solution.") + '\n\n' +
                           _("Click 'Forward' to begin."))
        intro.set_alignment (0, 0)
        intro.set_use_markup (True)
        intro.set_line_wrap (True)
        welcome.pack_start (image, False, False, 0)
        welcome.pack_start (intro, True, True, 0)
        page = troubleshooter.new_page (welcome, self)

    def collect_answer (self):
        parent = self.troubleshooter.main
        # Store the authentication dialog instance in the answers.  This
        # allows the password to be cached.
        return { '_authentication_dialog': AuthenticationDialog (parent) }

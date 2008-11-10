#!/usr/bin/python

## system-config-printer
## CUPS backend
 
## Copyright (C) 2002, 2003, 2006, 2007, 2008 Red Hat, Inc.
## Copyright (C) 2002, 2003, 2006, 2007, 2008 Tim Waugh <twaugh@redhat.com>
 
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

import errno
from gettext import gettext as _
import gobject
import gtk
import os
import pwd
import smbc
from debug import *

class AuthContext:
    def __init__ (self, parent=None, workgroup='', user='', passwd=''):
        self.passes = 0
        self.has_failed = False
        self.auth_called = False
        self.tried_guest = False
        self.cancel = False
        self.use_user = user
        self.use_password = passwd
        self.use_workgroup = workgroup
        self.dialog_shown = False
        self.parent = parent

    def perform_authentication (self):
        self.passes += 1
        if self.passes == 1:
            return 1

        if not self.has_failed:
            return 0

        debugprint ("pysmb: authentication pass: %d" % self.passes)
        if not self.auth_called:
            debugprint ("pysmb: auth callback not called?!")
            self.cancel = True
            return 0

        self.has_failed = False
        if self.auth_called and not self.tried_guest:
            self.use_user = 'guest'
            self.use_password = ''
            self.tried_guest = True
            debugprint ("pysmb: try auth as guest")
            return 1

        self.auth_called = False

        if self.dialog_shown:
            d = gtk.MessageDialog (self.parent,
                                   gtk.DIALOG_MODAL |
                                   gtk.DIALOG_DESTROY_WITH_PARENT,
                                   gtk.MESSAGE_ERROR,
                                   gtk.BUTTONS_CLOSE)
            d.set_title (_("Not authorized"))
            d.set_markup ('<span weight="bold" size="larger">' +
                          _("Not authorized") + '</span>\n\n' +
                          _("The password may be incorrect."))
            d.run ()
            d.destroy ()

        # After that, prompt
        d = gtk.Dialog ("Authentication", self.parent,
                        gtk.DIALOG_MODAL | gtk.DIALOG_NO_SEPARATOR,
                        (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                         gtk.STOCK_OK, gtk.RESPONSE_OK))
        d.set_default_response (gtk.RESPONSE_OK)
        d.set_border_width (6)
        d.set_resizable (False)
        hbox = gtk.HBox (False, 12)
        hbox.set_border_width (6)
        image = gtk.Image ()
        image.set_from_stock (gtk.STOCK_DIALOG_AUTHENTICATION,
                              gtk.ICON_SIZE_DIALOG)
        hbox.pack_start (image, False, False, 0)
        vbox = gtk.VBox (False, 12)
        label = gtk.Label ('<span weight="bold" size="larger">' +
                           "You must log in to access %s." % self.for_server +
                           '</span>')
        label.set_use_markup (True)
        label.set_alignment (0, 0)
        label.set_line_wrap (True)
        vbox.pack_start (label, False, False, 0)

        table = gtk.Table (3, 2)
        table.set_row_spacings (6)
        table.set_col_spacings (6)
        table.attach (gtk.Label ("Username:"), 0, 1, 0, 1, 0, 0)
        username_entry = gtk.Entry ()
        table.attach (username_entry, 1, 2, 0, 1, 0, 0)
        table.attach (gtk.Label ("Domain:"), 0, 1, 1, 2, 0, 0)
        domain_entry = gtk.Entry ()
        table.attach (domain_entry, 1, 2, 1, 2, 0, 0)
        table.attach (gtk.Label ("Password:"), 0, 1, 2, 3, 0, 0)
        password_entry = gtk.Entry ()
        password_entry.set_activates_default (True)
        password_entry.set_visibility (False)
        table.attach (password_entry, 1, 2, 2, 3, 0, 0)
        vbox.pack_start (table, False, False, 0)
        hbox.pack_start (vbox, False, False, 0)
        d.vbox.pack_start (hbox)
        self.dialog_shown = True
        d.show_all ()
        d.show_now ()

        if self.use_user == 'guest':
            self.use_user = pwd.getpwuid (os.getuid ())[0]
            debugprint ("pysmb: try as %s" % self.use_user)
        username_entry.set_text (self.use_user)
        domain_entry.set_text (self.use_workgroup)

        d.set_keep_above (True)
        gtk.gdk.pointer_grab (d.window, True)
        gtk.gdk.keyboard_grab (d.window, True)
        response = d.run ()
        gtk.gdk.keyboard_ungrab ()
        gtk.gdk.pointer_ungrab ()

        if response == gtk.RESPONSE_CANCEL:
            self.cancel = True
            d.destroy ()
            return -1

        self.use_user = username_entry.get_text ()
        self.use_password = password_entry.get_text ()
        self.use_workgroup = domain_entry.get_text ()
        d.destroy ()
        return 1

    def initial_authentication (self):
        try:
            context = smbc.Context ()
            self.use_workgroup = context.workgroup
        except:
            pass

    def failed (self, exc=None):
        self.has_failed = True
        debugprint ("pysmb: operation failed: %s" % repr (exc))

        if exc:
            if (self.cancel or
                (type (exc) == RuntimeError and
                 not (exc.args[0] in [errno.EACCES, errno.EPERM]))):
                    raise exc

    def callback (self, server, share, workgroup, user, password):
        debugprint ("pysmb: got password callback")
        self.auth_called = True
        self.for_server = server
        self.for_share = share
        if self.passes == 1:
            self.initial_authentication ()

        if self.use_user:
            if self.use_workgroup:
                workgroup = self.use_workgroup

            return (workgroup, self.use_user, self.use_password)

        user = ''
        password = ''
        return (workgroup, user, password)

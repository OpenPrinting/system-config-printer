#!/usr/bin/python3

## system-config-printer
## CUPS backend
 
## Copyright (C) 2002, 2003, 2006, 2007, 2008, 2010, 2012, 2013 Red Hat, Inc.
## Authors:
##  Tim Waugh <twaugh@redhat.com>
 
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

import errno
import config
import gettext
gettext.install(domain=config.PACKAGE, localedir=config.localedir)
from gi.repository import Gtk
import os
import pwd
import smbc
from debug import *

class _None(RuntimeError):
    pass

try:
    NoEntryError = smbc.NoEntryError
    PermissionError = smbc.PermissionError
    ExistsError = smbc.ExistsError
    NotEmptyError = smbc.NotEmptyError
    TimedOutError = smbc.TimedOutError
    NoSpaceError = smbc.NoSpaceError
except AttributeError:
    NoEntryError = PermissionError = ExistsError = _None
    NotEmptyError = TimedOutError = NoSpaceError = _None

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
            d = Gtk.MessageDialog (transient_for=self.parent,
                                   modal=True, destroy_with_parent=True,
                                   message_type=Gtk.MessageType.ERROR,
                                   buttons=Gtk.ButtonsType.CLOSE)
            d.set_title (_("Not authorized"))
            d.set_markup ('<span weight="bold" size="larger">' +
                          _("Not authorized") + '</span>\n\n' +
                          _("The password may be incorrect."))
            d.run ()
            d.destroy ()

        # After that, prompt
        d = Gtk.Dialog (title=_("Authentication"),
                        transient_for=self.parent,
                        modal=True)
        d.add_buttons (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                         Gtk.STOCK_OK, Gtk.ResponseType.OK)
        d.set_default_response (Gtk.ResponseType.OK)
        d.set_border_width (6)
        d.set_resizable (False)
        hbox = Gtk.HBox.new (False, 12)
        hbox.set_border_width (6)
        image = Gtk.Image ()
        image.set_from_stock (Gtk.STOCK_DIALOG_AUTHENTICATION,
                              Gtk.IconSize.DIALOG)
        hbox.pack_start (image, False, False, 0)
        vbox = Gtk.VBox (False, 12)
        label = Gtk.Label(label='<span weight="bold" size="larger">' +
                           _("You must log in to access %s.")
                          % self.for_server +
                           '</span>')
        label.set_use_markup (True)
        label.set_alignment (0, 0)
        label.set_line_wrap (True)
        vbox.pack_start (label, False, False, 0)

        grid = Gtk.Grid()
        grid.set_row_spacing (6)
        grid.set_column_spacing (6)
        grid.attach (Gtk.Label(label=_("Username:")), 0, 0, 1, 1)
        username_entry = Gtk.Entry ()
        grid.attach (username_entry, 1, 0, 1, 1)
        grid.attach (Gtk.Label(label=_("Domain:")), 0, 1, 1, 1)
        domain_entry = Gtk.Entry ()
        grid.attach (domain_entry, 1, 1, 1, 1)
        grid.attach (Gtk.Label(label=_("Password:")), 0, 2, 1, 1)
        password_entry = Gtk.Entry ()
        password_entry.set_activates_default (True)
        password_entry.set_visibility (False)
        grid.attach (password_entry, 1, 2, 1, 1)
        vbox.pack_start (grid, False, False, 0)
        hbox.pack_start (vbox, False, False, 0)
        d.vbox.pack_start (hbox, False, False, 0)
        self.dialog_shown = True
        d.show_all ()
        d.show_now ()

        if self.use_user == 'guest':
            self.use_user = pwd.getpwuid (os.getuid ())[0]
            debugprint ("pysmb: try as %s" % self.use_user)
        username_entry.set_text (self.use_user)
        domain_entry.set_text (self.use_workgroup)

        d.set_keep_above (True)
        response = d.run ()

        if response == Gtk.ResponseType.CANCEL:
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
                (type (exc) in [NoEntryError, ExistsError, NotEmptyError,
                                TimedOutError, NoSpaceError]) or
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

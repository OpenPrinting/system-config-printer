#!/usr/bin/env python

## Copyright (C) 2007, 2008 Tim Waugh <twaugh@redhat.com>
## Copyright (C) 2007, 2008 Red Hat, Inc.

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
import gtk
from debug import *

_ = lambda x: x
def set_gettext_function (fn):
    global _
    _ = fn

class Connection:
    def __init__ (self, parent):
        self._use_password = ''
        self._parent = parent
        self._connect ()
        self._prompt_allowed = True

    def _set_prompt_allowed (allowed):
        self._prompt_allowed = allowed

    def _make_binding (self, fn):
        return lambda *args, **kwds: self._authloop (fn, *args, **kwds)

    def _connect (self):
        self._connection = cups.Connection ()
        self._use_user = cups.getUser ()
        self._server = cups.getServer ()
        self._user = self._use_user
        methodtype = type (self._connection.getPrinters)
        for fname in dir (self._connection):
            if fname[0] == '_':
                continue
            fn = getattr (self._connection, fname)
            if type (fn) != methodtype:
                continue
            setattr (self, fname, self._make_binding (fn))

    def _authloop (self, fn, *args, **kwds):
        self._has_failed = False
        self._auth_called = False
        self._passes = 0
        self._cancel = False
        while self._perform_authentication () != 0:
            try:
                result = fn.__call__ (*args, **kwds)
                break
            except cups.IPPError, (e, m):
                if not self._cancel and e == cups.IPP_NOT_AUTHORIZED:
                    self._failed ()
                else:
                    raise
            except cups.HTTPError, (s,):
                if not self._cancel and s == cups.HTTP_UNAUTHORIZED:
                    self._failed ()
                else:
                    raise

        return result

    def _failed (self):
        self._has_failed = True

    def _password_callback (self, prompt):
        debugprint ("Got password callback")
        if self._cancel or self._auth_called:
            return ''

        self._auth_called = True
        self._prompt = prompt
        return self._use_password

    def _perform_authentication (self):
        self._passes += 1

        debugprint ("Authentication pass: %d" % self._passes)
        self._auth_called = False
        if self._passes == 1:
            # Haven't yet tried the operation.  Set the password
            # callback and return > 0 so we try it for the first time.
            cups.setPasswordCB (self._password_callback)
            debugprint ("Authentication: password callback set")
            return 1

        if not self._has_failed:
            # Tried the operation and it worked.  Return 0 to signal to
            # break out of the loop.
            debugprint ("Authentication: Operation successful")
            return 0

        self._has_failed = False
        if self._passes == 2:
            # Tried the operation without a password and it failed.
            if self._user != 'root' and self._server[0] == '/':
                # This is a UNIX domain socket connection so we should
                # not have needed a password, and so the operation must
                # not be something that the current user is authorised to
                # do.  They need to try as root, and supply the password.
                # However, to get the right prompt, we need to try as
                # root but with no password first.
                debugprint ("Authentication: Try as root")
                self._use_user = 'root'
                cups.setUser (self._use_user)
                self._connect ()
                return 1

        if not self._prompt_allowed:
            return -1

        # Prompt.
        d = gtk.Dialog (_("Authentication"), self._parent,
                        gtk.DIALOG_MODAL | gtk.DIALOG_NO_SEPARATOR,
                        (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                         gtk.STOCK_OK, gtk.RESPONSE_OK))
        d.set_default_response (gtk.RESPONSE_OK)
        d.set_border_width (6)
        d.set_resizable (False)
        hbox = gtk.HBox (False, 12)
        hbox.set_border_width (6)
        image = gtk.Image ()
        image.set_from_stock ('gtk-dialog-authentication',
                              gtk.ICON_SIZE_DIALOG)
        hbox.pack_start (image, False, False, 0)
        vbox = gtk.VBox (False, 12)
        label = gtk.Label ('<span weight="bold" size="larger">' +
                           self._prompt + '</span>')
        label.set_use_markup (True)
        label.set_alignment (0, 0)
        label.set_line_wrap (True)
        vbox.pack_start (label, False, False, 0)

        table = gtk.Table (2, 2)
        table.set_row_spacings (6)
        table.set_col_spacings (6)
        table.attach (gtk.Label ("Username:"), 0, 1, 0, 1, 0, 0)
        username_entry = gtk.Entry ()
        table.attach (username_entry, 1, 2, 0, 1, 0, 0)
        table.attach (gtk.Label ("Password:"), 0, 1, 1, 2, 0, 0)
        password_entry = gtk.Entry ()
        password_entry.set_activates_default (True)
        password_entry.set_visibility (False)
        table.attach (password_entry, 1, 2, 1, 2, 0, 0)
        vbox.pack_start (table, False, False, 0)
        hbox.pack_start (vbox, False, False, 0)
        d.vbox.pack_start (hbox)
        d.show_all ()

        username_entry.set_text (self._use_user)
        password_entry.grab_focus ()
        response = d.run ()
        d.hide ()

        if response == gtk.RESPONSE_CANCEL:
            self._cancel = True
            return -1

        self._use_user = username_entry.get_text ()
        self._use_password = password_entry.get_text ()

        if self._user != self._use_user:
            cups.setUser (self._use_user)
            debugprint ("Authentication: Reconnect")
            self._connect ()

        return 1

if __name__ == '__main__':
    # Test it out.
    set_debugging (True)
    c = Connection (None)
    print c.getFile ('/admin/conf/cupsd.conf', '/dev/stdout')

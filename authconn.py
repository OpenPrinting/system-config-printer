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

class AuthDialog(gtk.Dialog):
    AUTH_FIELD={'username': _("Username:"),
                'password': _("Password:"),
                'domain': _("Domain:")}

    def __init__ (self, title=_("Authentication"), parent=None,
                  flags=gtk.DIALOG_MODAL | gtk.DIALOG_NO_SEPARATOR,
                  buttons=(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                           gtk.STOCK_OK, gtk.RESPONSE_OK),
                  auth_info_required=['username', 'password']):
        gtk.Dialog.__init__ (self, title, parent, flags, buttons)
        self.auth_info_required = auth_info_required
        self.set_default_response (gtk.RESPONSE_OK)
        self.set_border_width (6)
        self.set_resizable (False)
        hbox = gtk.HBox (False, 12)
        hbox.set_border_width (6)
        image = gtk.Image ()
        image.set_from_stock ('gtk-dialog-authentication',
                              gtk.ICON_SIZE_DIALOG)
        image.set_alignment (0.0, 0.0)
        hbox.pack_start (image, False, False, 0)
        vbox = gtk.VBox (False, 12)
        self.prompt_label = gtk.Label ()
        vbox.pack_start (self.prompt_label, False, False, 0)

        num_fields = len (auth_info_required)
        table = gtk.Table (num_fields, 2)
        table.set_row_spacings (6)
        table.set_col_spacings (6)

        self.field_entry = []
        for i in range (num_fields):
            field = auth_info_required[i]
            label = gtk.Label (self.AUTH_FIELD.get (field, field))
            label.set_alignment (0, 0.5)
            table.attach (label, 0, 1, i, i + 1)
            entry = gtk.Entry ()
            entry.set_visibility (field != 'password')
            table.attach (entry, 1, 2, i, i + 1, 0, 0)
            self.field_entry.append (entry)

        self.field_entry[num_fields - 1].set_activates_default (True)
        vbox.pack_start (table, False, False, 0)
        hbox.pack_start (vbox, False, False, 0)
        self.vbox.pack_start (hbox)
        self.vbox.show_all ()

    def set_prompt (self, prompt):
        self.prompt_label.set_markup ('<span weight="bold" size="larger">' +
                                      prompt + '</span>')
        self.prompt_label.set_use_markup (True)
        self.prompt_label.set_alignment (0, 0)
        self.prompt_label.set_line_wrap (True)

    def set_auth_info (self, auth_info):
        for i in range (len (self.field_entry)):
            self.field_entry[i].set_text (auth_info[i])

    def get_auth_info (self):
        return map (lambda x: x.get_text (), self.field_entry)

    def field_grab_focus (self, field):
        i = self.auth_info_required.index (field)
        self.field_entry[i].grab_focus ()

class Connection:
    def __init__ (self, parent=None, try_as_root=True):
        self._use_password = ''
        self._parent = parent
        self._try_as_root = try_as_root
        self._connect ()
        self._prompt_allowed = True

    def _get_prompt_allowed (self, ):
        return self._prompt_allowed

    def _set_prompt_allowed (self, allowed):
        self._prompt_allowed = allowed

    def _connect (self):
        self._connection = cups.Connection ()
        self._use_user = cups.getUser ()
        self._server = cups.getServer ()
        self._user = self._use_user
        debugprint ("Connected as user %s" % self._user)
        methodtype = type (self._connection.getPrinters)
        for fname in dir (self._connection):
            if fname[0] == '_':
                continue
            fn = getattr (self._connection, fname)
            if type (fn) != methodtype:
                continue
            setattr (self, fname, self._make_binding (fname, fn))

    def _make_binding (self, fname, fn):
        return lambda *args, **kwds: self._authloop (fname, fn, *args, **kwds)

    def _authloop (self, fname, fn, *args, **kwds):
        self._passes = 0
        while self._perform_authentication () != 0:
            try:
                result = fn.__call__ (*args, **kwds)

                if fname == 'adminGetServerSettings':
                    # Special case for a rubbish bit of API.
                    if result == {}:
                        # Authentication failed, but we aren't told that.
                        raise cups.IPPError (cups.IPP_NOT_AUTHORIZED, '')
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
        if self._passes == 1:
            # Haven't yet tried the operation.  Set the password
            # callback and return > 0 so we try it for the first time.
            self._has_failed = False
            self._auth_called = False
            self._cancel = False
            cups.setPasswordCB (self._password_callback)
            debugprint ("Authentication: password callback set")
            return 1

        if not self._has_failed:
            # Tried the operation and it worked.  Return 0 to signal to
            # break out of the loop.
            debugprint ("Authentication: Operation successful")
            return 0

        # Reset failure flag.
        self._has_failed = False

        if self._passes == 2:
            # Tried the operation without a password and it failed.
            if (self._try_as_root and
                self._user != 'root' and
                self._server[0] == '/'):
                # This is a UNIX domain socket connection so we should
                # not have needed a password, and so the operation must
                # not be something that the current user is authorised to
                # do.  They need to try as root, and supply the password.
                # However, to get the right prompt, we need to try as
                # root but with no password first.
                debugprint ("Authentication: Try as root")
                self._use_user = 'root'
                cups.setUser (self._use_user)
                self._auth_called = False
                self._connect ()
                return 1

        if not self._prompt_allowed:
            debugprint ("Authentication: prompting not allowed")
            self._cancel = True
            return 1

        if not self._auth_called:
            # We aren't even getting a chance to supply credentials.
            debugprint ("Authentication: giving up")
            self._cancel = True
            return 1

        # Reset the flag indicating whether we were given an auth callback.
        self._auth_called = False

        # Prompt.
        d = AuthDialog (parent=self._parent)
        d.set_prompt (self._prompt)
        d.set_auth_info ([self._use_user, ''])
        d.field_grab_focus ('password')
        response = d.run ()
        d.hide ()

        if response == gtk.RESPONSE_CANCEL:
            self._cancel = True
            return -1

        (self._use_user,
         self._use_password) = d.get_auth_info ()

        cups.setUser (self._use_user)
        debugprint ("Authentication: Reconnect")
        self._connect ()

        return 1

if __name__ == '__main__':
    # Test it out.
    set_debugging (True)
    c = Connection (None)
    print c.getFile ('/admin/conf/cupsd.conf', '/dev/stdout')

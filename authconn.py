#!/usr/bin/python

## Copyright (C) 2007, 2008, 2009, 2010, 2011, 2013 Red Hat, Inc.
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

import threading
import config
import cups
import cupspk
from gi.repository import GLib
from gi.repository import Gdk
from gi.repository import Gtk
import os
from errordialogs import *
from debug import *
import gettext
gettext.install(domain=config.PACKAGE, localedir=config.localedir, unicode=True)
N_ = lambda x: x

cups.require("1.9.60")
class AuthDialog(Gtk.Dialog):
    AUTH_FIELD={'username': N_("Username:"),
                'password': N_("Password:"),
                'domain': N_("Domain:")}

    def __init__ (self, title=None, parent=None,
                  flags=Gtk.DialogFlags.MODAL,
                  buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                           Gtk.STOCK_OK, Gtk.ResponseType.OK),
                  auth_info_required=['username', 'password'],
                  allow_remember=False):
        if title == None:
            title = _("Authentication")
        Gtk.Dialog.__init__ (self, title, parent, flags, buttons)
        self.auth_info_required = auth_info_required
        self.set_default_response (Gtk.ResponseType.OK)
        self.set_border_width (6)
        self.set_resizable (False)
        hbox = Gtk.HBox.new (False, 12)
        hbox.set_border_width (6)
        image = Gtk.Image ()
        image.set_from_stock (Gtk.STOCK_DIALOG_AUTHENTICATION,
                              Gtk.IconSize.DIALOG)
        image.set_alignment (0.0, 0.0)
        hbox.pack_start (image, False, False, 0)
        vbox = Gtk.VBox.new (False, 12)
        self.prompt_label = Gtk.Label ()
        vbox.pack_start (self.prompt_label, False, False, 0)

        num_fields = len (auth_info_required)
        table = Gtk.Table (num_fields, 2)
        table.set_row_spacings (6)
        table.set_col_spacings (6)

        self.field_entry = []
        for i in range (num_fields):
            field = auth_info_required[i]
            label = Gtk.Label (_(self.AUTH_FIELD.get (field, field)))
            label.set_alignment (0, 0.5)
            table.attach (label, 0, 1, i, i + 1)
            entry = Gtk.Entry ()
            entry.set_visibility (field != 'password')
            table.attach (entry, 1, 2, i, i + 1, 0, 0)
            self.field_entry.append (entry)

        self.field_entry[num_fields - 1].set_activates_default (True)
        vbox.pack_start (table, False, False, 0)
        hbox.pack_start (vbox, False, False, 0)
        self.vbox.pack_start (hbox, False, False, 0)

        if allow_remember:
            cb = Gtk.CheckButton (_("Remember password"))
            cb.set_active (False)
            vbox.pack_start (cb, False, False, 0)
            self.remember_checkbox = cb

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

    def get_remember_password (self):
        try:
            return self.remember_checkbox.get_active ()
        except AttributeError:
            return False

    def field_grab_focus (self, field):
        i = self.auth_info_required.index (field)
        self.field_entry[i].grab_focus ()

###
### An auth-info cache.
###
class _AuthInfoCache:
    def __init__ (self):
        self.creds = dict() # by (host,port)

    def cache_auth_info (self, data, host=None, port=None):
        if port == None:
            port = 631

        self.creds[(host,port)] = data

    def lookup_auth_info (self, host=None, port=None):
        if port == None:
            port = 631

        try:
            return self.creds[(host,port)]
        except KeyError:
            return None

    def remove_auth_info (self, host=None, port=None):
        if port == None:
            port = 631

        try:
            del self.creds[(host,port)]
        except KeyError:
            return None

global_authinfocache = _AuthInfoCache ()

class Connection:
    def __init__ (self, parent=None, try_as_root=True, lock=False,
                  host=None, port=None, encryption=None):
        if host != None:
            cups.setServer (host)
        if port != None:
            cups.setPort (port)
        if encryption != None:
            cups.setEncryption (encryption)

        self._use_password = ''
        self._parent = parent
        self._try_as_root = try_as_root
        self._use_user = cups.getUser ()
        self._server = cups.getServer ()
        self._port = cups.getPort()
        self._encryption = cups.getEncryption ()
        self._prompt_allowed = True
        self._operation_stack = []
        self._lock = lock
        self._gui_event = threading.Event ()

        self._connect ()

    def _begin_operation (self, operation):
        debugprint ("%s: Operation += %s" % (self, operation))
        self._operation_stack.append (operation)

    def _end_operation (self):
        debugprint ("%s: Operation ended" % self)
        self._operation_stack.pop ()

    def _get_prompt_allowed (self, ):
        return self._prompt_allowed

    def _set_prompt_allowed (self, allowed):
        self._prompt_allowed = allowed

    def _set_lock (self, whether):
        self._lock = whether

    def _connect (self, allow_pk=True):
        cups.setUser (self._use_user)

        self._use_pk = (allow_pk and
                        (self._server[0] == '/' or self._server == 'localhost')
                        and os.getuid () != 0)
        if self._use_pk:
            create_object = cupspk.Connection
        else:
            create_object = cups.Connection

        self._connection = create_object (host=self._server,
                                            port=self._port,
                                            encryption=self._encryption)

        if self._use_pk:
            self._connection.set_parent(self._parent)

        self._user = self._use_user
        debugprint ("Connected as user %s" % self._user)
        methodtype_lambda = type (self._connection.getPrinters)
        methodtype_real = type (self._connection.addPrinter)
        for fname in dir (self._connection):
            if fname[0] == '_':
                continue
            fn = getattr (self._connection, fname)
            if not type (fn) in [methodtype_lambda, methodtype_real]:
                continue
            setattr (self, fname, self._make_binding (fname, fn))

    def _make_binding (self, fname, fn):
        return lambda *args, **kwds: self._authloop (fname, fn, *args, **kwds)

    def _authloop (self, fname, fn, *args, **kwds):
        self._passes = 0
        c = self._connection
        retry = False
        while True:
            try:
                if self._perform_authentication () == 0:
                    break

                if c != self._connection:
                    # We have reconnected.
                    fn = getattr (self._connection, fname)
                    c = self._connection

                cups.setUser (self._use_user)

                result = fn.__call__ (*args, **kwds)

                if fname == 'adminGetServerSettings':
                    # Special case for a rubbish bit of API.
                    if result == {}:
                        # Authentication failed, but we aren't told that.
                        raise cups.IPPError (cups.IPP_NOT_AUTHORIZED, '')
                break
            except cups.IPPError as e:
                (e, m) = e.args
                if isinstance(m, bytes):
                    m = m.decode('utf-8', 'replace')
                if self._use_pk and m == 'pkcancel':
                    raise cups.IPPError (0, _("Operation canceled"))

                if not self._cancel and (e == cups.IPP_NOT_AUTHORIZED or
                                         e == cups.IPP_FORBIDDEN or
                                         e == cups.IPP_AUTHENTICATION_CANCELED):
                    self._failed (e == cups.IPP_FORBIDDEN)
                elif not self._cancel and e == cups.IPP_SERVICE_UNAVAILABLE:
                    if self._lock:
                        self._gui_event.clear ()
                        GLib.timeout_add (1, self._ask_retry_server_error, m)
                        self._gui_event.wait ()
                    else:
                        self._ask_retry_server_error (m)

                    if self._retry_response == Gtk.ResponseType.OK:
                        debugprint ("retrying operation...")
                        retry = True
                        self._passes -= 1
                        self._has_failed = True
                    else:
                        self._cancel = True
                        raise
                else:
                    if self._cancel and not self._cannot_auth:
                        raise cups.IPPError (0, _("Operation canceled"))

                    debugprint ("%s: %s" % (e, repr (m)))
                    raise
            except cups.HTTPError as e:
                (s,) = e.args
                if not self._cancel:
                    self._failed (s == cups.HTTP_FORBIDDEN)
                else:
                    raise

        return result

    def _ask_retry_server_error (self, message):
        if self._lock:
            Gdk.threads_enter ()

        try:
            msg = (_("CUPS server error (%s)") % self._operation_stack[0])
        except IndexError:
            msg = _("CUPS server error")

        d = Gtk.MessageDialog (self._parent,
                               Gtk.DialogFlags.MODAL |
                               Gtk.DialogFlags.DESTROY_WITH_PARENT,
                               Gtk.MessageType.ERROR,
                               Gtk.ButtonsType.NONE,
                               msg)
                               
        d.format_secondary_text (_("There was an error during the "
                                   "CUPS operation: '%s'." % message))
        d.add_buttons (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                       _("Retry"), Gtk.ResponseType.OK)
        d.set_default_response (Gtk.ResponseType.OK)
        if self._lock:
            d.connect ("response", self._on_retry_server_error_response)
            Gdk.threads_leave ()
        else:
            self._retry_response = d.run ()
            d.destroy ()

    def _on_retry_server_error_response (self, dialog, response):
        self._retry_response = response
        dialog.destroy ()
        self._gui_event.set ()

    def _failed (self, forbidden=False):
        self._has_failed = True
        self._forbidden = forbidden

    def _password_callback (self, prompt):
        debugprint ("Got password callback")
        if self._cancel or self._auth_called:
            return ''

        self._auth_called = True
        self._prompt = prompt
        return self._use_password

    def _perform_authentication (self):
        self._passes += 1

        creds = global_authinfocache.lookup_auth_info (host=self._server, port=self._port)
        if creds != None:
            if (creds[0] != 'root' or self._try_as_root):
                (self._use_user, self._use_password) = creds
            del creds

        debugprint ("Authentication pass: %d" % self._passes)
        if self._passes == 1:
            # Haven't yet tried the operation.  Set the password
            # callback and return > 0 so we try it for the first time.
            self._has_failed = False
            self._forbidden = False
            self._auth_called = False
            self._cancel = False
            self._cannot_auth = False
            self._dialog_shown = False
            cups.setPasswordCB (self._password_callback)
            debugprint ("Authentication: password callback set")
            return 1

        debugprint ("Forbidden: %s" % self._forbidden)
        if not self._has_failed:
            # Tried the operation and it worked.  Return 0 to signal to
            # break out of the loop.
            debugprint ("Authentication: Operation successful")
            return 0

        # Reset failure flag.
        self._has_failed = False

        if self._passes >= 2:
            # Tried the operation without a password and it failed.
            if (self._try_as_root and
                self._user != 'root' and
                (self._server[0] == '/' or self._forbidden)):
                # This is a UNIX domain socket connection so we should
                # not have needed a password (or it is not a UDS but
                # we got an HTTP_FORBIDDEN response), and so the
                # operation must not be something that the current
                # user is authorised to do.  They need to try as root,
                # and supply the password.  However, to get the right
                # prompt, we need to try as root but with no password
                # first.
                debugprint ("Authentication: Try as root")
                self._use_user = 'root'
                self._auth_called = False
                try:
                    self._connect (allow_pk=False)
                except RuntimeError:
                    raise cups.IPPError (cups.IPP_SERVICE_UNAVAILABLE,
                                         'server-error-service-unavailable')

                return 1

        if not self._prompt_allowed:
            debugprint ("Authentication: prompting not allowed")
            self._cancel = True
            return 1

        if not self._auth_called:
            # We aren't even getting a chance to supply credentials.
            debugprint ("Authentication: giving up")
            self._cancel = True
            self._cannot_auth = True
            return 1

        # Reset the flag indicating whether we were given an auth callback.
        self._auth_called = False

        # If we're previously prompted, explain why we're prompting again.
        if self._dialog_shown:
            if self._lock:
                self._gui_event.clear ()
                GLib.timeout_add (1, self._show_not_authorized_dialog)
                self._gui_event.wait ()
            else:
                self._show_not_authorized_dialog ()

        if self._lock:
            self._gui_event.clear ()
            GLib.timeout_add (1, self._perform_authentication_with_dialog)
            self._gui_event.wait ()
        else:
            self._perform_authentication_with_dialog ()

        if self._cancel:
            debugprint ("cancelled")
            return -1

        cups.setUser (self._use_user)
        debugprint ("Authentication: Reconnect")
        try:
            self._connect (allow_pk=False)
        except RuntimeError:
            raise cups.IPPError (cups.IPP_SERVICE_UNAVAILABLE,
                                 'server-error-service-unavailable')

        return 1

    def _show_not_authorized_dialog (self):
        if self._lock:
            Gdk.threads_enter ()
        d = Gtk.MessageDialog (self._parent,
                               Gtk.DialogFlags.MODAL |
                               Gtk.DialogFlags.DESTROY_WITH_PARENT,
                               Gtk.MessageType.ERROR,
                               Gtk.ButtonsType.CLOSE)
        d.set_title (_("Not authorized"))
        d.set_markup ('<span weight="bold" size="larger">' +
                      _("Not authorized") + '</span>\n\n' +
                      _("The password may be incorrect."))
        if self._lock:
            d.connect ("response", self._on_not_authorized_dialog_response)
            d.show_all ()
            d.show_now ()
            Gdk.threads_leave ()
        else:
            d.run ()
            d.destroy ()

    def _on_not_authorized_dialog_response (self, dialog, response):
        self._gui_event.set ()
        dialog.destroy ()

    def _perform_authentication_with_dialog (self):
        if self._lock:
            Gdk.threads_enter ()

        # Prompt.
        if len (self._operation_stack) > 0:
            try:
                title = (_("Authentication (%s)") % self._operation_stack[0])
            except IndexError:
                title = _("Authentication")

            d = AuthDialog (title=title,
                            parent=self._parent)
        else:
            d = AuthDialog (parent=self._parent)

        d.set_prompt ('')
        d.set_auth_info (['', ''])
        d.field_grab_focus ('username')
        d.set_keep_above (True)
        d.show_all ()
        d.show_now ()
        self._dialog_shown = True
        if self._lock:
            d.connect ("response", self._on_authentication_response)
            Gdk.threads_leave ()
        else:
            response = d.run ()
            self._on_authentication_response (d, response)

    def _on_authentication_response (self, dialog, response):
        (user, self._use_password) = dialog.get_auth_info ()
        if user != '':
            self._use_user = user
        global_authinfocache.cache_auth_info ((self._use_user,
                                               self._use_password),
                                              host=self._server,
                                              port=self._port)
        dialog.destroy ()

        if (response == Gtk.ResponseType.CANCEL or
            response == Gtk.ResponseType.DELETE_EVENT):
            self._cancel = True

        if self._lock:
            self._gui_event.set ()

if __name__ == '__main__':
    # Test it out.
    Gdk.threads_init ()
    from timedops import TimedOperation
    set_debugging (True)
    c = TimedOperation (Connection, args=(None,)).run ()
    debugprint ("Connected")
    c._set_lock (True)
    print TimedOperation (c.getFile,
                          args=('/admin/conf/cupsd.conf',
                                '/dev/stdout')).run ()

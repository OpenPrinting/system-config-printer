#!/usr/bin/python

## Copyright (C) 2007, 2008, 2009, 2010, 2011, 2012, 2013 Red Hat, Inc.
## Copyright (C) 2008 Novell, Inc.
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
from gi.repository import GObject
from gi.repository import GLib
from gi.repository import Gdk
from gi.repository import Gtk
import Queue

cups.require ("1.9.60")

import authconn
from debug import *
import debug
import gettext
gettext.install(domain=config.PACKAGE, localedir=config.localedir, unicode=True)


######
###### An asynchronous libcups API using IPP with a separate worker
###### thread.
######

###
### This is the worker thread.
###
class _IPPConnectionThread(threading.Thread):
    def __init__ (self, queue, conn, reply_handler=None, error_handler=None,
                  auth_handler=None, user=None, host=None, port=None,
                  encryption=None):
                  
        threading.Thread.__init__ (self)
        self.setDaemon (True)
        self._queue = queue
        self._conn = conn
        self.host = host
        self.port = port
        self._encryption = encryption
        self._reply_handler = reply_handler
        self._error_handler = error_handler
        self._auth_handler = auth_handler
        self._auth_queue = Queue.Queue (1)
        self.user = user
        self._destroyed = False
        debugprint ("+%s" % self)

    def __del__ (self):
        debug.debugprint ("-%s" % self)

    def set_auth_info (self, password):
        self._auth_queue.put (password)

    def run (self):
        if self.host == None:
            self.host = cups.getServer ()
        if self.port == None:
            self.port = cups.getPort ()
        if self._encryption == None:
            self._encryption = cups.getEncryption ()

        if self.user:
            cups.setUser (self.user)
        else:
            self.user = cups.getUser ()

        cups.setPasswordCB2 (self._auth)

        try:
            conn = cups.Connection (host=self.host,
                                    port=self.port,
                                    encryption=self._encryption)
            self._reply (None)
        except RuntimeError as e:
            conn = None
            self._error (e)

        while True:
            # Wait to find out what operation to try.
            debugprint ("Awaiting further instructions")
            self.idle = self._queue.empty ()
            item = self._queue.get ()
            debugprint ("Next task: %s" % repr (item))
            if item == None:
                # Our signal to quit.
                self._queue.task_done ()
                break

            self.idle = False
            (fn, args, kwds, rh, eh, ah) = item
            if rh != False:
                self._reply_handler = rh
            if eh != False:
                self._error_handler = eh
            if ah != False:
                self._auth_handler = ah

            if fn == True:
                # Our signal to change user and reconnect.
                self.user = args[0]
                cups.setUser (self.user)
                debugprint ("Set user=%s; reconnecting..." % self.user)
                cups.setPasswordCB2 (self._auth)

                try:
                    conn = cups.Connection (host=self.host,
                                            port=self.port,
                                            encryption=self._encryption)
                    debugprint ("...reconnected")

                    self._queue.task_done ()
                    self._reply (None)
                except RuntimeError as e:
                    debugprint ("...failed")
                    self._queue.task_done ()
                    self._error (e)

                continue

            # Normal IPP operation.  Try to perform it.
            try:
                debugprint ("Call %s" % fn)
                result = fn (conn, *args, **kwds)
                if fn == cups.Connection.adminGetServerSettings.__call__:
                    # Special case for a rubbish bit of API.
                    if result == {}:
                        # Authentication failed, but we aren't told that.
                        raise cups.IPPError (cups.IPP_NOT_AUTHORIZED, '')

                debugprint ("...success")
                self._reply (result)
            except Exception as e:
                debugprint ("...failure (%s)" % repr (e))
                self._error (e)

            self._queue.task_done ()

        debugprint ("Thread exiting")
        self._destroyed = True
        del self._conn # already destroyed
        del self._reply_handler
        del self._error_handler
        del self._auth_handler
        del self._queue
        del self._auth_queue
        del conn

        cups.setPasswordCB2 (None)

    def _auth (self, prompt, conn=None, method=None, resource=None):
        def prompt_auth (prompt):
            Gdk.threads_enter ()
            if conn == None:
                self._auth_handler (prompt, self._conn)
            else:
                self._auth_handler (prompt, self._conn, method, resource)

            Gdk.threads_leave ()
            return False

        if self._auth_handler == None:
            return ""

        GLib.idle_add (prompt_auth, prompt)
        password = self._auth_queue.get ()
        return password

    def _reply (self, result):
        def send_reply (handler, result):
            if not self._destroyed:
                Gdk.threads_enter ()
                handler (self._conn, result)
                Gdk.threads_leave ()
            return False

        if not self._destroyed and self._reply_handler:
            GLib.idle_add (send_reply, self._reply_handler, result)

    def _error (self, exc):
        def send_error (handler, exc):
            if not self._destroyed:
                Gdk.threads_enter ()
                handler (self._conn, exc)
                Gdk.threads_leave ()
            return False

        if not self._destroyed and self._error_handler:
            debugprint ("Add %s to idle" % self._error_handler)
            GLib.idle_add (send_error, self._error_handler, exc)

###
### This is the user-visible class.  Although it does not inherit from
### cups.Connection it implements the same functions.
###
class IPPConnection:
    """
    This class starts a new thread to handle IPP operations.

    Each IPP operation method takes optional reply_handler,
    error_handler and auth_handler parameters.

    If an operation requires a password to proceed, the auth_handler
    function will be called.  The operation will continue once
    set_auth_info (in this class) is called.

    Once the operation has finished either reply_handler or
    error_handler will be called.
    """

    def __init__ (self, reply_handler=None, error_handler=None,
                  auth_handler=None, user=None, host=None, port=None,
                  encryption=None, parent=None):
        debugprint ("New IPPConnection")
        self._parent = parent
        self.queue = Queue.Queue ()
        self.thread = _IPPConnectionThread (self.queue, self,
                                            reply_handler=reply_handler,
                                            error_handler=error_handler,
                                            auth_handler=auth_handler,
                                            user=user, host=host, port=port,
                                            encryption=encryption)
        self.thread.start ()

        methodtype = type (cups.Connection.getPrinters)
        bindings = []
        for fname in dir (cups.Connection):
            if fname[0] == ' ':
                continue
            fn = getattr (cups.Connection, fname)
            if type (fn) != methodtype:
                continue
            setattr (self, fname, self._make_binding (fn))
            bindings.append (fname)

        self.bindings = bindings
        debugprint ("+%s" % self)

    def __del__ (self):
        debug.debugprint ("-%s" % self)

    def destroy (self):
        debugprint ("DESTROY: %s" % self)
        for binding in self.bindings:
            delattr (self, binding)

        if self.thread.isAlive ():
            GLib.timeout_add_seconds (1, self._reap_thread)

    def _reap_thread (self):
        if self.thread.idle:
            debugprint ("Putting None on the task queue")
            self.queue.put (None)
            self.queue.join ()
            return False

        debugprint ("Thread %s still processing tasks" % self.thread)
        return True

    def set_auth_info (self, password):
        """Call this from your auth_handler function."""
        self.thread.set_auth_info (password)

    def reconnect (self, user, reply_handler=None, error_handler=None):
        debugprint ("Reconnect...")
        self.queue.put ((True, (user,), {},
                         reply_handler, error_handler, False))

    def _make_binding (self, fn):
        return lambda *args, **kwds: self._call_function (fn, *args, **kwds)

    def _call_function (self, fn, *args, **kwds):
        reply_handler = error_handler = auth_handler = False
        if kwds.has_key ("reply_handler"):
            reply_handler = kwds["reply_handler"]
            del kwds["reply_handler"]
        if kwds.has_key ("error_handler"):
            error_handler = kwds["error_handler"]
            del kwds["error_handler"]
        if kwds.has_key ("auth_handler"):
            auth_handler = kwds["auth_handler"]
            del kwds["auth_handler"]

        self.queue.put ((fn, args, kwds,
                         reply_handler, error_handler, auth_handler))

######
###### An asynchronous libcups API with graphical authentication and
###### retrying.
######

###
### A class to take care of an individual operation.
###
class _IPPAuthOperation:
    def __init__ (self, reply_handler, error_handler, conn,
                  user=None, fn=None, args=None, kwds=None):
        self._auth_called = False
        self._dialog_shown = False
        self._use_password = ''
        self._cancel = False
        self._reconnect = False
        self._reconnected = False
        self._user = user
        self._conn = conn
        self._try_as_root = self._conn.try_as_root
        self._client_fn = fn
        self._client_args = args
        self._client_kwds = kwds
        self._client_reply_handler = reply_handler
        self._client_error_handler = error_handler

        debugprint ("+%s" % self)

    def __del__ (self):
        debug.debugprint ("-%s" % self)

    def _destroy (self):
        del self._conn
        del self._client_fn
        del self._client_args
        del self._client_kwds
        del self._client_reply_handler
        del self._client_error_handler

    def error_handler (self, conn, exc):
        if self._client_fn == None:
            # This is the initial "connection" operation, or a
            # subsequent reconnection attempt.
            debugprint ("Connection/reconnection failed")
            return self._reconnect_error (conn, exc)

        if self._cancel:
            debugprint ("%s (_error_handler): canceled so chaining up" % self)
            return self._error (exc)

        if self._reconnect:
            self._reconnect = False
            self._reconnected = True
            debugprint ("%s (_error_handler): reconnecting (as %s)..." %
                        (self, self._user))
            conn.reconnect (self._user,
                            reply_handler=self._reconnect_reply,
                            error_handler=self._reconnect_error)
            return

        forbidden = False
        if type (exc) == cups.IPPError:
            (e, m) = exc.args
            if (e == cups.IPP_NOT_AUTHORIZED or
                e == cups.IPP_FORBIDDEN or
                e == cups.IPP_AUTHENTICATION_CANCELED):
                forbidden = (e == cups.IPP_FORBIDDEN)
            elif e == cups.IPP_SERVICE_UNAVAILABLE:
                return self._reconnect_error (conn, exc)
            else:
                return self._error (exc)
        elif type (exc) == cups.HTTPError:
            (s,) = exc.args
            if (s == cups.HTTP_UNAUTHORIZED or
                s == cups.HTTP_FORBIDDEN):
                forbidden = (s == cups.HTTP_FORBIDDEN)
            else:
                return self._error (exc)
        else:
            return self._error (exc)

        # Not authorized.
        if forbidden:
            debugprint ("%s (_error_handler): forbidden" % self)
        else:
            debugprint ("%s (_error_handler): not authorized" % self)

        if (self._try_as_root and
            self._user != 'root' and
            (self._conn.thread.host[0] == '/' or forbidden)):
            # This is a UNIX domain socket connection so we should
            # not have needed a password (or it is not a UDS but
            # we got an HTTP_FORBIDDEN response), and so the
            # operation must not be something that the current
            # user is authorised to do.  They need to try as root,
            # and supply the password.  However, to get the right
            # prompt, we need to try as root but with no password
            # first.
            debugprint ("Authentication: Try as root")
            self._user = "root"
            conn.reconnect (self._user,
                            reply_handler=self._reconnect_reply,
                            error_handler=self._reconnect_error)
            # Don't submit the task until we've connected.
            return

        if not self._auth_called:
            # We aren't even getting a chance to supply credentials.
            return self._error (exc)

        # Now reconnect and retry.
        host = conn.thread.host
        port = conn.thread.port
        authconn.global_authinfocache.remove_auth_info (host=host,
                                                        port=port)
        self._use_password = ''
        debugprint ("%s (_error_handler): reconnecting (as %s)..." %
                    (self, self._user))
        conn.reconnect (self._user,
                        reply_handler=self._reconnect_reply,
                        error_handler=self._reconnect_error)

    def auth_handler (self, prompt, conn, method=None, resource=None):
        if self._auth_called == False:
            if self._user == None:
                self._user = cups.getUser()
            if self._user:
                host = conn.thread.host
                port = conn.thread.port
                creds = authconn.global_authinfocache.lookup_auth_info (host=host,
                                                                        port=port)
                if creds:
                    if creds[0] == self._user:
                        self._use_password = creds[1]
                        self._reconnected = True
                    del creds
        else:
            host = conn.thread.host
            port = conn.thread.port
            authconn.global_authinfocache.remove_auth_info (host=host,
                                                            port=port)
            self._use_password = ''

        self._auth_called = True
        if self._reconnected:
            debugprint ("Supplying password after reconnection")
            self._reconnected = False
            conn.set_auth_info (self._use_password)
            return

        self._reconnected = False
        if not conn.prompt_allowed:
            conn.set_auth_info (self._use_password)
            return

        # If we've previously prompted, explain why we're prompting again.
        if self._dialog_shown:
            d = Gtk.MessageDialog (self._conn.parent,
                                   Gtk.DialogFlags.MODAL |
                                   Gtk.DialogFlags.DESTROY_WITH_PARENT,
                                   Gtk.MessageType.ERROR,
                                   Gtk.ButtonsType.CLOSE,
                                   _("Not authorized"))
            d.format_secondary_text (_("The password may be incorrect."))
            d.run ()
            d.destroy ()

        op = None
        if conn.semantic:
            op = conn.semantic.current_operation ()

        if op == None:
            d = authconn.AuthDialog (parent=conn.parent)
        else:
            title = _("Authentication (%s)") % op
            d = authconn.AuthDialog (title=title,
                                     parent=conn.parent)

        d.set_prompt ('')
        if self._user == None:
            self._user = cups.getUser()
        d.set_auth_info (['', ''])
        d.field_grab_focus ('username')
        d.set_keep_above (True)
        d.show_all ()
        d.connect ("response", self._on_auth_dialog_response)
        self._dialog_shown = True

    def submit_task (self):
        self._auth_called = False
        self._conn.queue.put ((self._client_fn, self._client_args,
                               self._client_kwds,
                               self._client_reply_handler,
                               
                               # Use our own error and auth handlers.
                               self.error_handler,
                               self.auth_handler))

    def _on_auth_dialog_response (self, dialog, response):
        (user, password) = dialog.get_auth_info ()
        if user == '':
            user = self._user;
        authconn.global_authinfocache.cache_auth_info ((user,
                                                        password),
                                                       host=self._conn.thread.host,
                                                       port=self._conn.thread.port)
        self._dialog = dialog
        dialog.hide ()

        if (response == Gtk.ResponseType.CANCEL or
            response == Gtk.ResponseType.DELETE_EVENT):
            self._cancel = True
            self._conn.set_auth_info ('')
            authconn.global_authinfocache.remove_auth_info (host=self._conn.thread.host,
                                                            port=self._conn.thread.port)
            debugprint ("Auth canceled")
            return

        if user == self._user:
            self._use_password = password
            self._conn.set_auth_info (password)
            debugprint ("Password supplied.")
            return

        self._user = user
        self._use_password = password
        self._reconnect = True
        self._conn.set_auth_info ('')
        debugprint ("Will try as %s" % self._user)

    def _reconnect_reply (self, conn, result):
        # A different username was given in the authentication dialog,
        # so we've reconnected as that user.  Alternatively, the
        # connection has failed and we're retrying.
        debugprint ("Connected as %s" % self._user)
        if self._client_fn != None:
            self.submit_task ()

    def _reconnect_error (self, conn, exc):
        debugprint ("Failed to connect as %s" % self._user)
        if not self._conn.prompt_allowed:
            self._error (exc)
            return

        op = None
        if conn.semantic:
            op = conn.semantic.current_operation ()

        if op == None:
            msg = _("CUPS server error")
        else:
            msg = _("CUPS server error (%s)") % op

        d = Gtk.MessageDialog (self._conn.parent,
                               Gtk.DialogFlags.MODAL |
                               Gtk.DialogFlags.DESTROY_WITH_PARENT,
                               Gtk.MessageType.ERROR,
                               Gtk.ButtonsType.NONE,
                               msg)

        if self._client_fn == None and type (exc) == RuntimeError:
            # This was a connection failure.
            message = 'service-error-service-unavailable'
        elif type (exc) == cups.IPPError:
            message = exc.args[1]
        else:
            message = repr (exc)

        d.format_secondary_text (_("There was an error during the "
                                   "CUPS operation: '%s'." % message))
        d.add_buttons (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                       _("Retry"), Gtk.ResponseType.OK)
        d.set_default_response (Gtk.ResponseType.OK)
        d.connect ("response", self._on_retry_server_error_response)
        debugprint ("%s (_reconnect_error): presenting error dialog (%s; %s)" %
                    (self, msg, message))
        d.show ()

    def _on_retry_server_error_response (self, dialog, response):
        dialog.destroy ()
        if response == Gtk.ResponseType.OK:
            debugprint ("%s: got retry response, reconnecting (as %s)..." %
                        (self, self._conn.thread.user))
            self._conn.reconnect (self._conn.thread.user,
                                  reply_handler=self._reconnect_reply,
                                  error_handler=self._reconnect_error)
        else:
            debugprint ("%s: got cancel response" % self)
            self._error (cups.IPPError (0, _("Operation canceled")))

    def _error (self, exc):
        debugprint ("%s (_error): handling %s" % (self, repr (exc)))
        if self._client_error_handler:
            debugprint ("%s (_error): calling %s" %
                        (self, self._client_error_handler))
            self._client_error_handler (self._conn, exc)
            self._destroy ()
        else:
            debugprint ("%s (_error): no client error handler set" % self)

###
### The user-visible class.
###
class IPPAuthConnection(IPPConnection):
    def __init__ (self, reply_handler=None, error_handler=None,
                  auth_handler=None, host=None, port=None, encryption=None,
                  parent=None, try_as_root=True, prompt_allowed=True,
                  semantic=None):
        self.parent = parent
        self.prompt_allowed = prompt_allowed
        self.try_as_root = try_as_root
        self.semantic = semantic

        user = None
        creds = authconn.global_authinfocache.lookup_auth_info (host=host,
                                                                port=port)
        if creds:
            if creds[0] != 'root' or try_as_root:
                user = creds[0]
            del creds

        # The "connect" operation.
        op = _IPPAuthOperation (reply_handler, error_handler, self)
        IPPConnection.__init__ (self, reply_handler=reply_handler,
                                error_handler=op.error_handler,
                                auth_handler=op.auth_handler, user=user,
                                host=host, port=port, encryption=encryption)

    def destroy (self):
        self.semantic = None
        IPPConnection.destroy (self)

    def _call_function (self, fn, *args, **kwds):
        reply_handler = error_handler = auth_handler = False
        if kwds.has_key ("reply_handler"):
            reply_handler = kwds["reply_handler"]
            del kwds["reply_handler"]
        if kwds.has_key ("error_handler"):
            error_handler = kwds["error_handler"]
            del kwds["error_handler"]
        if kwds.has_key ("auth_handler"):
            auth_handler = kwds["auth_handler"]
            del kwds["auth_handler"]

        # Store enough information about the current operation to
        # restart it if necessary.
        op = _IPPAuthOperation (reply_handler, error_handler, self,
                                self.thread.user, fn, args, kwds)

        # Run the operation but use our own error and auth handlers.
        op.submit_task ()

if __name__ == "__main__":
    # Demo
    set_debugging (True)
    GObject.threads_init ()
    class UI:
        def __init__ (self):
            w = Gtk.Window ()
            w.connect ("destroy", self.destroy)
            b = Gtk.Button ("Connect")
            b.connect ("clicked", self.connect_clicked)
            vbox = Gtk.VBox ()
            vbox.pack_start (b, False, False, 0)
            w.add (vbox)
            self.get_devices_button = Gtk.Button ("Get Devices")
            self.get_devices_button.connect ("clicked", self.get_devices)
            self.get_devices_button.set_sensitive (False)
            vbox.pack_start (self.get_devices_button, False, False, 0)
            self.conn = None
            w.show_all ()

        def destroy (self, window):
            try:
                self.conn.destroy ()
            except AttributeError:
                pass

            Gtk.main_quit ()

        def connect_clicked (self, button):
            if self.conn:
                self.conn.destroy ()

            self.conn = IPPAuthConnection (reply_handler=self.connected,
                                           error_handler=self.connect_failed)

        def connected (self, conn, result):
            debugprint ("Success: %s" % repr (result))
            self.get_devices_button.set_sensitive (True)

        def connect_failed (self, conn, exc):
            debugprint ("Exc %s" % repr (exc))
            self.get_devices_button.set_sensitive (False)
            self.conn.destroy ()

        def get_devices (self, button):
            button.set_sensitive (False)
            debugprint ("Getting devices")
            self.conn.getDevices (reply_handler=self.get_devices_reply,
                                  error_handler=self.get_devices_error)

        def get_devices_reply (self, conn, result):
            if conn != self.conn:
                debugprint ("Ignoring stale reply")
                return

            debugprint ("Got devices: %s" % repr (result))
            self.get_devices_button.set_sensitive (True)

        def get_devices_error (self, conn, exc):
            if conn != self.conn:
                debugprint ("Ignoring stale error")
                return

            debugprint ("Error getting devices: %s" % repr (exc))
            self.get_devices_button.set_sensitive (True)

    UI ()
    Gtk.main ()

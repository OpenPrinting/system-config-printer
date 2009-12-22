#!/usr/bin/env python

## Copyright (C) 2007, 2008, 2009 Red Hat, Inc.
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
## Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.

import threading
import config
import cups
import gobject
import gtk
import Queue

import authconn
from debug import *
import debug

_ = lambda x: x
N_ = lambda x: x
def set_gettext_function (fn):
    global _
    _ = fn

######
###### An asynchronous libcups API using IPP with a separate worker
###### thread.
######

###
### This is the worker thread.
###
class _IPPConnectionThread(threading.Thread):
    def __init__ (self, queue, conn, reply_handler=None, error_handler=None,
                  auth_handler=None, host=None, port=None, encryption=None):
                  
        threading.Thread.__init__ (self)
        self.setDaemon (True)
        self._queue = queue
        self._conn = conn
        self.host = host
        self._port = port
        self._encryption = encryption
        self._reply_handler = reply_handler
        self._error_handler = error_handler
        self._auth_handler = auth_handler
        self._auth_queue = Queue.Queue (1)
        self.user = None
        debugprint ("+%s" % self)

    def __del__ (self):
        debug.debugprint ("-%s" % self)

    def set_auth_info (self, password):
        self._auth_queue.put (password)

    def run (self):
        if self.host == None:
            self.host = cups.getServer ()
        if self._port == None:
            self._port = cups.getPort ()
        if self._encryption == None:
            self._encryption = cups.getEncryption ()

        self.user = cups.getUser ()

        try:
            cups.setPasswordCB2 (self._auth)
        except AttributeError:
            # Requires pycups >= 1.9.47.  Fall back to rubbish API.
            cups.setPasswordCB (self._auth)

        try:
            conn = cups.Connection (host=self.host,
                                    port=self._port,
                                    encryption=self._encryption)
        except RuntimeError, e:
            self._error (e)
            return

        self._reply (None)

        while True:
            # Wait to find out what operation to try.
            debugprint ("Awaiting further instructions")
            item = self._queue.get ()
            debugprint ("Next task: %s" % repr (item))
            if item == None:
                # Our signal to quit.
                self._queue.task_done ()
                break

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
                try:
                    cups.setPasswordCB2 (self._auth)
                except AttributeError:
                    # Requires pycups >= 1.9.47.  Fall back to rubbish API.
                    cups.setPasswordCB (self._auth)

                try:
                    conn = cups.Connection (host=self.host,
                                            port=self._port,
                                            encryption=self._encryption)
                    debugprint ("...reconnected")
                except RuntimeError, e:
                    debugprint ("...failed")
                    self._queue.task_done ()
                    self._error (e)
                    break

                self._queue.task_done ()
                self._reply (None)

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
            except Exception, e:
                debugprint ("...failure")
                self._error (e)

            self._queue.task_done ()

        debugprint ("Thread exiting")
        del self._conn # already destroyed
        del self._reply_handler
        del self._error_handler
        del self._auth_handler
        del self._queue
        del self._auth_queue
        del conn

        try:
            cups.setPasswordCB2 (None)
        except AttributeError:
            # Requires pycups >= 1.9.47.  Fall back to rubbish API.
            cups.setPasswordCB (lambda x: '')

    def _auth (self, prompt, conn=None, method=None, resource=None):
        def prompt_auth (prompt):
            if conn == None:
                self._auth_handler (prompt, self._conn)
            else:
                self._auth_handler (prompt, self._conn, method, resource)

            return False

        if self._auth_handler == None:
            return ""

        gobject.idle_add (prompt_auth, prompt)
        password = self._auth_queue.get ()
        return password

    def _reply (self, result):
        def send_reply (result):
            self._reply_handler (self._conn, result)
            return False

        if self._reply_handler:
            gobject.idle_add (send_reply, result)

    def _error (self, exc):
        def send_error (exc):
            self._error_handler (self._conn, exc)
            return False

        if self._error_handler:
            debugprint ("Add %s to idle" % self._error_handler)
            gobject.idle_add (send_error, exc)

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
                  auth_handler=None, host=None, port=None, encryption=None,
                  parent=None):
        debugprint ("New IPPConnection")
        self._parent = parent
        self.queue = Queue.Queue ()
        self.thread = _IPPConnectionThread (self.queue, self,
                                            reply_handler=reply_handler,
                                            error_handler=error_handler,
                                            auth_handler=auth_handler,
                                            host=host, port=port,
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
        if self.thread.isAlive ():
            debugprint ("Putting None on the task queue")
            self.queue.put (None)
            self.queue.join ()

        for binding in self.bindings:
            delattr (self, binding)

    def set_auth_info (self, password):
        """Call this from your auth_handler function."""
        self.thread.set_auth_info (password)

    def reconnect (self, user, reply_handler=None, error_handler=None):
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
            return self._reconnect_error (exc)

        if self._cancel:
            return self._error (exc)

        if self._reconnect:
            self._reconnect = False
            self._reconnected = True
            conn.reconnect (self._user,
                            reply_handler=self._reconnect_reply,
                            error_handler=self._reconnect_error)
            return

        forbidden = False
        if type (exc) == cups.IPPError:
            (e, m) = exc.args
            if (e == cups.IPP_NOT_AUTHORIZED or
                e == cups.IPP_FORBIDDEN):
                forbidden = (e == cups.IPP_FORBIDDEN)
            elif e == cups.IPP_SERVICE_UNAVAILABLE:
                return self._reconnect_error (exc)
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
            self._try_as_root = False
            conn.reconnect (self._user,
                            reply_handler=self._reconnect_reply,
                            error_handler=self._reconnect_error)
            # Don't submit the task until we've connected.
            return

        if not self._auth_called:
            # We aren't even getting a chance to supply credentials.
            return self._error (exc)

        # Now reconnect and retry.
        conn.reconnect (self._user,
                        reply_handler=self._reconnect_reply,
                        error_handler=self._reconnect_error)

    def auth_handler (self, prompt, conn, method=None, resource=None):
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
            d = gtk.MessageDialog (self._conn.parent,
                                   gtk.DIALOG_MODAL |
                                   gtk.DIALOG_DESTROY_WITH_PARENT,
                                   gtk.MESSAGE_ERROR,
                                   gtk.BUTTONS_CLOSE,
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

        d.set_prompt (prompt)
        d.set_auth_info ([self._user, ''])
        d.field_grab_focus ('password')
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
        self._dialog = dialog
        dialog.hide ()

        if (response == gtk.RESPONSE_CANCEL or
            response == gtk.RESPONSE_DELETE_EVENT):
            self._cancel = True
            self._conn.set_auth_info ('')
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

        d = gtk.MessageDialog (self._conn.parent,
                               gtk.DIALOG_MODAL |
                               gtk.DIALOG_DESTROY_WITH_PARENT,
                               gtk.MESSAGE_ERROR,
                               gtk.BUTTONS_NONE,
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
        d.add_buttons (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                       _("Retry"), gtk.RESPONSE_OK)
        d.set_default_response (gtk.RESPONSE_OK)
        d.connect ("response", self._on_retry_server_error_response)

    def _on_retry_server_error_response (self, dialog, response):
        dialog.destroy ()
        if response == gtk.RESPONSE_OK:
            self.reconnect (self._conn.thread.user,
                            reply_handler=self._reconnect_reply,
                            error_handler=self._reconnect_error)
        else:
            self._error (cups.IPPError (0, _("Operation canceled")))

    def _error (self, exc):
        if self._client_error_handler:
            self._client_error_handler (self._conn, exc)
            self._destroy ()

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

        # The "connect" operation.
        op = _IPPAuthOperation (reply_handler, error_handler, self)
        IPPConnection.__init__ (self, reply_handler=reply_handler,
                                error_handler=op.error_handler,
                                auth_handler=op.auth_handler, host=host,
                                port=port, encryption=encryption)

    def destroy (self):
        del self.semantic
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
    import gtk
    set_debugging (True)
    gobject.threads_init ()
    class UI:
        def __init__ (self):
            w = gtk.Window ()
            w.connect ("destroy", self.destroy)
            b = gtk.Button ("Connect")
            b.connect ("clicked", self.connect_clicked)
            vbox = gtk.VBox ()
            vbox.pack_start (b)
            w.add (vbox)
            self.get_devices_button = gtk.Button ("Get Devices")
            self.get_devices_button.connect ("clicked", self.get_devices)
            self.get_devices_button.set_sensitive (False)
            vbox.pack_start (self.get_devices_button)
            self.conn = None
            w.show_all ()

        def destroy (self, window):
            try:
                self.conn.destroy ()
            except AttributeError:
                pass

            gtk.main_quit ()

        def connect_clicked (self, button):
            if self.conn:
                self.conn.destroy ()

            self.conn = IPPAuthConnection (reply_handler=self.connected,
                                           error_handler=self.connect_failed)

        def connected (self, conn, result):
            debugprint ("Success: %s" % result)
            self.get_devices_button.set_sensitive (True)

        def connect_failed (self, conn, exc):
            debugprint ("Exc %s" % exc)
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

            debugprint ("Got devices: %s" % result)
            self.get_devices_button.set_sensitive (True)

        def get_devices_error (self, conn, exc):
            if conn != self.conn:
                debugprint ("Ignoring stale error")
                return

            debugprint ("Error getting devices: %s" % exc)
            self.get_devices_button.set_sensitive (True)

    UI ()
    gtk.main ()

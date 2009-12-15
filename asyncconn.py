#!/usr/bin/env python

## Copyright (C) 2007, 2008, 2009 Red Hat, Inc.
## Copyright (C) 2008 Novell, Inc.
## Authors: Tim Waugh <twaugh@redhat.com>, Vincent Untz

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
import Queue
from debug import *

_ = lambda x: x
N_ = lambda x: x
def set_gettext_function (fn):
    global _
    _ = fn

class IPPConnectionThread(threading.Thread):
    def __init__ (self, queue, reply_handler=None, error_handler=None,
                  auth_handler=None, host=None, port=None, encryption=None):
                  
        threading.Thread.__init__ (self)
        self.setDaemon (True)
        self._queue = queue
        self._host = host
        self._port = port
        self._encryption = encryption
        self._reply_handler = reply_handler
        self._error_handler = error_handler
        self._auth_handler = auth_handler
        self._auth_queue = Queue.Queue (1)
        self.user = None

    def set_auth_info (self, password):
        self._auth_queue.put (password)

    def run (self):
        if self._host == None:
            self._host = cups.getServer ()
        if self._port == None:
            self._port = cups.getPort ()
        if self._encryption == None:
            self._encryption = cups.getEncryption ()

        self.user = cups.getUser ()
        cups.setPasswordCB (self._auth)
        try:
            self.conn = cups.Connection (host=self._host,
                                         port=self._port,
                                         encryption=self._encryption)
        except RuntimeError, e:
            self._error (e)
            return

        self._reply (None)

        while True:
            # Wait to find out what operation to try.
            item = self._queue.get ()
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
                try:
                    self.conn = cups.Connection (host=self._host,
                                                 port=self._port,
                                                 encryption=self._encryption)
                except RuntimeError, e:
                    self._queue.task_done ()
                    self._error (e)
                    break

                self._queue.task_done ()
                self._reply (None)
                continue

            # Normal IPP operation.  Try to perform it.
            try:
                result = fn (self.conn, *args, **kwds)
                if fn == cups.Connection.adminGetServerSettings.__call__:
                    # Special case for a rubbish bit of API.
                    if result == {}:
                        # Authentication failed, but we aren't told that.
                        raise cups.IPPError (cups.IPP_NOT_AUTHORIZED, '')

                self._reply (result)
            except Exception, e:
                self._error (e)

            self._queue.task_done ()

    def _auth (self, prompt):
        def prompt_auth (prompt):
            self._auth_handler (prompt)
            return False

        if self._auth_handler == None:
            return ""

        gobject.idle_add (prompt_auth, prompt)
        password = self._auth_queue.get ()
        return password

    def _reply (self, result):
        def send_reply (result):
            self._reply_handler (result)
            return False

        if self._reply_handler:
            gobject.idle_add (send_reply, result)

    def _error (self, exc):
        def send_error (exc):
            self._error_handler (exc)
            return False

        if self._error_handler:
            gobject.idle_add (send_error, exc)

class IPPConnection:
    def __init__ (self, reply_handler=None, error_handler=None,
                  auth_handler=None, host=None, port=None, encryption=None):
        debugprint ("New IPPConnection")
        self.queue = Queue.Queue ()
        self.thread = IPPConnectionThread (self.queue,
                                           reply_handler=reply_handler,
                                           error_handler=error_handler,
                                           auth_handler=auth_handler,
                                           host=host, port=port,
                                           encryption=encryption)
        self.thread.start ()

        methodtype = type (cups.Connection.getPrinters)
        for fname in dir (cups.Connection):
            if fname[0] == ' ':
                continue
            fn = getattr (cups.Connection, fname)
            if type (fn) != methodtype:
                continue
            setattr (self, fname, self._make_binding (fn))

    def __fini__ (self):
        if self.thread.isAlive ():
            debugprint ("Putting None on the task queue")
            self.queue.put (None)
            self.queue.join ()

    def set_auth_info (self, password):
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
            del self.conn
            gtk.main_quit ()

        def connect_clicked (self, button):
            self.conn = IPPConnection (reply_handler=self.connected,
                                       error_handler=self.connect_failed)

        def connected (self, result):
            debugprint ("Success: %s" % result)
            self.conn.reconnect ("root", reply_handler=self.connected_root,
                                 error_handler=self.connect_failed)

        def connected_root (self, result):
            debugprint ("Reconnect success: %s" % result)
            self.get_devices_button.set_sensitive (True)

        def connect_failed (self, exc):
            debugprint ("Exc %s" % exc)
            self.get_devices_button.set_sensitive (False)
            del self.conn

        def get_devices (self, button):
            button.set_sensitive (False)
            debugprint ("Getting devices")
            self.conn.getDevices (reply_handler=self.get_devices_reply,
                                  error_handler=self.get_devices_error,
                                  auth_handler=self.auth_handler)

        def get_devices_reply (self, result):
            debugprint ("Got devices: %s" % result)
            self.get_devices_button.set_sensitive (True)

        def get_devices_error (self, exc):
            raise exc
            self.get_devices_button.set_sensitive (True)

        def auth_handler (self, prompt):
            w = gtk.Window ()
            hbox = gtk.HBox ()
            w.add (hbox)
            label = gtk.Label (prompt)
            hbox.pack_start (label)
            self.auth_entry = gtk.Entry ()
            hbox.pack_start (self.auth_entry)
            b = gtk.Button ("Go")
            hbox.pack_start (b)
            b.connect ("clicked", self.set_auth_info)
            w.show_all ()
            self.w = w

        def set_auth_info (self, button):
            self.conn.set_auth_info (self.auth_entry.get_text ())
            self.w.destroy ()

    UI ()
    gtk.main ()

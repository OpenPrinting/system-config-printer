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

import cups
import dbus
import os

import asyncpk1
from debug import *
import debug

PK_AUTH_NAME  = 'org.freedesktop.PolicyKit.AuthenticationAgent'
PK_AUTH_PATH  = '/org/gnome/PolicyKit/Manager'
PK_AUTH_IFACE = 'org.freedesktop.PolicyKit.AuthenticationAgent'

######
###### A polkit-0 based asynchronous CupsPkHelper interface made to
###### work in the same way as a PK1Connection class.
######

###
### A class to handle an asynchronous method call.
###
class _PK0AsyncMethodCall(asyncpk1._PK1AsyncMethodCall):
    def __init__ (self, bus, conn, pk_method_name, pk_args,
                  reply_handler, error_handler, unpack_fn,
                  fallback_fn, args, kwds, parent):
        asyncpk1._PK1AsyncMethodCall.__init__ (self, bus, conn, pk_method_name,
                                               pk_args, reply_handler,
                                               error_handler, unpack_fn,
                                               fallback_fn, args, kwds)
        self._parent = parent
        debugprint ("+_PK0AsyncMethodCall: %s" % self)

    def __del__ (self):
        debug.debugprint ("-_PK0AsyncMethodCall: %s" % self)
        asyncpk1._PK1AsyncMethodCall.__del__ (self)

    def _destroy (self):
        debugprint ("DESTROY: %s" % self)
        asyncpk1._PK1AsyncMethodCall._destroy (self)

    def _pk_error_handler (self, exc):
        if exc.get_dbus_name () != asyncpk1.CUPS_PK_NEED_AUTH:
            return asyncpk1._PK1AsyncMethodCall._pk_error_handler (self, exc)

        tokens = exc.get_dbus_message ().split (' ', 2)
        if len (tokens) != 3:
            return asyncpk1._PK1AsyncMethodCall._pk_error_handler (self, exc)

        try:
            bus = dbus.SessionBus ()
        except dbus.exceptions.DBusException:
            return asyncpk1._PK1AsyncMethodCall._pk_error_handler (self, exc)

        try:
            xid = 0
            if (self._parent and
                getattr (self._parent, 'window') and
                getattr (self._parent.window, 'xid')):
                xid = self._parent.window.xid

            obj = bus.get_object (PK_AUTH_NAME, PK_AUTH_PATH)
            proxy = dbus.Interface (obj, PK_AUTH_IFACE)
            proxy.ObtainAuthorization (tokens[0],
                                       dbus.UInt32 (xid),
                                       dbus.UInt32 (os.getpid ()),
                                       reply_handler=self._auth_reply_handler,
                                       error_handler=self._auth_error_handler)
        except dbus.exceptions.DBusException, e:
            debugprint ("Failed to obtain authorization: %s" % repr (e))
            return asyncpk1._PK1AsyncMethodCall._pk_error_handler (self, exc)

    def _auth_reply_handler (self, result):
        if type (result) != dbus.Boolean:
            self.call_fallback_fn ()
            return

        if not result:
            exc = cups.IPPError (cups.IPP_NOT_AUTHORIZED, 'pkcancel')
            self._client_error_handler (self._conn, exc)
            self._destroy ()
            return

        # Auth succeeded.  Now resubmit the method call.
        self.call ()

    def _auth_error_handler (self, exc):
        self.call_fallback_fn ()

###
### The user-visible class.
###
class PK0Connection(asyncpk1.PK1Connection):
    def __init__(self, reply_handler=None, error_handler=None,
                 host=None, port=None, encryption=None, parent=None):
        asyncpk1.PK1Connection.__init__ (self, reply_handler=reply_handler,
                                         error_handler=error_handler,
                                         host=host, port=port,
                                         encryption=encryption,
                                         parent=parent)
        self._parent = parent
        debugprint ("+%s" % self)

    def _call_with_pk (self, use_pycups, pk_method_name, pk_args,
                       reply_handler, error_handler, unpack_fn,
                       fallback_fn, args, kwds):
        asyncmethodcall = _PK0AsyncMethodCall (self._system_bus, self,
                                               pk_method_name, pk_args,
                                               reply_handler, error_handler,
                                               unpack_fn, fallback_fn,
                                               args, kwds, self._parent)

        if use_pycups:
            return asyncmethodcall.call_fallback_fn ()

        debugprint ("Calling PK method %s" % pk_method_name)
        asyncmethodcall.call ()

if __name__ == '__main__':
    import gobject
    import gtk
    gobject.threads_init ()
    from debug import set_debugging
    set_debugging (True)
    class UI:
        def __init__ (self):
            w = gtk.Window ()
            v = gtk.VBox ()
            w.add (v)
            b = gtk.Button ("Go")
            v.pack_start (b)
            b.connect ("clicked", self.button_clicked)
            b = gtk.Button ("Fetch")
            v.pack_start (b)
            b.connect ("clicked", self.fetch_clicked)
            b.set_sensitive (False)
            self.fetch_button = b
            b = gtk.Button ("Cancel job")
            v.pack_start (b)
            b.connect ("clicked", self.cancel_clicked)
            b.set_sensitive (False)
            self.cancel_button = b
            b = gtk.Button ("Get file")
            v.pack_start (b)
            b.connect ("clicked", self.get_file_clicked)
            b.set_sensitive (False)
            self.get_file_button = b
            b = gtk.Button ("Something harmless")
            v.pack_start (b)
            b.connect ("clicked", self.harmless_clicked)
            b.set_sensitive (False)
            self.harmless_button = b
            w.connect ("destroy", self.destroy)
            w.show_all ()
            self.conn = None
            debugprint ("+%s" % self)
            self.mainwin = w

        def __del__ (self):
            debug.debugprint ("-%s" % self)

        def destroy (self, window):
            debugprint ("DESTROY: %s" % self)
            try:
                self.conn.destroy ()
                del self.conn
            except AttributeError:
                pass

            gtk.main_quit ()

        def button_clicked (self, button):
            if self.conn:
                self.conn.destroy ()

            self.conn = PK0Connection (reply_handler=self.connected,
                                       error_handler=self.connection_error,
                                       parent=self.mainwin)

        def connected (self, conn, result):
            print "Connected"
            self.fetch_button.set_sensitive (True)
            self.cancel_button.set_sensitive (True)
            self.get_file_button.set_sensitive (True)
            self.harmless_button.set_sensitive (True)

        def connection_error (self, conn, error):
            print "Failed to connect"
            raise error

        def fetch_clicked (self, button):
            print ("fetch devices...")
            self.conn.getDevices (reply_handler=self.got_devices,
                                  error_handler=self.get_devices_error)

        def got_devices (self, conn, devices):
            if conn != self.conn:
                print "Ignoring stale reply"
                return

            print "got devices: %s" % devices

        def get_devices_error (self, conn, exc):
            if conn != self.conn:
                print "Ignoring stale error"
                return

            print "devices error: %s" % repr (exc)

        def cancel_clicked (self, button):
            print "Cancel job..."
            self.conn.cancelJob (1,
                                 reply_handler=self.job_canceled,
                                 error_handler=self.cancel_job_error)

        def job_canceled (self, conn, none):
            if conn != self.conn:
                print "Ignoring stale reply for %s" % conn
                return

            print "Job canceled"

        def cancel_job_error (self, conn, exc):
            if conn != self.conn:
                print "Ignoring stale error for %s" % conn
                return

            print "cancel error: %s" % repr (exc)

        def get_file_clicked (self, button):
            self.my_file = file ("/tmp/foo", "w")
            self.conn.getFile ("/admin/conf/cupsd.conf", file=self.my_file,
                               reply_handler=self.got_file,
                               error_handler=self.get_file_error)

        def got_file (self, conn, none):
            if conn != self.conn:
                print "Ignoring stale reply for %s" % conn
                return

            print "Got file"

        def get_file_error (self, conn, exc):
            if conn != self.conn:
                print "Ignoring stale error"
                return

            print "get file error: %s" % repr (exc)

        def harmless_clicked (self, button):
            self.conn.getJobs (reply_handler=self.got_jobs,
                               error_handler=self.get_jobs_error)

        def got_jobs (self, conn, result):
            if conn != self.conn:
                print "Ignoring stale reply from %s" % repr (conn)
                return
            print result

        def get_jobs_error (self, exc):
            print "get jobs error: %s" % repr (exc)

    UI ()
    gtk.main ()

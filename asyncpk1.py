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
import gobject
import gtk
import os
import sys
import tempfile

import asyncipp
from debug import *

from dbus.mainloop.glib import DBusGMainLoop
DBusGMainLoop (set_as_default=True)

_ = lambda x: x
N_ = lambda x: x
def set_gettext_function (fn):
    global _
    _ = fn

CUPS_PK_NAME  = 'org.opensuse.CupsPkHelper.Mechanism'
CUPS_PK_PATH  = '/'
CUPS_PK_IFACE = 'org.opensuse.CupsPkHelper.Mechanism'
CUPS_PK_NEED_AUTH = 'org.opensuse.CupsPkHelper.Mechanism.NotPrivileged'

######
###### A polkit-1 based asynchronous CupsPkHelper interface made to
###### look just like a normal IPPAuthConnection class.  For method
###### calls that have no equivalent in the CupsPkHelper API, IPP
###### authentication is used over a CUPS connection in a separate
###### thread.
######

###
### A class to handle an asynchronous method call.
###
class _PK1AsyncMethodCall:
    def __init__ (self, bus, conn, pk_method_name, pk_args,
                  reply_handler, error_handler, unpack_fn,
                  fallback_fn, args, kwds):
        self._client_reply_handler = reply_handler
        self._client_error_handler = error_handler
        object = bus.get_object(CUPS_PK_NAME, CUPS_PK_PATH)
        proxy = dbus.Interface (object, CUPS_PK_IFACE)
        self._conn = conn
        self._pk_method = proxy.get_dbus_method (pk_method_name)
        self._pk_args = pk_args
        self._unpack_fn = unpack_fn
        self._fallback_fn = fallback_fn
        self._fallback_args = args
        self._fallback_kwds = kwds

    def call (self):
        try:
            self._pk_method (*self._pk_args,
                             reply_handler=self._pk_reply_handler,
                             error_handler=self._pk_error_handler)
        except TypeError, e:
            debugprint ("Type error in PK call: %s" % e)
            self._call_fallback_fn ()

    def _pk_reply_handler (self, *args):
        self._client_reply_handler (self._conn, self._unpack_fn (*args))

    def _pk_error_handler (self, exc):
        if exc.get_dbus_name () == CUPS_PK_NEED_AUTH:
            exc = cups.IPPError (cups.IPP_NOT_AUTHORIZED, 'pkcancel')
            self._client_error_handler (self._conn, exc)

        debugprint ("PolicyKit call to %s did not work: %s" %
                    (self._pk_method_name, exc))
        self._call_fallback_fn ()

    def _call_fallback_fn (self):
        # Make the 'connection' parameter consistent with PK callbacks.
        self._fallback_kwds["reply_handler"] = self._ipp_reply_handler
        self._fallback_kwds["error_handler"] = self._ipp_error_handler
        self._fallback_fn (*self._fallback_args, **self._fallback_kwds)

    def _ipp_reply_handler (self, conn, *args):
        self._client_reply_handler (self._conn, *args)

    def _ipp_error_handler (self, conn, *args):
        self._client_error_handler (self._conn, *args)

###
### The user-visible class.
###
class PK1Connection:
    def __init__(self, reply_handler=None, error_handler=None,
                 host=None, port=None, encryption=None, parent=None):
        self._conn = asyncipp.IPPAuthConnection  (reply_handler=reply_handler,
                                                  error_handler=error_handler,
                                                  host=host, port=port,
                                                  encryption=encryption,
                                                  parent=parent)

        try:
            self._system_bus = dbus.SystemBus()
        except (dbus.exceptions.DBusException, AttributeError):
            # No system D-Bus.
            self._system_bus = None

    def _coerce (self, typ, val):
        return typ (val)

    def _args_kwds_to_tuple (self, types, params, args, kwds):
        """Collapse args and kwds into a single tuple."""
        leftover_kwds = kwds.copy ()
        reply_handler = leftover_kwds.get ("reply_handler")
        error_handler = leftover_kwds.get ("error_handler")
        if leftover_kwds.has_key ("reply_handler"):
            del leftover_kwds["reply_handler"]
        if leftover_kwds.has_key ("error_handler"):
            del leftover_kwds["error_handler"]
        if leftover_kwds.has_key ("auth_handler"):
            del leftover_kwds["auth_handler"]

        result = [True, reply_handler, error_handler, ()]
        if self._system_bus == None:
            return result

        tup = []
        argindex = 0
        for arg in args:
            try:
                val = self._coerce (types[argindex], arg)
            except TypeError, e:
                debugprint ("Error converting %s to %s" %
                            (repr (arg), types[argindex]))
                return result

            tup.append (val)
            argindex += 1

        for kw, default in params[argindex:]:
            if leftover_kwds.has_key (kw):
                try:
                    val = self._coerce (types[argindex], leftover_kwds[kw])
                except TypeError, e:
                    debugprint ("Error converting %s to %s" %
                                (repr (leftover_kwds[kw]), types[argindex]))
                    return result

                tup.append (val)
                del leftover_kwds[kw]
            else:
                tup.append (default)

            argindex += 1

        if leftover_kwds:
            debugprint ("Leftover keywords: %s" % repr (leftover_kwds.keys ()))
            return result

        result[0] = False
        result[3] = tuple (tup)
        debugprint ("Converted %s/%s to %s" % (args, kwds, tuple (tup)))
        return result

    def _call_with_pk (self, use_pycups, pk_method_name, pk_args,
                       reply_handler, error_handler, unpack_fn,
                       fallback_fn, args, kwds):
        if not use_pycups:
            try:
                asyncmethodcall = _PK1AsyncMethodCall (self._system_bus,
                                                       self,
                                                       pk_method_name,
                                                       pk_args,
                                                       reply_handler,
                                                       error_handler,
                                                       unpack_fn,
                                                       fallback_fn,
                                                       args, kwds)
            except dbus.exceptions.DBusException, e:
                debugprint ("Failed to get D-Bus method for %s: %s" %
                            (pk_method_name, e))
                use_pycups = True

        if use_pycups:
            return fallback_fn (*args, **kwds)

        debugprint ("Calling PK method %s" % pk_method_name)
        asyncmethodcall.call ()

    def getDevices (self, *args, **kwds):
        (use_pycups, reply_handler, error_handler,
         tup) = self._args_kwds_to_tuple ([int, str, str],
                                          [("limit", 0),
                                           ("include_schemes", ""),
                                           ("exclude_schemes", "")],
                                          args, kwds)

        if not use_pycups:
            # Special handling for include_schemes/exclude_schemes.
            # Convert from list to ","-separated string.
            newtup = list (tup)
            for paramindex in [1, 2]:
                if len (newtup[paramindex]) > 0:
                    newtup[paramindex] = reduce (lambda x, y: x + "," + y,
                                                 newtup[paramindex])
                else:
                    newtup[paramindex] = ""

            tup = tuple (newtup)

        self._call_with_pk (use_pycups,
                            'DevicesGet', tup, reply_handler, error_handler,
                            self._unpack_getDevices_reply,
                            self._conn.getDevices, args, kwds)

    def _unpack_getDevices_reply (self, unused, dbusdict):
        result_str = dict()
        for key, value in dbusdict.iteritems ():
            if type (key) == dbus.String:
                result_str[str (key)] = str (value)
            else:
                result_str[key] = value

        # cups-pk-helper returns all devices in one dictionary.
        # Keys of different devices are distinguished by ':n' postfix.

        devices = dict()
        n = 0
        affix = ':' + str (n)
        device_keys = [x for x in result_str.keys () if x.endswith (affix)]
        while len (device_keys) > 0:
            device_uri = None
            device_dict = dict()
            for keywithaffix in device_keys:
                key = keywithaffix[:len (keywithaffix) - len (affix)]
                if key != 'device-uri':
                    device_dict[key] = result_str[keywithaffix]
                else:
                    device_uri = result_str[keywithaffix]

            if device_uri != None:
                devices[device_uri] = device_dict

            n += 1
            affix = ':' + str (n)
            device_keys = [x for x in result_str.keys () if x.endswith (affix)]

        return devices

if __name__ == '__main__':
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
            w.connect ("destroy", self.destroy)
            w.show_all ()

        def destroy (self, window):
            del self.conn
            gtk.main_quit ()

        def button_clicked (self, button):
            self.conn = PK1Connection (reply_handler=self.connected,
                                       error_handler=self.connection_error)

        def connected (self, conn, result):
            print "Connected"
            self.fetch_button.set_sensitive (True)

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

    UI ()
    gtk.main ()

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

######
###### A polkit-1 based asynchronous CupsPkHelper interface made to
###### look just like a normal IPPAuthConnection class.  For method
###### calls that have no equivalent in the CupsPkHelper API, IPP
###### authentication is used over a CUPS connection in a separate
###### thread.
######
class PK1Connection(asyncipp.IPPAuthConnection):
    def __init__(self, reply_handler=None, error_handler=None,
                 host=None, port=None, encryption=None, parent=None):
        asyncipp.IPPAuthConnection.__init__ (self,
                                             reply_handler=reply_handler,
                                             error_handler=error_handler,
                                             host=host, port=port,
                                             encryption=encryption,
                                             parent=parent)

        try:
            self._session_bus = dbus.SessionBus()
            self._system_bus = dbus.SystemBus()
        except dbus.exceptions.DBusException:
            # One or other bus not running.
            self._session_bus = self._system_bus = None

    def _get_cups_pk(self):
        try:
            object = self._system_bus.get_object(CUPS_PK_NAME, CUPS_PK_PATH)
            return dbus.Interface(object, CUPS_PK_IFACE)
        except dbus.exceptions.DBusException:
            # Failed to get object or interface.
            return None
        except AttributeError:
            # No system D-Bus
            return None

    def _call_with_pk_and_fallback(self, use_fallback, pk_function_name,
                                   pk_args, fallback_function, *args, **kwds):
        pk_function = None

        if not use_fallback:
            cups_pk = self._get_cups_pk()
            if cups_pk:
                try:
                    pk_function = cups_pk.get_dbus_method(pk_function_name)
                except dbus.exceptions.DBusException:
                    pass

        if use_fallback or not pk_function:
            return fallback_function(*args, **kwds)

        reply_handler = kwds.get ("reply_handler")
        error_handler = kwds.get ("error_handler")
        if reply_handler and error_handler:
            pk_function (*pk_args,
                          reply_handler=reply_handler,
                          error_handler=error_handler)
        else:
            pk_function (*pk_args)

    def _error_handler (self, *args):
        print args

    def _args_to_tuple(self, types, *args):
        retval = [ False ]

        if len(types) != len(args):
            retval[0] = True
            # We do this to have the right length for the returned value
            retval.extend(types)
            return tuple(types)

        exception = False

        for i in range(len(types)):
            if type(args[i]) != types[i]:
                if types[i] == str and type(args[i]) == unicode:
                    # we accept a mix between unicode and str
                    pass
                elif types[i] == str and type(args[i]) == int:
                    # we accept a mix between int and str
                    retval.append(str(args[i]))
                    continue
                elif types[i] == str and type(args[i]) == float:
                    # we accept a mix between float and str
                    retval.append(str(args[i]))
                    continue
                elif types[i] == str and type(args[i]) == bool:
                    # we accept a mix between bool and str
                    retval.append(str(args[i]))
                    continue
                elif types[i] == str and args[i] == None:
                    # None is an empty string for dbus
                    retval.append('')
                    continue
                elif types[i] == list and type(args[i]) == tuple:
                    # we accept a mix between list and tuple
                    retval.append(list(args[i]))
                    continue
                elif types[i] == list and args[i] == None:
                    # None is an empty list
                    retval.append([])
                    continue
                else:
                    exception = True
            retval.append(args[i])

        retval[0] = exception

        return tuple(retval)


    def _kwds_to_vars(self, names, **kwds):
        ret = []

        for name in names:
            if kwds.has_key(name):
                ret.append(kwds[name])
            else:
                ret.append('')

        return tuple(ret)


#    getPrinters
#    getDests
#    getClasses
#    getPPDs
#    getServerPPD
#    getDocument


    def getDevices(self, *args, **kwds):
        use_pycups = False

        limit = 0
        include_schemes = ''
        exclude_schemes = ''
        timeout = 0

        if len(args) == 4:
            (use_pycups, limit, include_schemes, exclude_schemes, timeout) = self._args_to_tuple([int, str, str, int], *args)
        else:
            if kwds.has_key('timeout'):
                timeout = kwds['timeout']

            if kwds.has_key('include_schemes'):
                include_schemes = kwds['include_schemes']

            if kwds.has_key('exclude_schemes'):
                exclude_schemes = kwds['exclude_schemes']

        # Convert from list to string
        if len (include_schemes) > 0:
            include_schemes = reduce (lambda x, y: x + "," + y, include_schemes)
        else:
            include_schemes = ""

        if len (exclude_schemes) > 0:
            exclude_schemes = reduce (lambda x, y: x + "," + y, exclude_schemes)
        else:
            exclude_schemes = ""

        pk_args = (timeout, include_schemes, exclude_schemes)

        reply_handler = kwds["reply_handler"]
        def getDevices_reply_handler (*args):
            print repr (args)
            reply_handler (args)

        self._call_with_pk_and_fallback(use_pycups,
                                        'DevicesGet', pk_args,
                                        super (asyncipp.IPPAuthConnection,
                                               self).getDevices,
                                        *args, **kwds)
        return

        # return 'result' if fallback was called
        if len (result.keys()) > 0 and type (result[result.keys()[0]]) == dict:
             return result

        result_str = {}
        if result != None:
            for i in result.keys():
                if type(i) == dbus.String:
                    result_str[str(i)] = str(result[i])
                else:
                    result_str[i] = result[i]

        # cups-pk-helper returns all devices in one dictionary.
        # Keys of different devices are distinguished by ':n' postfix.

        devices = {}
        n = 0
        postfix = ':' + str (n)
        device_keys = [x for x in result_str.keys() if x.endswith(postfix)]
        while len (device_keys) > 0:

            device_uri = None
            device_dict = {}
            for i in device_keys:
                key = i[:len(i) - len(postfix)]
                if key != 'device-uri':
                    device_dict[key] = result_str[i]
                else:
                    device_uri = result_str[i]

            if device_uri != None:
                devices[device_uri] = device_dict

            n += 1
            postfix = ':' + str (n)
            device_keys = [x for x in result_str.keys() if x.endswith(postfix)]

        return devices

if __name__ == '__main__':
    import gtk
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

        def got_devices (self, *args):
            print "got devices: %s" % repr (args)

        def get_devices_error (self, *args):
            print "devices error: %s" % repr (args)

    UI ()
    gtk.main ()

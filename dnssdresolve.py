#!/usr/bin/python

## Copyright (C) 2010, 2011, 2012, 2013 Red Hat, Inc.
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

import dbus, re
from debug import *

class DNSSDHostNamesResolver:
    def __init__ (self, devices):
        self._devices = devices
        self._unresolved = len (devices)
        self._device_uri_by_name = {}
        debugprint ("+%s" % self)

    def __del__ (self):
        debugprint ("-%s" % self)

    def resolve (self, reply_handler):

        def expandhex (searchres):
            expr = searchres.group(0)
            return chr(int(expr[1:], 16))

        self._reply_handler = reply_handler

        bus = dbus.SystemBus ()
        if not bus:
            reply_handler ([])
            del self._devices
            del self._reply_handler
            return

        for uri, device in self._devices.iteritems ():
            if not uri.startswith ("dnssd://"):
                self._unresolved -= 1
                continue

            # We need to resolve the DNS-SD hostname in order to
            # compare with other network devices.
            p = uri[8:].find ("/")
            if p == -1:
                hostname = uri[8:]
            else:
                hostname = uri[8:8+p]

            hostname = hostname.encode('utf-8')
            hostname = re.sub("%(?i)[\dabcdef]{2}", expandhex, hostname)

            elements = hostname.rsplit (".", 3)
            if len (elements) != 4:
                self._resolved ()
                continue

            name, stype, protocol, domain = elements
            stype += "." + protocol #  e.g. _printer._tcp

            try:
                obj = bus.get_object ("org.freedesktop.Avahi", "/")
                server = dbus.Interface (obj,
                                         "org.freedesktop.Avahi.Server")
                self._device_uri_by_name[(name, stype, domain)] = uri
                debugprint ("Resolving address for %s" % hostname)
                server.ResolveService (-1, -1,
                                        name, stype, domain,
                                        -1, 0,
                                        reply_handler=self._reply,
                                        error_handler=lambda e:
                                            self._error (uri, e))
            except dbus.DBusException as e:
                debugprint ("Failed to resolve address: %s" % repr (e))
                self._resolved ()

    def _resolved (self):
        self._unresolved -= 1
        if self._unresolved == 0:
            debugprint ("All addresses resolved")
            self._reply_handler (self._devices)
            del self._devices
            del self._reply_handler

    def _reply (self, interface, protocol, name, stype, domain,
                host, aprotocol, address, port, txt, flags):
        uri = self._device_uri_by_name[(name.encode ('utf-8'), stype, domain)]
        self._devices[uri].address = address
        hostname = host
        p = hostname.find(".")
        if p != -1:
            hostname = hostname[:p]
        debugprint ("%s is at %s (%s)" % (uri, address, hostname))
        self._devices[uri].hostname = hostname
        self._resolved ()

    def _error (self, uri, error):
        debugprint ("Error resolving %s: %s" % (uri, repr (error)))
        self._resolved ()

if __name__ == '__main__':
    class Device:
        def __repr__ (self):
            try:
                return "<Device @ %s>" % self.address
            except:
                return "<Device>"

    devices = {"dnssd://dlk-08E206-P1._printer._tcp.local/": Device(),
               "dnssd://foo._printer._tcp.local/": Device()}
    from dbus.glib import DBusGMainLoop
    DBusGMainLoop (set_as_default=True)

    class Test:
        def __init__ (self, loop, devices):
            self._loop = loop
            self._devices = devices

        def run (self):
            r = DNSSDHostNamesResolver (self._devices)
            r.resolve (reply_handler=self.reply)
            return False

        def reply (self, *args):
            print args
            self._loop.quit ()

    from gi.repository import GObject
    from gi.repository import GLib
    loop = GObject.MainLoop ()
    set_debugging (True)
    GLib.idle_add (Test (loop, devices).run)
    loop.run ()

#!/usr/bin/env python

## system-config-printer

## Copyright (C) 2008 Red Hat, Inc.
## Copyright (C) 2008 Tim Waugh <twaugh@redhat.com>

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

import dbus
import xml.etree.ElementTree
from dbus.mainloop.glib import DBusGMainLoop
DBusGMainLoop (set_as_default=True)

class PackageKit:
    def __init__ (self):
        bus = dbus.SessionBus ()
        obj = bus.get_object ("org.freedesktop.PackageKit",
                              "/org/freedesktop/PackageKit")

        # Find out which API is required.
        num_args = -1
        introsp = dbus.Interface (obj, "org.freedesktop.DBus.Introspectable")
        api = introsp.Introspect ()
        top = xml.etree.ElementTree.XML (api)
        for interface in top.findall ("interface"):
            if interface.attrib.get ("name") != "org.freedesktop.PackageKit":
                continue

            for method in interface.findall ("method"):
                if method.attrib.get ("name") != "InstallPackageName":
                    continue

                num_args = len (method.findall ("arg"))
                break

        if num_args == -1:
            raise RuntimeError, "Introspection failed for PackageKit"

        self.proxy = dbus.Interface (obj, "org.freedesktop.PackageKit")
        self.num_args = num_args

    def InstallPackageName (self, xid, timestamp, name):
        proxy = self.proxy
        if self.num_args == 3:
            return proxy.InstallPackageName (xid, timestamp, name,
                                             reply_handler=self.reply_handler,
                                             error_handler=self.error_handler)
        else:
            # Old PackageKit interface
            return proxy.InstallPackageName (name,
                                             reply_handler=self.reply_handler,
                                             error_handler=self.error_handler)

    def reply_handler (self, *args):
        pass

    def error_handler (self, *args):
        pass

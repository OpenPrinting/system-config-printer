#!/usr/bin/python3

## system-config-printer

## Copyright (C) 2008, 2009, 2014 Red Hat, Inc.
## Copyright (C) 2008, 2009 Tim Waugh <twaugh@redhat.com>

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

import os
import dbus
import dbus.glib
from gi.repository import GLib
from debug import *

class PackageKit:
    DBUS_NAME="org.freedesktop.PackageKit"
    DBUS_PATH="/org/freedesktop/PackageKit"
    DBUS_IFACE="org.freedesktop.PackageKit.Modify"

    def __init__ (self):
        try:
            bus = dbus.SessionBus ()
            remote_object = bus.get_object(self.DBUS_NAME, self.DBUS_PATH)
            iface = dbus.Interface(remote_object, self.DBUS_IFACE)
        except dbus.exceptions.DBusException:
            # System bus not running.
            iface = None
        self.iface = iface

    def InstallPackageName (self, xid, timestamp, name):
        try:
            if self.iface is not None:
                self.iface.InstallPackageNames(xid, [name],
                                           "show-progress,show-finished,show-warning",
                                           timeout = 999999)
        except dbus.exceptions.DBusException:
            pass

    def InstallProvideFile (self, xid, timestamp, filename):
        try:
            if self.iface is not None:
                self.iface.InstallProvideFiles(xid, [filename],
                                               "show-progress,show-finished,show-warning",
                                               timeout = 999999)
        except dbus.exceptions.DBusException:
            pass

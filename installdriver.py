#!/usr/bin/env python

## system-config-printer

## Copyright (C) 2010 Red Hat, Inc.
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

import dbus
import dbus.glib
import dbus.service

class PrinterDriversInstaller(dbus.service.Object):
    DBUS_PATH  = "/com/redhat/PrinterDriversInstaller"
    DBUS_IFACE = "com.redhat.PrinterDriversInstaller"
    DBUS_OBJ   = "com.redhat.PrinterDriversInstaller"

    def __init__ (self, bus):
        self.bus = bus
        bus_name = dbus.service.BusName (self.DBUS_OBJ, bus=bus)
        dbus.service.Object.__init__ (self, bus_name, self.DBUS_PATH)

    @dbus.service.method(DBUS_IFACE,
                         in_signature="sss",
                         async_callbacks=("reply_handler",
                                          "error_handler"))
    def InstallDrivers (self, mfg, mdl, cmd,
                       reply_handler, error_handler):
        bus = dbus.SessionBus ()
        obj = bus.get_object ("org.freedesktop.PackageKit",
                              "/org/freedesktop/PackageKit")
        proxy = dbus.Interface (obj, "org.freedesktop.PackageKit.Modify")
        proxy.InstallPrinterDrivers (0, ["MFG:%s;MDL:%s;" % (mfg, mdl)],
                                     "hide-finished",
                                     reply_handler=reply_handler,
                                     error_handler=error_handler)

if __name__ == "__main__":
    bus = dbus.SessionBus ()
    import sys
    if len (sys.argv) < 2 or sys.argv[1] == "--client":
        # Client
        obj = bus.get_object (PrinterDriversInstaller.DBUS_OBJ,
                              PrinterDriversInstaller.DBUS_PATH)
        proxy = dbus.Interface (obj, PrinterDriversInstaller.DBUS_IFACE)
        print proxy.InstallDriver ("MFG", "MDL", "CMD")
    else:
        # Server
        import gtk
        PrinterDriversInstaller (bus)
        gtk.main ()

#!/usr/bin/env python

## system-config-printer

## Copyright (C) 2010 Red Hat, Inc.
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
## Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.

import dbus.service
import gobject
import sys

from debug import *
import newprinter

CONFIG_BUS='org.fedoraproject.Config.Printing'
CONFIG_PATH='/org/fedoraproject/Config/Printing'
CONFIG_IFACE='org.fedoraproject.Config.Printing'
CONFIG_NEWPRINTERDIALOG_IFACE=CONFIG_IFACE + ".NewPrinterDialog"

class KillTimer:
    def __init__ (self, timeout=30, killfunc=None):
        self._timeout = timeout
        self._killfunc = killfunc
        self._holds = 0
        self._add_timeout ()

    def _add_timeout (self):
        self._timer = gobject.timeout_add_seconds (self._timeout, self._kill)

    def _kill (self):
        debugprint ("Timeout (%ds), exiting" % self._timeout)
        if self._killfunc:
            self._killfunc ()
        else:
            sys.exit (0)

    def add_hold (self):
        if self._holds == 0:
            debugprint ("Kill timer stopped")
            gobject.source_remove (self._timer)

        self._holds += 1

    def remove_hold (self):
        self._holds -= 1
        if self._holds == 0:
            debugprint ("Kill timer started")
            self._add_timeout ()

    def alive (self):
        if self._holds == 0:
            gobject.source_remove (self._timer)
            self._add_timeout ()

class ConfigPrintingNewPrinterDialog(dbus.service.Object):
    def __init__ (self, bus, path, killtimer):
        bus_name = dbus.service.BusName (CONFIG_BUS, bus=bus)
        dbus.service.Object.__init__ (self, bus_name, path)
        self.dialog = newprinter.NewPrinterGUI()
        self.dialog.connect ('dialog-canceled', self.on_dialog_canceled)
        self.dialog.connect ('printer-added', self.on_printer_added)
        debugprint ("+%s" % self)

    def __del__ (self):
        debugprint ("-%s" % self)

    @dbus.service.method(dbus_interface=CONFIG_NEWPRINTERDIALOG_IFACE,
                         in_signature='uss', out_signature='')
    def NewPrinterFromDevice(self, xid, device_uri, device_id):
        killtimer.add_hold ()
        self.dialog.init ('printer_with_uri', device_uri=device_uri,
                          devid=device_id, xid=xid)

    @dbus.service.signal(dbus_interface=CONFIG_NEWPRINTERDIALOG_IFACE,
                         signature='')
    def DialogCanceled(self):
        pass

    @dbus.service.signal(dbus_interface=CONFIG_NEWPRINTERDIALOG_IFACE,
                         signature='s')
    def PrinterAdded(self, name):
        pass

    def on_dialog_canceled(self, obj):
        killtimer.remove_hold ()
        self.DialogCanceled ()

    def on_printer_added(self, obj, name):
        killtimer.remove_hold ()
        self.PrinterAdded (name)

class ConfigPrinting(dbus.service.Object):
    def __init__ (self, killtimer):
        self._killtimer = killtimer
        self.bus = dbus.SessionBus ()
        bus_name = dbus.service.BusName (CONFIG_BUS, bus=self.bus)
        dbus.service.Object.__init__ (self, bus_name, CONFIG_PATH)
        self.pathn = 0

    @dbus.service.method(dbus_interface=CONFIG_IFACE,
                         in_signature='', out_signature='s')
    def NewPrinterDialog(self):
        self.pathn += 1
        path = "%s/NewPrinterDialog%s" % (CONFIG_PATH, self.pathn)
        ConfigPrintingNewPrinterDialog (self.bus, path,
                                        killtimer=self._killtimer)
        self._killtimer.alive ()
        return path

def _client_demo ():
    # Client demo
    if len (sys.argv) > 2:
        device_uri = sys.argv[2]
        device_id = ''
        if (len (sys.argv) > 4 and
            sys.argv[3] == '--devid'):
            device_id = sys.argv[4]
    else:
        print "Device URI required"
        return

    import gtk
    bus = dbus.SessionBus ()
    obj = bus.get_object (CONFIG_BUS, CONFIG_PATH)
    iface = dbus.Interface (obj, CONFIG_IFACE)
    path = iface.NewPrinterDialog ()
    debugprint (path)

    obj = bus.get_object (CONFIG_BUS, path)
    iface = dbus.Interface (obj, CONFIG_NEWPRINTERDIALOG_IFACE)
    loop = gobject.MainLoop ()
    def on_canceled(path=None):
        print "%s: Dialog canceled" % path
        loop.quit ()

    def on_added(name, path=None):
        print "%s: Printer '%s' added" % (path, name)
        loop.quit ()

    w = gtk.Window ()
    w.show_now ()
    iface.connect_to_signal ("DialogCanceled", on_canceled,
                             path_keyword="path")
    iface.connect_to_signal ("PrinterAdded", on_added,
                             path_keyword="path")

    iface.NewPrinterFromDevice (w.window.xid, device_uri, device_id)
    loop.run ()

if __name__ == '__main__':
    import ppdippstr
    import locale
    locale.setlocale (locale.LC_ALL, "")
    ppdippstr.init ()
    gobject.threads_init ()
    from dbus.glib import DBusGMainLoop
    DBusGMainLoop (set_as_default=True)

    client_demo = False
    if len (sys.argv) > 1:
        for opt in sys.argv[1:]:
            if opt == "--debug":
                set_debugging (True)
            elif opt == "--client":
                client_demo = True

    if client_demo:
        _client_demo ()
        sys.exit (0)

    debugprint ("Service running...")
    loop = gobject.MainLoop ()
    killtimer = KillTimer (killfunc=loop.quit)
    ConfigPrinting (killtimer=killtimer)
    loop.run ()

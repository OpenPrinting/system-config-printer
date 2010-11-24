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
import asyncconn
import jobviewer
import newprinter
import ppdcache
import printerproperties

CONFIG_BUS='org.fedoraproject.Config.Printing'
CONFIG_PATH='/org/fedoraproject/Config/Printing'
CONFIG_IFACE='org.fedoraproject.Config.Printing'
CONFIG_NEWPRINTERDIALOG_IFACE=CONFIG_IFACE + ".NewPrinterDialog"
CONFIG_PRINTERPROPERTIESDIALOG_IFACE=CONFIG_IFACE + ".PrinterPropertiesDialog"
CONFIG_JOBVIEWER_IFACE=CONFIG_IFACE + ".JobViewer"

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
    def __init__ (self, bus, path, cupsconn, killtimer):
        bus_name = dbus.service.BusName (CONFIG_BUS, bus=bus)
        dbus.service.Object.__init__ (self, bus_name, path)
        self.dialog = newprinter.NewPrinterGUI()
        self.dialog.NewPrinterWindow.set_modal (False)
        self.handles = [self.dialog.connect ('dialog-canceled',
                                             self.on_dialog_canceled),
                        self.dialog.connect ('printer-added',
                                             self.on_printer_added)]
        self._ppdcache = ppdcache.PPDCache ()
        self._cupsconn = cupsconn
        self._killtimer = killtimer
        debugprint ("+%s" % self)

    def __del__ (self):
        debugprint ("-%s" % self)

    @dbus.service.method(dbus_interface=CONFIG_NEWPRINTERDIALOG_IFACE,
                         in_signature='uss', out_signature='')
    def NewPrinterFromDevice(self, xid, device_uri, device_id):
        self._killtimer.add_hold ()
        self.dialog.init ('printer_with_uri', device_uri=device_uri,
                          devid=device_id, xid=xid)

    @dbus.service.method(dbus_interface=CONFIG_NEWPRINTERDIALOG_IFACE,
                         in_signature='uss', out_signature='')
    def ChangePPD(self, xid, name, device_id):
        self._killtimer.add_hold ()
        self.xid = xid
        self.name = name
        self.device_id = device_id
        self._ppdcache.fetch_ppd (name, self._change_ppd_got_ppd)

    def _change_ppd_got_ppd(self, name, ppd, exc):
        # Got PPD; now find device URI.
        self.ppd = ppd
        self._cupsconn.getPrinters (reply_handler=self._change_ppd_with_dev,
                                    error_handler=self._do_change_ppd)

    def _change_ppd_with_dev (self, conn, result):
        self.device_uri = result.get (self.name, {}).get ('device-uri', None)
        self._do_change_ppd (conn)

    def _do_change_ppd(self, conn, exc=None):
        self.dialog.init ('ppd', device_uri=self.device_uri, name=self.name,
                          ppd=self.ppd, devid=self.device_id, xid=self.xid)

    @dbus.service.signal(dbus_interface=CONFIG_NEWPRINTERDIALOG_IFACE,
                         signature='')
    def DialogCanceled(self):
        pass

    @dbus.service.signal(dbus_interface=CONFIG_NEWPRINTERDIALOG_IFACE,
                         signature='s')
    def PrinterAdded(self, name):
        pass

    def on_dialog_canceled(self, obj):
        self._killtimer.remove_hold ()
        self.DialogCanceled ()
        self.remove_handles ()
        self.remove_from_connection ()

    def on_printer_added(self, obj, name):
        self._killtimer.remove_hold ()
        self.PrinterAdded (name)
        self.remove_handles ()
        self.remove_from_connection ()

    def remove_handles (self):
        for handle in self.handles:
            self.dialog.disconnect (handle)

class ConfigPrintingPrinterPropertiesDialog(dbus.service.Object):
    def __init__ (self, bus, path, xid, name, killtimer):
        bus_name = dbus.service.BusName (CONFIG_BUS, bus=bus)
        dbus.service.Object.__init__ (self, bus_name=bus_name, object_path=path)
        self.dialog = printerproperties.PrinterPropertiesDialog ()
        self.dialog.dialog.set_modal (False)
        handle = self.dialog.connect ('dialog-closed', self.on_dialog_closed)
        self.closed_handle = handle
        self.dialog.show (name)
        self.dialog.dialog.set_modal (False)
        self._killtimer = killtimer
        killtimer.add_hold ()

    @dbus.service.method(dbus_interface=CONFIG_PRINTERPROPERTIESDIALOG_IFACE,
                         in_signature='', out_signature='')
    def PrintTestPage (self):
        debugprint ("Printing test page")
        return self.dialog.printTestPage ()

    @dbus.service.signal(dbus_interface=CONFIG_PRINTERPROPERTIESDIALOG_IFACE,
                         signature='')
    def Finished (self):
        pass

    def on_dialog_closed (self, dialog):
        dialog.destroy ()
        self._killtimer.remove_hold ()
        self.Finished ()
        self.dialog.disconnect (self.closed_handle)
        self.remove_from_connection ()

class ConfigPrintingJobApplet(dbus.service.Object):
    def __init__ (self, bus, path, killtimer):
        bus_name = dbus.service.BusName (CONFIG_BUS, bus=bus)
        dbus.service.Object.__init__ (self, bus_name=bus_name, object_path=path)
        self.jobapplet = jobviewer.JobViewer(bus=dbus.SystemBus (),
                                             applet=True, my_jobs=True)
        handle = self.jobapplet.connect ('finished', self.on_jobapplet_finished)
        self.finished_handle = handle
        self._killtimer = killtimer
        self.has_finished = False
        killtimer.add_hold ()
        debugprint ("+%s" % self)

    def __del__ (self):
        debugprint ("-%s" % self)

    @dbus.service.method(dbus_interface=CONFIG_JOBVIEWER_IFACE,
                         in_signature='', out_signature='')
    def Quit(self):
        if not self.has_finished:
            self.jobapplet.cleanup ()

    @dbus.service.signal(dbus_interface=CONFIG_JOBVIEWER_IFACE, signature='')
    def Finished(self):
        pass

    def on_jobapplet_finished (self, jobapplet):
        self.Finished ()
        self._killtimer.remove_hold ()
        self.has_finished = True
        self.jobapplet.disconnect (self.finished_handle)
        self.remove_from_connection ()

class ConfigPrinting(dbus.service.Object):
    def __init__ (self, killtimer):
        self._killtimer = killtimer
        self.bus = dbus.SessionBus ()
        bus_name = dbus.service.BusName (CONFIG_BUS, bus=self.bus)
        dbus.service.Object.__init__ (self, bus_name, CONFIG_PATH)
        self._cupsconn = asyncconn.Connection ()
        self._pathn = 0
        self._jobapplet = None
        self._jobappletpath = None

    def destroy (self):
        self._cupsconn.destroy ()

    @dbus.service.method(dbus_interface=CONFIG_IFACE,
                         in_signature='', out_signature='s')
    def NewPrinterDialog(self):
        self._pathn += 1
        path = "%s/NewPrinterDialog%s" % (CONFIG_PATH, self._pathn)
        ConfigPrintingNewPrinterDialog (self.bus, path,
                                        self._cupsconn,
                                        killtimer=self._killtimer)
        self._killtimer.alive ()
        return path

    @dbus.service.method(dbus_interface=CONFIG_IFACE,
                         in_signature='us', out_signature='s')
    def PrinterPropertiesDialog(self, xid, name):
        self._pathn += 1
        path = "%s/PrinterPropertiesDialog%s" % (CONFIG_PATH, self._pathn)
        ConfigPrintingPrinterPropertiesDialog (self.bus, path, xid, name,
                                               killtimer=self._killtimer)
        self._killtimer.alive ()
        return path

    @dbus.service.method(dbus_interface=CONFIG_IFACE,
                         in_signature='', out_signature='s')
    def JobApplet(self):
       if self._jobapplet == None or self._jobapplet.has_finished:
            self._pathn += 1
            path = "%s/JobApplet%s" % (CONFIG_PATH, self._pathn)
            self._jobapplet = ConfigPrintingJobApplet (self.bus, path,
                                                       self._killtimer)
            self._jobappletpath = path

       return self._jobappletpath

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
    cp = ConfigPrinting (killtimer=killtimer)
    loop.run ()
    cp.destroy ()

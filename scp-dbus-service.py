#!/usr/bin/python3

## system-config-printer

## Copyright (C) 2010, 2011, 2012, 2013, 2014 Red Hat, Inc.
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

import gi
import dbus.service
from gi.repository import GObject
from gi.repository import GLib
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
import sys

from debug import *
import asyncconn
import config
import cups
import cupshelpers
import dnssdresolve
import jobviewer
import killtimer
import newprinter
import PhysicalDevice
import ppdcache
import printerproperties

cups.require ("1.9.52")

CONFIG_BUS='org.fedoraproject.Config.Printing'
CONFIG_PATH='/org/fedoraproject/Config/Printing'
CONFIG_IFACE='org.fedoraproject.Config.Printing'
CONFIG_NEWPRINTERDIALOG_IFACE=CONFIG_IFACE + ".NewPrinterDialog"
CONFIG_PRINTERPROPERTIESDIALOG_IFACE=CONFIG_IFACE + ".PrinterPropertiesDialog"
CONFIG_JOBVIEWER_IFACE=CONFIG_IFACE + ".JobViewer"

g_ppds = None
g_killtimer = None

#set program name
GLib.set_prgname("system-config-printer")

class FetchedPPDs(GObject.GObject):
    __gsignals__ = {
        'ready': (GObject.SIGNAL_RUN_LAST, None, ()),
        'error': (GObject.SIGNAL_RUN_LAST, None,
                  (GObject.TYPE_PYOBJECT,))
        }

    def __init__ (self, cupsconn, language):
        GObject.GObject.__init__ (self)
        self._cupsconn = cupsconn
        self._language = language
        self._ppds = None

    def is_ready (self):
        return self._ppds is not None

    def get_ppds (self):
        return self._ppds

    def run (self):
        debugprint ("FetchPPDs: running")
        self._ppds = None
        self._cupsconn.getPPDs2 (reply_handler=self._cups_getppds_reply,
                                 error_handler=self._cups_error)

    def _cups_error (self, conn, exc):
        debugprint ("FetchPPDs: error: %s" % repr (exc))
        self.emit ('error', exc)

    def _cups_getppds_reply (self, conn, result):
        debugprint ("FetchPPDs: success")
        self._ppds = cupshelpers.ppds.PPDs (result, language=self._language)
        self.emit ('ready')

class GetBestDriversRequest:
    def __init__ (self, device_id, device_make_and_model, device_uri,
                  cupsconn, language, reply_handler, error_handler):
        self.device_id = device_id
        self.device_make_and_model = device_make_and_model
        self.device_uri = device_uri
        self.cupsconn = cupsconn
        self.language = language
        self.reply_handler = reply_handler
        self.error_handler = error_handler
        self._signals = []
        self.installed_files = []
        self.download_tried = False
        debugprint ("+%s" % self)

        g_killtimer.add_hold ()
        global g_ppds
        if g_ppds is None:
            debugprint ("GetBestDrivers request: need to fetch PPDs")
            g_ppds = FetchedPPDs (self.cupsconn, self.language)
            self._signals.append (g_ppds.connect ('ready', self._ppds_ready))
            self._signals.append (g_ppds.connect ('error', self._ppds_error))
            g_ppds.run ()
        else:
            if g_ppds.is_ready ():
                debugprint ("GetBestDrivers request: PPDs already fetched")
                self._ppds_ready (g_ppds)
            else:
                debugprint ("GetBestDrivers request: waiting for PPDs")
                self._signals.append (g_ppds.connect ('ready',
                                                      self._ppds_ready))
                self._signals.append (g_ppds.connect ('error',
                                                      self._ppds_error))

    def __del__ (self):
        debugprint ("-%s" % self)

    def _disconnect_signals (self):
        for s in self._signals:
            g_ppds.disconnect (s)

    def _ppds_error (self, fetchedppds, exc):
        self._disconnect_signals ()
        self.error_handler (exc)

    def _ppds_ready (self, fetchedppds):
        if not fetchedppds.is_ready ():
            # PPDs being reloaded. Wait for next 'ready' signal.
            return

        self._disconnect_signals ()
        ppds = fetchedppds.get_ppds ()

        try:
            if self.device_id:
                id_dict = cupshelpers.parseDeviceID (self.device_id)
            else:
                id_dict = {}
                (mfg,
                 mdl) = cupshelpers.ppds.ppdMakeModelSplit (self.device_make_and_model)
                id_dict["MFG"] = mfg
                id_dict["MDL"] = mdl
                id_dict["DES"] = ""
                id_dict["CMD"] = []
                self.device_id = "MFG:%s;MDL:%s;" % (mfg, mdl)

            fit = ppds.getPPDNamesFromDeviceID (id_dict["MFG"],
                                                id_dict["MDL"],
                                                id_dict["DES"],
                                                id_dict["CMD"],
                                                self.device_uri,
                                                self.device_make_and_model)

            ppdnamelist = ppds.orderPPDNamesByPreference (fit.keys (),
                                                          self.installed_files,
                                                          devid=id_dict,
                                                          fit=fit)
            ppdname = ppdnamelist[0]
            status = fit[ppdname]

            try:
                if status != "exact" and not self.download_tried:
                    self.download_tried = True
                    self.dialog = newprinter.NewPrinterGUI()
                    self.dialog.NewPrinterWindow.set_modal (False)
                    self.handles = \
                                   [self.dialog.connect ('dialog-canceled',
                                                         self.on_dialog_canceled),
                                    self.dialog.connect ('driver-download-checked',
                                                         self.on_driver_download_checked)]

                    self.reply_if_fail = [(x, fit[x]) for x in ppdnamelist]
                    if not self.dialog.init ('download_driver',
                                             devid=self.device_id):
                        try:
                            g_killtimer.remove_hold ()
                        finally:
                            e = RuntimeError ("Failed to launch dialog")
                            self.error_handler (e)

                    return
            except:
                # Ignore driver download if packages needed for the GUI are not
                # installed or if no windows can be opened
                pass

            g_killtimer.remove_hold ()
            self.reply_handler ([(x, fit[x]) for x in ppdnamelist])
        except Exception as e:
            try:
                g_killtimer.remove_hold ()
            except:
                pass

            self.error_handler (e)

    def _destroy_dialog (self):
        for handle in self.handles:
            self.dialog.disconnect (handle)

        self.dialog.destroy ()
        del self.dialog

    def on_driver_download_checked(self, obj, installed_files):
        if len (installed_files) > 0:
            debugprint ("GetBestDrivers request: Re-fetch PPDs after driver download")
            self._signals.append (g_ppds.connect ('ready', self._ppds_ready))
            self._signals.append (g_ppds.connect ('error', self._ppds_error))
            g_ppds.run ()
            return

        g_killtimer.remove_hold ()
        self._destroy_dialog ()
        self.reply_handler (self.reply_if_fail)

    def on_dialog_canceled(self, obj):
        g_killtimer.remove_hold ()
        self._destroy_dialog ()
        self.reply_handler (self.reply_if_fail)

class GroupPhysicalDevicesRequest:
    def __init__ (self, devices, reply_handler, error_handler):
        self.devices = devices
        self.reply_handler = reply_handler
        self.error_handler = error_handler
        debugprint ("+%s" % self)

        try:
            g_killtimer.add_hold ()
            need_resolving = {}
            self.deviceobjs = {}
            for device_uri, device_dict in self.devices.items ():
                deviceobj = cupshelpers.Device (device_uri, **device_dict)
                self.deviceobjs[device_uri] = deviceobj
                if device_uri.startswith ("dnssd://"):
                    need_resolving[device_uri] = deviceobj

            if len (need_resolving) > 0:
                resolver = dnssdresolve.DNSSDHostNamesResolver (need_resolving)
                resolver.resolve (reply_handler=self._group)
            else:
                self._group ()
        except Exception as e:
            g_killtimer.remove_hold ()
            self.error_handler (e)

    def __del__ (self):
        debugprint ("-%s" % self)

    def _group (self, resolved_devices=None):
        # We can ignore resolved_devices because the actual objects
        # (in self.devices) have been modified.
        try:
            self.physdevs = []
            for device_uri, deviceobj in self.deviceobjs.items ():
                newphysicaldevice = PhysicalDevice.PhysicalDevice (deviceobj)
                matched = False
                try:
                    i = self.physdevs.index (newphysicaldevice)
                    self.physdevs[i].add_device (deviceobj)
                except ValueError:
                    self.physdevs.append (newphysicaldevice)

            uris_by_phys = []
            for physdev in self.physdevs:
                uris_by_phys.append ([x.uri for x in physdev.get_devices ()])

            g_killtimer.remove_hold ()
            self.reply_handler (uris_by_phys)
        except Exception as e:
            g_killtimer.remove_hold ()
            self.error_handler (e)

class ConfigPrintingNewPrinterDialog(dbus.service.Object):
    def __init__ (self, bus, path, cupsconn):
        bus_name = dbus.service.BusName (CONFIG_BUS, bus=bus)
        dbus.service.Object.__init__ (self, bus_name, path)
        self.dialog = newprinter.NewPrinterGUI()
        self.dialog.NewPrinterWindow.set_modal (False)
        self.handles = [self.dialog.connect ('dialog-canceled',
                                             self.on_dialog_canceled),
                        self.dialog.connect ('printer-added',
                                             self.on_printer_added),
                        self.dialog.connect ('printer-modified',
                                             self.on_printer_modified),
                        self.dialog.connect ('driver-download-checked',
                                             self.on_driver_download_checked)]
        self._ppdcache = ppdcache.PPDCache ()
        self._cupsconn = cupsconn
        debugprint ("+%s" % self)

    def __del__ (self):
        self.dialog.destroy ()
        debugprint ("-%s" % self)

    @dbus.service.method(dbus_interface=CONFIG_NEWPRINTERDIALOG_IFACE,
                         in_signature='uss', out_signature='')
    def NewPrinterFromDevice(self, xid, device_uri, device_id):
        g_killtimer.add_hold ()
        self.dialog.init ('printer_with_uri', device_uri=device_uri,
                          devid=device_id, xid=xid)

    @dbus.service.method(dbus_interface=CONFIG_NEWPRINTERDIALOG_IFACE,
                         in_signature='us', out_signature='')
    def DownloadDriverForDeviceID(self, xid, device_id):
        g_killtimer.add_hold ()
        self.dialog.init ('download_driver', devid=device_id, xid=xid)

    @dbus.service.method(dbus_interface=CONFIG_NEWPRINTERDIALOG_IFACE,
                         in_signature='uss', out_signature='')
    def ChangePPD(self, xid, name, device_id):
        g_killtimer.add_hold ()
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

    @dbus.service.signal(dbus_interface=CONFIG_NEWPRINTERDIALOG_IFACE,
                         signature='sb')
    def PrinterModified(self, name, ppd_has_changed):
        pass

    @dbus.service.signal(dbus_interface=CONFIG_NEWPRINTERDIALOG_IFACE,
                         signature='a(s)')
    def DriverDownloadChecked(self, installed_files):
        pass

    def on_dialog_canceled(self, obj):
        debugprint ("%s: dialog canceled" % self)
        g_killtimer.remove_hold ()
        self.DialogCanceled ()
        self.remove_handles ()
        self.remove_from_connection ()

    def on_printer_added(self, obj, name):
        debugprint ("%s: printer added" % self)
        g_killtimer.remove_hold ()
        self.PrinterAdded (name)
        self.remove_handles ()
        self.remove_from_connection ()

    def on_printer_modified(self, obj, name, ppd_has_changed):
        debugprint ("%s: printer modified" % self)
        g_killtimer.remove_hold ()
        self.PrinterModifed (name, ppd_has_changed)
        self.remove_handles ()
        self.remove_from_connection ()

    def on_driver_download_checked(self, obj, installed_files):
        debugprint ("%s: driver download checked" % self)
        g_killtimer.remove_hold ()
        self.DriverDownloadChecked (installed_files)
        self.remove_handles ()
        self.remove_from_connection ()

    def remove_handles (self):
        for handle in self.handles:
            self.dialog.disconnect (handle)

class ConfigPrintingPrinterPropertiesDialog(dbus.service.Object):
    def __init__ (self, bus, path, xid, name):
        bus_name = dbus.service.BusName (CONFIG_BUS, bus=bus)
        dbus.service.Object.__init__ (self, bus_name=bus_name, object_path=path)
        self.dialog = printerproperties.PrinterPropertiesDialog ()
        self.dialog.dialog.set_modal (False)
        handle = self.dialog.connect ('dialog-closed', self.on_dialog_closed)
        self.closed_handle = handle
        self.dialog.show (name)
        self.dialog.dialog.set_modal (False)
        g_killtimer.add_hold ()

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
        g_killtimer.remove_hold ()
        self.Finished ()
        self.dialog.disconnect (self.closed_handle)
        self.remove_from_connection ()

class ConfigPrintingJobApplet(dbus.service.Object):
    def __init__ (self, bus, path):
        bus_name = dbus.service.BusName (CONFIG_BUS, bus=bus)
        dbus.service.Object.__init__ (self, bus_name=bus_name, object_path=path)
        Gdk.threads_enter ()
        self.jobapplet = jobviewer.JobViewer(bus=dbus.SystemBus (),
                                             applet=True, my_jobs=True)
        self.jobapplet.set_process_pending (False)
        Gdk.threads_leave ()
        handle = self.jobapplet.connect ('finished', self.on_jobapplet_finished)
        self.finished_handle = handle
        self.has_finished = False
        g_killtimer.add_hold ()
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
        g_killtimer.remove_hold ()
        self.has_finished = True
        self.jobapplet.disconnect (self.finished_handle)
        self.remove_from_connection ()

class ConfigPrinting(dbus.service.Object):
    def __init__ (self):
        self.bus = dbus.SessionBus ()
        bus_name = dbus.service.BusName (CONFIG_BUS, bus=self.bus)
        dbus.service.Object.__init__ (self, bus_name, CONFIG_PATH)
        self._cupsconn = asyncconn.Connection ()
        self._pathn = 0
        self._jobapplet = None
        self._jobappletpath = None
        self._ppds = None
        self._language = locale.getlocale (locale.LC_MESSAGES)[0]

    def destroy (self):
        self._cupsconn.destroy ()

    @dbus.service.method(dbus_interface=CONFIG_IFACE,
                         in_signature='', out_signature='s')
    def NewPrinterDialog(self):
        self._pathn += 1
        path = "%s/NewPrinterDialog/%s" % (CONFIG_PATH, self._pathn)
        ConfigPrintingNewPrinterDialog (self.bus, path,
                                        self._cupsconn)
        g_killtimer.alive ()
        return path

    @dbus.service.method(dbus_interface=CONFIG_IFACE,
                         in_signature='us', out_signature='s')
    def PrinterPropertiesDialog(self, xid, name):
        self._pathn += 1
        path = "%s/PrinterPropertiesDialog/%s" % (CONFIG_PATH, self._pathn)
        ConfigPrintingPrinterPropertiesDialog (self.bus, path, xid, name)
        g_killtimer.alive ()
        return path

    @dbus.service.method(dbus_interface=CONFIG_IFACE,
                         in_signature='', out_signature='s')
    def JobApplet(self):
       if self._jobapplet is None or self._jobapplet.has_finished:
            self._pathn += 1
            path = "%s/JobApplet/%s" % (CONFIG_PATH, self._pathn)
            self._jobapplet = ConfigPrintingJobApplet (self.bus, path)
            self._jobappletpath = path

       return self._jobappletpath

    @dbus.service.method(dbus_interface=CONFIG_IFACE,
                         in_signature='sss', out_signature='a(ss)',
                         async_callbacks=('reply_handler', 'error_handler'))
    def GetBestDrivers(self, device_id, device_make_and_model, device_uri,
                   reply_handler, error_handler):
        GetBestDriversRequest (device_id, device_make_and_model, device_uri,
                               self._cupsconn, self._language[0],
                               reply_handler, error_handler)

    @dbus.service.method(dbus_interface=CONFIG_IFACE,
                         in_signature='s', out_signature='as')
    def MissingExecutables(self, ppd_filename):
        ppd = cups.PPD (ppd_filename)
        return cupshelpers.missingExecutables (ppd)

    @dbus.service.method(dbus_interface=CONFIG_IFACE,
                         in_signature='a{sa{ss}}', out_signature='aas',
                         async_callbacks=('reply_handler', 'error_handler'))
    def GroupPhysicalDevices(self, devices, reply_handler, error_handler):
        GroupPhysicalDevicesRequest (devices, reply_handler, error_handler)

def _client_demo ():
    # Client demo
    if len (sys.argv) > 2:
        device_uri = sys.argv[2]
        device_id = ''
        if (len (sys.argv) > 4 and
            sys.argv[3] == '--devid'):
            device_id = sys.argv[4]
    else:
        print ("Device URI required")
        return

    from gi.repository import Gtk
    bus = dbus.SessionBus ()
    obj = bus.get_object (CONFIG_BUS, CONFIG_PATH)
    iface = dbus.Interface (obj, CONFIG_IFACE)
    path = iface.NewPrinterDialog ()
    debugprint (path)

    obj = bus.get_object (CONFIG_BUS, path)
    iface = dbus.Interface (obj, CONFIG_NEWPRINTERDIALOG_IFACE)
    loop = GObject.MainLoop ()
    def on_canceled(path=None):
        print ("%s: Dialog canceled" % path)
        loop.quit ()

    def on_added(name, path=None):
        print ("%s: Printer '%s' added" % (path, name))
        loop.quit ()

    iface.connect_to_signal ("DialogCanceled", on_canceled,
                             path_keyword="path")
    iface.connect_to_signal ("PrinterAdded", on_added,
                             path_keyword="path")

    iface.NewPrinterFromDevice (0, device_uri, device_id)
    loop.run ()

if __name__ == '__main__':
    import ppdippstr
    import config
    import gettext
    gettext.install(domain=config.PACKAGE, localedir=config.localedir)

    import locale
    try:
        locale.setlocale (locale.LC_ALL, "")
    except:
        pass

    ppdippstr.init ()
    Gdk.threads_init ()
    from dbus.glib import DBusGMainLoop
    DBusGMainLoop (set_as_default=True)

    client_demo = False
    if len (sys.argv) > 1:
        for opt in sys.argv[1:]:
            if opt == "--debug":
                set_debugging (True)
                cupshelpers.set_debugprint_fn (debugprint)
            elif opt == "--client":
                client_demo = True

    if client_demo:
        _client_demo ()
        sys.exit (0)

    debugprint ("Service running...")
    g_killtimer = killtimer.KillTimer (killfunc=Gtk.main_quit)
    cp = ConfigPrinting ()
    Gdk.threads_enter ()
    Gtk.main ()
    Gdk.threads_leave ()
    cp.destroy ()

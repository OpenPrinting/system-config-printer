#!/usr/bin/python3

## system-config-printer

## Copyright (C) 2010, 2011, 2012, 2013, 2014 Red Hat, Inc.
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
## Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import threading

import dbus
from gi.repository import GObject, GLib
from gi.repository import Gtk

import cups
import cupshelpers
cups.require ("1.9.52")

import asyncconn
from debug import debugprint
import config
import gettext
gettext.install(domain=config.PACKAGE, localedir=config.localedir)

class PPDsLoader(GObject.GObject):
    """
    1. If PackageKit support is available, and this is a local server,
    try to use PackageKit to install relevant drivers.  We do this
    because we can only make the right choice about the "best" driver
    when the full complement of drivers is there to choose from.

    2. Fetch the list of available drivers from CUPS.

    3. If Jockey is available, and there is no appropriate driver
    available, try to use Jockey to install one.

    4. If Jockey was able to install one, fetch the list of available
    drivers again.
    """

    __gsignals__ = {
        'finished': (GObject.SignalFlags.RUN_LAST, None, ())
        }

    def __init__ (self, device_id=None, parent=None, device_uri=None,
                  host=None, encryption=None, language=None,
                  device_make_and_model=None):
        GObject.GObject.__init__ (self)
        debugprint ("+%s" % self)
        self._device_id = device_id
        self._device_uri = device_uri
        self._device_make_and_model = device_make_and_model
        self._parent = parent
        self._host = host
        self._encryption = encryption
        self._language = language

        self._installed_files = []
        self._conn = None
        self._ppds = None
        self._exc = None

        self._ppdsmatch_result = None
        self._jockey_queried = False
        self._jockey_has_answered = False
        self._destroyed = False
        self._local_cups = (self._host is None or
                            self._host == "localhost" or
                            self._host[0] == '/')
        try:
            self._bus = dbus.SessionBus ()
        except:
            debugprint ("Failed to get session bus")
            self._bus = None


    def run (self):

        if self._device_id:
            self._devid_dict = cupshelpers.parseDeviceID (self._device_id)

        if (self._local_cups and
            self._device_id and
            self._devid_dict["MFG"] and
            self._devid_dict["MDL"] and
            self._bus):
            self._gpk_device_id = "MFG:%s;MDL:%s;" % (self._devid_dict["MFG"],
                                                      self._devid_dict["MDL"])
            self._query_packagekit ()
        else:
            self._query_cups ()

    def __del__ (self):
        debugprint ("-%s" % self)

    def destroy (self):
        debugprint ("DESTROY: %s" % self)
        self._destroyed = True

        self._parent = None

        if self._conn:
            self._conn.destroy ()
            self._conn = None

    def get_installed_files (self):
        return self._installed_files

    def get_ppds (self):
        return self._ppds

    def get_ppdsmatch_result (self):
        return self._ppdsmatch_result

    def get_error (self):
        debugprint ("%s: stored error is %s" % (self, repr (self._exc)))
        return self._exc

    def _query_cups (self):
        debugprint ("Asking CUPS for PPDs")
        if (not self._conn):
            c = asyncconn.Connection (host=self._host,
                                      encryption=self._encryption,
                                      reply_handler=self._cups_connect_reply,
                                      error_handler=self._cups_error)
            self._conn = c
        else:
            self._cups_connect_reply(self._conn, None)

    def _cups_connect_reply (self, conn, UNUSED):
        if self._destroyed:
            return

        conn._begin_operation (_("fetching PPDs"))
        conn.getPPDs2 (reply_handler=self._cups_reply,
                       error_handler=self._cups_error)

    def _cups_reply (self, conn, result):
        if self._destroyed:
            return

        ppds = cupshelpers.ppds.PPDs (result, language=self._language)
        self._ppds = ppds
        self._need_requery_cups = False
        if self._device_id:
            fit = ppds.\
                getPPDNamesFromDeviceID (self._devid_dict["MFG"],
                                         self._devid_dict["MDL"],
                                         self._devid_dict["DES"],
                                         self._devid_dict["CMD"],
                                         self._device_uri,
                                         self._device_make_and_model)

            ppdnamelist = ppds.\
                orderPPDNamesByPreference (list(fit.keys ()),
                                           self._installed_files,
                                           devid=self._devid_dict,
                                           fit=fit)
            self._ppdsmatch_result = (fit, ppdnamelist)

            ppdname = ppdnamelist[0]
            if (self._bus and
                not fit[ppdname].startswith ("exact") and
                not self._jockey_queried and
                self._devid_dict["MFG"] and
                self._devid_dict["MDL"] and
                self._local_cups):
                # Try to install packages using jockey if
                # - there's no appropriate driver (PPD) locally available
                # - we are configuring local CUPS server
                self._jockey_queried = True
                self._query_jockey ()
                return

        conn.destroy ()
        self._conn = None

        self.emit ('finished')

    def _cups_error (self, conn, exc):
        if self._destroyed:
            return

        conn.destroy ()
        self._conn = None
        self._ppds = None
        self._exc = exc

        self.emit ('finished')

    def _query_packagekit (self):
        debugprint ("Asking PackageKit to install drivers")

        gpk_device_id = self._gpk_device_id

        def worker():
            bus = None
            success = False
            try:
                bus = dbus.SessionBus(private=True)
                obj = bus.get_object("org.freedesktop.PackageKit",
                                     "/org/freedesktop/PackageKit")
                proxy = dbus.Interface(obj, "org.freedesktop.PackageKit.Modify")
                resources = [gpk_device_id]
                interaction = "hide-finished"
                debugprint("Calling InstallPrinterDrivers in worker")
                proxy.InstallPrinterDrivers(dbus.UInt32(0), resources, interaction, timeout=3600)
                success = True
            except Exception as e:
                debugprint("Got PackageKit error in worker: %s" % repr(e))
            finally:
                if bus is not None:
                    bus.close()
                GLib.idle_add(self._on_packagekit_done, success)

        threading.Thread(target=worker, daemon=True).start()

    def _on_packagekit_done(self, success):
        if self._destroyed:
            return False

        if not success:
            debugprint("PackageKit installation failed or returned error")
        else:
            debugprint("Got PackageKit reply")
            self._need_requery_cups = True

        self._query_cups()
        return False

    def _query_jockey (self):
        debugprint ("Asking Jockey to install drivers")
        try:
            obj = self._bus.get_object ("com.ubuntu.DeviceDriver", "/GUI")
            jockey = dbus.Interface (obj, "com.ubuntu.DeviceDriver")
            r = jockey.search_driver ("printer_deviceid:%s" % self._device_id,
                                      reply_handler=self._jockey_reply,
                                      error_handler=self._jockey_error,
                                      timeout=3600)
        except Exception as e:
            self._jockey_error (e)

    def _jockey_reply (self, conn, result):
        if self._destroyed:
            return

        debugprint ("Got Jockey result: %s" % repr (result))
        self._jockey_has_answered = True
        try:
            self._installed_files = result[1]
        except:
            self._installed_files = []
        self._query_cups ()

    def _jockey_error (self, exc):
        if self._destroyed:
            return

        debugprint ("Got Jockey error: %s" % repr (exc))
        if self._need_requery_cups:
            self._query_cups ()
        else:
            if self._conn is not None:
                self._conn.destroy ()
                self._conn = None


            self.emit ('finished')

if __name__ == "__main__":
    class Foo:
        def __init__ (self):
            w = Gtk.Window ()
            b = Gtk.Button.new_with_label ("Go")
            w.add (b)
            b.connect ('clicked', self.go)
            w.connect ('delete-event', Gtk.main_quit)
            w.show_all ()
            self._window = w

        def go (self, button):
            loader = PPDsLoader (device_id="MFG:MFG;MDL:MDL;",
                                 parent=self._window)
            loader.connect ('finished', self.ppds_loaded)
            loader.run ()

        def ppds_loaded (self, ppdsloader):
            self._window.destroy ()
            Gtk.main_quit ()
            exc = ppdsloader.get_error ()
            print(exc)
            ppds = ppdsloader.get_ppds ()
            if ppds is not None:
                print(len (ppds))

            ppdsloader.destroy ()

    from debug import set_debugging
    set_debugging (True)
    Foo ()
    Gtk.main ()

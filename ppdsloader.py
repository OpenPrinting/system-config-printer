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
import gtk
import cupshelpers

import asyncconn
from debug import debugprint

_ = lambda x: x
def set_gettext_function (fn):
    global _
    _ = fn

class PPDsLoader:
    def __init__ (self, callback, device_id=None, device_uri=None, parent=None,
                  host=None, encryption=None):
        debugprint ("+%s" % self)
        self._callback = callback
        self._device_id = device_id
        self._device_uri = device_uri
        self._parent = parent
        self._host = host
        self._encryption = encryption

        self._installed_files = []
        self._conn = None
        self._ppds = None

        try:
            self._bus = dbus.SessionBus ()
        except:
            debugprint ("Failed to get session bus")
            self._bus = None

        fmt = _("Searching")
        self._dialog = gtk.MessageDialog (parent=parent,
                                          flags=gtk.DIALOG_MODAL |
                                          gtk.DIALOG_DESTROY_WITH_PARENT,
                                          type=gtk.MESSAGE_INFO,
                                          buttons=gtk.BUTTONS_CANCEL,
                                          message_format=fmt)

        self._dialog.format_secondary_text (_("Searching for drivers"))

        self._dialog.connect ("response", self._dialog_response)

        self._dialog.show_all ()
        self._query_cups (True)

    def __del__ (self):
        debugprint ("-%s" % self)

    def destroy (self):
        debugprint ("DESTROY: %s" % self)
        if self._dialog:
            self._dialog.destroy ()
            self._dialog = None

        self._callback = None
        self._parent = None

    def get_installed_files (self):
        return self._installed_files

    def get_ppds (self):
        return self._ppds

    def _dialog_response (self, dialog, response):
        self._call_callback (None)

    def _query_packagekit (self):
        debugprint ("Asking PackageKit to install drivers")
        try:
            xid = self._parent.window.xid
        except:
            xid = 0

        try:
            obj = self._bus.get_object ("org.freedesktop.PackageKit",
                                        "/org/freedesktop/PackageKit")
            proxy = dbus.Interface (obj, "org.freedesktop.PackageKit.Modify")
            proxy.InstallPrinterDrivers (xid, [self._device_id],
                                         "hide-finished",
                                         reply_handler=self._packagekit_reply,
                                         error_handler=self._packagekit_error,
                                         timeout=3600)
        except Exception, e:
            debugprint ("Failed to talk to PackageKit: %s" % e)
            if self._dialog:
                self._dialog.show_all ()
                self._query_jockey ()

    def _packagekit_reply (self):
        debugprint ("Got PackageKit reply")
        if self._dialog:
            self._dialog.show_all ()
            self._query_jockey ()

    def _packagekit_error (self, exc):
        debugprint ("Got PackageKit error: %s" % exc)
        if self._dialog:
            self._dialog.show_all ()
            self._query_jockey ()

    def _query_jockey (self):
        debugprint ("Asking Jockey to install drivers")
        try:
            obj = self._bus.get_object ("com.ubuntu.DeviceDriver", "/GUI")
            jockey = dbus.Interface (obj, "com.ubuntu.DeviceDriver")
            r = jockey.search_driver ("printer_deviceid:%s" % self._device_id,
                                      reply_handler=self._jockey_reply,
                                      error_handler=self._jockey_error,
                                      timeout=3600)
        except Exception, e:
            self._jockey_error (e)

    def _jockey_reply (self, conn, result):
        debugprint ("Got Jockey result: %s" % repr (result))
        try:
            self._installed_files = result[1]
        except:
            self._installed_files = ()
        self._query_cups ()

    def _jockey_error (self, exc):
        debugprint ("Got Jockey error: %s" % exc)
        self._query_cups ()

    def _query_cups (self, local=False):
        debugprint ("Asking CUPS for PPDs")
        if (local):
            c = asyncconn.Connection (host=self._host,
                                      encryption=self._encryption,
                                      reply_handler=self._cups_connect_reply_local,
                                      error_handler=self._cups_error)
        else:
            c = asyncconn.Connection (host=self._host,
                                      encryption=self._encryption,
                                      reply_handler=self._cups_connect_reply,
                                      error_handler=self._cups_error)
        self._conn = c

    def _cups_connect_reply_local (self, conn, UNUSED):
        if conn != self._conn:
            conn.destroy ()
            return

        conn._begin_operation (_("fetching PPDs"))
        conn.getPPDs (reply_handler=self._cups_reply_local,
                      error_handler=self._cups_error)

    def _cups_connect_reply (self, conn, UNUSED):
        if conn != self._conn:
            conn.destroy ()
            return

        conn._begin_operation (_("fetching PPDs"))
        conn.getPPDs (reply_handler=self._cups_reply,
                      error_handler=self._cups_error)

    def _cups_reply_local (self, conn, result):
        if conn != self._conn:
            conn.destroy ()
            return

        conn.destroy ()
        self._conn = None
        self._ppds = result
        ppds = cupshelpers.ppds.PPDs (result)
        if self._device_id and self._bus:
            devid_dict = cupshelpers.parseDeviceID (self._device_id)
            (status, ppdname) = ppds.\
                getPPDNameFromDeviceID (devid_dict["MFG"],
                                        devid_dict["MDL"],
                                        devid_dict["DES"],
                                        devid_dict["CMD"],
                                        self._device_uri,
                                        ())
            if status != ppds.STATUS_SUCCESS:
                self._query_packagekit ()
            else:
                self._call_callback (None)
        else:
            self._call_callback (None)

    def _cups_reply (self, conn, result):
        if conn != self._conn:
            conn.destroy ()
            return

        conn.destroy ()
        self._conn = None
        self._ppds = result
        self._call_callback (None)

    def _cups_error (self, conn, exc):
        if conn != self._conn:
            conn.destroy ()
            return

        conn.destroy ()
        self._conn = None
        self._ppds = None
        self._call_callback (exc)

    def _call_callback (self, exc):
        if self._callback:
            self._callback (self, exc)


if __name__ == "__main__":
    class Foo:
        def __init__ (self):
            w = gtk.Window ()
            b = gtk.Button ("Go")
            w.add (b)
            b.connect ('clicked', self.go)
            w.connect ('delete-event', gtk.main_quit)
            w.show_all ()
            self._window = w

        def go (self, button):
            PPDsLoader (self.ppds_loaded, device_id="MFG:MFG;MDL:MDL;",
                        parent=self._window)

        def ppds_loaded (self, ppdsloader, exc):
            self._window.destroy ()
            gtk.main_quit ()
            print exc
            ppds = ppdsloader.get_ppds ()
            if ppds != None:
                print len (ppds)

            ppdsloader.destroy ()

    import gobject
    from debug import set_debugging
    set_debugging (True)
    gobject.threads_init ()
    Foo ()
    gtk.main ()

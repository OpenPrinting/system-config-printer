#!/usr/bin/python

## Copyright (C) 2007, 2008, 2009, 2010, 2012, 2013 Red Hat, Inc.
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
## Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import cups
import dbus
try:
    from gi.repository import Gdk
    from gi.repository import Gtk
except:
    pass
import os
import sys
import tempfile
import xml.etree.ElementTree

import asyncipp
from debug import *
import debug

CUPS_PK_NAME  = 'org.opensuse.CupsPkHelper.Mechanism'
CUPS_PK_PATH  = '/'
CUPS_PK_IFACE = 'org.opensuse.CupsPkHelper.Mechanism'
CUPS_PK_NEED_AUTH = 'org.opensuse.CupsPkHelper.Mechanism.NotPrivileged'

######
###### A polkit-1 based asynchronous CupsPkHelper interface made to
###### look just like a normal IPPAuthConnection class.  For method
###### calls that have no equivalent in the CupsPkHelper API, IPP
###### authentication is used over a CUPS connection in a separate
###### thread.
######

_DevicesGet_uses_new_api = None

###
### A class to handle an asynchronous method call.
###
class _PK1AsyncMethodCall:
    def __init__ (self, bus, conn, pk_method_name, pk_args,
                  reply_handler, error_handler, unpack_fn,
                  fallback_fn, args, kwds):
        self._bus = bus
        self._conn = conn
        self._pk_method_name = pk_method_name
        self._pk_args = pk_args
        self._client_reply_handler = reply_handler
        self._client_error_handler = error_handler
        self._unpack_fn = unpack_fn
        self._fallback_fn = fallback_fn
        self._fallback_args = args
        self._fallback_kwds = kwds
        self._destroyed = False
        debugprint ("+_PK1AsyncMethodCall: %s" % self)

    def __del__ (self):
        debug.debugprint ("-_PK1AsyncMethodCall: %s" % self)

    def call (self):
        object = self._bus.get_object(CUPS_PK_NAME, CUPS_PK_PATH)
        proxy = dbus.Interface (object, CUPS_PK_IFACE)
        pk_method = proxy.get_dbus_method (self._pk_method_name)

        try:
            debugprint ("%s: calling %s" % (self, pk_method))
            pk_method (*self._pk_args,
                        reply_handler=self._pk_reply_handler,
                        error_handler=self._pk_error_handler,
                        timeout=3600)
        except TypeError as e:
            debugprint ("Type error in PK call: %s" % repr (e))
            self.call_fallback_fn ()

    def _destroy (self):
        debugprint ("DESTROY: %s" % self)
        self._destroyed = True
        del self._bus
        del self._conn
        del self._pk_method_name
        del self._pk_args
        del self._client_reply_handler
        del self._client_error_handler
        del self._unpack_fn
        del self._fallback_fn
        del self._fallback_args
        del self._fallback_kwds

    def _pk_reply_handler (self, error, *args):
        if self._destroyed:
            return

        if str (error) == '':
            try:
                Gdk.threads_enter ()
            except:
                pass
            debugprint ("%s: no error, calling reply handler %s" %
                        (self, self._client_reply_handler))
            self._client_reply_handler (self._conn, self._unpack_fn (*args))
            try:
                Gdk.threads_leave ()
            except:
                pass
            self._destroy ()
            return

        debugprint ("PolicyKit method failed with: %s" % repr (error))
        self.call_fallback_fn ()

    def _pk_error_handler (self, exc):
        if self._destroyed:
            return

        if exc.get_dbus_name () == CUPS_PK_NEED_AUTH:
            exc = cups.IPPError (cups.IPP_NOT_AUTHORIZED, 'pkcancel')
            try:
                Gdk.threads_enter ()
            except:
                pass
            debugprint ("%s: no auth, calling error handler %s" %
                        (self, self._client_error_handler))
            self._client_error_handler (self._conn, exc)
            try:
                Gdk.threads_leave ()
            except:
                pass
            self._destroy ()
            return

        debugprint ("PolicyKit call to %s did not work: %s" %
                    (self._pk_method_name, repr (exc)))
        self.call_fallback_fn ()

    def call_fallback_fn (self):
        # Make the 'connection' parameter consistent with PK callbacks.
        self._fallback_kwds["reply_handler"] = self._ipp_reply_handler
        self._fallback_kwds["error_handler"] = self._ipp_error_handler
        debugprint ("%s: calling %s" % (self, self._fallback_fn))
        self._fallback_fn (*self._fallback_args, **self._fallback_kwds)

    def _ipp_reply_handler (self, conn, *args):
        if self._destroyed:
            return

        debugprint ("%s: chaining up to %s" % (self,
                                               self._client_reply_handler))
        self._client_reply_handler (self._conn, *args)
        self._destroy ()

    def _ipp_error_handler (self, conn, *args):
        if self._destroyed:
            return

        debugprint ("%s: chaining up to %s" % (self,
                                               self._client_error_handler))
        self._client_error_handler (self._conn, *args)
        self._destroy ()

###
### A class for handling FileGet when a temporary file is needed.
###
class _WriteToTmpFile:
    def __init__ (self, kwds, reply_handler, error_handler):
        self._reply_handler = reply_handler
        self._error_handler = error_handler

        # Create the temporary file in /tmp to ensure that
        # cups-pk-helper-mechanism is able to write to it.
        (tmpfd, tmpfname) = tempfile.mkstemp (dir="/tmp")
        os.close (tmpfd)
        self._filename = tmpfname
        debugprint ("Created tempfile %s" % tmpfname)
        self._kwds = kwds

    def __del__ (self):
        try:
            os.unlink (self._filename)
            debug.debugprint ("Removed tempfile %s" % self._filename)
        except:
            debug.debugprint ("No tempfile to remove")

    def get_filename (self):
        return self._filename

    def reply_handler (self, conn, none):
        tmpfd = os.open (self._filename, os.O_RDONLY)
        tmpfile = os.fdopen (tmpfd, 'r')
        if self._kwds.has_key ("fd"):
            fd = self._kwds["fd"]
            os.lseek (fd, 0, os.SEEK_SET)
            line = tmpfile.readline ()
            while line != '':
                os.write (fd, line)
                line = tempfile.readline ()
        else:
            file_object = self._kwds["file"]
            file_object.seek (0)
            line = tmpfile.readline ()
            while line != '':
                file_object.write (line)
                line = tmpfile.readline ()

        tmpfile.close ()
        self._reply_handler (conn, none)

    def error_handler (self, conn, exc):
        self._error_handler (conn, exc)

###
### The user-visible class.
###
class PK1Connection:
    def __init__(self, reply_handler=None, error_handler=None,
                 host=None, port=None, encryption=None, parent=None):
        self._conn = asyncipp.IPPAuthConnection  (reply_handler=reply_handler,
                                                  error_handler=error_handler,
                                                  host=host, port=port,
                                                  encryption=encryption,
                                                  parent=parent)

        try:
            self._system_bus = dbus.SystemBus()
        except (dbus.exceptions.DBusException, AttributeError):
            # No system D-Bus.
            self._system_bus = None

        global _DevicesGet_uses_new_api
        if _DevicesGet_uses_new_api == None and self._system_bus:
            try:
                obj = self._system_bus.get_object(CUPS_PK_NAME, CUPS_PK_PATH)
                proxy = dbus.Interface (obj, dbus.INTROSPECTABLE_IFACE)
                api = proxy.Introspect ()
                top = xml.etree.ElementTree.XML (api)
                for interface in top.findall ("interface"):
                    if interface.attrib.get ("name") != CUPS_PK_IFACE:
                        continue

                    for method in interface.findall ("method"):
                        if method.attrib.get ("name") != "DevicesGet":
                            continue

                        num_args = 0
                        for arg in method.findall ("arg"):
                            direction = arg.attrib.get ("direction")
                            if direction != "in":
                                continue

                            num_args += 1

                        _DevicesGet_uses_new_api = num_args == 4
                        debugprint ("DevicesGet new API: %s" % (num_args == 4))
                        break

                    break

            except Exception as e:
                debugprint ("Exception assessing DevicesGet API: %s" % repr (e))

        methodtype = type (self._conn.getPrinters)
        bindings = []
        for fname in dir (self._conn):
            if fname.startswith ('_'):
                continue
            fn = getattr (self._conn, fname)
            if type (fn) != methodtype:
                continue
            if not hasattr (self, fname):
                setattr (self, fname, self._make_binding (fn))
                bindings.append (fname)

        self._bindings = bindings
        debugprint ("+%s" % self)

    def __del__ (self):
        debug.debugprint ("-%s" % self)

    def _make_binding (self, fn):
        def binding (*args, **kwds):
            op = _PK1AsyncMethodCall (None, self, None, None,
                                      kwds.get ("reply_handler"),
                                      kwds.get ("error_handler"),
                                      None, fn, args, kwds)
            op.call_fallback_fn ()

        return binding

    def destroy (self):
        debugprint ("DESTROY: %s" % self)
        self._conn.destroy ()

        for binding in self._bindings:
            delattr (self, binding)

    def _coerce (self, typ, val):
        return typ (val)

    def _args_kwds_to_tuple (self, types, params, args, kwds):
        """Collapse args and kwds into a single tuple."""
        leftover_kwds = kwds.copy ()
        reply_handler = leftover_kwds.get ("reply_handler")
        error_handler = leftover_kwds.get ("error_handler")
        if leftover_kwds.has_key ("reply_handler"):
            del leftover_kwds["reply_handler"]
        if leftover_kwds.has_key ("error_handler"):
            del leftover_kwds["error_handler"]
        if leftover_kwds.has_key ("auth_handler"):
            del leftover_kwds["auth_handler"]

        result = [True, reply_handler, error_handler, ()]
        if self._system_bus == None:
            return result

        tup = []
        argindex = 0
        for arg in args:
            try:
                val = self._coerce (types[argindex], arg)
            except IndexError:
                # More args than types.
                kw, default = params[argindex]
                if default != arg:
                    return result

                # It's OK, this is the default value anyway and can be
                # ignored.  Skip to the next one.
                argindex += 1
                continue
            except TypeError as e:
                debugprint ("Error converting %s to %s" %
                            (repr (arg), types[argindex]))
                return result

            tup.append (val)
            argindex += 1

        for kw, default in params[argindex:]:
            if leftover_kwds.has_key (kw):
                try:
                    val = self._coerce (types[argindex], leftover_kwds[kw])
                except TypeError as e:
                    debugprint ("Error converting %s to %s" %
                                (repr (leftover_kwds[kw]), types[argindex]))
                    return result

                tup.append (val)
                del leftover_kwds[kw]
            else:
                tup.append (default)

            argindex += 1

        if leftover_kwds:
            debugprint ("Leftover keywords: %s" % repr (leftover_kwds.keys ()))
            return result

        result[0] = False
        result[3] = tuple (tup)
        debugprint ("Converted %s/%s to %s" % (args, kwds, tuple (tup)))
        return result

    def _call_with_pk (self, use_pycups, pk_method_name, pk_args,
                       reply_handler, error_handler, unpack_fn,
                       fallback_fn, args, kwds):
        asyncmethodcall = _PK1AsyncMethodCall (self._system_bus, self,
                                               pk_method_name, pk_args,
                                               reply_handler,
                                               error_handler,
                                               unpack_fn, fallback_fn,
                                               args, kwds)

        if not use_pycups:
            try:
                debugprint ("Calling PK method %s" % pk_method_name)
                asyncmethodcall.call ()
            except dbus.DBusException as e:
                debugprint ("D-Bus call failed: %s" % repr (e))
                use_pycups = True

        if use_pycups:
            return asyncmethodcall.call_fallback_fn ()

    def _nothing_to_unpack (self):
        return None

    def getDevices (self, *args, **kwds):
        global _DevicesGet_uses_new_api
        if _DevicesGet_uses_new_api:
            (use_pycups, reply_handler, error_handler,
             tup) = self._args_kwds_to_tuple ([int, int, list, list],
                                              [("timeout", 0),
                                               ("limit", 0),
                                               ("include_schemes", []),
                                               ("exclude_schemes", [])],
                                              args, kwds)
        else:
            (use_pycups, reply_handler, error_handler,
             tup) = self._args_kwds_to_tuple ([int, list, list],
                                              [("limit", 0),
                                               ("include_schemes", []),
                                               ("exclude_schemes", [])],
                                              args, kwds)

            if not use_pycups:
                # Special handling for include_schemes/exclude_schemes.
                # Convert from list to ","-separated string.
                newtup = list (tup)
                for paramindex in [1, 2]:
                    if len (newtup[paramindex]) > 0:
                        newtup[paramindex] = reduce (lambda x, y:
                                                         x + "," + y,
                                                     newtup[paramindex])
                    else:
                        newtup[paramindex] = ""

                tup = tuple (newtup)

        self._call_with_pk (use_pycups,
                            'DevicesGet', tup, reply_handler, error_handler,
                            self._unpack_getDevices_reply,
                            self._conn.getDevices, args, kwds)

    def _unpack_getDevices_reply (self, dbusdict):
        result_str = dict()
        for key, value in dbusdict.iteritems ():
            if type (key) == dbus.String:
                result_str[unicode (key)] = unicode (value)
            else:
                result_str[key] = value

        # cups-pk-helper returns all devices in one dictionary.
        # Keys of different devices are distinguished by ':n' postfix.

        devices = dict()
        n = 0
        affix = ':' + str (n)
        device_keys = [x for x in result_str.keys () if x.endswith (affix)]
        while len (device_keys) > 0:
            device_uri = None
            device_dict = dict()
            for keywithaffix in device_keys:
                key = keywithaffix[:len (keywithaffix) - len (affix)]
                if key != 'device-uri':
                    device_dict[key] = result_str[keywithaffix]
                else:
                    device_uri = result_str[keywithaffix]

            if device_uri != None:
                devices[device_uri] = device_dict

            n += 1
            affix = ':' + str (n)
            device_keys = [x for x in result_str.keys () if x.endswith (affix)]

        return devices

    def cancelJob (self, *args, **kwds):
        (use_pycups, reply_handler, error_handler,
         tup) = self._args_kwds_to_tuple ([int, bool],
                                          [(None, None),
                                           (None, False)], # purge_job
                                          args, kwds)

        self._call_with_pk (use_pycups,
                            'JobCancelPurge', tup, reply_handler, error_handler,
                            self._nothing_to_unpack,
                            self._conn.cancelJob, args, kwds)

    def setJobHoldUntil (self, *args, **kwds):
        (use_pycups, reply_handler, error_handler,
         tup) = self._args_kwds_to_tuple ([int, str],
                                          [(None, None),
                                           (None, None)],
                                          args, kwds)

        self._call_with_pk (use_pycups,
                            'JobSetHoldUntil', tup, reply_handler,
                            error_handler, self._nothing_to_unpack,
                            self._conn.setJobHoldUntil, args, kwds)

    def restartJob (self, *args, **kwds):
        (use_pycups, reply_handler, error_handler,
         tup) = self._args_kwds_to_tuple ([int],
                                          [(None, None)],
                                          args, kwds)

        self._call_with_pk (use_pycups,
                            'JobRestart', tup, reply_handler,
                            error_handler, self._nothing_to_unpack,
                            self._conn.restartJob, args, kwds)

    def getFile (self, *args, **kwds):
        (use_pycups, reply_handler, error_handler,
         tup) = self._args_kwds_to_tuple ([str, str],
                                          [("resource", None),
                                           ("filename", None)],
                                          args, kwds)

        # getFile(resource, filename=None, fd=-1, file=None) -> None
        if use_pycups:
            if ((len (args) == 0 and kwds.has_key ('resource')) or
                (len (args) == 1)):
                can_use_tempfile = True
                for each in kwds.keys ():
                    if each not in ['resource', 'fd', 'file',
                                    'reply_handler', 'error_handler']:
                        can_use_tempfile = False
                        break

                if can_use_tempfile:
                    # We can still use PackageKit for this.
                    if len (args) == 0:
                        resource = kwds["resource"]
                    else:
                        resource = args[0]

                    wrapper = _WriteToTmpFile (kwds,
                                               reply_handler,
                                               error_handler)
                    self._call_with_pk (False,
                                        'FileGet',
                                        (resource, wrapper.get_filename ()),
                                        wrapper.reply_handler,
                                        wrapper.error_handler,
                                        self._nothing_to_unpack,
                                        self._conn.getFile, args, kwds)
                    return

        self._call_with_pk (use_pycups,
                            'FileGet', tup, reply_handler,
                            error_handler, self._nothing_to_unpack,
                            self._conn.getFile, args, kwds)

    ## etc
    ## Still to implement:
    ## putFile
    ## addPrinter
    ## setPrinterDevice
    ## setPrinterInfo
    ## setPrinterLocation
    ## setPrinterShared
    ## setPrinterJobSheets
    ## setPrinterErrorPolicy
    ## setPrinterOpPolicy
    ## setPrinterUsersAllowed
    ## setPrinterUsersDenied
    ## addPrinterOptionDefault
    ## deletePrinterOptionDefault
    ## deletePrinter
    ## addPrinterToClass
    ## deletePrinterFromClass
    ## deleteClass
    ## setDefault
    ## enablePrinter
    ## disablePrinter
    ## acceptJobs
    ## rejectJobs
    ## adminGetServerSettings
    ## adminSetServerSettings
    ## ...

if __name__ == '__main__':
    from gi.repository import GObject
    GObject.threads_init ()
    from debug import set_debugging
    set_debugging (True)
    class UI:
        def __init__ (self):
            w = Gtk.Window ()
            v = Gtk.VBox ()
            w.add (v)
            b = Gtk.Button ("Go")
            v.pack_start (b, False, False, 0)
            b.connect ("clicked", self.button_clicked)
            b = Gtk.Button ("Fetch")
            v.pack_start (b, False, False, 0)
            b.connect ("clicked", self.fetch_clicked)
            b.set_sensitive (False)
            self.fetch_button = b
            b = Gtk.Button ("Cancel job")
            v.pack_start (b, False, False, 0)
            b.connect ("clicked", self.cancel_clicked)
            b.set_sensitive (False)
            self.cancel_button = b
            b = Gtk.Button ("Get file")
            v.pack_start (b, False, False, 0)
            b.connect ("clicked", self.get_file_clicked)
            b.set_sensitive (False)
            self.get_file_button = b
            b = Gtk.Button ("Something harmless")
            v.pack_start (b, False, False, 0)
            b.connect ("clicked", self.harmless_clicked)
            b.set_sensitive (False)
            self.harmless_button = b
            w.connect ("destroy", self.destroy)
            w.show_all ()
            self.conn = None
            debugprint ("+%s" % self)

        def __del__ (self):
            debug.debugprint ("-%s" % self)

        def destroy (self, window):
            debugprint ("DESTROY: %s" % self)
            try:
                self.conn.destroy ()
                del self.conn
            except AttributeError:
                pass

            Gtk.main_quit ()

        def button_clicked (self, button):
            if self.conn:
                self.conn.destroy ()

            self.conn = PK1Connection (reply_handler=self.connected,
                                       error_handler=self.connection_error)

        def connected (self, conn, result):
            print "Connected"
            self.fetch_button.set_sensitive (True)
            self.cancel_button.set_sensitive (True)
            self.get_file_button.set_sensitive (True)
            self.harmless_button.set_sensitive (True)

        def connection_error (self, conn, error):
            print "Failed to connect"
            raise error

        def fetch_clicked (self, button):
            print ("fetch devices...")
            self.conn.getDevices (reply_handler=self.got_devices,
                                  error_handler=self.get_devices_error)

        def got_devices (self, conn, devices):
            if conn != self.conn:
                print "Ignoring stale reply"
                return

            print "got devices: %s" % devices

        def get_devices_error (self, conn, exc):
            if conn != self.conn:
                print "Ignoring stale error"
                return

            print "devices error: %s" % repr (exc)

        def cancel_clicked (self, button):
            print "Cancel job..."
            self.conn.cancelJob (1,
                                 reply_handler=self.job_canceled,
                                 error_handler=self.cancel_job_error)

        def job_canceled (self, conn, none):
            if conn != self.conn:
                print "Ignoring stale reply for %s" % conn
                return

            print "Job canceled"

        def cancel_job_error (self, conn, exc):
            if conn != self.conn:
                print "Ignoring stale error for %s" % conn
                return

            print "cancel error: %s" % repr (exc)

        def get_file_clicked (self, button):
            self.my_file = file ("cupsd.conf", "w")
            self.conn.getFile ("/admin/conf/cupsd.conf", file=self.my_file,
                               reply_handler=self.got_file,
                               error_handler=self.get_file_error)

        def got_file (self, conn, none):
            if conn != self.conn:
                print "Ignoring stale reply for %s" % conn
                return

            print "Got file"

        def get_file_error (self, conn, exc):
            if conn != self.conn:
                print "Ignoring stale error"
                return

            print "get file error: %s" % repr (exc)

        def harmless_clicked (self, button):
            self.conn.getJobs (reply_handler=self.got_jobs,
                               error_handler=self.get_jobs_error)

        def got_jobs (self, conn, result):
            if conn != self.conn:
                print "Ignoring stale reply from %s" % repr (conn)
                return
            print result

        def get_jobs_error (self, exc):
            print "get jobs error: %s" % repr (exc)

    UI ()
    from dbus.mainloop.glib import DBusGMainLoop
    DBusGMainLoop (set_as_default=True)
    Gtk.main ()

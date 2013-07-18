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

import asyncconn
import cups
from gi.repository import GLib
from gi.repository import Gdk
from gi.repository import Gtk
import os
import tempfile
from debug import *

cups.require ("1.9.50")

class PPDCache:
    def __init__ (self, host=None, port=None, encryption=None):
        self._cups = None
        self._exc = None
        self._cache = dict()
        self._modtimes = dict()
        self._host = host
        self._port = port
        self._encryption = encryption
        self._queued = list()
        self._connecting = False
        debugprint ("+%s" % self)

    def __del__ (self):
        debugprint ("-%s" % self)
        if self._cups:
            self._cups.destroy ()

    def fetch_ppd (self, name, callback, check_uptodate=True):
        if check_uptodate and self._modtimes.has_key (name):
            # We have getPPD3 so we can check whether the PPD is up to
            # date.
            debugprint ("%s: check if %s is up to date" % (self, name))
            self._cups.getPPD3 (name,
                                modtime=self._modtimes[name],
                                reply_handler=lambda c, r:
                                    self._got_ppd3 (c, name, r, callback),
                                error_handler=lambda c, r:
                                    self._got_ppd3 (c, name, r, callback))
            return

        try:
            f = self._cache[name]
        except RuntimeError as e:
            self._schedule_callback (callback, name, None, e)
            return
        except KeyError:
            if not self._cups:
                self._queued.append ((name, callback))
                if not self._connecting:
                    self._connect ()

                return

            debugprint ("%s: fetch PPD for %s" % (self, name))
            self._cups.getPPD3 (name,
                                reply_handler=lambda c, r:
                                    self._got_ppd3 (c, name, r, callback),
                                error_handler=lambda c, r:
                                    self._got_ppd3 (c, name, r, callback))
            return

        # Copy from our file object to a new temporary file, create a
        # PPD object from it, then remove the file.  This way we don't
        # leave temporary files around even though we are caching...
        f.seek (0)
        (tmpfd, tmpfname) = tempfile.mkstemp ()
        tmpf = file (tmpfname, "w")
        tmpf.writelines (f.readlines ())
        del tmpf
        os.close (tmpfd)
        try:
            ppd = cups.PPD (tmpfname)
            os.unlink (tmpfname)
            self._schedule_callback (callback, name, ppd, None)
        except Exception as e:
            os.unlink (tmpfname)
            self._schedule_callback (callback, name, None, e)

    def _connect (self, callback=None):
        self._connecting = True
        asyncconn.Connection (host=self._host, port=self._port,
                              encryption=self._encryption,
                              reply_handler=self._connected,
                              error_handler=self._connected)

    def _got_ppd (self, connection, name, result, callback):
        if isinstance (result, Exception):
            self._schedule_callback (callback, name, result, None)
        else:
            # Store an open file object, then remove the actual file.
            # This way we don't leave temporary files around.
            self._cache[name] = file (result)
            debugprint ("%s: caching %s (fd %d)" % (self, result,
                                                    self._cache[name].fileno()))
            os.unlink (result)
            self.fetch_ppd (name, callback)

    def _got_ppd3 (self, connection, name, result, callback):
        (status, modtime, filename) = result
        if status in [cups.HTTP_OK, cups.HTTP_NOT_MODIFIED]:
            if status == cups.HTTP_NOT_MODIFIED:
                # The file is no newer than the one we already have.

                # CUPS before 1.5.3 created a temporary file in error
                # in this situation (STR #4018) so remove that.
                try:
                    os.unlink (filename)
                except OSError:
                    pass

            elif status == cups.HTTP_OK:
                # Our version of the file was older.  Cache the new version.

                # Store an open file object, then remove the actual
                # file.  This way we don't leave temporary files
                # around.
                try:
                    self._cache[name] = file (filename)
                    debugprint ("%s: caching %s (fd %d) "
                                "(%s) - %s" % (self, filename,
                                               self._cache[name].fileno (),
                                               modtime, status))
                    os.unlink (filename)
                    self._modtimes[name] = modtime
                except IOError:
                    # File disappeared?
                    debugprint ("%s: file %s disappeared? Unable to cache it"
                                % (self, filename))

            # Now fetch it from our own cache.
            self.fetch_ppd (name, callback, check_uptodate=False)
        else:
            self._schedule_callback (callback, name,
                                     None, cups.HTTPError (status))

    def _connected (self, connection, exc):
        self._connecting = False
        if isinstance (exc, Exception):
            self._cups = None
            self._exc = exc
        else:
            self._cups = connection

        queued = self._queued
        self._queued = list()
        for name, callback in queued:
            self.fetch_ppd (name, callback)

    def _schedule_callback (self, callback, name, result, exc):
        def cb_func (callback, name, result, exc):
            Gdk.threads_enter ()
            callback (name, result, exc)
            Gdk.threads_leave ()
            return False

        GLib.idle_add (cb_func, callback, name, result, exc)

if __name__ == "__main__":
    import sys
    from debug import *
    from gi.repository import GObject
    set_debugging (True)
    GObject.threads_init ()
    Gdk.threads_init ()
    loop = GObject.MainLoop ()

    def signal (name, result, exc):
        debugprint ("**** %s" % name)
        debugprint (repr (result))
        debugprint (repr (exc))

    c = cups.Connection ()
    printers = c.getPrinters ()
    del c

    cache = PPDCache ()
    p = None
    for p in printers:
        cache.fetch_ppd (p, signal)

    if p:
        GLib.timeout_add_seconds (1, cache.fetch_ppd, p, signal)
        GLib.timeout_add_seconds (5, loop.quit)
    loop.run ()

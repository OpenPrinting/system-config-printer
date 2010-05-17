#!/usr/bin/env python

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

import asyncconn
import cups
import gobject
import os

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
        self._connect ()
        debugprint ("+%s" % self)

    def __del__ (self):
        debugprint ("-%s" % self)
        if self._cups:
            self._cups.destroy ()

        for f in self._cache.values ():
            try:
                debugprint ("PPD cache: removing %s" % f)
                os.unlink (f)
            except OSError:
                pass

    def fetch_ppd (self, name, callback, check_uptodate=True):
        if check_uptodate and self._modtimes.has_key (name):
            # We have getPPD3 so we can check whether the PPD is up to
            # date.
            debugprint ("PPD cache: check if %s is up to date" % name)
            self._cups.getPPD3 (name,
                                modtime=self._modtimes[name],
                                reply_handler=lambda c, r:
                                    self._got_ppd3 (c, name, r, callback),
                                error_handler=lambda c, r:
                                    self._got_ppd3 (c, name, r, callback))
            return

        try:
            ppd = cups.PPD (self._cache[name])
        except RuntimeError, e:
            callback (name, None, e)
            return
        except KeyError:
            if not self._cups:
                self._queued.append ((name, callback))
                if not self._connecting:
                    self._connect ()

                return

            debugprint ("PPD cache: fetch PPD for %s" % name)
            try:
                self._cups.getPPD3 (name,
                                    reply_handler=lambda c, r:
                                        self._got_ppd3 (c, name, r, callback),
                                    error_handler=lambda c, r:
                                        self._got_ppd3 (c, name, r, callback))
            except AttributeError:
                # getPPD3 requires pycups >= 1.9.50
                self._cups.getPPD (name,
                                   reply_handler=lambda c, r:
                                       self._got_ppd (c, name, r, callback),
                                   error_handler=lambda c, r:
                                       self._got_ppd (c, name, r, callback))

            return

        callback (name, ppd, None)

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
            debugprint ("PPD cache: caching %s" % result)
            self._cache[name] = result
            self.fetch_ppd (name, callback)

    def _got_ppd3 (self, connection, name, result, callback):
        (status, modtime, filename) = result
        if status in [cups.HTTP_OK, cups.HTTP_NOT_MODIFIED]:
            if status == cups.HTTP_OK:
                debugprint ("PPD cache: caching %s (%s) - %s" % (filename,
                                                                 modtime,
                                                                 status))
                self._cache[name] = filename
                self._modtimes[name] = modtime

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
            callback (name, result, exc)
            return False

        gobject.idle_add (cb_func)

if __name__ == "__main__":
    import sys
    from debug import *
    set_debugging (True)
    gobject.threads_init ()
    loop = gobject.MainLoop ()

    def signal (name, result, exc):
        debugprint ("**** %s" % name)
        debugprint (result)
        debugprint (exc)

    c = cups.Connection ()
    printers = c.getPrinters ()
    del c

    cache = PPDCache ()
    p = None
    for p in printers:
        cache.fetch_ppd (p, signal)

    if p:
        gobject.timeout_add_seconds (1, cache.fetch_ppd, p, signal)
    loop.run ()

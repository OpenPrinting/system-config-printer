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

class PPDCache(gobject.GObject):

    __gsignals__ = {
        'ppd-ready': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE,
                      [gobject.TYPE_STRING, gobject.TYPE_PYOBJECT]),
        'ppd-error': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE,
                      [gobject.TYPE_STRING, gobject.TYPE_PYOBJECT])
        }

    def __init__ (self, host=None, port=None, encryption=None):
        gobject.GObject.__init__ (self)
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

    def fetch_ppd (self, name, check_uptodate=True):
        if check_uptodate and self._modtimes.has_key (name):
            # We have getPPD3 so we can check whether the PPD is up to
            # date.
            debugprint ("PPD cache: check if %s is up to date" % name)
            self._cups.getPPD3 (name,
                                modtime=self._modtimes[name],
                                reply_handler=lambda c, r:
                                    self._got_ppd3 (c, name, r),
                                error_handler=lambda c, r:
                                    self._got_ppd3 (c, name, r))
            return

        try:
            self.emit ('ppd-ready', name, cups.PPD (self._cache[name]))
        except RuntimeError, e:
            self.emit ('ppd-error', name, e)
        except KeyError:
            if not self._cups:
                self._queued.append (name)
                if self._connecting:
                    return

                exc = self._exc
                self._connect ()
                if not exc:
                    exc = RuntimeError

                self.emit ('ppd-error', name, exc)
                return

            debugprint ("PPD cache: fetch PPD for %s" % name)
            try:
                self._cups.getPPD3 (name,
                                    reply_handler=lambda c, r:
                                        self._got_ppd3 (c, name, r),
                                    error_handler=lambda c, r:
                                        self._got_ppd3 (c, name, r))
            except AttributeError:
                # getPPD3 requires pycups >= 1.9.50
                self._cups.getPPD (name,
                                   reply_handler=lambda c, r:
                                       self._got_ppd (c, name, r),
                                   error_handler=lambda c, r:
                                       self._got_ppd (c, name, r))

    def _connect (self):
        self._connecting = True
        asyncconn.Connection (host=self._host, port=self._port,
                              encryption=self._encryption,
                              reply_handler=self._connected,
                              error_handler=self._connected)

    def _got_ppd (self, connection, name, result):
        if isinstance (result, Exception):
            self.emit ('ppd-error', name, result)
        else:
            debugprint ("PPD cache: caching %s" % result)
            self._cache[name] = result
            self.fetch_ppd (name)

    def _got_ppd3 (self, connection, name, result):
        (status, modtime, filename) = result
        if status in [cups.HTTP_OK, cups.HTTP_NOT_MODIFIED]:
            if status == cups.HTTP_OK:
                debugprint ("PPD cache: caching %s (%s) - %s" % (filename,
                                                                 modtime,
                                                                 status))
                self._cache[name] = filename
                self._modtimes[name] = modtime

            self.fetch_ppd (name, check_uptodate=False)
        else:
            self.emit ('ppd-error', name, cups.HTTPError (status))

    def _connected (self, connection, exc):
        self._connecting = False
        if isinstance (exc, Exception):
            self._cups = None
            self._exc = exc
        else:
            self._cups = connection

        queued = self._queued
        self._queued = list()
        for name in queued:
            self.fetch_ppd (name)

gobject.type_register (PPDCache)

if __name__ == "__main__":
    from debug import *
    set_debugging (True)
    gobject.threads_init ()
    loop = gobject.MainLoop ()

    def signal (obj, name, result):
        print "****"
        print obj
        print name
        print result

    c = cups.Connection ()
    printers = c.getPrinters ()
    del c

    cache = PPDCache ()
    cache.connect ('ppd-error', signal)
    cache.connect ('ppd-ready', signal)
    p = None
    for p in printers:
        cache.fetch_ppd (p)

    if p:
        gobject.timeout_add_seconds (1, cache.fetch_ppd, p)
    loop.run ()

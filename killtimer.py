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

import threading

from gi.repository import GLib

from debug import *

class KillTimer:
    def __init__ (self, timeout=30, killfunc=None):
        self._timeout = timeout
        self._killfunc = killfunc
        self._holds = 0
        self._add_timeout ()
        self._lock = threading.Lock()

    def _add_timeout (self):
        self._timer = GLib.timeout_add_seconds (self._timeout, self._kill)

    def _kill (self):
        debugprint ("Timeout (%ds), exiting" % self._timeout)
        if self._killfunc:
            self._killfunc ()
        else:
            sys.exit (0)

    def add_hold (self):
        self._lock.acquire()
        if self._holds == 0:
            debugprint ("Kill timer stopped")
            GLib.source_remove (self._timer)

        self._holds += 1
        self._lock.release()

    def remove_hold (self):
        self._lock.acquire()
        if self._holds > 0:
            self._holds -= 1
            if self._holds == 0:
                debugprint ("Kill timer started")
                self._add_timeout ()
        self._lock.release()

    def alive (self):
        self._lock.acquire()
        if self._holds == 0:
            GLib.source_remove (self._timer)
            self._add_timeout ()
        self._lock.release()

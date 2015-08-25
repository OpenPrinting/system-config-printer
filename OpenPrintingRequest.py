#!/usr/bin/python

## system-config-printer

## Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014 Red Hat, Inc.
## Authors:
##  Tim Waugh <twaugh@redhat.com>
##  Till Kamppeter <till.kamppeter@gmail.com>

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

# config is generated from config.py.in by configure
import config

import cupshelpers
from debug import *

from gi.repository import GObject

class OpenPrintingRequest(GObject.GObject):
    __gsignals__ = {
        'finished':     (GObject.SignalFlags.RUN_LAST, None,
                         (
                             # list of (printerid,name) tuples
                             GObject.TYPE_PYOBJECT,

                             # dict of printerid: dict of drivername: dict
                             # for driver info
                             GObject.TYPE_PYOBJECT,
                         )),

        'error':        (GObject.SignalFlags.RUN_LAST, None,
                         (
                             # HTTP status
                             int,

                             GObject.TYPE_PYOBJECT,
                         )),
    }

    def __init__ (self, **args):
        GObject.GObject.__init__ (self)
        debugprint ("Starting")
        self.openprinting = cupshelpers.openprinting.OpenPrinting (**args)
        self._handle = None
        debugprint ("+%s" % self)

    def __del__ (self):
        debugprint ("-%s" % self)

    def cancel (self):
        debugprint ("%s: cancel()" % self)
        if self._handle is not None:
            self.openprinting.cancelOperation (self._handle)
            self._handle = None

        debugprint ("%s -> 'error'" % self)
        self.emit ('error', 0, 'canceled')

    def searchPrinters (self, searchterm, user_data=None):
        debugprint ("%s: searchPrinters()" % self)
        self._handle = self.openprinting.searchPrinters (searchterm,
                                                         self._printers_got,
                                                         user_data)

    def _printers_got (self, status, user_data, printers):
        self._handle = None
        if status != 0:
            debugprint ("%s -> 'error'" % self)
            self.emit ('error', status, printers)
            return

        self.downloadable_printers_unchecked = [(x, printers[x])
                                                for x in printers]
        self.downloadable_printers = []
        self.downloadable_drivers = dict() # by printer id of dict

        # Kick off a search for drivers for each model.
        if not self._query_next_printer ():
            self._drivers_got ()

    def _query_next_printer (self):
        """
        If there are more printers to query, kick off a query and
        return True.

        Otherwise return False.
        """

        try:
            user_data = self.downloadable_printers_unchecked.pop ()
            (printer_id, printer_name) = user_data
        except IndexError:
            debugprint ("%s: All printer driver queries finished" % self)
            return False

        if config.DOWNLOADABLE_ONLYFREE:
            self.openprinting.onlyfree = 1
        else:
            self.openprinting.onlyfree = 0

        options = dict()
        if config.DOWNLOADABLE_ONLYPPD:
            options['onlyppdfiles'] = '1'
        else:
            options['onlydownload'] = '1'
            options['packagesystem'] = config.packagesystem

        debugprint ("%s: Querying drivers for %s" % (self, printer_id))
        self._handle = self.openprinting.listDrivers (printer_id,
                                                      self._printer_drivers_got,
                                                      user_data=user_data,
                                                      extra_options=options)

        return True

    def _printer_drivers_got (self, status, user_data, drivers):
        self._handle = None
        if status != 0:
            debugprint ("%s -> 'error'" % self)
            self.emit ('error', status, drivers)
            return

        if drivers:
            debugprint ("%s: - drivers found" % self)
            drivers_installable = { }
            for driverkey in drivers.keys ():
                driver = drivers[driverkey]
                if (('ppds' in driver and
                     len(driver['ppds']) > 0) or
                    (not config.DOWNLOADABLE_ONLYPPD and
                     'packages' in driver and
                     len(driver['packages']) > 0)):
                    # Driver entry with installable resources (Package or
                    # PPD), overtake it
                    drivers_installable[driverkey] = drivers[driverkey]
                else:
                    debugprint ("Not using invalid driver entry %s" %
                                driverkey)

            if len(drivers_installable) > 0:
                debugprint ("%s: - drivers with installable resources found" %
                            self)
                (printer_id, printer_name) = user_data
                self.downloadable_drivers[printer_id] = drivers_installable
                self.downloadable_printers.append (user_data)

        if not self._query_next_printer ():
            self._drivers_got ()

    def _drivers_got (self):
        self._handle = None
        debugprint ("%s -> 'finished'" % self)
        self.emit ('finished',
                   self.downloadable_printers,
                   self.downloadable_drivers)

if __name__ == '__main__':
    from pprint import pprint
    mainloop = GObject.MainLoop ()
    set_debugging (True)
    cupshelpers.set_debugprint_fn (debugprint)
    req = OpenPrintingRequest ()
    handlers = []

    def done (obj):
        for handler in handlers:
            obj.disconnect (handler)

        GObject.timeout_add_seconds (1, mainloop.quit)

    def error (obj, status, err):
        print ("Error: %d" % status)
        print (repr (err))
        done (obj)

    def finished (obj, printers, drivers):
        pprint (printers)
        pprint (drivers)
        done (obj)

    handlers.append (req.connect ('error', error))
    handlers.append (req.connect ('finished', finished))
    GObject.idle_add (req.searchPrinters, 'ricoh 8000')
    mainloop.run ()
    del req

## system-config-printer

## Copyright (C) 2008 Red Hat, Inc.
## Copyright (C) 2008 Tim Waugh <twaugh@redhat.com>

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

__all__  = ['set_debugprint_fn',
            'Device', 'Printer', 'activateNewPrinter',
            'copyPPDOptions', 'getDevices', 'getPrinters',
            'missingPackagesAndExecutables', 'parseDeviceID',
            'setPPDPageSize',
            'ppds',
            'openprinting']

def _no_debug (x):
    return

_debugprint_fn = _no_debug
def _debugprint (x):
    _debugprint_fn (x)

def set_debugprint_fn (debugprint):
    """
    Set debugging hook.

    @param debugprint: function to print debug output
    @type debugprint: fn (str) -> None
    """
    global _debugprint_fn
    _debugprint_fn = debugprint

from cupshelpers import				\
    Device,					\
    Printer,					\
    activateNewPrinter,				\
    copyPPDOptions,				\
    getDevices,					\
    getPrinters,				\
    missingPackagesAndExecutables,		\
    parseDeviceID,				\
    setPPDPageSize

import ppds
import openprinting

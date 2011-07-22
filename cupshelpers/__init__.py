## system-config-printer

## Copyright (C) 2008, 2011 Red Hat, Inc.
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

__all__  = ['set_debugprint_fn',
            'Device', 'Printer', 'activateNewPrinter',
            'copyPPDOptions', 'getDevices', 'getPrinters',
            'missingPackagesAndExecutables', 'missingExecutables',
            'parseDeviceID',
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
    missingExecutables,                         \
    parseDeviceID,				\
    setPPDPageSize

import ppds
import openprinting

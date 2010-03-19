#!/usr/bin/env python

## check-device-ids

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

import cups
import cupshelpers
from cupshelpers.ppds import PPDs, ppdMakeModelSplit
import sys

cups.setUser ('root')
c = cups.Connection ()
print "Fetching driver list"
ppds = PPDs (c.getPPDs ())
ppds._init_ids ()
makes = ppds.getMakes ()

devices = None
if len (sys.argv) > 1 and sys.argv[1] == '--help':
    print "Syntax: check-device-ids <device-make-and-model> <device-id>"
    sys.exit (1)

if len (sys.argv) == 3:
    id_dict = cupshelpers.parseDeviceID (sys.argv[2])
    if id_dict.has_key ("MFG") and id_dict.has_key ("MDL"):
        devices = { 'user-specified':
                        { 'device-make-and-model': sys.argv[1],
                          'device-id': sys.argv[2] }
                    }

if devices == None:
    print "Examining connected devices"
    try:
        devices = c.getDevices (include_schemes=["usb",
                                                 "parallel",
                                                 "serial",
                                                 "bluetooth"])
    except cups.IPPError, (e, m):
        if e == cups.IPP_FORBIDDEN:
            print "Run this as root to examine IDs from attached devices."
            sys.exit (1)

        if e == cups.IPP_NOT_AUTHORIZED:
            print "Not authorized."
            sys.exit (1)

if len (devices) == 0:
    print "No attached devices."
    sys.exit (0)

n = 0
for device, attrs in devices.iteritems ():
    make_and_model = attrs.get ('device-make-and-model')
    device_id = attrs.get ('device-id')
    if not (make_and_model and device_id):
        continue

    n += 1

i = 1
item = unichr (0x251c) + unichr (0x2500) + unichr (0x2500)
last = unichr (0x2514) + unichr (0x2500) + unichr (0x2500)
for device, attrs in devices.iteritems ():
    make_and_model = attrs.get ('device-make-and-model')
    device_id = attrs.get ('device-id')
    if not (make_and_model and device_id):
        continue

    id_fields = cupshelpers.parseDeviceID (device_id)
    if i < n:
        line = item
    else:
        line = last

    cmd = id_fields['CMD']
    if cmd:
        cmd = "CMD:%s;" % reduce (lambda x, y: x + ',' + y, cmd)
    else:
        cmd = ""

    print "%s %s: MFG:%s;MDL:%s;%s" % (line, make_and_model,
                                       id_fields['MFG'],
                                       id_fields['MDL'],
                                       cmd)
    
    try:
        drivers = ppds.ids[id_fields['MFG'].lower ()][id_fields['MDL'].lower ()]
    except KeyError:
        drivers = []

    if i < n:
        more = unichr (0x2502)
    else:
        more = " "

    if drivers:
        drivers.sort ()
        n_drivers = len (drivers)
        j = 1
        for driver in drivers:
            if j < n_drivers:
                print "%s   %s %s" % (more, item, driver)
            else:
                print "%s   %s %s" % (more, last, driver)

            j += 1
    else:
        print "%s   (No drivers)" % more

    (mfr, mdl) = ppdMakeModelSplit (make_and_model)
    mfrl = mfr.lower ()
    mdls = None
    for make in makes:
        if make.lower () == mfrl:
            mdls = ppds.makes[make]
            break
    if mdls:
        (s, bestmatches) = ppds._findBestMatchPPDs (mdls, id_fields['MDL'])
        if s == ppds.STATUS_SUCCESS:
            missing = set (bestmatches) - set (drivers)
            for each in missing:
                print "%s       MISSING  %s" % (more, each)

    i += 1

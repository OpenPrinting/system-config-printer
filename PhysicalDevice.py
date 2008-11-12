#!/usr/bin/env python

## Copyright (C) 2008 Tim Waugh <twaugh@redhat.com>
## Copyright (C) 2008 Red Hat, Inc.

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

from gettext import gettext as _
import cupshelpers

class PhysicalDevice:
    def __init__(self, device):
        self.devices = None
        self.add_device (device)

    def _canonical_id (self, device):
        mfg = device.id_dict.get ('MFG', '')
        mdl = device.id_dict.get ('MDL', '')
        if mfg == '':
            return ('', '')

        make_and_model = "%s %s" % (mfg, mdl)
        return cupshelpers.ppds.ppdMakeModelSplit (make_and_model)

    def add_device (self, device):
        (mfg, mdl) = self._canonical_id (device)
        if self.devices == None:
            self.mfg = mfg
            self.mdl = mdl
            self.mfg_lower = mfg.lower ()
            self.mdl_lower = mdl.lower ()
            self.sn = device.id_dict.get ('SN', '')
            self.devices = []
        else:
            def nicest (a, b):
                def count_lower (s):
                    l = s.lower ()
                    n = 0
                    for i in xrange (len (s)):
                        if l[i] != s[i]:
                            n += 1
                    return n
                if count_lower (b) < count_lower (a):
                    return b
                return a

            self.mfg = nicest (self.mfg, mfg)
            self.mdl = nicest (self.mdl, mdl)

            sn = device.id_dict.get ('SN', '')
            if sn != self.sn:
                raise RuntimeError

        self.devices.append (device)
        self.devices.sort ()

    def get_devices (self):
        return self.devices

    def get_info (self):
        if self.mfg == '':
            return self.devices[0].info

        info = "%s %s" % (self.mfg, self.mdl)
        if len (self.sn) > 0:
            info += " (%s)" % self.sn
        return info

    def __str__ (self):
        return "(description: %s)" % self.__repr__ ()

    def __repr__ (self):
        return "<PhysicalDevice.PhysicalDevice (%s,%s,%s)>" % (self.mfg,
                                                               self.mdl,
                                                               self.sn)

    def __cmp__(self, other):
        if other == None or type (other) != type (self):
            return 1

        if other.mfg == '' or self.mfg == '':
            # One or other is just a backend, not a real physical device.
            if other.mfg == '' and self.mfg == '':
                return cmp (self.devices[0], other.devices[0])

            if other.mfg == '':
                return -1
            return 1

        mfgcmp = cmp (self.mfg_lower, other.mfg_lower)
        if mfgcmp != 0:
            return mfgcmp
        mdlcmp = cmp (self.mdl_lower, other.mdl_lower)
        if mdlcmp != 0:
            return mdlcmp
        return cmp (self.sn, other.sn)

if __name__ == '__main__':
    import authconn
    c = authconn.Connection ()
    devices = cupshelpers.getDevices (c)

    physicaldevices = []
    for device in devices.values ():
        physicaldevice = PhysicalDevice (device)
        try:
            i = physicaldevices.index (physicaldevice)
            physicaldevices[i].add_device (device)
        except ValueError:
            physicaldevices.append (physicaldevice)

    physicaldevices.sort ()
    for physicaldevice in physicaldevices:
        print physicaldevice.get_info ()
        devices = physicaldevice.get_devices ()
        for device in devices:
            print " ", device

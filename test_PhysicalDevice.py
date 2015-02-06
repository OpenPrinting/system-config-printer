#!/usr/bin/python3

## Copyright (C) 2015 Red Hat, Inc.
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

from PhysicalDevice import PhysicalDevice
from cupshelpers import cupshelpers

def run_test():
    # See https://bugzilla.redhat.com/show_bug.cgi?id=1154686
    device = cupshelpers.Device("dnssd://Abc%20Def%20%5BABCDEF%5D._ipp._tcp.local/",
                                **{'device-class': "network",
                                   'device-make-and-model': "Abc Def",
                                   'device-id': "MFG:Abc;MDL:Def;"})
    phys = PhysicalDevice (device)

    device = cupshelpers.Device("hp:/net/Abc_Def?hostname=ABCDEF",
                                **{'device-class': "network",
                                   'device-make-and-model': "Abc Def",
                                   'device-id': "MFG:Abc;MDL:Def;"})
    phys.add_device (device)

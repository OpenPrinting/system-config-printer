#!/usr/bin/python

## system-config-printer

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
## Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

## This program performs validation that cannot be performed using
## RELAX NG alone.

import fnmatch
import sys
import xml.etree.ElementTree

class Validator:
    def __init__ (self, filename):
        self._filename = filename

    def validate (self):
        filename = self._filename
        print "Validating %s" % filename
        preferreddrivers = xml.etree.ElementTree.XML (file (filename).read ())
        (drivertypes, preferenceorder) = preferreddrivers.getchildren ()
        validates = True

        names = set()
        for drivertype in drivertypes.getchildren ():
            name = drivertype.get ("name")
            names.add (name)

        for printer in preferenceorder.getchildren ():
            types = []
            drivers = printer.find ("drivers")
            if drivers != None:
                types.extend (drivers.getchildren ())

            blacklist = printer.find ("blacklist")
            if blacklist != None:
                types.extend (blacklist.getchildren ())

            for drivertype in types:
                pattern = drivertype.text.strip ()
                matches = fnmatch.filter (names, pattern)
                names -= set (matches)

        for name in names:
            validates = False
            print >>sys.stderr, ("*** Driver type \"%s\" is never used" %
                                 name)

        return validates

import getopt
import os
opts, args = getopt.getopt (sys.argv[1:], "")

if len (args) < 1:
    dirname = os.path.dirname (sys.argv[0])
    args = [os.path.join (dirname, "preferreddrivers.xml")]

exitcode = 0
for filename in args:
    validator = Validator (filename)
    if not validator.validate ():
        exitcode = 1

sys.exit (exitcode)

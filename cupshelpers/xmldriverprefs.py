#!/usr/bin/env python

## system-config-printer

## Copyright (C) 2006, 2007, 2008, 2009, 2010 Red Hat, Inc.
## Copyright (C) 2006 Florian Festi <ffesti@redhat.com>
## Copyright (C) 2006, 2007, 2008, 2009 Tim Waugh <twaugh@redhat.com>

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

import xml.etree.ElementTree
import re
from .cupshelpers import parseDeviceID

class DriverType:
    """
    A type of driver.
    """

    def __init__ (self, name):
        self.name = name
        self.ppd_name = None
        self.attributes = []
        self.deviceid = []

    def add_ppd_name (self, pattern):
        """
        An optional PPD name regular expression.
        """
        self.ppd_name = re.compile (pattern, re.I)

    def add_attribute (self, name, pattern):
        """
        An optional IPP attribute name and regular expression to match
        against its values.
        """
        self.attributes.append ((name, re.compile (pattern, re.I)))

    def add_deviceid (self, field, pattern):
        """
        An optional IEEE 1284 Device ID field name and regular
        expression to match against its value.
        """
        self.deviceid.append ((field.upper (), re.compile (pattern, re.I)))

    def get_name (self):
        """
        Return the name for this driver type.
        """
        return self.name

    def __repr__ (self):
        return "<DriverType %s instance at 0x%x>" % (self.name, id (self))

    def match (self, ppd_name, attributes):
        """
        Return True if there is a match for all specified criteria.

        ppdname: string

        attributes: dict

        deviceid: dict indexed by Device ID field key, of strings;
        except the CMD field which must be a list of strings.
        """

        matches = True
        if self.ppd_name and not self.ppd_name.match (ppd_name):
            matches = False

        if matches:
            for name, match in self.attributes:
                if not attributes.has_key (name):
                    matches = False
                    break

                values = attributes[name]
                if not isinstance (values, list):
                    # In case getPPDs() was used instead of getPPDs2()
                    values = [values]

                any_value_matches = False
                for value in values:
                    if match.match (value):
                        any_value_matches = True
                        break

                if not any_value_matches:
                    matches = False
                    break

        if matches:
            if self.deviceid and not attributes.has_key ("ppd-device-id"):
                matches = False
            else:
                # This is a match if any of the ppd-device-id values
                # match.
                deviceidlist = attributes["ppd-device-id"]
                if not isinstance (deviceidlist, list):
                    # In case getPPDs() was used instead of getPPDs2()
                    deviceidlist = [deviceidlist]

                any_id_matches = False
                for deviceidstr in deviceidlist:
                    deviceid = parseDeviceID (deviceidstr)

                    this_id_matches = True
                    for field, match in self.deviceid:
                        if not deviceid.has_key (field):
                            this_id_matches = False
                            break

                        if field == "CMD":
                            this_field_matches = False
                            for cmd in deviceid[field]:
                                if match.match (cmd):
                                    this_field_matches = True
                                    break

                            if not this_field_matches:
                                this_id_matches = False
                                break

                        if not match.match (deviceid[field]):
                            this_id_matches = False
                            break

                    if this_id_matches:
                        any_id_matches = True
                        break

                if not any_id_matches:
                    matches = False

        return matches

class DriverTypes:
    """
    A list of driver types.
    """

    def __init__ (self):
        self.drivertypes = []

    def load (self, filename):
        """
        Load the list of driver types from an XML file.
        """

        types = []
        drivertypes = xml.etree.ElementTree.XML (file (filename).read ())
        for drivertype in drivertypes.getchildren ():
            t = DriverType (drivertype.attrib["name"])
            if drivertype.attrib.has_key ("ppdname"):
                t.add_ppd_name (drivertype.attrib["ppdname"])

            for child in drivertype.getchildren ():
                if child.tag == "attribute":
                    t.add_attribute (child.attrib["name"],
                                     child.attrib["match"])
                elif child.tag == "deviceid":
                    t.add_deviceid (child.attrib["field"],
                                    child.attrib["match"])

            types.append (t)

        self.drivertypes = types

    def match (self, ppdname, ppddict):
        """
        Return the first matching drivertype for a PPD, given its name
        and attributes, or None if there is no match.
        """

        for drivertype in self.drivertypes:
            if drivertype.match (ppdname, ppddict):
                return drivertype

        return None

    def get_ordered_ppdnames (self, drivertypes, ppds):
        """
        Given a list of driver type names and a dict of PPD attributes
        by PPD name, return a list of tuples in the form
        (driver-type-name, PPD-name), representing PPDs that match the
        list of driver types.

        The returned tuples will have driver types in the same order
        as the driver types given, with the exception that any
        blacklisted driver types will be omitted from the returned
        result.
        """

        ppdnames = []

        # First find out what driver types we have
        ppdtypes = {}
        for ppd_name, ppd_dict in ppds.iteritems ():
            drivertype = self.match (ppd_name, ppd_dict)
            name = drivertype.get_name ()
            m = ppdtypes.get (name, [])
            m.append (ppd_name)
            ppdtypes[name] = m

        # Now construct the list.
        for drivertypename in drivertypes:
            for ppd_name in ppdtypes.get (drivertypename, []):
                if ppd_name in ppdnames:
                    continue

                ppdnames.append ((drivertypename, ppd_name))

        return ppdnames

class PrinterType:
    """
    A make-and-model pattern and/or set of IEEE 1284 Device ID
    patterns for matching a set of printers, together with an ordered
    list of driver type names.
    """

    def __init__ (self):
        self.make_and_model = None
        self.deviceid = []
        self.drivertypes = []
        self.blacklist = set()

    def add_make_and_model (self, pattern):
        """
        Set a make-and-model regular expression.  Only one is permitted.
        """
        self.make_and_model = re.compile (pattern, re.I)

    def add_deviceid (self, field, pattern):
        """
        Add a Device ID regular expression.
        """
        self.deviceid.append ((field.upper (), re.compile (pattern, re.I)))

    def add_drivertype (self, name):
        """
        Append a driver type.
        """
        self.drivertypes.append (name)

    def get_drivertypes (self):
        """
        Return the list of driver types.
        """
        return self.drivertypes

    def add_blacklisted (self, name):
        """
        Add a blacklisted driver type.
        """
        self.blacklist.add (name)

    def get_blacklist (self):
        """
        Return the set of blacklisted driver types.
        """
        return self.blacklist

    def match (self, make_and_model, deviceid):
        """
        Return True if there are no constraints to match against; if
        the make-and-model pattern matches; or if all of the IEEE 1284
        Device ID patterns match.

        The CMD field is treated specially.  If any of the
        comma-separated words in this field value match, the Device ID
        pattern is considered to match.

        The deviceid parameter must be a dict indexed by Device ID
        field key, of strings; except for the CMD field which must be
        a list of strings.

        Return False otherwise.
        """

        matches = (not self.make_and_model and not self.deviceid)
        if self.make_and_model:
            if self.make_and_model.match (make_and_model):
                matches = True

        if not matches and self.deviceid:
            all_match = True
            for field, regexp in self.deviceid:
                if not deviceid.has_key (field):
                    all_match = False
                    break

                if field == "CMD":
                    any_cmd_match = False
                    for cmd in deviceid[field]:
                        if regexp.match (cmd):
                            any_cmd_match = True
                            break

                    if not any_cmd_match:
                        all_match = False
                        break
                elif not regexp.match (deviceid[field]):
                    all_match = False
                    break

            if all_match:
                matches = True

        return matches

class PreferenceOrder:
    """
    A policy for choosing the preference order for drivers.
    """

    def __init__ (self):
        self.ptypes = []

    def load (self, filename):
        """
        Load the policy from an XML file.
        """

        preferreddrivers = xml.etree.ElementTree.XML (file (filename).read ())
        for printer in preferreddrivers.getchildren ():
            ptype = PrinterType ()
            for child in printer.getchildren ():
                if child.tag == "make-and-model":
                    ptype.add_make_and_model (child.attrib["match"])
                elif child.tag == "deviceid":
                    ptype.add_deviceid (child.attrib["field"],
                                        child.attrib["match"])

                elif child.tag == "drivers":
                    for drivertype in child.getchildren ():
                        ptype.add_drivertype (drivertype.text)

                elif child.tag == "blacklist":
                    for drivertype in child.getchildren ():
                        ptype.add_blacklisted (drivertype.text)

            self.ptypes.append (ptype)

    def get_ordered_types (self, make_and_model, deviceid):
        """
        Return an accumulated list of driver types from all printer
        types that match a given printer's device-make-and-model and
        IEEE 1284 Device ID.

        The deviceid parameter must be None or a dict indexed by
        short-form upper-case field keys.
        """

        if deviceid == None:
            deviceid = {}

        if make_and_model == None:
            make_and_model = ""

        orderedtypes = []
        blacklist = set()
        for ptype in self.ptypes:
            if ptype.match (make_and_model, deviceid):
                for drivertype in ptype.get_drivertypes ():
                    if drivertype not in orderedtypes:
                        orderedtypes.append (drivertype)

                blacklist.update (ptype.get_blacklist ())

        if blacklist:
            # Remove blacklisted drivers.
            remaining = []
            for t in orderedtypes:
                if t not in blacklist:
                    remaining.append (t)

            orderedtypes = remaining

        return orderedtypes


def test (xml_dir=None):
    import cups
    import ppds
    from pprint import pprint
    from time import time
    import os.path

    if xml_dir == None:
        xml_dir = os.path.join (os.path.join (os.path.dirname (__file__),
                                              ".."),
                                "xml")

    typesfilename = os.path.join (xml_dir, "drivertypes.xml")
    preffilename = os.path.join (xml_dir, "preferreddrivers.xml")
    c = cups.Connection ()
    loadstart = time ()
    drivertypes = DriverTypes ()
    drivertypes.load (typesfilename)
    loadtime = time () - loadstart
    print "Time to load %s: %.3fs" % (typesfilename, loadtime)
    try:
        cupsppds = c.getPPDs2 ()
    except AttributeError:
        # getPPDs2 requires pycups >= 1.9.52 
        cupsppds = c.getPPDs ()

    loadstart = time ()
    preforder = PreferenceOrder ()
    preforder.load (preffilename)
    loadtime = time () - loadstart
    print "Time to load %s: %.3fs" % (preffilename, loadtime)

    ppdfinder = ppds.PPDs (cupsppds)

    for make in ppdfinder.getMakes ():
        for model in ppdfinder.getModels (make):
            ppds = ppdfinder.getInfoFromModel (make, model)
            mm = make + " " + model
            orderedtypes = preforder.get_ordered_types (mm, None)
            orderedppds = drivertypes.get_ordered_ppdnames (orderedtypes,
                                                            ppds)
            print mm + ":"
            for t, ppd in orderedppds:
                print "  %s\n    (%s)" % (ppd, t)

            print

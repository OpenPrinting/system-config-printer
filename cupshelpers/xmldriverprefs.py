#!/usr/bin/python

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
## Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import fnmatch
import re
import xml.etree.ElementTree
from .cupshelpers import parseDeviceID
import ppds

def PreferredDrivers (filename):
    preferreddrivers = xml.etree.ElementTree.XML (file (filename).read ())
    return preferreddrivers.getchildren()

class DeviceIDMatch:
    """
    A set of fields and regular expressions for matching a Device ID.
    """
    def __init__ (self):
        self._re = dict()

    def add_field (self, field, pattern):
        self._re[field.upper ()] = re.compile (pattern, re.I)

    def match (self, deviceid):
        """
        Match against a parsed Device ID dictionary.

        The CMD field is treated specially.  If any of the
        comma-separated words in this field value match, the Device ID
        pattern is considered to match.
        """

        for field, match in self._re.iteritems ():
            if not deviceid.has_key (field):
                return False

            if field == "CMD":
                this_field_matches = False
                for cmd in deviceid[field]:
                    if match.match (cmd):
                        this_field_matches = True
                        break

                if not this_field_matches:
                    return False

            if not match.match (deviceid[field]):
                return False

        return True

class DriverType:
    """
    A type of driver.
    """

    FIT_EXACT_CMD =     "exact-cmd"
    FIT_EXACT =         "exact"
    FIT_CLOSE =         "close"
    FIT_GENERIC =       "generic"
    FIT_NONE =          "none"

    def __init__ (self, name):
        self.name = name
        self.ppd_name = None
        self.attributes = []
        self.deviceid = []

        class AlwaysTrue:
            def get (self, k, d=None):
                return True

        self._fit = AlwaysTrue ()
        self._packagehint = None

    def add_ppd_name (self, pattern):
        """
        An optional PPD name regular expression.
        """
        self.ppd_name = re.compile (pattern, re.I)

        # If the PPD name pattern includes a scheme, we can perhaps
        # deduce which package would provide this driver type.
        if self._packagehint != None:
            return

        parts = pattern.split (":", 1)
        if len (parts) > 1:
            scheme = parts[0]
            if scheme == "drv":
                rest = parts[1]
                if rest.startswith ("///"):
                    drv = rest[3:]
                    f = drv.rfind ("/")
                    if f != -1:
                        drv = drv[:f]
                        self._packagehint = "/usr/share/cups/drv/%s" % drv
            else:
                self._packagehint = "/usr/lib/cups/driver/%s" % scheme

    def add_attribute (self, name, pattern):
        """
        An optional IPP attribute name and regular expression to match
        against its values.
        """
        self.attributes.append ((name, re.compile (pattern, re.I)))

    def add_deviceid_match (self, deviceid_match):
        """
        An optional IEEE 1284 Device ID match.
        """
        self.deviceid.append (deviceid_match)

    def add_fit (self, text):
        self._fit = {}
        for fittype in text.split():
            self._fit[fittype] = True

            # <fit>exact</fit> matches exact-cmd as well
            if fittype == self.FIT_EXACT:
                self._fit[self.FIT_EXACT_CMD] = True

    def set_packagehint (self, hint):
        self._packagekit = hint

    def get_name (self):
        """
        Return the name for this driver type.
        """
        return self.name

    def __repr__ (self):
        return "<DriverType %s instance at 0x%x>" % (self.name, id (self))

    def match (self, ppd_name, attributes, fit):
        """
        Return True if there is a match for all specified criteria.

        ppdname: string

        attributes: dict

        fit: string
        """

        matches = self._fit.get (fit, False)
        if matches and self.ppd_name and not self.ppd_name.match (ppd_name):
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
            elif self.deviceid:
                # This is a match if any of the ppd-device-id values
                # match.
                deviceidlist = attributes["ppd-device-id"]
                if not isinstance (deviceidlist, list):
                    # In case getPPDs() was used instead of getPPDs2()
                    deviceidlist = [deviceidlist]

                any_id_matches = False
                for deviceidstr in deviceidlist:
                    deviceid = parseDeviceID (deviceidstr)
                    for match in self.deviceid:
                        if match.match (deviceid):
                            any_id_matches = True
                            break

                if not any_id_matches:
                    matches = False

        return matches

    def get_packagehint (self):
        return None

class DriverTypes:
    """
    A list of driver types.
    """

    def __init__ (self):
        self.drivertypes = []

    def load (self, drivertypes):
        """
        Load the list of driver types from an XML file.
        """

        types = []
        for drivertype in drivertypes.getchildren ():
            t = DriverType (drivertype.attrib["name"])

            for child in drivertype.getchildren ():
                if child.tag == "ppdname":
                    t.add_ppd_name (child.attrib["match"])
                elif child.tag == "attribute":
                    t.add_attribute (child.attrib["name"],
                                     child.attrib["match"])
                elif child.tag == "deviceid":
                    deviceid_match = DeviceIDMatch ()
                    for field in child.getchildren ():
                        if field.tag == "field":
                            deviceid_match.add_field (field.attrib["name"],
                                                      field.attrib["match"])

                    t.add_deviceid_match (deviceid_match)
                elif child.tag == "fit":
                    t.add_fit (child.text)

            types.append (t)

        self.drivertypes = types

    def match (self, ppdname, ppddict, fit):
        """
        Return the first matching drivertype for a PPD, given its name,
        attributes, and fitness, or None if there is no match.
        """

        for drivertype in self.drivertypes:
            if drivertype.match (ppdname, ppddict, fit):
                return drivertype

        return None

    def filter (self, pattern):
        """
        Return the subset of driver type names that match a glob
        pattern.
        """

        return fnmatch.filter (map (lambda x: x.get_name (),
                                    self.drivertypes),
                               pattern)

    def get_ordered_ppdnames (self, drivertypes, ppdsdict, fit):
        """
        Given a list of driver type names, a dict of PPD attributes by
        PPD name, and a dict of driver fitness status codes by PPD
        name, return a list of tuples in the form (driver-type-name,
        PPD-name), representing PPDs that match the list of driver
        types.

        The returned tuples will have driver types in the same order
        as the driver types given, with the exception that any
        blacklisted driver types will be omitted from the returned
        result.
        """

        ppdnames = []

        # First find out what driver types we have
        ppdtypes = {}
        fit_default = DriverType.FIT_CLOSE
        for ppd_name, ppd_dict in ppdsdict.iteritems ():
            drivertype = self.match (ppd_name, ppd_dict, fit.get (ppd_name,
                                                                  fit_default))
            if drivertype:
                name = drivertype.get_name ()
            else:
                name = "none"

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
        self.drivertype_patterns = []
        self.avoid = set()
        self.blacklist = set()

    def add_make_and_model (self, pattern):
        """
        Set a make-and-model regular expression.  Only one is permitted.
        """
        self.make_and_model = re.compile (pattern, re.I)

    def add_deviceid_match (self, deviceid_match):
        """
        Add a Device ID match.
        """
        self.deviceid.append (deviceid_match)

    def add_drivertype_pattern (self, name):
        """
        Append a driver type pattern.
        """
        self.drivertype_patterns.append (name.strip ())

    def get_drivertype_patterns (self):
        """
        Return the list of driver type patterns.
        """
        return self.drivertype_patterns

    def add_avoidtype_pattern (self, name):
        """
        Add an avoid driver type pattern.
        """
        self.avoid.add (name)

    def get_avoidtype_patterns (self):
        """
        Return the set of driver type patterns to avoid.
        """
        return self.avoid

    def add_blacklisted (self, name):
        """
        Add a blacklisted driver type pattern.
        """
        self.blacklist.add (name)

    def get_blacklist (self):
        """
        Return the set of blacklisted driver type patterns.
        """
        return self.blacklist

    def match (self, make_and_model, deviceid):
        """
        Return True if there are no constraints to match against; if
        the make-and-model pattern matches; or if all of the IEEE 1284
        Device ID patterns match.

        The deviceid parameter must be a dict indexed by Device ID
        field key, of strings; except for the CMD field which must be
        a list of strings.

        Return False otherwise.
        """

        matches = (self.make_and_model == None and self.deviceid == [])
        if self.make_and_model:
            if self.make_and_model.match (make_and_model):
                matches = True

        if not matches:
            for match in self.deviceid:
                if match.match (deviceid):
                    matches = True
                    break

        return matches

class PreferenceOrder:
    """
    A policy for choosing the preference order for drivers.
    """

    def __init__ (self):
        self.ptypes = []

    def load (self, preferreddrivers):
        """
        Load the policy from an XML file.
        """

        for printer in preferreddrivers.getchildren ():
            ptype = PrinterType ()
            for child in printer.getchildren ():
                if child.tag == "make-and-model":
                    ptype.add_make_and_model (child.attrib["match"])
                elif child.tag == "deviceid":
                    deviceid_match = DeviceIDMatch ()
                    for field in child.getchildren ():
                        if field.tag == "field":
                            deviceid_match.add_field (field.attrib["name"],
                                                      field.attrib["match"])
                    ptype.add_deviceid_match (deviceid_match)

                elif child.tag == "drivers":
                    for drivertype in child.getchildren ():
                        ptype.add_drivertype_pattern (drivertype.text)

                elif child.tag == "avoid":
                    for drivertype in child.getchildren ():
                        ptype.add_avoidtype_pattern (drivertype.text)

                elif child.tag == "blacklist":
                    for drivertype in child.getchildren ():
                        ptype.add_blacklisted (drivertype.text)

            self.ptypes.append (ptype)

    def get_ordered_types (self, drivertypes, make_and_model, deviceid):
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
        avoidtypes = set()
        for ptype in self.ptypes:
            if ptype.match (make_and_model, deviceid):
                for pattern in ptype.get_drivertype_patterns ():
                    # Match against the glob pattern
                    for drivertype in drivertypes.filter (pattern):
                        # Add each result if not already in the list.
                        if drivertype not in orderedtypes:
                            orderedtypes.append (drivertype)

                for pattern in ptype.get_avoidtype_patterns ():
                    # Match against the glob pattern.
                    for drivertype in drivertypes.filter (pattern):
                        # Add each result to the set.
                        avoidtypes.add (drivertype)

                for pattern in ptype.get_blacklist ():
                    # Match against the glob pattern.
                    for drivertype in drivertypes.filter (pattern):
                        # Add each result to the set.
                        blacklist.add (drivertype)

        if avoidtypes:
            avoided = []
            for t in avoidtypes:
                try:
                    i = orderedtypes.index (t)
                    del orderedtypes[i]
                    avoided.append (t)
                except IndexError:
                    continue

            orderedtypes.extend (avoided)

        if blacklist:
            # Remove blacklisted drivers.
            remaining = []
            for t in orderedtypes:
                if t not in blacklist:
                    remaining.append (t)

            orderedtypes = remaining

        return orderedtypes


def test (xml_path=None, attached=False, deviceid=None, debug=False):
    import cups
    import locale
    import ppds
    from pprint import pprint
    from time import time
    import os.path

    if debug:
        def debugprint (x):
            print x

        ppds.set_debugprint_fn (debugprint)
            
    locale.setlocale (locale.LC_ALL, "")
    encoding = locale.getlocale (locale.LC_CTYPE)[1]
    if xml_path == None:
        xml_path = os.path.join (os.path.join (os.path.dirname (__file__),
                                               ".."),
                                 "xml")

    os.environ["CUPSHELPERS_XMLDIR"] = xml_path
    xml_path = os.path.join (xml_path, "preferreddrivers.xml")
    loadstart = time ()
    (xmldrivertypes, xmlpreferenceorder) = PreferredDrivers (xml_path)
    drivertypes = DriverTypes ()
    drivertypes.load (xmldrivertypes)

    preforder = PreferenceOrder ()
    preforder.load (xmlpreferenceorder)
    loadtime = time () - loadstart
    if debug:
        print "Time to load %s: %.3fs" % (xml_path, loadtime)

    c = cups.Connection ()
    try:
        cupsppds = c.getPPDs2 ()
    except AttributeError:
        # getPPDs2 requires pycups >= 1.9.52 
        cupsppds = c.getPPDs ()

    ppdfinder = ppds.PPDs (cupsppds)

    if attached or deviceid:
        if attached:
            cups.setUser ("root")
            devices = c.getDevices ()
        else:
            devid = parseDeviceID (deviceid)
            devices = { "xxx://yyy":
                            { "device-id": deviceid,
                              "device-make-and-model": "%s %s" % (devid["MFG"],
                                                                  devid["MDL"])
                              }
                        }

        for uri, device in devices.iteritems ():
            if uri.find (":") == -1:
                continue

            devid = device.get ("device-id", "")
            if isinstance (devid, list):
                devid = devid[0]

            if not devid:
                continue

            if not uri.startswith ("xxx:"):
                print uri

            id_dict = parseDeviceID (devid)
            fit = ppdfinder.getPPDNamesFromDeviceID (id_dict["MFG"],
                                                     id_dict["MDL"],
                                                     id_dict["DES"],
                                                     id_dict["CMD"],
                                                     uri)

            mm = device.get ("device-make-and-model", "")
            orderedtypes = preforder.get_ordered_types (drivertypes,
                                                        mm, id_dict)

            ppds = {}
            for ppdname in fit.keys ():
                ppds[ppdname] = ppdfinder.getInfoFromPPDName (ppdname)

            orderedppds = drivertypes.get_ordered_ppdnames (orderedtypes,
                                                            ppds,
                                                            fit)
            i = 1
            for t, ppd in orderedppds:
                print "%d  %s\n    (%s, %s)" % (i, ppd, t, fit[ppd])
                i += 1
    else:
        for make in ppdfinder.getMakes ():
            for model in ppdfinder.getModels (make):
                ppdsdict = ppdfinder.getInfoFromModel (make, model)
                mm = make + " " + model
                orderedtypes = preforder.get_ordered_types (drivertypes,
                                                            mm, None)

                fit = {}
                for ppdname in ppdsdict.keys ():
                    fit[ppdname] = DriverType.FIT_CLOSE

                orderedppds = drivertypes.get_ordered_ppdnames (orderedtypes,
                                                                ppdsdict, fit)
                print mm.encode (encoding) + ":"
                i = 1
                for t, ppd in orderedppds:
                    print "%d  %s\n    (%s)" % (i, ppd, t)
                    i += 1

                print

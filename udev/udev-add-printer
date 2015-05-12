#!/usr/bin/python3 -sB

## udev-add-printer

## Copyright (C) 2009, 2010, 2014, 2015 Red Hat, Inc.
## Author: Tim Waugh <twaugh@redhat.com>

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

import cups
import cupshelpers
import dbus
import os
import sys
import traceback
from syslog import *
from functools import reduce

MFG_BLACKLIST=[
    "graphtec",
    ]

def create_queue (c, printers, name, device_uri, ppdname, info, installer):
    # Make sure the name is unique.
    namel = str (name.lower ())
    unique = False
    suffix = 1
    while not unique:
        unique = True
        for printer in list(printers.values ()):
            if (not printer.discovered and
                ((suffix == 1 and printer.name.lower () == namel) or
                 (suffix > 1 and
                  printer.name.lower () == namel + "-" + str (suffix)))):
                unique = False
                break

        if not unique:
            suffix += 1
            if suffix == 100:
                break

    if suffix > 1:
        name += "-" + str (suffix)

    c.addPrinter (name,
                  device=device_uri,
                  ppdname=ppdname,
                  info=info,
                  location=os.uname ()[1])

    if not installer:
        # There is no session applet running to deal with installing
        # drivers so there is a good chance that this queue won't work
        # right now.  If that's the case, delete it.  The user can
        # reconnect the printer when they log in, and everything will
        # be set up correctly for them at that point.
        try:
            ppdfile = c.getPPD (name)
            ppd = cups.PPD (ppdfile)
            os.unlink (ppdfile)

            (pkgs, exes) = cupshelpers.missingPackagesAndExecutables (ppd)
            if pkgs or exes:
                # There are filters missing.  Delete the queue.
                syslog (LOG_ERROR, "PPD %s requires %s" % (ppdname,
                                                           repr ((pkgs, exes))))
                syslog (LOG_ERROR, "Deleting non-functional queue")
                c.deletePrinter (name)
                name = None
        except cups.IPPError:
            pass
        except RuntimeError:
            pass

    if name:
        cupshelpers.activateNewPrinter (c, name)

    return name

def add_queue (device_id, device_uris, fax_basename=False):
    """
    Create a CUPS queue.

    device_id: the IEEE 1284 Device ID of the device to add a queue for.
    device_uris: device URIs, best first, for this device
    fax_basename: False if this is not a fax queue, else name prefix
    """

    id_dict = cupshelpers.parseDeviceID (device_id)
    if id_dict["MFG"].lower () in MFG_BLACKLIST:
        syslog (LOG_DEBUG, "Ignoring blacklisted manufacturer %s", id_dict["MFG"])
        return

    syslog (LOG_DEBUG, "add_queue: URIs=%s" % device_uris)
    installer = None
    if fax_basename != False:
        notification = None
    else:
        try:
            bus = dbus.SystemBus ()
            obj = bus.get_object ("com.redhat.NewPrinterNotification",
                                  "/com/redhat/NewPrinterNotification")
            notification = dbus.Interface (obj,
                                           "com.redhat.NewPrinterNotification")
            notification.GetReady ()
        except dbus.DBusException as e:
            syslog (LOG_DEBUG, "D-Bus method call failed: %s" % e)
            notification = None

        try:
            obj = bus.get_object ("com.redhat.PrinterDriversInstaller",
                                  "/com/redhat/PrinterDriversInstaller")
            installer = dbus.Interface (obj,
                                        "com.redhat.PrinterDriversInstaller")
        except dbus.DBusException as e:
            #syslog (LOG_DEBUG, "Failed to get D-Bus object for "
            #        "PrinterDriversInstaller: %s" % e)
            pass

    id_dict = cupshelpers.parseDeviceID (device_id)
    if installer:
        cmd = id_dict["CMD"]
        if cmd:
            cmd = reduce (lambda x, y: x + ',' + y, cmd)
        else:
            cmd = ""

        try:
            installer.InstallDrivers (id_dict["MFG"], id_dict["MDL"], cmd,
                                      timeout=3600)
        except dbus.DBusException as e:
            syslog (LOG_DEBUG, "Failed to install drivers: %s" % repr (e))

    c = cups.Connection ()
    ppds = cupshelpers.ppds.PPDs (c.getPPDs ())
    (status, ppdname) = ppds.getPPDNameFromDeviceID (id_dict["MFG"],
                                                     id_dict["MDL"],
                                                     id_dict["DES"],
                                                     id_dict["CMD"],
                                                     device_uris[0])
    syslog (LOG_DEBUG, "PPD: %s; Status: %d" % (ppdname, status))

    if status == 0:
        # Think of a name for it.
        name = id_dict["MDL"]
        name = name.replace (" ", "-")
        name = name.replace ("/", "-")
        name = name.replace ("#", "-")

        if fax_basename != False:
            name = fax_basename + "-" + name

        printers = cupshelpers.getPrinters (c)
        uniquename = create_queue (c, printers, name, device_uris[0], ppdname,
                                   "%s %s" % (id_dict["MFG"], id_dict["MDL"]),
                                   installer)

        if uniquename != None and fax_basename == False:
            # Look for a corresponding fax queue.  We can only
            # identify these by looking for device URIs that are the
            # same as this one but with a different scheme.  If we
            # find one whose scheme ends in "fax", use that as a fax
            # queue.  Note that the HPLIP backends do follow this
            # pattern (hp and hpfax).
            used_uris = [x.device_uri for x in list(printers.values ())]
            for uri in device_uris[1:]:
                if uri.find (":") == -1:
                    continue

                (scheme, rest) = uri.split (":", 1)
                if scheme.endswith ("fax"):
                    # Now see if the non-scheme parts of the URI match
                    # any of the URIs we were given.
                    for each_uri in device_uris:
                        if each_uri == uri:
                            continue
                        (s, device_uri_rest) = each_uri.split (":", 1)
                        if rest == device_uri_rest:
                            # This one matches.  Check there is not
                            # already a queue using this URI.
                            if uri in used_uris:
                                break

                            try:
                                devices = c.getDevices(include_schemes=[scheme])
                            except TypeError:
                                # include_schemes requires pycups 1.9.46
                                devices = c.getDevices ()

                            device_dict = devices.get (uri)
                            if device_dict == None:
                                break

                            add_queue (device_dict.get ("device-id", ""),
                                       [uri], fax_basename=uniquename)
    else:
        # Not an exact match.
        uniquename = device_uris[0]

    if uniquename != None and notification:
        try:
            cmd = id_dict["CMD"]
            if cmd:
                cmd = reduce (lambda x, y: x + ',' + y, cmd)
            else:
                cmd = ""

            notification.NewPrinter (status, uniquename, id_dict["MFG"],
                                     id_dict["MDL"], id_dict["DES"], cmd)
        except dbus.DBusException as e:
            syslog (LOG_DEBUG, "D-Bus method call failed: %s" % e)

if len (sys.argv) < 3:
   print("Syntax: %s {Device ID} {Device URI} [other device URIs...]")
   sys.exit (1)

openlog ("udev-add-printer", 0, LOG_LPR)
try:
    add_queue (sys.argv[1], sys.argv[2:])
except SystemExit as e:
    sys.exit (e)
except:
    (type, value, tb) = sys.exc_info ()
    tblast = traceback.extract_tb (tb, limit=None)
    if len (tblast):
        tblast = tblast[:len (tblast) - 1]
    for line in traceback.format_tb (tb):
        syslog (LOG_ERR, line.strip ())
    extxt = traceback.format_exception_only (type, value)
    syslog (LOG_ERR, extxt[0].strip ())

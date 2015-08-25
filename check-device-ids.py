#!/usr/bin/python3

## check-device-ids

## Copyright (C) 2010, 2011, 2012, 2013 Red Hat, Inc.
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

import dbus
import cups
import cupshelpers
from cupshelpers.ppds import PPDs, ppdMakeModelSplit
import sys
from functools import reduce

c = cups.Connection ()

devices = None
if len (sys.argv) > 1 and sys.argv[1] == '--help':
    print("Syntax: check-device-ids <device-make-and-model> <device-id>")
    print("    or: check-device-ids <device-uri>")
    print("    or: check-device-ids <queue-name>")
    print("    or: check-device-ids")
    sys.exit (1)

SPECIFIC_URI = None
if len (sys.argv) == 3:
    id_dict = cupshelpers.parseDeviceID (sys.argv[2])
    if id_dict.get ("MFG") and id_dict.get ("MDL"):
        devices = { 'user-specified:':
                        { 'device-make-and-model': sys.argv[1],
                          'device-id': sys.argv[2] }
                    }
elif len (sys.argv) == 2:
    if sys.argv[1].find (":/") != -1:
        SPECIFIC_URI = sys.argv[1]
    else:
        # This is a queue name.  Work out the URI from that.
        try:
            attrs = c.getPrinterAttributes (sys.argv[1])
        except cups.IPPError as e:
            (e, m) = e.args
            print("Error getting printer attibutes: %s" % m)
            sys.exit (1)

        SPECIFIC_URI = attrs['device-uri']
        print("URI for queue %s is %s" % (sys.argv[1], SPECIFIC_URI))
else:
    print ("\nIf you have not already done so, you may get more results\n"
           "by temporarily disabling your firewall (or by allowing\n"
           "incoming UDP packets on port 161).\n")

if devices is None:
    if not SPECIFIC_URI:
        print("Examining connected devices")

    cups.setUser ('root')
    c = cups.Connection ()

    try:
        if SPECIFIC_URI:
            scheme = str (SPECIFIC_URI.split (":", 1)[0])
            devices = c.getDevices (include_schemes=[scheme])
        else:
            devices = c.getDevices (exclude_schemes=["dnssd", "hal", "hpfax"])
    except cups.IPPError as e:
        (e, m) = e.args
        if e == cups.IPP_FORBIDDEN:
            print("Run this as root to examine IDs from attached devices.")
            sys.exit (1)
        if e in (cups.IPP_NOT_AUTHORIZED, cups.IPP_AUTHENTICATION_CANCELED):
            print("Not authorized.")
            sys.exit (1)

if SPECIFIC_URI:
    if devices.get (SPECIFIC_URI) is None:
        devices = { SPECIFIC_URI:
                        { 'device-make-and-model': '',
                          'device-id': ''} }
if len (devices) == 0:
    print("No attached devices.")
    sys.exit (0)

n = 0
device_ids = []
for device, attrs in devices.items ():
    if device.find (":") == -1:
        continue

    if SPECIFIC_URI and device != SPECIFIC_URI:
        continue

    make_and_model = attrs.get ('device-make-and-model')
    device_id = attrs.get ('device-id')
    if (SPECIFIC_URI or make_and_model) and not device_id:
        try:
            hostname = None
            if (device.startswith ("socket://") or
                device.startswith ("lpd://") or
                device.startswith ("ipp://") or
                device.startswith ("http://") or
                device.startswith ("https://")):
                hostname = device[device.find ("://") + 3:]
                colon = hostname.find (":")
                if colon != -1:
                    hostname = hostname[:colon]

            if hostname:
                devs = []

                def got_device (dev):
                    if dev is not None:
                        devs.append (dev)

                import probe_printer
                pf = probe_printer.PrinterFinder ()
                pf.hostname = hostname
                pf.callback_fn = got_device
                pf._cached_attributes = dict()
                print("Sending SNMP request to %s for device-id" % hostname)
                pf._probe_snmp ()

                for dev in devs:
                    if dev.id:
                        device_id = dev.id
                        attrs.update ({'device-id': dev.id})

                    if not make_and_model and dev.make_and_model:
                        make_and_model = dev.make_and_model
                        attrs.update ({'device-make-and-model':
                                           dev.make_and_model})

        except Exception as e:
            print("Exception: %s" % repr (e))

    if not (make_and_model and device_id):
        print("Skipping %s, insufficient data" % device)
        continue

    id_fields = cupshelpers.parseDeviceID (device_id)
    this_id = "MFG:%s;MDL:%s;" % (id_fields['MFG'], id_fields['MDL'])
    device_ids.append (this_id)
    n += 1

if not device_ids:
    print("No Device IDs available.")
    sys.exit (0)

try:
    bus = dbus.SessionBus ()

    print("Installing relevant drivers using session service")
    try:
        obj = bus.get_object ("org.freedesktop.PackageKit",
                              "/org/freedesktop/PackageKit")
        proxy = dbus.Interface (obj, "org.freedesktop.PackageKit.Modify")
        proxy.InstallPrinterDrivers (0, device_ids,
                                     "hide-finished", timeout=3600)
    except dbus.exceptions.DBusException as e:
        print("Ignoring exception: %s" % e)
except dbus.exceptions.DBusException:
    try:
        bus = dbus.SystemBus ()

        print("Installing relevant drivers using system service")
        try:
            obj = bus.get_object ("com.redhat.PrinterDriversInstaller",
                                  "/com/redhat/PrinterDriversInstaller")
            proxy = dbus.Interface (obj,
                                    "com.redhat.PrinterDriversInstaller")
            for device_id in device_ids:
                id_dict = cupshelpers.parseDeviceID (device_id)
                proxy.InstallDrivers (id_dict['MFG'], id_dict['MDL'], '',
                                      timeout=3600)
        except dbus.exceptions.DBusException as e:
            print("Ignoring exception: %s" % e)
    except dbus.exceptions.DBusException:
        print("D-Bus not available so skipping package installation")


print("Fetching driver list")
ppds = PPDs (c.getPPDs ())
ppds._init_ids ()
makes = ppds.getMakes ()

def driver_uri_to_filename (uri):
    schemeparts = uri.split (':', 2)
    if len (schemeparts) < 2:
        if uri.startswith ("lsb/usr/"):
            return "/usr/share/ppd/" + uri[8:]
        elif uri.startswith ("lsb/opt/"):
            return "/opt/share/ppd/" + uri[8:]
        elif uri.startswith ("lsb/local/"):
            return "/usr/local/share/ppd/" + uri[10:]

        return "/usr/share/cups/model/" + uri

    scheme = schemeparts[0]
    if scheme != "drv":
        return "/usr/lib/cups/driver/" + scheme

    rest = schemeparts[1]
    rest = rest.lstrip ('/')
    parts = rest.split ('/')
    if len (parts) > 1:
        parts = parts[:len (parts) - 1]

    return "/usr/share/cups/drv/" + reduce (lambda x, y: x + "/" + y, parts)

def driver_uri_to_pkg (uri):
    filename = driver_uri_to_filename (uri)

    try:
        import packagekit.client, packagekit.enums
        client = packagekit.client.PackageKitClient ()
        packages = client.search_file ([filename],
                                       packagekit.enums.FILTER_INSTALLED)
        return packages[0].name
    except:
        return filename

i = 1
if sys.stdout.encoding == 'UTF-8':
    item = chr (0x251c) + chr (0x2500) + chr (0x2500)
    last = chr (0x2514) + chr (0x2500) + chr (0x2500)
else:
    item = "|--"
    last = "`--"

for device, attrs in devices.items ():
    make_and_model = attrs.get ('device-make-and-model')
    device_id = attrs.get ('device-id')
    if device.find (":") == -1:
        continue

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

    scheme = device.split (":", 1)[0]
    print("%s %s (%s): MFG:%s;MDL:%s;%s" % (line, make_and_model,
                                            scheme,
                                            id_fields['MFG'],
                                            id_fields['MDL'],
                                            cmd))
    
    try:
        drivers = ppds.ids[id_fields['MFG'].lower ()][id_fields['MDL'].lower ()]
    except KeyError:
        drivers = []

    if i < n:
        more = chr (0x2502)
    else:
        more = " "

    if drivers:
        drivers = ppds.orderPPDNamesByPreference (drivers)
        n_drivers = len (drivers)
        j = 1
        for driver in drivers:
            if j < n_drivers:
                print("%s   %s %s [%s]" % (more, item, driver,
                                           driver_uri_to_pkg (driver)))
            else:
                print("%s   %s %s [%s]" % (more, last, driver,
                                           driver_uri_to_pkg (driver)))

            j += 1
    else:
        print("%s   (No drivers)" % more)

    (mfr, mdl) = ppdMakeModelSplit (make_and_model)
    matches = set (ppds.getInfoFromModel (mfr, mdl))
    mfrl = mfr.lower ()
    mdls = None
    for make in makes:
        if make.lower () == mfrl:
            mdls = ppds.makes[make]
            break
    if mdls:
        (s, bestmatches) = ppds._findBestMatchPPDs (mdls, mdl)
        if s == ppds.FIT_EXACT:
            matches = matches.union (set (bestmatches))

    missing = set (matches) - set (drivers)
    for each in missing:
        try:
            ppd_device_id = ppds.getInfoFromPPDName (each).get ('ppd-device-id')
        except Exception as e:
            print(e)
            ppd_device_id = None

        if ppd_device_id:
            ppd_id_fields = cupshelpers.parseDeviceID (ppd_device_id)
        else:
            ppd_id_fields = {}

        if ppd_id_fields.get ("MFG") and ppd_id_fields.get ("MDL"):
            print("%s       WRONG    %s [%s]" % (more, each,
                                                 driver_uri_to_pkg (each)))
            for field in ["MFG", "MDL"]:
                value = id_fields[field]
                ppd_value = ppd_id_fields[field]
                if value.lower () != ppd_value.lower ():
                    print("%s                      %s:%s;" % (more, field, ppd_value))
                    print("%s                should be:%s;" % (more, value))
        else:
            print("%s       MISSING  %s [%s]" % (more, each,
                                                 driver_uri_to_pkg (each)))

    i += 1

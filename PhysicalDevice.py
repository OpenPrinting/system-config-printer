#!/usr/bin/python

## Copyright (C) 2008, 2009, 2010, 2012 Red Hat, Inc.
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

import config
import gettext
gettext.install(domain=config.PACKAGE, localedir=config.localedir, unicode=True)
import cupshelpers
import urllib

import ppdippstr

class PhysicalDevice:
    def __init__(self, device):
        self.devices = None
        self._network_host = None
        self.dnssd_hostname = None
        self._cupsserver = False
        self.add_device (device)
        self._user_data = {}
        self._ppdippstr = ppdippstr.backends

    def _canonical_id (self, device):
        if hasattr (device, "id_dict"):
            mfg = device.id_dict.get ('MFG', '')
            mdl = device.id_dict.get ('MDL', '')

            if mfg == '' or mdl.lower ().startswith (mfg.lower ()):
                make_and_model = mdl
            else:
                make_and_model = "%s %s" % (mfg, mdl)
        else:
             make_and_model = device.make_and_model

        return cupshelpers.ppds.ppdMakeModelSplit (make_and_model)

    def _get_host_from_uri (self, uri):
        hostport = None
        host = None
        dnssdhost = None
        (scheme, rest) = urllib.splittype (uri)
        if scheme == 'hp' or scheme == 'hpfax':
            if rest.startswith ("/net/"):
                (rest, ipparam) = urllib.splitquery (rest[5:])
                if ipparam != None and ipparam.startswith("ip="):
                    hostport = ipparam[3:]
                else:
                    if ipparam != None and ipparam.startswith("zc="):
                        dnssdhost = ipparam[3:]
                    else:
                        return None, None
            else:
                return None, None
        elif scheme == 'dnssd' or scheme == 'mdns':
            # The URIs of the CUPS "dnssd" backend do not contain the host
            # name of the printer
            return None, None
        else:
            (hostport, rest) = urllib.splithost (rest)
            if hostport == None:
                return None, None

        if hostport:
            (host, port) = urllib.splitport (hostport)

        if type (host) == unicode:
            host = host.encode ('utf-8')
        if type (dnssdhost) == unicode:
            dnssdhost = dnssdhost.encode ('utf-8')
        return host, dnssdhost

    def add_device (self, device):
        if self._network_host or self.dnssd_hostname:
            host, dnssdhost = self._get_host_from_uri (device.uri)
            if (hasattr (device, 'address')):
                host = device.address
            if (hasattr (device, 'hostname') and dnssdhost == None):
                dnssdhost = device.hostname
            if (host == None and dnssdhost == None) or \
               (host and self._network_host and \
                host != self._network_host) or \
               (dnssdhost and self.dnssd_hostname and \
                dnssdhost != self.dnssd_hostname) or \
               (host == None and self.dnssd_hostname == None) or \
               (dnssdhost == None and self._network_host == None):
                raise ValueError
        else:
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
                if sn != '' and self.sn != '' and sn != self.sn:
                    raise ValueError

        if device.type == "socket":
            # Remove default port to more easily find duplicate URIs
            device.uri = device.uri.replace (":9100", "")
        if (device.uri.startswith('ipp:') and \
            device.uri.find('/printers/') != -1) or \
           ((device.uri.startswith('dnssd:') or \
             device.uri.startswith('mdns:')) and \
            device.uri.endswith('/cups')):
            # CUPS server
            self._cupsserver = True
        elif self._cupsserver:
            # Non-CUPS queue on a CUPS server, drop this one
            return
        for d in self.devices:
            if d.uri == device.uri:
                return

        self.devices.append (device)
        self.devices.sort ()

        if (not self._network_host or not self.dnssd_hostname) and \
           device.device_class == "network":
            # We just added a network device.
            self._network_host, dnssdhost = \
                self._get_host_from_uri (device.uri)
            if dnssdhost:
                self.dnssd_hostname = dnssdhost;

        if (hasattr (device, 'address') and self._network_host == None):
            if device.address:
                self._network_host = device.address
        if (hasattr (device, 'hostname') and self.dnssd_hostname == None):
            if device.hostname:
                self.dnssd_hostname = device.hostname

    def get_devices (self):
        return self.devices

    def get_info (self):
        # If the manufacturer/model is not known, or useless (in the
        # case of the hpfax backend or a dnssd URI pointing to a remote
        # CUPS queue), show the device-info field instead.
        if (self.devices[0].uri.startswith('ipp:') and \
            self.devices[0].uri.find('/printers/') != -1) or \
           ((self.devices[0].uri.startswith('dnssd:') or \
             self.devices[0].uri.startswith('mdns:')) and \
            self.devices[0].uri.endswith('/cups')):
            if not self.dnssd_hostname:
                info = "%s" % self._network_host
            elif not self._network_host or self._network_host.find(":") != -1:
                info = "%s" % self.dnssd_hostname
            else:
                if self._network_host != self.dnssd_hostname:
                    info = "%s (%s)" % (self.dnssd_hostname, self._network_host)
                else:
                    info = "%s" % self._network_host
        elif self.mfg == '' or \
           (self.mfg == "HP" and self.mdl.startswith("Fax")):
            info = self._ppdippstr.get (self.devices[0].info)
        else:
            info = "%s %s" % (self.mfg, self.mdl)
        if ((self._network_host and len (self._network_host) > 0) or \
            (self.dnssd_hostname and len (self.dnssd_hostname) > 0)) and not \
            ((self.devices[0].uri.startswith('dnssd:') or \
              self.devices[0].uri.startswith('mdns:')) and \
              self.devices[0].uri.endswith('/cups')) and \
            (not self._network_host or \
             info.find(self._network_host) == -1) and \
            (not self.dnssd_hostname or \
             info.find(self.dnssd_hostname) == -1):
            if not self.dnssd_hostname:
                info += " (%s)" % self._network_host
            elif not self._network_host:
                info += " (%s)" % self.dnssd_hostname
            else:
                info += " (%s, %s)" % (self.dnssd_hostname, self._network_host)
        elif len (self.sn) > 0:
            info += " (%s)" % self.sn
        return info

    # User data
    def set_data (self, key, value):
        self._user_data[key] = value

    def get_data (self, key):
        return self._user_data.get (key)

    def __str__ (self):
        return "(description: %s)" % self.__repr__ ()

    def __repr__ (self):
        return "<PhysicalDevice.PhysicalDevice (%s,%s,%s)>" % (self.mfg,
                                                               self.mdl,
                                                               self.sn)

    def __cmp__(self, other):
        if other == None or type (other) != type (self):
            return 1

        if (self._network_host != None or
            other._network_host != None):
            return cmp (self._network_host, other._network_host)

        devs = other.get_devices()
        if devs:
            uris = map (lambda x: x.uri, self.devices)
            for dev in devs:
                if dev.uri in uris:
                    # URI match
                    return 0

        if (other.mfg == '' and other.mdl == '') or \
           (self.mfg == '' and self.mdl == ''):
            # One or other is just a backend, not a real physical device.
            if other.mfg == '' and other.mdl == '' and \
               self.mfg == '' and self.mdl == '':
                return cmp (self.devices[0], other.devices[0])

            if other.mfg == '' and other.mdl == '':
                return -1
            return 1

        if self.mfg == '' or self.mdl.lower ().startswith (self.mfg.lower ()):
            our_make_and_model = self.mdl
        else:
            our_make_and_model = "%s %s" % (self.mfg, self.mdl)
        (our_mfg, our_mdl) = \
            cupshelpers.ppds.ppdMakeModelSplit (our_make_and_model)

        if other.mfg == '' or \
                other.mdl.lower ().startswith (other.mfg.lower ()):
            other_make_and_model = other.mdl
        else:
            other_make_and_model = "%s %s" % (other.mfg, other.mdl)
        (other_mfg, other_mdl) = \
            cupshelpers.ppds.ppdMakeModelSplit (other_make_and_model)

        mfgcmp = cmp (our_mfg.lower (), other_mfg.lower ())
        if mfgcmp != 0:
            return mfgcmp
        mdlcmp = cmp (our_mdl.lower (), other_mdl.lower ())
        if mdlcmp != 0:
            return mdlcmp
        if self.sn == '' or other.sn == '':
            return 0
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

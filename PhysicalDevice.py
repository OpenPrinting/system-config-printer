#!/usr/bin/python3

## Copyright (C) 2008, 2009, 2010, 2012, 2014 Red Hat, Inc.
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
gettext.install(domain=config.PACKAGE, localedir=config.localedir)
import cupshelpers
import urllib.parse
import ppdippstr
import socket
from debug import *

class PhysicalDevice:
    def __init__(self, device):
        self.devices = None
        self._network_host = None
        self.dnssd_hostname = None
        self._cupsserver = False
        self.firsturi = None
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

    def _add_dot_local_if_needed(self, hostname):
        if (hostname is None):
            return None
        if ((not '.' in hostname) and (not ':' in hostname) and
            (hostname != 'localhost')):
            return hostname + '.local'
        else:
            return hostname

    def _get_address (self, hostname):
        try:
            address = socket.getaddrinfo(hostname, 0,
                                         family=socket.AF_INET)[0][4][0]
        except:
            try:
                address = socket.getaddrinfo(hostname, 0,
                                             family=socket.AF_INET6)[0][4][0]
            except:
                address = None
        return address

    def _get_host_from_uri (self, uri):
        hostport = None
        host = None
        dnssdhost = None
        (scheme, rest) = urllib.parse.splittype (uri)
        if scheme == 'hp' or scheme == 'hpfax':
            ipparam = None
            if rest.startswith ("/net/"):
                (rest, ipparam) = urllib.parse.splitquery (rest[5:])

            if ipparam is not None:
                if ipparam.startswith("ip="):
                    hostport = ipparam[3:]
                elif ipparam.startswith ("hostname="):
                    hostport = ipparam[9:]
                elif ipparam.startswith("zc="):
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
            (hostport, rest) = urllib.parse.splithost (rest)
            if hostport is None:
                return None, None

        if hostport:
            (host, port) = urllib.parse.splitport (hostport)

        if (host):
            ip = None
            try:
                ip = self._get_address(host)
                if ip:
                    host = ip
            except:
                pass
        elif (dnssdhost):
            try:
                host = self._get_address(dnssdhost)
            except:
                host = None

        return self._add_dot_local_if_needed(host), \
            self._add_dot_local_if_needed(dnssdhost)

    def add_device (self, device):
        if self._network_host or self.dnssd_hostname:
            host, dnssdhost = self._get_host_from_uri (device.uri)
            if (hasattr (device, 'address')):
                host = self._add_dot_local_if_needed(device.address)
            if (hasattr (device, 'hostname') and dnssdhost is None):
                dnssdhost = self._add_dot_local_if_needed(device.hostname)
            if (host is None and dnssdhost is None) or \
               not ((host and self._network_host and
                     host == self._network_host) or
                    (host and self.dnssd_hostname and
                     host == self.dnssd_hostname) or
                    (dnssdhost and self._network_host and
                     dnssdhost == self._network_host) or
                    (dnssdhost and self.dnssd_hostname and
                     dnssdhost == self.dnssd_hostname)) or \
               (host is None and self.dnssd_hostname is None) or \
               (dnssdhost is None and self._network_host is None):
                raise ValueError
        else:
            (mfg, mdl) = self._canonical_id (device)
            if self.devices is None:
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
                        for i in range (len (s)):
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

        # Use the URI of the very first device added as a kind of identifier
        # for this physical device record, to make debugging easier
        if not self.firsturi:
            self.firsturi = device.uri;

        self.devices.append (device)
        self.devices.sort ()

        if (not self._network_host or not self.dnssd_hostname) and \
           device.device_class == "network":
            # We just added a network device.
            self._network_host, dnssdhost = \
                self._get_host_from_uri (device.uri)
            if dnssdhost:
                self.dnssd_hostname = dnssdhost;

        if (hasattr (device, 'address') and self._network_host is None):
            address = device.address
            if address:
                self._network_host = self._add_dot_local_if_needed(address)

        if (hasattr (device, 'hostname') and self.dnssd_hostname is None):
            hostname = device.hostname
            if hostname:
                self.dnssd_hostname = self._add_dot_local_if_needed(hostname)

        if (self.dnssd_hostname and self._network_host is None):
            try:
                self._network_host = self._get_address(hostname);
            except:
                self._network_host = None

        debugprint("Device %s added to physical device: %s" %
                   (device.uri, repr(self)))

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
        return ("<PhysicalDevice.PhysicalDevice (%s,%s,%s,%s,%s,%s)>" %
                (self.mfg, self.mdl, self.sn, self._network_host,
                 self.dnssd_hostname, self.firsturi))

    def __eq__(self, other):
        if type (other) != type (self):
            return False

        if not (((not self._network_host or len (self._network_host) == 0) and
                 (not other._network_host or len (other._network_host) == 0) and
                 (not self.dnssd_hostname or len (self.dnssd_hostname) == 0) and
                 (not other.dnssd_hostname or
                  len (other.dnssd_hostname) == 0)) or
                (self._network_host and len (self._network_host) > 0 and
                 other._network_host and len (other._network_host) > 0 and
                 self._network_host == other._network_host) or
                (self.dnssd_hostname and len (self.dnssd_hostname) > 0 and
                 other.dnssd_hostname and len (other.dnssd_hostname) > 0 and
                 self.dnssd_hostname == other.dnssd_hostname) or
                (self._network_host and len (self._network_host) > 0 and
                 other.dnssd_hostname and len (other.dnssd_hostname) > 0 and
                 self._network_host == other.dnssd_hostname) or
                (self.dnssd_hostname and len (self.dnssd_hostname) > 0 and
                 other._network_host and len (other._network_host) > 0 and
                 self.dnssd_hostname == other._network_host)):
            return False

        devs = other.get_devices()
        if devs:
            uris = [x.uri for x in self.devices]
            for dev in devs:
                if dev.uri in uris:
                    # URI match
                    return True

        if ((other.mfg == '' and other.mdl == '') or
            (self.mfg == ''  and self.mdl == '')):
            if other.mfg == '' and self.mfg == '':
                # Both just a backend, not a real physical device.
                return self.devices[0] == other.devices[0]

            # One or other is just a backend, not a real physical device.
            return False

        def split_make_and_model (dev):
            if dev.mfg == '' or dev.mdl.lower ().startswith (dev.mfg.lower ()):
                make_and_model = dev.mdl
            else:
                make_and_model = "%s %s" % (dev.mfg, dev.mdl)
            (mfg, mdl) = cupshelpers.ppds.ppdMakeModelSplit (make_and_model)
            return (cupshelpers.ppds.normalize (mfg),
                    cupshelpers.ppds.normalize (mdl))

        (our_mfg, our_mdl) = split_make_and_model (self)
        (other_mfg, other_mdl) = split_make_and_model (other)

        if our_mfg != other_mfg:
            return False

        if our_mfg == "hp" and self.sn != '' and self.sn == other.sn:
            return True

        if our_mdl != other_mdl:
            return False

        if self.sn == '' or other.sn == '':
            return True

        return self.sn == other.sn

    def __lt__(self, other):
        if type (other) != type (self):
            return False

        if self == other:
            return False;

        if self._network_host != other._network_host:
            if self._network_host is None:
                return True

            if other._network_host is None:
                return False

            return self._network_host < other._network_host

        if self.dnssd_hostname != other.dnssd_hostname:
            if self.dnssd_hostname is None:
                return True

            if other.dnssd_hostname is None:
                return False

            return self.dnssd_hostname < other.dnssd_hostname

        devs = other.get_devices()
        if devs:
            uris = [x.uri for x in self.devices]
            for dev in devs:
                if dev.uri in uris:
                    # URI match, so compare equal. Not less than.
                    return False

        if ((other.mfg == '' and other.mdl == '') or
            (self.mfg == ''  and self.mdl == '')):
            if other.mfg == '' and self.mfg == '':
                # Both just a backend, not a real physical device.
                return self.devices[0] < other.devices[0]

            # One or other is just a backend, not a real physical device.
            return other.mfg == '' and other.mdl == ''

        def split_make_and_model (dev):
            if dev.mfg == '' or dev.mdl.lower ().startswith (dev.mfg.lower ()):
                make_and_model = dev.mdl
            else:
                make_and_model = "%s %s" % (dev.mfg, dev.mdl)
            (mfg, mdl) = cupshelpers.ppds.ppdMakeModelSplit (make_and_model)
            return (cupshelpers.ppds.normalize (mfg),
                    cupshelpers.ppds.normalize (mdl))

        (our_mfg, our_mdl) = split_make_and_model (self)
        (other_mfg, other_mdl) = split_make_and_model (other)

        if our_mfg != other_mfg:
            return our_mfg < other_mfg

        if our_mdl != other_mdl:
            return our_mdl < other_mdl

        if self.sn == '' or other.sn == '':
            return False

        return self.sn < other.sn

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
        print(physicaldevice.get_info ())
        devices = physicaldevice.get_devices ()
        for device in devices:
            print(" ", device)

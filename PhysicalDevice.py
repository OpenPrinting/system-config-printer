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
import ipaddress
from debug import *


class PhysicalDevice:
    def __init__(self, device):
        self.devices = None
        self._network_host = None
        self.dnssd_hostname = None
        self._dnssd_instance = None
        self._cupsserver = False
        self.firsturi = None
        self.add_device (device)
        self._user_data = {}
        self._ppdippstr = ppdippstr.backends

    @staticmethod
    def _protocol_from_uri(uri):
        """
        Determine the actual protocol from a printer URI by inspecting the scheme and DNS-SD service suffix.

        For dnssd:// URIs, the protocol is determined by the service type in the hostname:
        - _printer._tcp.local -> LPD
        - _pdl-datastream._tcp.local -> AppSocket (socket)
        - _ipp._tcp.local -> IPP
        - _ipps._tcp.local -> IPPS

        For explicit scheme URIs (ipp://, ipps://, lpd://, socket://), the scheme is used directly.

        Returns the canonical protocol scheme: 'ipp', 'ipps', 'lpd', or 'socket'.
        Returns None if the URI is not a recognized network printer URI.
        """
        if not uri:
            return None

        try:
            parsed = urllib.parse.urlsplit(uri)
            scheme = parsed.scheme.lower()
            netloc = parsed.netloc.lower()
        except ValueError:
            return None

        # Explicit protocol schemes - use directly
        if scheme in ('ipp', 'ipps', 'lpd', 'socket'):
            return scheme

        # DNS-SD scheme - inspect service type in hostname
        if scheme in ('dnssd', 'mdns'):
            # Extract service type from netloc (e.g., "Printer._ipp._tcp.local")
            # The service type is the part starting with _ and ending with _tcp.local or _udp.local
            parts = netloc.rsplit('.', 3)
            if len(parts) >= 4:
                # parts[-3] is the service type (e.g., "_ipp", "_pdl-datastream", "_printer")
                # parts[-2] is the protocol ("_tcp" or "_udp")
                # parts[-1] is the domain ("local")
                service_type = parts[-3]
                protocol = parts[-2]

                if protocol in ('_tcp', '_udp'):
                    if service_type == '_ipp':
                        return 'ipp'
                    elif service_type == '_ipps':
                        return 'ipps'
                    elif service_type == '_printer':
                        return 'lpd'
                    elif service_type == '_pdl-datastream':
                        return 'socket'

        return None

    @staticmethod
    def _canonical_uri(uri):
        """
        Convert a DNS-SD URI to its canonical explicit protocol form.

        For dnssd:// URIs, converts to the corresponding explicit protocol URI:
        - dnssd://Name._printer._tcp.local/?uuid=... -> lpd://Name._printer._tcp.local/
        - dnssd://Name._pdl-datastream._tcp.local/?uuid=... -> socket://Name._pdl-datastream._tcp.local/
        - dnssd://Name._ipp._tcp.local/?uuid=... -> ipp://Name._ipp._tcp.local/
        - dnssd://Name._ipps._tcp.local/?uuid=... -> ipps://Name._ipps._tcp.local/

        Strips UUID query parameters and normalizes the URI.

        Returns the canonical URI, or the original URI if not a recognized DNS-SD printer URI.
        """
        if not uri:
            return uri

        protocol = PhysicalDevice._protocol_from_uri(uri)
        if not protocol:
            return uri

        try:
            parsed = urllib.parse.urlsplit(uri)
            scheme = parsed.scheme.lower()
            netloc = parsed.netloc
        except ValueError:
            return uri

        path = parsed.path
        if path in ("", "/", "//"):
            path = "/"

        # For dnssd/mdns, reconstruct with canonical protocol scheme and no query/fragment
        if scheme in ("dnssd", "mdns"):
            return urllib.parse.urlunsplit((protocol, netloc, path, "", ""))

        # For explicit schemes, strip uuid from query if present, normalize path
        if parsed.query:
            params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
            filtered_params = [(k, v) for k, v in params if k.lower() != "uuid"]
            new_query = urllib.parse.urlencode(filtered_params)
        else:
            new_query = ""

        return urllib.parse.urlunsplit((protocol, netloc, path, new_query, parsed.fragment))

    def _canonical_id (self, device):
        make_and_model = ''
        if hasattr (device, "id_dict"):
            mfg = device.id_dict.get ('MFG', '')
            mdl = device.id_dict.get ('MDL', '')

            if mfg == '' or mdl.lower ().startswith (mfg.lower ()):
                make_and_model = mdl
            else:
                make_and_model = "%s %s" % (mfg, mdl)

        if not make_and_model:
            make_and_model = getattr (device, 'make_and_model', '') or getattr (device, 'info', '')

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

    @staticmethod
    def _is_literal_ip_uri (uri):
        if not uri:
            return False

        scheme = uri.split (':', 1)[0].lower ()
        if scheme in ('dnssd', 'mdns'):
            return False

        if scheme in ('hp', 'hpfax'):
            try:
                query = urllib.parse.urlsplit (uri).query
                params = urllib.parse.parse_qs (query)
                if 'ip' in params and params['ip']:
                    host = params['ip'][0]
                    if '%' in host:
                        host = host.split ('%')[0]
                    try:
                        ipaddress.ip_address (host)
                        return True
                    except ValueError:
                        return False
            except Exception:
                pass
            return False

        try:
            parsed = urllib.parse.urlsplit (uri)
            host = parsed.hostname
        except ValueError:
            return False

        if not host:
            return False

        if '%' in host:
            host = host.split ('%')[0]

        try:
            ipaddress.ip_address (host)
            return True
        except ValueError:
            return False

    def is_literal_ip (self):
        if not self.devices:
            return False
        return self._is_literal_ip_uri (self.devices[0].uri)

    @staticmethod
    def _dnssd_instance_from_uri (uri):
        if not uri:
            return None
        protocol = PhysicalDevice._protocol_from_uri (uri)
        if protocol in ('lpd', 'socket'):
            uri = PhysicalDevice._canonical_uri (uri)
        (scheme, rest) = urllib.parse.splittype (uri)
        if scheme == 'hp' or scheme == 'hpfax':
            if rest.startswith ("/net/"):
                (rest, ipparam) = urllib.parse.splitquery (rest[5:])
                if ipparam and ipparam.startswith ("zc="):
                    return ipparam[3:]
            return None
        (hostport, rest) = urllib.parse.splithost (rest)
        if not hostport:
            return None
        (host, port) = urllib.parse.splitport (hostport)
        if not host:
            return None
        return PhysicalDevice._extract_dnssd_instance (host)

    @staticmethod
    def _host_matches (h1, h2):
        if not h1 or not h2:
            return False
        if h1 == h2:
            return True
        s1 = h1[:-6] if h1.endswith('.local') else h1
        s2 = h2[:-6] if h2.endswith('.local') else h2
        if s1 == s2:
            return True
        if f'[{s1}]' in h2 or f'[{s2}]' in h1:
            return True
        return False

    @staticmethod
    def _extract_dnssd_instance (host):
        if not host:
            return None
            
        h = host.rstrip ('.')
        elements = h.rsplit ('.', 3)
        if len (elements) == 4:
            name, stype, protocol, domain = elements
            if (domain.lower () == 'local' and
                protocol.lower () in ('_tcp', '_udp') and
                stype.startswith ('_')):
                return urllib.parse.unquote (name)
        return None

    def _get_host_from_uri (self, uri):
        hostport = None
        host = None
        dnssdhost = None
        protocol = self._protocol_from_uri(uri)
        if protocol in ('lpd', 'socket'):
            uri = self._canonical_uri(uri)
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
                    return None, None, protocol
            else:
                return None, None, protocol
        else:
            (hostport, rest) = urllib.parse.splithost (rest)
            if hostport is None:
                return None, None, protocol

        if hostport:
            (host, port) = urllib.parse.splitport (hostport)

        if (host):
            if dnssdhost is None:
                instance = self._extract_dnssd_instance (host)
                if instance:
                    dnssdhost = instance
                    host = None

        return self._add_dot_local_if_needed(host), \
            self._add_dot_local_if_needed(dnssdhost), protocol

    def add_device (self, device):
        protocol = self._protocol_from_uri (device.uri)
        if protocol in ('lpd', 'socket'):
            canonical_uri = self._canonical_uri (device.uri)
            device.uri = canonical_uri
            device.type = protocol

        dnssd_instance = self._dnssd_instance_from_uri (device.uri)

        if self.devices is None:
            self._dnssd_instance = dnssd_instance
            (mfg, mdl) = self._canonical_id (device)
            self.mfg = mfg
            self.mdl = mdl
            self.mfg_lower = mfg.lower ()
            self.mdl_lower = mdl.lower ()
            self.sn = device.id_dict.get ('SN', '')
            self.devices = []
        else:
            if self.is_literal_ip () != self._is_literal_ip_uri (device.uri):
                raise ValueError

            if self._dnssd_instance and dnssd_instance:
                if self._dnssd_instance != dnssd_instance:
                    raise ValueError
            elif self._network_host or self.dnssd_hostname:
                host, dnssdhost, protocol = self._get_host_from_uri (device.uri)
                if (hasattr (device, 'address')):
                    host = self._add_dot_local_if_needed(device.address)
                if (hasattr (device, 'hostname') and dnssdhost is None):
                    dnssdhost = self._add_dot_local_if_needed(device.hostname)
                if (host is None and dnssdhost is None) or \
                   not (self._host_matches (host, self._network_host) or
                        self._host_matches (host, self.dnssd_hostname) or
                        self._host_matches (dnssdhost, self._network_host) or
                        self._host_matches (dnssdhost, self.dnssd_hostname)):
                    raise ValueError
            else:
                (mfg, mdl) = self._canonical_id (device)
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

            if dnssd_instance and not self._dnssd_instance:
                self._dnssd_instance = dnssd_instance

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
            if d.uri == device.uri or self._canonical_uri (d.uri) == self._canonical_uri (device.uri):
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
            self._network_host, dnssdhost, _ = \
                self._get_host_from_uri (device.uri)
            if hasattr (device, 'hostname') and device.hostname:
                self.dnssd_hostname = self._add_dot_local_if_needed (device.hostname)
                device.dnssd_hostname = self.dnssd_hostname
            elif dnssdhost:
                self.dnssd_hostname = dnssdhost
                device.dnssd_hostname = dnssdhost

        if hasattr (device, 'hostname') and device.hostname:
            self.dnssd_hostname = self._add_dot_local_if_needed (device.hostname)
        elif self.dnssd_hostname and not getattr (device, 'dnssd_hostname', None):
            device.dnssd_hostname = self.dnssd_hostname

        if (hasattr (device, 'address') and self._network_host is None):
            address = device.address
            if address:
                self._network_host = self._add_dot_local_if_needed(address)

        if (hasattr (device, 'hostname') and self.dnssd_hostname is None):
            hostname = device.hostname
            if hostname:
                self.dnssd_hostname = self._add_dot_local_if_needed(hostname)

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
            translated = self._ppdippstr.get (self.devices[0].info)
            info = translated or self.devices[0].info
        else:
            info = "%s %s" % (self.mfg, self.mdl)
        if self._network_host and not self.dnssd_hostname and not \
            ((self.devices[0].uri.startswith('dnssd:') or \
              self.devices[0].uri.startswith('mdns:')) and \
              self.devices[0].uri.endswith('/cups')) and \
            info.find(self._network_host) == -1:
            info += " (%s)" % self._network_host
        elif len (self.sn) > 0 and not (self._network_host or self.dnssd_hostname):
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

        if self.is_literal_ip () != other.is_literal_ip ():
            return False

        if self._dnssd_instance and other._dnssd_instance:
            if self._dnssd_instance != other._dnssd_instance:
                return False
        elif not (((not self._network_host or len (self._network_host) == 0) and
                   (not other._network_host or len (other._network_host) == 0) and
                   (not self.dnssd_hostname or len (self.dnssd_hostname) == 0) and
                   (not other.dnssd_hostname or
                    len (other.dnssd_hostname) == 0)) or
                  self._host_matches (self._network_host, other._network_host) or
                  self._host_matches (self.dnssd_hostname, other.dnssd_hostname) or
                  self._host_matches (self._network_host, other.dnssd_hostname) or
                  self._host_matches (self.dnssd_hostname, other._network_host)):
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

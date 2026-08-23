#!/usr/bin/python3

## Copyright (C) 2010, 2011, 2012, 2013, 2014 Red Hat, Inc.
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

import dbus, re
import urllib.parse
from debug import *


def _txt_value (txt, key):
    prefix = key + "="
    for value in txt:
        value = _txt_text (value)
        if value.startswith (prefix):
            return value[len (prefix):]
    return ''


def _txt_text (value):
    if isinstance (value, str):
        return value
    if isinstance (value, bytes):
        return value.decode ("utf-8", "replace")
    if isinstance (value, dbus.ByteArray):
        return bytes (value).decode ("utf-8", "replace")
    if isinstance (value, dbus.Array):
        try:
            return bytes (value).decode ("utf-8", "replace")
        except (TypeError, ValueError):
            return ''.join (_txt_text (item) for item in value)
    return str (value)


def _service_tuple_from_uri (uri):
    parsed = urllib.parse.urlparse (uri)
    if parsed.scheme == 'dnssd':
        hostname = parsed.netloc
    elif parsed.scheme in ('ipp', 'ipps') and \
         parsed.netloc.find ("._ipp._tcp.local") != -1:
        hostname = parsed.netloc
    else:
        return None

    elements = hostname.rsplit (".", 3)
    if len (elements) != 4:
        return None

    name, stype, protocol, domain = elements
    name = urllib.parse.unquote (name)
    stype += "." + protocol # e.g. _printer._tcp
    return (name, stype, domain)


def needs_service_resolution (uri):
    return _service_tuple_from_uri (uri) is not None


def _device_serial (device):
    if hasattr (device, 'id_dict'):
        return device.id_dict.get ('SN', '')
    if hasattr (device, 'sn'):
        return device.sn
    return ''


def is_ipp_over_usb_device (device):
    parsed = urllib.parse.urlparse (device.uri)
    return (parsed.scheme in ('ipp', 'ipps') and
            _service_tuple_from_uri (device.uri) is not None)


def _is_legacy_usb_device (device):
    return (getattr (device, 'device_class', '') == 'direct' and
            getattr (device, 'type', '') == 'usb')


def ipp_usb_serials (devices):
    devices = list (devices)
    serials = set ()
    for device in devices:
        if is_ipp_over_usb_device (device):
            serial = _device_serial (device)
            if serial != '':
                serials.add (serial)
    return serials


class LegacyUSBDeviceCache:
    """Track legacy USB device serials across sequential discovery batches."""

    def __init__ (self):
        self._usb_serials = set ()

    def note_devices (self, devices):
        for device in devices:
            if _is_legacy_usb_device (device):
                serial = _device_serial (device)
                if serial != '':
                    self._usb_serials.add (serial)

    def suppress(self, devices):
        devices = list(devices)

        ipp_serials = ipp_usb_serials(devices)

        if not ipp_serials:
            return devices

        filtered = []
        for device in devices:
            if (_is_legacy_usb_device(device) and
                _device_serial(device) in ipp_serials):
                continue

            filtered.append(device)

        return filtered

    def superseded_usb_serials (self, devices):
        """Return cached USB serials superseded by IPP-over-USB in devices."""
        return self._usb_serials & ipp_usb_serials (devices)


def suppress_legacy_usb_devices (devices, cache=None):
    devices = list (devices)
    if cache is None:
        cache = LegacyUSBDeviceCache ()
    cache.note_devices (devices)
    return cache.suppress (devices)

class DNSSDHostNamesResolver:
    def __init__ (self, devices):
        self._devices = devices
        self._unresolved = len (devices)
        self._device_uri_by_name = {}
        debugprint ("+%s" % self)

    def __del__ (self):
        debugprint ("-%s" % self)

    def resolve (self, reply_handler):

        self._reply_handler = reply_handler

        bus = dbus.SystemBus ()
        if not bus:
            reply_handler ([])
            del self._devices
            del self._reply_handler
            return

        for uri, device in self._devices.items ():
            service = _service_tuple_from_uri (uri)
            if service is None:
                self._unresolved -= 1
                continue

            name, stype, domain = service

            try:
                obj = bus.get_object ("org.freedesktop.Avahi", "/")
                server = dbus.Interface (obj,
                                         "org.freedesktop.Avahi.Server")
                self._device_uri_by_name[(name, stype, domain)] = uri
                debugprint ("Resolving address for %s" % uri)
                server.ResolveService (-1, -1,
                                        name, stype, domain,
                                        -1, 0,
                                        reply_handler=self._reply,
                                        error_handler=lambda e:
                                            self._error (uri, e))
            except dbus.DBusException as e:
                debugprint ("Failed to resolve address: %s" % repr (e))
                self._resolved ()

    def _resolved (self):
        self._unresolved -= 1
        if self._unresolved == 0:
            debugprint ("All addresses resolved")
            self._reply_handler (self._devices)
            del self._devices
            del self._reply_handler

    def _reply (self, interface, protocol, name, stype, domain,
                host, aprotocol, address, port, txt, flags):
        uri = self._device_uri_by_name[(name, stype, domain)]
        device = self._devices[uri]
        device.address = address
        hostname = host
        p = hostname.find(".")
        if p != -1:
            hostname = hostname[:p]
        debugprint ("%s is at %s (%s)" % (uri, address, hostname))
        device.hostname = hostname
        if hasattr (device, 'id_dict') and not device.id_dict.get ('SN', ''):
            serial = _txt_value (txt, 'usb_SER')
            if serial != '':
                device.id_dict['SN'] = serial
        self._resolved ()

    def _error (self, uri, error):
        debugprint ("Error resolving %s: %s" % (uri, repr (error)))
        self._resolved ()

if __name__ == '__main__':
    class Device:
        def __repr__ (self):
            try:
                return "<Device @ %s>" % self.address
            except:
                return "<Device>"

    devices = {"dnssd://dlk-08E206-P1._printer._tcp.local/": Device(),
               "dnssd://foo._printer._tcp.local/": Device()}
    from dbus.glib import DBusGMainLoop
    DBusGMainLoop (set_as_default=True)

    class Test:
        def __init__ (self, loop, devices):
            self._loop = loop
            self._devices = devices

        def run (self):
            r = DNSSDHostNamesResolver (self._devices)
            r.resolve (reply_handler=self.reply)
            return False

        def reply (self, *args):
            print(args)
            self._loop.quit ()

    from gi.repository import GObject
    from gi.repository import GLib
    loop = GObject.MainLoop ()
    set_debugging (True)
    GLib.idle_add (Test (loop, devices).run)
    loop.run ()

#!/usr/bin/python

## system-config-printer

## Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011 Red Hat, Inc.
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

# config is generated from config.py.in by configure
import config

import dbus
import json
from debug import *

IPP_CLIENT_SERVICE   = "ipp-client"
IPP_CLIENT_PORT      = "631"
IPP_CLIENT_PROTOCOL  = "udp"
IPP_SERVER_SERVICE   = "ipp"
IPP_SERVER_PORT      = "631"
IPP_SERVER_PROTOCOL  = "tcp"
MDNS_SERVICE         = "mdns"
MDNS_PORT            = "5353"
MDNS_PROTOCOL        = "udp"
SAMBA_CLIENT_SERVICE = "samba-client"


class FirewallD:
    DBUS_INTERFACE = "org.fedoraproject.FirewallD1"
    DBUS_INTERFACE_ZONE = DBUS_INTERFACE+".zone"
    DBUS_PATH = "/org/fedoraproject/FirewallD1"

    def __init__ (self):
        try:
            bus = dbus.SystemBus ()
            obj = bus.get_object (self.DBUS_INTERFACE, self.DBUS_PATH)
            self._firewall = dbus.Interface (obj, self.DBUS_INTERFACE_ZONE)
            self._firewall_properties = dbus.Interface(obj,
                            dbus_interface='org.freedesktop.DBus.Properties')
        except (dbus.DBusException), e:
            self._firewall = None
            self._firewall_properties = None
            self._zone = None
            return

        self._fw_data = []
        self._zone=self._get_active_zone()
        self._timeout=60
        debugprint ("Using FirewallD, active zone: %s" % self._zone)

    def running (self):
        return self._firewall and self._firewall_properties and \
             str(self._firewall_properties.Get(self.DBUS_INTERFACE, "state")) \
             == "RUNNING"

    def _get_active_zone (self):
        try:
            zones = map (str, self._firewall.getActiveZones())
            # remove immutable zones
            zones = [z for z in zones if not self._firewall.isImmutable(z)]
        except (dbus.DBusException), e:
            debugprint ("FirewallD getting active zones failed")
            return None

        if not zones:
            debugprint ("FirewallD: no changeable zone")
            return None
        elif len(zones) == 1:
            # most probable case
            return zones[0]
        else:
            # Do we need to handle the 'more active zones' case ?
            # It's quite unlikely case because that would mean that more
            # interfaces are up and running and they are
            # in different network zones at the same time.
            debugprint ("FirewallD returned more zones, taking first one")
            return zones[0]

    def _addService (self, service):
        if not self._zone:
            return

        try:
            self._firewall.addService (self._zone, service, self._timeout)
        except (dbus.DBusException), e:
            debugprint ("FirewallD allowing service %s failed" % service)
            pass

    def add_service (self, service):
        self._fw_data.append (service)

    def write (self):
        map (self._addService, self._fw_data)
        self._fw_data = []

    def read (self, reply_handler=None, error_handler=None):
        if reply_handler:
            # FIXME:
            # Here I would like to just call the reply_handler() because we
            # don't need to do anything else here, but if I remove the
            # getServices() call and directly call reply_handler()
            # the firewall dialog that the NewPrinterGUI.on_firewall_read()
            # creates becomes unresponsive.

            #reply_handler (self._fw_data)
            self._firewall.getServices (self._zone if self._zone else "",
                                        reply_handler=reply_handler,
                                        error_handler=error_handler)
        return

    def check_ipp_client_allowed (self):
        if not self._zone:
            return True

        try:
            return (self._firewall.queryService(self._zone,
                                                IPP_CLIENT_SERVICE)
                 or self._firewall.queryPort(self._zone,
                                             IPP_CLIENT_PORT,
                                             IPP_CLIENT_PROTOCOL))
        except (dbus.DBusException), e:
            debugprint ("FirewallD query ipp-client service/port failed")
            return True

    def check_ipp_server_allowed (self):
        if not self._zone:
            return True

        try:
            return (self._firewall.queryService(self._zone,
                                                IPP_SERVER_SERVICE)
                 or self._firewall.queryPort(self._zone,
                                             IPP_SERVER_PORT,
                                             IPP_SERVER_PROTOCOL))
        except (dbus.DBusException), e:
            debugprint ("FirewallD query ipp-server service/port failed")
            return True

    def check_samba_client_allowed (self):
        if not self._zone:
            return True

        try:
            return self._firewall.queryService(self._zone,
                                               SAMBA_CLIENT_SERVICE)
        except (dbus.DBusException), e:
            debugprint ("FirewallD query samba-client service failed")
            return True


    def check_mdns_allowed (self):
        if not self._zone:
            return True

        try:
            return (self._firewall.queryService(self._zone, MDNS_SERVICE)
                 or self._firewall.queryPort(self._zone, MDNS_PORT,
                                                         MDNS_PROTOCOL))
        except (dbus.DBusException), e:
            debugprint ("FirewallD query mdns service/port failed")
            return True




class SystemConfigFirewall:
    DBUS_INTERFACE = "org.fedoraproject.Config.Firewall"
    DBUS_PATH = "/org/fedoraproject/Config/Firewall"

    def __init__(self):
        try:
            bus = dbus.SystemBus ()
            obj = bus.get_object (self.DBUS_INTERFACE, self.DBUS_PATH)
            self._firewall = dbus.Interface (obj, self.DBUS_INTERFACE)
            debugprint ("Using system-config-firewall")
        except (dbus.DBusException), e:
            debugprint ("No firewall ")
            self._firewall = None

    def _get_fw_data (self, reply_handler=None, error_handler=None):
        try:
            debugprint ("%s in _get_fw_data: _fw_data is %s" %
                        (self, repr(self._fw_data)))
            if self._fw_data:
                debugprint ("Using cached firewall data")
                if reply_handler == None:
                    return self._fw_data

                self._client_reply_handler (self._fw_data)
        except AttributeError:
            try:
                if reply_handler:
                    self._firewall.read (reply_handler=reply_handler,
                                         error_handler=error_handler)
                    return

                p = self._firewall.read ()
                self._fw_data = json.loads (p.encode ('utf-8'))
            except (dbus.DBusException, AttributeError, ValueError), e:
                self._fw_data = (None, None)
                if error_handler:
                    debugprint ("D-Bus exception examining firewall")
                    self._client_error_handler (e)

        return self._fw_data

    def read (self, reply_handler=None, error_handler=None):
        if reply_handler:
            self._client_reply_handler = reply_handler
            self._client_error_handler = error_handler
            self._get_fw_data (reply_handler=self.reply_handler,
                               error_handler=self.error_handler)
        else:
            self._get_fw_data ()

    def reply_handler (self, result):
        try:
            self._fw_data = json.loads (result.encode ('utf-8'))
        except ValueError, e:
            self.error_handler (e)
            return

        debugprint ("Firewall data obtained")
        self._client_reply_handler (self._fw_data)

    def error_handler (self, exc):
        debugprint ("Exception fetching firewall data")
        self._client_error_handler (exc)

    def write (self):
        try:
            self._firewall.write (json.dumps (self._fw_data[0]))
        except:
            pass

    def _check_any_allowed (self, search):
        (args, filename) = self._get_fw_data ()
        if filename == None: return True
        isect = set (search).intersection (set (args))
        return len (isect) != 0

    def add_service (self, service):
        try:
            (args, filename) = self._fw_data
        except AttributeError:
            (args, filename) = self._get_fw_data ()
        if filename == None: return

        args.append ("--service=" + service)
        self._fw_data = (args, filename)

    def check_ipp_client_allowed (self):
        return self._check_any_allowed (set(["--port=%s:%s" %
                                        (IPP_CLIENT_PORT, IPP_CLIENT_PROTOCOL),
                                             "--service=" + IPP_CLIENT_SERVICE]))

    def check_ipp_server_allowed (self):
        return self._check_any_allowed (set(["--port=%s:%s" %
                                        (IPP_SERVER_PORT, IPP_SERVER_PROTOCOL),
                                             "--service=" + IPP_SERVER_SERVICE]))

    def check_samba_client_allowed (self):
        return self._check_any_allowed (set(["--service=" + SAMBA_CLIENT_SERVICE]))

    def check_mdns_allowed (self):
        return self._check_any_allowed (set(["--port=%s:%s" %
                                                    (MDNS_PORT, MDNS_PROTOCOL),
                                             "--service=" + MDNS_SERVICE]))

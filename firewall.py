#!/usr/bin/env python

## system-config-printer

## Copyright (C) 2006, 2007, 2008, 2009, 2010 Red Hat, Inc.
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
## Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.

# config is generated from config.py.in by configure
import config

import dbus
import pickle

class Firewall:
    ALLOW_IPP_CLIENT = "--service=ipp-client"
    ALLOW_IPP_SERVER = "--service=ipp"
    ALLOW_SAMBA_CLIENT = "--service=samba-client"
    ALLOW_MDNS = "--service=mdns"
    ALLOW_SNMP = "--port=161:udp"

    def _get_fw_data (self, reply_handler=None, error_handler=None):
        try:
            bus = dbus.SystemBus ()
            obj = bus.get_object ("org.fedoraproject.Config.Firewall",
                                  "/org/fedoraproject/Config/Firewall")
            iface = dbus.Interface (obj, "org.fedoraproject.Config.Firewall")
            self._firewall = iface
            if reply_handler:
                self._firewall.read (reply_handler=reply_handler,
                                     error_handler=error_handler)
                return

            p = self._firewall.read ()
            self._fw_data = pickle.loads (p.encode ('utf-8'))
        except dbus.DBusException:
            return None, None

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
        self._fw_data = pickle.loads (result.encode ('utf-8'))
        self._client_reply_handler (self._fw_data)

    def error_handler (self, exc):
        self._client_error_handler (exc)

    def write (self):
        try:
            self._firewall.write (pickle.dumps (self._fw_data[0]))
        except:
            pass

    def _check_any_allowed (self, search):
        (args, filename) = self._get_fw_data ()
        if filename == None: return True
        isect = set (search).intersection (set (args))
        return len (isect) != 0

    def add_rule (self, rule):
        try:
            (args, filename) = self._fw_data
        except AttributeError:
            (args, filename) = self._get_fw_data ()
        if filename == None: return

        args.append (rule)
        self._fw_data = (args, filename)

    def check_ipp_client_allowed (self):
        return self._check_any_allowed (set(["--port=631:udp",
                                             self.ALLOW_IPP_CLIENT]))

    def check_ipp_server_allowed (self):
        return self._check_any_allowed (set(["--port=631:tcp",
                                             self.ALLOW_IPP_SERVER]))

    def check_samba_client_allowed (self):
        return self._check_any_allowed (set([self.ALLOW_SAMBA_CLIENT]))

    def check_mdns_allowed (self):
        return self._check_any_allowed (set(["--port=5353:udp",
                                             self.ALLOW_MDNS]))

    def check_snmp_allowed (self):
        return self._check_any_allowed (set([self.ALLOW_SNMP]))

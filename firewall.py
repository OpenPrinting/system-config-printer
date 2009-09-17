#!/usr/bin/env python

## system-config-printer

## Copyright (C) 2006, 2007, 2008, 2009 Red Hat, Inc.

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
    def _get_fw_data (self):
        try:
            bus = dbus.SystemBus ()
            obj = bus.get_object ("org.fedoraproject.Config.Firewall",
                                  "/org/fedoraproject/Config/Firewall")
            iface = dbus.Interface (obj, "org.fedoraproject.Config.Firewall")
            self._firewall = iface
            p = self._firewall.read ()
            self._fw_data = pickle.loads (p.encode ('utf-8'))
        except dbus.DBusException:
            raise RuntimeError

        return self._fw_data

    def _check_any_allowed (self, search):
        (args, filename) = self._get_fw_data ()
        isect = set (search).intersection (set (args))
        return len (isect) != 0

    def check_ipp_client_allowed (self):
        return self._check_any_allowed (set(["--port=631:udp",
                                             "--service=ipp-client"]))

    def check_ipp_server_allowed (self):
        return self._check_any_allowed (set(["--port=631:tcp",
                                             "--service=ipp"]))

    def check_samba_client_allowed (self):
        return self._check_any_allowed (set(["--service=samba-client"]))

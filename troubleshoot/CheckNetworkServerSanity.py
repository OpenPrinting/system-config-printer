#!/usr/bin/env python

## Printing troubleshooter

## Copyright (C) 2008 Red Hat, Inc.
## Copyright (C) 2008 Tim Waugh <twaugh@redhat.com>

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

import cups
import socket
import subprocess
from base import *
from base import _
class CheckNetworkServerSanity(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Check network server sanity")
        troubleshooter.new_page (gtk.Label (), self)

    def display (self):
        # Collect useful information.

        self.answers = {}
        answers = self.troubleshooter.answers
        if (not answers.has_key ('remote_server_name') and
            not answers.has_key ('remote_server_ip_address')):
            return False

        server_name = answers['remote_server_name']
        server_port = answers.get('remote_server_port', 631)
        if server_name:
            # Try resolving the hostname.
            try:
                ai = socket.getaddrinfo (server_name, server_port)
                resolves = map (lambda (family, socktype,
                                        proto, canonname, sockaddr):
                                    sockaddr[0], ai)
            except socket.gaierror:
                resolves = False

            self.answers['remote_server_name_resolves'] = resolves

            if resolves:
                ipaddr = answers.get ('remote_server_ip_address', '')
                if ipaddr:
                    try:
                        resolves.index (ipaddr)
                    except ValueError:
                        # The IP address given doesn't match the server name.
                        # Use the IP address instead of the name.
                        server_name = ipaddr
        else:
            server_name = answers['remote_server_ip_address']
            # Validate it.
            try:
                ai = socket.getaddrinfo (server_name, server_port)
                resolves = map (lambda (family, socktype,
                                        proto, canonname, sockaddr):
                                    sockaddr[0], ai)
            except socket.gaierror:
                resolves = False

            self.answers['remote_server_name_resolves'] = resolves

        self.answers['remote_server_try_connect'] = server_name

        if (self.answers['remote_server_name_resolves'] and
            answers.get ('cups_device_uri_scheme', 'ipp')):
            try:
                cups.setServer (server_name)
                cups.setPort (server_port)
                c = cups.Connection ()
                ipp_connect = True
            except RuntimeError:
                ipp_connect = False

            self.answers['remote_server_connect_ipp'] = ipp_connect

            if ipp_connect:
                try:
                    c.getPrinters ()
                    cups_server = True
                except:
                    cups_server = False

                self.answers['remote_server_cups'] = cups_server

                if cups_server and answers.get ('cups_queue', False):
                    try:
                        attr = c.getPrinterAttributes (answers['cups_queue'])
                        self.answers['remote_cups_queue_attributes'] = attr
                    except:
                        pass

        # Try traceroute if we haven't already.
        if (self.answers['remote_server_name_resolves'] and
            not answers.has_key ('remote_server_traceroute')):
            try:
                p = subprocess.Popen (['traceroute', '-w', '1', server_name],
                                      stdin=file("/dev/null"),
                                      stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE)
                (stdout, stderr) = p.communicate ()
                self.answers['remote_server_traceroute'] = (stdout, stderr)
            except:
                # Problem executing command.
                pass

        return False

    def collect_answer (self):
        return self.answers

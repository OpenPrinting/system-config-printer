#!/usr/bin/python

## Printing troubleshooter

## Copyright (C) 2008, 2009, 2010, 2011 Red Hat, Inc.
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

from gi.repository import Gtk

import cups
import os
import smburi
import socket
import subprocess
from timedops import TimedSubprocess, TimedOperation
from base import *

try:
    import smbc
except:
    pass

class CheckNetworkServerSanity(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Check network server sanity")
        troubleshooter.new_page (Gtk.Label (), self)

    def display (self):
        # Collect useful information.

        self.answers = {}
        answers = self.troubleshooter.answers
        if (not answers.has_key ('remote_server_name') and
            not answers.has_key ('remote_server_ip_address')):
            return False

        parent = self.troubleshooter.get_window ()

        server_name = answers['remote_server_name']
        server_port = answers.get('remote_server_port', 631)
        try_connect = False
        if server_name:
            # Try resolving the hostname.
            try:
                ai = socket.getaddrinfo (server_name, server_port)
                resolves = map (lambda (family, socktype,
                                        proto, canonname, sockaddr):
                                    sockaddr[0], ai)
                try_connect = True
            except socket.gaierror:
                resolves = False

            self.answers['remote_server_name_resolves'] = resolves

            ipaddr = answers.get ('remote_server_ip_address', '')
            if resolves:
                if ipaddr:
                    try:
                        resolves.index (ipaddr)
                    except ValueError:
                        # The IP address given doesn't match the server name.
                        # Use the IP address instead of the name.
                        server_name = ipaddr
                        try_connect = True
            elif ipaddr:
                server_name = ipaddr
                try_connect = True
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
            try_connect = True

        self.answers['remote_server_try_connect'] = server_name

        if (try_connect and
            answers.get ('cups_device_uri_scheme', 'ipp') in ['ipp',
                                                              'http',
                                                              'https']):
            if answers.get ('cups_device_uri_scheme') == 'https':
                encryption = cups.HTTP_ENCRYPT_REQUIRED
            else:
                encryption = cups.HTTP_ENCRYPT_IF_REQUESTED

            try:
                self.op = TimedOperation (cups.Connection,
                                          kwargs={"host": server_name,
                                                  "port": server_port,
                                                  "encryption": encryption},
                                          parent=parent)
                c = self.op.run ()
                ipp_connect = True
            except RuntimeError:
                ipp_connect = False

            self.answers['remote_server_connect_ipp'] = ipp_connect

            if ipp_connect:
                try:
                    self.op = TimedOperation (c.getPrinters, parent=parent)
                    self.op.run ()
                    cups_server = True
                except:
                    cups_server = False

                self.answers['remote_server_cups'] = cups_server

                if cups_server:
                    cups_printer_dict = answers.get ('cups_printer_dict', {})
                    uri = cups_printer_dict.get ('device-uri', None)
                    if uri:
                        try:
                            self.op = TimedOperation (c.getPrinterAttributes,
                                                      kwargs={"uri": uri},
                                                      parent=parent)
                            attr = self.op.run ()
                            self.answers['remote_cups_queue_attributes'] = attr
                        except:
                            pass

        if try_connect:
            # Try to see if we can connect using smbc.
            context = None
            try:
                context = smbc.Context ()
                name = self.answers['remote_server_try_connect']
                self.op = TimedOperation (context.opendir,
                                          args=("smb://%s/" % name,),
                                          parent=parent)
                dir = self.op.run ()
                self.op = TimedOperation (dir.getdents, parent=parent)
                shares = self.op.run ()
                self.answers['remote_server_smb'] = True
                self.answers['remote_server_smb_shares'] = shares
            except NameError:
                # No smbc support
                pass
            except RuntimeError as e:
                (e, s) = e.args
                self.answers['remote_server_smb_shares'] = (e, s)

            if context != None and answers.has_key ('cups_printer_dict'):
                uri = answers['cups_printer_dict'].get ('device-uri', '')
                u = smburi.SMBURI (uri)
                (group, host, share, user, password) = u.separate ()
                accessible = False
                try:
                    self.op = TimedOperation (context.open,
                                              args=("smb://%s/%s" % (host,
                                                                     share),
                                                    os.O_RDWR,
                                                    0777),
                                              parent=parent)
                    f  = self.op.run ()
                    accessible = True
                except RuntimeError as e:
                    (e, s) = e.args
                    accessible = (e, s)

                self.answers['remote_server_smb_share_anon_access'] = accessible

        # Try traceroute if we haven't already.
        if (try_connect and
            not answers.has_key ('remote_server_traceroute')):
            try:
                self.op = TimedSubprocess (parent=parent, close_fds=True,
                                           args=['traceroute', '-w', '1',
                                                 server_name],
                                           stdin=file("/dev/null"),
                                           stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE)
                self.answers['remote_server_traceroute'] = self.op.run ()
            except:
                # Problem executing command.
                pass

        return False

    def collect_answer (self):
        return self.answers

    def cancel_operation (self):
        self.op.cancel ()

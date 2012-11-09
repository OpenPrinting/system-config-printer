#!/usr/bin/python

## Printing troubleshooter

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

from gi.repository import Gtk

import cups
import os
import smburi
import subprocess
from timedops import TimedOperation, TimedSubprocess
import urllib
from base import *
class CheckPrinterSanity(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Check printer sanity")
        troubleshooter.new_page (Gtk.Label (), self)
        self.troubleshooter = troubleshooter

    def display (self):
        # Collect information useful for the various checks.

        self.answers = {}

        answers = self.troubleshooter.answers
        if not answers['cups_queue_listed']:
            return False

        name = answers['cups_queue']

        parent = self.troubleshooter.get_window ()

        # Find out if this is a printer or a class.
        try:
            cups.setServer ('')
            c = TimedOperation (cups.Connection, parent=parent).run ()
            printers = TimedOperation (c.getPrinters, parent=parent).run ()
            if printers.has_key (name):
                self.answers['is_cups_class'] = False
                queue = printers[name]
                self.answers['cups_printer_dict'] = queue
            else:
                self.answers['is_cups_class'] = True
                classes = TimedOperation (c.getClasses, parent=parent).run ()
                queue = classes[name]
                self.answers['cups_class_dict'] = queue

            attrs = TimedOperation (c.getPrinterAttributes, (name,),
                                    parent=parent).run ()
            self.answers['local_cups_queue_attributes'] = attrs
        except:
            pass

        if self.answers.has_key ('cups_printer_dict'):
            cups_printer_dict = self.answers['cups_printer_dict']
            uri = cups_printer_dict['device-uri']
            (scheme, rest) = urllib.splittype (uri)
            self.answers['cups_device_uri_scheme'] = scheme
            if scheme in ["ipp", "http", "https"]:
                (hostport, rest) = urllib.splithost (rest)
                (host, port) = urllib.splitnport (hostport, defport=631)
                self.answers['remote_server_name'] = host
                self.answers['remote_server_port'] = port
            elif scheme == "smb":
                u = smburi.SMBURI (uri)
                (group, host, share, user, password) = u.separate ()
                new_environ = os.environ.copy()
                new_environ['LC_ALL'] = "C"
                if group:
                    args = ["nmblookup", "-W", group, host]
                else:
                    args = ["nmblookup", host]
                try:
                    p = TimedSubprocess (parent=parent,
                                         timeout=5000,
                                         args=args,
                                         env=new_environ,
                                         close_fds=True,
                                         stdin=file("/dev/null"),
                                         stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE)
                    result = p.run ()
                    self.answers['nmblookup_output'] = result
                    for line in result[0]:
                        if line.startswith ("querying"):
                            continue
                        spc = line.find (' ')
                        if (spc != -1 and
                            not line[spc:].startswith (" failed ")):
                            # Remember the IP address.
                            self.answers['remote_server_name'] = line[:spc]
                            break
                except OSError:
                    # Problem executing command.
                    pass
            elif scheme == "hp":
                new_environ = os.environ.copy()
                new_environ['LC_ALL'] = "C"
                new_environ['DISPLAY'] = ""
                try:
                    p = TimedSubprocess (parent=parent,
                                         timeout=3000,
                                         args=["hp-info", "-d" + uri],
                                         close_fds=True,
                                         env=new_environ,
                                         stdin=file("/dev/null"),
                                         stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE)
                    self.answers['hplip_output'] = p.run ()
                except OSError:
                    # Problem executing command.
                    pass

            r = cups_printer_dict['printer-type'] & cups.CUPS_PRINTER_REMOTE
            self.answers['cups_printer_remote'] = (r != 0)
        return False

    def collect_answer (self):
        return self.answers

#!/usr/bin/env python

## Printing troubleshooter

## Copyright (C) 2008, 2009 Red Hat, Inc.
## Copyright (C) 2008, 2009 Tim Waugh <twaugh@redhat.com>

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
import gobject
import os
import smburi
import subprocess
from timedops import TimedOperation, TimedSubprocess
import urllib
from base import *
class CheckPrinterSanity(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Check printer sanity")
        troubleshooter.new_page (gtk.Label (), self)
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
                os.environ['HOST'] = host
                if group:
                    os.environ['GROUP'] = group
                    cmdline = 'LC_ALL=C nmblookup -W "$GROUP" "$HOST"'
                else:
                    cmdline = 'LC_ALL=C nmblookup "$HOST"'
                try:
                    p = TimedSubprocess (parent=parent,
                                         timeout=5000,
                                         args=cmdline, shell=True,
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
                os.environ['URI'] = uri
                try:
                    p = TimedSubprocess (parent=parent,
                                         timeout=3000,
                                         args='LC_ALL=C DISPLAY= hp-info -d"$URI"',
                                         shell=True,
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

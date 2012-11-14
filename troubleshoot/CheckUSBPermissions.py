#!/usr/bin/python

## Printing troubleshooter

## Copyright (C) 2008, 2009, 2010 Red Hat, Inc.
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

import glob
import os
import subprocess
from timedops import TimedSubprocess
import urllib
from base import *
from gi.repository import Gtk

class CheckUSBPermissions(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Check USB permissions")
        troubleshooter.new_page (Gtk.Label (), self)

    def display (self):
        self.answers = {}
        answers = self.troubleshooter.answers
        if answers['cups_queue_listed']:
            if answers['is_cups_class']:
                return False

            cups_printer_dict = answers['cups_printer_dict']
            device_uri = cups_printer_dict['device-uri']
        elif answers.get ('cups_device_listed', False):
            device_uri = answers['cups_device_uri']
        else:
            return False

        (scheme, rest) = urllib.splittype (device_uri)
        if scheme not in ['hp', 'hpfax', 'usb', 'hal']:
            return False

        LSUSB = "/sbin/lsusb"
        if not os.access (LSUSB, os.X_OK):
            return False

        GETFACL = "/usr/bin/getfacl"
        if not os.access (GETFACL, os.X_OK):
            return False

        new_environ = os.environ.copy()
        new_environ['LC_ALL'] = "C"

        # Run lsusb
        parent = self.troubleshooter.get_window ()
        try:
            self.op = TimedSubprocess (parent=parent,
                                       args=[LSUSB, "-v"],
                                       close_fds=True,
                                       env=new_environ,
                                       stdin=file("/dev/null"),
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
            (lsusb_stdout, lsusb_stderr, result) = self.op.run ()
        except:
            # Problem executing command.
            return False

        # Now parse it.
        dev_by_id = {}
        this_dev = None
        for line in lsusb_stdout:
            if (this_dev != None and
                ((line.find ("bInterfaceClass") != -1 and
                  line.find ("7 Printer") != -1) or
                 (line.find ("bInterfaceSubClass") != -1 and
                  line.find ("1 Printer") != -1))):
                mfr = dev_by_id.get (this_mfr_id, {})
                mdl = mfr.get (this_mdl_id, [])
                mdl.append (this_dev)
                mfr[this_mdl_id] = mdl
                dev_by_id[this_mfr_id] = mfr
                this_dev = None
                continue

            separators = [ ('Bus ', 3),
                           (' Device ', 3),
                           (': ID ', 4),
                           (':', 4),
                           (' ', -1)]
            fields = []
            i = 0
            p = line
            while i < len (separators):
                (sep, length) = separators[i]
                if not p.startswith (sep):
                    break
                start = len (sep)
                if length == -1:
                    end = len (p)
                    fields.append (p[start:])
                else:
                    end = start + length
                    fields.append (p[start:end])

                p = p[end:]
                i += 1

            if i < len (separators):
                continue

            if not scheme.startswith ('hp') and fields[2] != '03f0':
                # Skip non-HP printers if we know we're using HPLIP.
                continue

            this_dev = { 'bus': fields[0],
                         'dev': fields[1],
                         'name': fields[4],
                         'full': line }
            this_mfr_id = fields[2]
            this_mdl_id = fields[3]

        infos = {}
        paths = []
        if not scheme.startswith ('hp'):
            paths.extend (glob.glob ("/dev/usb/lp?"))
        for mfr_id, mdls in dev_by_id.iteritems ():
            for mdl_id, devs in mdls.iteritems ():
                for dev in devs:
                    path = "/dev/bus/usb/%s/%s" % (dev['bus'], dev['dev'])
                    paths.append (path)
                    infos[path] = dev['full']

        perms = []
        for path in paths:
            try:
                self.op = TimedSubprocess (parent=parent,
                                           args=[GETFACL, path],
                                           close_fds=True,
                                           env=new_environ,
                                           stdin=file("/dev/null"),
                                           stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE)
                (getfacl_stdout, getfacl_stderr, result) = self.op.run ()
                output = filter (lambda x: len (x) > 0, getfacl_stdout)
            except:
                # Problem executing command.
                output = []

            info = infos.get (path, path)
            perms.append ((info, output))

        self.answers['getfacl_output'] = perms

        # Don't actually display anything, just collect information.
        return False

    def collect_answer (self):
        return self.answers

    def cancel_operation (self):
        self.op.cancel ()

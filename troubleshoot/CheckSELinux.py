#!/usr/bin/python

## Printing troubleshooter

## Copyright (C) 2010 Red Hat, Inc.
## Copyright (C) 2010 Jiri Popelka <jpopelka@redhat.com>

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

import subprocess
from base import *
import os
import shlex
from timedops import TimedSubprocess

class CheckSELinux(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Check SELinux contexts")
        troubleshooter.new_page (Gtk.Label (), self)

    def display (self):
        self.answers = {}
        #answers = self.troubleshooter.answers

        RESTORECON = "/sbin/restorecon"
        if not os.access (RESTORECON, os.X_OK):
            return False

        try:
            import selinux
        except ImportError:
            return False
        if not selinux.is_selinux_enabled():
            return False

        paths = ["/etc/cups/", "/usr/lib/cups/", "/usr/share/cups/"]
        null = file ("/dev/null", "r+")
        parent = self.troubleshooter.get_window ()
        contexts = {}
        new_environ = os.environ.copy()
        new_environ['LC_ALL'] = "C"
        restorecon_args = [RESTORECON, "-nvR"].extend(paths)
        try:
            # Run restorecon -nvR
            self.op = TimedSubprocess (parent=parent,
                                       args=restorecon_args,
                                       close_fds=True,
                                       env=new_environ,
                                       stdin=null,
                                       stdout=subprocess.PIPE,
                                       stderr=null)
            (restorecon_stdout, restorecon_stderr, result) = self.op.run ()
        except:
            # Problem executing command.
            return False
        for line in restorecon_stdout:
            l = shlex.split (line)
            if (len (l) < 1):
                continue
            contexts[l[2]] = l[4]
        self.answers['selinux_contexts'] = contexts
        return False

    def collect_answer (self):
        return self.answers

    def cancel_operation (self):
        self.op.cancel ()

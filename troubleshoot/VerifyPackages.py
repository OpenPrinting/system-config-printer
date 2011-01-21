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
from timedops import TimedSubprocess

class VerifyPackages(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Verify packages")
        troubleshooter.new_page (Gtk.Label (), self)

    def display (self):
        self.answers = {}
        packages_verification = {}

        package_manager="/bin/rpm"
        if not os.access (package_manager, os.X_OK):
            return False

        packages = ["cups",
                    "foomatic",
                    "gutenprint",
                    "hpijs",
                    "hplip",
                    "system-config-printer"]
        null = file ("/dev/null", "r+")
        parent = self.troubleshooter.get_window ()

        new_environ = os.environ.copy()
        new_environ['LC_ALL'] = "C"

        for package in packages:
            verification_args = [package_manager, "-V", package]
            try:
                self.op = TimedSubprocess (parent=parent,
                                           args=verification_args,
                                           close_fds=True,
                                           env=new_environ,
                                           stdin=null,
                                           stdout=subprocess.PIPE,
                                           stderr=null)
                (verif_stdout, verif_stderr, result) = self.op.run ()
            except:
                # Problem executing command.
                return False
            packages_verification[package] = verif_stdout[:-1]

        self.answers['packages_verification'] = packages_verification
        return False

    def collect_answer (self):
        return self.answers

    def cancel_operation (self):
        self.op.cancel ()

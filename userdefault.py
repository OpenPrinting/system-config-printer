#!/usr/bin/env python

## Copyright (C) 2006, 2007, 2008 Red Hat, Inc.
## Copyright (C) 2007, 2008 Tim Waugh <twaugh@redhat.com>

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

import os
import subprocess

class UserDefaultPrinter:
    def __init__ (self):
        try:
            lpoptions = os.environ["HOME"]
        except KeyError:
            try:
                lpoptions = "/home/" + os.environ["USER"]
            except KeyError:
                lpoptions = None

        if lpoptions:
            lpoptions += "/.cups/lpoptions"

        self.lpoptions = lpoptions

    def clear (self):
        if not self.lpoptions:
            return

        try:
            opts = file (self.lpoptions).readlines ()
        except IOError:
            return

        for i in range (len (opts)):
            if opts[i].startswith ("Default "):
                opts[i] = "Dest " + opts[i][8:]
        file (self.lpoptions, "w").writelines (opts)

    def get (self):
        if not self.lpoptions:
            return None

        try:
            opts = file (self.lpoptions).readlines ()
        except IOError:
            return None

        for i in range (len (opts)):
            if opts[i].startswith ("Default "):
                rest = opts[i][8:]
                slash = rest.find ("/")
                if slash != -1:
                    space = rest[:slash].find (" ")
                else:
                    space = rest.find (" ")
                return rest[:space]
        return None

    def set (self, default):
        p = subprocess.Popen ([ "lpoptions", "-d", default ],
                              stdin=file ("/dev/null"),
                              stdout=file ("/dev/null", "w"),
                              stderr=subprocess.PIPE)
        (stdout, stderr) = p.communicate ()
        exitcode = p.wait ()
        if exitcode != 0:
            raise RuntimeError (exitcode, stderr.strip ())
        return

    def __repr__ (self):
        return "<UserDefaultPrinter (%s)>" % repr (self.get ())

#!/usr/bin/env python

## system-config-printer

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

import os
import glib

class PackageKit:
    def __init__ (self):
        for dir in os.environ.get ("PATH", "").split (":"):
            path = dir + os.path.sep + "gpk-install-package-name"
            if os.access (path, os.X_OK):
                self.gpk_install_package_name = path
                return

        raise RuntimeError, "No gpk-install-package-name program available"

    def InstallPackageName (self, xid, timestamp, name):
        glib.spawn_async ([self.gpk_install_package_name, name])

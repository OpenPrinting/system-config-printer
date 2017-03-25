#!/usr/bin/python3
# -*- python -*-

## Copyright (C) 2008, 2014 Red Hat, Inc.
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
## Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import sys

import cups
try:
    from cupshelpers import missingPackagesAndExecutables
except ImportError:
    sys.path.append ('..')
    from cupshelpers import missingPackagesAndExecutables

from getopt import getopt
import os
import posix
import re
import shlex
import signal
import subprocess
import tempfile

class TimedOut(Exception):
    def __init__ (self):
        Exception.__init__ (self, "Timed out")

class MissingExecutables(Exception):
    def __init__ (self):
        Exception.__init__ (self, "Missing executables")

class Driver:
    def __init__ (self, driver):
        self.exe = "/usr/lib/cups/driver/%s" % driver
	self.ppds = None
	self.files = {}
        signal.signal (signal.SIGALRM, self._alarm)

    def _alarm (self, sig, stack):
        raise TimedOut

    def list (self):
        if self.ppds:
		return self.ppds

        signal.alarm (60)
        p = subprocess.Popen ([self.exe, "list"],
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
        try:
            (stdout, stderr) = p.communicate ()
            signal.alarm (0)
        except TimedOut:
            posix.kill (p.pid, signal.SIGKILL)
            raise

	if stderr:
		print(stderr.decode (), file=sys.stderr)

	ppds = []
	lines = stdout.decode ().split ('\n')
	for line in lines:
		l = shlex.split (line)
		if len (l) < 1:
			continue
		ppds.append (l[0])

	self.ppds = ppds
	return ppds

    def cat (self, name):
        try:
            return self.files[name]
	except KeyError:
            signal.alarm (10)
            p = subprocess.Popen ([self.exe, "cat", name],
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
            try:
                (stdout, stderr) = p.communicate ()
                signal.alarm (0)
            except TimedOut:
                posix.kill (p.pid, signal.SIGKILL)
                raise

            if stderr:
                print(stderr.decode (), file=sys.stderr)

            self.files[name] = stdout.decode ()
            return self.files[name]

opts, args = getopt (sys.argv[1:], "m:")
if len (args) != 1:
    print ("Syntax: test-cups-driver [-m REGEXP] DRIVER")
    sys.exit (1)

match = None
for opt, arg in opts:
    if opt == '-m':
        match = arg
        break

bad = []
ids = set()
d = Driver (args[0])
list = d.list ()

if match:
    exp = re.compile (match)
    list = [x for x in list if exp.match (x)]

n = len (list)
i = 0
for name in list:
    i += 1
    try:
        ppd = d.cat (name)
        (fd, fname) = tempfile.mkstemp ()
        f = os.fdopen (fd, "w")
        f.write (ppd)
        del f
        try:
            PPD = cups.PPD (fname)
        except:
            os.unlink (fname)
            raise
        os.unlink (fname)

        (pkgs, exes) = missingPackagesAndExecutables (PPD)
        if pkgs or exes:
            raise MissingExecutables

        attr = PPD.findAttr ('1284DeviceID')
        if attr:
            pieces = attr.value.split (';')
            mfg = mdl = None
            for piece in pieces:
                s = piece.split (':', 1)
                if len (s) < 2:
                    continue
                key, value = s
                key = key.upper ()
                if key in ["MFG", "MANUFACTURER"]:
                    mfg = value
                elif key in ["MDL", "MODEL"]:
                    mdl = value
            if mfg and mdl:
                id = "MFG:%s;MDL:%s;" % (mfg, mdl)
                ids.add (id)
        sys.stderr.write ("%3d%%\r" % (100 * i / n))
        sys.stderr.flush ()
    except KeyboardInterrupt:
        print ("Keyboard interrupt\n")
        break
    except TimedOut as e:
        bad.append ((name, e))
        print ("Timed out fetching %s" % name)
    except Exception as e:
        bad.append ((name, e))
        print ("Exception fetching %s: %s" % (name, e))

    sys.stdout.flush ()

if len (bad) > 0:
    print ("Bad PPDs:")
    for each in bad:
        print ("  %s (%s)" % each)
    print

if len (ids) > 0:
    print ("IEEE 1284 Device IDs:")
    for each in ids:
        print ("  %s" % each)
    print

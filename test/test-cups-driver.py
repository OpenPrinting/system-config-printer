#!/usr/bin/python
# -*- python -*-

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
from getopt import getopt
import os
import posix
import shlex
import signal
import subprocess
import sys
import tempfile

class AlarmClock(Exception):
    def __init__ (self):
        Exception.__init__ (self, "Timed out")

class Driver:
    def __init__ (self, driver):
        self.exe = "/usr/lib/cups/driver/%s" % driver
	self.ppds = None
	self.files = {}
        signal.signal (signal.SIGALRM, self._alarm)

    def _alarm (self, sig, stack):
        raise AlarmClock

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
        except AlarmClock:
            posix.kill (p.pid, signal.SIGKILL)
            raise

	if stderr:
		print >> sys.stderr, stderr

	ppds = []
	lines = stdout.split ('\n')
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
            except AlarmClock:
                posix.kill (p.pid, signal.SIGKILL)
                raise

            if stderr:
                print >> sys.stderr, stderr

            self.files[name] = stdout
            return stdout

opts, args = getopt (sys.argv, "")
me = args.pop (0)
if len (args) != 1:
    print "Syntax: %s DRIVER" % me
    sys.exit (1)

bad = []
ids = set()
d = Driver (args[0])
list = d.list ()
n = len (list)
i = 0
for name in list:
    i += 1
    try:
        ppd = d.cat (name)
        (fd, name) = tempfile.mkstemp ()
        file (name, "w").write (ppd)
        try:
            PPD = cups.PPD (name)
        except:
            os.unlink (name)
            raise
        os.unlink (name)
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
        print "Keyboard interrupt\n"
        break
    except AlarmClock, e:
        bad.append ((name, e))
        print "Timed out fetching %s" % name
    except Exception, e:
        bad.append ((name, e))
        print "Exception fetching %s: %s" % (name, e)

    sys.stdout.flush ()

if len (bad) > 0:
    print "Bad PPDs:"
    for each in bad:
        print "  %s (%s)" % each
    print

if len (ids) > 0:
    print "IEEE 1284 Device IDs:"
    for each in ids:
        print "  %s" % each
    print

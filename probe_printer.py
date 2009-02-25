## system-config-printer

## Copyright (C) 2006, 2007, 2008, 2009 Red Hat, Inc.
## Copyright (C) 2006 Florian Festi <ffesti@redhat.com>
## Copyright (C) 2007, 2008, 2009 Tim Waugh <twaugh@redhat.com>

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

import cupshelpers
import socket, time
import gtk
from timedops import TimedOperation

class LpdServer:
    def __init__(self, hostname):
        self.hostname = hostname
        self.max_lpt_com = 8

    def _open_socket(self):
        port = 515
        try:
            host, port = self.hostname.split(":", 1)
        except ValueError:
            host = self.hostname
        
        s = None
        try:
            ai = socket.getaddrinfo(host, port, socket.AF_UNSPEC,
                                    socket.SOCK_STREAM)
        except socket.gaierror:
            ai = []

        for res in ai:
            af, socktype, proto, canonname, sa = res
            try:
                s = socket.socket(af, socktype, proto)
                s.settimeout(0.5)
            except socket.error, msg:
                s = None
                continue
            try:
                s.connect(sa)
            except socket.error, msg:
                s.close()
                s = None
                continue
            break
        return s

    def probe_queue(self,name, result):
        while gtk.events_pending ():
            gtk.main_iteration ()

        s = self._open_socket()
        if not s: return False
        print name
        
        try:
            s.send('\2%s\n' % name) # cmd send job to queue
            data = s.recv(1024) # receive status
            print repr(data)
        except socket.error, msg:
            print msg
            try:
                s.close ()
            except:
                pass

            return False

        if len(data)>0 and ord(data[0])==0:
            try:
                s.send('\1\n') # abort job again
                s.close ()
            except:
                pass

            result.append(name)
            return True

        try:
            s.close()
        except:
            pass

        return False

    def get_possible_queue_names (self):
        candidate = ["PASSTHRU", "ps", "lp", "PORT1", ""]
        for nr in range (self.max_lpt_com):
            candidate.extend (["LPT%d" % nr,
                               "LPT%d_PASSTHRU" % nr,
                               "COM%d" % nr,
                               "COM%d_PASSTHRU" % nr])
        for nr in range (50):
            candidate.append ("pr%d" % nr)

        return candidate

    def probe(self):
        result = []
        for name in self.get_possible_queue_names ():
            found = self.probe_queue(name, result)
            if not found and name.startswith ("pr"):
                break
            time.sleep(0.1) # avoid DOS and following counter messures 

        return result

class SocketServer:
    def __init__(self, hostname):
        self.hostname = hostname
    
class IppServer:
    def __init__(self, hostname):
        self.hostname = hostname

class PrinterFinder:
    def find (self, hostname, callback_fn):
        self.hostname = hostname
        self.callback_fn = callback_fn
        self._probe_lpd ()
        self.callback_fn (None)

    def _probe_lpd (self):
        lpd = LpdServer (self.hostname)
        for name in lpd.get_possible_queue_names ():
            op = TimedOperation (lpd.probe_queue, args=(name, []))
            found = op.run ()
            if found:
                uri = "lpd://%s/%s" % (self.hostname, name)
                device_dict = { 'device-class': 'network',
                                'device-info': uri }
                new_device = cupshelpers.Device (uri, **device_dict)
                self.callback_fn (new_device)

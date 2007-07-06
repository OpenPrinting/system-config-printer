## system-config-printer

## Copyright (C) 2006, 2007 Red Hat, Inc.
## Copyright (C) 2006 Florian Festi <ffesti@redhat.com>
## Copyright (C) 2007 Tim Waugh <twaugh@redhat.com>

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

import socket, time

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

    def _probe_queue(self,name, result):
        s = self._open_socket()
        if not s: return False
        print name
        
        s.send('\0x02%s\n' % name) # cmd send job to queue
        data = s.recv(1024) # receive status
        print repr(data)
        s.close()
        if len(data)>0 and data[0]==0:
            s.send('\0x01\n') # abort job again
            result.append(name)
            return True
        return False

    def probe(self):
        #s = self._open_socket()        
        #if s is None:
        #    return []
        result = []
        for name in ["PASSTHRU", "ps", "lp", "PORT1"]:
            self._probe_queue(name, result)
            time.sleep(0.1) # avoid DOS and following counter messures 
        for nr in range(self.max_lpt_com):
            self._probe_queue("LPT%d" % nr, result)
            time.sleep(0.1)
            self._probe_queue("LPT%d_PASSTHRU" % nr, result)
            time.sleep(0.1)
            self._probe_queue("COM%d" % nr, result)
            time.sleep(0.1)
            self._probe_queue("COM%d_PASSTHRU" % nr, result)
            time.sleep(0.1)

        nr = 1
        while nr<50:
            found =  self._probe_queue("pr%d" % nr, result)
            time.sleep(0.1)
            if not found: break
            nr += 1

        return result

class SocketServer:
    def __init__(self, hostname):
        self.hostname = hostname
    
class IppServer:
    def __init__(self, hostname):
        self.hostname = hostname

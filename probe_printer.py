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
from debug import *
import errno
import socket, time
import gtk
from timedops import TimedOperation
import subprocess
import threading
import errno
import cups

try:
    import pysmb
    PYSMB_AVAILABLE=True
except:
    PYSMB_AVAILABLE=False
    class pysmb:
        class AuthContext:
            pass

def wordsep (line):
    words = []
    escaped = False
    quoted = False
    in_word = False
    word = ''
    n = len (line)
    for i in range (n):
        ch = line[i]
        if escaped:
            word += ch
            escaped = False
            continue

        if ch == '\\':
            in_word = True
            escaped = True
            continue

        if in_word:
            if quoted:
                if ch == '"':
                    quoted = False
                else:
                    word += ch
            elif ch.isspace ():
                words.append (word)
                word = ''
                in_word = False
            elif ch == '"':
                quoted = True
            else:
                word += ch
        else:
            if ch == '"':
                in_word = True
                quoted = True
            elif not ch.isspace ():
                in_word = True
                word += ch

    if word != '':
        words.append (word)

    return words

### should be ['network', 'foo bar', ' ofoo', '"', '2 3']
##print wordsep ('network "foo bar" \ ofoo "\\"" 2" "3')

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
            while gtk.events_pending ():
                gtk.main_iteration ()

            found = self.probe_queue(name, result)
            if not found and name.startswith ("pr"):
                break
            time.sleep(0.1) # avoid DOS and following counter measures 

        return result

class BackgroundSmbAuthContext(pysmb.AuthContext):
    """An SMB AuthContext class that is only ever run from
    a non-GUI thread."""

    def __init__ (self, *args, **kwargs):
        self._gui_event = threading.Event ()
        pysmb.AuthContext.__init__ (self, *args, **kwargs)

    def _do_perform_authentication (self):
        result = pysmb.AuthContext.perform_authentication (self)
        self.do_perform_authentication_result = result
        self._gui_event.set ()
        
    def perform_authentication (self):
        if (self.passes == 0 or
            not self.has_failed or
            not self.auth_called or
            (self.auth_called and not self.tried_guest)):
            # Safe to call the base function.  It won't try any UI stuff.
            return pysmb.AuthContext.perform_authentication (self)

        self._gui_event.clear ()
        gobject.timeout_add (1, self._do_perform_authentication)
        self._gui_event.wait ()
        return self._do_perform_authentication_result

class PrinterFinder:
    def __init__ (self):
        self.quit = False

    def find (self, hostname, callback_fn):
        self.hostname = hostname
        self.callback_fn = callback_fn
        self.op = TimedOperation (self._do_find, callback=lambda x, y: None)

    def cancel (self):
        self.op.cancel ()
        self.quit = True

    def _do_find (self):
        self._cached_attributes = dict()
        for fn in [self._probe_jetdirect,
                   self._probe_ipp,
                   self._probe_snmp,
                   self._probe_lpd,
                   self._probe_hplip,
                   self._probe_smb]:
            if self.quit:
                return

            try:
                fn ()
            except Exception, e:
                nonfatalException ()

        # Signal that we've finished.
        if not self.quit:
            self.callback_fn (None)

    def _new_device (self, uri, info):
        device_dict = { 'device-class': 'network',
                        'device-info': "%s" % info }
        device_dict.update (self._cached_attributes)
        new_device = cupshelpers.Device (uri, **device_dict)
        debugprint ("Device found: %s" % uri)
        self.callback_fn (new_device)

    def _probe_snmp (self):
        # Run the CUPS SNMP backend, pointing it at the host.
        null = file ("/dev/null", "r+")
        try:
            p = subprocess.Popen (args=["/usr/lib/cups/backend/snmp",
                                        self.hostname],
                                  stdin=null,
                                  stdout=subprocess.PIPE,
                                  stderr=null)
        except OSError, e:
            if e == errno.ENOENT:
                return

            raise

        (stdout, stderr) = p.communicate ()
        if p.returncode != 0:
            return

        if self.quit:
            return

        for line in stdout.split ('\n'):
            words = wordsep (line)
            n = len (words)
            if n == 5:
                (device_class, uri, make_and_model, info, device_id) = words
            elif n == 4:
                (device_class, uri, make_and_model, info) = words
            else:
                continue

            device_dict = { 'device-class': device_class,
                            'device-make-and-model': make_and_model,
                            'device-info': info }
            if n == 5:
                device_dict['device-id'] = device_id

            device = cupshelpers.Device (uri, **device_dict)
            self.callback_fn (device)

            # Cache the make and model for use by other search methods
            # that are not able to determine it.
            self._cached_attributes['device-make-and-model'] = make_and_model

    def _probe_lpd (self):
        lpd = LpdServer (self.hostname)
        for name in lpd.get_possible_queue_names ():
            if self.quit:
                return

            found = lpd.probe_queue (name, [])
            if found:
                uri = "lpd://%s/%s" % (self.hostname, name)
                self._new_device(uri, self.hostname)

            if not found and name.startswith ("pr"):
                break

            time.sleep(0.1) # avoid DOS and following counter measures 

    def _probe_hplip (self):
        null = file ("/dev/null", "r+")
        try:
            p = subprocess.Popen (args=["hp-makeuri", "-c", self.hostname],
                                  stdin=null,
                                  stdout=subprocess.PIPE,
                                  stderr=null)
        except OSError, e:
            if e == errno.ENOENT:
                return

            raise

        (stdout, stderr) = p.communicate ()
        if p.returncode != 0:
            return

        if self.quit:
            return

        uri = stdout.strip ()
        if uri.find (":") != -1:
            self._new_device(uri, uri)

    def _probe_smb (self):
        if not PYSMB_AVAILABLE:
            return

        smbc_auth = BackgroundSmbAuthContext ()
        debug = 0
        if get_debugging ():
            debug = 10
        ctx = pysmb.smbc.Context (debug=debug,
                                  auth_fn=smbc_auth.callback)
        entries = []
        uri = "smb://%s/" % self.hostname
        try:
            while smbc_auth.perform_authentication () > 0:
                if self.quit:
                    return

                try:
                    entries = ctx.opendir (uri).getdents ()
                except Exception, e:
                    smbc_auth.failed (e)
        except RuntimeError, (e, s):
            if e not in [errno.ENOENT, errno.EACCES, errno.EPERM]:
                debugprint ("Runtime error: %s" % repr ((e, s)))
        except:
            nonfatalException ()

        if self.quit:
            return

        for entry in entries:
            if entry.smbc_type == pysmb.smbc.PRINTER_SHARE:
                uri = "smb://%s/%s" % (self.hostname, entry.name)
                info = "SMB (%s)" % self.hostname
                self._new_device(uri, info)

    def _probe_jetdirect (self):
        port = 9100    #jetdirect
        sock_address = (self.hostname, port)
        sock = socket.socket (socket.AF_INET, socket.SOCK_STREAM)
        try:
            # try to connect on given port
            sock.connect (sock_address)
        except socket.error:
            debugprint ("%s:%d CLOSED" % sock_address)
        else:
            # port is open so assume its a JetDirect device
            debugprint ("%s:%d OPEN" % sock_address)
            uri = "socket://%s:%d" % sock_address
            info = "JetDirect (%s)" % self.hostname
            self._new_device(uri, info)
            sock.close ()

    def _probe_ipp (self):
        try:
            fqdn = socket.getfqdn(self.hostname)
            ip_address = socket.gethostbyname(fqdn)
        except socket.gaierror:
            debugprint ("Can't resolve %s" % self.hostname)
            return
        if ip_address == "127.0.0.1":
            debugprint ("Do not probe local cups server")
            return

        try:
            c = cups.Connection (host = self.hostname)
        except RuntimeError:
            debugprint ("Can't connect to server/printer")
            return

        try:
            printers = c.getPrinters ()
        except cups.IPPError:
            debugprint ("%s is probably not a cups server but IPP printer" %
                        self.hostname)
            uri = "ipp://%s:631/ipp" % (self.hostname)
            info = "IPP (%s)" % self.hostname
            self._new_device(uri, info)
            return

        for name, queue in printers.iteritems ():
            uri = queue['printer-uri-supported']
            info = queue['printer-info']
            self._new_device(uri, info)

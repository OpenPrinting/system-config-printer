## system-config-printer

## Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012 Red Hat, Inc.
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
## Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import cupshelpers
from debug import *
import errno
import socket, time
from gi.repository import Gdk
from gi.repository import Gtk
from timedops import TimedOperation
import subprocess
import threading
import errno
import cups
from gi.repository import GObject
from gi.repository import GLib
import smburi

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

def open_socket(hostname, port):
    try:
        host, port = hostname.split(":", 1)
    except ValueError:
        host = hostname

    s = None
    try:
        ai = socket.getaddrinfo(host, port, socket.AF_UNSPEC,
                                socket.SOCK_STREAM)
    except (socket.gaierror, socket.error):
        ai = []

    for res in ai:
        af, socktype, proto, canonname, sa = res
        try:
            s = socket.socket(af, socktype, proto)
            s.settimeout(0.5)
        except socket.error:
            s = None
            continue
        try:
            s.connect(sa)
        except socket.error:
            s.close()
            s = None
            continue
        break
    return s

class LpdServer:
    def __init__(self, hostname):
        self.hostname = hostname
        self.max_lpt_com = 8
        self.stop = False

    def probe_queue(self,name, result):
        s = open_socket(self.hostname, 515)
        if not s:
            return None
        print name
        
        try:
            s.send('\2%s\n' % name) # cmd send job to queue
            data = s.recv(1024) # receive status
            print repr(data)
        except socket.error as msg:
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

    def destroy(self):
        debugprint ("LpdServer exiting: destroy called")
        self.stop = True

    def probe(self):
        result = []
        for name in self.get_possible_queue_names ():
            while Gtk.events_pending ():
                Gtk.main_iteration ()

            if self.stop:
                break

            found = self.probe_queue(name, result)
            if found == None:
                # Couldn't even connect.
                break

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
        Gdk.threads_enter ()
        result = pysmb.AuthContext.perform_authentication (self)
        Gdk.threads_leave ()
        self._do_perform_authentication_result = result
        self._gui_event.set ()
        
    def perform_authentication (self):
        if (self.passes == 0 or
            not self.has_failed or
            not self.auth_called or
            (self.auth_called and not self.tried_guest)):
            # Safe to call the base function.  It won't try any UI stuff.
            return pysmb.AuthContext.perform_authentication (self)

        self._gui_event.clear ()
        GLib.timeout_add (1, self._do_perform_authentication)
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
            except Exception:
                nonfatalException ()

        # Signal that we've finished.
        if not self.quit:
            self.callback_fn (None)

    def _new_device (self, uri, info, location = None):
        device_dict = { 'device-class': 'network',
                        'device-info': "%s" % info }
        if location:
            device_dict['device-location']=location
        device_dict.update (self._cached_attributes)
        new_device = cupshelpers.Device (uri, **device_dict)
        debugprint ("Device found: %s" % uri)
        self.callback_fn (new_device)

    def _probe_snmp (self):
        # Run the CUPS SNMP backend, pointing it at the host.
        null = file ("/dev/null", "r+")
        try:
            debugprint ("snmp: trying")
            p = subprocess.Popen (args=["/usr/lib/cups/backend/snmp",
                                        self.hostname],
                                  close_fds=True,
                                  stdin=null,
                                  stdout=subprocess.PIPE,
                                  stderr=null)
        except OSError as e:
            debugprint ("snmp: no good")
            if e == errno.ENOENT:
                return

            raise

        (stdout, stderr) = p.communicate ()
        if p.returncode != 0:
            debugprint ("snmp: no good (return code %d)" % p.returncode)
            return

        if self.quit:
            debugprint ("snmp: no good")
            return

        for line in stdout.split ('\n'):
            words = wordsep (line)
            n = len (words)
            if n == 6:
                (device_class, uri, make_and_model,
                 info, device_id, device_location) = words
            elif n == 5:
                (device_class, uri, make_and_model, info, device_id) = words
            elif n == 4:
                (device_class, uri, make_and_model, info) = words
            else:
                continue

            device_dict = { 'device-class': device_class,
                            'device-make-and-model': make_and_model,
                            'device-info': info }
            if n == 5:
                debugprint ("snmp: Device ID found:\n%s" %
                            device_id)
                device_dict['device-id'] = device_id
            if n == 6:
                device_dict['device-location'] = device_location

            device = cupshelpers.Device (uri, **device_dict)
            debugprint ("Device found: %s" % uri)
            self.callback_fn (device)

            # Cache the make and model for use by other search methods
            # that are not able to determine it.
            self._cached_attributes['device-make-and-model'] = make_and_model
            self._cached_attributes['device_id'] = device_id

        debugprint ("snmp: done")

    def _probe_lpd (self):
        debugprint ("lpd: trying")
        lpd = LpdServer (self.hostname)
        for name in lpd.get_possible_queue_names ():
            if self.quit:
                debugprint ("lpd: no good")
                return

            found = lpd.probe_queue (name, [])
            if found == None:
                # Couldn't even connect.
                debugprint ("lpd: couldn't connect")
                break

            if found:
                uri = "lpd://%s/%s" % (self.hostname, name)
                self._new_device(uri, self.hostname)

            if not found and name.startswith ("pr"):
                break

            time.sleep(0.1) # avoid DOS and following counter measures 

        debugprint ("lpd: done")

    def _probe_hplip (self):
        null = file ("/dev/null", "r+")
        try:
            debugprint ("hplip: trying")
            p = subprocess.Popen (args=["hp-makeuri", "-c", self.hostname],
                                  close_fds=True,
                                  stdin=null,
                                  stdout=subprocess.PIPE,
                                  stderr=null)
        except OSError as e:
            if e == errno.ENOENT:
                return

            raise

        (stdout, stderr) = p.communicate ()
        if p.returncode != 0:
            debugprint ("hplip: no good (return code %d)" % p.returncode)
            return

        if self.quit:
            debugprint ("hplip: no good")
            return

        uri = stdout.strip ()
        debugprint ("hplip: uri is %s" % uri)
        if uri.find (":") != -1:
            self._new_device(uri, uri)

        debugprint ("hplip: done")

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
        debugprint ("smb: trying")
        try:
            while smbc_auth.perform_authentication () > 0:
                if self.quit:
                    debugprint ("smb: no good")
                    return

                try:
                    entries = ctx.opendir (uri).getdents ()
                except Exception as e:
                    smbc_auth.failed (e)
        except RuntimeError as e:
            (e, s) = e.args
            if e not in [errno.ENOENT, errno.EACCES, errno.EPERM]:
                debugprint ("Runtime error: %s" % repr ((e, s)))
        except:
            nonfatalException ()

        if self.quit:
            debugprint ("smb: no good")
            return

        for entry in entries:
            if entry.smbc_type == pysmb.smbc.PRINTER_SHARE:
                uri = "smb://%s/%s" % (smburi.urlquote (self.hostname),
                                       smburi.urlquote (entry.name))
                info = "SMB (%s)" % self.hostname
                self._new_device(uri, info)

        debugprint ("smb: done")

    def _probe_jetdirect (self):
        port = 9100    #jetdirect
        sock_address = (self.hostname, port)
        debugprint ("jetdirect: trying")
        s = open_socket(self.hostname, port)
        if not s:
            debugprint ("jetdirect: %s:%d CLOSED" % sock_address)
        else:
            # port is open so assume its a JetDirect device
            debugprint ("jetdirect %s:%d OPEN" % sock_address)
            uri = "socket://%s:%d" % sock_address
            info = "JetDirect (%s)" % self.hostname
            self._new_device(uri, info)
            s.close ()

        debugprint ("jetdirect: done")

    def _probe_ipp (self):
        debugprint ("ipp: trying")
        try:
            ai = socket.getaddrinfo(self.hostname, 631, socket.AF_UNSPEC,
                                    socket.SOCK_STREAM)
        except socket.gaierror:
            debugprint ("ipp: can't resolve %s" % self.hostname)
            debugprint ("ipp: no good")
            return
        for res in ai:
            af, socktype, proto, canonname, sa = res
            if (af == socket.AF_INET and sa[0] == '127.0.0.1' or
                af == socket.AF_INET6 and sa[0] == '::1'):
                debugprint ("ipp: do not probe local cups server")
                debugprint ("ipp: no good")
                return

        try:
            c = cups.Connection (host = self.hostname)
        except RuntimeError:
            debugprint ("ipp: can't connect to server/printer")
            debugprint ("ipp: no good")
            return

        try:
            printers = c.getPrinters ()
        except cups.IPPError:
            debugprint ("%s is probably not a cups server but IPP printer" %
                        self.hostname)
            uri = "ipp://%s:631/ipp" % (self.hostname)
            info = "IPP (%s)" % self.hostname
            self._new_device(uri, info)
            debugprint ("ipp: done")
            return

        for name, queue in printers.iteritems ():
            uri = queue['printer-uri-supported']
            info = queue['printer-info']
            location = queue['printer-location']
            self._new_device(uri, info, location)

        debugprint ("ipp: done")

if __name__ == '__main__':
    import sys
    if len (sys.argv) < 2:
        print "Need printer address"
        sys.exit (1)

    set_debugging (True)
    loop = GObject.MainLoop ()

    def display (device):
        if device == None:
            loop.quit ()

    addr = sys.argv[1]
    p = PrinterFinder ()
    p.find (addr, display)
    loop.run ()

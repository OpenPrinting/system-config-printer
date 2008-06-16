#!/usr/bin/python

## system-config-printer
## CUPS backend
 
## Copyright (C) 2002, 2003, 2006, 2007, 2008 Red Hat, Inc.
## Copyright (C) 2002, 2003, 2006, 2007, 2008 Tim Waugh <twaugh@redhat.com>
 
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

USE_OLD_CODE=False
try:
    import smbc
except ImportError:
    USE_OLD_CODE=True

import errno
import gobject
import gtk
import os
import pwd
from debug import *

class AuthContext:
    def __init__ (self, parent=None, workgroup='', user='', passwd=''):
        self.passes = 0
        self.has_failed = False
        self.auth_called = False
        self.tried_guest = False
        self.cancel = False
        self.use_user = user
        self.use_password = passwd
        self.use_workgroup = workgroup
        self.parent = parent

    def perform_authentication (self):
        self.passes += 1
        if self.passes == 1:
            return 1

        if not self.has_failed:
            return 0

        debugprint ("pysmb: authentication pass: %d" % self.passes)
        if not self.auth_called:
            debugprint ("pysmb: auth callback not called?!")
            self.cancel = True
            return 0

        self.has_failed = False
        if self.auth_called and not self.tried_guest:
            self.use_user = 'guest'
            self.use_password = ''
            self.tried_guest = True
            debugprint ("pysmb: try auth as guest")
            return 1

        self.auth_called = False

        # After that, prompt
        d = gtk.Dialog ("Authentication", self.parent,
                        gtk.DIALOG_MODAL | gtk.DIALOG_NO_SEPARATOR,
                        (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                         gtk.STOCK_OK, gtk.RESPONSE_OK))
        d.set_default_response (gtk.RESPONSE_OK)
        d.set_border_width (6)
        d.set_resizable (False)
        hbox = gtk.HBox (False, 12)
        hbox.set_border_width (6)
        image = gtk.Image ()
        image.set_from_stock (gtk.STOCK_DIALOG_AUTHENTICATION,
                              gtk.ICON_SIZE_DIALOG)
        hbox.pack_start (image, False, False, 0)
        vbox = gtk.VBox (False, 12)
        label = gtk.Label ('<span weight="bold" size="larger">' +
                           "You must log in to access %s." % self.for_server +
                           '</span>')
        label.set_use_markup (True)
        label.set_alignment (0, 0)
        label.set_line_wrap (True)
        vbox.pack_start (label, False, False, 0)

        table = gtk.Table (3, 2)
        table.set_row_spacings (6)
        table.set_col_spacings (6)
        table.attach (gtk.Label ("Username:"), 0, 1, 0, 1, 0, 0)
        username_entry = gtk.Entry ()
        table.attach (username_entry, 1, 2, 0, 1, 0, 0)
        table.attach (gtk.Label ("Domain:"), 0, 1, 1, 2, 0, 0)
        domain_entry = gtk.Entry ()
        table.attach (domain_entry, 1, 2, 1, 2, 0, 0)
        table.attach (gtk.Label ("Password:"), 0, 1, 2, 3, 0, 0)
        password_entry = gtk.Entry ()
        password_entry.set_activates_default (True)
        password_entry.set_visibility (False)
        table.attach (password_entry, 1, 2, 2, 3, 0, 0)
        vbox.pack_start (table, False, False, 0)
        hbox.pack_start (vbox, False, False, 0)
        d.vbox.pack_start (hbox)
        d.show_all ()

        if self.use_user == 'guest':
            self.use_user = pwd.getpwuid (os.getuid ())[0]
            debugprint ("pysmb: try as %s" % self.use_user)
        username_entry.set_text (self.use_user)
        domain_entry.set_text (self.use_workgroup)
        response = d.run ()
        d.hide ()

        if response == gtk.RESPONSE_CANCEL:
            self.cancel = True
            return -1

        self.use_user = username_entry.get_text ()
        self.use_password = password_entry.get_text ()
        self.use_workgroup = domain_entry.get_text ()
        return 1

    def initial_authentication (self):
        pass

    def failed (self, exc=None):
        self.has_failed = True
        debugprint ("pysmb: operation failed: %s" % repr (exc))

        if exc:
            if (self.cancel or
                (type (exc) == RuntimeError and
                 not (exc.args[0] in [errno.EACCES, errno.EPERM]))):
                    raise exc

    def callback (self, server, share, workgroup, user, password):
        debugprint ("pysmb: got password callback")
        self.auth_called = True
        self.for_server = server
        self.for_share = share
        if self.passes == 1:
            self.initial_authentication ()

        if self.use_user:
            if self.use_workgroup:
                workgroup = self.use_workgroup

            return (workgroup, self.use_user, self.use_password)

        user = ''
        password = ''
        return (workgroup, user, password)

###########################
######## OLD CODE #########
###########################
import os
import sys
import re

nmblookup = "/usr/bin/nmblookup"
smbclient = "/usr/bin/smbclient"

wins = None

def get_wins_server():
        smbconf = "/etc/samba/smb.conf"
        wsregex = re.compile("\s*wins\s*server.*",re.IGNORECASE)
	
	global wins	

	if wins:
		return
	
        try:    
                file = open(smbconf, 'r')
        except IOError:
                return

        for l in file.readlines():
                t = l.splitlines()
                if wsregex.match(t[0]):
                        sp = t[0].split('=');
                        winslist = sp[1] 
                        winslist = winslist.lstrip()
                        winslist = winslist.rstrip()
         
                        file.close()
                        winstab = winslist.split(",")
        		# for now we only take the first wins server 
			wins = winstab[0]
         
        file.close()
        return

def get_domain_list ():
    domains = {}
    global wins

    if not os.access (smbclient, os.X_OK):
        return domains

    get_wins_server()

    ips = []
    if wins:
    	os.environ['WINS'] = wins
    	str = 'LC_ALL=C %s -U "$WINS" -M -- - 2>&1' % (nmblookup)
    else:
    	str = "LC_ALL=C %s -M -- - 2>&1" % (nmblookup)
    for l in os.popen (str, 'r').readlines ():
	l = l.splitlines()[0]
	if l.endswith("<01>"):
            ips.append (l.split(" ")[0])
    if len (ips) <= 0:
        if wins:
	    os.environ['WINS'] = wins
            str = 'LC_ALL=C %s -U "$WINS" "*" 2>&1' % (nmblookup)
	else:
            str = "LC_ALL=C %s '*' 2>&1" % (nmblookup)
	for l in os.popen (str, 'r').readlines ():
            l = l.splitlines()[0]
	    ips.append (l.split(" ")[0])

    for ip in ips:
        dom = None
    	dict = { 'IP': ip }
	os.environ["IP"] = ip
	if wins:
		os.environ["WINS"] = wins
    		str = 'LC_ALL=C %s -U "$WINS" -A "$IP"' % (nmblookup)
	else:
    		str = 'LC_ALL=C %s -A "$IP"' % (nmblookup)
	str += " 2>&1"
	for line in os.popen(str, 'r').readlines():
		line = line.splitlines()[0]
		if (line.find(" <00> ") != -1) and (line.find("<GROUP>") != -1):
			dom = line.split(" ")[0]
			dom = dom.lstrip()
			dict['IP'] = ip
			dict['DOMAIN'] = dom
				
	if dom:
		domains[dom] = dict
    
    return domains


def get_host_list(dmbip):
        serverlist = 0
	hosts = {}
	list = []
	global wins
        shareregex = re.compile("\s*Sharename\s*Type\s*Comment")
        serverregex = re.compile("\s*Server\s*Comment")
        domainregex = re.compile("\s*Workgroup\s*Master")
        commentregex = re.compile("(\s*-+)+")
	os.environ["DMBIP"] = dmbip
	str = 'LC_ALL=C %s -N -L "//$DMBIP" 2>/dev/null' % (smbclient)
        for l in os.popen (str, 'r').readlines ():
                l = l.splitlines()[0]

                if serverregex.match(l):
                        serverlist = 1
                elif shareregex.match(l):
                        serverlist = 0
                elif domainregex.match(l):
                        serverlist = 0
                elif commentregex.match(l):
                        continue
                elif serverlist == 1:
			l = l.split (" ")[0].lstrip()
			if not l:
                        	continue
			list.append(l)

	for name in list:	
		dict = { 'NAME': name }
		# if there are a lot of servers it takes too much time
		# so commented out
		#
		#if wins:
		#	str = nmblookup + " -U " + wins + " " +name
		#else:
		#	str = nmblookup + " " + name
        	#for l in os.popen (str, 'r').readlines ():
		#	if l.endswith("<00>") != False:
		#		dict['IP'] = l.split(" ")[0]
		#	else:
		#		continue
		
		hosts[name] = dict

	return hosts

def get_host_list_from_domain (domain):
    hosts = {}
    global wins
    ips = []
    if wins:
    	str = "LC_ALL=C %s -U %s -R '%s' 2>&1" % (nmblookup, wins, domain)
    else:
    	str = "LC_ALL=C %s -R '%s' 2>&1" % (nmblookup, domain)
    for l in os.popen (str, 'r').readlines ():
	l = l.splitlines()[0]
	if l.endswith("<00>"):
            ips.append (l.split(" ")[0])

    for ip in ips:
        name = None
    	dict = { 'IP': ip }
	os.environ["IP"] = ip
	if wins:
    		os.environ["WINS"] = wins
    		str = 'LC_ALL=C %s -U "$WINS" -A "$IP"' % (nmblookup)
	else:
    		str = 'LC_ALL=C %s -A "$IP"' % (nmblookup)
	str += " 2>&1"
	for line in os.popen(str, 'r').readlines():
		line = line.splitlines()[0]
		if (line.find(" <00> ") != -1) and (line.find("<GROUP>") == -1):
			name = line.split(" ")[0]
			name = name.lstrip()
			dict['NAME'] = name
			dict['DOMAIN'] = domain
				
	if name:
		hosts[name] = dict
    
    return hosts


def get_host_info (smbname):
    """Given an SMB name, returns a host dict for it."""
    dict = { 'NAME': smbname, 'IP': '', 'GROUP': '' }
    global wins
    os.environ["SMBNAME"] = smbname
    if wins:
    	os.environ["WINS"] = wins
    	str = 'LC_ALL=C %s -U "$WINS" -S "$SMBNAME" 2>&1' % (nmblookup)
    else:
    	str = 'LC_ALL=C %s -S "$SMBNAME" 2>&1' % (nmblookup)
    for l in os.popen (str, 'r').readlines ():
        l = l.strip ()
        if l.endswith ("<00>"):
            dict['IP'] = l.split (" ")[0]
            continue

        if l.find (" <00> ") == -1:
            continue

        if l.find (" <GROUP> ") != -1:
            dict['GROUP'] = l.split (" ")[0]
        else:
            name = l.split (" ")[0]
            dict['NAME'] = name

    return dict

def get_printer_list (host):
    """Given a host dict, returns a dict of printer shares for that host.
    The value for a printer share name is its comment."""

    printers = {}
    if not os.access (smbclient, os.X_OK):
        return printers

    os.environ["NAME"] = host['NAME']
    str = 'LC_ALL=C %s -N -L "$NAME" 2>&1' % (smbclient)
    if host.has_key ('IP'):
	os.environ["IP"] = host['IP']
	str += ' -I "$IP"'

    if host.has_key ('GROUP'):
        os.environ["GROUP"] = host['GROUP']
        str += ' -W "$GROUP"'

    section = 0
    typepos = 0
    commentpos = 0
    for l in os.popen (str, 'r'):
        l = l.strip ()
        if l == "":
            continue

        if l[0] == '-':
            section += 1
            if section > 1:
                break

            continue

	if section == 0:
	    if l.find ("Sharename ") != -1:
	        typepos = l.find (" Type ") + 1
                commentpos = l.find (" Comment") + 1
	    continue

        if section != 1:
	    continue

        share = l[:l[typepos:].find (" " + "Printer".ljust (commentpos - typepos, " ")) + typepos].strip ()
	if share == -1 and share.endswith (" Printer"):
            share = l[:- len (" Printer")].strip ()
	if share == -1:
            continue
        rest = l[len (share):].strip ()
        end = rest.find (" ")
        if end == -1:
            type = rest
            comment = ""
        else:
            type = rest[:rest.find (" ")]
            comment = rest[len (type):].strip ()

        if type == "Printer":
            printers[share] = comment

    return printers

def printer_share_accessible (share, group = None, user = None, passwd = None):
    """Returns None if the share is inaccessible.  Otherwise,
    returns a dict with 'GROUP' associated with the workgroup name
    of the server."""

    if not os.access (smbclient, os.X_OK):
        return None

    args = [ smbclient, share ]
    if os.getenv ("KRB5CCNAME"):
        args.append ("-k")
    elif passwd:
        args.append (passwd)
    else:
        args.append ("-N")

    if group:
        args.extend (["-W", group])

    args.extend (["-c", "quit"])
    if user:
        args.extend (["-U", user])

    read, write = os.pipe ()
    pid = os.fork ()
    if pid == 0:
        os.close (read)
        if write != 1:
            os.dup2 (write, 1)
        os.dup2 (1, 2)

        os.environ['LC_ALL'] = 'C'
        os.execv (args[0], args)
        sys.exit (1)

    # Parent
    dict = { 'GROUP': ''}
    os.close (write)
    for l in os.fdopen (read, 'r').readlines ():
        if l.startswith ("Domain=[") and l.find ("]") != -1:
            dict['GROUP'] = l[len("Domain=["):].split ("]")[0]
            break

    pid, status = os.waitpid (pid, 0)
    if status:
        return None

    return dict

if __name__ == '__main__':

    domains = get_domain_list ()
    for domain in domains:
        print domains[domain]
	hosts = get_host_list_from_domain (domain)
	if len(hosts) <= 0:
            print "fallback to get_host_list(IP)"
	    hosts = get_host_list (domains[domain]['IP'])
	print hosts
        for host in hosts:
            print hosts[host]
            printers = get_printer_list (hosts[host])
            print printers

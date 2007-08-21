#!/usr/bin/python

## system-config-printer
## CUPS backend
 
## Copyright (C) 2002, 2003, 2006 Red Hat, Inc.
## Copyright (C) 2002, 2003 Tim Waugh <twaugh@redhat.com>
 
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
import signal
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
    signal.signal (signal.SIGCHLD, signal.SIG_DFL)
    if wins:
    	str = "LC_ALL=C %s -U %s -M -- - 2>&1" % (nmblookup, wins)
    else:
    	str = "LC_ALL=C %s -M -- - 2>&1" % (nmblookup)
    for l in os.popen (str, 'r').readlines ():
	l = l.splitlines()[0]
	if l.endswith("<01>"):
            ips.append (l.split(" ")[0])
    if len (ips) <= 0:
        if wins:
            str = "LC_ALL=C %s -U %s '*' 2>&1" % (nmblookup, wins)
	else:
            str = "LC_ALL=C %s '*' 2>&1" % (nmblookup)
	for l in os.popen (str, 'r').readlines ():
            l = l.splitlines()[0]
	    ips.append (l.split(" ")[0])

    for ip in ips:
        dom = None
    	dict = { 'IP': ip }
	if wins:
    		str = "LC_ALL=C " + nmblookup + " -U " + wins + " -A " + ip
	else:
    		str = "LC_ALL=C %s -A '%s'" % (nmblookup, ip)
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
        signal.signal (signal.SIGCHLD, signal.SIG_DFL)
	str = " %s -N -L //%s 2>/dev/null" % (smbclient, dmbip)
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
	        #signal.signal (signal.SIGCHLD, signal.SIG_DFL)
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

def get_host_info (smbname):
    """Given an SMB name, returns a host dict for it."""
    dict = { 'NAME': smbname, 'IP': '', 'GROUP': '' }
    global wins
    if wins:
    	str = "LC_ALL=C %s -U %s -S '%s' 2>&1" % (nmblookup, wins, smbname)
    else:
    	str = "LC_ALL=C %s -S '%s' 2>&1" % (nmblookup, smbname)
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

    str = "LC_ALL=C %s -N -L '%s' 2>&1" % (smbclient, host['NAME'])
    if host.has_key ('IP'):
	str += " -I '%s'" % host['IP']

    if host.has_key ('GROUP'):
        str += " -W '%s'" % host['GROUP']

    signal.signal (signal.SIGCHLD, signal.SIG_DFL)
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
    signal.signal (signal.SIGCHLD, signal.SIG_DFL)
    pid = os.fork ()
    if pid == 0:
        os.close (read)
        if write != 1:
            os.dup2 (write, 1)
        os.dup2 (1, 2)

        os.environ['LANG'] = 'C'
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
        hosts = get_host_list (domains[domain]['IP'])
        for host in hosts:
            print hosts[host]
            printers = get_printer_list (hosts[host])
            print printers

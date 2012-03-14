#!/usr/bin/python

## system-config-printer

## Copyright (C) 2006, 2007, 2008, 2009, 2011, 2012 Red Hat, Inc.
## Copyright (C) 2006, 2007 Florian Festi <ffesti@redhat.com>
## Copyright (C) 2006, 2007, 2008, 2009 Tim Waugh <twaugh@redhat.com>

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

import urllib

def urlquote (x):
    q = urllib.quote (x)
    for c in ["/", "@", ":"]:
        q = q.replace (c, "%%%02X" % ord (c))

    return q

class SMBURI:
    def __init__ (self,
                  uri=None,
                  group='', host='', share='', user='', password=''):
        if uri:
            if group or host or share or user or password:
                raise RuntimeError

            uri = uri.encode ('utf-8')
            if uri.startswith ("smb://"):
                uri = uri[6:]

            self.uri = uri
        else:
            self.uri = self._construct (group, host, share,
                                        user=user, password=password)

    def _construct (self, group, host, share, user='', password=''):
        uri_password = ''
        if password:
            uri_password = ':' + urlquote (password)
        if user:
            uri_password += '@'
        uri = "%s%s%s" % (urlquote (user),
                          uri_password,
                          urlquote (group))
        if len (group) > 0:
            uri += '/'
        uri += urlquote (host)
        if len (share) > 0:
            uri += "/" + urlquote (share)
        return uri

    def get_uri (self):
        return self.uri

    def sanitize_uri (self):
        group, host, share, user, password = self.separate ()
        return self._construct (group, host, share)

    def separate (self):
        uri = self.get_uri ()
        user = ''
        password = ''
        auth = uri.find ('@')
        if auth != -1:
            u = uri[:auth].find(':')
            if u != -1:
                user = uri[:u]
                password = uri[u + 1:auth]
            else:
                user = uri[:auth]
            uri = uri[auth + 1:]
        sep = uri.count ('/')
        group = ''
        if sep == 2:
            g = uri.find('/')
            group = uri[:g]
            uri = uri[g + 1:]
        if sep < 1:
            host = ''
        else:
            h = uri.find('/')
            host = uri[:h]
            uri = uri[h + 1:]
            p = host.find(':')
            if p != -1:
                host = host[:p]
        share = uri
        return (urllib.unquote (group), urllib.unquote (host),
                urllib.unquote (share),
                urllib.unquote (user), urllib.unquote (password))

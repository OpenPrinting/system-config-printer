#!/usr/bin/env python

## Copyright (C) 2007, 2008, 2009 Red Hat, Inc.
## Copyright (C) 2008 Novell, Inc.
## Authors: Tim Waugh <twaugh@redhat.com>, Vincent Untz

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
import gobject
import gtk
import os

import asyncipp
import asyncpk1
import asyncpk0
import authconn
import config
from debug import *
import debug

def set_gettext_function (x):
    asyncipp.set_gettext_function (x)

######
###### A class to keep track of what we're trying to achieve in order
###### to display that to the user if authentication is required.
######
class SemanticOperations(object):
    def __init__ (self):
        self._operation_stack = []

    def _begin_operation (self, operation):
        self._operation_stack.append (operation)

    def _end_operation (self):
        self._operation_stack.pop ()

    def current_operation (self):
        try:
            return self._operation_stack[0]
        except IndexError:
            return None

######
###### An asynchronous libcups API using IPP or PolicyKit as
###### appropriate.
######

class Connection(SemanticOperations):
    def __init__ (self, reply_handler=None, error_handler=None,
                  auth_handler=None, host=None, port=None, encryption=None,
                  parent=None, try_as_root=True, prompt_allowed=True):
        super (Connection, self).__init__ ()

        # Decide whether to use direct IPP or PolicyKit.
        if host == None:
            host = cups.getServer()
        use_pk = ((host.startswith ('/') or host == 'localhost') and
                  os.getuid () != 0)

        if use_pk and try_as_root:
            if config.WITH_POLKIT_1:
                debugprint ("Using polkit-1 connection class")
                c = asyncpk1.PK1Connection (reply_handler=reply_handler,
                                            error_handler=error_handler,
                                            host=host, port=port,
                                            encryption=encryption,
                                            parent=parent)
                self._conn = c
            else:
                debugprint ("Using PolicyKit (pre-polkit-1) connection class")
                c = asyncpk0.PK0Connection (reply_handler=reply_handler,
                                            error_handler=error_handler,
                                            host=host, port=port,
                                            encryption=encryption,
                                            parent=parent)
                self._conn = c
        else:
            debugprint ("Using IPP connection class")
            c = asyncipp.IPPAuthConnection (reply_handler=reply_handler,
                                            error_handler=error_handler,
                                            auth_handler=auth_handler,
                                            host=host, port=port,
                                            encryption=encryption,
                                            parent=parent,
                                            try_as_root=try_as_root,
                                            prompt_allowed=prompt_allowed,
                                            semantic=self)
            self._conn = c

        methodtype = type (self._conn.getPrinters)
        instancemethodtype = type (self._conn.getDevices)
        bindings = []
        for fname in dir (self._conn):
            if fname.startswith ('_'):
                continue
            fn = getattr (self._conn, fname)
            if type (fn) != methodtype and type (fn) != instancemethodtype:
                continue
            if not hasattr (self, fname):
                setattr (self, fname, self._make_binding (fn))
                bindings.append (fname)

        self._bindings = bindings
        debugprint ("+%s" % self)

    def __del__ (self):
        debug.debugprint ("-%s" % self)

    def __eq__ (self, other):
        # We want to be able to be compared as equal to our captured
        # connection class.
        return self._conn == other

    def __ne__ (self, other):
        return self._conn != other

    def destroy (self):
        debugprint ("DESTROY: %s" % self)
        try:
            self._conn.destroy ()
        except AttributeError:
            pass

        for binding in self._bindings:
            delattr (self, binding)

    def _make_binding (self, fn):
        return lambda *args, **kwds: fn (*args, **kwds)

    def set_auth_info (self, password):
        """Call this from your auth_handler function."""
        self.thread.set_auth_info (password)

if __name__ == "__main__":
    # Demo
    set_debugging (True)
    gobject.threads_init ()

    class Test:
        def __init__ (self):
            self._conn = Connection ()
            debugprint ("+%s" % self)

        def __del__ (self):
            debug.debugprint ("-%s" % self)

        def destroy (self):
            debugprint ("DESTROY: %s" % self)
            self._conn.destroy ()
            loop.quit ()

        def getDevices (self):
            self._conn.getDevices (reply_handler=self.getDevices_reply,
                                   error_handler=self.getDevices_error)

        def getDevices_reply (self, conn, result):
            print result
            self.destroy ()

        def getDevices_error (self, conn, exc):
            print repr (exc)
            self.destroy ()

    t = Test ()
    loop = gobject.MainLoop ()
    t.getDevices ()
    loop.run ()

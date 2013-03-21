#!/usr/bin/python

## Copyright (C) 2007, 2008, 2009, 2010, 2012, 2013 Red Hat, Inc.
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
## Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import cups
import os

import config
from debug import *
import debug

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
###### Destructible method call.  Required so that all references can
###### be dropped when an asynchronous method call is destroyed.
######
class _AsyncMethodCall:
    def __init__ (self, fn, reply_handler, error_handler, auth_handler):
        self._fn = fn
        self._reply_handler = reply_handler
        self._error_handler = error_handler
        self._auth_handler = auth_handler
        self._destroyed = False
        debugprint ("+%s" % self)

    def __del__ (self):
        debugprint ("-%s" % self)

    def destroy (self):
        if self._destroyed:
            return

        debugprint ("DESTROY: %s" % self)
        self._destroyed = True
        self._reply_handler = None
        self._error_handler = None
        self._auth_handler = None
        self._reply_data = None
        self._error_data = None
        self._auth_data = None

    def run (self, *args, **kwds):
        self._reply_data = kwds.get ('reply_handler')
        self._error_data = kwds.get ('error_handler')
        self._auth_data = kwds.get ('auth_handler')
        kwds['reply_handler'] = self.reply_handler
        kwds['error_handler'] = self.error_handler
        kwds['auth_handler'] = self.auth_handler
        debugprint ("%s: calling %s" % (self, self._fn))
        self._fn (*args, **kwds)

    def reply_handler (self, *args):
        if not self._destroyed:
            debugprint ("%s: to reply_handler at %s" % (self,
                                                        self._reply_handler))
            self._reply_handler (self, self._reply_data, *args)

    def error_handler (self, *args):
        if not self._destroyed:
            debugprint ("%s: to error_handler at %s" % (self,
                                                        self._error_handler))
            self._error_handler (self, self._error_data, *args)

    def auth_handler (self, *args):
        if not self._destroyed:
            debugprint ("%s: to auth_handler at %s" % (self,
                                                       self._auth_handler))
            self._auth_handler (self, self.auth_data, *args)

######
###### An asynchronous libcups API using IPP or PolicyKit as
###### appropriate.
######

class Connection(SemanticOperations):
    def __init__ (self, reply_handler=None, error_handler=None,
                  auth_handler=None, host=None, port=None, encryption=None,
                  parent=None, try_as_root=True, prompt_allowed=True):
        super (Connection, self).__init__ ()

        self._destroyed = False

        # Decide whether to use direct IPP or PolicyKit.
        if host == None:
            host = cups.getServer()
        use_pk = ((host.startswith ('/') or host == 'localhost') and
                  os.getuid () != 0)

        def subst_reply_handler (conn, reply):
            self._subst_reply_handler (None, reply_handler, reply)

        def subst_error_handler (conn, exc):
            self._subst_error_handler (None, error_handler, exc)

        def subst_auth_handler (prompt, conn, method, resource):
            self._subst_auth_handler (None, auth_handler, prompt, method, resource)

        if use_pk and try_as_root:
            debugprint ("Using polkit-1 connection class")
            import asyncpk1
            c = asyncpk1.PK1Connection (reply_handler=subst_reply_handler,
                                        error_handler=subst_error_handler,
                                        host=host, port=port,
                                        encryption=encryption,
                                        parent=parent)
            self._conn = c
        else:
            debugprint ("Using IPP connection class")
            import asyncipp
            c = asyncipp.IPPAuthConnection (reply_handler=subst_reply_handler,
                                            error_handler=subst_error_handler,
                                            auth_handler=subst_auth_handler,
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
        self._methodcalls = []
        debugprint ("+%s" % self)

    def __del__ (self):
        debug.debugprint ("-%s" % self)

    def destroy (self):
        debugprint ("DESTROY: %s" % self)
        self._destroyed = True
        try:
            self._conn.destroy ()
        except AttributeError:
            pass

        for methodcall in self._methodcalls:
            methodcall.destroy ()

        for binding in self._bindings:
            delattr (self, binding)

    def _make_binding (self, fn):
        return lambda *args, **kwds: self._call_function (fn, *args, **kwds)

    def _call_function (self, fn, *args, **kwds):
        methodcall = _AsyncMethodCall (fn,
                                       self._subst_reply_handler,
                                       self._subst_error_handler,
                                       self._subst_auth_handler)
        self._methodcalls.append (methodcall)
        methodcall.run (*args, **kwds)

    def _subst_reply_handler (self, methodcall, reply_handler, *args):
        if methodcall:
            methodcall.destroy ()
            i = self._methodcalls.index (methodcall)
            del self._methodcalls[i]
            args = args[1:]
        if reply_handler and not self._destroyed:
            debugprint ("%s: chaining up to %s" % (self, reply_handler))
            reply_handler (self, *args)

    def _subst_error_handler (self, methodcall, error_handler, *args):
        if methodcall:
            methodcall.destroy ()
            i = self._methodcalls.index (methodcall)
            del self._methodcalls[i]
            args = args[1:]
        if error_handler and not self._destroyed:
            debugprint ("%s: chaining up to %s" % (self, error_handler))
            error_handler (self, *args)

    def _subst_auth_handler (self, methodcall, auth_handler, prompt, method, resource):
        if methodcall:
            methodcall.destroy ()
            i = self._methodcalls.index (methodcall)
            del self._methodcalls[i]
        if auth_handler and not self._destroyed:
            debugprint ("%s: chaining up to %s" % (self, auth_handler))
            auth_handler (prompt, self, method, resource)

    def set_auth_info (self, password):
        """Call this from your auth_handler function."""
        self.thread.set_auth_info (password)

if __name__ == "__main__":
    # Demo
    from gi.repository import GObject
    set_debugging (True)
    GObject.threads_init ()

    class Test:
        def __init__ (self, quit):
            self._conn = Connection ()
            self._quit = quit
            debugprint ("+%s" % self)

        def __del__ (self):
            debug.debugprint ("-%s" % self)

        def destroy (self):
            debugprint ("DESTROY: %s" % self)
            self._conn.destroy ()
            if self._quit:
                loop.quit ()

        def getDevices (self):
            self._conn.getDevices (reply_handler=self.getDevices_reply,
                                   error_handler=self.getDevices_error)

        def getDevices_reply (self, conn, result):
            print conn, result
            self.destroy ()

        def getDevices_error (self, conn, exc):
            print repr (exc)
            self.destroy ()

    t = Test (False)
    loop = GObject.MainLoop ()
    t.getDevices ()
    t.destroy ()

    t = Test (True)
    t.getDevices ()
    loop.run ()

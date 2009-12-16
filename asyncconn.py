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
import authconn
import config
from debug import *

_ = lambda x: x
N_ = lambda x: x
def set_gettext_function (fn):
    global _
    _ = fn

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
###### appropriate, with the ability to call synchronously.
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

        if False and use_pk and try_as_root:
            if config.WITH_POLKIT_1:
                debugprint ("Using polkit-1 connection class")
                raise RuntimeError
            else:
                debugprint ("Using PolicyKit (pre-polkit-1) connection class")
                raise RuntimeError
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
        for fname in dir (self._conn):
            if fname.startswith ('_'):
                continue
            fn = getattr (self._conn, fname)
            if type (fn) != methodtype:
                continue
            if not hasattr (self, fname):
                setattr (self, fname, self._make_binding (fn))

    def _make_binding (self, fn):
        return lambda *args, **kwds: self._call_function (fn, *args, **kwds)

    def _sync_reply_handler (self, conn, result):
        self._result = result
        gtk.main_quit ()

    def _sync_error_handler (self, conn, error):
        self._error = error
        gtk.main_quit ()

    def _call_function (self, fn, *args, **kwds):
        if (kwds.has_key ("reply_handler") or
            kwds.has_key ("error_handler")):
            # Call asynchronously.
            return fn (*args, **kwds)

        # Call synchronously.
        if self.__dict__.has_key ("_result"):
            del self._result
        if self.__dict__.has_key ("_error"):
            del self._error

        kwds["reply_handler"] = self._sync_reply_handler
        kwds["error_handler"] = self._sync_error_handler
        def deferred_call ():
            fn (*args, **kwds)
        gobject.idle_add (deferred_call)
        debugprint ("Re-enter main")
        gtk.main ()
        debugprint ("Left main")
        try:
            return self._result
        except AttributeError:
            raise self._error

    def set_auth_info (self, password):
        """Call this from your auth_handler function."""
        self.thread.set_auth_info (password)

if __name__ == "__main__":
    # Demo
    set_debugging (True)
    gobject.threads_init ()
    c = Connection ()
    print c.getDevices ()

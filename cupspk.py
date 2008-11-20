# vim: set ts=4 sw=4 et: coding=UTF-8
#
# Copyright (C) 2008 Novell, Inc.
#
# Authors: Vincent Untz
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
#

# check FIXME/TODO here
# check FIXME/TODO in cups-pk-helper
# define fine-grained policy (more than one level of permission)
# add missing methods

import os

import tempfile

import cups
import dbus
import gtk

from dbus.mainloop.glib import DBusGMainLoop
DBusGMainLoop(set_as_default=True)

PK_AUTH_NAME  = 'org.freedesktop.PolicyKit.AuthenticationAgent'
PK_AUTH_PATH  = '/'
PK_AUTH_IFACE = 'org.freedesktop.PolicyKit.AuthenticationAgent'

CUPS_PK_NAME  = 'org.opensuse.CupsPkHelper.Mechanism'
CUPS_PK_PATH  = '/'
CUPS_PK_IFACE = 'org.opensuse.CupsPkHelper.Mechanism'

CUPS_PK_NEED_AUTH = 'org.opensuse.CupsPkHelper.Mechanism.NotPrivileged'


pk_auth_ret = False
pk_auth_error = None
pk_auth_running = False
pk_auth_done = False

def _pk_auth_reply_handler(ret):
    global pk_auth_ret
    global pk_auth_done

    pk_auth_ret = ret
    pk_auth_done = True

def _pk_auth_error_handler(e):
    global pk_auth_error
    global pk_auth_done

    pk_auth_error = str(e)
    pk_auth_done = True


# we can't subclass cups.Connection, even when adding
# Py_TPFLAGS_BASETYPE to cupsconnection.c
# So we'll hack this...
class Connection:
    def __init__(self, host, port, encryption):
        self._parent = None
        self._session_bus = dbus.SessionBus()
        self._system_bus = dbus.SystemBus()

        self._connection = cups.Connection(host=host,
                                           port=port,
                                           encryption=encryption)

        self._hack_subclass()


    def _hack_subclass(self):
        # here's how to subclass without really subclassing. Just provide
        # the same methods
        methodtype = type(self._connection.getPrinters)
        for fname in dir(self._connection):
            if fname[0] == '_':
                continue
            fn = getattr(self._connection, fname)
            if type(fn) != methodtype:
                continue
            if not hasattr(self, fname):
                setattr(self, fname, fn.__call__)


    def set_parent(self, parent):
        self._parent = parent


    def _get_cups_pk(self):
        try:
            object = self._system_bus.get_object(CUPS_PK_NAME, CUPS_PK_PATH)
            return dbus.Interface(object, CUPS_PK_IFACE)
        except dbus.exceptions.DBusException:
            return None


    def _obtain_auth(self, action, xid = 0):
        global pk_auth_ret
        global pk_auth_error
        global pk_auth_done
        global pk_auth_running

        if pk_auth_running:
            # FIXME: raise an exception: this should really never happen
            return False

        pk_auth_ret = False
        pk_auth_error = None
        pk_auth_done = False

        pk_auth_object = self._session_bus.get_object(PK_AUTH_NAME, PK_AUTH_PATH)
        pk_auth = dbus.Interface(pk_auth_object, PK_AUTH_IFACE)

        # We're doing this dbus call asynchronously because we want to not
        # freeze the UI while a menu is being destroyed. And the windows might
        # need some repainting while the authorization dialog is displayed.
        pk_auth_running = True

        pk_auth.ObtainAuthorization(action, dbus.UInt32(xid), dbus.UInt32(os.getpid()), reply_handler=_pk_auth_reply_handler, error_handler=_pk_auth_error_handler)

        while not pk_auth_done:
            gtk.main_iteration(True)

        pk_auth_running = False

        if pk_auth_error != None:
            raise dbus.exceptions.DBusException(pk_auth_error)

        if not type(pk_auth_ret) == dbus.Boolean:
            return False

        return pk_auth_ret != 0


    def _handle_exception_with_auth(self, e, fallback, *args, **kwds):
        if e.get_dbus_name() != CUPS_PK_NEED_AUTH:
            fallback(*args, **kwds)
            return False

        tokens = e.get_dbus_message().split(' ', 2)
        if len(tokens) != 3:
            fallback(*args, **kwds)
            return False

        try:
            xid = 0
            if self._parent and getattr(self._parent, 'window') and getattr(self._parent.window, 'xid'):
                xid = self._parent.window.xid

            # FIXME: is xid working?
            ret = self._obtain_auth(tokens[0], xid)
        except dbus.exceptions.DBusException:
            fallback(*args, **kwds)
            return False

        if not ret:
            raise cups.IPPError(cups.IPP_NOT_AUTHORIZED, 'pkcancel')

        return True


    def _call_with_pk_and_fallback(self, use_fallback, pk_function_name, pk_args, fallback_function, *args, **kwds):
        pk_function = None

        if not use_fallback:
            cups_pk = self._get_cups_pk()
            if cups_pk:
                try:
                    pk_function = cups_pk.get_dbus_method(pk_function_name)
                except dbus.exceptions.DBusException:
                    pass

        if use_fallback or not pk_function:
            fallback_function(*args, **kwds)
            return

        while True:
            try:
                # FIXME: async call or not?
                pk_function(*pk_args)
                break
            except dbus.exceptions.DBusException, e:
                if not self._handle_exception_with_auth(e, fallback_function, *args, **kwds):
                    break


    def _args_to_tuple(self, types, *args):
        retval = [ False ]

        if len(types) != len(args):
            retval[0] = True
            # We do this to have the right length for the returned value
            retval.extend(types)
            return tuple(types)

        exception = False

        for i in range(len(types)):
            if type(args[i]) != types[i]:
                if types[i] == str and type(args[i]) == unicode:
                    # we accept a mix between unicode and str
                    pass
                elif types[i] == str and args[i] == None:
                    # None is an empty string for dbus
                    retval.append('')
                    continue
                else:
                    exception = True
            retval.append(args[i])

        retval[0] = exception

        return tuple(retval)


    def _kwds_to_vars(self, names, **kwds):
        ret = []

        for name in names:
            if kwds.has_key(name):
                ret.append(kwds[name])
            else:
                ret.append('')

        return tuple(ret)


#    getPrinters
#    getDests
#    getClasses
#    getPPDs
#    getServerPPD
#    getDocument
#    getDevices
#    getJobs
#    getJobAttributes
#    cancelJob
#    cancelAllJobs
#    authenticateJob
#    setJobHoldUntil
#    restartJob
#    getFile
#    putFile

    def addPrinter(self, *args, **kwds):
        (use_pycups, name) = self._args_to_tuple([str], *args)
        (filename, ppdname, info, location, device, ppd) = self._kwds_to_vars(['filename', 'ppdname', 'info', 'location', 'device', 'ppd'], **kwds)

        need_unlink = False
        if not ppdname and not filename and ppd:
            (fd, filename) = tempfile.mkstemp ()
            ppd.writeFd(fd)
            os.close(fd)
            need_unlink = True

        if filename and not ppdname:
            pk_args = (name, device, filename, info, location)
            self._call_with_pk_and_fallback(use_pycups,
                                            'PrinterAddWithPpdFile', pk_args,
                                            self._connection.addPrinter,
                                            *args, **kwds)
            if need_unlink:
                os.unlink(filename)
        else:
            pk_args = (name, device, ppdname, info, location)
            self._call_with_pk_and_fallback(use_pycups,
                                            'PrinterAdd', pk_args,
                                            self._connection.addPrinter,
                                            *args, **kwds)


    def setPrinterDevice(self, *args, **kwds):
        (use_pycups, name, device) = self._args_to_tuple([str, str], *args)
        pk_args = (name, device)

        self._call_with_pk_and_fallback(use_pycups,
                                        'PrinterSetDevice', pk_args,
                                        self._connection.setPrinterDevice,
                                        *args, **kwds)


    def setPrinterInfo(self, *args, **kwds):
        (use_pycups, name, info) = self._args_to_tuple([str, str], *args)
        pk_args = (name, info)

        self._call_with_pk_and_fallback(use_pycups,
                                        'PrinterSetInfo', pk_args,
                                        self._connection.setPrinterInfo,
                                        *args, **kwds)


    def setPrinterLocation(self, *args, **kwds):
        (use_pycups, name, location) = self._args_to_tuple([str, str], *args)
        pk_args = (name, location)

        self._call_with_pk_and_fallback(use_pycups,
                                        'PrinterSetLocation', pk_args,
                                        self._connection.setPrinterLocation,
                                        *args, **kwds)


    def setPrinterShared(self, *args, **kwds):
        (use_pycups, name, shared) = self._args_to_tuple([str, bool], *args)
        pk_args = (name, shared)

        self._call_with_pk_and_fallback(use_pycups,
                                        'PrinterSetShared', pk_args,
                                        self._connection.setPrinterShared,
                                        *args, **kwds)


    def setPrinterJobSheets(self, *args, **kwds):
        (use_pycups, name, start, end) = self._args_to_tuple([str, str, str], *args)
        pk_args = (name, start, end)

        self._call_with_pk_and_fallback(use_pycups,
                                        'PrinterSetJobSheets', pk_args,
                                        self._connection.setPrinterJobSheets,
                                        *args, **kwds)


    def setPrinterErrorPolicy(self, *args, **kwds):
        (use_pycups, name, policy) = self._args_to_tuple([str, str], *args)
        pk_args = (name, policy)

        self._call_with_pk_and_fallback(use_pycups,
                                        'PrinterSetErrorPolicy', pk_args,
                                        self._connection.setPrinterErrorPolicy,
                                        *args, **kwds)


    def setPrinterOpPolicy(self, *args, **kwds):
        (use_pycups, name, policy) = self._args_to_tuple([str, str], *args)
        pk_args = (name, policy)

        self._call_with_pk_and_fallback(use_pycups,
                                        'PrinterSetOpPolicy', pk_args,
                                        self._connection.setPrinterOpPolicy,
                                        *args, **kwds)


#    setPrinterUsersAllowed
#    setPrinterUsersDenied

    def addPrinterOptionDefault(self, *args, **kwds):
        #FIXME: value can be a sequence (need to fix dbus API too)
        (use_pycups, name, option, value) = self._args_to_tuple([str, str, str], *args)
        pk_args = (name, option, value)

        self._call_with_pk_and_fallback(use_pycups,
                                        'PrinterAddOptionDefault', pk_args,
                                        self._connection.addPrinterOptionDefault,
                                        *args, **kwds)


    def deletePrinterOptionDefault(self, *args, **kwds):
        (use_pycups, name, option) = self._args_to_tuple([str, str], *args)
        pk_args = (name, option)

        self._call_with_pk_and_fallback(use_pycups,
                                        'PrinterDeleteOptionDefault', pk_args,
                                        self._connection.deletePrinterOptionDefault,
                                        *args, **kwds)


    def deletePrinter(self, *args, **kwds):
        (use_pycups, name) = self._args_to_tuple([str], *args)
        pk_args = (name,)

        self._call_with_pk_and_fallback(use_pycups,
                                        'PrinterDelete', pk_args,
                                        self._connection.deletePrinter,
                                        *args, **kwds)

#    getPrinterAttributes
#    addPrinterToClass
#    deletePrinterFromClass
#    deleteClass
#    getDefault

    def setDefault(self, *args, **kwds):
        (use_pycups, name) = self._args_to_tuple([str], *args)
        pk_args = (name,)

        self._call_with_pk_and_fallback(use_pycups,
                                        'PrinterSetDefault', pk_args,
                                        self._connection.setDefault,
                                        *args, **kwds)

#    getPPD

    def enablePrinter(self, *args, **kwds):
        (use_pycups, name) = self._args_to_tuple([str], *args)
        pk_args = (name, True)

        self._call_with_pk_and_fallback(use_pycups,
                                        'PrinterSetEnabled', pk_args,
                                        self._connection.enablePrinter,
                                        *args, **kwds)


    def disablePrinter(self, *args, **kwds):
        (use_pycups, name) = self._args_to_tuple([str], *args)
        pk_args = (name, False)

        self._call_with_pk_and_fallback(use_pycups,
                                        'PrinterSetEnabled', pk_args,
                                        self._connection.enablePrinter,
                                        *args, **kwds)


    def acceptJobs(self, *args, **kwds):
        (use_pycups, name) = self._args_to_tuple([str], *args)
        pk_args = (name, True, '')

        self._call_with_pk_and_fallback(use_pycups,
                                        'PrinterSetAcceptJobs', pk_args,
                                        self._connection.acceptJobs,
                                        *args, **kwds)


    def rejectJobs(self, *args, **kwds):
        (use_pycups, name) = self._args_to_tuple([str], *args)
        (reason,) = self._kwds_to_vars(['reason'], **kwds)
        pk_args = (name, False, reason)

        self._call_with_pk_and_fallback(use_pycups,
                                        'PrinterSetAcceptJobs', pk_args,
                                        self._connection.rejectJobs,
                                        *args, **kwds)


#    printTestPage
#    adminGetServerSettings
#    adminSetServerSettings
#    getSubscriptions
#    createSubscription
#    getNotifications
#    cancelSubscription
#    renewSubscription
#    printFile
#    printFiles

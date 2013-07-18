# vim: set ts=4 sw=4 et: coding=UTF-8
#
# Copyright (C) 2008, 2013 Novell, Inc.
# Copyright (C) 2008, 2009, 2010, 2012 Red Hat, Inc.
# Copyright (C) 2008, 2009, 2010, 2012 Tim Waugh <twaugh@redhat.com>
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#

# check FIXME/TODO here
# check FIXME/TODO in cups-pk-helper
# define fine-grained policy (more than one level of permission)
# add missing methods

import os
import sys

import tempfile

import cups
import dbus
from debug import debugprint

from dbus.mainloop.glib import DBusGMainLoop
DBusGMainLoop(set_as_default=True)

CUPS_PK_NAME  = 'org.opensuse.CupsPkHelper.Mechanism'
CUPS_PK_PATH  = '/'
CUPS_PK_IFACE = 'org.opensuse.CupsPkHelper.Mechanism'

CUPS_PK_NEED_AUTH = 'org.opensuse.CupsPkHelper.Mechanism.NotPrivileged'


# we can't subclass cups.Connection, even when adding
# Py_TPFLAGS_BASETYPE to cupsconnection.c
# So we'll hack this...
class Connection:
    def __init__(self, host, port, encryption):
        self._parent = None

        try:
            self._session_bus = dbus.SessionBus()
            self._system_bus = dbus.SystemBus()
        except dbus.exceptions.DBusException:
            # One or other bus not running.
            self._session_bus = self._system_bus = None

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
            # Failed to get object or interface.
            return None
        except AttributeError:
            # No system D-Bus
            return None


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
            return fallback_function(*args, **kwds)

        pk_retval = 'PolicyKit communication issue'

        while True:
            try:
                # FIXME: async call or not?
                pk_retval = pk_function(*pk_args)

                # if the PK call has more than one return values, we pop the
                # first one as the error message
                if type(pk_retval) == tuple:
                    retval = pk_retval[1:]
                    # if there's no error, then we can safely return what we
                    # got
                    if pk_retval[0] == '':
                        # if there's only one item left in the tuple, we don't
                        # want to return the tuple, but the item
                        if len(retval) == 1:
                            return retval[0]
                        else:
                            return retval
                break
            except dbus.exceptions.DBusException as e:
                if e.get_dbus_name() == CUPS_PK_NEED_AUTH:
                    raise cups.IPPError(cups.IPP_NOT_AUTHORIZED, 'pkcancel')

                break

        # The PolicyKit call did not work (either a PK-error and we got a dbus
        # exception that wasn't handled, or an error in the mechanism itself)
        if pk_retval != '':
            debugprint ('PolicyKit call to %s did not work: %s' %
                        (pk_function_name, repr (pk_retval)))
            return fallback_function(*args, **kwds)


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
                elif types[i] == str and type(args[i]) == int:
                    # we accept a mix between int and str
                    retval.append(str(args[i]))
                    continue
                elif types[i] == str and type(args[i]) == float:
                    # we accept a mix between float and str
                    retval.append(str(args[i]))
                    continue
                elif types[i] == str and type(args[i]) == bool:
                    # we accept a mix between bool and str
                    retval.append(str(args[i]))
                    continue
                elif types[i] == str and args[i] == None:
                    # None is an empty string for dbus
                    retval.append('')
                    continue
                elif types[i] == list and type(args[i]) == tuple:
                    # we accept a mix between list and tuple
                    retval.append(list(args[i]))
                    continue
                elif types[i] == list and args[i] == None:
                    # None is an empty list
                    retval.append([])
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


    def getDevices(self, *args, **kwds):
        use_pycups = False

        limit = 0
        include_schemes = []
        exclude_schemes = []
        timeout = 0

        if len(args) == 4:
            (use_pycups, limit, include_schemes, exclude_schemes, timeout) = self._args_to_tuple([int, str, str, int], *args)
        else:
            if kwds.has_key('timeout'):
                timeout = kwds['timeout']

            if kwds.has_key('limit'):
                limit = kwds['limit']

            if kwds.has_key('include_schemes'):
                include_schemes = kwds['include_schemes']

            if kwds.has_key('exclude_schemes'):
                exclude_schemes = kwds['exclude_schemes']

        pk_args = (timeout, limit, include_schemes, exclude_schemes)

        try:
            result = self._call_with_pk_and_fallback(use_pycups,
                                                     'DevicesGet', pk_args,
                                                     self._connection.getDevices,
                                                     *args, **kwds)
        except TypeError:
            debugprint ("DevicesGet API exception; using old signature")
            if kwds.has_key ('timeout'):
                use_pycups = True

            # Convert from list to string
            if len (include_schemes) > 0:
                include_schemes = reduce (lambda x, y: x + "," + y,
                                          include_schemes)
            else:
                include_schemes = ""

            if len (exclude_schemes) > 0:
                exclude_schemes = reduce (lambda x, y: x + "," + y,
                                          exclude_schemes)
            else:
                exclude_schemes = ""

            pk_args = (limit, include_schemes, exclude_schemes)
            result = self._call_with_pk_and_fallback(use_pycups,
                                                     'DevicesGet', pk_args,
                                                     self._connection.getDevices,
                                                     *args, **kwds)

        # return 'result' if fallback was called
        if len (result.keys()) > 0 and type (result[result.keys()[0]]) == dict:
             return result

        result_str = {}
        if result != None:
            for i in result.keys():
                if type(i) == dbus.String:
                    result_str[str(i)] = str(result[i])
                else:
                    result_str[i] = result[i]

        # cups-pk-helper returns all devices in one dictionary.
        # Keys of different devices are distinguished by ':n' postfix.

        devices = {}
        n = 0
        postfix = ':' + str (n)
        device_keys = [x for x in result_str.keys() if x.endswith(postfix)]
        while len (device_keys) > 0:

            device_uri = None
            device_dict = {}
            for i in device_keys:
                key = i[:len(i) - len(postfix)]
                if key != 'device-uri':
                    device_dict[key] = result_str[i]
                else:
                    device_uri = result_str[i]

            if device_uri != None:
                devices[device_uri] = device_dict

            n += 1
            postfix = ':' + str (n)
            device_keys = [x for x in result_str.keys() if x.endswith(postfix)]

        return devices


#    getJobs
#    getJobAttributes

    def cancelJob(self, *args, **kwds):
        (use_pycups, jobid) = self._args_to_tuple([int], *args)
        pk_args = (jobid, )

        self._call_with_pk_and_fallback(use_pycups,
                                        'JobCancel', pk_args,
                                        self._connection.cancelJob,
                                        *args, **kwds)


#    cancelAllJobs
#    authenticateJob
    def setJobHoldUntil(self, *args, **kwds):
        (use_pycups, jobid, job_hold_until) = self._args_to_tuple([int, str], *args)
        pk_args = (jobid, job_hold_until, )

        self._call_with_pk_and_fallback(use_pycups,
                                        'JobSetHoldUntil', pk_args,
                                        self._connection.setJobHoldUntil,
                                        *args, **kwds)

    def restartJob(self, *args, **kwds):
        (use_pycups, jobid) = self._args_to_tuple([int], *args)
        pk_args = (jobid, )
        
        self._call_with_pk_and_fallback(use_pycups,
                                        'JobRestart', pk_args,
                                        self._connection.restartJob,
                                        *args, **kwds)

    def getFile(self, *args, **kwds):
        ''' Keeping this as an alternative for the code.
            We don't use it because it's not possible to know if the call was a
            PK-one (and so we push the content of a temporary filename to fd or
            file) or a non-PK-one (in which case nothing should be done).

                filename = None
                fd = None
                file = None
                if use_pycups:
                    if len(kwds) != 1:
                        use_pycups = True
                    elif kwds.has_key('filename'):
                        filename = kwds['filename']
                    elif kwds.has_key('fd'):
                        fd = kwds['fd']
                    elif kwds.has_key('file'):
                        file = kwds['file']
                    else:
                        use_pycups = True

                    if fd or file:
        '''

        file_object = None
        fd = None
        if len(args) == 2:
            (use_pycups, resource, filename) = self._args_to_tuple([str, str], *args)
        else:
            (use_pycups, resource) = self._args_to_tuple([str], *args)
            if kwds.has_key('filename'):
                filename = kwds['filename']
            elif kwds.has_key('fd'):
                fd = kwds['fd']
            elif kwds.has_key('file'):
                file_object = kwds['file']
            else:
                if not use_pycups:
                    raise TypeError()
                else:
                    filename = None

        if (not use_pycups) and (fd != None or file_object != None):
            # Create the temporary file in /tmp to ensure that
            # cups-pk-helper-mechanism is able to write to it.
            (tmpfd, tmpfname) = tempfile.mkstemp(dir="/tmp")
            os.close (tmpfd)

            pk_args = (resource, tmpfname)
            self._call_with_pk_and_fallback(use_pycups,
                                            'FileGet', pk_args,
                                            self._connection.getFile,
                                            *args, **kwds)

            tmpfd = os.open (tmpfname, os.O_RDONLY)
            tmpfile = os.fdopen (tmpfd, 'r')
            tmpfile.seek (0)

            if fd != None:
                os.lseek (fd, 0, os.SEEK_SET)
                line = tmpfile.readline()
                while line != '':
                    os.write (fd, line)
                    line = tmpfile.readline()
            else:
                file_object.seek (0)
                line = tmpfile.readline()
                while line != '':
                    file_object.write (line)
                    line = tmpfile.readline()

            tmpfile.close ()
            os.remove (tmpfname)
        else:
            pk_args = (resource, filename)

            self._call_with_pk_and_fallback(use_pycups,
                                            'FileGet', pk_args,
                                            self._connection.getFile,
                                            *args, **kwds)


    def putFile(self, *args, **kwds):
        if len(args) == 2:
            (use_pycups, resource, filename) = self._args_to_tuple([str, str], *args)
        else:
            (use_pycups, resource) = self._args_to_tuple([str], *args)
            if kwds.has_key('filename'):
                filename = kwds['filename']
            elif kwds.has_key('fd'):
                fd = kwds['fd']
            elif kwds.has_key('file'):
                file_object = kwds['file']
            else:
                if not use_pycups:
                    raise TypeError()
                else:
                    filename = None

        if (not use_pycups) and (fd != None or file_object != None):
            (tmpfd, tmpfname) = tempfile.mkstemp()
            os.lseek (tmpfd, 0, os.SEEK_SET)

            if fd != None:
                os.lseek (fd, 0, os.SEEK_SET)
                buf = os.read (fd, 512)
                while buf != '':
                    os.write (tmpfd, buf)
                    buf = os.read (fd, 512)
            else:
                file_object.seek (0)
                line = file_object.readline ()
                while line != '':
                    os.write (tmpfd, line)
                    line = file_object.readline ()

            os.close (tmpfd)

            pk_args = (resource, tmpfname)

            self._call_with_pk_and_fallback(use_pycups,
                                            'FilePut', pk_args,
                                            self._connection.putFile,
                                            *args, **kwds)

            os.remove (tmpfname)
        else:

            pk_args = (resource, filename)

            self._call_with_pk_and_fallback(use_pycups,
                                            'FilePut', pk_args,
                                            self._connection.putFile,
                                            *args, **kwds)


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


    def setPrinterUsersAllowed(self, *args, **kwds):
        (use_pycups, name, users) = self._args_to_tuple([str, list], *args)
        pk_args = (name, users)

        self._call_with_pk_and_fallback(use_pycups,
                                        'PrinterSetUsersAllowed', pk_args,
                                        self._connection.setPrinterUsersAllowed,
                                        *args, **kwds)


    def setPrinterUsersDenied(self, *args, **kwds):
        (use_pycups, name, users) = self._args_to_tuple([str, list], *args)
        pk_args = (name, users)

        self._call_with_pk_and_fallback(use_pycups,
                                        'PrinterSetUsersDenied', pk_args,
                                        self._connection.setPrinterUsersDenied,
                                        *args, **kwds)

    def addPrinterOptionDefault(self, *args, **kwds):
        # The values can be either a single string, or a list of strings, so
        # we have to handle this
        (use_pycups, name, option, value) = self._args_to_tuple([str, str, str], *args)
        # success
        if not use_pycups:
            values = (value,)
        # okay, maybe we directly have values
        else:
            (use_pycups, name, option, values) = self._args_to_tuple([str, str, list], *args)
        pk_args = (name, option, values)

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

    def addPrinterToClass(self, *args, **kwds):
        (use_pycups, printer, name) = self._args_to_tuple([str, str], *args)
        pk_args = (name, printer)

        self._call_with_pk_and_fallback(use_pycups,
                                        'ClassAddPrinter', pk_args,
                                        self._connection.addPrinterToClass,
                                        *args, **kwds)


    def deletePrinterFromClass(self, *args, **kwds):
        (use_pycups, printer, name) = self._args_to_tuple([str, str], *args)
        pk_args = (name, printer)

        self._call_with_pk_and_fallback(use_pycups,
                                        'ClassDeletePrinter', pk_args,
                                        self._connection.deletePrinterFromClass,
                                        *args, **kwds)


    def deleteClass(self, *args, **kwds):
        (use_pycups, name) = self._args_to_tuple([str], *args)
        pk_args = (name,)

        self._call_with_pk_and_fallback(use_pycups,
                                        'ClassDelete', pk_args,
                                        self._connection.deleteClass,
                                        *args, **kwds)

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
                                        self._connection.disablePrinter,
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

    def adminGetServerSettings(self, *args, **kwds):
        use_pycups = False
        pk_args = ()

        result = self._call_with_pk_and_fallback(use_pycups,
                                               'ServerGetSettings', pk_args,
                                               self._connection.adminGetServerSettings,
                                               *args, **kwds)
        settings = {}
        if result != None:
            for i in result.keys():
                if type(i) == dbus.String:
                    settings[str(i)] = str(result[i])
                else:
                    settings[i] = result[i]

        return settings


    def adminSetServerSettings(self, *args, **kwds):
        (use_pycups, settings) = self._args_to_tuple([dict], *args)
        pk_args = (settings,)

        self._call_with_pk_and_fallback(use_pycups,
                                        'ServerSetSettings', pk_args,
                                        self._connection.adminSetServerSettings,
                                        *args, **kwds)


#    getSubscriptions
#    createSubscription
#    getNotifications
#    cancelSubscription
#    renewSubscription
#    printFile
#    printFiles

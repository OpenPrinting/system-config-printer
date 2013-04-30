## system-config-printer

## Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013 Red Hat, Inc.
## Authors:
##  Florian Festi <ffesti@redhat.com>
##  Tim Waugh <twaugh@redhat.com>

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

import cups, pprint, os, tempfile, re, string
import locale
from . import _debugprint
from . import config

class Printer:
    _flags_blacklist = ["options", "local"]

    def __init__(self, name, connection, **kw):
        """
        @param name: printer name
        @type name: string
        @param connection: CUPS connection
        @type connection: CUPS.Connection object
        @param kw: printer attributes
        @type kw: dict indexed by string
        """
        self.name = name
        self.connection = connection
        self.class_members = []
        have_kw = len (kw) > 0
        fetch_attrs = True
        if have_kw:
            self.update (**kw)
            if self.is_class:
                fetch_attrs = True
            else:
                fetch_attrs = False

        if fetch_attrs:
            self.getAttributes ()

        self._ppd = None # load on demand

    def __del__ (self):
        if self._ppd != None:
            os.unlink(self._ppd)

    def __repr__ (self):
        return "<cupshelpers.Printer \"%s\">" % self.name

    def _expand_flags(self):

        def _ascii_lower(str):
            return str.translate(string.maketrans(string.ascii_uppercase,
                                                  string.ascii_lowercase));

        prefix = "CUPS_PRINTER_"
        prefix_length = len(prefix)

        # loop over cups constants
        for name in cups.__dict__:
            if name.startswith(prefix):
                attr_name = \
                    _ascii_lower(name[prefix_length:])
                if attr_name in self._flags_blacklist: continue
                if attr_name == "class": attr_name = "is_class"
                # set as attribute
                setattr(self, attr_name,
                        bool(self.type & getattr(cups, name)))

    def update(self, **kw):
        """
        Update object from printer attributes.

        @param kw: printer attributes
        @type kw: dict indexed by string
        """
        self.state = kw.get('printer-state', 0)
        self.enabled = self.state != cups.IPP_PRINTER_STOPPED
        self.device_uri = kw.get('device-uri', "")
        self.info = kw.get('printer-info', "")
        self.is_shared = kw.get('printer-is-shared', None)
        self.location = kw.get('printer-location', "")
        self.make_and_model = kw.get('printer-make-and-model', "")
        self.type = kw.get('printer-type', 0)
        self.uri_supported = kw.get('printer-uri-supported', "")
        if type (self.uri_supported) != list:
            self.uri_supported = [self.uri_supported]
        self._expand_flags()
        if self.is_shared is None:
            self.is_shared = not self.not_shared
        del self.not_shared
        self.class_members = kw.get('member-names', [])
        if type (self.class_members) != list:
            self.class_members = [self.class_members]
        self.class_members.sort ()
        self.other_attributes = kw

    def getAttributes(self):
        """
        Fetch further attributes for the printer.

        Normally only a small set of attributes is fetched.  This
        method is for fetching more.
        """
        attrs = self.connection.getPrinterAttributes(self.name)
        self.attributes = {}
        self.other_attributes = {}
        self.possible_attributes = {
            'landscape' : ('False', ['True', 'False']),
            'page-border' : ('none', ['none', 'single', 'single-thick',
                                     'double', 'double-thick']),
            }

        for key, value in attrs.iteritems():
            if key.endswith("-default"):
                name = key[:-len("-default")]
                if name in ["job-sheets", "printer-error-policy",
                            "printer-op-policy", # handled below
                            "notify-events", # cannot be set
                            "document-format", # cannot be set
                            "notify-lease-duration"]: # cannot be set
                    continue 

                supported = attrs.get(name + "-supported", None) or \
                            self.possible_attributes.get(name, None) or \
                            ""

                # Convert a list into a comma-separated string, since
                # it can only really have been misinterpreted as a list
                # by CUPS.
                if isinstance (value, list):
                    value = reduce (lambda x, y: x+','+y, value)

                self.attributes[name] = value
                    
                if attrs.has_key(name+"-supported"):
                    supported = attrs[name+"-supported"]
                    self.possible_attributes[name] = (value, supported)
            elif (not key.endswith ("-supported") and
                  key != 'job-sheets-default' and
                  key != 'printer-error-policy' and
                  key != 'printer-op-policy' and
                  not key.startswith ('requesting-user-name-')):
                self.other_attributes[key] = value
        
        self.job_sheet_start, self.job_sheet_end = attrs.get(
            'job-sheets-default', ('none', 'none'))
        self.job_sheets_supported = attrs.get('job-sheets-supported', ['none'])
        self.error_policy = attrs.get('printer-error-policy', 'none')
        self.error_policy_supported = attrs.get(
            'printer-error-policy-supported', ['none'])
        self.op_policy = attrs.get('printer-op-policy', "") or "default"
        self.op_policy_supported = attrs.get(
            'printer-op-policy-supported', ["default"])

        self.default_allow = True
        self.except_users = []
        if attrs.has_key('requesting-user-name-allowed'):
            self.except_users = attrs['requesting-user-name-allowed']
            self.default_allow = False
        elif attrs.has_key('requesting-user-name-denied'):
            self.except_users = attrs['requesting-user-name-denied']
        self.except_users_string = ', '.join(self.except_users)
        self.update (**attrs)

    def getServer(self):
        """
        Find out which server defines this printer.

        @returns: server URI or None
        """
        if not self.uri_supported[0].startswith('ipp://'):
            return None
        uri = self.uri_supported[0][6:]
        uri = uri.split('/')[0]
        uri = uri.split(':')[0]
        if uri == "localhost.localdomain":
            uri = "localhost"
        return uri

    def getPPD(self):
        """
        Obtain the printer's PPD.

        @returns: cups.PPD object, or False for raw queues
        @raise cups.IPPError: IPP error
        """
        result = None
        if self._ppd is None:
            try:
                self._ppd = self.connection.getPPD(self.name)
                result = cups.PPD (self._ppd)
            except cups.IPPError, (e, m):
                if e == cups.IPP_NOT_FOUND:
                    result = False
                else:
                    raise

        if result == None and self._ppd != None:
            result = cups.PPD (self._ppd)

        return result

    def setOption(self, name, value):
        """
        Set a printer's option.

        @param name: option name
        @type name: string
        @param value: option value
        @type value: option-specific
        """
        if isinstance (value, float):
            radixchar = locale.nl_langinfo (locale.RADIXCHAR)
            if radixchar != '.':
                # Convert floats to strings, being careful with decimal points.
                value = str (value).replace (radixchar, '.')
        self.connection.addPrinterOptionDefault(self.name, name, value)

    def unsetOption(self, name):
        """
        Unset a printer's option.

        @param name: option name
        @type name: string
        """
        self.connection.deletePrinterOptionDefault(self.name, name)

    def setEnabled(self, on, reason=None):
        """
        Set the printer's enabled state.

        @param on: whether it will be enabled
        @type on: bool
        @param reason: reason for this state
        @type reason: string
        """
        if on:
            self.connection.enablePrinter(self.name)
        else:
            if reason:
                self.connection.disablePrinter(self.name, reason=reason)
            else:
                self.connection.disablePrinter(self.name)

    def setAccepting(self, on, reason=None):
        """
        Set the printer's accepting state.

        @param on: whether it will be accepting
        @type on: bool
        @param reason: reason for this state
        @type reason: string
        """
        if on:
            self.connection.acceptJobs(self.name)
        else:
            if reason:
                self.connection.rejectJobs(self.name, reason=reason)
            else:
                self.connection.rejectJobs(self.name)

    def setShared(self,on):
        """
        Set the printer's shared state.

        @param on: whether it will be accepting
        @type on: bool
        """
        self.connection.setPrinterShared(self.name, on)

    def setErrorPolicy (self, policy):
        """
        Set the printer's error policy.

        @param policy: error policy
        @type policy: string
        """
        self.connection.setPrinterErrorPolicy(self.name, policy)

    def setOperationPolicy(self, policy):
        """
        Set the printer's operation policy.

        @param policy: operation policy
        @type policy: string
        """
        self.connection.setPrinterOpPolicy(self.name, policy)    

    def setJobSheets(self, start, end):
        """
        Set the printer's job sheets.

        @param start: start sheet
        @type start: string
        @param end: end sheet
        @type end: string
        """
        self.connection.setPrinterJobSheets(self.name, start, end)

    def setAccess(self, allow, except_users):
        """
        Set access control list.

        @param allow: whether to allow by default, otherwise deny
        @type allow: bool
        @param except_users: exception list
        @type except_users: string list
        """
        if isinstance(except_users, str):
            users = except_users.split()
            users = [u.split(",") for u in users]
            except_users = []
            for u in users:
                except_users.extend(u)
            except_users = [u.strip() for u in except_users]
            except_users = filter(None, except_users)
            
        if allow:
            self.connection.setPrinterUsersDenied(self.name, except_users)
        else:
            self.connection.setPrinterUsersAllowed(self.name, except_users)

    def jobsQueued(self, only_tests=False, limit=None):
        """
        Find out whether jobs are queued for this printer.

        @param only_tests: whether to restrict search to test pages
        @type only_tests: bool
        @returns: list of job IDs
        """
        ret = []
        try:
            try:
                r = ['job-id', 'job-printer-uri', 'job-name']
                jobs = self.connection.getJobs (requested_attributes=r)
            except TypeError:
                # requested_attributes requires pycups 1.9.50
                jobs = self.connection.getJobs ()
        except cups.IPPError:
            return ret

        for id, attrs in jobs.iteritems():
            try:
                uri = attrs['job-printer-uri']
                uri = uri[uri.rindex ('/') + 1:]
            except:
                continue
            if uri != self.name:
                continue

            if (not only_tests or
                (attrs.has_key ('job-name') and
                 attrs['job-name'] == 'Test Page')):
                ret.append (id)

                if limit != None and len (ret) == limit:
                    break
        return ret

    def jobsPreserved(self, limit=None):
        """
        Find out whether there are preserved jobs for this printer.

        @return: list of job IDs
        """
        ret = []
        try:
            try:
                r = ['job-id', 'job-printer-uri', 'job-state']
                jobs = self.connection.getJobs (which_jobs='completed',
                                                requested_attributes=r)
            except TypeError:
                # requested_attributes requires pycups 1.9.50
                jobs = self.connection.getJobs (which_jobs='completed')
        except cups.IPPError:
            return ret

        for id, attrs in jobs.iteritems():
            try:
                uri = attrs['job-printer-uri']
                uri = uri[uri.rindex ('/') + 1:]
            except:
                continue
            if uri != self.name:
                continue
            if (attrs.get ('job-state',
                           cups.IPP_JOB_PENDING) < cups.IPP_JOB_COMPLETED):
                continue
            ret.append (id)
            if limit != None and len (ret) == limit:
                break

        return ret

    def testsQueued(self, limit=None):
        """
        Find out whether test jobs are queued for this printer.

        @returns: list of job IDs
        """
        return self.jobsQueued (only_tests=True, limit=limit)

    def setAsDefault(self):
        """
        Set this printer as the system default.
        """
        self.connection.setDefault(self.name)

        # Also need to check system-wide lpoptions because that's how
        # previous Fedora versions set the default (bug #217395).
        (tmpfd, tmpfname) = tempfile.mkstemp ()
        os.remove (tmpfname)
        try:
            resource = "/admin/conf/lpoptions"
            self.connection.getFile(resource, fd=tmpfd)
        except cups.HTTPError, (s,):
            if s == cups.HTTP_NOT_FOUND:
                return False

            raise cups.HTTPError (s)

        f = os.fdopen (tmpfd, 'r+')
        f.seek (0)
        lines = f.readlines ()
        changed = False
        i = 0
        for line in lines:
            if line.startswith ("Default "):
                # This is the system-wide default.
                name = line.split (' ')[1]
                if name != self.name:
                    # Stop it from over-riding the server default.
                    lines[i] = "Dest " + line[8:]
                    changed = True
                i += 1

        if changed:
            f.seek (0)
            f.writelines (lines)
            f.truncate ()
            os.lseek (tmpfd, 0, os.SEEK_SET)
            try:
                self.connection.putFile (resource, fd=tmpfd)
            except cups.HTTPError, (s,):
                return False

        return changed

def getPrinters(connection):
    """
    Obtain a list of printers.

    @param connection: CUPS connection
    @type connection: CUPS.Connection object
    @returns: L{Printer} list
    """
    printers = connection.getPrinters()
    classes = connection.getClasses()
    for name, printer in printers.iteritems():
        printer = Printer(name, connection, **printer)
        printers[name] = printer
        if classes.has_key(name):
            printer.class_members = classes[name]
            printer.class_members.sort()
    return printers

def parseDeviceID (id):
    """
    Parse an IEEE 1284 Device ID, so that it may be indexed by field name.

    @param id: IEEE 1284 Device ID, without the two leading length bytes
    @type id: string
    @returns: dict indexed by field name
    """
    id_dict = {}
    pieces = id.split(";")
    for piece in pieces:
        if piece.find(":") == -1:
            continue
        name, value = piece.split(":",1)
        id_dict[name.strip ()] = value.strip()
    if id_dict.has_key ("MANUFACTURER"):
        id_dict.setdefault("MFG", id_dict["MANUFACTURER"])
    if id_dict.has_key ("MODEL"):
        id_dict.setdefault("MDL", id_dict["MODEL"])
    if id_dict.has_key ("COMMAND SET"):
        id_dict.setdefault("CMD", id_dict["COMMAND SET"])
    for name in ["MFG", "MDL", "CMD", "CLS", "DES", "SN", "S", "P", "J"]:
        id_dict.setdefault(name, "")
    if id_dict["CMD"] == '':
        id_dict["CMD"] = []
    else:
        id_dict["CMD"] = id_dict["CMD"].split(',') 
    return id_dict

class Device:
    """
    This class represents a CUPS device.
    """

    def __init__(self, uri, **kw):
        """
        @param uri: device URI
        @type uri: string
        @param kw: device attributes
        @type kw: dict
        """
        self.uri = uri
        self.device_class = kw.get('device-class', '')
        self.info = kw.get('device-info', '')
        self.make_and_model = kw.get('device-make-and-model', '')
        self.id = kw.get('device-id', '')
        self.location = kw.get('device-location', '')

        uri_pieces = uri.split(":")
        self.type =  uri_pieces[0]
        self.is_class = len(uri_pieces)==1

        #self.id = 'MFG:HEWLETT-PACKARD;MDL:DESKJET 990C;CMD:MLC,PCL,PML;CLS:PRINTER;DES:Hewlett-Packard DeskJet 990C;SN:US05N1J00XLG;S:00808880800010032C1000000C2000000;P:0800,FL,B0;J:                    ;'

        self.id_dict = parseDeviceID (self.id)

        s = uri.find("serial=")
        if s != -1 and not self.id_dict.get ('SN',''):
            self.id_dict['SN'] = uri[s + 7:]

    def __repr__ (self):
        return "<cupshelpers.Device \"%s\">" % self.uri

    def __cmp__(self, other):
        """
        Compare devices by order of preference.
        """
        if other == None:
            return -1

        if self.is_class != other.is_class:
            if other.is_class:
                return -1
            return 1
        if not self.is_class and (self.type != other.type):
            # "hp"/"hpfax" before "usb" before * before "parallel" before
            # "serial"
            if other.type == "serial":
                return -1
            if self.type == "serial":
                return 1
            if other.type == "parallel":
                return -1
            if self.type == "parallel":
                return 1
            if other.type == "hp":
                return 1
            if self.type == "hp":
                return -1
            if other.type == "hpfax":
                return 1
            if self.type == "hpfax":
                return -1
            if other.type == "dnssd":
                return 1
            if self.type == "dnssd":
                return -1
            if other.type == "socket":
                return 1
            if self.type == "socket":
                return -1
            if other.type == "lpd":
                return 1
            if self.type == "lpd":
                return -1
            if other.type == "ipps":
                return 1
            if self.type == "ipps":
                return -1
            if other.type == "ipp":
                return 1
            if self.type == "ipp":
                return -1
            if other.type == "usb":
                return 1
            if self.type == "usb":
                return -1
        if self.type == "dnssd" and other.type == "dnssd":
            if other.uri.find("._pdl-datastream") != -1: # Socket
                return 1
            if self.uri.find("._pdl-datastream") != -1:
                return -1
            if other.uri.find("._printer") != -1: # LPD
                return 1
            if self.uri.find("._printer") != -1:
                return -1
            if other.uri.find("._ipp") != -1: # IPP
                return 1
            if self.uri.find("._ipp") != -1:
                return -1
        result = cmp(bool(self.id), bool(other.id))
        if not result:
            result = cmp(self.info.encode ('utf-8'),
                         other.info.encode ('utf-8'))
        
        return result

class _GetDevicesCall(object):
    def call (self, connection, kwds):
        if kwds.has_key ("reply_handler"):
            self._client_reply_handler = kwds.get ("reply_handler")
            kwds["reply_handler"] = self._reply_handler
            return connection.getDevices (**kwds)

        self._client_reply_handler = None
        result = connection.getDevices (**kwds)
        return self._reply_handler (connection, result)

    def _reply_handler (self, connection, devices):
        for uri, data in devices.iteritems():
            device = Device(uri, **data)
            devices[uri] = device
            if device.info != '' and device.make_and_model == '':
                device.make_and_model = device.info

        if self._client_reply_handler:
            self._client_reply_handler (connection, devices)
        else:
            return devices
            
def getDevices(connection, **kw):
    """
    Obtain a list of available CUPS devices.

    @param connection: CUPS connection
    @type connection: cups.Connection object
    @returns: a list of L{Device} objects
    @raise cups.IPPError: IPP Error
    """
    op = _GetDevicesCall ()
    return op.call (connection, kw)

def activateNewPrinter(connection, name):
    """
    Set a new printer enabled, accepting jobs, and (if necessary) the
    default printer.

    @param connection: CUPS connection
    @type connection: cups.Connection object
    @param name: printer name
    @type name: string
    @raise cups.IPPError: IPP error
    """
    connection.enablePrinter (name)
    connection.acceptJobs (name)

    # Set as the default if there is not already a default printer.
    if connection.getDefault () == None:
        connection.setDefault (name)

def copyPPDOptions(ppd1, ppd2):
    """
    Copy default options between PPDs.

    @param ppd1: source PPD
    @type ppd1: cups.PPD object
    @param ppd2: destination PPD
    @type ppd2: cups.PPD object
    """
    def getPPDGroupOptions(group):
    	options = group.options[:]
        for g in group.subgroups:
            options.extend(getPPDGroupOptions(g))
        return options

    def iteratePPDOptions(ppd):
    	for group in ppd.optionGroups:
            for option in getPPDGroupOptions(group):
            	yield option

    for option in iteratePPDOptions(ppd1):
        if option.keyword == "PageRegion":
            continue
        new_option = ppd2.findOption(option.keyword)
        if new_option and option.ui==new_option.ui:
            value = option.defchoice
            for choice in new_option.choices:
                if choice["choice"]==value:
                    ppd2.markOption(new_option.keyword, value)
                    _debugprint ("set %s = %s" % (new_option.keyword, value))
                    
def setPPDPageSize(ppd, language):
    """
    Set the PPD page size according to locale.

    @param ppd: PPD
    @type ppd: cups.PPD object
    @param language: language, as given by the first element of
    locale.setlocale
    @type language: string
    """
    # Just set the page size to A4 or Letter, that's all.
    # Use the same method CUPS uses.
    size = 'A4'
    letter = [ 'C', 'POSIX', 'en', 'en_US', 'en_CA', 'fr_CA' ]
    for each in letter:
        if language == each:
            size = 'Letter'
    try:
        ppd.markOption ('PageSize', size)
        _debugprint ("set PageSize = %s" % size)
    except:
        _debugprint ("Failed to set PageSize (%s not available?)" % size)

def missingExecutables(ppd):
    """
    Check that all relevant executables for a PPD are installed.

    @param ppd: PPD
    @type ppd: cups.PPD object
    @returns: string list, representing missing executables
    """

    # First, a local function.  How to check that something exists
    # in a path:
    def pathcheck (name, path="/usr/bin:/bin"):
        if name == "-":
            # A filter of "-" means that no filter is required,
            # i.e. the device accepts the given format as-is.
            return "builtin"
        # Strip out foomatic '%'-style place-holders.
        p = name.find ('%')
        if p != -1:
            name = name[:p]
        if len (name) == 0:
            return "true"
        if name[0] == '/':
            if os.access (name, os.X_OK):
                _debugprint ("%s: found" % name)
                return name
            else:
                _debugprint ("%s: NOT found" % name)
                return None
        if name.find ("=") != -1:
            return "builtin"
        if name in [ ":", ".", "[", "alias", "bind", "break", "cd",
                     "continue", "declare", "echo", "else", "eval",
                     "exec", "exit", "export", "fi", "if", "kill", "let",
                     "local", "popd", "printf", "pushd", "pwd", "read",
                     "readonly", "set", "shift", "shopt", "source",
                     "test", "then", "trap", "type", "ulimit", "umask",
                     "unalias", "unset", "wait" ]:
            return "builtin"
        for component in path.split (':'):
            file = component.rstrip (os.path.sep) + os.path.sep + name
            if os.access (file, os.X_OK):
                _debugprint ("%s: found" % file)
                return file
        _debugprint ("%s: NOT found in %s" % (name,path))
        return None

    exes_to_install = []

    def add_missing (exe):
        # Strip out foomatic '%'-style place-holders.
        p = exe.find ('%')
        if p != -1:
            exe = exe[:p]

        exes_to_install.append (exe)

    # Find a 'FoomaticRIPCommandLine' attribute.
    exe = exepath = None
    attr = ppd.findAttr ('FoomaticRIPCommandLine')
    if attr:
        # Foomatic RIP command line to check.
        cmdline = attr.value.replace ('&&\n', '')
        cmdline = cmdline.replace ('&quot;', '"')
        cmdline = cmdline.replace ('&lt;', '<')
        cmdline = cmdline.replace ('&gt;', '>')
        if (cmdline.find ("(") != -1 or
            cmdline.find ("&") != -1):
            # Don't try to handle sub-shells or unreplaced HTML entities.
            cmdline = ""

        # Strip out foomatic '%'-style place-holders
        pipes = cmdline.split (';')
        for pipe in pipes:
            cmds = pipe.strip ().split ('|')
            for cmd in cmds:
                args = cmd.strip ().split (' ')
                exe = args[0]
                exepath = pathcheck (exe)
                if not exepath:
                    add_missing (exe)
                    continue

                # Main executable found.  But if it's 'gs',
                # perhaps there is an IJS server we also need
                # to check.
                if os.path.basename (exepath) == 'gs':
                    argn = len (args)
                    argi = 1
                    search = "-sIjsServer="
                    while argi < argn:
                        arg = args[argi]
                        if arg.startswith (search):
                            exe = arg[len (search):]
                            exepath = pathcheck (exe)
                            if not exepath:
                                add_missing (exe)

                            break

                        argi += 1

            if not exepath:
                # Next pipe.
                break

    if exepath or not exe:
        # Look for '*cupsFilter' lines in the PPD and check that
        # the filters are installed.
        (tmpfd, tmpfname) = tempfile.mkstemp ()
        os.unlink (tmpfname)
        ppd.writeFd (tmpfd)
        os.lseek (tmpfd, 0, os.SEEK_SET)
        f = os.fdopen (tmpfd, "r")
        search = "*cupsFilter:"
        for line in f.readlines ():
            if line.startswith (search):
                line = line[len (search):].strip ().strip ('"')
                try:
                    (mimetype, cost, exe) = line.split (' ')
                except:
                    continue

                exepath = pathcheck (exe,
                                     config.cupsserverbindir + "/filter:"
                                     "/usr/lib64/cups/filter")
                if not exepath:
                    add_missing (config.cupsserverbindir + "/filter/" + exe)

    return exes_to_install

def missingPackagesAndExecutables(ppd):
    """
    Check that all relevant executables for a PPD are installed.

    @param ppd: PPD
    @type ppd: cups.PPD object
    @returns: string list pair, representing missing packages and
    missing executables
    """
    executables = missingExecutables(ppd)
    return ([], executables)

def _main():
    c = cups.Connection()
    #printers = getPrinters(c)
    for device in getDevices(c).itervalues():
        print device.uri, device.id_dict

if __name__=="__main__":
    _main()

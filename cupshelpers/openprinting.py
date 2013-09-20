#!/usr/bin/python

## system-config-printer

## Copyright (C) 2008, 2011 Red Hat, Inc.
## Copyright (C) 2008 Till Kamppeter <till.kamppeter@gmail.com>

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

import pycurl, urllib, platform, threading, tempfile, traceback
import os, sys
from xml.etree.ElementTree import XML
from . import Device
from . import _debugprint

__all__ = ['OpenPrinting']

def _normalize_space (text):
    result = text.strip ()
    result = result.replace ('\n', ' ')
    i = result.find ('  ')
    while i != -1:
        result = result.replace ('  ', ' ')
        i = result.find ('  ')
    return result

class _QueryThread (threading.Thread):
    def __init__ (self, parent, parameters, callback, user_data=None):
        threading.Thread.__init__ (self)
        self.parent = parent
        self.parameters = parameters
        self.callback = callback
        self.user_data = user_data
        self.result = ""

        self.setDaemon (True)

    def run (self):

        # Callback function for pycURL collecting the data coming from
        # the web server
        def collect_data(result):
            self.result += result;
            return len(result)

        # CGI script to be executed
        query_command = "/query.cgi"
        # Headers for the post request
        headers = {"Content-type": "application/x-www-form-urlencoded",
                   "Accept": "text/plain"}
        params = ("%s&uilanguage=%s&locale=%s" %
                  (urllib.urlencode (self.parameters),
                   self.parent.language[0],
                   self.parent.language[0]))
        self.url = "https://%s%s?%s" % (self.parent.base_url, query_command, params)
        # Send request
        result = None
        self.result = ""
        status = 1
        try:
            curl = pycurl.Curl()
            curl.setopt(pycurl.SSL_VERIFYPEER, 1)
            curl.setopt(pycurl.SSL_VERIFYHOST, 2)
            curl.setopt(pycurl.WRITEFUNCTION, collect_data)
            curl.setopt(pycurl.URL, self.url)
            status = curl.perform()
            if status == None: status = 0
            if (status != 0):
                self.result = sys.exc_info ()
        except:
            self.result = sys.exc_info ()
            if status == None: status = 0

        if self.callback != None:
            self.callback (status, self.user_data, self.result)

class OpenPrinting:
    def __init__(self, language=None):
        """
        @param language: language, as given by the first element of
        locale.setlocale().
        @type language: string
        """
        if language == None:
            import locale
            try:
                language = locale.getlocale(locale.LC_MESSAGES)
            except locale.Error:
                language = 'C'
        self.language = language

        # XXX Read configuration file.
        self.base_url = "www.openprinting.org"

        # Restrictions on driver choices XXX Parameters to be taken from
        # config file
        self.onlyfree = 1
        self.onlymanufacturer = 0
        _debugprint ("OpenPrinting: Init %s %s %s" % (self.language, self.onlyfree, self.onlymanufacturer))

    def cancelOperation(self, handle):
        """
        Cancel an operation.

        @param handle: query/operation handle
        """
        # Just prevent the callback.
        try:
            handle.callback = None
        except:
            pass

    def webQuery(self, parameters, callback, user_data=None):
        """
        Run a web query for a driver.

        @type parameters: dict
        @param parameters: URL parameters
        @type callback: function
        @param callback: callback function, taking (integer, user_data, string)
        parameters with the first parameter being the status code, zero for
        success
        @return: query handle
        """
        the_thread = _QueryThread (self, parameters, callback, user_data)
        the_thread.start()
        return the_thread

    def searchPrinters(self, searchterm, callback, user_data=None):
        """
        Search for printers using a search term.

        @type searchterm: string
        @param searchterm: search term
        @type callback: function
        @param callback: callback function, taking (integer, user_data, string)
        parameters with the first parameter being the status code, zero for
        success
        @return: query handle
        """

        def parse_result (status, data, result):
            (callback, user_data) = data
            if status != 0:
                callback (status, user_data, result)
                return

            status = 0
            printers = {}
            try:
                root = XML (result)
                # We store the printers as a dict of:
                # foomatic_id: displayname

                for printer in root.findall ("printer"):
                    id = printer.find ("id")
                    make = printer.find ("make")
                    model = printer.find ("model")
                    if id != None and make != None and model != None:
                        idtxt = id.text
                        maketxt = make.text
                        modeltxt = model.text
                        if idtxt and maketxt and modeltxt:
                            printers[idtxt] = maketxt + " " + modeltxt
            except:
                status = 1
                printers = sys.exc_info ()

            _debugprint ("searchPrinters/parse_result: OpenPrinting entries: %s" % repr(printers))
            try:
                callback (status, user_data, printers)
            except:
                (type, value, tb) = sys.exc_info ()
                tblast = traceback.extract_tb (tb, limit=None)
                if len (tblast):
                    tblast = tblast[:len (tblast) - 1]
                extxt = traceback.format_exception_only (type, value)
                for line in traceback.format_tb(tb):
                    print (line.strip ())
                print (extxt[0].strip ())

        # Common parameters for the request
        params = { 'type': 'printers',
                   'printer': searchterm,
                   'format': 'xml' }
        _debugprint ("searchPrinters: Querying OpenPrinting: %s" % repr(params))
        return self.webQuery(params, parse_result, (callback, user_data))

    def listDrivers(self, model, callback, user_data=None, extra_options=None):
        """
        Obtain a list of printer drivers.

        @type model: string or cupshelpers.Device
        @param model: foomatic printer model string or a cupshelpers.Device
        object
        @type callback: function
        @param callback: callback function, taking (integer, user_data, string)
        parameters with the first parameter being the status code, zero for
        success
        @type extra_options: string -> string dictionary
        @param extra_options: Additional search options, see
        http://www.linuxfoundation.org/en/OpenPrinting/Database/Query
        @return: query handle
        """

        def parse_result (status, data, result):
            (callback, user_data) = data
            if status != 0:
                callback (status, user_data, result)

            try:
                # filter out invalid UTF-8 to avoid breaking the XML parser
                result = result.decode('UTF-8', errors='replace').encode('UTF-8')
                root = XML (result)
                drivers = {}
                # We store the drivers as a dict of:
                # foomatic_id:
                #   { 'name': name,
                #     'url': url,
                #     'supplier': supplier,
                #     'license': short license string e.g. GPLv2,
                #     'licensetext': license text (Plain text),
                #     'nonfreesoftware': Boolean,
                #     'thirdpartysupplied': Boolean,
                #     'manufacturersupplied': Boolean,
                #     'patents': Boolean,
                #     'supportcontacts' (optional):
                #       list of { 'name',
                #                 'url',
                #                 'level',
                #               }
                #     'shortdescription': short description,
                #     'recommended': Boolean,
                #     'functionality':
                #       { 'text': integer percentage,
                #         'lineart': integer percentage,
                #         'graphics': integer percentage,
                #         'photo': integer percentage,
                #         'speed': integer percentage,
                #       }
                #     'packages' (optional):
                #       { arch:
                #         { file:
                #           { 'url': url,
                #             'fingerprint': signature key fingerprint URL
                #             'realversion': upstream version string,
                #             'version': packaged version string,
                #             'release': package release string
                #           }
                #         }
                #       }
                #     'ppds' (optional):
                #       URL string list
                #   }
                # There is more information in the raw XML, but this
                # can be added to the Python structure as needed.

                for driver in root.findall ('driver'):
                    id = driver.attrib.get ('id')
                    if id == None:
                        continue

                    dict = {}
                    for attribute in ['name', 'url', 'supplier', 'license',
                                      'shortdescription' ]:
                        element = driver.find (attribute)
                        if element != None and element.text != None:
                            dict[attribute] = _normalize_space (element.text)

                    element = driver.find ('licensetext')
                    if element != None:
                        dict['licensetext'] = element.text

                    for boolean in ['nonfreesoftware', 'recommended',
                                    'patents', 'thirdpartysupplied',
                                    'manufacturersupplied']:
                        dict[boolean] = driver.find (boolean) != None

                    # Make a 'freesoftware' tag for compatibility with
                    # how the OpenPrinting API used to work (see trac
                    # #74).
                    dict['freesoftware'] = not dict['nonfreesoftware']

                    supportcontacts = []
                    container = driver.find ('supportcontacts')
                    if container != None:
                        for sc in container.findall ('supportcontact'):
                            supportcontact = {}
                            if sc.text != None:
                                supportcontact['name'] = \
                                    _normalize_space (sc.text)
                            else:
                                supportcontact['name'] = ""
                            supportcontact['url'] = sc.attrib.get ('url')
                            supportcontact['level'] = sc.attrib.get ('level')
                            supportcontacts.append (supportcontact)

                    if supportcontacts:
                        dict['supportcontacts'] = supportcontacts

                    if not dict.has_key ('name') or not dict.has_key ('url'):
                        continue

                    container = driver.find ('functionality')
                    if container != None:
                        functionality = {}
                        for attribute in ['text', 'lineart', 'graphics',
                                          'photo', 'speed']:
                            element = container.find (attribute)
                            if element != None:
                                functionality[attribute] = element.text
                        if functionality:
                            dict[container.tag] = functionality

                    packages = {}
                    container = driver.find ('packages')
                    if container != None:
                        for arch in container.getchildren ():
                            rpms = {}
                            for package in arch.findall ('package'):
                                rpm = {}
                                for attribute in ['realversion','version',
                                                  'release', 'url', 'pkgsys',
                                                  'fingerprint']:
                                    element = package.find (attribute)
                                    if element != None:
                                        rpm[attribute] = element.text

                                repositories = package.find ('repositories')
                                if repositories != None:
                                    for pkgsys in repositories.getchildren ():
                                        rpm.setdefault('repositories', {})[pkgsys.tag] = pkgsys.text

                                rpms[package.attrib['file']] = rpm
                            packages[arch.tag] = rpms

                    if packages:
                        dict['packages'] = packages

                    ppds = []
                    container = driver.find ('ppds')
                    if container != None:
                        for each in container.getchildren ():
                            ppds.append (each.text)

                    if ppds:
                        dict['ppds'] = ppds

                    drivers[id] = dict
                    _debugprint ("listDrivers/parse_result: OpenPrinting entries: %s" % repr(drivers))
                callback (0, user_data, drivers)
            except:
                callback (1, user_data, sys.exc_info ())

        if isinstance(model, Device):
            model = model.id

        params = { 'type': 'drivers',
                   'moreinfo': '1',
                   'showprinterid': '1',
                   'onlynewestdriverpackages': '1',
                   'architectures': platform.machine(),
                   'noobsoletes': '1',
                   'onlyfree': str (self.onlyfree),
                   'onlymanufacturer': str (self.onlymanufacturer),
                   'printer': model,
                   'format': 'xml'}
        if extra_options:
            params.update(extra_options)
        _debugprint ("listDrivers: Querying OpenPrinting: %s" % repr(params))
        return self.webQuery(params, parse_result, (callback, user_data))

def _simple_gui ():
    from gi.repository import Gdk
    from gi.repository import Gtk
    import pprint
    Gdk.threads_init ()
    class QueryApp:
        def __init__(self):
            self.openprinting = OpenPrinting()
            self.main = Gtk.Dialog ("OpenPrinting query application",
                                    None,
                                    Gtk.DialogFlags.MODAL,
                                    (Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE,
                                     "Search", 10,
                                     "List", 20))
            self.main.set_border_width (6)
            self.main.vbox.set_spacing (2)
            vbox = Gtk.VBox.new (False, 6)
            self.main.vbox.pack_start (vbox, True, True, 0)
            vbox.set_border_width (6)
            self.entry = Gtk.Entry ()
            vbox.pack_start (self.entry, False, False, 6)
            sw = Gtk.ScrolledWindow ()
            self.tv = Gtk.TextView ()
            sw.add (self.tv)
            vbox.pack_start (sw, True, True, 6)
            self.main.connect ("response", self.response)
            self.main.show_all ()

        def response (self, dialog, response):
            if (response == Gtk.ResponseType.CLOSE or
                response == Gtk.ResponseType.DELETE_EVENT):
                Gtk.main_quit ()

            if response == 10:
                # Run a query.
                self.openprinting.searchPrinters (self.entry.get_text (),
                                                  self.search_printers_callback)

            if response == 20:
                self.openprinting.listDrivers (self.entry.get_text (),
                                               self.list_drivers_callback)

        def search_printers_callback (self, status, user_data, printers):
            if status != 0:
                raise printers[1]

            text = ""
            for printer in printers.values ():
                text += printer + "\n"
            Gdk.threads_enter ()
            self.tv.get_buffer ().set_text (text)
            Gdk.threads_leave ()

        def list_drivers_callback (self, status, user_data, drivers):
            if status != 0:
                raise drivers[1]

            text = pprint.pformat (drivers)
            Gdk.threads_enter ()
            self.tv.get_buffer ().set_text (text)
            Gdk.threads_leave ()

        def query_callback (self, status, user_data, result):
            Gdk.threads_enter ()
            self.tv.get_buffer ().set_text (str (result))
            file ("result.xml", "w").write (str (result))
            Gdk.threads_leave ()

    q = QueryApp()
    Gtk.main ()

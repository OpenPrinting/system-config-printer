#!/usr/bin/env python

## system-config-printer

## Copyright (C) 2008 Red Hat, Inc.
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
## Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.

import urllib, httplib, platform

class OpenPrinting:
    def __init__(self, language=None):
        if language == None:
            import locale
            language = locale.getlocale(locale.LC_MESSAGES)
        self.language = language

        # XXX Read configuration file.
        self.base_url = "www.openprinting.org"

        # Restrictions on driver choices XXX Parameters to be taken from
        # config file
        self.onlyfree = 0
        self.onlymanufacturer = 0

    def cancelOperation(self, handle):
        pass

    def webQuery(self, parameters, callback):
        """
        webQuery(params, callback) -> integer

        Run a web query for a driver.
        @type parameters: dict
        @param parameters: URL parameters
        @type callback: function
        @param callback: callback function, taking (integer, string) parameters
        with the first parameter being the status code, zero for success
        @return: query handle
        """

        # CGI script to be executed
        query_command = "/query.cgi"
        # Headers for the post request
        headers = {"Content-type": "application/x-www-form-urlencoded",
                   "Accept": "text/plain"}
        params = "%s&uilanguage=%s&locale=%s" % (urllib.urlencode (parameters),
                                                 self.language[0],
                                                 self.language[0])
        # Send request
        # XXX Do this in a new thread
        conn = httplib.HTTPConnection(base_url)
        conn.request("POST", query_command, params, headers)
        resp = conn.getresponse()
        if resp.status != 200:
            # XXX error handling
            pass
        result = resp.read()
        conn.close()
        callback (0, result)
        return 0

    def searchPrinters(self, searchterm, callback):
        """
        searchPrinters(searchterm, callback) -> integer

        Search for printers using a search term.
        @type searchterm: string
        @param searchterm: search term
        @type callback: function
        @param callback: callback function, taking (integer, string) parameters
        with the first parameter being the status code, zero for success
        @return: query handle
        """

        # Common parameters for the request
        params = "type=printers&%s&moreinfo=1"
        # Search term to be inserted into the URL, with special characters
        # in device ID appropriately encoded
        search = urllib.urlencode({'printer': searchterm})
        # Send request to poll driver package list
        return self.webQuery(params % search, callback)

    def listDrivers(self, model, callback):
        """
        listDrivers(model, callback) -> integer

        Obtain a list of printer drivers.
        @type model: string
        @param model: printer model string
        @type callback: function
        @param callback: callback function, taking (integer, string) parameters
        with the first parameter being the status code, zero for success
        @return: query handle
        """

        # CGI script to be executed
        query_command = "/query.cgi"
        # Common parameters for the request
        params = "type=drivers&%s&moreinfo=1&showprinterid=1&onlydownload=1&onlynewestdriverpackages=1&architectures=%s&uilanguage=%s&locale=%s&noobsoletes=1&onlyfree=%s&onlymanufacturer=%s"
        # Headers for the post request
        headers = {"Content-type": "application/x-www-form-urlencoded",
                   "Accept": "text/plain"}
        # Search term to be inserted into the URL, with special characters
        # in device ID appropriately encoded
        search = urllib.urlencode({'printer': searchterm})
        # Architecture of this machine
        arch = platform.machine()
        # Send request to poll driver package list
        conn = httplib.HTTPConnection(self.base_url)
        conn.request("POST", query_command,
                     params % (search, arch, self.language[0],
                               self.language[0], self.onlyfree,
                               self.onlymanufacturer),
                     headers)
        resp = conn.getresponse()
        if resp.status != 200:
            # XXX error handling
            pass
        # This is the list of driver descriptions and downloadable packages
        # and PPDs
        dd_data_txt = resp.read()
        conn.close()
        callback (0, dd_data_txt)
        return 0

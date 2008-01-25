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

import urllib, httplib, platform, threading

class QueryThread (threading.Thread):
    def __init__ (self, parent, parameters, callback, user_data=None):
        threading.Thread.__init__ (self)
        self.parent = parent
        self.parameters = parameters
        self.callback = callback
        self.user_data = user_data

    def run (self):
        # CGI script to be executed
        query_command = "/query.cgi"
        # Headers for the post request
        headers = {"Content-type": "application/x-www-form-urlencoded",
                   "Accept": "text/plain"}
        params = ("%s&uilanguage=%s&locale=%s" %
                  (urllib.urlencode (self.parameters),
                   self.parent.language[0],
                   self.parent.language[0]))
        # Send request
        # XXX Do this in a new thread
        conn = httplib.HTTPConnection(self.parent.base_url)
        conn.request("POST", query_command, params, headers)
        resp = conn.getresponse()
        if resp.status != 200:
            # XXX error handling
            pass
        result = resp.read()
        conn.close()
        if self.callback != None:
            self.callback (0, self.user_data, result)

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
        # Just prevent the callback.
        handle.callback = None

    def webQuery(self, parameters, callback, user_data=None):
        """
        webQuery(parameters, callback, user_data) -> integer

        Run a web query for a driver.
        @type parameters: dict
        @param parameters: URL parameters
        @type callback: function
        @param callback: callback function, taking (integer, user_data, string)
        parameters with the first parameter being the status code, zero for
        success
        @return: query handle
        """
        the_thread = QueryThread (self, parameters, callback, user_data)
        the_thread.start()
        return the_thread

    def searchPrinters(self, searchterm, callback, user_data=None):
        """
        searchPrinters(searchterm, callback, user_data) -> integer

        Search for printers using a search term.
        @type searchterm: string
        @param searchterm: search term
        @type callback: function
        @param callback: callback function, taking (integer, user_data, string)
        parameters with the first parameter being the status code, zero for
        success
        @return: query handle
        """

        # Common parameters for the request
        params = { 'type': 'printers',
                   'printer': searchterm,
                   'moreinfo': '1' }
        return self.webQuery(params, callback, user_data)

    def listDrivers(self, model, callback, user_data=None):
        """
        listDrivers(model, callback, user_data) -> integer

        Obtain a list of printer drivers.
        @type model: string
        @param model: foomatic printer model string
        @type callback: function
        @param callback: callback function, taking (integer, user_data, string)
        parameters with the first parameter being the status code, zero for
        success
        @return: query handle
        """

        params = { 'type': 'drivers',
                   'moreinfo': '1',
                   'showprinterid': '1',
                   'onlydownload': '1',
                   'onlynewestdriverpackages': '1',
                   'architectures': platform.machine(),
                   'noobsoletes': '1',
                   'onlyfree': str (self.onlyfree),
                   'onlymanufacturer': str (self.onlymanufacturer),
                   'printer': model }
        return self.webQuery(params, callback, user_data)

if __name__ == "__main__":
    import gtk
    class QueryApp:
        def __init__(self):
            self.openprinting = OpenPrinting()
            self.main = gtk.Dialog ("OpenPrinting query application",
                                    None,
                                    gtk.DIALOG_MODAL | gtk.DIALOG_NO_SEPARATOR,
                                    (gtk.STOCK_CLOSE, gtk.RESPONSE_CLOSE,
                                     "Query", 10))
            self.main.set_border_width (6)
            self.main.vbox.set_spacing (2)
            vbox = gtk.VBox (False, 6)
            self.main.vbox.pack_start (vbox, True, True, 0)
            vbox.set_border_width (6)
            self.label = gtk.Label ()
            vbox.pack_start (self.label)
            self.main.connect ("response", self.response)
            self.main.show_all ()

        def response (self, dialog, response):
            if (response == gtk.RESPONSE_CLOSE or
                response == gtk.RESPONSE_DELETE_EVENT):
                gtk.main_quit ()

            if response == 10:
                # Run a query.
                self.openprinting.searchPrinters ("hp deskjet 990c",
                                                  self.query_callback)

        def query_callback (self, status, user_data, result):
            gtk.gdk.threads_enter ()
            print "Got callback", result
            self.label.set_text (result)
            gtk.gdk.threads_leave ()

    q = QueryApp()
    gtk.main ()


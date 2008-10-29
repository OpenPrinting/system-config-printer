#!/usr/bin/env python

## my-default-printer

## Copyright (C) 2006, 2007, 2008 Red Hat, Inc.
## Copyright (C) 2007, 2008 Tim Waugh <twaugh@redhat.com>

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
import signal
import sys

domain='system-config-printer'
import locale
try:
    locale.setlocale (locale.LC_ALL, "")
except locale.Error, e:
    os.environ['LC_ALL'] = 'C'
    locale.setlocale (locale.LC_ALL, "")

from gettext import gettext as _
import gettext
gettext.textdomain (domain)

def handle_sigchld (signum, stack):
    try:
        (pid, status) = os.wait ()
        exitcode = os.WEXITSTATUS (status)
        if exitcode != 0:
            print "Child exit status %d" % exitcode
    except OSError:
        pass

signal.signal (signal.SIGCHLD, handle_sigchld)

class Server:
    def __init__ (self):
        self.cups_connection = cups.Connection()
        try:
            lpoptions = os.environ["HOME"]
        except KeyError:
            try:
                lpoptions = "/home/" + os.environ["USER"]
            except KeyError:
                lpoptions = None

        if lpoptions:
            lpoptions += "/.cups/lpoptions"

        self.lpoptions = lpoptions

    def clearUserDefault (self):
        if not self.lpoptions:
            return

        try:
            opts = file (self.lpoptions).readlines ()
        except IOError:
            return

        for i in range (len (opts)):
            if opts[i].startswith ("Default "):
                opts[i] = "Dest " + opts[i][8:]
        file (self.lpoptions, "w").writelines (opts)

    def setUserDefault (self, default):
        pid = os.fork ()
        if pid == 0:
            # Child
            null = file ("/dev/null", "r+")
            f = null.fileno ()
            if f != 0:
                os.dup2 (f, 0)
            if f != 1:
                os.dup2 (f, 1)

            os.execvp ("lpoptions", [ "lpoptions", "-d", default ])
            sys.exit (1)

        # Parent
        return

    def isUserDefaultSet (self):
        if self.getUserDefault () != self.getSystemDefault ():
            return True

        if self.lpoptions:
            try:
                opts = file (self.lpoptions).readlines ()
            except IOError:
                return False

            for opt in opts:
                if opt.startswith ("Default "):
                    return True

        return False

    def getUserDefault (self):
        dests = self.cups_connection.getDests ()
        if dests.has_key ((None, None)):
            return dests[(None, None)].name

        for ((name, instance), dest) in dests.iteritems ():
            if dest.is_default:
                return name

        return None

    def getSystemDefault (self):
        try:
            return self.cups_connection.getDefault ()
        except:
            pass

        return None

class Dialog:
    def __init__ (self):
        gtk.window_set_default_icon_name ('printer')
        self.dialog = gtk.Dialog (_("Default Printer"),
                                  None,
                                  gtk.DIALOG_MODAL | gtk.DIALOG_NO_SEPARATOR,
                                  (gtk.STOCK_CLOSE, gtk.RESPONSE_CLOSE,
                                   _("_Use System Default"), gtk.RESPONSE_NO,
                                   _("_Set Default"), gtk.RESPONSE_OK))
        self.dialog.set_default_response (gtk.RESPONSE_OK)
        self.dialog.set_border_width (6)
        self.dialog.vbox.set_spacing (2)
        vbox = gtk.VBox (False, 6)
        self.dialog.vbox.pack_start (vbox, True, True, 0)
        vbox.set_border_width (6)

        self.model = gtk.ListStore (gobject.TYPE_STRING, gobject.TYPE_STRING)
        self.model.set_sort_column_id (0, gtk.SORT_ASCENDING)
        view = gtk.TreeView (self.model)
        col = gtk.TreeViewColumn (_("Printer"), gtk.CellRendererText (),
                                  text=0)
        col.set_sort_column_id (0)
        view.append_column (col)

        col = gtk.TreeViewColumn (_("Location"), gtk.CellRendererText (),
                                  text=1)
        col.set_sort_column_id (1)
        view.append_column (col)
        self.view = view

        view.get_selection ().connect ('changed', self.selection_changed)

        scrollwin = gtk.ScrolledWindow ()
        scrollwin.set_shadow_type (gtk.SHADOW_IN)
        scrollwin.set_policy (gtk.POLICY_AUTOMATIC,
                              gtk.POLICY_AUTOMATIC)
        scrollwin.add (view)
        vbox.pack_start (scrollwin, True, True, 0)

        self.dialog.set_default_size (320, 240)

        self.server = Server ()
        for button in self.dialog.action_area.get_children ():
            if button.get_label () == _("_Use System Default"):
                self.system_default_button = button
            elif button.get_label () == _("_Set Default"):
                self.set_default_button = button

    def selection_changed (self, selection):
        (model, iter) = selection.get_selected ()
        if iter:
            self.last_iter_selected = iter
        else:
            selection.select_iter (self.last_iter_selected)

    def run (self):
        c = cups.Connection ()
        printers = c.getPrinters ()
        del c
        user_default = self.server.getUserDefault ()
        for (name, info) in printers.iteritems ():
            iter = self.model.append ()
            self.model.set_value (iter, 0, name)
            self.model.set_value (iter, 1, info['printer-location'])
            if name == user_default:
                self.view.get_selection ().select_iter (iter)

        self.system_default_button.set_sensitive (self.server.
                                                  isUserDefaultSet ())
        self.set_default_button.set_sensitive (len (printers) > 0)

        self.dialog.show_all ()
        self.dialog.connect ("response", self.response)
        gtk.main ()

    def response (self, dialog, response):
        if (response == gtk.RESPONSE_CLOSE or
            response == gtk.RESPONSE_DELETE_EVENT):
            gtk.main_quit ()

        try:
            if response == gtk.RESPONSE_OK:
                (model, iter) = self.view.get_selection ().get_selected ()
                name = model.get_value (iter, 0)
                self.server.setUserDefault (name)
                self.system_default_button.set_sensitive (True)
            elif response == gtk.RESPONSE_NO:
                self.server.clearUserDefault ()
                system_default = self.server.getSystemDefault ()
                iter = self.model.get_iter_first ()
                while iter:
                    name = self.model.get_value (iter, 0)
                    if name == system_default:
                        self.view.get_selection ().select_iter (iter)
                        break
                    iter = self.model.iter_next (iter)
                self.system_default_button.set_sensitive (False)
        except cups.IPPError, (e, s):
            if e == cups.IPP_SERVICE_UNAVAILABLE:
                error_out ('<span weight="bold" size="larger">' +
                           'CUPS server error' + '</span>\n\n' +
                           'The CUPS scheduler is not running.')
            else:
                error_out ('<span weight="bold" size="larger">' +
                           'CUPS server error' + '</span>\n\n' +
                           'There was an error during the CUPS operation: ' +
                           s)

def error_out (msg):
    d = gtk.MessageDialog (None, 0, gtk.MESSAGE_ERROR, gtk.BUTTONS_OK, '')
    d.set_markup (msg)
    d.run ()
    d.destroy ()
    sys.exit (1)

try:
    d = Dialog()
    d.run ()
except RuntimeError:
    error_out ('<span weight="bold" size="larger">' +
               'CUPS server error' + '</span>\n\n' +
               'The CUPS scheduler is not running.')
except cups.IPPError, (e, s):
    if e == cups.IPP_SERVICE_UNAVAILABLE:
        error_out ('<span weight="bold" size="larger">' +
                   'CUPS server error' + '</span>\n\n' +
                   'The CUPS scheduler is not running.')
    else:
        error_out ('<span weight="bold" size="larger">' +
                   'CUPS server error' + '</span>\n\n' +
                   'There was an error during the CUPS operation: ' +
                   s)

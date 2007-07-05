#!/usr/bin/env python

## my-default-printer

## Copyright (C) 2006, 2007 Red Hat, Inc.
## Copyright (C) 2007 Tim Waugh <twaugh@redhat.com>

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

domain='my-default-printer'
import locale
locale.setlocale (locale.LC_ALL, "")
from gettext import gettext as _
import gettext
gettext.textdomain (domain)

def handle_sigchld (signum, stack):
    (pid, status) = os.wait ()
    exitcode = os.WEXITSTATUS (status)
    if exitcode != 0:
        print "Child exit status %d" % exitcode

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
        for ((name, instance), dest) in dests.iteritems ():
            if dest.is_default:
                return name

        return None

    def getSystemDefault (self):
        printers = self.cups_connection.getPrinters ()
        for (name, info) in printers.iteritems ():
            if info['printer-type'] & cups.CUPS_PRINTER_DEFAULT:
                return name

        return None

class Dialog:
    def __init__ (self):
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
        view = gtk.TreeView (self.model)
        col = gtk.TreeViewColumn (_("Printer"), gtk.CellRendererText (),
                                  text=0)
        view.append_column (col)

        col = gtk.TreeViewColumn (_("Location"), gtk.CellRendererText (),
                                  text=1)
        view.append_column (col)
        self.view = view

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

        self.dialog.show_all ()
        self.dialog.connect ("response", self.response)
        gtk.main ()

    def response (self, dialog, response):
        if (response == gtk.RESPONSE_CLOSE or
            response == gtk.RESPONSE_DELETE_EVENT):
            gtk.main_quit ()

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
                iter = self.model.get_iter_next (iter)
            self.system_default_button.set_sensitive (False)

d = Dialog()
d.run ()

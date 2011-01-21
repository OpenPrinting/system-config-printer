#!/usr/bin/python

## Printing troubleshooter

## Copyright (C) 2008, 2009, 2010 Red Hat, Inc.
## Authors:
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

from gi.repository import Gtk

import cups
import cupshelpers
import installpackage
import os
import subprocess
from timedops import TimedOperation, TimedSubprocess
from base import *

class CheckPPDSanity(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Check PPD sanity")
        vbox = Gtk.VBox ()
        vbox.set_border_width (12)
        vbox.set_spacing (12)
        self.label = Gtk.Label ()
        self.label.set_line_wrap (True)
        self.label.set_use_markup (True)
        self.label.set_alignment (0, 0)
        vbox.pack_start (self.label, False, False, 0)

        box = Gtk.HButtonBox ()
        box.set_layout (Gtk.ButtonBoxStyle.START)
        self.install_button = Gtk.Button (_("Install"))
        box.add (self.install_button)
        # Although we want this hidden initially,
        # troubleshooter.new_page will call show_all() on the widget
        # we give it.  We'll need to hide this button in the display()
        # callback instead.
        vbox.pack_start (box, False, False, 0)

        troubleshooter.new_page (vbox, self)

    def display (self):
        self.answers = {}

        answers = self.troubleshooter.answers
        if not answers['cups_queue_listed']:
            return False

        parent = self.troubleshooter.get_window ()
        name = answers['cups_queue']
        tmpf = None
        try:
            cups.setServer ('')
            self.op = TimedOperation (cups.Connection, parent=parent)
            c = self.op.run ()
            self.op = TimedOperation (c.getPPD, args=(name,), parent=parent)
            tmpf = self.op.run ()
        except RuntimeError:
            return False
        except cups.IPPError:
            return False

        self.install_button.hide ()
        title = None
        text = None
        try:
            ppd = cups.PPD (tmpf)
            self.answers['cups_printer_ppd_valid'] = True

            def options (options_list):
                o = {}
                for option in options_list:
                    o[option.keyword] = option.defchoice
                return o

            defaults = {}
            for group in ppd.optionGroups:
                g = options (group.options)
                for subgroup in group.subgroups:
                    g[subgroup.name] = options (subgroup.options)
                defaults[group.name] = g
            self.answers['cups_printer_ppd_defaults'] = defaults
        except RuntimeError:
            title = _("Invalid PPD File")
            self.answers['cups_printer_ppd_valid'] = False
            try:
                self.op = TimedSubprocess (parent=parent,
                                           args=['cupstestppd', '-rvv', tmpf],
                                           close_fds=True,
                                           stdin=file("/dev/null"),
                                           stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE)
                result = self.op.run ()
                self.answers['cupstestppd_output'] = result
                text = _("The PPD file for printer '%s' does not conform "
                         "to the specification.  "
                         "Possible reason follows:") % name
                text += '\n' + reduce (lambda x, y: x + '\n' + y, result[0])
            except OSError:
                # Perhaps cupstestppd is not in the path.
                text = _("There is a problem with the PPD file for "
                         "printer '%s'.") % name

        if tmpf:
            os.unlink (tmpf)

        if title == None and not answers['cups_printer_remote']:
            (pkgs, exes) = cupshelpers.missingPackagesAndExecutables (ppd)
            self.answers['missing_pkgs_and_exes'] = (pkgs, exes)
            if len (pkgs) > 0 or len (exes) > 0:
                title = _("Missing Printer Driver")
                if len (pkgs) > 0:
                    try:
                        self.packagekit = installpackage.PackageKit ()
                    except:
                        pkgs = []

                if len (pkgs) > 0:
                    self.package = pkgs[0]
                    text = _("Printer '%s' requires the %s package but it "
                             "is not currently installed.") % (name,
                                                               self.package)
                    self.install_button.show ()
                else:
                    text = _("Printer '%s' requires the '%s' program but it "
                             "is not currently installed.") % (name,
                                                               (exes + pkgs)[0])

        if title != None:
            self.label.set_markup ('<span weight="bold" size="larger">' +
                                   title + '</span>\n\n' + text)

        return title != None

    def connect_signals (self, handle):
        self.button_sigid = self.install_button.connect ("clicked",
                                                         self.install_clicked)

    def disconnect_signals (self):
        self.install_button.disconnect (self.button_sigid)

    def collect_answer (self):
        return self.answers

    def cancel_operation (self):
        self.op.cancel ()

    def install_clicked (self, button):
        pkgs = self.answers.get('packages_installed', [])
        pkgs.append (self.package)
        self.answers['packages_installed'] = pkgs
        try:
            self.packagekit.InstallPackageName (0, 0, self.package)
        except:
            pass

#!/usr/bin/python

## Printing troubleshooter

## Copyright (C) 2008, 2012 Red Hat, Inc.
## Copyright (C) 2008, 2012 Tim Waugh <twaugh@redhat.com>

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

import locale

from gi.repository import Gtk

from base import *

class Locale(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Locale issues")
        page = self.initial_vbox (_("Incorrect Page Size"),
                                  _("The page size for the print job was "
                                    "not the printer's default page size.  "
                                    "If this is not intentional it may cause "
                                    "alignment problems."))

        table = Gtk.Table (2, 2)
        table.set_row_spacings (6)
        table.set_col_spacings (6)
        page.pack_start (table, False, False, 0)
        self.printer_page_size = Gtk.Label ()
        self.printer_page_size.set_alignment (0, 0)
        self.job_page_size = Gtk.Label ()
        self.job_page_size.set_alignment (0, 0)
        label = Gtk.Label(label=_("Print job page size:"))
        label.set_alignment (0, 0)
        table.attach (label, 0, 1, 0, 1, xoptions=Gtk.AttachOptions.FILL, yoptions=0)
        table.attach (self.job_page_size, 1, 2, 0, 1,
                      xoptions=Gtk.AttachOptions.FILL, yoptions=0)
        label = Gtk.Label(label=_("Printer page size:"))
        label.set_alignment (0, 0)
        table.attach (label, 0, 1, 1, 2, xoptions=Gtk.AttachOptions.FILL, yoptions=0)
        table.attach (self.printer_page_size, 1, 2, 1, 2,
                      xoptions=Gtk.AttachOptions.FILL, yoptions=0)
        troubleshooter.new_page (page, self)

    def display (self):
        self.answers = {}
        (messages, encoding) = locale.getlocale (locale.LC_MESSAGES)
        (ctype, encoding) = locale.getlocale (locale.LC_CTYPE)
        self.answers['user_locale_messages'] = messages
        self.answers['user_locale_ctype'] = ctype

        try:
            system_lang = None
            conf = None
            for conffile in ["/etc/locale.conf", "/etc/sysconfig/i18n"]:
                try:
                    conf = file (conffile).readlines ()
                except IOError:
                    continue

            if conf != None:
                for line in conf:
                    if line.startswith("LC_PAPER="):
                        system_lang = line[9:].strip ('\n"')
                    elif system_lang == None and line.startswith ("LANG="):
                        system_lang = line[5:].strip ('\n"')

                if system_lang != None:
                    dot = system_lang.find ('.')
                    if dot != -1:
                        system_lang = system_lang[:dot]
        except:
            system_lang = None

        self.answers['system_locale_lang'] = system_lang

        printer_page_size = None
        try:
            ppd_defs = self.troubleshooter.answers['cups_printer_ppd_defaults']
            for group, options in ppd_defs.iteritems ():
                if options.has_key ("PageSize"):
                    printer_page_size = options["PageSize"]
                    break

        except KeyError:
            try:
                attrs = self.troubleshooter.answers['remote_cups_queue_attributes']
                printer_page_size = attrs["media-default"]
            except KeyError:
                pass

        try:
            job_status = self.troubleshooter.answers["test_page_job_status"]
        except KeyError:
            job_status = []

        self.answers['printer_page_size'] = printer_page_size
        if printer_page_size != None:
            job_page_size = None
            for (test, jobid, printer, doc, status, attrs) in job_status:
                if test:
                    if attrs.has_key ("PageSize"):
                        job_page_size = attrs["PageSize"]
                        self.answers['job_page_size'] = job_page_size
                        if job_page_size != printer_page_size:
                            self.printer_page_size.set_text (printer_page_size)
                            self.job_page_size.set_text (job_page_size)
                            return True

        return False

    def collect_answer (self):
        return self.answers


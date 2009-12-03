#!/usr/bin/env python

## Copyright (C) 2007, 2008, 2009 Tim Waugh <twaugh@redhat.com>
## Copyright (C) 2007, 2008, 2009 Red Hat, Inc.

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

_ = lambda x: x
def set_gettext_function (fn):
    global _
    _ = fn

class StateReason:
    REPORT=1
    WARNING=2
    ERROR=3

    LEVEL_ICON={
        REPORT: "dialog-info",
        WARNING: "dialog-warning",
        ERROR: "dialog-error"
        }

    def __init__(self, connection, printer, reason):
        self.printer = printer
        self.reason = reason
        self.level = None
        self.canonical_reason = None
        self.connection = connection

    def get_printer (self):
        return self.printer

    def get_level (self):
        if self.level != None:
            return self.level

        if (self.reason.endswith ("-report") or
            self.reason == "connecting-to-device"):
            self.level = self.REPORT
        elif self.reason.endswith ("-warning"):
            self.level = self.WARNING
        else:
            self.level = self.ERROR

        return self.level

    def get_reason (self):
        if self.canonical_reason:
            return self.canonical_reason

        level = self.get_level ()
        reason = self.reason
        if level == self.WARNING and reason.endswith ("-warning"):
            reason = reason[:-8]
        elif level == self.ERROR and reason.endswith ("-error"):
            reason = reason[:-6]
        self.canonical_reason = reason
        return self.canonical_reason

    def __repr__ (self):
        self.get_level()
        if self.level == self.REPORT:
            level = "REPORT"
        elif self.level == self.WARNING:
            level = "WARNING"
        else:
            level = "ERROR"

        return "<statereason.StateReason (%s,%s,%s)>" % (level,
                                                         self.get_printer (),
                                                         self.get_reason ())

    def get_description (self):
        messages = {
            'toner-low': (_("Toner low"),
                          _("Printer '%s' is low on toner.")),
            'toner-empty': (_("Toner empty"),
                            _("Printer '%s' has no toner left.")),
            'cover-open': (_("Cover open"),
                           _("The cover is open on printer '%s'.")),
            'door-open': (_("Door open"),
                          _("The door is open on printer '%s'.")),
            'media-low': (_("Paper low"),
                          _("Printer '%s' is low on paper.")),
            'media-empty': (_("Out of paper"),
                            _("Printer '%s' is out of paper.")),
            'marker-supply-low': (_("Ink low"),
                                  _("Printer '%s' is low on ink.")),
            'marker-supply-empty': (_("Ink empty"),
                                    _("Printer '%s' has no ink left.")),
            'offline': (_("Printer off-line"),
                        _("Printer '%s' is currently off-line.")),
            'connecting-to-device': (_("Not connected?"),
                                     _("Printer '%s' may not be connected.")),
            'other': (_("Printer error"),
                      _("There is a problem on printer '%s'.")),
            }
        try:
            (title, text) = messages[self.get_reason ()]
            try:
                text = text % self.get_printer ()
            except TypeError:
                # Probably an incorrect translation, missing a '%s'.
                pass
        except KeyError:
            if self.get_level () == self.REPORT:
                title = _("Printer report")
            elif self.get_level () == self.WARNING:
                title = _("Printer warning")
            elif self.get_level () == self.ERROR:
                title = _("Printer error")

            try:
                f = self.connection.getPPD(self.printer)
                ppd = cups.PPD (f)
                schemes = ["text", "http", "help", "file"]
                localized_reason = ""
                for scheme in schemes:
                    reason = ppd.localizeIPPReason(self.reason, scheme)
                    if reason != None:
                        localized_reason = localized_reason + reason + ", "
                if localized_reason != "":
                    reason = localized_reason[:-2]
                else:
                    reason = self.get_reason()
            except (cups.IPPError, RuntimeError):
                reason = self.get_reason()

            text = _("Printer '%s': '%s'.") % (self.get_printer (), reason)
        return (title, text)

    def get_tuple (self):
        return (self.get_level (), self.get_printer (), self.get_reason ())

    def __cmp__(self, other):
        if other == None:
            return 1
        if other.get_level () != self.get_level ():
            return cmp (self.get_level (), other.get_level ())
        if other.get_printer () != self.get_printer ():
            return cmp (other.get_printer (), self.get_printer ())
        return cmp (other.get_reason (), self.get_reason ())

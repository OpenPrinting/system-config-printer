#!/usr/bin/python

## Printing troubleshooter

## Copyright (C) 2008 Red Hat, Inc.
## Copyright (C) 2008 Tim Waugh <twaugh@redhat.com>

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

from base import *
class LocalOrRemote(Multichoice):
    def __init__ (self, troubleshooter):
        Multichoice.__init__ (self, troubleshooter, "printer_is_remote",
                              _("Printer Location"),
                              _("Is the printer connected to this computer "
                                "or available on the network?"),
                              [(_("Locally connected printer"), False),
                               (_("Network printer"), True)],
                              "Local or remote?")

    def display (self):
        return not self.troubleshooter.answers['cups_queue_listed']

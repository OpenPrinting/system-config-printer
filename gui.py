#!/usr/bin/python

## system-config-printer

## Copyright (C) 2006, 2007, 2008, 2009, 2010, 2012 Red Hat, Inc.
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

from gi.repository import GObject
from gi.repository import Gtk
import os

import config
pkgdata = config.pkgdatadir

class GtkGUI(GObject.GObject):
    def getWidgets(self, widgets, domain=None):
        ui_dir = os.environ.get ("SYSTEM_CONFIG_PRINTER_UI",
                                 os.path.join (pkgdata, "ui"))
        self._bld = []
        for xmlfile, names in widgets.iteritems ():
            bld = Gtk.Builder ()
            self._bld.append (bld)

            if domain:
                bld.set_translation_domain (domain)

            bld.add_from_file (os.path.join (ui_dir, xmlfile + ".ui"))
            for name in names:
                widget = bld.get_object(name)
                if widget is None:
                    raise ValueError, "Widget '%s' not found" % name
                setattr(self, name, widget)

            try:
                win = widget.get_top_level()
            except AttributeError:
                win = None
            
            if win != None:
                Gtk.Window.set_focus_on_map(widget.get_top_level (),
                                            self.focus_on_map)
                widget.show()

    def connect_signals (self):
        map (lambda x: x.connect_signals (self), self._bld)

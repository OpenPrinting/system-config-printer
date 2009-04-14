#!/usr/bin/env python

## system-config-printer

## Copyright (C) 2006, 2007, 2008 Red Hat, Inc.
## Copyright (C) 2006, 2007 Florian Festi <ffesti@redhat.com>
## Copyright (C) 2006, 2007, 2008 Tim Waugh <twaugh@redhat.com>

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

import gtk.glade
import os

import config
pkgdata = config.pkgdatadir

class GtkGUI:
    def getWidgets(self, widgets):
        glade_dir = os.environ.get ("SYSTEM_CONFIG_PRINTER_GLADE",
                                    os.path.join (pkgdata, "glade"))
        for xmlfile, names in widgets.iteritems ():
            xml = gtk.glade.XML (os.path.join (glade_dir, xmlfile + ".glade"))
            for name in names:
                widget = xml.get_widget(name)
                if widget is None:
                    raise ValueError, "Widget '%s' not found" % name
                setattr(self, name, widget)

            try:
                win = widget.get_top_level()
            except AttributeError:
                win = None
            
            if win != None:
                gtk.Window.set_focus_on_map(widget.get_top_level (),
                                            self.focus_on_map)
                widget.show()

            xml.signal_autoconnect(self)

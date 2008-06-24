## Copyright (C) 2008 Rui Matos <tiagomatos@gmail.com>

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

import gobject
import gtk

from gettext import gettext as _

# FIXME: we should make subclasses of these objects so that they define all of
# their behaviour on the subclasses like setting the icon, label and so on. We
# might even make them have a method to call externally and show us a popup
# menu. Also we might define here the behaviour on drag and drop.
class GroupsPaneItem (gobject.GObject):
    def __init__ (self):
        super (GroupsPaneItem, self).__init__ ()

        self.icon = None
        self.label = None
        self.separator = False

class AllPrintersItem (GroupsPaneItem):
    def __init__ (self):
        super (AllPrintersItem, self).__init__ ()

        theme = gtk.icon_theme_get_default ()
        try:
            self.icon = theme.load_icon ('gnome-dev-printer',
                                         gtk.ICON_SIZE_MENU, 0)
        except gobject.GError:
            pass

        self.label = _("All Printers")

class SeparatorItem (GroupsPaneItem):
    def __init__ (self):
        super (SeparatorItem, self).__init__ ()

        self.separator = True

class FavouritesItem (GroupsPaneItem):
    def __init__ (self):
        super (FavouritesItem, self).__init__ ()

        theme = gtk.icon_theme_get_default ()
        try:
            self.icon = theme.load_icon ('gnome-dev-printer',
                                         gtk.ICON_SIZE_MENU, 0)
        except gobject.GError:
            pass

        self.label = _("Favourites")

class GroupsPaneModel (gtk.ListStore):
    def __init__ (self):
        super (GroupsPaneModel, self).__init__ (GroupsPaneItem)

    def append (self, item):
        return super (GroupsPaneModel, self).append ([item])

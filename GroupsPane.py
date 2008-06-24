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

import gtk
import gobject
from gettext import gettext as _

from GroupsPaneModel import *

class GroupsPane (gtk.ScrolledWindow):
    __gsignals__ = {
        'item-activated' : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE,
                            [GroupsPaneItem])
        }

    def __init__ (self, first_group_item):
        super (GroupsPane, self).__init__ ()

        self.tree_view = None
        self.store = None

        self.set_policy (gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)

        self.tree_view = gtk.TreeView ()
        self.tree_view.set_headers_visible (False)

        column = gtk.TreeViewColumn ()

        cell = gtk.CellRendererPixbuf ()
        column.pack_start (cell, False)
        column.set_cell_data_func (cell, self.icon_cell_data_func)

        cell = gtk.CellRendererText ()
        column.pack_start (cell, True)
        column.set_cell_data_func (cell, self.label_cell_data_func)

        # To change the group name in place
        cell.connect ('edited', self.on_group_name_edited)
        cell.connect ('editing-canceled', self.on_group_name_editing_canceled)

        self.tree_view.set_row_separator_func (self.row_separator_func)
        self.tree_view.append_column (column)

        self.store = GroupsPaneModel ()
        self.tree_view.set_model (self.store)

        self.add (self.tree_view)
        self.show_all ()

        selection = self.tree_view.get_selection ()
        selection.set_mode (gtk.SELECTION_BROWSE)

        self.tree_view.connect ('button-press-event',
                                self.on_single_click_activate)
        self.tree_view.connect ('row-activated', self.on_row_activated)

        selection = self.tree_view.get_selection ()
        selection.select_iter (self.store.append (first_group_item))
        self.store.append (FavouritesItem ())
        self.store.append (SeparatorItem ())

    def icon_cell_data_func (self, column, cell, model, iter):
        icon = model.get_value (iter, 0).icon
        cell.set_properties (pixbuf = icon)

    def label_cell_data_func (self, column, cell, model, iter):
        label = model.get_value (iter, 0).label
        cell.set_properties (text = label)

    def on_group_name_edited (self):
        pass

    def on_group_name_editing_canceled (self):
        pass

    def on_single_click_activate (self, tree_view, event):
        if (event.type == gtk.gdk.BUTTON_PRESS and event.button == 1):
            t = self.tree_view.get_path_at_pos (event.x, event.y)
            if t != None:
                self.tree_view.row_activated (t[0], t[1])

        return False

    def on_row_activated (self, tree_view, path, column):
        item = self.store.get_value (self.store.get_iter (path), 0)
        self.emit ('item-activated', item)

    def row_separator_func (self, model, iter):
        return model.get_value (iter, 0).separator

gobject.type_register (GroupsPane)

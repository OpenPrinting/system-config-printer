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
from XmlHelper import xml_helper

class GroupsPane (gtk.ScrolledWindow):
    __gsignals__ = {
        'item-activated' : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE,
                            [GroupsPaneItem]),
        'items-changed' : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE,
                           []),
        }

    def __init__ (self):
        super (GroupsPane, self).__init__ ()

        self.tree_view = None
        self.store = None
        self.groups_menu = None
        self.ui_manager = None
        self.currently_selected_queues = []

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

        self.tree_view.connect ('key-press-event',
                                self.on_key_press_event)
        self.tree_view.connect ('button-press-event',
                                self.on_button_press_event)
        self.tree_view.connect ('button-press-event',
                                self.on_single_click_activate)
        self.tree_view.connect ('row-activated',
                                self.on_row_activated)
        self.tree_view.connect ('popup-menu',
                                self.on_popup_menu)

        self.tree_view.enable_model_drag_dest ([("queue", 0, 0)],
                                               gtk.gdk.ACTION_COPY)
        self.tree_view.connect ("drag-data-received",
                                self.on_drag_data_received)
        self.tree_view.connect ("drag-drop",
                                self.on_drag_drop)
        self.tree_view.connect ("drag-motion",
                                self.on_drag_motion)

        # actions
        action_group = gtk.ActionGroup ("GroupsPaneActionGroup")
        action_group.add_actions ([
                ("new-group", gtk.STOCK_NEW, _("_New Group"),
                 "<Ctrl>g", None, self.on_new_group_activate),
                ("new-group-from-selection", None,
                 _("_New Group from Selection"),
                 "<Ctrl><Shift>g", None,
                 self.on_new_group_from_selection_activate),
                ("rename-group", None, _("_Rename"),
                 None, None, self.on_rename_group_activate),
                ("delete-group", gtk.STOCK_DELETE, None,
                 None, None, self.on_delete_group_activate),
                ])
        action_group.get_action (
            "new-group-from-selection").set_sensitive (False)
        action_group.get_action (
            "rename-group").set_sensitive (False)
        action_group.get_action (
            "delete-group").set_sensitive (False)

        self.ui_manager = gtk.UIManager ()
        self.ui_manager.insert_action_group (action_group, -1)
        self.ui_manager.add_ui_from_string (
"""
<ui>
 <accelerator action="new-group"/>
 <accelerator action="new-group-from-selection"/>
 <accelerator action="rename-group"/>
 <accelerator action="delete-group"/>
</ui>
"""
)
        self.ui_manager.ensure_update ()

        self.groups_menu = gtk.Menu ()
        for action_name in ["new-group",
                            "new-group-from-selection",
                            None,
                            "rename-group",
                            "delete-group"]:
            if not action_name:
                item = gtk.SeparatorMenuItem ()
            else:
                action = action_group.get_action (action_name)
                item = action.create_menu_item ()
            item.show ()
            self.groups_menu.append (item)

        selection = self.tree_view.get_selection ()
        selection.connect ("changed", self.on_selection_changed)
        selection.set_mode (gtk.SELECTION_BROWSE)
        selection.select_iter (self.store.append (AllPrintersItem ()))
#        self.store.append (FavouritesItem ())
        self.store.append (SeparatorItem ())
        for group_name, group_node in xml_helper.get_static_groups ():
            self.store.append (StaticGroupItem (group_name, group_node))
        for group_name, group_node in xml_helper.get_search_groups ():
            self.store.append (SavedSearchGroupItem (group_name,
                                                     xml_node = group_node))

    def icon_cell_data_func (self, column, cell, model, iter):
        icon = model.get (iter).icon
        cell.set_properties (pixbuf = icon)

    def label_cell_data_func (self, column, cell, model, iter):
        label = model.get (iter).name
        cell.set_properties (text = label)

    def on_group_name_edited (self, cell, path, new_text):
        cell.set_properties (editable = False)

        group_item = self.get_selected_item ()
        if group_item.name == new_text:
            return

        if self.store.lookup_by_name (new_text):
            dialog = gtk.MessageDialog (self.get_toplevel (),
                                        gtk.DIALOG_DESTROY_WITH_PARENT,
                                        gtk.MESSAGE_ERROR,
                                        gtk.BUTTONS_OK,
                                        _("The item could not be renamed."))
            dialog.format_secondary_text (_("The name \"%s\" is already "
                                            "in use. Please use a different "
                                            "name.") % new_text)
            dialog.connect ('response', lambda dialog, x: dialog.destroy ())
            dialog.show ()
            return

        group_item.rename (new_text)
        self.emit ("items-changed")

    def on_group_name_editing_canceled (self, cell):
        cell.set_properties (editable = False)

    def on_key_press_event (self, tree_view, event):
        modifiers = gtk.accelerator_get_default_mod_mask ()

        if ((event.keyval == gtk.keysyms.BackSpace or
             event.keyval == gtk.keysyms.Delete or
             event.keyval == gtk.keysyms.KP_Delete) and
            ((event.state & modifiers) == 0)):

            self.delete_selected_group ()
            return True

        if ((event.keyval == gtk.keysyms.F2) and
            ((event.state & modifiers) == 0)):

            self.rename_selected_group ()
            return True

        return False

    def on_single_click_activate (self, tree_view, event):
        # idea from eel_gtk_tree_view_set_activate_on_single_click ()
        if event.button == 1:
            t = self.tree_view.get_path_at_pos (int (event.x),
                                                int (event.y))
            if t != None:
                self.tree_view.row_activated (t[0], t[1])

        return False

    def on_row_activated (self, tree_view, path, column):
        tree_view.get_selection ().select_path (path)
        item = self.store.get (path)
        self.emit ('item-activated', item)

    def on_selection_changed (self, selection):
        model, titer = selection.get_selected ()
        group_item = model.get (titer)
        sensitivity = isinstance (group_item, MutableItem)
        self.ui_manager.get_action ("/rename-group").set_sensitive (sensitivity)
        self.ui_manager.get_action ("/delete-group").set_sensitive (sensitivity)

    def row_separator_func (self, model, iter):
        return model.get (iter).separator

    def do_popup_menu (self, event):
        # idea from eel_pop_up_context_menu ()
        button = 0
        activate_time = 0L # GDK_CURRENT_TIME
        if event:
            activate_time = event.time
            if event.type != gtk.gdk.BUTTON_RELEASE:
                button = event.button

        self.groups_menu.popup (None, None, None, button, activate_time)

    def on_button_press_event (self, tree_view, event):
        if event.button == 3:
            selection = tree_view.get_selection ()
            model, selected_paths = selection.get_selected_rows ()
            click_info = tree_view.get_path_at_pos (int (event.x),
                                                    int (event.y))
            if click_info and (click_info[0] not in selected_paths):
                selection.select_path (click_info[0])

            self.do_popup_menu (event)

        return False

    def on_popup_menu (self, tree_view):
        self.do_popup_menu (None)

        return True

    def on_rename_group_activate (self, UNUSED):
        self.rename_selected_group ()

    def on_delete_group_activate (self, UNUSED):
        self.delete_selected_group ()

    def rename_selected_group (self):
        model, titer = self.tree_view.get_selection ().get_selected ()
        group_item = model.get (titer)
        if not isinstance (group_item, MutableItem):
            return

        column = self.tree_view.get_column (0)
        cell = None
        for cr in column.get_cell_renderers ():
            if isinstance (cr, gtk.CellRendererText):
                cell = cr
                break
        cell.set_properties (editable = True)
        self.tree_view.set_cursor_on_cell (model.get_path (titer),
                                           column, cell, True)

    def delete_selected_group (self):
        model, titer = self.tree_view.get_selection ().get_selected ()
        group_item = model.get (titer)
        if not isinstance (group_item, MutableItem):
            return

        dialog = gtk.MessageDialog (self.get_toplevel (),
                                    gtk.DIALOG_DESTROY_WITH_PARENT |
                                    gtk.DIALOG_MODAL,
                                    gtk.MESSAGE_WARNING,
                                    gtk.BUTTONS_NONE,
                                    _("Are you sure you want to "
                                      "permanently delete \"%s\"?") %
                                    group_item.name)
        dialog.add_buttons (gtk.STOCK_CANCEL, gtk.RESPONSE_REJECT,
                            gtk.STOCK_DELETE, gtk.RESPONSE_ACCEPT)
        dialog.set_default_response (gtk.RESPONSE_REJECT)
        dialog.format_secondary_text (_("This will not delete any printer queues from your computer. To delete queues completely, you must delete them from the 'All Printers' group."))
        dialog.connect ('response', self.on_delete_selected_group_response,
                        group_item, titer)
        dialog.show ()

    def on_delete_selected_group_response (self, dialog, response,
                                           group_item, titer):
        dialog.destroy ()

        if response == gtk.RESPONSE_ACCEPT:
            self.tree_view.row_activated (
                self.store.get_path (self.store.get_iter_first ()),
                self.tree_view.get_column (0))
            self.store.remove (titer)
            group_item.delete ()
            self.emit ("items-changed")

    def get_selected_item (self):
        model, titer = self.tree_view.get_selection ().get_selected ()
        return model.get (titer)

    def generate_new_group_name (self):
        name = _('New Group')

        if not self.store.lookup_by_name (name):
            return name

        i = 1
        while True:
            new_name = name + ' %d' % i
            if not self.store.lookup_by_name (new_name):
                return new_name
            i += 1

    def _create_new_group_common (self, item):
        titer = self.store.append_by_type (item)
        self.emit ("items-changed")
        self.tree_view.row_activated (
            self.store.get_path (titer),
            self.tree_view.get_column (0))
        self.rename_selected_group ()

    def create_new_search_group (self, criterion, group_name = None):
        item = SavedSearchGroupItem (
            group_name and group_name or self.generate_new_group_name (),
            criteria = [criterion])
        self._create_new_group_common (item)

    def create_new_group (self, printer_queues, group_name = None):
        item = StaticGroupItem (
            group_name and group_name or self.generate_new_group_name ())
        item.add_queues (printer_queues)
        self._create_new_group_common (item)

    def on_new_group_activate (self, UNUSED):
        self.create_new_group ([])

    def on_new_group_from_selection_activate (self, UNUSED):
        self.create_new_group (self.currently_selected_queues)

    def is_drop_target (self, tree_view, x, y):
        try:
            path, position = self.tree_view.get_dest_row_at_pos (x, y)
            group_item = self.store.get (path)
        except TypeError:
            return False

        if not isinstance (group_item, StaticGroupItem):
            return False

        return True

    def on_drag_data_received (self, tree_view, context, x, y,
                               selection_data, info, timestamp):
        if not selection_data.data  or info != 0:
            context.finish (False, False, timestamp)
            return

        if not self.is_drop_target (tree_view, x, y):
            context.finish (False, False, timestamp)
            return

        path, position = self.tree_view.get_dest_row_at_pos (x, y)
        group_item = self.store.get (path)
        group_item.add_queues (selection_data.data.splitlines ())
        context.finish (True, False, timestamp)

    def on_drag_drop (self, tree_view, context, x, y, timestamp):
        if not self.is_drop_target (tree_view, x, y):
            return False

        target_list = tree_view.drag_dest_get_target_list ()
        target = tree_view.drag_dest_find_target (context, target_list)
        tree_view.drag_get_data (context, target, timestamp)
        return True

    def on_drag_motion (self, tree_view, context, x, y, timestamp):
        if not self.is_drop_target (tree_view, x, y):
            return False

        path, position = tree_view.get_dest_row_at_pos (x, y)
        tree_view.set_drag_dest_row (path, position)

        context.drag_status (gtk.gdk.ACTION_COPY, timestamp)
        return True

    def get_static_groups (self):
        static_groups = []
        for row in self.store:
            if isinstance (row[0], StaticGroupItem):
                static_groups.append (row[0])
        return static_groups

    def n_groups (self):
        n = 0
        for row in self.store:
            if (isinstance (row[0], StaticGroupItem) or
                isinstance (row[0], SavedSearchGroupItem)):
                    n += 1
        return n

gobject.type_register (GroupsPane)

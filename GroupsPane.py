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
                            [GroupsPaneItem])
        }

    def __init__ (self):
        super (GroupsPane, self).__init__ ()

        self.tree_view = None
        self.store = None
        self.action_group = None
        self.popup_menu_main_list = []

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

        self.tree_view.connect ('key-press-event',
                                self.on_key_press_event)
        self.tree_view.connect ('button-press-event',
                                self.on_single_click_activate)
        self.tree_view.connect ('row-activated',
                                self.on_row_activated)
        self.tree_view.connect ('button-release-event',
                                self.on_button_release)
        self.tree_view.connect ('popup-menu',
                                self.on_popup_menu)

        selection.select_iter (self.store.append (AllPrintersItem ()))
        self.store.append (FavouritesItem ())
        self.store.append (SeparatorItem ())
        for group_name, group_node in xml_helper.get_static_groups ():
            self.store.append (StaticGroupItem (group_name, group_node))

        # groups actions
        self.action_group = gtk.ActionGroup ('groups_actions')
        self.action_group.add_actions ([
                ('new_group', gtk.STOCK_NEW, _('_New Group'),
                 None, None, self.on_new_group_activate)
                ])

        # popup menu's persistent items
        item = self.action_group.get_action ('new_group').create_menu_item ()
        self.popup_menu_main_list.append (item)

    def icon_cell_data_func (self, column, cell, model, iter):
        icon = model.get_value (iter, 0).icon
        cell.set_properties (pixbuf = icon)

    def label_cell_data_func (self, column, cell, model, iter):
        label = model.get_value (iter, 0).name
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
                                        gtk.BUTTONS_CLOSE,
                                        _("The item could not be renamed."))
            dialog.format_secondary_text (_("The name \"") + new_text +
                                          _("\" is already in use. Please use a different name."))
            dialog.connect ('response', lambda dialog, x: dialog.destroy ())
            dialog.show ()
            return

        group_item.rename (new_text)

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
            t = self.tree_view.get_path_at_pos (event.x, event.y)
            if t != None:
                self.tree_view.row_activated (t[0], t[1])

        return False

    def on_row_activated (self, tree_view, path, column):
        item = self.store.get_value (self.store.get_iter (path), 0)
        self.emit ('item-activated', item)

    def row_separator_func (self, model, iter):
        return model.get_value (iter, 0).separator

    def do_popup_menu (self, event):
        # idea from eel_pop_up_context_menu ()
        button = 0
        activate_time = 0 # GDK_CURRENT_TIME
        if event:
            if event.type != gtk.gdk.BUTTON_RELEASE:
                button = event.button
            activate_time = event.time

        menu = self.build_popup_menu ()
        menu.connect ('unmap', self.on_popup_menu_unmap)
        menu.attach_to_widget (self, self.on_popup_menu_detach)
        menu.popup (None, None, None, button, activate_time)

    def on_popup_menu_unmap (self, menu):
        menu.destroy ()

    def on_popup_menu_detach (self, menu, UNUSED):
        for item in menu.get_children ():
            menu.remove (item)

    def on_button_release (self, tree_view, event):
        if event.button == 3:
            self.do_popup_menu (event)

        return False

    def on_popup_menu (self, tree_view):
        self.do_popup_menu (None)

        return True

#     def on_selection_changed (self, selection):
#         model, titer = selection.get_selected ()
#         item = model.get (titer)
#         self.popup_menu = item.get_menu ()

    def build_popup_menu (self):
        menu = gtk.Menu ()

        for item in self.popup_menu_main_list:
            item.show ()
            menu.append (item)

        model, titer = self.tree_view.get_selection ().get_selected ()
        group_item = model.get (titer)
        if isinstance (group_item, MutableItem):
            item = gtk.SeparatorMenuItem ()
            item.show ()
            menu.append (item)

            item = gtk.MenuItem (_("_Rename"))
            item.connect ('activate', self.on_popup_menu_group_rename)
            item.show ()
            menu.append (item)

            item = gtk.ImageMenuItem (gtk.STOCK_DELETE)
            item.connect ('activate', self.on_popup_menu_group_delete)
            item.show ()
            menu.append (item)

        return menu

    def on_popup_menu_group_rename (self, UNUSED):
        self.rename_selected_group ()

    def on_popup_menu_group_delete (self, UNUSED):
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
                                    _("Are you sure you want to permanently delete \"") +
                                    group_item.name +
                                    _("\"?"))
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
            self.store.remove (titer)
            group_item.delete ()

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

    def on_new_group_activate (self, UNUSED):
        item = StaticGroupItem (self.generate_new_group_name ())
        self.store.append_by_type (item)

gobject.type_register (GroupsPane)

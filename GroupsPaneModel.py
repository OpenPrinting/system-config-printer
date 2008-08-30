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
import libxml2
from XmlHelper import xml_helper
from SearchCriterion import *
from gettext import gettext as _

from debug import *

class GroupsPaneItem (gobject.GObject):
    def __init__ (self):
        super (GroupsPaneItem, self).__init__ ()

        self.icon = None
        self.name = None
        self.separator = False

    def load_icon (self, icon_name):
        theme = gtk.icon_theme_get_default ()
        try:
            return theme.load_icon (icon_name,
                                    gtk.ICON_SIZE_MENU, 0)
        except gobject.GError:
            return None

class AllPrintersItem (GroupsPaneItem):
    def __init__ (self):
        super (AllPrintersItem, self).__init__ ()

        self.icon = self.load_icon ('printer')
        self.name = _("All Printers")

class SeparatorItem (GroupsPaneItem):
    def __init__ (self):
        super (SeparatorItem, self).__init__ ()

        self.separator = True

class FavouritesItem (GroupsPaneItem):
    def __init__ (self):
        super (FavouritesItem, self).__init__ ()

        self.icon = self.load_icon ('emblem-favorite')
        self.name = _("Favorites")

# Helper common base class, do not instantiate
class MutableItem (GroupsPaneItem):
    def __init__ (self, name, xml_node = None):
        super (MutableItem, self).__init__ ()

        self.name = name
        self.xml_node = xml_node

    def rename (self, new_name):
        self.xml_node.setProp ("name", new_name)
        xml_helper.write ()

        self.name = new_name

    def delete (self):
        self.xml_node.unlinkNode ()
        self.xml_node.freeNode ()
        xml_helper.write ()

class StaticGroupItem (MutableItem):
    def __init__ (self, name, xml_node = None):
        super (StaticGroupItem, self).__init__ (name, xml_node)

        self.icon = self.load_icon ('folder')
        self.printer_queues = []

        if not self.xml_node:
            self.xml_node = libxml2.newNode ("static-group")
            self.xml_node.newProp ("name", self.name)
            self.xml_node.newChild (None, "queues", None)
            xml_helper.add_group (self.xml_node)
        else:
            if not self.xml_node.children.children:
                # no queues
                return
            else:
                queue_node = self.xml_node.children.children
                while queue_node:
                    self.printer_queues.append (queue_node.prop ("name"))
                    queue_node = queue_node.next

    def add_queues (self, queue_list):
        queues_node = self.xml_node.children

        for queue_name in queue_list:
            if queue_name not in self.printer_queues:
                queue_node = libxml2.newNode ("queue")
                queue_node.newProp ("name", queue_name)
                queues_node.addChild (queue_node)
                self.printer_queues.append (queue_name)

        xml_helper.write ()

    def remove_queues (self, queue_list):
        queues_node = self.xml_node.children

        for queue_name in queue_list:
            if queue_name in self.printer_queues:
                queue_node = self.xml_node.children.children
                while queue_node:
                    if queue_node.prop ("name") == queue_name:
                        break
                    queue_node = queue_node.next
                queue_node.unlinkNode ()
                queue_node.freeNode ()
                self.printer_queues.remove (queue_name)

        xml_helper.write ()

class SavedSearchGroupItem (MutableItem):
    def __init__ (self, name, criteria = [],
                  match_all = False, xml_node = None):
        super (SavedSearchGroupItem, self).__init__ (name, xml_node)

        self.icon = self.load_icon ('folder-saved-search')
        self.criteria = criteria
        self.match_all = match_all

        if not self.xml_node:
            self.xml_node = libxml2.newNode ("search-group")
            self.xml_node.newProp ("name", self.name)
            criteria_node = self.xml_node.newChild (None, "criterias", None)
            criteria_node.newProp ("match", self.match_all and "all" or "any")
            for criterion in self.criteria:
                criterion_node = criteria_node.newChild (None, "criteria", None)
                criterion_node.newChild (None, "subject",
                                         str (criterion.subject))
                criterion_node.newChild (None, "rule",
                                         str (criterion.rule))
                criterion_node.newChild (None, "value",
                                         str (criterion.value))
            xml_helper.add_group (self.xml_node)
        else:
            criteria_node = self.xml_node.children
            self.match_all = criteria_node.prop ("match") == "all"
            criterion_node = criteria_node.children
            while criterion_node:
                criterion = SearchCriterion ()

                crit_child = criterion_node.children
                while crit_child:
                    if crit_child.name == "subject":
                        criterion.subject = int (crit_child.content)
                    elif crit_child.name == "rule":
                        criterion.rule = int (crit_child.content)
                    elif crit_child.name == "value":
                        criterion.value = crit_child.content
                    else:
                        pass
                    crit_child = crit_child.next

                self.criteria.append (criterion)
                criterion_node = criterion_node.next

class GroupsPaneModel (gtk.ListStore):
    def __init__ (self):
        super (GroupsPaneModel, self).__init__ (GroupsPaneItem)

    def append (self, item):
        return super (GroupsPaneModel, self).append ([item])

    def get (self, iter_or_path):
        return self[iter_or_path][0]

    def lookup_by_name (self, name):
        for item in self:
            if name == item[0].name:
                return item[0]

        return None

    def append_by_type (self, new_item):
        new_item_type = type (new_item)

        titer = self.get_iter_first ()
        while titer:
            if type (self.get_value (titer, 0)) == new_item_type:
                break

            titer = self.iter_next (titer)

        while titer:
            if type (self.get_value (titer, 0)) != new_item_type:
                break

            titer = self.iter_next (titer)

        return self.insert_before (titer, [new_item])

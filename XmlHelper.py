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

import os
import libxml2
from debug import *

class XmlHelper (object):
    def __init__ (self, filename):
        self.group_file_name = None
        self.xml_doc = libxml2.newDoc ('1.0')
        self.xml_doc.setRootElement (libxml2.newNode ("ospm-groups"))

        self.group_file_name = filename

        if not os.path.exists (self.group_file_name):
            try:
                self.xml_doc.saveFormatFile (self.group_file_name, True)
            except:
                nonfatalException ()
        else:
            try:
                self.xml_doc = libxml2.parseFile (self.group_file_name)
            except:
                nonfatalException ()

    def write (self):
        if self.xml_doc.saveFormatFile (self.group_file_name, True) == -1:
            nonfatalException ()

    def __get_non_text_child (self, node):
        child = node.children

        while child and child.isText:
            child = child.next

        return child

    def __parse_groups (self, key):
        current = self.xml_doc.getRootElement ().children
        # FIXME: this does not work
        #current = self.__get_non_text_child (current)

        group_list = []
        while current:
            if current.name == key:
                group_list.append ((current.prop ("name"), current))

            current = current.next

        return group_list

    def get_static_groups (self):
        return self.__parse_groups ("static-group")

    def get_search_groups (self):
        return self.__parse_groups ("search-group")

    def add_group (self, group_node):
        self.xml_doc.getRootElement ().addChild (group_node)
        self.write ()

xml_helper = XmlHelper (os.path.expanduser ('~/.printer-groups.xml'))

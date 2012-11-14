#!/usr/bin/python

## Printing troubleshooter

## Copyright (C) 2008, 2009, 2011, 2012 Red Hat, Inc.
## Author: Tim Waugh <twaugh@redhat.com>

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

from gi.repository import Gtk

import cups
from gi.repository import GObject
from timedops import TimedOperation
from base import *
class ChooseNetworkPrinter(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Choose network printer")
        page1 = self.initial_vbox (_("Choose Network Printer"),
                                   _("Please select the network printer you "
                                     "are trying to use from the list below. "
                                     "If it does not appear in the list, "
                                     "select 'Not listed'."))
        tv = Gtk.TreeView ()
        name = Gtk.TreeViewColumn (_("Name"),
                                   Gtk.CellRendererText (), text=0)
        location = Gtk.TreeViewColumn (_("Location"),
                                       Gtk.CellRendererText (), text=1)
        info = Gtk.TreeViewColumn (_("Information"),
                                   Gtk.CellRendererText (), text=2)
        name.set_property ("resizable", True)
        location.set_property ("resizable", True)
        info.set_property ("resizable", True)
        tv.append_column (name)
        tv.append_column (location)
        tv.append_column (info)
        tv.set_rules_hint (True)
        sw = Gtk.ScrolledWindow ()
        sw.set_policy (Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.set_shadow_type (Gtk.ShadowType.IN)
        sw.add (tv)
        page1.pack_start (sw, True, True, 0)
        self.treeview = tv
        troubleshooter.new_page (page1, self)

    def display (self):
        answers = self.troubleshooter.answers
        if answers['cups_queue_listed']:
            return False

        if not answers.get ('remote_server_cups', False):
            return False

        server = answers['remote_server_try_connect']

        model = Gtk.ListStore (str,
                               str,
                               str,
                               GObject.TYPE_PYOBJECT)
        self.model = model
        self.treeview.set_model (model)
        iter = model.append (None)
        model.set (iter, 0, _("Not listed"), 1, '', 2, '', 3, 0)

        parent = self.troubleshooter.get_window ()

        try:
            self.op = TimedOperation (cups.Connection, 
                                      kwargs={"host": server},
                                      parent=parent)
            c = self.op.run ()
            self.op = TimedOperation (c.getDests, parent=parent)
            dests = self.op.run ()
            printers = None
            dests_list = []
            for (name, instance), dest in dests.iteritems ():
                if name == None:
                    continue

                if instance != None:
                    queue = "%s/%s" % (name, instance)
                else:
                    queue = name

                if printers == None:
                    self.op = TimedOperation (c.getPrinters)
                    printers = self.op.run ()

                if not printers.has_key (name):
                    info = _("Unknown")
                    location = _("Unknown")
                else:
                    printer = printers[name]
                    info = printer.get('printer-info', _("Unknown"))
                    location = printer.get('printer-location', _("Unknown"))

                dests_list.append ((queue, location, info, dest))

            dests_list.sort (lambda x, y: cmp (x[0], y[0]))
            for queue, location, info, dest in dests_list:
                iter = model.append (None)
                model.set (iter, 0, queue, 1, location, 2, info, 3, dest)

        except cups.HTTPError:
            pass
        except cups.IPPError:
            pass
        except RuntimeError:
            pass

        return True

    def connect_signals (self, handler):
        self.signal_id = self.treeview.connect ("cursor-changed", handler)

    def disconnect_signals (self):
        self.treeview.disconnect (self.signal_id)

    def can_click_forward (self):
        model, iter = self.treeview.get_selection ().get_selected ()
        if iter == None:
            return False
        return True

    def collect_answer (self):
        if not self.troubleshooter.answers.get ('remote_server_cups', False):
            return {}

        model, iter = self.treeview.get_selection ().get_selected ()
        if not model:
            return {}

        dest = model.get_value (iter, 3)
        if dest == 0:
            class enum_dests:
                def __init__ (self, model):
                    self.dests = []
                    model.foreach (self.each, None)

                def each (self, model, path, iter, user_data):
                    dest = model.get_value (iter, 3)
                    if dest:
                        self.dests.append ((dest.name, dest.instance))

            return { 'remote_cups_queue_listed': False,
                     'remote_cups_dests_available': enum_dests (model).dests }
        else:
            return { 'remote_cups_queue_listed': True,
                     'remote_cups_dest': dest,
                     'remote_cups_queue': dest.name,
                     'remote_cups_instance': dest.instance }

    def cancel_operation (self):
        self.op.cancel ()

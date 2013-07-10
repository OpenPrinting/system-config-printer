#!/usr/bin/python

## Printing troubleshooter

## Copyright (C) 2008, 2012 Red Hat, Inc.
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

from gi.repository import Gtk

class NoPrinter:
    pass

NotListed = NoPrinter()

import cups
from gi.repository import GObject
from timedops import TimedOperation
from base import *
class ChoosePrinter(Question):
    def __init__ (self, troubleshooter):
        # First question: which printer? (page 1)
        Question.__init__ (self, troubleshooter, "Choose printer")
        page1 = self.initial_vbox (_("Choose Printer"),
                                   _("Please select the printer you are "
                                     "trying to use from the list below. "
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
        model = Gtk.ListStore (str,
                               str,
                               str,
                               GObject.TYPE_PYOBJECT)
        self.treeview.set_model (model)
        iter = model.append (None)
        model.set (iter, 0, _("Not listed"), 1, '', 2, '', 3, NotListed)

        parent = self.troubleshooter.get_window ()
        try:
            cups.setServer ('')
            c = self.timedop (cups.Connection, parent=parent).run ()
            dests = self.timedop (c.getDests, parent=parent).run ()
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
                    printers = self.timedop (c.getPrinters,
                                             parent=parent).run ()

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
        model, iter = self.treeview.get_selection ().get_selected ()
        dest = model.get_value (iter, 3)
        if dest == NotListed:
            class enum_dests:
                def __init__ (self, model):
                    self.dests = []
                    model.foreach (self.each, None)

                def each (self, model, path, iter, user_data):
                    dest = model.get_value (iter, 3)
                    if dest != NotListed:
                        self.dests.append ((dest.name.decode ('utf-8'),
                                            dest.instance))

            return { 'cups_queue_listed': False,
                     'cups_dests_available': enum_dests (model).dests }
        else:
            return { 'cups_queue_listed': True,
                     'cups_dest': dest,
                     'cups_queue': dest.name.decode ('utf-8'),
                     'cups_instance': dest.instance }

    def cancel_operation (self):
        self.op.cancel ()

    def timedop (self, *args, **kwargs):
        self.op = TimedOperation (*args, **kwargs)
        return self.op

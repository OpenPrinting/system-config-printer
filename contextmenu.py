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

import jobviewer
from debug import *

class PrinterContextMenu:
    def __init__ (self, parent):
        self.parent = parent
        self.xml = parent.xml
        for name in ["printer_context_menu",
                     "printer_context_edit",
                     "printer_context_rename",
                     "printer_context_disable",
                     "printer_context_enable",
                     "printer_context_copy",
                     "printer_context_delete",
                     "printer_context_set_as_default",
                     "printer_context_view_print_queue"]:
            widget = self.xml.get_widget (name)
            setattr (self, name, widget)
        self.xml.signal_autoconnect (self)
        self.jobviewers = []

    def cleanup (self):
        while len (self.jobviewers) > 0:
            self.jobviewers[0].cleanup () # this will call on_jobviewer_exit

    def popup (self, event, iconview, paths):
        self.iconview = iconview
        self.paths = paths

        n = len (paths)

        model = self.iconview.get_model ()
        if n == 1:
            iter = model.get_iter (paths[0])
            name = model.get_value (iter, 2)
            is_default = name == self.parent.default_printer
        else:
            is_default = False

        any_disabled = False
        any_enabled = False
        any_discovered = False
        for i in range (n):
            iter = model.get_iter (paths[i])
            object = model.get_value (iter, 0)
            if object.discovered:
                any_discovered = True
            if object.enabled:
                any_enabled = True
            else:
                any_disabled = True

            if any_discovered and any_enabled and any_disabled:
                break

        def show_widget (widget, condition):
            if condition:
                widget.show ()
            else:
                widget.hide ()

        # Actions that require a single destination
        show_widget (self.printer_context_edit, n == 1)
        show_widget (self.printer_context_copy, n == 1)
        show_widget (self.printer_context_rename, n == 1 and not any_discovered)
        show_widget (self.printer_context_set_as_default,
                     n == 1 and not is_default)

        # Actions that require at least one destination
        show_widget (self.printer_context_disable,
                     n > 0 and any_enabled and not any_discovered)
        show_widget (self.printer_context_enable,
                     n > 0 and any_disabled and not any_discovered)
        show_widget (self.printer_context_delete, n > 0 and not any_discovered)

        self.printer_context_menu.popup (None, None, None,
                                         event.button,
                                         event.get_time (), None)

    ### Edit
    def on_printer_context_edit_activate (self, menuitem):
        self.parent.dests_iconview_item_activated (self.iconview, self.paths[0])

    ### Rename
    def on_printer_context_rename_activate (self, menuitem):
        tuple = self.parent.dests_iconview.get_cursor ()
        if tuple == None:
            return

        (path, cell) = tuple
        cell.set_property ('editable', True)
        self.parent.dests_iconview.set_cursor (path, cell, start_editing=True)
        ids = []
        ids.append (cell.connect ('edited', self.printer_name_edited))
        ids.append (cell.connect ('editing-canceled',
                                 self.printer_name_edit_cancel))
        self.rename_sigids = ids

    def printer_name_edited (self, cell, path, newname):
        model = self.parent.dests_iconview.get_model ()
        iter = model.get_iter (path)
        name = model.get_value (iter, 2)
        debugprint ("edited: %s -> %s" % (name, newname))
        try:
            self.parent.rename_printer (name, newname)
        finally:
            cell.stop_editing (canceled=False)
            cell.set_property ('editable', False)
            for id in self.rename_sigids:
                cell.disconnect (id)

    def printer_name_edit_cancel (self, cell):
        debugprint ("editing-canceled")
        cell.stop_editing (canceled=True)
        cell.set_property ('editable', False)
        for id in self.rename_sigids:
            cell.disconnect (id)

    ### Enable
    def on_printer_context_enable_activate (self, menuitem, enable=True):
        model = self.iconview.get_model ()
        for i in range (len (self.paths)):
            iter = model.get_iter (self.paths[i])
            printer = model.get_value (iter, 0)
            printer.setEnabled (enable)
        self.parent.populateList ()

    ### Disable
    def on_printer_context_disable_activate (self, menuitem):
        self.on_printer_context_enable_activate (menuitem, enable=False)

    ### Copy
    def on_printer_context_copy_activate (self, menuitem):
        self.parent.on_copy_activate (menuitem)

    ### Delete
    def on_printer_context_delete_activate (self, menuitem):
        self.parent.on_delete_activate (menuitem)

    ### Set as default
    def on_printer_context_set_as_default_activate (self, menuitem):
        model = self.iconview.get_model ()
        iter = model.get_iter (self.paths[0])
        printer = model.get_value (iter, 0)
        printer.setAsDefault ()
        self.parent.populateList ()

    ### View print queue
    def on_printer_context_view_print_queue_activate (self, menuitem):
        if len (self.paths):
            specific_dests = []
            model = self.iconview.get_model ()
            for path in self.paths:
                iter = model.get_iter (path)
                name = model.get_value (iter, 2)
                specific_dests.append (name)
            viewer = jobviewer.JobViewer (None, None, my_jobs=False,
                                          specific_dests=specific_dests,
                                          exit_handler=self.on_jobviewer_exit,
                                          parent=self.parent.MainWindow)
        else:
            viewer = jobviewer.JobViewer (None, None, my_jobs=False,
                                          exit_handler=self.on_jobviewer_exit,
                                          parent=self.parent.MainWindow)

        self.jobviewers.append (viewer)

    def on_jobviewer_exit (self, viewer):
        i = self.jobviewers.index (viewer)
        del self.jobviewers[i]

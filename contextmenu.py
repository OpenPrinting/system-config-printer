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

import gtk.gdk

import cups
import errordialogs
import jobviewer
from debug import *
import userdefault

_ = lambda x: x
def set_gettext_function (x):
    global _
    _ = x

class PrinterContextMenu:
    def __init__ (self, parent):
        self.parent = parent
        self.xml = parent.xml
        for name in ["printer_context_menu",
                     "printer_context_edit",
                     "printer_context_rename",
                     "printer_context_enabled",
                     "printer_context_shared",
                     "printer_context_copy",
                     "printer_context_delete",
                     "printer_context_set_as_default",
                     "printer_context_create_class",
                     "printer_context_view_print_queue"]:
            widget = self.xml.get_widget (name)
            setattr (self, name, widget)
        self.xml.signal_autoconnect (self)
        self.jobviewers = []
        self.updating_widgets = False

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

        any_disabled = False
        any_enabled = False
        any_discovered = False
        any_shared = False
        any_unshared = False
        for i in range (n):
            iter = model.get_iter (paths[i])
            object = model.get_value (iter, 0)
            if object.discovered:
                any_discovered = True
            if object.enabled:
                any_enabled = True
            else:
                any_disabled = True
            if object.is_shared:
                any_shared = True
            else:
                any_unshared = True

            if (any_discovered and any_enabled and any_disabled and
                any_shared and any_unshared):
                break

        def show_widget (widget, condition):
            if condition:
                widget.show ()
            else:
                widget.hide ()

        self.updating_widgets = True

        # Actions that require a single destination
        show_widget (self.printer_context_edit, n == 1)
        show_widget (self.printer_context_copy, n == 1)
        show_widget (self.printer_context_rename, n == 1 and not any_discovered)
        userdef = userdefault.UserDefaultPrinter ().get ()
        if (n != 1 or
            (userdef == None and self.parent.default_printer == name)):
            self.printer_context_set_as_default.hide ()
        else:
            self.printer_context_set_as_default.show ()

        # Actions that require at least one destination
        show_widget (self.printer_context_delete, n > 0 and not any_discovered)
        show_widget (self.printer_context_enabled, n > 0 and not any_discovered)
        self.printer_context_enabled.set_active (any_discovered or
                                                 not any_disabled)
        self.printer_context_enabled.set_inconsistent (n > 1 and
                                                       any_enabled and
                                                       any_disabled)
        show_widget (self.printer_context_shared, n > 0 and not any_discovered)
        self.printer_context_shared.set_active (any_discovered or
                                                not any_unshared)
        self.printer_context_shared.set_inconsistent (n > 1 and
                                                      any_shared and
                                                      any_unshared)

        # Actions that require more than one destination
        show_widget (self.printer_context_create_class, n > 1)

        if event == None:
            event_button = 0
            event_time = gtk.gdk.Event (gtk.gdk.NOTHING).get_time ()
        else:
            event_button = event.button
            event_time = event.get_time ()

        self.updating_widgets = False
        self.printer_context_menu.popup (None, None, None, event_button,
                                         event_time, None)

    ### Edit
    def on_printer_context_edit_activate (self, menuitem):
        self.parent.dests_iconview_item_activated (self.iconview, self.paths[0])

    ### Rename
    def on_printer_context_rename_activate (self, menuitem):
        self.parent.on_rename_activate (menuitem)

    ### Enabled
    def on_printer_context_enabled_activate (self, menuitem):
        if self.updating_widgets:
            return
        enable = menuitem.get_active ()
        model = self.iconview.get_model ()
        for i in range (len (self.paths)):
            iter = model.get_iter (self.paths[i])
            printer = model.get_value (iter, 0)
            try:
                printer.setEnabled (enable)
            except cups.IPPError, (e, m):
                errordialogs.show_IPP_Error (e, m, self.parent.MainWindow)
                # Give up on this operation.
                break
        self.parent.populateList ()

    ### Shared
    def on_printer_context_shared_activate (self, menuitem):
        if self.updating_widgets:
            return
        share = menuitem.get_active ()
        model = self.iconview.get_model ()
        for i in range (len (self.paths)):
            iter = model.get_iter (self.paths[i])
            printer = model.get_value (iter, 0)
            try:
                printer.setShared (share)
            except cups.IPPError, (e, m):
                errordialogs.show_IPP_Error (e, m, self.parent.MainWindow)
                # Give up on this operation.
                break
        if share:
            self.parent.advise_publish ()
        self.parent.populateList ()

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
        name = model.get_value (iter, 2)
        self.parent.set_system_or_user_default_printer (name)

    ### Create Class
    def on_printer_context_create_class_activate (self, menuitem):
        class_members = []
        model = self.iconview.get_model ()
        for path in self.paths:
            iter = model.get_iter (path)
            name = model.get_value (iter, 2)
            class_members.append (name)
        self.parent.newPrinterGUI.init ("class")
        out_model = self.parent.newPrinterGUI.tvNCNotMembers.get_model ()
        in_model = self.parent.newPrinterGUI.tvNCMembers.get_model ()
        iter = out_model.get_iter_first ()
        while iter != None:
            next = out_model.iter_next (iter)
            data = out_model.get (iter, 0)
            if data[0] in class_members:
                in_model.append (data)
                out_model.remove (iter)
            iter = next

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

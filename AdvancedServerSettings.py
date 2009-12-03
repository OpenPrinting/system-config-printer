#!/usr/bin/env python

## system-config-printer

## Copyright (C) 2008, 2009 Red Hat, Inc.
## Copyright (C) 2008, 2009 Tim Waugh <twaugh@redhat.com>

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

from gettext import gettext as _
import gobject
import gtk
import os
import socket
import tempfile
import time

from errordialogs import *

class AdvancedServerSettingsDialog:
    RESOURCE="/admin/conf/cupsd.conf"

    def __init__ (self, cupsconn, parent=None, on_apply=None):
        self.cupsconn = cupsconn
        self.on_apply = on_apply

        # Signal handler IDs.
        self.handler_ids = {}

        dialog = gtk.Dialog (_("Advanced Server Settings"),
                             parent,
                             gtk.DIALOG_MODAL |
                             gtk.DIALOG_DESTROY_WITH_PARENT,
                             (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                              gtk.STOCK_OK, gtk.RESPONSE_OK))
        dialog.set_default_response (gtk.RESPONSE_OK)
        dialog.set_border_width (6)
        dialog.set_resizable (False)
        dialog.set_has_separator (False)
        self.connect (dialog, 'response', self.on_response)
        self.dialog = dialog

        frames_vbox = gtk.VBox (False, 6)
        dialog.vbox.pack_start (frames_vbox, False, False, 0)

        history_frame = gtk.Frame ()
        label = gtk.Label ('<b>' + _("Job History") + '</b>')
        label.set_use_markup (True)
        history_frame.set_label_widget (label)
        history_frame.set_shadow_type (gtk.SHADOW_NONE)
        frames_vbox.pack_start (history_frame, False, False, 0)

        align = gtk.Alignment (0.5, 0.5, 1.0, 1.0)
        align.set_padding (0, 0, 12, 0)
        history_frame.add (align)
        vbox = gtk.VBox (False, 0)
        align.add (vbox)
        rb1 = gtk.RadioButton (None, _("Do not preserve job history"), False)
        self.rbPreserveJobNone = rb1
        rb2 = gtk.RadioButton (rb1, _("Preserve job history but not files"),
                               False)
        self.rbPreserveJobHistory = rb2
        rb3 = gtk.RadioButton (rb1, _("Preserve job files (allow reprinting)"),
                               False)
        self.rbPreserveJobFiles = rb3
        vbox.pack_start (rb1, False, False, 0)
        vbox.pack_start (rb2, False, False, 0)
        vbox.pack_start (rb3, False, False, 0)

        browse_frame = gtk.Frame ()
        label = gtk.Label ('<b>' + _("Browse Servers") + '</b>')
        label.set_use_markup (True)
        browse_frame.set_label_widget (label)
        browse_frame.set_shadow_type (gtk.SHADOW_NONE)
        frames_vbox.pack_start (browse_frame, False, False, 0)

        align = gtk.Alignment (0.5, 0.5, 1.0, 1.0)
        align.set_padding (0, 0, 12, 0)
        browse_frame.add (align)
        vbox = gtk.VBox (False, 6)
        align.add (vbox)
        label = gtk.Label (_("Usually print servers broadcast their "
                             "queues.  Specify print servers below "
                             "to periodically ask for queues instead."))
        label.set_line_wrap (True)
        vbox.pack_start (label, False, False, 0)
        hbox = gtk.HBox (False, 6)
        vbox.pack_start (hbox, False, False, 0)

        scrollwin = gtk.ScrolledWindow ()
        scrollwin.set_shadow_type (gtk.SHADOW_IN)
        scrollwin.set_policy (gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        hbox.pack_start (scrollwin, True, True, 0)
        treeview = gtk.TreeView ()
        treeview.set_headers_visible (False)
        scrollwin.add (treeview)
        selection = treeview.get_selection ()
        selection.set_mode (gtk.SELECTION_MULTIPLE)
        self.connect (selection, 'changed', self.on_treeview_selection_changed)
        col = gtk.TreeViewColumn ('', gtk.CellRendererText (), text=0)
        treeview.append_column (col)
        self.browse_treeview = treeview

        bb = gtk.VButtonBox ()
        bb.set_layout (gtk.BUTTONBOX_START)
        hbox.pack_start (bb, False, False, 0)

        add = gtk.Button (stock=gtk.STOCK_ADD)
        bb.add (add)
        self.connect (add, 'clicked', self.on_add_clicked)
        self.add = add
        remove = gtk.Button (stock=gtk.STOCK_REMOVE)
        remove.set_sensitive (False)
        bb.add (remove)
        self.connect (remove, 'clicked', self.on_remove_clicked)
        self.remove = remove

        # Fetch cupsd.conf
        f = tempfile.TemporaryFile ()
        try:
            cupsconn.getFile (self.RESOURCE, file=f)
        except cups.HTTPError, s:
            show_HTTP_Error (s, dialog)
            raise

        def parse_yesno (line):
            arg1 = line.split (' ')[1].strip ()
            if arg1 in ['true', 'on', 'enabled', 'yes']:
                return True
            if arg1 in ['false', 'off', 'disabled', 'no', '0']:
                return False
            try:
                if int (arg1) != 0:
                    return True
            except:
                pass
            raise RuntimeError

        preserve_job_history = True
        preserve_job_files = False
        browsing = True
        self.browse_poll = []
        f.seek (0)
        for line in f.readlines ():
            l = line.lower ().strip ()
            if l.startswith ("preservejobhistory "):
                try:
                    preserve_job_history = parse_yesno (l)
                except:
                    pass
            elif l.startswith ("preservejobfiles "):
                try:
                    preserve_job_files = parse_yesno (l)
                except:
                    pass
            elif l.startswith ("browsing "):
                try:
                    browsing = parse_yesno (l)
                except:
                    pass
            elif l.startswith ("browsepoll "):
                self.browse_poll.append (line[len ("browsepoll "):].strip ())

        if not browsing:
            browse_frame.set_sensitive (False)
            
        if preserve_job_files:
            self.rbPreserveJobFiles.set_active (True)
        elif preserve_job_history:
            self.rbPreserveJobHistory.set_active (True)
        else:
            self.rbPreserveJobNone.set_active (True)

        self.preserve_job_history = preserve_job_history
        self.preserve_job_files = preserve_job_files

        model = gtk.ListStore (gobject.TYPE_STRING)
        treeview.set_model (model)
        for server in self.browse_poll:
            model.append (row=[server])

        dialog.show_all ()

    def connect (self, widget, signal, handler, reason=None):
        id = widget.connect (signal, handler)
        if not self.handler_ids.has_key (reason):
            self.handler_ids[reason] = []
        self.handler_ids[reason].append ((widget, id))

    def disconnect (self, reason=None):
        for (widget, id) in self.handler_ids[reason]:
            widget.disconnect (id)
        del self.handler_ids[reason]

    def __del__ (self):
        self.dialog.destroy ()

    def on_treeview_selection_changed (self, selection):
        self.remove.set_sensitive (selection.count_selected_rows () != 0)

    def on_add_clicked (self, button):
        model = self.browse_treeview.get_model ()
        iter = model.insert (0, row=[_("Enter IP address")])
        button.set_sensitive (False)
        col = self.browse_treeview.get_columns ()[0]
        cell = col.get_cell_renderers ()[0]
        cell.set_property ('editable', True)
        self.browse_treeview.set_cursor ((0,), col, start_editing=True)
        self.connect (cell, 'edited', self.on_browse_poll_edited,
                      'edit')
        self.connect (cell, 'editing-canceled', self.on_browse_poll_edit_cancel,
                      'edit')

    def on_browse_poll_edited (self, cell, path, newvalue):
        model = self.browse_treeview.get_model ()
        iter = model.get_iter (path)
        model.set_value (iter, 0, newvalue)
        cell.stop_editing (canceled=False)
        cell.set_property ('editable', False)
        self.add.set_sensitive (True)
        self.disconnect ('edit')

        valid = True
        # Check that it's a valid IP address or hostname.
        # First, is it an IP address?
        try:
            socket.getaddrinfo (newvalue, '0', socket.AF_UNSPEC, 0, 0,
                                socket.AI_NUMERICHOST)
        except socket.gaierror:
            # No.  Perhaps it's a hostname.
            labels = newvalue.split (".")
            seen_alpha = False
            for label in labels:
                if (label[0] == '-' or
                    label.endswith ('-')):
                    valid = False
                    break
                for char in label:
                    if not seen_alpha:
                        if char.isalpha ():
                            seen_alpha = True

                    if not (char.isalpha () or
                            char.isdigit () or
                            char == '-'):
                        valid = False
                        break

                if not valid:
                    break

            if valid and not seen_alpha:
                valid = False

        if valid:
            count = 0
            i = model.get_iter_first ()
            while i:
                if model.get_value (i, 0) == newvalue:
                    count += 1
                    if count == 2:
                        valid = False
                        selection = self.browse_treeview.get_selection ()
                        selection.select_iter (i)
                        break
                i = model.iter_next (i)
        else:
            model.remove (iter)

    def on_browse_poll_edit_cancel (self, cell):
        cell.stop_editing (canceled=True)
        cell.set_property ('editable', False)
        model = self.browse_treeview.get_model ()
        iter = model.get_iter ((0,))
        model.remove (iter)
        self.add.set_sensitive (True)
        self.remove.set_sensitive (False)
        self.disconnect ('edit')

    def on_remove_clicked (self, button):
        model = self.browse_treeview.get_model ()
        selection = self.browse_treeview.get_selection ()
        rows = selection.get_selected_rows ()
        refs = map (lambda path: gtk.TreeRowReference (model, path),
                    rows[1])
        for ref in refs:
            path = ref.get_path ()
            iter = model.get_iter (path)
            model.remove (iter)

    def on_response (self, dialog, response):
        if (response == gtk.RESPONSE_CANCEL or
            response != gtk.RESPONSE_OK):
            self.disconnect ()
            del self
            return

        # See if there are changes.
        preserve_job_files = self.rbPreserveJobFiles.get_active ()
        preserve_job_history = (preserve_job_files or
                                self.rbPreserveJobHistory.get_active ())
        model = self.browse_treeview.get_model ()
        browse_poll = []
        iter = model.get_iter_first ()
        while iter:
            browse_poll.append (model.get_value (iter, 0))
            iter = model.iter_next (iter)

        if (set (browse_poll) == set (self.browse_poll) and
            preserve_job_files == self.preserve_job_files and
            preserve_job_history == self.preserve_job_history):
            self.disconnect ()
            del self
            return

        # Fetch cupsd.conf afresh
        f = tempfile.TemporaryFile ()
        try:
            self.cupsconn.getFile (self.RESOURCE, file=f)
        except cups.HTTPError, s:
            show_HTTP_Error (s, dialog)
            return

        job_history_line = job_files_line = browsepoll_lines = ""

        # Default is to preserve job history
        if not preserve_job_history:
            job_history_line = "PreserveJobHistory No\n"

        # Default is not to preserve job files.
        if preserve_job_files:
            job_files_line = "PreserveJobFiles Yes\n"

        for server in browse_poll:
            browsepoll_lines += "BrowsePoll %s\n" % server

        f.seek (0)
        conf = tempfile.TemporaryFile ()
        wrote_preserve_history = wrote_preserve_files = False
        wrote_browsepoll = False
        has_browsepoll = False
        lines = f.readlines ()
        for line in lines:
            l = line.lower ().strip ()
            if l.startswith ("browsepoll "):
                has_browsepoll = True
                break

        for line in lines:
            l = line.lower ().strip ()
            if l.startswith ("preservejobhistory "):
                if wrote_preserve_history:
                    # Don't write out another line with this keyword.
                    continue
                # Alter this line before writing it out.
                line = job_history_line
                wrote_preserve_history = True
            elif l.startswith ("preservejobfiles "):
                if wrote_preserve_files:
                    # Don't write out another line with this keyword.
                    continue
                # Alter this line before writing it out.
                line = job_files_line
                wrote_preserve_files = True
            elif (has_browsepoll and
                  l.startswith ("browsepoll ")):
                if wrote_browsepoll:
                    # Ignore extra BrowsePoll lines.
                    continue
                # Write new BrowsePoll section.
                conf.write (browsepoll_lines)
                wrote_browsepoll = True
                # Don't write out the original BrowsePoll line.
                continue
            elif (not has_browsepoll and
                  l.startswith ("browsing ")):
                if not wrote_browsepoll:
                    # Write original Browsing line.
                    conf.write (line)
                    # Write new BrowsePoll section.
                    conf.write (browsepoll_lines)
                    wrote_browsepoll = True
                    continue

            conf.write (line)

        if not wrote_preserve_history:
            conf.write (job_history_line)
        if not wrote_preserve_files:
            conf.write (job_files_line)
        if not wrote_browsepoll:
            conf.write (browsepoll_lines)

        conf.flush ()
        fd = conf.fileno ()
        os.lseek (fd, 0, os.SEEK_SET)
        try:
            self.cupsconn.putFile ("/admin/conf/cupsd.conf", fd=fd)
        except cups.HTTPError, s:
            show_HTTP_Error (s, dialog)
            return

        # Give the server a chance to process our request.
        time.sleep (1)

        # Now reconnect, in case the server needed to reload.
        try:
            attempt = 1
            while attempt <= 5:
                try:
                    self.cupsconn._connect ()
                    break
                except RuntimeError:
                    # Connection failed.
                    time.sleep (1)
                    attempt += 1
        except AttributeError:
            # _connect method is part of the authconn.Connection
            # interface, so don't fail if that method doesn't exist.
            pass

        self.disconnect ()
        self.on_apply ()
        del self

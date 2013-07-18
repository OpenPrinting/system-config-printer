#!/usr/bin/python

## Printing troubleshooter

## Copyright (C) 2008, 2009, 2010, 2011, 2012 Red Hat, Inc.
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

from base import *
class Shrug(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Shrug")
        page = self.initial_vbox (_("Sorry!"),
                                  _("There is no obvious solution to this "
                                    "problem.  Your answers have been "
                                    "collected together with "
                                    "other useful information.  If you "
                                    "would like to report a bug, please "
                                    "include this information."))

        expander = Gtk.Expander.new(_("Diagnostic Output (Advanced)"))
        expander.set_expanded (False)
        sw = Gtk.ScrolledWindow ()
        expander.add (sw)
        textview = Gtk.TextView ()
        textview.set_editable (False)
        sw.add (textview)
        page.pack_start (expander, True, True, 0)
        self.buffer = textview.get_buffer ()

        box = Gtk.HButtonBox ()
        box.set_border_width (0)
        box.set_spacing (3)
        box.set_layout (Gtk.ButtonBoxStyle.END)
        page.pack_start (box, False, False, 0)

        self.save = Gtk.Button (stock=Gtk.STOCK_SAVE)
        box.pack_start (self.save, False, False, 0)

        troubleshooter.new_page (page, self)

    def display (self):
        self.buffer.set_text (self.troubleshooter.answers_as_text ())
        return True

    def connect_signals (self, handler):
        self.save_sigid = self.save.connect ('clicked', self.on_save_clicked)

    def disconnect_signals (self):
        self.save.disconnect (self.save_sigid)

    def on_save_clicked (self, button):
        while True:
            parent = self.troubleshooter.get_window()
            dialog = Gtk.FileChooserDialog (parent=parent,
                                            action=Gtk.FileChooserAction.SAVE,
                                            buttons=(Gtk.STOCK_CANCEL,
                                                     Gtk.ResponseType.CANCEL,
                                                     Gtk.STOCK_SAVE,
                                                     Gtk.ResponseType.OK))
            dialog.set_do_overwrite_confirmation (True)
            dialog.set_current_name ("troubleshoot.txt")
            dialog.set_default_response (Gtk.ResponseType.OK)
            dialog.set_local_only (True)
            response = dialog.run ()
            dialog.hide ()
            if response != Gtk.ResponseType.OK:
                return

            try:
                f = file (dialog.get_filename (), "w")
                f.write (self.buffer.get_text (start=self.buffer.get_start_iter (),
                                               end=self.buffer.get_end_iter (),
                                               include_hidden_chars=False))
            except IOError as e:
                err = Gtk.MessageDialog (parent,
                                         Gtk.DialogFlags.MODAL |
                                         Gtk.DialogFlags.DESTROY_WITH_PARENT,
                                         Gtk.MessageType.ERROR,
                                         Gtk.ButtonsType.CLOSE,
                                         _("Error saving file"))
                err.format_secondary_text (_("There was an error saving "
                                             "the file:") + "\n" +
                                           e.strerror)
                err.run ()
                err.destroy ()
                continue

            del f
            break

#!/usr/bin/python

## Printing troubleshooter

## Copyright (C) 2008, 2009, 2010, 2011 Red Hat, Inc.
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
## Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.

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

        expander = gtk.Expander (_("Diagnostic Output (Advanced)"))
        expander.set_expanded (False)
        sw = gtk.ScrolledWindow ()
        expander.add (sw)
        textview = gtk.TextView ()
        textview.set_editable (False)
        sw.add (textview)
        page.pack_start (expander)
        self.buffer = textview.get_buffer ()

        box = gtk.HButtonBox ()
        box.set_border_width (0)
        box.set_spacing (3)
        box.set_layout (gtk.BUTTONBOX_END)
        page.pack_start (box, False, False, 0)

        self.save = gtk.Button (stock=gtk.STOCK_SAVE)
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
            dialog = gtk.FileChooserDialog (parent=parent,
                                            action=gtk.FILE_CHOOSER_ACTION_SAVE,
                                            buttons=(gtk.STOCK_CANCEL,
                                                     gtk.RESPONSE_CANCEL,
                                                     gtk.STOCK_SAVE,
                                                     gtk.RESPONSE_OK))
            dialog.set_do_overwrite_confirmation (True)
            dialog.set_current_name ("troubleshoot.txt")
            dialog.set_default_response (gtk.RESPONSE_OK)
            dialog.set_local_only (True)
            response = dialog.run ()
            dialog.hide ()
            if response != gtk.RESPONSE_OK:
                return

            try:
                f = file (dialog.get_filename (), "w")
                f.write (self.buffer.get_text (self.buffer.get_start_iter (),
                                               self.buffer.get_end_iter ()))
            except IOError, e:
                err = gtk.MessageDialog (parent,
                                         gtk.DIALOG_MODAL |
                                         gtk.DIALOG_DESTROY_WITH_PARENT,
                                         gtk.MESSAGE_ERROR,
                                         gtk.BUTTONS_CLOSE,
                                         _("Error saving file"))
                err.format_secondary_text (_("There was an error saving "
                                             "the file:") + "\n" +
                                           e.strerror)
                err.run ()
                err.destroy ()
                continue

            del f
            break

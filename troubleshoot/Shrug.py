#!/usr/bin/env python

## Printing troubleshooter

## Copyright (C) 2008 Red Hat, Inc.
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
## Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.

from base import *
class Shrug(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Shrug")
        page = self.initial_vbox (_("Sorry!"),
                                  _("I have not been able to work out what "
                                    "the problem is, but I have collected "
                                    "some useful information to put in a "
                                    "bug report."))

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

        self.save = gtk.Button (stock='gtk-save')
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
        dialog = gtk.FileChooserDialog (parent=self.troubleshooter.get_window(),
                                        action=gtk.FILE_CHOOSER_ACTION_SAVE,
                                        buttons=('gtk-cancel',
                                                 gtk.RESPONSE_CANCEL,
                                                 'gtk-save',
                                                 gtk.RESPONSE_OK))
        dialog.set_do_overwrite_confirmation (True)
        dialog.set_current_name ("troubleshoot.txt")
        dialog.set_default_response (gtk.RESPONSE_OK)
        response = dialog.run ()
        dialog.hide ()
        if response != gtk.RESPONSE_OK:
            return

        f = file (dialog.get_filename (), "w")
        f.write (self.buffer.get_text (self.buffer.get_start_iter (),
                                       self.buffer.get_end_iter ()))
        del f

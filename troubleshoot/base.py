#!/usr/bin/python

## Printing troubleshooter

## Copyright (C) 2008, 2010, 2012 Red Hat, Inc.
## Authors:
##  Tim Waugh <twaugh@redhat.com>

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
from gettext import gettext as _
N_ = lambda x: x
from debug import *

__all__ = [ '_',
            'debugprint', 'get_debugging', 'set_debugging',
            'Question',
            'Multichoice',
            'TEXT_start_print_admin_tool' ]

TEXT_start_print_admin_tool = N_("To start this tool, select "
                                 "System->Administration->Print Settings "
                                 "from the main menu.")

class Question:
    def __init__ (self, troubleshooter, name=None):
        self.troubleshooter = troubleshooter
        if name:
            self.__str__ = lambda: name

    def display (self):
        """Returns True if this page should be displayed, or False
        if it should be skipped."""
        return True

    def connect_signals (self, handler):
        pass

    def disconnect_signals (self):
        pass

    def can_click_forward (self):
        return True

    def collect_answer (self):
        return {}

    def cancel_operation (self):
        pass

    ## Helper functions
    def initial_vbox (self, title='', text=''):
        vbox = Gtk.VBox ()
        vbox.set_border_width (12)
        vbox.set_spacing (12)
        if title:
            s = '<span weight="bold" size="larger">' + title + '</span>\n\n'
        else:
            s = ''
        s += text
        label = Gtk.Label(label=s)
        label.set_alignment (0, 0)
        label.set_line_wrap (True)
        label.set_use_markup (True)
        vbox.pack_start (label, False, False, 0)
        return vbox

class Multichoice(Question):
    def __init__ (self, troubleshooter, question_tag, question_title,
                  question_text, choices, name=None):
        Question.__init__ (self, troubleshooter, name)
        page = self.initial_vbox (question_title, question_text)
        choice_vbox = Gtk.VBox ()
        choice_vbox.set_spacing (6)
        page.pack_start (choice_vbox, False, False, 0)
        self.question_tag = question_tag
        self.widgets = []
        button = None
        for choice, tag in choices:
            if button:
                button = Gtk.RadioButton.new_with_label_from_widget(button, choice)
            else:
                # special case to work around GNOME#635253
                button = Gtk.RadioButton.new_with_label([], choice)
            choice_vbox.pack_start (button, False, False, 0)
            self.widgets.append ((button, tag))

        troubleshooter.new_page (page, self)

    def collect_answer (self):
        for button, answer_tag in self.widgets:
            if button.get_active ():
                return { self.question_tag: answer_tag }

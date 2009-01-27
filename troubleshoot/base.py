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

import gtk
from gettext import gettext as _
from debug import *

__all__ = [ 'gtk',
            '_',
            'debugprint', 'get_debugging', 'set_debugging',
            'Question',
            'Multichoice',
            'TEXT_start_print_admin_tool' ]

TEXT_start_print_admin_tool = _("To start this tool, select "
                                "System->Administration->Printing "
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
        vbox = gtk.VBox ()
        vbox.set_border_width (12)
        vbox.set_spacing (12)
        if title:
            s = '<span weight="bold" size="larger">' + title + '</span>\n\n'
        else:
            s = ''
        s += text
        label = gtk.Label (s)
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
        choice_vbox = gtk.VBox ()
        choice_vbox.set_spacing (6)
        page.pack_start (choice_vbox, False, False, 0)
        self.question_tag = question_tag
        self.widgets = []
        for choice, tag in choices:
            button = gtk.RadioButton (label=choice)
            if len (self.widgets) > 0:
                button.set_group (self.widgets[0][0])
            choice_vbox.pack_start (button, False, False, 0)
            self.widgets.append ((button, tag))

        troubleshooter.new_page (page, self)

    def collect_answer (self):
        for button, answer_tag in self.widgets:
            if button.get_active ():
                return { self.question_tag: answer_tag }

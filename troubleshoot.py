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
import gobject
import cups
from gettext import gettext as _

class Troubleshooter:
    def __init__ (self):
        main = gtk.Window ()
        main.set_title (_("Printing troubleshooter"))
        main.set_property ("default-width", 400)
        main.set_property ("default-height", 300)
        main.connect ("delete_event", gtk.main_quit)
        self.main = main

        vbox = gtk.VBox ()
        main.add (vbox)
        ntbk = gtk.Notebook ()
        ntbk.set_border_width (6)
        vbox.pack_start (ntbk, True, True, 0)
        vbox.pack_start (gtk.HSeparator (), False, False, 0)
        box = gtk.HButtonBox ()
        box.set_border_width (6)
        box.set_spacing (3)
        box.set_layout (gtk.BUTTONBOX_END)

        back = gtk.Button (stock='gtk-go-back')
        back.connect ('clicked', self.on_back_clicked)
        back.set_sensitive (False)
        self.back = back

        close = gtk.Button (stock='gtk-close')
        close.connect ('clicked', gtk.main_quit)
        self.close = close

        cancel = gtk.Button (stock='gtk-cancel')
        cancel.connect ('clicked', gtk.main_quit)
        self.cancel = cancel

        forward = gtk.Button (stock='gtk-go-forward')
        forward.connect ('clicked', self.on_forward_clicked)
        self.forward = forward

        box.pack_start (back, False, False, 0)
        box.pack_start (cancel, False, False, 0)
        box.pack_start (close, False, False, 0)
        box.pack_start (forward, False, False, 0)
        vbox.pack_start (box, False, False, 0)

        ntbk.set_current_page (0)
        ntbk.set_show_tabs (False)
        self.ntbk = ntbk

        self.questions = []
        self.question_answers = []
        self.answers = {}

        main.show_all ()

    def no_more_questions (self, question):
        page = self.questions.index (question)
        print "Page %d: No more questions." % page
        self.questions = self.questions[:page + 1]
        self.question_answers = self.question_answers[:page + 1]
        for p in range (self.ntbk.get_n_pages () - 1, page, -1):
            self.ntbk.remove_page (p)
        self.set_back_forward_buttons ()

    def new_page (self, widget, question):
        page = len (self.questions)
        print "Page %d: new: %s" % (page, str (question))
        self.questions.append (question)
        self.question_answers.append ([])
        self.ntbk.insert_page (widget, position=page)
        widget.show_all ()
        if page == 0:
            question.connect_signals (self.set_back_forward_buttons)
            self.ntbk.set_current_page (page)
        self.set_back_forward_buttons ()
        return page

    def set_back_forward_buttons (self, *args):
        page = self.ntbk.get_current_page ()
        self.back.set_sensitive (page != 0)
        if len (self.questions) == page + 1:
            # Out of questions.
            print "Out of questions"
            self.forward.set_sensitive (False)
            self.close.show ()
            self.cancel.hide ()
        else:
            can = self.questions[page].can_click_forward ()
            print "Page %d: can click forward? %s" % (page, can)
            self.forward.set_sensitive (can)
            self.close.hide ()
            self.cancel.show ()

    def on_back_clicked (self, widget):
        page = self.ntbk.get_current_page ()
        self.questions[page].disconnect_signals ()

        step = 1
        question = self.questions[page - step]
        while not question.display ():
            # Skip this one.
            print "Page %d: skip" % (page - step)
            step += 1
            question = self.questions[page - step]

        self.ntbk.set_current_page (page - step)
        page -= step

        answers = {}
        for i in range (page):
            print i, self.question_answers[i]
            answers.update (self.question_answers[i])
        self.answers = answers

        self.questions[page].connect_signals (self.set_back_forward_buttons)
        self.set_back_forward_buttons ()

    def on_forward_clicked (self, widget):
        page = self.ntbk.get_current_page ()
        answer_dict = self.questions[page].collect_answer ()
        print answer_dict
        self.questions[page].disconnect_signals ()
        self.question_answers[page] = answer_dict
        self.answers.update (answer_dict)

        step = 1
        question = self.questions[page + step]
        while not question.display ():
            # Skip this one.
            print "Page %d: skip" % (page + step)
            step += 1
            question = self.questions[page + step]

        self.ntbk.set_current_page (page + step)
        page += step
        question.connect_signals (self.set_back_forward_buttons)
        self.set_back_forward_buttons ()

#############

class Question:
    def __init__ (self, troubleshooter):
        self.troubleshooter = troubleshooter

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

class Multichoice(Question):
    def __init__ (self, troubleshooter, question_tag, question_text, choices):
        Question.__init__ (self, troubleshooter)
        page = gtk.VBox ()
        page.set_spacing (12)
        page.set_border_width (12)
        question = gtk.Label (question_text)
        question.set_line_wrap (True)
        question.set_alignment (0, 0)
        page.pack_start (question, False, False, 0)
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

#############

class Welcome(Question):
    def __init__ (self, troubleshooter):
        # Welcome page (page 0)
        Question.__init__ (self, troubleshooter)
        welcome = gtk.HBox ()
        welcome.set_spacing (12)
        welcome.set_border_width (12)
        image = gtk.Image ()
        image.set_alignment (0, 0)
        image.set_from_stock (gtk.STOCK_PRINT, gtk.ICON_SIZE_DIALOG)
        intro = gtk.Label ('<span weight="bold" size="larger">' +
                           _("Trouble-shooting Printing") +
                           '</span>\n\n' +
                           _("In the next few screens I will ask you some "
                             "questions about your problem with printing. "
                             "Based on your answers I will try to suggest "
                             "a solution.") + '\n\n' +
                           _("Click 'Forward' to begin."))
        intro.set_alignment (0, 0)
        intro.set_use_markup (True)
        intro.set_line_wrap (True)
        welcome.pack_start (image, False, False, 0)
        welcome.pack_start (intro, True, True, 0)
        page = troubleshooter.new_page (welcome, self)

class CheckCUPS(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter)
        troubleshooter.new_page (gtk.Label ("CUPS not running?"), self)
        troubleshooter.no_more_questions (self)

class CheckPrinterSanity(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter)
        self.troubleshooter = troubleshooter
        troubleshooter.new_page (gtk.Label ("Queue not enabled."), self)
        troubleshooter.no_more_questions (self)

    def display (self):
        # Check some common problems.
        CheckCUPS (self.troubleshooter)
        return False

class ChoosePrinter(Question):
    def __init__ (self, troubleshooter):
        # First question: which printer? (page 1)
        Question.__init__ (self, troubleshooter)
        page1 = gtk.VBox ()
        page1.set_spacing (12)
        page1.set_border_width (12)
        question = gtk.Label (_("Please select the printer you are trying "
                                "to use from the list below.  If it does "
                                "not appear in the list, select "
                                "'Not listed'."))
        question.set_line_wrap (True)
        question.set_alignment (0, 0)
        page1.pack_start (question, False, False, 0)
        model = gtk.ListStore (gobject.TYPE_STRING,
                               gobject.TYPE_STRING,
                               gobject.TYPE_STRING,
                               gobject.TYPE_PYOBJECT)
        tv = gtk.TreeView (model)
        name = gtk.TreeViewColumn (_("Name"),
                                   gtk.CellRendererText (), text=0)
        location = gtk.TreeViewColumn (_("Location"),
                                       gtk.CellRendererText (), text=1)
        info = gtk.TreeViewColumn (_("Information"),
                                   gtk.CellRendererText (), text=2)
        name.set_property ("resizable", True)
        location.set_property ("resizable", True)
        info.set_property ("resizable", True)
        tv.append_column (name)
        tv.append_column (location)
        tv.append_column (info)
        tv.set_rules_hint (True)
        sw = gtk.ScrolledWindow ()
        sw.set_policy (gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        sw.set_shadow_type (gtk.SHADOW_IN)
        sw.add (tv)
        page1.pack_start (sw, True, True, 0)
        self.treeview = tv
        try:
            c = cups.Connection ()
            dests = c.getDests ()
            printers = None
            dests_list = []
            for (name, instance), dest in dests.iteritems ():
                if instance != None:
                    queue = "%s/%s" % (name, instance)
                else:
                    queue = name

                if printers == None:
                    printers = c.getPrinters ()

                if not printers.has_key (name):
                    info = _("Unknown")
                    location = _("Unknown")
                else:
                    printer = printers[name]
                    info = printer.get('printer-info', _("Unknown"))
                    location = printer.get('printer-location', _("Unknown"))

                dests_list.append ((queue, location, info, dest))

            iter = model.append (None)
            model.set (iter, 0, _("Not listed"), 1, '', 2, '', 3, None)

            dests_list.sort (lambda x, y: cmp (x[0], y[0]))
            for queue, location, info, dest in dests_list:
                iter = model.append (None)
                model.set (iter, 0, queue, 1, location, 2, info, 3, dest)

        except cups.HTTPError:
            pass
        except cups.IPPError:
            pass

        troubleshooter.new_page (page1, self)
        self.troubleshooter = troubleshooter

    def cursor_changed (self, widget, handler):
        model, iter = widget.get_selection ().get_selected ()
        if iter != None:
            dest = model.get_value (iter, 3)
            if dest == None:
                # Printer not listed.
                CheckCUPS (self.troubleshooter)
            else:
                Multichoice (self.troubleshooter, 'printer_working_at_all',
                             _("Can you get printer `%s' to print at all?") %
                             dest.name,
                             [(_("Yes"), True),
                              (_("No"), False)])
                CheckPrinterSanity (self.troubleshooter)

        handler (widget)

    def connect_signals (self, handler):
        self.signal_id = self.treeview.connect ("cursor-changed",
                                                lambda x: self.
                                                cursor_changed (x, handler))

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
        if dest == None:
            return { 'cups_queue_listed': False }
        else:
            return { 'cups_queue_listed': True,
                     'cups_dest': dest }

troubleshooter = Troubleshooter ()
Welcome (troubleshooter)
ChoosePrinter (troubleshooter)
gtk.main ()

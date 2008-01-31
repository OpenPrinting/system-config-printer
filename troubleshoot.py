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

import pprint

TEXT_start_print_admin_tool = _("To start this tool, select "
                                "System->Administration->Printing "
                                "from the main menu.")

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
        self.question_answers[page] = answer_dict
        self.answers.update (answer_dict)

        self.questions[page].disconnect_signals ()

        step = 1
        question = self.questions[page + step]
        while not question.display ():
            # Skip this one, but collect its answers.
            answer_dict = question.collect_answer ()
            self.question_answers[page + step] = answer_dict
            self.answers.update (answer_dict)
            print "Page %d: skip" % (page + step)
            step += 1
            question = self.questions[page + step]

        self.ntbk.set_current_page (page + step)
        page += step
        question.connect_signals (self.set_back_forward_buttons)
        self.set_back_forward_buttons ()

        self._dump_answers ()

    def _dump_answers (self):
        page = self.ntbk.get_current_page ()
        print "***"
        for i in range (page):
            print "Page %d:" % i
            pprint.pprint (self.question_answers[i])

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

class TestPagePrinted(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter)
        page = gtk.VBox ()
        page.set_spacing (12)
        page.set_border_width (12)

        hbox = gtk.HBox ()
        hbox.set_spacing (12)
        self.button = gtk.Button (_("Print Test Page"))
        hbox.pack_start (self.button, False, False, 0)

        label = gtk.Label (_("Click the button to print a test page."))
        label.set_line_wrap (True)
        label.set_alignment (0, 0.5)
        hbox.pack_start (label, False, False, 0)

        page.pack_start (hbox, False, False, 0)

        label = gtk.Label (_("Did the test page print?"))
        label.set_line_wrap (True)
        label.set_alignment (0, 0)
        page.pack_start (label, False, False, 0)

        vbox = gtk.VBox ()
        vbox.set_spacing (6)
        self.yes = gtk.RadioButton (label=_("Yes"))
        no = gtk.RadioButton (label=_("No"))
        no.set_group (self.yes)
        vbox.pack_start (self.yes, False, False, 0)
        vbox.pack_start (no, False, False, 0)
        page.pack_start (vbox, False, False, 0)
        self.answers = {}
        troubleshooter.new_page (page, self)

    def clicked (self, widget, handler):
        print "Print test page!"
        self.answers['test_page_attempted'] = True

    def connect_signals (self, handler):
        self.signal_id = self.button.connect ("clicked",
                                              lambda x: self.
                                              clicked (x, handler))

    def disconnect_signals (self):
        self.button.disconnect (self.signal_id)

    def collect_answer (self):
        success = self.yes.get_active ()
        self.answers['test_page_successful'] = success
        return self.answers

class QueueRejectingJobs(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter)
        self.label = gtk.Label ()
        solution = gtk.VBox ()
        self.label.set_line_wrap (True)
        solution.pack_start (self.label, False, False, 0)
        solution.set_border_width (12)
        troubleshooter.new_page (solution, self)

    def display (self):
        troubleshooter = self.troubleshooter
        if troubleshooter.answers['is_cups_class']:
            queue = troubleshooter.answers['cups_class_dict']
        else:
            queue = troubleshooter.answers['cups_printer_dict']

        rejecting = queue['printer-type'] & cups.CUPS_PRINTER_REJECTING
        if not rejecting:
            return False

        state_message = queue.get('printer-state-message', '')

        text = (_("The queue `%s' is rejecting jobs.") %
                troubleshooter.answers['cups_queue'])

        if state_message:
            text += _(" The reason given is: `%s'.") % state_message

        text += "\n\n"
        text += _("To make the queue accept jobs, select the `Accepting Jobs' "
                  "checkbox in the `Policies' tab for the printer in the "
                  "printer administration tool.") + ' ' + \
                  TEXT_start_print_admin_tool

        self.label.set_text (text)
        return True

    def can_click_forward (self):
        return False

class QueueNotEnabled(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter)
        self.label = gtk.Label ()
        solution = gtk.VBox ()
        self.label.set_line_wrap (True)
        solution.pack_start (self.label, False, False, 0)
        solution.set_border_width (12)
        troubleshooter.new_page (solution, self)

    def display (self):
        troubleshooter = self.troubleshooter
        if troubleshooter.answers['is_cups_class']:
            queue = troubleshooter.answers['cups_class_dict']
        else:
            queue = troubleshooter.answers['cups_printer_dict']

        enabled = queue['printer-state'] != cups.IPP_PRINTER_STOPPED
        if enabled:
            return False

        text = _("The queue `%s' is not enabled.  To enable it, "
                 "select the `Enabled' checkbox in the `Policies' "
                 "tab for the printer in the printer administration tool.") % \
                 troubleshooter.answers['cups_queue']

        text += ' ' + TEXT_start_print_admin_tool

        self.label.set_text (text)
        return True

    def can_click_forward (self):
        return False

class CheckPrinterSanity(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter)
        self.answers = {}
        troubleshooter.new_page (gtk.Label (), self)
        QueueNotEnabled (self.troubleshooter)
        QueueRejectingJobs (self.troubleshooter)
        TestPagePrinted (self.troubleshooter)
        CheckCUPS (self.troubleshooter)

    def display (self):
        # Check some common problems.

        # Find out if this is a printer or a class.
        name = self.troubleshooter.answers['cups_queue']
        try:
            c = cups.Connection ()
            printers = c.getPrinters ()
            if printers.has_key (name):
                self.answers['is_cups_class'] = False
                queue = printers[name]
                self.answers['cups_printer_dict'] = queue
            else:
                self.answers['is_cups_class'] = True
                classes = c.getClasses ()
                queue = classes[name]
                self.answers['cups_class_dict'] = queue
        except:
            pass

        return False

    def collect_answer (self):
        return self.answers

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
            self.troubleshooter.no_more_questions (self)
            if dest == None:
                # Printer not listed.
                CheckCUPS (self.troubleshooter)
            else:
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
                     'cups_dest': dest,
                     'cups_queue': dest.name,
                     'cups_instance': dest.instance }

troubleshooter = Troubleshooter ()
Welcome (troubleshooter)
ChoosePrinter (troubleshooter)
gtk.main ()

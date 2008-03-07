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
import pprint
import sys
import traceback
import base
from base import *
from base import _

if __name__ == "__main__":
    import gettext
    gettext.textdomain ('system-config-printer')

class Troubleshooter:
    def __init__ (self, quitfn=None):
        main = gtk.Window ()
        main.set_title (_("Printing troubleshooter"))
        main.set_property ("default-width", 400)
        main.set_property ("default-height", 350)
        main.connect ("delete_event", self.quit)
        self.main = main
        self.quitfn = quitfn

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
        close.connect ('clicked', self.quit)
        self.close = close

        cancel = gtk.Button (stock='gtk-cancel')
        cancel.connect ('clicked', self.quit)
        self.cancel = cancel

        forward = gtk.Button (stock='gtk-go-forward')
        forward.connect ('clicked', self.on_forward_clicked)
        forward.set_flags (gtk.CAN_DEFAULT | gtk.HAS_DEFAULT)
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

    def quit (self, *args):
        page = self.ntbk.get_current_page ()
        try:
            self.questions[page].disconnect_signals ()
        except:
            self._report_traceback ()

        self.main.hide ()
        if self.quitfn:
            self.quitfn (self)

    def no_more_questions (self, question):
        page = self.questions.index (question)
        debugprint ("Page %d: No more questions." % page)
        self.questions = self.questions[:page + 1]
        self.question_answers = self.question_answers[:page + 1]
        for p in range (self.ntbk.get_n_pages () - 1, page, -1):
            self.ntbk.remove_page (p)
        self.set_back_forward_buttons ()

    def new_page (self, widget, question):
        page = len (self.questions)
        debugprint ("Page %d: new: %s" % (page, str (question)))
        self.questions.append (question)
        self.question_answers.append ([])
        self.ntbk.insert_page (widget, position=page)
        widget.show_all ()
        if page == 0:
            try:
                question.connect_signals (self.set_back_forward_buttons)
            except:
                self._report_traceback ()

            self.ntbk.set_current_page (page)
        self.set_back_forward_buttons ()
        return page

    def set_back_forward_buttons (self, *args):
        page = self.ntbk.get_current_page ()
        self.back.set_sensitive (page != 0)
        if len (self.questions) == page + 1:
            # Out of questions.
            debugprint ("Out of questions")
            self.forward.set_sensitive (False)
            self.close.show ()
            self.cancel.hide ()
        else:
            can = self._can_click_forward (self.questions[page])
            debugprint ("Page %d: can click forward? %s" % (page, can))
            self.forward.set_sensitive (can)
            self.close.hide ()
            self.cancel.show ()

    def on_back_clicked (self, widget):
        page = self.ntbk.get_current_page ()
        try:
            self.questions[page].disconnect_signals ()
        except:
            self._report_traceback ()

        step = 1
        question = self.questions[page - step]
        self.ntbk.prev_page ()
        while not self._display (question):
            # Skip this one.            
            debugprint ("Page %d: skip" % (page - step))
            step += 1
            question = self.questions[page - step]
            self.ntbk.prev_page ()

        page -= step

        answers = {}
        for i in range (page):
            answers.update (self.question_answers[i])
        self.answers = answers

        try:
            self.questions[page].connect_signals (self.set_back_forward_buttons)
        except:
            self._report_traceback ()

        self.set_back_forward_buttons ()

    def on_forward_clicked (self, widget):
        page = self.ntbk.get_current_page ()
        answer_dict = self._collect_answer (self.questions[page])
        self.question_answers[page] = answer_dict
        self.answers.update (answer_dict)

        try:
            self.questions[page].disconnect_signals ()
        except:
            self._report_traceback ()

        step = 1
        question = self.questions[page + step]
        self.ntbk.next_page ()
        while not self._display (question):
            # Skip this one, but collect its answers.
            answer_dict = self._collect_answer (question)
            self.question_answers[page + step] = answer_dict
            self.answers.update (answer_dict)
            debugprint ("Page %d: skip" % (page + step))
            step += 1
            question = self.questions[page + step]
            self.ntbk.next_page ()

        page += step

        try:
            question.connect_signals (self.set_back_forward_buttons)
        except:
            self._report_traceback ()

        self.set_back_forward_buttons ()

        if debug:
            self._dump_answers ()

    def answers_as_text (self):
        text = ""
        page = self.ntbk.get_current_page ()
        n = 1
        for i in range (page):
            answers = self.question_answers[i].copy ()
            for hidden in filter (lambda x: x.startswith ("_"), answers.keys()):
                del answers[hidden]
            if len (answers.keys ()) == 0:
                continue
            text += "Page %d (%s):" % (n, self.questions[i]) + '\n'
            text += pprint.pformat (answers) + '\n'
            n += 1
        return text.rstrip () + '\n'

    def _dump_answers (self):
        debugprint (self.answers_as_text ())

    def _report_traceback (self):
        print "Traceback:"
        (type, value, tb) = sys.exc_info ()
        tblast = traceback.extract_tb (tb, limit=None)
        if len (tblast):
            tblast = tblast[:len (tblast) - 1]
        extxt = traceback.format_exception_only (type, value)
        for line in traceback.format_tb(tb):
            print line.strip ()
        print extxt[0].strip ()

    def _display (self, question):
        result = False
        try:
            result = question.display ()
        except:
            self._report_traceback ()

        question.displayed = result
        return result

    def _can_click_forward (self, question):
        try:
            return question.can_click_forward ()
        except:
            self._report_traceback ()
            return True

    def _collect_answer (self, question):
        try:
            return question.collect_answer ()
        except:
            self._report_traceback ()
            return {}

QUESTIONS = ["Welcome",
             "SchedulerNotRunning",
             "ChoosePrinter",
             "CheckPrinterSanity",

             "LocalOrRemote",
             "DeviceListed",
             "RemoteAddress",
             "CheckNetworkServerSanity",
             "ChooseNetworkPrinter",

             "NetworkCUPSPrinterShared",

             "QueueNotEnabled",
             "QueueRejectingJobs",
             "PrinterStateReasons",

             "ServerFirewalled",
             "ErrorLogCheckpoint",
             "PrintTestPage",
             "ErrorLogFetch",
             "PrinterStateReasons",
             "ErrorLogParse",
             "Shrug"]

def run (quitfn=None):
    troubleshooter = Troubleshooter (quitfn)
    modules_imported = []
    for module in QUESTIONS:
        try:
            if not module in modules_imported:
                exec ("from %s import %s" % (module, module))
                exec ("%s.debug = %d" % (module, debug))
                modules_imported.append (module)

            exec ("%s (troubleshooter)" % module)
        except:
            troubleshooter._report_traceback ()
    return troubleshooter

if __name__ == "__main__":
    import sys, getopt
    base.debug = 0
    try:
        opts, args = getopt.gnu_getopt (sys.argv[1:], '',
                                        ['debug'])
        for opt, optarg in opts:
            if opt == '--debug':
                base.debug = 1
    except getopt.GetoptError:
        pass

    import os.path
    if sys.argv[0][0] != '/':
        cwd = os.getcwd ()
        path = cwd + os.path.sep + sys.argv[0]
    else:
        path = sys.argv[0]
    sub = os.path.dirname (path)
    root = os.path.dirname (sub)
    debugprint ("Appending %s to path" % root)
    sys.path.append (root)
    run (gtk.main_quit)
    gtk.main ()

#!/usr/bin/python3

## Printing troubleshooter

## Copyright (C) 2008, 2009, 2010, 2012 Red Hat, Inc.
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

from gi.repository import Gdk
from gi.repository import Gtk
import pprint
import sys
import traceback

if __name__ == "__main__":
    import os.path
    import gettext
    gettext.textdomain ('system-config-printer')

    if sys.argv[0][0] != '/':
        cwd = os.getcwd ()
        path = cwd + os.path.sep + sys.argv[0]
    else:
        path = sys.argv[0]
    sub = os.path.dirname (path)
    root = os.path.dirname (sub)
    sys.path.append (root)

from . import base
from .base import *

class Troubleshooter:
    def __init__ (self, quitfn=None, parent=None):
        self._in_module_call = False

        main = Gtk.Window ()
        if parent:
            main.set_transient_for (parent)
            main.set_position (Gtk.WindowPosition.CENTER_ON_PARENT)
            main.set_modal (True)

        main.set_title (_("Printing troubleshooter"))
        main.set_property ("default-width", 400)
        main.set_property ("default-height", 350)
        main.connect ("delete_event", self.quit)
        self.main = main
        self.quitfn = quitfn

        vbox = Gtk.VBox ()
        main.add (vbox)
        ntbk = Gtk.Notebook ()
        ntbk.set_border_width (6)
        vbox.pack_start (ntbk, True, True, 0)
        vbox.pack_start (Gtk.HSeparator (), False, False, 0)
        box = Gtk.HButtonBox ()
        box.set_border_width (6)
        box.set_spacing (3)
        box.set_layout (Gtk.ButtonBoxStyle.END)

        back = Gtk.Button.new_from_stock (Gtk.STOCK_GO_BACK)
        back.connect ('clicked', self._on_back_clicked)
        back.set_sensitive (False)
        self.back = back

        close = Gtk.Button.new_from_stock (Gtk.STOCK_CLOSE)
        close.connect ('clicked', self.quit)
        self.close = close

        cancel = Gtk.Button.new_from_stock (Gtk.STOCK_CANCEL)
        cancel.connect ('clicked', self.quit)
        self.cancel = cancel

        forward = Gtk.Button.new_from_stock (Gtk.STOCK_GO_FORWARD)
        forward.connect ('clicked', self._on_forward_clicked)
        self.forward = forward

        box.pack_start (back, False, False, 0)
        box.pack_start (cancel, False, False, 0)
        box.pack_start (close, False, False, 0)
        box.pack_start (forward, False, False, 0)
        vbox.pack_start (box, False, False, 0)
        forward.set_property('can-default', True)
        forward.set_property('has-default', True)

        ntbk.set_current_page (0)
        ntbk.set_show_tabs (False)
        self.ntbk = ntbk
        self.current_page = 0

        self.questions = []
        self.question_answers = []
        self.answers = {}
        self.moving_backwards = False

        main.show_all ()

    def quit (self, *args):
        if self._in_module_call:
            try:
                self.questions[self.current_page].cancel_operation ()
            except:
                self._report_traceback ()

            return

        try:
            self.questions[self.current_page].disconnect_signals ()
        except:
            self._report_traceback ()

        # Delete the questions so that their __del__ hooks can run.
        # Do this in reverse order of creation.
        for i in range (len (self.questions)):
            self.questions.pop ()

        self.main.hide ()
        if self.quitfn:
            self.quitfn (self)

    def get_window (self):
        # Any error dialogs etc from the modules need to be able
        # to set themselves transient for this window.
        return self.main

    def no_more_questions (self, question):
        page = self.questions.index (question)
        debugprint ("Page %d: No more questions." % page)
        self.questions = self.questions[:page + 1]
        self.question_answers = self.question_answers[:page + 1]
        for p in range (self.ntbk.get_n_pages () - 1, page, -1):
            self.ntbk.remove_page (p)
        self._set_back_forward_buttons ()

    def new_page (self, widget, question):
        page = len (self.questions)
        debugprint ("Page %d: new: %s" % (page, str (question)))
        self.questions.append (question)
        self.question_answers.append ([])
        self.ntbk.insert_page (widget, None, page)
        widget.show_all ()
        if page == 0:
            try:
                question.connect_signals (self._set_back_forward_buttons)
            except:
                self._report_traceback ()

            self.ntbk.set_current_page (page)
            self.current_page = page
        self._set_back_forward_buttons ()
        return page

    def is_moving_backwards (self):
        return self.moving_backwards

    def answers_as_text (self):
        text = ""
        n = 1
        for i in range (self.current_page):
            answers = self.question_answers[i].copy ()
            for hidden in [x for x in answers.keys() if x.startswith ("_")]:
                del answers[hidden]
            if len (list(answers.keys ())) == 0:
                continue
            text += "Page %d (%s):" % (n, self.questions[i]) + '\n'
            text += pprint.pformat (answers) + '\n'
            n += 1
        return text.rstrip () + '\n'

    def busy (self):
        self._in_module_call = True
        self.forward.set_sensitive (False)
        self.back.set_sensitive (False)
        gdkwin = self.get_window ().get_window()
        if gdkwin:
            gdkwin.set_cursor (Gdk.Cursor.new(Gdk.CursorType.WATCH))
            while Gtk.events_pending ():
                Gtk.main_iteration ()

    def ready (self):
        self._in_module_call = False
        gdkwin = self.get_window ().get_window()
        if gdkwin:
            gdkwin.set_cursor (Gdk.Cursor.new(Gdk.CursorType.LEFT_PTR))

        self._set_back_forward_buttons ()

    def _set_back_forward_buttons (self, *args):
        page = self.current_page
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

    def _on_back_clicked (self, widget):
        self.busy ()
        self.moving_backwards = True
        try:
            self.questions[self.current_page].disconnect_signals ()
        except:
            self._report_traceback ()

        self.current_page -= 1
        question = self.questions[self.current_page]
        while not self._display (question):
            # Skip this one.            
            debugprint ("Page %d: skip" % (self.current_page))
            self.current_page -= 1
            question = self.questions[self.current_page]

        self.ntbk.set_current_page (self.current_page)
        answers = {}
        for i in range (self.current_page):
            answers.update (self.question_answers[i])
        self.answers = answers

        try:
            self.questions[self.current_page].\
                connect_signals (self._set_back_forward_buttons)
        except:
            self._report_traceback ()

        self.moving_backwards = False
        self.ready ()

    def _on_forward_clicked (self, widget):
        self.busy ()
        answer_dict = self._collect_answer (self.questions[self.current_page])
        self.question_answers[self.current_page] = answer_dict
        self.answers.update (answer_dict)

        try:
            self.questions[self.current_page].disconnect_signals ()
        except:
            self._report_traceback ()

        self.current_page += 1
        question = self.questions[self.current_page]
        while not self._display (question):
            # Skip this one, but collect its answers.
            answer_dict = self._collect_answer (question)
            self.question_answers[self.current_page] = answer_dict
            self.answers.update (answer_dict)
            debugprint ("Page %d: skip" % (self.current_page))
            self.current_page += 1
            question = self.questions[self.current_page]

        self.ntbk.set_current_page (self.current_page)
        try:
            question.connect_signals (self._set_back_forward_buttons)
        except:
            self._report_traceback ()

        self.ready ()
        if get_debugging ():
            self._dump_answers ()

    def _dump_answers (self):
        debugprint (self.answers_as_text ())

    def _report_traceback (self):
        try:
            print("Traceback:")
            (type, value, tb) = sys.exc_info ()
            tblast = traceback.extract_tb (tb, limit=None)
            if len (tblast):
                tblast = tblast[:len (tblast) - 1]
            extxt = traceback.format_exception_only (type, value)
            for line in traceback.format_tb(tb):
                print(line.strip ())
            print(extxt[0].strip ())
        except:
            pass

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
        answer = {}
        try:
            answer = question.collect_answer ()
        except:
            self._report_traceback ()

        return answer

QUESTIONS = ["Welcome",
             "SchedulerNotRunning",
             "CheckLocalServerPublishing",
             "ChoosePrinter",
             "CheckPrinterSanity",
             "CheckPPDSanity",

             "LocalOrRemote",
             "DeviceListed",
             "CheckUSBPermissions",

             "RemoteAddress",
             "CheckNetworkServerSanity",
             "ChooseNetworkPrinter",

             "NetworkCUPSPrinterShared",

             "QueueNotEnabled",
             "QueueRejectingJobs",
             "PrinterStateReasons",

             "VerifyPackages",
             "CheckSELinux",
             "ServerFirewalled",
             "ErrorLogCheckpoint",
             "PrintTestPage",
             "ErrorLogFetch",
             "PrinterStateReasons",
             "ErrorLogParse",
             "Locale",
             "Shrug"]

def run (quitfn=None, parent=None):
    troubleshooter = Troubleshooter (quitfn, parent=parent)
    modules_imported = []
    for module in QUESTIONS:
        try:
            if not module in modules_imported:
                exec ("from .%s import %s" % (module, module))
                modules_imported.append (module)

            exec ("%s (troubleshooter)" % module)
        except:
            troubleshooter._report_traceback ()
    return troubleshooter

if __name__ == "__main__":
    import getopt
    try:
        opts, args = getopt.gnu_getopt (sys.argv[1:], '',
                                        ['debug'])
        for opt, optarg in opts:
            if opt == '--debug':
                set_debugging (True)
    except getopt.GetoptError:
        pass
    Gdk.threads_init()
    run (Gtk.main_quit)
    Gdk.threads_enter ()
    Gtk.main ()
    Gdk.threads_leave ()

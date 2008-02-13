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
import pango
import pprint
import socket
import subprocess
import sys
import traceback
import urllib
from gettext import gettext as _

if __name__ == "__main__":
    import gettext
    gettext.textdomain ('system-config-printer')

debug=0
def debugprint (x):
    if debug:
        try:
            print x
        except:
            pass

TEXT_start_print_admin_tool = _("To start this tool, select "
                                "System->Administration->Printing "
                                "from the main menu.")

class AuthenticationDialog:
    def __init__ (self, parent=None):
        self.parent = parent
        cups.setPasswordCB (self.callback)

    def callback (self, prompt):
        dialog = gtk.Dialog (_("Authentication"),
                             self.parent,
                             gtk.DIALOG_MODAL | gtk.DIALOG_NO_SEPARATOR,
                             (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                              gtk.STOCK_OK, gtk.RESPONSE_OK))
        dialog.set_default_response (gtk.RESPONSE_OK)
        dialog.set_border_width (6)
        dialog.set_resizable (False)
        hbox = gtk.HBox (False, 12)
        hbox.set_border_width (6)
        image = gtk.Image ()
        image.set_from_stock ('gtk-dialog-authentication', gtk.ICON_SIZE_DIALOG)
        hbox.pack_start (image, False, False, 0)
        vbox = gtk.VBox (False, 12)
        label = gtk.Label ('<span weight="bold" size="larger">' +
                           _("Password required") + '</span>\n\n' + prompt)
        label.set_use_markup (True)
        label.set_alignment (0, 0)
        vbox.pack_start (label, False, False, 0)
        hbox.pack_start (vbox, False, False, 0)

        box = gtk.HBox (False, 6)
        vbox.pack_start (box, False, False, 0)
        box.pack_start (gtk.Label (_("Password:")), False, False, 0)
        self.password = gtk.Entry ()
        self.password.set_activates_default (True)
        self.password.set_visibility (False)
        box.pack_start (self.password, False, False, 0)

        dialog.vbox.pack_start (hbox, True, True, 0)
        dialog.show_all ()
        response = dialog.run ()
        dialog.hide ()
        if response != gtk.RESPONSE_OK:
            # Give up.
            return ''

        self.last_password = self.password.get_text ()
        if self.username.get_text () != cups.getUser ():
            # Switch to another username for this action.
            print "Switch"
            cups.setUser (self.username.get_text ())
            self.need_reconnect = True
            return ''

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
            answers = self.question_answers[i]
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
        try:
            return question.display ()
        except:
            self._report_traceback ()
            return False

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

#############

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

#############

class Welcome(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Welcome")
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

class Shrug(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Shrug")
        page = self.initial_vbox (_("Sorry!"),
                                  _("I have not been able to work out what "
                                    "the problem is, but I have collected "
                                    "some useful information to put in a "
                                    "bug report."))

        sw = gtk.ScrolledWindow ()
        textview = gtk.TextView ()
        textview.set_editable (False)
        sw.add (textview)
        page.pack_start (sw)
        self.buffer = textview.get_buffer ()

        box = gtk.HButtonBox ()
        box.set_border_width (0)
        box.set_spacing (3)
        box.set_layout (gtk.BUTTONBOX_END)
        page.pack_start (box, False, False, 0)

        self.copy = gtk.Button (stock='gtk-copy')
        box.pack_start (self.copy, False, False, 0)

        self.save = gtk.Button (stock='gtk-save')
        box.pack_start (self.save, False, False, 0)

        self.clipboard = gtk.Clipboard ()

        troubleshooter.new_page (page, self)

    def display (self):
        self.buffer.set_text (self.troubleshooter.answers_as_text ())
        return True

    def connect_signals (self, handler):
        self.copy_sigid = self.copy.connect ('clicked', self.on_copy_clicked)
        self.save_sigid = self.save.connect ('clicked', self.on_save_clicked)

    def disconnect_signals (self):
        self.copy.disconnect (self.copy_sigid)
        self.save.disconnect (self.save_sigid)

    def on_copy_clicked (self, button):
        text = self.buffer.get_text (self.buffer.get_start_iter (),
                                     self.buffer.get_end_iter ())
        self.clipboard.set_text (text)

    def on_save_clicked (self, button):
        dialog = gtk.FileChooserDialog (parent=self.troubleshooter.main,
                                        action=gtk.FILE_CHOOSER_ACTION_SAVE,
                                        buttons=('gtk-cancel',
                                                 gtk.RESPONSE_CANCEL,
                                                 'gtk-save',
                                                 gtk.RESPONSE_OK))
        dialog.set_do_overwrite_confirmation (True)
        dialog.set_default_response (gtk.RESPONSE_OK)
        response = dialog.run ()
        dialog.hide ()
        if response != gtk.RESPONSE_OK:
            return

        f = file (dialog.get_filename (), "w")
        f.write (self.buffer.get_text (self.buffer.get_start_iter (),
                                       self.buffer.get_end_iter ()))
        del f

###

class NetworkCUPSPrinterAccepting(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Queue not accepting jobs?")
        page = self.initial_vbox (_("Queue Not Accepting Jobs"),
                                  _("The CUPS printer on the server is not "
                                    "accepting jobs."))
        troubleshooter.new_page (page, self)

    def display (self):
        answers = self.troubleshooter.answers
        attr = answers.get ('remote_cups_queue_attributes', False)
        if not attr:
            return False

        try:
            if attr['printer-type'] & cups.CUPS_PRINTER_REJECTING:
                return True
        except:
            pass

        return False

    def can_click_forward (self):
        return False

class NetworkCUPSPrinterEnabled(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Queue not enabled?")
        page = self.initial_vbox (_("Queue Not Enabled"),
                                  _("The CUPS printer on the server is not "
                                    "enabled."))
        troubleshooter.new_page (page, self)

    def display (self):
        answers = self.troubleshooter.answers
        try:
            attr = answers['remote_cups_queue_attributes']
            if attr['printer-state'] == cups.IPP_PRINTER_STOPPED:
                return True
        except:
            pass

        return False

    def can_click_forward (self):
        return False

class NetworkCUPSPrinterShared(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Queue not shared?")
        page = self.initial_vbox (_("Queue Not Shared"),
                                  _("The CUPS printer on the server is not "
                                    "shared."))
        troubleshooter.new_page (page, self)

    def display (self):
        self.answers = {}
        answers = self.troubleshooter.answers
        if not answers.get ('remote_cups_queue_listed', False):
            return False

        try:
            cups.setServer (answers['remote_server_try_connect'])
            c = cups.Connection ()
            attr = c.getPrinterAttributes (answers['remote_cups_queue'])
        except:
            return False

        self.answers['remote_cups_queue_attributes'] = attr
        if attr.has_key ('printer-is-shared'):
            # CUPS >= 1.2
            if not attr['printer-is-shared']:
                return True

        return False

    def can_click_forward (self):
        return False

    def collect_answer (self):
        return self.answers

class ChooseNetworkPrinter(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Choose network printer")
        page1 = self.initial_vbox (_("Choose Network Printer"),
                                   _("Please select the network printer you "
                                     "are trying to use from the list below. "
                                     "If it does not appear in the list, "
                                     "select 'Not listed'."))
        tv = gtk.TreeView ()
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
        troubleshooter.new_page (page1, self)

    def display (self):
        answers = self.troubleshooter.answers
        if not answers.get ('remote_server_cups', False):
            return False

        server = answers['remote_server_name']
        if not server:
            server = answers['remote_server_ip_address']

        model = gtk.ListStore (gobject.TYPE_STRING,
                               gobject.TYPE_STRING,
                               gobject.TYPE_STRING,
                               gobject.TYPE_PYOBJECT)
        self.model = model
        self.treeview.set_model (model)
        iter = model.append (None)
        model.set (iter, 0, _("Not listed"), 1, '', 2, '', 3, None)

        try:
            cups.setServer (server)
            c = cups.Connection ()
            dests = c.getDests ()
            printers = None
            dests_list = []
            for (name, instance), dest in dests.iteritems ():
                if name == None:
                    continue

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

            dests_list.sort (lambda x, y: cmp (x[0], y[0]))
            for queue, location, info, dest in dests_list:
                iter = model.append (None)
                model.set (iter, 0, queue, 1, location, 2, info, 3, dest)

        except cups.HTTPError:
            pass
        except cups.IPPError:
            pass
        except RuntimeError:
            pass

        return True

    def connect_signals (self, handler):
        self.signal_id = self.treeview.connect ("cursor-changed", handler)

    def disconnect_signals (self):
        self.treeview.disconnect (self.signal_id)

    def can_click_forward (self):
        model, iter = self.treeview.get_selection ().get_selected ()
        if iter == None:
            return False
        return True

    def collect_answer (self):
        model, iter = self.treeview.get_selection ().get_selected ()
        if not model:
            return {}

        dest = model.get_value (iter, 3)
        if dest == None:
            class enum_dests:
                def __init__ (self, model):
                    self.dests = []
                    model.foreach (self.each, None)

                def each (self, model, path, iter, user_data):
                    dest = model.get_value (iter, 3)
                    if dest:
                        self.dests.append ((dest.name, dest.instance))

            return { 'remote_cups_queue_listed': False,
                     'remote_cups_dests_available': enum_dests (model).dests }
        else:
            return { 'remote_cups_queue_listed': True,
                     'remote_cups_dest': dest,
                     'remote_cups_queue': dest.name,
                     'remote_cups_instance': dest.instance }

class CheckNetworkPrinterSanity(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Check network printer sanity")
        troubleshooter.new_page (gtk.Label (), self)

    def display (self):
        # Collect useful information.

        self.answers = {}
        answers = self.troubleshooter.answers
        if (not answers.has_key ('remote_server_name') and
            not answers.has_key ('remote_server_ip_address')):
            return False

        server_name = answers['remote_server_name']
        server_port = answers.get('remote_server_port', 631)
        if server_name:
            # Try resolving the hostname.
            try:
                ai = socket.getaddrinfo (server_name, server_port)
                resolves = map (lambda (family, socktype,
                                        proto, canonname, sockaddr):
                                    sockaddr[0], ai)
            except socket.gaierror:
                resolves = False

            self.answers['remote_server_name_resolves'] = resolves

            ipaddr = answers.get ('remote_server_ip_address', '')
            if ipaddr:
                try:
                    resolves.index (ipaddr)
                except ValueError:
                    # The IP address given doesn't match the server name.
                    # Use the IP address instead of the name.
                    server_name = ipaddr
        else:
            server_name = answers['remote_server_ip_address']

        self.answers['remote_server_try_connect'] = server_name

        if (answers.has_key ('cups_device_uri_scheme') and
            answers['cups_device_uri_scheme'] == "ipp"):
            try:
                cups.setServer (server_name)
                cups.setPort (server_port)
                c = cups.Connection ()
                ipp_connect = True
            except RuntimeError:
                ipp_connect = False

            self.answers['remote_server_connect_ipp'] = ipp_connect

        if ipp_connect:
            try:
                c.getPrinters ()
                cups_server = True
            except:
                cups_server = False

            self.answers['remote_server_cups'] = cups_server

        # Try traceroute if we haven't already.
        if not answers.has_key ('remote_server_traceroute'):
            p = subprocess.Popen (['traceroute', '-w', '1', server_name],
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
            (stdout, stderr) = p.communicate ()
            self.answers['remote_server_traceroute'] = (stdout, stderr)

        return False

    def collect_answer (self):
        return self.answers

class RemoteAddress(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Remote address")
        page = self.initial_vbox (_("Remote Address"),
                                  _("Please enter as many details as you "
                                    "can about the network address of this "
                                    "printer."))
        table = gtk.Table (2, 2)
        table.set_row_spacings (6)
        table.set_col_spacings (6)
        page.pack_start (table, False, False, 0)

        label = gtk.Label (_("Server name:"))
        label.set_alignment (0, 0)
        table.attach (label, 0, 1, 0, 1)
        self.server_name = gtk.Entry ()
        table.attach (self.server_name, 1, 2, 0, 1)

        label = gtk.Label (_("Server IP address:"))
        label.set_alignment (0, 0)
        table.attach (label, 0, 1, 1, 2)
        self.server_ipaddr = gtk.Entry ()
        table.attach (self.server_ipaddr, 1, 2, 1, 2)

        troubleshooter.new_page (page, self)

    def display (self):
        return self.troubleshooter.answers['printer_is_remote']

    def collect_answer (self):
        return { 'remote_server_name': self.server_name.get_text (),
                 'remote_server_ip_address': self.server_ipaddr.get_text () }

class LocalOrRemote(Multichoice):
    def __init__ (self, troubleshooter):
        Multichoice.__init__ (self, troubleshooter, "printer_is_remote",
                              _("Printer Location"),
                              _("Is the printer connected to this computer "
                                "or available on the network?"),
                              [(_("Locally connected printer"), False),
                               (_("Network printer"), True)],
                              "Local or remote?")
        RemoteAddress (troubleshooter)
        CheckNetworkPrinterSanity (troubleshooter)
        ChooseNetworkPrinter (troubleshooter)
        NetworkCUPSPrinterShared (troubleshooter)
        NetworkCUPSPrinterAccepting (troubleshooter)
        NetworkCUPSPrinterEnabled (troubleshooter)

class PrinterNotListed(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Printer not listed")
        page = self.initial_vbox (_("CUPS Service Stopped"),
                                  _("The CUPS print spooler does not appear "
                                    "to be running.  To correct this, choose "
                                    "System->Administration->Services from "
                                    "the main menu and look for the `cups' "
                                    "service."))
        troubleshooter.new_page (page, self)
        LocalOrRemote (troubleshooter)

    def display (self):
        # Find out if CUPS is running.
        self.answers = {}
        failure = False
        try:
            c = cups.Connection ()
        except:
            failure = True

        self.answers['cups_connection_failure'] = failure
        return failure

    def can_click_forward (self):
        return False

    def collect_answer (self):
        return self.answers

###

class PrintTestPage(Question):
    STATE = { cups.IPP_JOB_PENDING: _("Pending"),
              cups.IPP_JOB_HELD: _("Held"),
              cups.IPP_JOB_PROCESSING: _("Processing"),
              cups.IPP_JOB_STOPPED: _("Stopped"),
              cups.IPP_JOB_CANCELED: _("Canceled"),
              cups.IPP_JOB_ABORTED: _("Aborted"),
              cups.IPP_JOB_COMPLETED: _("Completed") }

    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Print test page")
        page = gtk.VBox ()
        page.set_spacing (12)
        page.set_border_width (12)

        label = gtk.Label ('<span weight="bold" size="larger">' +
                           _("Test Page") + '</span>')
        label.set_alignment (0, 0)
        label.set_use_markup (True)
        page.pack_start (label, False, False, 0)

        hbox = gtk.HButtonBox ()
        hbox.set_border_width (0)
        hbox.set_spacing (3)
        hbox.set_layout (gtk.BUTTONBOX_START)
        self.print_button = gtk.Button (_("Print Test Page"))
        hbox.pack_start (self.print_button, False, False, 0)

        self.cancel_button = gtk.Button (_("Cancel All Jobs"))
        hbox.pack_start (self.cancel_button, False, False, 0)
        page.pack_start (hbox, False, False, 0)

        tv = gtk.TreeView ()
        job = gtk.TreeViewColumn (_("Job"), gtk.CellRendererText (), text=0)
        printer_cell = gtk.CellRendererText ()
        printer = gtk.TreeViewColumn (_("Printer"), printer_cell, text=1)
        name_cell = gtk.CellRendererText ()
        name = gtk.TreeViewColumn (_("Document"), name_cell, text=2)
        status = gtk.TreeViewColumn (_("Status"), gtk.CellRendererText (),
                                     text=3)
        printer.set_resizable (True)
        printer_cell.set_property ("ellipsize", pango.ELLIPSIZE_END)
        printer_cell.set_property ("width-chars", 20)
        name.set_resizable (True)
        name_cell.set_property ("ellipsize", pango.ELLIPSIZE_END)
        name_cell.set_property ("width-chars", 20)
        status.set_resizable (True)
        tv.append_column (job)
        tv.append_column (printer)
        tv.append_column (name)
        tv.append_column (status)
        tv.set_rules_hint (True)
        sw = gtk.ScrolledWindow ()
        sw.set_policy (gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        sw.set_shadow_type (gtk.SHADOW_IN)
        sw.add (tv)
        self.treeview = tv
        page.pack_start (sw)

        label = gtk.Label (_("Did the test page print correctly?"))
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
        self.persistent_answers = {}
        troubleshooter.new_page (page, self)

    def update_job (self, jobid, job_dict):
        iter = self.job_to_iter[jobid]
        model = self.treeview.get_model ()
        try:
            printer_name = job_dict['printer-name']
        except KeyError:
            try:
                uri = job_dict['job-printer-uri']
                r = uri.rfind ('/')
                printer_name = uri[r + 1:]
            except KeyError:
                printer_name = None

        if printer_name != None:
            model.set_value (iter, 1, printer_name)

        model.set_value (iter, 2, job_dict['job-name'])
        model.set_value (iter, 3, self.STATE[job_dict['job-state']])

    def display (self):
        if not self.troubleshooter.answers.has_key ('cups_queue'):
            return False

        model = gtk.ListStore (gobject.TYPE_INT,
                               gobject.TYPE_STRING,
                               gobject.TYPE_STRING,
                               gobject.TYPE_STRING)
        self.treeview.set_model (model)
        self.job_to_iter = {}

        jobs = self.persistent_answers.get ('test_page_job_id', [])
        cups.setServer ('')
        c = cups.Connection ()

        jobs_dict = c.getJobs (which_jobs='not-completed',
                               my_jobs=False)

        # We want to display the jobs in the queue for this printer...
        try:
            queue_uri_ending = "/" + self.troubleshooter.answers['cups_queue']
            jobs_on_this_printer = filter (lambda x:
                                               jobs_dict[x]['job-printer-uri'].\
                                               endswith (queue_uri_ending),
                                           jobs_dict.keys ())
        except:
            jobs_on_this_printer = []

        # ...as well as any other jobs we've previous submitted as test pages.
        jobs = list (set(jobs).union (set (jobs_on_this_printer)))

        completed_jobs_dict = None
        for job in jobs:
            try:
                j = jobs_dict[job]
            except KeyError:
                if completed_jobs_dict == None:
                    completed_jobs_dict = c.getJobs (which_jobs='completed')
                try:
                    j = completed_jobs_dict[job]
                except KeyError:
                    continue

            iter = model.append (None)
            self.job_to_iter[job] = iter
            model.set_value (iter, 0, job)
            self.update_job (job, j)

        return True

    def print_clicked (self, widget):
        self.persistent_answers['test_page_attempted'] = True
        answers = self.troubleshooter.answers
        c = cups.Connection ()
        jobid = c.printTestPage (answers['cups_queue'])
        jobs = self.persistent_answers.get ('test_page_job_id', [])
        jobs.append (jobid)
        self.persistent_answers['test_page_job_id'] = jobs

    def cancel_clicked (self, widget):
        self.persistent_answers['test_page_jobs_cancelled'] = True
        c = cups.Connection ()
        for jobid, iter in self.job_to_iter.iteritems ():
            try:
                c.cancelJob (jobid)
            except cups.IPPError, (e, s):
                if e != cups.IPP_NOT_POSSIBLE:
                    raise

    def connect_signals (self, handler):
        self.print_sigid = self.print_button.connect ("clicked",
                                                      self.print_clicked)
        self.cancel_sigid = self.cancel_button.connect ("clicked",
                                                        self.cancel_clicked)

        cups.setServer ('')
        c = cups.Connection ()
        self.sub_id = c.createSubscription ("/",
                                            events=["job-created",
                                                    "job-completed",
                                                    "job-stopped",
                                                    "job-progress",
                                                    "job-state-changed"])

        self.timer = gobject.timeout_add (1000, self.update_jobs_list)

    def disconnect_signals (self):
        self.print_button.disconnect (self.print_sigid)
        self.cancel_button.disconnect (self.cancel_sigid)
        c = cups.Connection ()
        c.cancelSubscription (self.sub_id)
        try:
            del self.sub_seq
        except:
            pass

        gobject.source_remove (self.timer)

    def collect_answer (self):
        self.answers = self.persistent_answers.copy ()
        success = self.yes.get_active ()
        self.answers['test_page_successful'] = success

        class collect_jobs:
            def __init__ (self, model):
                self.jobs = []
                model.foreach (self.each, None)

            def each (self, model, path, iter, user_data):
                self.jobs.append (model.get (iter, 0, 1, 2))

        model = self.treeview.get_model ()
        self.answers['test_page_job_status'] = collect_jobs (model).jobs
        return self.answers

    def update_jobs_list (self):
        c = cups.Connection ()
        try:
            notifications = c.getNotifications ([self.sub_id],
                                                [self.sub_seq + 1])
        except AttributeError:
            notifications = c.getNotifications ([self.sub_id])

        answers = self.troubleshooter.answers
        model = self.treeview.get_model ()
        queue = answers['cups_queue']
        test_jobs = self.persistent_answers.get('test_page_job_id', [])
        for event in notifications['events']:
            self.sub_seq = event['notify-sequence-number']
            job = event['notify-job-id']

            nse = event['notify-subscribed-event']
            if nse == 'job-created':
                if (job in test_jobs or
                    event['printer-name'] == queue):
                    iter = model.append (None)
                    self.job_to_iter[job] = iter
                    model.set_value (iter, 0, job)
                else:
                    continue
            elif not self.job_to_iter.has_key (job):
                continue

            if (job in test_jobs and
                nse in ["job-stopped", "job-completed"]):
                comp = self.persistent_answers.get ('test_page_completions', [])
                comp.append ((job, event['notify-text']))
                self.persistent_answers['test_page_completions'] = comp

            self.update_job (job, event)
        return True

class PrinterStateReasons(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Printer state reasons")
        page = self.initial_vbox (_("Status Messages"),
                                  _("There are status messages associated with "
                                    "this queue."))
        table = gtk.Table (2, 2)
        table.set_col_spacings (6)
        table.set_row_spacings (6)

        label = gtk.Label (_("Printer's state message:"))
        label.set_alignment (0, 0)
        table.attach (label, 0, 1, 0, 1, gtk.FILL)
        self.state_message_label = gtk.Label ()
        self.state_message_label.set_line_wrap (True)
        self.state_message_label.set_alignment (0, 0)
        table.attach (self.state_message_label, 1, 2, 0, 1)

        label = gtk.Label (_("Printer's state reasons:"))
        label.set_alignment (0, 0)
        table.attach (label, 0, 1, 1, 2, gtk.FILL)
        self.state_reasons_label = gtk.Label ()
        self.state_reasons_label.set_line_wrap (True)
        self.state_reasons_label.set_alignment (0, 0)
        table.attach (self.state_reasons_label, 1, 2, 1, 2)
        page.pack_start (table, False, False, 0)

        troubleshooter.new_page (page, self)

    def display (self):
        troubleshooter = self.troubleshooter
        queue = troubleshooter.answers['cups_queue']
        cups.setServer ('')
        c = cups.Connection ()
        dict = c.getPrinterAttributes (queue)

        state_message = dict['printer-state-message']
        self.state_message_label.set_text (state_message)

        state_reasons_list = dict['printer-state-reasons']
        if type (state_reasons_list) == unicode:
            state_reasons_list = [state_reasons_list]

        state_reasons = reduce (lambda x, y: x + "\n" + y,
                                state_reasons_list)
        self.state_reasons_label.set_text (state_reasons)
        if state_message == '' and state_reasons == 'none':
            return False

        # If this screen has been show before, don't show it again if
        # nothing changed.
        if troubleshooter.answers.has_key ('printer-state-message'):
            if (troubleshooter.answers['printer-state-message'] ==
                state_message and
                troubleshooter.answers['printer-state-reasons'] ==
                state_reasons):
                return False

        return True

    def collect_answer (self):
        return { 'printer-state-message': self.state_message_label.get_text (),
                 'printer-state-reasons': self.state_reasons_label.get_text () }

class QueueRejectingJobs(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Queue rejecting jobs?")
        solution = gtk.VBox ()
        solution.set_border_width (12)
        solution.set_spacing (12)
        label = gtk.Label ('<span weight="bold" size="larger">' +
                           _("Queue Rejecting Jobs") + '</span>')
        label.set_alignment (0, 0)
        label.set_use_markup (True)
        solution.pack_start (label, False, False, 0)
        self.label = gtk.Label ()
        self.label.set_alignment (0, 0)
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
        Question.__init__ (self, troubleshooter, "Queue not enabled?")
        self.label = gtk.Label ()
        solution = gtk.VBox ()
        self.label.set_line_wrap (True)
        self.label.set_alignment (0, 0)
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

        reason = queue['printer-state-message']
        if reason:
            reason = _("The reason given is: `%s'.") % reason
        else:
            reason = _("This may be due to the printer being disconnected or "
                       "switched off.")

        text = ('<span weight="bold" size="larger">' +
                _("Queue Not Enabled") + '</span>\n\n' +
                _("The queue `%s' is not enabled.") %
                troubleshooter.answers['cups_queue'] + ' ' +
                reason + '\n\n' +
                _("To enable it, select the `Enabled' checkbox in the "
                  "`Policies' tab for the printer in the printer "
                  "administration tool."))

        text += ' ' + TEXT_start_print_admin_tool

        self.label.set_markup (text)
        return True

    def can_click_forward (self):
        return False

class ServerFirewalled(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Server firewalled")
        page = self.initial_vbox (_("Check Server Firewall"),
                                   _("It is not possible to connect to the "
                                     "server."))
        self.label = gtk.Label ()
        self.label.set_alignment (0, 0)
        self.label.set_line_wrap (True)
        page.pack_start (self.label)
        troubleshooter.new_page (page, self)

    def display (self):
        answers = self.troubleshooter.answers
        if (answers.get ('cups_queue_listed', False) and
            answers.has_key ('remote_server_connect_ipp') and
            answers['remote_server_connect_ipp'] == False):
            self.label.set_text (_("Please check to see if a firewall or "
                                   "router configuration is blocking TCP "
                                   "port %d on server `%s'.")
                                 % (answers['remote_server_port'],
                                    answers['remote_server_try_connect']))
            return True
        return False

    def can_click_forward (self):
        return False

class CheckPrinterSanity(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Check printer sanity")
        troubleshooter.new_page (gtk.Label (), self)
        QueueNotEnabled (self.troubleshooter)
        QueueRejectingJobs (self.troubleshooter)
        PrinterStateReasons (self.troubleshooter)
        CheckNetworkPrinterSanity (self.troubleshooter)
        ServerFirewalled (self.troubleshooter)
        PrintTestPage (self.troubleshooter)
        # Look at the state reasons after printing the test page.
        PrinterStateReasons (self.troubleshooter)

    def display (self):
        # Collect information useful for the various checks.

        self.answers = {}

        # Find out if this is a printer or a class.
        answers = self.troubleshooter.answers
        name = answers['cups_queue']
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

        if self.answers.has_key ('cups_printer_dict'):
            uri = self.answers['cups_printer_dict']['device-uri']
            (scheme, rest) = urllib.splittype (uri)
            self.answers['cups_device_uri_scheme'] = scheme
            if scheme in ["ipp"]:
                (hostport, rest) = urllib.splithost (rest)
                (host, port) = urllib.splitnport (hostport, defport=631)
                self.answers['remote_server_name'] = host
                self.answers['remote_server_port'] = port

        return False

    def collect_answer (self):
        return self.answers

###

class ChoosePrinter(Question):
    def __init__ (self, troubleshooter):
        # First question: which printer? (page 1)
        Question.__init__ (self, troubleshooter, "Choose printer")
        page1 = self.initial_vbox (_("Choose Printer"),
                                   _("Please select the printer you are "
                                     "trying to use from the list below. "
                                     "If it does not appear in the list, "
                                     "select 'Not listed'."))
        tv = gtk.TreeView ()
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
        troubleshooter.new_page (page1, self)

    def display (self):
        model = gtk.ListStore (gobject.TYPE_STRING,
                               gobject.TYPE_STRING,
                               gobject.TYPE_STRING,
                               gobject.TYPE_PYOBJECT)
        self.treeview.set_model (model)
        iter = model.append (None)
        model.set (iter, 0, _("Not listed"), 1, '', 2, '', 3, None)

        try:
            cups.setServer ('')
            c = cups.Connection ()
            dests = c.getDests ()
            printers = None
            dests_list = []
            for (name, instance), dest in dests.iteritems ():
                if name == None:
                    continue

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

            dests_list.sort (lambda x, y: cmp (x[0], y[0]))
            for queue, location, info, dest in dests_list:
                iter = model.append (None)
                model.set (iter, 0, queue, 1, location, 2, info, 3, dest)

        except cups.HTTPError:
            pass
        except cups.IPPError:
            pass
        except RuntimeError:
            pass

        return True

    def cursor_changed (self, widget, handler):
        model, iter = widget.get_selection ().get_selected ()
        if iter != None:
            dest = model.get_value (iter, 3)
            self.troubleshooter.no_more_questions (self)
            if dest == None:
                # Printer not listed.
                PrinterNotListed (self.troubleshooter)
                Shrug (self.troubleshooter)
            else:
                CheckPrinterSanity (self.troubleshooter)
                CheckNetworkPrinterSanity (self.troubleshooter)
                Shrug (self.troubleshooter)

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
            class enum_dests:
                def __init__ (self, model):
                    self.dests = []
                    model.foreach (self.each, None)

                def each (self, model, path, iter, user_data):
                    dest = model.get_value (iter, 3)
                    if dest:
                        self.dests.append ((dest.name, dest.instance))

            return { 'cups_queue_listed': False,
                     'cups_dests_available': enum_dests (model).dests }
        else:
            return { 'cups_queue_listed': True,
                     'cups_dest': dest,
                     'cups_queue': dest.name,
                     'cups_instance': dest.instance }

def run (quitfn=None):
    troubleshooter = Troubleshooter (quitfn)
    Welcome (troubleshooter)
    ChoosePrinter (troubleshooter)
    return troubleshooter

if __name__ == "__main__":
    import sys, getopt
    debug = 0
    try:
        opts, args = getopt.gnu_getopt (sys.argv[1:], '',
                                        ['debug'])
        for opt, optarg in opts:
            if opt == '--debug':
                debug = 1
    except getopt.GetoptError:
        pass

    run (gtk.main_quit)
    gtk.main ()

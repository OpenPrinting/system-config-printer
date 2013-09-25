#!/usr/bin/python

## system-config-printer

## Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013 Red Hat, Inc.
## Authors:
##  Tim Waugh <twaugh@redhat.com>
##  Florian Festi <ffesti@redhat.com>

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

# config is generated from config.py.in by configure
import config

import os, tempfile
from gi.repository import Gtk
import cups
import locale
import gettext
gettext.install(domain=config.PACKAGE, localedir=config.localedir, unicode=True)

import cupshelpers, options
from gi.repository import GObject
from gi.repository import GLib
from gui import GtkGUI
from optionwidgets import OptionWidget
from debug import *
import authconn
from errordialogs import *
import gtkinklevel
import ppdcache
import statereason
import monitor
import newprinter
from newprinter import busy, ready

import ppdippstr
pkgdata = config.pkgdatadir

def CUPS_server_hostname ():
    host = cups.getServer ()
    if host[0] == '/':
        return 'localhost'
    return host

def on_delete_just_hide (widget, event):
    widget.hide ()
    return True # stop other handlers

class PrinterPropertiesDialog(GtkGUI):

    __gsignals__ = {
        'destroy':       ( GObject.SIGNAL_RUN_LAST, None, ()),
        'dialog-closed': ( GObject.SIGNAL_RUN_LAST, None, ()),
        }

    printer_states = { cups.IPP_PRINTER_IDLE:
                           _("Idle"),
                       cups.IPP_PRINTER_PROCESSING:
                           _("Processing"),
                       cups.IPP_PRINTER_BUSY:
                           _("Busy"),
                       cups.IPP_PRINTER_STOPPED:
                           _("Stopped") }

    def __init__(self):
        GObject.GObject.__init__ (self)

        try:
            self.language = locale.getlocale(locale.LC_MESSAGES)
            self.encoding = locale.getlocale(locale.LC_CTYPE)
        except:
            nonfatalException()
            os.environ['LC_ALL'] = 'C'
            locale.setlocale (locale.LC_ALL, "")
            self.language = locale.getlocale(locale.LC_MESSAGES)
            self.encoding = locale.getlocale(locale.LC_CTYPE)

        self.parent = None
        self.printer = self.ppd = None
        self.conflicts = set() # of options
        self.changed = set() # of options
        self.signal_ids = dict()

        # WIDGETS
        # =======
        self.updating_widgets = False
        self.getWidgets({"PrinterPropertiesDialog":
                             ["PrinterPropertiesDialog",
                              "tvPrinterProperties",
                              "btnPrinterPropertiesCancel",
                              "btnPrinterPropertiesOK",
                              "btnPrinterPropertiesApply",
                              "btnPrinterPropertiesClose",
                              "ntbkPrinter",
                              "entPDescription",
                              "entPLocation",
                              "entPMakeModel",
                              "lblPMakeModel2",
                              "entPState",
                              "entPDevice",
                              "lblPDevice2",
                              "btnSelectDevice",
                              "btnChangePPD",
                              "chkPEnabled",
                              "chkPAccepting",
                              "chkPShared",
                              "lblNotPublished",
                              "btnPrintTestPage",
                              "btnSelfTest",
                              "btnCleanHeads",
                              "btnConflict",

                              "cmbPStartBanner",
                              "cmbPEndBanner",
                              "cmbPErrorPolicy",
                              "cmbPOperationPolicy",

                              "rbtnPAllow",
                              "rbtnPDeny",
                              "tvPUsers",
                              "entPUser",
                              "btnPAddUser",
                              "btnPDelUser",

                              "lblPInstallOptions",
                              "swPInstallOptions",
                              "vbPInstallOptions",
                              "swPOptions",
                              "lblPOptions",
                              "vbPOptions",
                              "algnClassMembers",
                              "vbClassMembers",
                              "lblClassMembers",
                              "tvClassMembers",
                              "tvClassNotMembers",
                              "btnClassAddMember",
                              "btnClassDelMember",
                              "btnRefreshMarkerLevels",
                              "tvPrinterStateReasons",
                              "ntbkPrinterStateReasons",

                              # Job options
                              "sbJOCopies", "btnJOResetCopies",
                              "cmbJOOrientationRequested", "btnJOResetOrientationRequested",
                              "cbJOFitplot", "btnJOResetFitplot",
                              "cmbJONumberUp", "btnJOResetNumberUp",
                              "cmbJONumberUpLayout", "btnJOResetNumberUpLayout",
                              "sbJOBrightness", "btnJOResetBrightness",
                              "cmbJOFinishings", "btnJOResetFinishings",
                              "sbJOJobPriority", "btnJOResetJobPriority",
                              "cmbJOMedia", "btnJOResetMedia",
                              "cmbJOSides", "btnJOResetSides",
                              "cmbJOHoldUntil", "btnJOResetHoldUntil",
                              "cmbJOOutputOrder", "btnJOResetOutputOrder",
                              "cmbJOPrintQuality", "btnJOResetPrintQuality",
                              "cmbJOPrinterResolution",
                              "btnJOResetPrinterResolution",
                              "cmbJOOutputBin", "btnJOResetOutputBin",
                              "cbJOMirror", "btnJOResetMirror",
                              "sbJOScaling", "btnJOResetScaling",
                              "sbJOSaturation", "btnJOResetSaturation",
                              "sbJOHue", "btnJOResetHue",
                              "sbJOGamma", "btnJOResetGamma",
                              "sbJOCpi", "btnJOResetCpi",
                              "sbJOLpi", "btnJOResetLpi",
                              "sbJOPageLeft", "btnJOResetPageLeft",
                              "sbJOPageRight", "btnJOResetPageRight",
                              "sbJOPageTop", "btnJOResetPageTop",
                              "sbJOPageBottom", "btnJOResetPageBottom",
                              "cbJOPrettyPrint", "btnJOResetPrettyPrint",
                              "cbJOWrap", "btnJOResetWrap",
                              "sbJOColumns", "btnJOResetColumns",
                              "tblJOOther",
                              "entNewJobOption", "btnNewJobOption",

                              # Marker levels
                              "vboxMarkerLevels",
                              "btnRefreshMarkerLevels"]},

                        domain=config.PACKAGE)


        self.dialog = self.PrinterPropertiesDialog

        # Don't let delete-event destroy the dialog.
        self.dialog.connect ("delete-event", self.on_delete)

        # Printer properties combo boxes
        for combobox in [self.cmbPStartBanner,
                         self.cmbPEndBanner,
                         self.cmbPErrorPolicy,
                         self.cmbPOperationPolicy]:
            cell = Gtk.CellRendererText ()
            combobox.clear ()
            combobox.pack_start (cell, True)
            combobox.add_attribute (cell, 'text', 0)

        btn = self.btnRefreshMarkerLevels
        btn.connect ("clicked", self.on_btnRefreshMarkerLevels_clicked)

        # Printer state reasons list
        column = Gtk.TreeViewColumn (_("Message"))
        icon = Gtk.CellRendererPixbuf ()
        column.pack_start (icon, False)
        text = Gtk.CellRendererText ()
        column.pack_start (text, False)
        column.set_cell_data_func (icon, self.set_printer_state_reason_icon, None)
        column.set_cell_data_func (text, self.set_printer_state_reason_text, None)
        column.set_resizable (True)
        self.tvPrinterStateReasons.append_column (column)
        selection = self.tvPrinterStateReasons.get_selection ()
        selection.set_mode (Gtk.SelectionMode.NONE)
        store = Gtk.ListStore (int, str)
        self.tvPrinterStateReasons.set_model (store)
        self.PrinterPropertiesDialog.connect ("delete-event",
                                              on_delete_just_hide)

        self.static_tabs = 3

        # setup some lists
        for name, treeview in (
            (_("Members of this class"), self.tvClassMembers),
            (_("Others"), self.tvClassNotMembers),
            (_("Users"), self.tvPUsers),
            ):

            model = Gtk.ListStore(str)
            cell = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(name, cell, text=0)
            treeview.set_model(model)
            treeview.append_column(column)
            treeview.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)

        # Printer Properties dialog
        self.dialog.connect ('response', self.printer_properties_response)

        # Printer Properties tree view
        col = Gtk.TreeViewColumn ('', Gtk.CellRendererText (), markup=0)
        self.tvPrinterProperties.append_column (col)
        sel = self.tvPrinterProperties.get_selection ()
        sel.connect ('changed', self.on_tvPrinterProperties_selection_changed)
        sel.set_mode (Gtk.SelectionMode.SINGLE)

        # Job Options widgets.
        for (widget,
             opts) in [(self.cmbJOOrientationRequested,
                        [[_("Portrait (no rotation)")],
                         [_("Landscape (90 degrees)")],
                         [_("Reverse landscape (270 degrees)")],
                         [_("Reverse portrait (180 degrees)")]]),

                       (self.cmbJONumberUp,
                        [["1"], ["2"], ["4"], ["6"], ["9"], ["16"]]),

                       (self.cmbJONumberUpLayout,
                        [[_("Left to right, top to bottom")],
                         [_("Left to right, bottom to top")],
                         [_("Right to left, top to bottom")],
                         [_("Right to left, bottom to top")],
                         [_("Top to bottom, left to right")],
                         [_("Top to bottom, right to left")],
                         [_("Bottom to top, left to right")],
                         [_("Bottom to top, right to left")]]),

                       (self.cmbJOFinishings,
  # See section 4.2.6 of this document for explanation of finishing types:
  # ftp://ftp.pwg.org/pub/pwg/candidates/cs-ippfinishings10-20010205-5100.1.pdf
                        [[_("None")],
                         [_("Staple")],
                         [_("Punch")],
                         [_("Cover")],
                         [_("Bind")],
                         [_("Saddle stitch")],
                         [_("Edge stitch")],
                         [_("Fold")],
                         [_("Trim")],
                         [_("Bale")],
                         [_("Booklet maker")],
                         [_("Job offset")],
                         [_("Staple (top left)")],
                         [_("Staple (bottom left)")],
                         [_("Staple (top right)")],
                         [_("Staple (bottom right)")],
                         [_("Edge stitch (left)")],
                         [_("Edge stitch (top)")],
                         [_("Edge stitch (right)")],
                         [_("Edge stitch (bottom)")],
                         [_("Staple dual (left)")],
                         [_("Staple dual (top)")],
                         [_("Staple dual (right)")],
                         [_("Staple dual (bottom)")],
                         [_("Bind (left)")],
                         [_("Bind (top)")],
                         [_("Bind (right)")],
                         [_("Bind (bottom)")]]),

                       (self.cmbJOMedia, []),

                       (self.cmbJOSides,
                        [[_("One-sided")],
                         [_("Two-sided (long edge)")],
                         [_("Two-sided (short edge)")]]),

                       (self.cmbJOHoldUntil, []),

                       (self.cmbJOOutputOrder,
                        [[_("Normal")],
                         [_("Reverse")]]),

                       (self.cmbJOPrintQuality,
                        [[_("Draft")],
                         [_("Normal")],
                         [_("High")]]),

                       (self.cmbJOOutputBin, []),
                       ]:
            model = Gtk.ListStore (str)
            for row in opts:
                model.append (row=row)

            cell = Gtk.CellRendererText ()
            widget.pack_start (cell, True)
            widget.add_attribute (cell, 'text', 0)
            widget.set_model (model)

        opts = [ options.OptionAlwaysShown ("copies", int, 1,
                                            self.sbJOCopies,
                                            self.btnJOResetCopies),

                 options.OptionAlwaysShownSpecial \
                 ("orientation-requested", int, 3,
                  self.cmbJOOrientationRequested,
                  self.btnJOResetOrientationRequested,
                  combobox_map = [3, 4, 5, 6],
                  special_choice=_("Automatic rotation")),

                 options.OptionAlwaysShown ("fitplot", bool, False,
                                            self.cbJOFitplot,
                                            self.btnJOResetFitplot),

                 options.OptionAlwaysShown ("number-up", int, 1,
                                            self.cmbJONumberUp,
                                            self.btnJOResetNumberUp,
                                            combobox_map=[1, 2, 4, 6, 9, 16],
                                            use_supported = True),

                 options.OptionAlwaysShown ("number-up-layout", str, "lrtb",
                                            self.cmbJONumberUpLayout,
                                            self.btnJOResetNumberUpLayout,
                                            combobox_map = [ "lrtb",
                                                             "lrbt",
                                                             "rltb",
                                                             "rlbt",
                                                             "tblr",
                                                             "tbrl",
                                                             "btlr",
                                                             "btrl" ]),

                 options.OptionAlwaysShown ("brightness", int, 100,
                                            self.sbJOBrightness,
                                            self.btnJOResetBrightness),

                 options.OptionAlwaysShown ("finishings", int, 3,
                                            self.cmbJOFinishings,
                                            self.btnJOResetFinishings,
                                            combobox_map = [ 3, 4, 5, 6,
                                                             7, 8, 9, 10,
                                                             11, 12, 13, 14,
                                                             20, 21, 22, 23,
                                                             24, 25, 26, 27,
                                                             28, 29, 30, 31,
                                                             50, 51, 52, 53 ],
                                            use_supported = True),

                 options.OptionAlwaysShown ("job-priority", int, 50,
                                            self.sbJOJobPriority,
                                            self.btnJOResetJobPriority),

                 options.OptionAlwaysShown ("media", str,
                                            "A4", # This is the default for
                                                  # when media-default is
                                                  # not supplied by the IPP
                                                  # server.  Fortunately it
                                                  # is a mandatory attribute.
                                            self.cmbJOMedia,
                                            self.btnJOResetMedia,
                                            use_supported = True),

                 options.OptionAlwaysShown ("sides", str, "one-sided",
                                            self.cmbJOSides,
                                            self.btnJOResetSides,
                                            combobox_map =
                                            [ "one-sided",
                                              "two-sided-long-edge",
                                              "two-sided-short-edge" ],
                                            use_supported = True),

                 options.OptionAlwaysShown ("job-hold-until", str,
                                            "no-hold",
                                            self.cmbJOHoldUntil,
                                            self.btnJOResetHoldUntil,
                                            use_supported = True),

                 options.OptionAlwaysShown ("outputorder", str,
                                            "normal",
                                            self.cmbJOOutputOrder,
                                            self.btnJOResetOutputOrder,
                                            combobox_map =
                                            [ "normal",
                                              "reverse" ]),

                 options.OptionAlwaysShown ("print-quality", int, 3,
                                            self.cmbJOPrintQuality,
                                            self.btnJOResetPrintQuality,
                                            combobox_map = [ 3, 4, 5 ],
                                            use_supported = True),

                 options.OptionAlwaysShown ("printer-resolution",
                                            options.IPPResolution,
                                            options.IPPResolution((300,300,3)),
                                            self.cmbJOPrinterResolution,
                                            self.btnJOResetPrinterResolution,
                                            use_supported = True),

                 options.OptionAlwaysShown ("output-bin", str,
                                            "face-up",
                                            self.cmbJOOutputBin,
                                            self.btnJOResetOutputBin,
                                            use_supported = True),

                 options.OptionAlwaysShown ("mirror", bool, False,
                                            self.cbJOMirror,
                                            self.btnJOResetMirror),

                 options.OptionAlwaysShown ("scaling", int, 100,
                                            self.sbJOScaling,
                                            self.btnJOResetScaling),

                 options.OptionAlwaysShown ("saturation", int, 100,
                                            self.sbJOSaturation,
                                            self.btnJOResetSaturation),

                 options.OptionAlwaysShown ("hue", int, 0,
                                            self.sbJOHue,
                                            self.btnJOResetHue),

                 options.OptionAlwaysShown ("gamma", int, 1000,
                                            self.sbJOGamma,
                                            self.btnJOResetGamma),

                 options.OptionAlwaysShown ("cpi", float, 10.0,
                                            self.sbJOCpi, self.btnJOResetCpi),

                 options.OptionAlwaysShown ("lpi", float, 6.0,
                                            self.sbJOLpi, self.btnJOResetLpi),

                 options.OptionAlwaysShown ("page-left", int, 0,
                                            self.sbJOPageLeft,
                                            self.btnJOResetPageLeft),

                 options.OptionAlwaysShown ("page-right", int, 0,
                                            self.sbJOPageRight,
                                            self.btnJOResetPageRight),

                 options.OptionAlwaysShown ("page-top", int, 0,
                                            self.sbJOPageTop,
                                            self.btnJOResetPageTop),

                 options.OptionAlwaysShown ("page-bottom", int, 0,
                                            self.sbJOPageBottom,
                                            self.btnJOResetPageBottom),

                 options.OptionAlwaysShown ("prettyprint", bool, False,
                                            self.cbJOPrettyPrint,
                                            self.btnJOResetPrettyPrint),

                 options.OptionAlwaysShown ("wrap", bool, False, self.cbJOWrap,
                                            self.btnJOResetWrap),

                 options.OptionAlwaysShown ("columns", int, 1,
                                            self.sbJOColumns,
                                            self.btnJOResetColumns),
                 ]
        self.job_options_widgets = {}
        self.job_options_buttons = {}
        for option in opts:
            self.job_options_widgets[option.widget] = option
            self.job_options_buttons[option.button] = option

        self._monitor = None
        self._ppdcache = None
        self.connect_signals ()
        debugprint ("+%s" % self)

    def __del__ (self):
        debugprint ("-%s" % self)
        del self._monitor

    def _connect (self, collection, obj, name, handler):
        c = self.signal_ids.get (collection, [])
        c.append ((obj, obj.connect (name, handler)))
        self.signal_ids[collection] = c

    def _disconnect (self, collection=None):
        if collection:
            collection = [collection]
        else:
            collection = self.signal_ids.keys ()

        for coll in collection:
            if self.signal_ids.has_key (coll):
                for (obj, signal_id) in self.signal_ids[coll]:
                    obj.disconnect (signal_id)

                del self.signal_ids[coll]

    def do_destroy (self):
        if self.PrinterPropertiesDialog:
            self.PrinterPropertiesDialog.destroy ()
            self.PrinterPropertiesDialog = None

    def destroy (self):
        debugprint ("DESTROY: %s" % self)
        self._disconnect ()
        self.ppd = None
        self.ppd_local = None
        self.printer = None
        self.emit ('destroy')

    def set_monitor (self, monitor):
        self._monitor = monitor
        if not monitor:
            return

        self._monitor.connect ('printer-event', self.on_printer_event)
        self._monitor.connect ('printer-removed', self.on_printer_removed)
        self._monitor.connect ('state-reason-added', self.on_state_reason_added)
        self._monitor.connect ('state-reason-removed',
                               self.on_state_reason_removed)
        self._monitor.connect ('cups-connection-error',
                               self.on_cups_connection_error)

    def show (self, name, host=None, encryption=None, parent=None):
        self.parent = parent
        self._host = host
        self._encryption = encryption
        if not host:
            self._host = cups.getServer()
        if not encryption:
            self._encryption = cups.getEncryption ()

        if self._monitor == None:
            self.set_monitor (monitor.Monitor (monitor_jobs=False))

        self._ppdcache = self._monitor.get_ppdcache ()

        self._disconnect ("newPrinterGUI")
        self.newPrinterGUI = newprinter.NewPrinterGUI ()
        self._connect ("newPrinterGUI", self.newPrinterGUI,
                       "printer-modified", self.on_printer_modified)
        self._connect ("newPrinterGUI", self.newPrinterGUI,
                       "dialog-canceled", self.on_printer_not_modified)
        if parent:
            self.dialog.set_transient_for (parent)

        self.load (name, host=host, encryption=encryption, parent=parent)
        if not self.printer:
            return

        for button in [self.btnPrinterPropertiesCancel,
                       self.btnPrinterPropertiesOK,
                       self.btnPrinterPropertiesApply]:
            if self.printer.discovered:
                button.hide ()
            else:
                button.show ()
        if self.printer.discovered:
            self.btnPrinterPropertiesClose.show ()
        else:
            self.btnPrinterPropertiesClose.hide ()
        self.setDataButtonState ()
        self.btnPrintTestPage.set_tooltip_text(_("CUPS test page"))
        self.btnSelfTest.set_tooltip_text(_("Typically shows whether all jets "
                                            "on a print head are functioning "
                                            "and that the print feed mechanisms"
                                            " are working properly."))
        treeview = self.tvPrinterProperties
        treeview.set_cursor (Gtk.TreePath(), None, False)
        host = CUPS_server_hostname ()
        self.dialog.set_title (_("Printer Properties - "
                                 "'%s' on %s") % (name, host))
        self.dialog.show ()

    def printer_properties_response (self, dialog, response):
        if not self.printer:
            response = Gtk.ResponseType.CANCEL

        if response == Gtk.ResponseType.REJECT:
            # The Conflict button was pressed.
            message = _("There are conflicting options.\n"
                        "Changes can only be applied after\n"
                        "these conflicts are resolved.")
            message += "\n\n"
            for option in self.conflicts:
                message += option.option.text + "\n"

            dialog = Gtk.MessageDialog(self.dialog,
                                       Gtk.DialogFlags.DESTROY_WITH_PARENT |
                                       Gtk.DialogFlags.MODAL,
                                       Gtk.MessageType.WARNING,
                                       Gtk.ButtonsType.CLOSE,
                                       message)
            dialog.run()
            dialog.destroy()
            return

        if (response == Gtk.ResponseType.OK or
            response == Gtk.ResponseType.APPLY):
            if (response == Gtk.ResponseType.OK and len (self.changed) == 0):
                failed = False
            else:
                failed = self.save_printer (self.printer)

        if response == Gtk.ResponseType.APPLY and not failed:
            try:
                self.load (self.printer.name)
            except:
                pass

            self.setDataButtonState ()

        if ((response == Gtk.ResponseType.OK and not failed) or
            response == Gtk.ResponseType.CANCEL):
            self.ppd = None
            self.ppd_local = None
            self.printer = None
            dialog.hide ()
            self.emit ('dialog-closed')

            if self.newPrinterGUI.NewPrinterWindow.get_property ("visible"):
                self.newPrinterGUI.on_NPCancel (None)

    # Data handling

    def on_delete(self, dialog, event):
        self.printer_properties_response (dialog, Gtk.ResponseType.CANCEL)

    def on_printer_changed(self, widget):
        if isinstance(widget, Gtk.CheckButton):
            value = widget.get_active()
        elif isinstance(widget, Gtk.Entry):
            value = widget.get_text()
        elif isinstance(widget, Gtk.RadioButton):
            value = widget.get_active()
        elif isinstance(widget, Gtk.ComboBox):
            model = widget.get_model ()
            iter = widget.get_active_iter()
            value = model.get_value (iter, 1)
        else:
            raise ValueError, "Widget type not supported (yet)"

        p = self.printer
        old_values = {
            self.entPDescription : p.info,
            self.entPLocation : p.location,
            self.entPDevice : p.device_uri,
            self.chkPEnabled : p.enabled,
            self.chkPAccepting : not p.rejecting,
            self.chkPShared : p.is_shared,
            self.cmbPStartBanner : p.job_sheet_start,
            self.cmbPEndBanner : p.job_sheet_end,
            self.cmbPErrorPolicy : p.error_policy,
            self.cmbPOperationPolicy : p.op_policy,
            self.rbtnPAllow: p.default_allow,
            }

        old_value = old_values[widget]

        if type (old_value) == unicode:
            old_value = old_value.encode ('utf-8')

        if old_value == value:
            self.changed.discard(widget)
        else:
            self.changed.add(widget)
        self.setDataButtonState()

    def option_changed(self, option):
        if option.is_changed():
            self.changed.add(option)
        else:
            self.changed.discard(option)

        if option.conflicts:
            self.conflicts.add(option)
        else:
            self.conflicts.discard(option)
        self.setDataButtonState()

        if (self.option_manualfeed and self.option_inputslot and
            option == self.option_manualfeed):
            if option.get_current_value() == "True":
                self.option_inputslot.disable ()
            else:
                self.option_inputslot.enable ()

    # Access control
    def getPUsers(self):
        """return list of usernames from the GUI"""
        model = self.tvPUsers.get_model()
        result = []
        model.foreach(lambda model, path, iter, data:
                      result.append(model.get(iter, 0)[0]), None)
        result.sort()
        return result

    def setPUsers(self, users):
        """write list of usernames inot the GUI"""
        model = self.tvPUsers.get_model()
        model.clear()
        for user in users:
            model.append((user,))

        self.on_entPUser_changed(self.entPUser)
        self.on_tvPUsers_cursor_changed(self.tvPUsers)

    def checkPUsersChanged(self):
        """check if users in GUI and printer are different
        and set self.changed"""
        if not self.printer:
            return

        if self.getPUsers() != self.printer.except_users:
            self.changed.add(self.tvPUsers)
        else:
            self.changed.discard(self.tvPUsers)

        self.on_tvPUsers_cursor_changed(self.tvPUsers)
        self.setDataButtonState()

    def on_btnPAddUser_clicked(self, button):
        user = self.entPUser.get_text()
        if user:
            self.tvPUsers.get_model().insert(0, (user,))
            self.entPUser.set_text("")
        self.checkPUsersChanged()

    def on_btnPDelUser_clicked(self, button):
        model, rows = self.tvPUsers.get_selection().get_selected_rows()
        rows = [Gtk.TreeRowReference.new (model, row) for row in rows]
        for row in rows:
            path = row.get_path()
            iter = model.get_iter(path)
            model.remove(iter)
        self.checkPUsersChanged()

    def on_entPUser_changed(self, widget):
        self.btnPAddUser.set_sensitive(bool(widget.get_text()))

    def on_tvPUsers_cursor_changed(self, widget):
        selection = widget.get_selection ()
        if selection == None:
            return

        model, rows = selection.get_selected_rows()
        self.btnPDelUser.set_sensitive(bool(rows))

    # Server side options
    def on_job_option_reset(self, button):
        option = self.job_options_buttons[button]
        option.reset ()
        # Remember to set this option for removal in the IPP request.
        if self.server_side_options.has_key (option.name):
            del self.server_side_options[option.name]
        if option.is_changed ():
            self.changed.add(option)
        else:
            self.changed.discard(option)
        self.setDataButtonState()

    def on_job_option_changed(self, widget):
        if not self.printer:
            return
        option = self.job_options_widgets[widget]
        option.changed ()
        if option.is_changed ():
            self.server_side_options[option.name] = option
            self.changed.add(option)
        else:
            if self.server_side_options.has_key (option.name):
                del self.server_side_options[option.name]
            self.changed.discard(option)
        self.setDataButtonState()
        # Don't set the reset button insensitive if the option hasn't
        # changed from the original value: it's still meaningful to
        # reset the option to the system default.

    def draw_other_job_options (self, editable=True):
        n = len (self.other_job_options)
        if n == 0:
            self.tblJOOther.hide()
            return

        self.tblJOOther.resize (n, 3)
        children = self.tblJOOther.get_children ()
        for child in children:
            self.tblJOOther.remove (child)
        i = 0
        for opt in self.other_job_options:
            self.tblJOOther.attach (opt.label, 0, 1, i, i + 1,
                                    xoptions=Gtk.AttachOptions.FILL,
                                    yoptions=Gtk.AttachOptions.FILL)
            opt.label.set_alignment (0.0, 0.5)
            self.tblJOOther.attach (opt.selector, 1, 2, i, i + 1,
                                    xoptions=Gtk.AttachOptions.FILL,
                                    yoptions=0)
            opt.selector.set_sensitive (editable)

            btn = Gtk.Button(stock=Gtk.STOCK_REMOVE)
            btn.connect("clicked", self.on_btnJOOtherRemove_clicked)
            btn.pyobject = opt
            btn.set_sensitive (editable)
            self.tblJOOther.attach(btn, 2, 3, i, i + 1,
                                   xoptions=0,
                                   yoptions=0)
            i += 1

        self.tblJOOther.show_all ()

    def add_job_option(self, name, value = "", supported = "", is_new=True,
                       editable=True):
        try:
            option = options.OptionWidget(name, value, supported,
                                          self.option_changed)
        except ValueError:
            # We can't deal with this option type for some reason.
            nonfatalException ()
            return

        option.is_new = is_new
        self.other_job_options.append (option)
        self.draw_other_job_options (editable=editable)
        self.server_side_options[name] = option
        if name in self.changed: # was deleted before
            option.is_new = False
        self.changed.add(option)
        self.setDataButtonState()
        if is_new:
            option.selector.grab_focus ()

    def on_btnJOOtherRemove_clicked(self, button):
        option = button.pyobject
        self.other_job_options.remove (option)
        self.draw_other_job_options ()
        if option.is_new:
            self.changed.discard(option)
        else:
            # keep name as reminder that option got deleted
            self.changed.add(option.name)
        del self.server_side_options[option.name]
        self.setDataButtonState()

    def on_btnNewJobOption_clicked(self, button):
        name = self.entNewJobOption.get_text()
        self.add_job_option(name)
        self.tblJOOther.show_all()
        self.entNewJobOption.set_text ('')
        self.btnNewJobOption.set_sensitive (False)
        self.setDataButtonState()

    def on_entNewJobOption_changed(self, widget):
        text = self.entNewJobOption.get_text()
        active = (len(text) > 0) and text not in self.server_side_options
        self.btnNewJobOption.set_sensitive(active)

    def on_entNewJobOption_activate(self, widget):
        self.on_btnNewJobOption_clicked (widget) # wrong widget but ok

    # set buttons sensitivity
    def setDataButtonState(self):
        try:
            attrs = self.printer.other_attributes
            formats = attrs.get('document-format-supported', [])
            printable = (not bool (self.changed) and
                         self.printer.enabled and
                         not self.printer.rejecting)
            try:
                formats.index ('application/postscript')
                testpage = printable
            except ValueError:
                # PostScript not accepted
                testpage = False

            self.btnPrintTestPage.set_sensitive (testpage)
            adjustable = not (self.printer.discovered or bool (self.changed))
            for button in [self.btnChangePPD,
                           self.btnSelectDevice]:
                button.set_sensitive (adjustable)

            selftest = False
            cleanheads = False
            if (printable and
                (self.printer.type & cups.CUPS_PRINTER_COMMANDS) != 0):
                try:
                    # Is the command format supported?
                    formats.index ('application/vnd.cups-command')

                    # Yes...
                    commands = attrs.get('printer-commands', [])
                    for command in commands:
                        if command == "PrintSelfTestPage":
                            selftest = True
                            if cleanheads:
                                break

                        elif command == "Clean":
                            cleanheads = True
                            if selftest:
                                break
                except ValueError:
                    # Command format not supported.
                    pass

            for cond, button in [(selftest, self.btnSelfTest),
                                 (cleanheads, self.btnCleanHeads)]:
                if cond:
                    button.show ()
                else:
                    button.hide ()
        except:
            nonfatalException()

        if self.ppd or \
           ((self.printer.remote or \
             ((self.printer.device_uri.startswith('dnssd:') or \
               self.printer.device_uri.startswith('mdns:')) and \
              self.printer.device_uri.endswith('/cups'))) and not \
            self.printer.discovered):
            self.btnPrintTestPage.show ()
        else:
            self.btnPrintTestPage.hide ()

        installablebold = False
        optionsbold = False
        if self.conflicts:
            debugprint ("Conflicts detected")
            self.btnConflict.show()
            for option in self.conflicts:
                if option.tab_label.get_text () == self.lblPInstallOptions.get_text ():
                    installablebold = True
                else:
                    optionsbold = True
        else:
            self.btnConflict.hide()
        installabletext = _("Installable Options")
        optionstext = _("Printer Options")
        if installablebold:
            installabletext = "<b>%s</b>" % installabletext
        if optionsbold:
            optionstext = "<b>%s</b>" % optionstext
        self.lblPInstallOptions.set_markup (installabletext)
        self.lblPOptions.set_markup (optionstext)

        store = self.tvPrinterProperties.get_model ()
        if store:
            for n in range (self.ntbkPrinter.get_n_pages ()):
                page = self.ntbkPrinter.get_nth_page (n)
                label = self.ntbkPrinter.get_tab_label (page).get_text ()
                try:
                    if label == self.lblPInstallOptions.get_text():
                        iter = store.get_iter ((n,))
                        store.set_value (iter, 0, installabletext)
                    elif label == self.lblPOptions.get_text ():
                        iter = store.get_iter ((n,))
                        store.set_value (iter, 0, optionstext)
                except ValueError:
                    # If we get here, the store has not yet been set
                    # up (trac #111).
                    pass

        self.btnPrinterPropertiesApply.set_sensitive (len (self.changed) > 0 and
                                                      not self.conflicts)
        self.btnPrinterPropertiesOK.set_sensitive (not self.conflicts)

    def save_printer(self, printer, saveall=False, parent=None):
        if parent == None:
            parent = self.dialog
        class_deleted = False
        name = printer.name
        if isinstance (name, bytes):
            name = name.decode ('utf-8')

        if printer.is_class:
            self.cups._begin_operation (_("modifying class %s") % name)
        else:
            self.cups._begin_operation (_("modifying printer %s") % name)

        try:
            if not printer.is_class and self.ppd:
                self.getPrinterSettings()
                if self.ppd.nondefaultsMarked() or saveall:
                    self.cups.addPrinter(name, ppd=self.ppd)

            if printer.is_class:
                # update member list
                new_members = newprinter.getCurrentClassMembers(self.tvClassMembers)
                if not new_members:
                    dialog = Gtk.MessageDialog(
                        flags=0, type=Gtk.MessageType.WARNING,
                        buttons=Gtk.ButtonsType.NONE,
                        message_format=_("This will delete this class!"))
                    dialog.format_secondary_text(_("Proceed anyway?"))
                    dialog.add_buttons (Gtk.STOCK_CANCEL, Gtk.ResponseType.NO,
                                        Gtk.STOCK_DELETE, Gtk.ResponseType.YES)
                    result = dialog.run()
                    dialog.destroy()
                    if result==Gtk.ResponseType.NO:
                        self.cups._end_operation ()
                        return True
                    class_deleted = True

                # update member list
                old_members = printer.class_members[:]

                for member in new_members:
                    if member in old_members:
                        old_members.remove(member)
                    else:
                        self.cups.addPrinterToClass(member, name)
                for member in old_members:
                    self.cups.deletePrinterFromClass(member, name)

            location = self.entPLocation.get_text().decode ('utf-8')
            info = self.entPDescription.get_text().decode ('utf-8')
            device_uri = self.entPDevice.get_text().decode ('utf-8')

            enabled = self.chkPEnabled.get_active()
            accepting = self.chkPAccepting.get_active()
            shared = self.chkPShared.get_active()

            if info!=printer.info or saveall:
                self.cups.setPrinterInfo(name, info)
            if location!=printer.location or saveall:
                self.cups.setPrinterLocation(name, location)
            if (not printer.is_class and
                (device_uri!=printer.device_uri or saveall)):
                self.cups.setPrinterDevice(name, device_uri)

            if enabled != printer.enabled or saveall:
                printer.setEnabled(enabled)
            if accepting == printer.rejecting or saveall:
                printer.setAccepting(accepting)
            if shared != printer.is_shared or saveall:
                printer.setShared(shared)

            def get_combo_value (cmb):
                model = cmb.get_model ()
                iter = cmb.get_active_iter ()
                return model.get_value (iter, 1)

            job_sheet_start = get_combo_value (self.cmbPStartBanner)
            job_sheet_end = get_combo_value (self.cmbPEndBanner)
            error_policy = get_combo_value (self.cmbPErrorPolicy)
            op_policy = get_combo_value (self.cmbPOperationPolicy)

            if (job_sheet_start != printer.job_sheet_start or
                job_sheet_end != printer.job_sheet_end) or saveall:
                printer.setJobSheets(job_sheet_start, job_sheet_end)
            if error_policy != printer.error_policy or saveall:
                printer.setErrorPolicy(error_policy)
            if op_policy != printer.op_policy or saveall:
                printer.setOperationPolicy(op_policy)

            default_allow = self.rbtnPAllow.get_active()
            except_users = self.getPUsers()

            if (default_allow != printer.default_allow or
                except_users != printer.except_users) or saveall:
                printer.setAccess(default_allow, except_users)

            for option in printer.attributes:
                if option not in self.server_side_options:
                    printer.unsetOption(option)
            for option in self.server_side_options.itervalues():
                if (option.is_changed() or
                    (saveall and
                     option.get_current_value () != option.get_default())):
                    debugprint ("Set %s = %s" % (option.name,
                                                 option.get_current_value()))
                    printer.setOption(option.name, option.get_current_value())

        except cups.IPPError as e:
            (e, s) = e.args
            show_IPP_Error(e, s, parent)
            self.cups._end_operation ()
            return True
        self.cups._end_operation ()
        self.changed = set() # of options

        if not self.cups._use_pk and not self.__dict__.has_key ("server_settings"):
            # We can authenticate with the server correctly at this point,
            # but we have never fetched the server settings to see whether
            # the server is publishing shared printers.  Fetch the settings
            # now so that we can update the "not published" label if necessary.
            self.cups._begin_operation (_("fetching server settings"))
            try:
                self.server_settings = self.cups.adminGetServerSettings()
            except:
                nonfatalException()

            self.cups._end_operation ()

        if not class_deleted:
            # Update our copy of the printer's settings.
            try:
                printer.getAttributes ()
                self.updatePrinterProperties ()
            except cups.IPPError:
                pass

        self._monitor.update ()
        return False

    def getPrinterSettings(self):
        #self.ppd.markDefaults()
        for option in self.options.itervalues():
            option.writeback()

    ### Printer Properties tree view signal handlers
    def on_tvPrinterProperties_selection_changed (self, selection):
        # Prevent selection from being de-selected.
        (model, iter) = selection.get_selected ()
        if iter:
            self.printer_properties_last_iter_selected = iter
        else:
            try:
                iter = self.printer_properties_last_iter_selected
            except AttributeError:
                # Not set yet.
                return

            if model.iter_is_valid (iter):
                selection.select_iter (iter)

    def on_tvPrinterProperties_cursor_changed (self, treeview):
        # Adjust notebook to reflect selected item.
        (path, column) = treeview.get_cursor ()
        if path != None:
            model = treeview.get_model ()
            iter = model.get_iter (path)
            n = model.get_value (iter, 1)
            self.ntbkPrinter.set_current_page (n)

    # print test page

    def printTestPage (self):
        self.btnPrintTestPage.clicked ()

    def on_btnPrintTestPage_clicked(self, button):
        printer = self.printer
        if not printer:
            # Printer has been deleted meanwhile
            return

        # if we have a page size specific custom test page, use it;
        # otherwise use cups' default one
        custom_testpage = None
        if self.ppd != False:
            opt = self.ppd.findOption ("PageSize")
            if opt:
                custom_testpage = os.path.join(pkgdata,
                                               'testpage-%s.ps' %
                                               opt.defchoice.lower())

        # Connect as the current user so that the test page can be managed
        # as a normal job.
        user = cups.getUser ()
        cups.setUser ('')
        try:
            c = authconn.Connection (self.parent, try_as_root=False,
                                     host=self._host,
                                     encryption=self._encryption)
        except RuntimeError as e:
            show_IPP_Error (None, e, self.parent)
            return

        job_id = None
        c._begin_operation (_("printing test page"))
        try:
            if custom_testpage and os.path.exists(custom_testpage):
                debugprint ('Printing custom test page ' + custom_testpage)
                job_id = c.printTestPage(printer.name,
                                         file=custom_testpage)
            else:
                debugprint ('Printing default test page')
                job_id = c.printTestPage(printer.name)
        except cups.IPPError as e:
            (e, msg) = e.args
            if (e == cups.IPP_NOT_AUTHORIZED and
                self._host != 'localhost' and
                self._host[0] != '/'):
                show_error_dialog (_("Not possible"),
                                   _("The remote server did not accept "
                                     "the print job, most likely "
                                     "because the printer is not "
                                     "shared."),
                                   self.parent)
            else:
                show_IPP_Error(e, msg, self.parent)

        c._end_operation ()
        cups.setUser (user)

        if job_id != None:
            show_info_dialog (_("Submitted"),
                              _("Test page submitted as job %d") % job_id,
                              parent=self.parent)

    def maintenance_command (self, command):
        printer = self.printer
        if not printer:
            # Printer has been deleted meanwhile
            return

        (tmpfd, tmpfname) = tempfile.mkstemp ()
        os.write (tmpfd, "#CUPS-COMMAND\n%s\n" % command)
        os.close (tmpfd)
        self.cups._begin_operation (_("sending maintenance command"))
        try:
            format = "application/vnd.cups-command"
            job_id = self.cups.printTestPage (printer.name,
                                              format=format,
                                              file=tmpfname,
                                              user=cups.getUser ())
            show_info_dialog (_("Submitted"),
                              _("Maintenance command submitted as "
                                "job %d") % job_id,
                              parent=self.parent)
        except cups.IPPError as e:
            (e, msg) = e.args
            if (e == cups.IPP_NOT_AUTHORIZED and
                self.printer.name != 'localhost'):
                show_error_dialog (_("Not possible"),
                                   _("The remote server did not accept "
                                     "the print job, most likely "
                                     "because the printer is not "
                                     "shared."),
                                   self.parent)
            else:
                show_IPP_Error(e, msg, self.parent)

        self.cups._end_operation ()

        os.unlink (tmpfname)

    def on_btnSelfTest_clicked(self, button):
        self.maintenance_command ("PrintSelfTestPage")

    def on_btnCleanHeads_clicked(self, button):
        self.maintenance_command ("Clean all")

    def fillComboBox(self, combobox, values, value, translationdict=None):
        if translationdict == None:
            translationdict = ppdippstr.TranslationDict ()

        model = Gtk.ListStore (str,
                               str)
        combobox.set_model (model)
        set_active = False
        for nr, val in enumerate(values):
            model.append ([(translationdict.get (val)), val])
            if val == value:
                combobox.set_active(nr)
                set_active = True

        if not set_active:
            combobox.set_active (0)

    def load (self, name, host=None, encryption=None, parent=None):
        self.changed = set() # of options
        self.options = {} # keyword -> Option object
        self.conflicts = set() # of options

        if not host:
            host = cups.getServer()
        if not encryption:
            encryption = cups.getEncryption ()

        c = authconn.Connection (parent=self.dialog,
                                 host=host,
                                 encryption=encryption)
        self.cups = c

        printer = cupshelpers.Printer (name, self.cups)
        self.printer = printer
        try:
            # CUPS 1.4
            publishing = printer.other_attributes['server-is-sharing-printers']
            self.server_is_publishing = publishing
        except KeyError:
            pass

        editable = not self.printer.discovered

        try:
            self.ppd = printer.getPPD()
            self.ppd_local = printer.getPPD()
            if self.ppd_local != False:
                self.ppd_local.localize()
        except cups.IPPError as e:
            (e, m) = e.args
            # We might get IPP_INTERNAL_ERROR if this is a memberless
            # class.
            if e != cups.IPP_INTERNAL_ERROR:
                # Some IPP error other than IPP_NOT_FOUND.
                show_IPP_Error(e, m, self.parent)

            # Treat it as a raw queue.
            self.ppd = False
        except RuntimeError as e:
            # Either the underlying cupsGetPPD2() function returned
            # NULL without setting an IPP error (so it'll be something
            # like a failed connection), or the PPD could not be parsed.
            if e.message.startswith ("ppd"):
                show_error_dialog (_("Error"),
                                   _("The PPD file for this queue "
                                     "is damaged."),
                                   self.parent)
            else:
                show_error_dialog (_("Error"),
                                   _("There was a problem connecting to "
                                     "the CUPS server."),
                                   self.parent)
            raise

        for widget in (self.entPDescription, self.entPLocation,
                       self.entPDevice):
            widget.set_editable(editable)

        for widget in (self.btnSelectDevice, self.btnChangePPD,
                       self.chkPEnabled, self.chkPAccepting, self.chkPShared,
                       self.cmbPStartBanner, self.cmbPEndBanner,
                       self.cmbPErrorPolicy, self.cmbPOperationPolicy,
                       self.rbtnPAllow, self.rbtnPDeny, self.tvPUsers,
                       self.entPUser, self.btnPAddUser, self.btnPDelUser):
            widget.set_sensitive(editable)

        # Description page
        self.entPDescription.set_text(printer.info)
        self.entPLocation.set_text(printer.location)

        uri = printer.device_uri
        self.entPDevice.set_text(uri)
        self.changed.discard(self.entPDevice)

        # Hide make/model and Device URI for classes
        for widget in (self.lblPMakeModel2, self.entPMakeModel,
                       self.btnChangePPD, self.lblPDevice2,
                       self.entPDevice, self.btnSelectDevice):
            if printer.is_class:
                widget.hide()
            else:
                widget.show()


        # Policy tab
        # ----------

        try:
            if printer.is_shared:
                if self.server_is_publishing:
                    self.lblNotPublished.hide()
                else:
                    self.lblNotPublished.show_all ()
            else:
                self.lblNotPublished.hide()
        except:
            nonfatalException()
            self.lblNotPublished.hide()

        # Job sheets
        self.cmbPStartBanner.set_sensitive(editable)
        self.cmbPEndBanner.set_sensitive(editable)

        # Policies
        self.cmbPErrorPolicy.set_sensitive(editable)
        self.cmbPOperationPolicy.set_sensitive(editable)

        # Access control
        self.entPUser.set_text("")

        # Server side options (Job options)
        self.server_side_options = {}
        for option in self.job_options_widgets.values ():
            if option.name == "media" and self.ppd:
                # Slightly special case because the 'system default'
                # (i.e. what you get when you press Reset) depends
                # on the printer's PageSize.
                opt = self.ppd.findOption ("PageSize")
                if opt:
                    option.set_default (opt.defchoice)

            option_editable = editable
            try:
                value = self.printer.attributes[option.name]
            except KeyError:
                option.reinit (None)
            else:
                try:
                    if self.printer.possible_attributes.has_key (option.name):
                        supported = self.printer.\
                                    possible_attributes[option.name][1]
                        # Set the option widget.
                        # In CUPS 1.3.x the orientation-requested-default
                        # attribute may have the value None; this means there
                        # is no value set.  This suits our needs here, as None
                        # resets the option to the system default and makes the
                        # Reset button insensitive.
                        option.reinit (value, supported=supported)
                    else:
                        option.reinit (value)

                    self.server_side_options[option.name] = option
                except:
                    nonfatalException()
                    option_editable = False
                    show_error_dialog (_("Error"),
                                       _("Option '%s' has value '%s' and "
                                         "cannot be edited.") %
                                       (option.name,
                                        value),
                                       self.parent)
            option.widget.set_sensitive (option_editable)
            if not editable:
                option.button.set_sensitive (False)
        self.other_job_options = []
        self.draw_other_job_options (editable=editable)
        for option in self.printer.attributes.keys ():
            if self.server_side_options.has_key (option):
                continue
            if option == "output-mode":
                # Not settable
                continue
            value = self.printer.attributes[option]
            if self.printer.possible_attributes.has_key (option):
                supported = self.printer.possible_attributes[option][1]
            else:
                if isinstance (value, bool):
                    supported = ["true", "false"]
                    value = str (value).lower ()
                else:
                    supported = ""
                    value = str (value)

            self.add_job_option (option, value=value,
                                 supported=supported, is_new=False,
                                 editable=editable)
        self.entNewJobOption.set_text ('')
        self.entNewJobOption.set_sensitive (editable)
        self.btnNewJobOption.set_sensitive (False)

        if printer.is_class:
            # remove InstallOptions tab
            tab_nr = self.ntbkPrinter.page_num(self.swPInstallOptions)
            if tab_nr != -1:
                self.ntbkPrinter.remove_page(tab_nr)
            self.fillClassMembers(editable)
        else:
            # real Printer
            self.fillPrinterOptions(name, editable)

        self.updateMarkerLevels()
        self.updateStateReasons()
        self.updatePrinterPropertiesTreeView()

        self.changed = set() # of options
        self.updatePrinterProperties ()
        self.setDataButtonState()

    def updatePrinterPropertiesTreeView (self):
        # Now update the tree view (which we use instead of the notebook tabs).
        store = Gtk.ListStore (str, int)
        self.ntbkPrinter.set_show_tabs (False)
        for n in range (self.ntbkPrinter.get_n_pages ()):
            page = self.ntbkPrinter.get_nth_page (n)
            label = self.ntbkPrinter.get_tab_label (page)
            iter = store.append (None)
            store.set_value (iter, 0, label.get_text ())
            store.set_value (iter, 1, n)
        sel = self.tvPrinterProperties.get_selection ()
        self.tvPrinterProperties.set_model (store)

    def updateMarkerLevels (self):
        printer = self.printer
        if not printer:
            # Printer has been deleted meanwhile
            return

        # Marker levels
        for widget in self.vboxMarkerLevels.get_children ():
            self.vboxMarkerLevels.remove (widget)

        marker_info = dict()
        num_markers = 0
        for (attr, typ) in [('marker-colors', str),
                            ('marker-names', str),
                            ('marker-types', str),
                            ('marker-levels', float)]:
            val = printer.other_attributes.get (attr, [])
            if typ != str and len (val) > 0:
                try:
                    # Can the value be coerced into the right type?
                    typ (val[0])
                except TypeError as s:
                    debugprint ("%s value not coercible to %s: %s" %
                                (attr, typ, s))
                    val = map (lambda x: 0.0, val)

            marker_info[attr] = val
            if num_markers == 0 or len (val) < num_markers:
                num_markers = len (val)

        for attr in ['marker-colors', 'marker-names',
                     'marker-types', 'marker-levels']:
            if len (marker_info[attr]) > num_markers:
                debugprint ("Trimming %s from %s" %
                            (marker_info[attr][num_markers:], attr))
                del marker_info[attr][num_markers:]

        markers = map (lambda color, name, type, level:
                           (color, name, type, level),
                       marker_info['marker-colors'],
                       marker_info['marker-names'],
                       marker_info['marker-types'],
                       marker_info['marker-levels'])
        debugprint (markers)

        can_refresh = (printer.type & cups.CUPS_PRINTER_COMMANDS) != 0
        if can_refresh:
            self.btnRefreshMarkerLevels.show ()
        else:
            self.btnRefreshMarkerLevels.hide ()

        if len (markers) == 0:
            label = Gtk.Label(label=_("Marker levels are not reported "
                                "for this printer."))
            label.set_line_wrap (True)
            label.set_alignment (0.0, 0.0)
            self.vboxMarkerLevels.pack_start (label, False, False, 0)
        else:
            num_markers = 0
            cols = len (markers)
            rows = 1 + (cols - 1) / 4
            if cols > 4:
                cols = 4
            table = Gtk.Table (rows=rows,
                               columns=cols,
                               homogeneous=True)
            table.set_col_spacings (6)
            table.set_row_spacings (12)
            self.vboxMarkerLevels.pack_start (table, False, False, 0)
            for color, name, marker_type, level in markers:
                if name == None:
                    name = ''
                elif self.ppd != False:
                    localized_name = self.ppd.localizeMarkerName(name)
                    if localized_name != None:
                        name = localized_name

                row = num_markers / 4
                col = num_markers % 4

                vbox = Gtk.VBox (spacing=6)
                subhbox = Gtk.HBox ()
                inklevel = gtkinklevel.GtkInkLevel (color, level)
                inklevel.set_tooltip_text ("%d%%" % level)
                subhbox.pack_start (inklevel, True, False, 0)
                vbox.pack_start (subhbox, False, False, 0)
                label = Gtk.Label(label=name)
                label.set_width_chars (10)
                label.set_line_wrap (True)
                vbox.pack_start (label, False, False, 0)
                table.attach (vbox, col, col + 1, row, row + 1)
                num_markers += 1

        self.vboxMarkerLevels.show_all ()

    def on_btnRefreshMarkerLevels_clicked (self, button):
        self.maintenance_command ("ReportLevels")

    def updateStateReasons (self):
        printer = self.printer
        reasons = printer.other_attributes.get ('printer-state-reasons', [])
        store = Gtk.ListStore (str, str)
        any = False
        for reason in reasons:
            if reason == "none":
                break

            any = True
            iter = store.append (None)
            r = statereason.StateReason (printer.name, reason, self._ppdcache)
            if r.get_reason () == "paused":
                icon = Gtk.STOCK_MEDIA_PAUSE
            else:
                icon = statereason.StateReason.LEVEL_ICON[r.get_level ()]
            store.set_value (iter, 0, icon)
            (title, text) = r.get_description ()
            store.set_value (iter, 1, text)

        self.tvPrinterStateReasons.set_model (store)
        page = 0
        if any:
            page = 1

        self.ntbkPrinterStateReasons.set_current_page (page)

    def set_printer_state_reason_icon (self, column, cell, model, iter, *data):
        icon = model.get_value (iter, 0)
        theme = Gtk.IconTheme.get_default ()
        try:
            pixbuf = theme.load_icon (icon, 22, 0)
            cell.set_property ("pixbuf", pixbuf)
        except GLib.GError:
            pass # Couldn't load icon

    def set_printer_state_reason_text (self, column, cell, model, iter, *data):
        cell.set_property ("text", model.get_value (iter, 1))

    def updatePrinterProperties(self):
        debugprint ("update printer properties")
        printer = self.printer
        self.entPMakeModel.set_text(printer.make_and_model)
        state = self.printer_states.get (printer.state,
                                         _("Unknown"))
        reason = printer.other_attributes.get ('printer-state-message', '')
        if len (reason) > 0:
            state += ' - ' + reason
        self.entPState.set_text(state)
        if len (self.changed) == 0:
            debugprint ("no changes yet: full printer properties update")
            # State
            self.chkPEnabled.set_active(printer.enabled)
            self.chkPAccepting.set_active(not printer.rejecting)
            self.chkPShared.set_active(printer.is_shared)

            # Job sheets
            self.fillComboBox(self.cmbPStartBanner,
                              printer.job_sheets_supported,
                              printer.job_sheet_start,
                              ppdippstr.job_sheets)
            self.fillComboBox(self.cmbPEndBanner, printer.job_sheets_supported,
                              printer.job_sheet_end,
                              ppdippstr.job_sheets)

            # Policies
            self.fillComboBox(self.cmbPErrorPolicy,
                              printer.error_policy_supported,
                              printer.error_policy,
                              ppdippstr.printer_error_policy)
            self.fillComboBox(self.cmbPOperationPolicy,
                              printer.op_policy_supported,
                              printer.op_policy,
                              ppdippstr.printer_op_policy)

            # Access control
            self.rbtnPAllow.set_active(printer.default_allow)
            self.rbtnPDeny.set_active(not printer.default_allow)
            self.setPUsers(printer.except_users)

            # Marker levels
            self.updateMarkerLevels ()
            self.updateStateReasons ()

            self.updatePrinterPropertiesTreeView ()

    def fillPrinterOptions(self, name, editable):
        # remove Class membership tab
        tab_nr = self.ntbkPrinter.page_num(self.algnClassMembers)
        if tab_nr != -1:
            self.ntbkPrinter.remove_page(tab_nr)

        # clean Installable Options Tab
        for widget in self.vbPInstallOptions.get_children():
            self.vbPInstallOptions.remove(widget)

        # clean Options Tab
        for widget in self.vbPOptions.get_children():
            self.vbPOptions.remove(widget)

        # insert Options Tab
        if self.ntbkPrinter.page_num(self.swPOptions) == -1:
            self.ntbkPrinter.insert_page(
                self.swPOptions, self.lblPOptions, self.static_tabs)

        if not self.ppd:
            tab_nr = self.ntbkPrinter.page_num(self.swPInstallOptions)
            if tab_nr != -1:
                self.ntbkPrinter.remove_page(tab_nr)
            tab_nr = self.ntbkPrinter.page_num(self.swPOptions)
            if tab_nr != -1:
                self.ntbkPrinter.remove_page(tab_nr)
            return
        ppd = self.ppd
        ppd.markDefaults()
        self.ppd_local.markDefaults()

        hasInstallableOptions = False

        # build option tabs
        for group in self.ppd_local.optionGroups:
            if group.name == "InstallableOptions":
                hasInstallableOptions = True
                container = self.vbPInstallOptions
                tab_nr = self.ntbkPrinter.page_num(self.swPInstallOptions)
                if tab_nr == -1:
                    self.ntbkPrinter.insert_page(self.swPInstallOptions,
                                                 Gtk.Label(label=group.text),
                                                 self.static_tabs)
                tab_label = self.lblPInstallOptions
            else:
                frame = Gtk.Frame(label="<b>%s</b>" % ppdippstr.ppd.get (group.text))
                frame.get_label_widget().set_use_markup(True)
                frame.set_shadow_type (Gtk.ShadowType.NONE)
                self.vbPOptions.pack_start (frame, False, False, 0)
                container = Gtk.Alignment.new(0.5, 0.5, 1.0, 1.0)
                # We want a left padding of 12, but there is a Table with
                # spacing 6, and the left-most column of it (the conflict
                # icon) is normally hidden, so just use 6 here.
                container.set_padding (6, 12, 6, 0)
                frame.add (container)
                tab_label = self.lblPOptions

            table = Gtk.Table(1, 3, False)
            table.set_col_spacings(6)
            table.set_row_spacings(6)
            container.add(table)

            rows = 0

            # InputSlot and ManualFeed need special handling.  With
            # libcups, if ManualFeed is True, InputSlot gets unset.
            # Likewise, if InputSlot is set, ManualFeed becomes False.
            # We handle it by toggling the sensitivity of InputSlot
            # based on ManualFeed.
            self.option_inputslot = self.option_manualfeed = None

            for nr, option in enumerate(group.options):
                if option.keyword == "PageRegion":
                    continue
                rows += 1
                table.resize (rows, 3)
                o = OptionWidget(option, ppd, self, tab_label=tab_label)
                table.attach(o.conflictIcon, 0, 1, nr, nr+1, 0, 0, 0, 0)

                hbox = Gtk.HBox()
                if o.label:
                    a = Gtk.Alignment.new(0.5, 0.5, 1.0, 1.0)
                    a.set_padding (0, 0, 0, 6)
                    a.add (o.label)
                    table.attach(a, 1, 2, nr, nr+1, Gtk.AttachOptions.FILL, 0, 0, 0)
                    table.attach(hbox, 2, 3, nr, nr+1, Gtk.AttachOptions.FILL, 0, 0, 0)
                else:
                    table.attach(hbox, 1, 3, nr, nr+1, Gtk.AttachOptions.FILL, 0, 0, 0)
                hbox.pack_start(o.selector, False, False, 0)
                self.options[option.keyword] = o
                o.selector.set_sensitive(editable)
                if option.keyword == "InputSlot":
                    self.option_inputslot = o
                elif option.keyword == "ManualFeed":
                    self.option_manualfeed = o

        # remove Installable Options tab if not needed
        if not hasInstallableOptions:
            tab_nr = self.ntbkPrinter.page_num(self.swPInstallOptions)
            if tab_nr != -1:
                self.ntbkPrinter.remove_page(tab_nr)

        # check for conflicts
        for option in self.options.itervalues():
            conflicts = option.checkConflicts()
            if conflicts:
                self.conflicts.add(option)

        self.swPInstallOptions.show_all()
        self.swPOptions.show_all()

    # Class members

    def fillClassMembers(self, editable):
        self.btnClassAddMember.set_sensitive(editable)
        self.btnClassDelMember.set_sensitive(editable)

        # remove Options tab
        tab_nr = self.ntbkPrinter.page_num(self.swPOptions)
        if tab_nr != -1:
            self.ntbkPrinter.remove_page(tab_nr)

        # insert Member Tab
        if self.ntbkPrinter.page_num(self.algnClassMembers) == -1:
            self.ntbkPrinter.insert_page(
                self.algnClassMembers, self.lblClassMembers,
                self.static_tabs)

        model_members = self.tvClassMembers.get_model()
        model_not_members = self.tvClassNotMembers.get_model()
        model_members.clear()
        model_not_members.clear()

        names = list (self._monitor.get_printers ())
        names.sort ()
        for name in names:
            if name != self.printer.name:
                if name in self.printer.class_members:
                    model_members.append((name, ))
                else:
                    model_not_members.append((name, ))

    def on_btnClassAddMember_clicked(self, button):
        newprinter.moveClassMembers(self.tvClassNotMembers,
                                    self.tvClassMembers)
        if newprinter.getCurrentClassMembers(self.tvClassMembers) != self.printer.class_members:
            self.changed.add(self.tvClassMembers)
        else:
            self.changed.discard(self.tvClassMembers)
        self.setDataButtonState()

    def on_btnClassDelMember_clicked(self, button):
        newprinter.moveClassMembers(self.tvClassMembers,
                                    self.tvClassNotMembers)
        if newprinter.getCurrentClassMembers(self.tvClassMembers) != self.printer.class_members:
            self.changed.add(self.tvClassMembers)
        else:
            self.changed.discard(self.tvClassMembers)
        self.setDataButtonState()

    def sensitise_new_printer_widgets (self, sensitive=True):
        sensitive = (sensitive and
                     self.printer != None and
                     not (self.printer.discovered or
                          bool (self.changed)))
        for button in [self.btnChangePPD,
                       self.btnSelectDevice]:
            button.set_sensitive (sensitive)

    def desensitise_new_printer_widgets (self):
        self.sensitise_new_printer_widgets (False)
        
    # change device
    def on_btnSelectDevice_clicked(self, button):
        busy (self.dialog)
        self.desensitise_new_printer_widgets ()
        if not self.newPrinterGUI.init("device", device_uri=self.printer.device_uri,
                                       name=self.printer.name,
                                       host=self._host,
                                       encryption=self._encryption,
                                       parent=self.dialog):
            self.sensitise_new_printer_widgets ()

        ready (self.dialog)

    # change PPD
    def on_btnChangePPD_clicked(self, button):
        busy (self.dialog)
        self.desensitise_new_printer_widgets ()
        if not self.newPrinterGUI.init("ppd", device_uri=self.printer.device_uri,
                                       ppd=self.ppd,
                                       name=self.printer.name,
                                       host=self._host,
                                       encryption=self._encryption,
                                       parent=self.dialog):
            self.sensitise_new_printer_widgets ()

        ready (self.dialog)

    # NewPrinterGUI signal handlers
    def on_printer_modified (self, obj, name, ppd_has_changed):
        debugprint ("on_printer_modified called")
        self.sensitise_new_printer_widgets ()
        if self.dialog.get_property ('visible') and self.printer:
            try:
                self.printer.getAttributes ()
                if ppd_has_changed:
                    self.load (name)
                else:
                    self.updatePrinterProperties ()

            except cups.IPPError:
                pass

    def on_printer_not_modified (self, obj):
        self.sensitise_new_printer_widgets ()

    # Monitor signal handlers
    def on_printer_event (self, mon, printer, eventname, event):
        self.on_printer_modified (None, printer, False)

    def on_printer_removed (self, mon, printer):
        if (self.dialog.get_property ('visible') and
            self.printer and self.printer.name == printer):
            self.dialog.response (Gtk.ResponseType.CANCEL)

        if self.printer and self.printer.name == printer:
            self.printer = None

    def on_state_reason_added (self, mon, reason):
        if (self.dialog.get_property ('visible') and
            self.printer and self.printer.name == reason.get_printer ()):
            try:
                self.printer.getAttributes ()
                self.updatePrinterProperties ()
            except cups.IPPError:
                pass

    def on_state_reason_removed (self, mon, reason):
        if (self.dialog.get_property ('visible') and
            self.printer and self.printer.name == reason.get_printer ()):
            try:
                self.printer.getAttributes ()
                self.updatePrinterProperties ()
            except cups.IPPError:
                pass

    def on_cups_connection_error (self, mon):
        # FIXME: figure out how to handle this
        pass

if __name__ == '__main__':
    import locale
    import sys

    if len (sys.argv) < 2:
        print "Specify queue name"
        sys.exit (1)

    set_debugging (True)
    os.environ["SYSTEM_CONFIG_PRINTER_UI"] = "ui"
    locale.setlocale (locale.LC_ALL, "")
    ppdippstr.init ()
    loop = GObject.MainLoop ()
    def on_dialog_closed (obj):
        obj.destroy ()
        loop.quit ()

    properties = PrinterPropertiesDialog ()
    properties.connect ('dialog-closed', on_dialog_closed)
    properties.show (sys.argv[1])

    loop.run ()

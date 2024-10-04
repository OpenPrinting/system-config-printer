#!/usr/bin/python3

## system-config-printer

## Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014, 2015 Red Hat, Inc.
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

import authconn
import cupshelpers
from OpenPrintingRequest import OpenPrintingRequest

import errno
import sys, os, tempfile, time, re, http.client
import locale
import string
import subprocess
from timedops import *
import dbus
from gi.repository import Gdk
from gi.repository import Gtk
import functools

import cups

try:
    import pysmb
    PYSMB_AVAILABLE=True
except:
    PYSMB_AVAILABLE=False

import options
from gi.repository import GObject
from gi.repository import GLib
from gui import GtkGUI
from optionwidgets import OptionWidget
from debug import *
import probe_printer
import urllib.request, urllib.parse
from smburi import SMBURI
from errordialogs import *
from PhysicalDevice import PhysicalDevice
import firewallsettings
import asyncconn
import ppdsloader
import dnssdresolve
import installpackage

import gettext
gettext.install(domain=config.PACKAGE, localedir=config.localedir)

HTTPS_TIMEOUT = 15.0

TEXT_adjust_firewall = _("The firewall may need adjusting in order to "
                         "detect network printers.  Adjust the "
                         "firewall now?")

def validDeviceURI (uri):
    """Returns True is the provided URI is valid."""
    (scheme, rest) = urllib.parse.splittype (uri)
    if scheme is None or scheme == '':
        return False
    return True

# Both the printer properties window and the new printer window
# need to be able to drive 'class members' selections.
def moveClassMembers(treeview_from, treeview_to):
    selection = treeview_from.get_selection()
    model_from, rows = selection.get_selected_rows()
    rows = [Gtk.TreeRowReference.new(model_from, row) for row in rows]

    model_to = treeview_to.get_model()

    for row in rows:
        path = row.get_path()
        iter = model_from.get_iter(path)
        row_data = model_from.get(iter, 0)
        model_to.append(row_data)
        model_from.remove(iter)

def getCurrentClassMembers(treeview):
    model = treeview.get_model()
    iter = model.get_iter_first()
    result = []
    while iter:
        result.append(model.get(iter, 0)[0])
        iter = model.iter_next(iter)
    result.sort()
    return result

def checkNPName(printers, name):
    if not name: return False
    name = name.lower()
    for printer in printers.values():
        if not printer.discovered and printer.name.lower()==name:
            return False
    return True

def ready (win, cursor=None):
    try:
        gdkwin = win.get_window()
        if gdkwin:
            gdkwin.set_cursor (cursor)
            while Gtk.events_pending ():
                Gtk.main_iteration ()
    except:
        nonfatalException ()

def busy (win):
    ready (win, Gdk.Cursor.new(Gdk.CursorType.WATCH))

def on_delete_just_hide (widget, event):
    widget.hide ()
    return True # stop other handlers

def _singleton (x):
    """If we don't know whether getPPDs() or getPPDs2() was used, this
    function can unwrap an item from a list in either case."""
    if isinstance (x, list):
        return x[0]
    return x

def download_gpg_fingerprint(url):
    """Get GPG fingerprint from URL.

    Check that the URL is HTTPS with a valid and trusted server
    certificate, read it, extract the GPG fingerprint from it, and return
    it. Return None if the URL is invalid, not trusted, or the fingerprint
    can't be found.
    """
    if not url.startswith('https://'):
        debugprint('Not a https fingerprint URL: %s, ignoring driver' % url)
        return None

    content = None
    try:
        with urllib.request.urlopen(url, timeout=HTTPS_TIMEOUT) as resp:
            if resp.status == 200:
                content = resp.read().decode('utf-8')
    except Exception as e:
        debugprint('Cannot retrieve %s: %s' % (url, e))

    if content is None:
        debugprint('Cannot retrieve %s' % url)
        return None

    keyid_re = re.compile(r' ((?:(?:[0-9A-F]{4})(?:\s+|$)){10})$', re.M)

    m = keyid_re.search(content)
    if m:
        return m.group(1).strip().replace(' ','')

    return None

class NewPrinterGUI(GtkGUI):

    __gsignals__ = {
        'destroy':          (GObject.SignalFlags.RUN_LAST, None, ()),
        'printer-added' :   (GObject.SignalFlags.RUN_LAST, None, (str,)),
        'printer-modified': (GObject.SignalFlags.RUN_LAST, None,
                             (str,    # printer name
                              bool,)), # PPD modified?
        'driver-download-checked': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        'dialog-canceled':  (GObject.SignalFlags.RUN_LAST, None, ()),
        }

    # Page numbers used to name the different stages
    PAGE_DESCRIBE_PRINTER = 0
    PAGE_SELECT_DEVICE = 1
    PAGE_SELECT_INSTALL_METHOD = 2
    PAGE_CHOOSE_DRIVER_FROM_DB = 3
    PAGE_CHOOSE_CLASS_MEMBERS = 4
    PAGE_APPLY = 5
    PAGE_INSTALLABLE_OPTIONS = 6
    PAGE_DOWNLOAD_DRIVER = 7

    # Values returned by _handlePrinterInstallationMode() and
    # related sub-functions, to know whether to continue the
    # execution of the remaining logic from calling functions
    INSTALL_RESULT_DONE = True
    INSTALL_RESULT_OPS_PENDING = False

    new_printer_device_tabs = {
        "parallel" : 0, # empty tab
        "usb" : 0,
        "bluetooth" : 0,
        "hal" : 0,
        "beh" : 0,
        "hp" : 0,
        "hpfax" : 0,
        "dnssd" : 0,
        "socket": 2,
        "lpd" : 3,
        "scsi" : 4,
        "serial" : 5,
        "smb" : 6,
        "network": 7,
        }

    def __init__(self):
        GObject.GObject.__init__ (self)
        self.language = locale.getlocale (locale.LC_MESSAGES)

        self.options = {} # keyword -> Option object
        self.changed = set()
        self.conflicts = set()
        self.device = None
        self.ppd = None
        self.remotecupsqueue = False
        self.exactdrivermatch = False
        self.installable_options = False
        self.ppdsloader = None
        self.installed_driver_files = []
        self.searchedfordriverpackages = False
        self.founddownloadabledrivers = False
        self.founddownloadableppd = False
        self.downloadable_driver_for_printer = None
        self.downloadable_printers = []
        self.nextnptab_rerun = False
        self.printers = {} # set in init()
        self.recommended_model_selected = False
        self._searchdialog = None
        self._installdialog = None

        self.getWidgets({"NewPrinterWindow":
                             ["NewPrinterWindow",
                              "ntbkNewPrinter",
                              "btnNPBack",
                              "btnNPForward",
                              "btnNPApply",
                              "spinner",
                              "entNPName",
                              "entNPDescription",
                              "entNPLocation",
                              "isSharedCbx",
                              "tvNPDevices",
                              "ntbkNPType",
                              "lblNPDeviceDescription",
                              "expNPDeviceURIs",
                              "tvNPDeviceURIs",
                              "cmbNPTSerialBaud",
                              "cmbNPTSerialParity",
                              "cmbNPTSerialBits",
                              "cmbNPTSerialFlow",
                              "btnNPTLpdProbe",
                              "entNPTLpdHost",
                              "entNPTLpdQueue",
                              "entNPTJetDirectHostname",
                              "entNPTJetDirectPort",
                              "entSMBURI",
                              "btnSMBBrowse",
                              "tblSMBAuth",
                              "rbtnSMBAuthPrompt",
                              "rbtnSMBAuthSet",
                              "entSMBUsername",
                              "entSMBPassword",
                              "btnSMBVerify",
                              "entNPTNetworkHostname",
                              "btnNetworkFind",
                              "lblNetworkFindSearching",
                              "lblNetworkFindNotFound",
                              "entNPTDevice",
                              "tvNCMembers",
                              "tvNCNotMembers",
                              "btnNCAddMember",
                              "btnNCDelMember",
                              "ntbkPPDSource",
                              "rbtnNPPPD",
                              "tvNPMakes",
                              "rbtnNPFoomatic",
                              "filechooserPPD",
                              "rbtnNPDownloadableDriverSearch",
                              "entNPDownloadableDriverSearch",
                              "btnNPDownloadableDriverSearch",
                              "btnNPDownloadableDriverSearch_label",
                              "cmbNPDownloadableDriverFoundPrinters",
                              "tvNPModels",
                              "tvNPDrivers",
                              "rbtnChangePPDasIs",
                              "rbtnChangePPDKeepSettings",
                              "scrNPInstallableOptions",
                              "vbNPInstallOptions",
                              "tvNPDownloadableDrivers",
                              "ntbkNPDownloadableDriverProperties",
                              "lblNPDownloadableDriverSupplier",
                              "cbNPDownloadableDriverSupplierVendor",
                              "lblNPDownloadableDriverLicense",
                              "cbNPDownloadableDriverLicensePatents",
                              "cbNPDownloadableDriverLicenseFree",
                              "lblNPDownloadableDriverDescription",
                              "lblNPDownloadableDriverSupportContacts",
                              "hsDownloadableDriverPerfText",
                              "hsDownloadableDriverPerfLineArt",
                              "hsDownloadableDriverPerfGraphics",
                              "hsDownloadableDriverPerfPhoto",
                              "lblDownloadableDriverPerfTextUnknown",
                              "lblDownloadableDriverPerfLineArtUnknown",
                              "lblDownloadableDriverPerfGraphicsUnknown",
                              "lblDownloadableDriverPerfPhotoUnknown",
                              "frmNPDownloadableDriverLicenseTerms",
                              "tvNPDownloadableDriverLicense",
                              "rbtnNPDownloadLicenseYes",
                              "rbtnNPDownloadLicenseNo"],
                         "WaitWindow":
                             ["WaitWindow",
                              "lblWait"],
                         "SMBBrowseDialog":
                             ["SMBBrowseDialog",
                              "tvSMBBrowser",
                              "btnSMBBrowseOk"]},

                        domain=config.PACKAGE)

        # Fill in liststores for combo-box widgets
        for (widget,
             opts) in [(self.cmbNPTSerialBaud,
                        [[_("Default"), ""],
                         ["1200", "1200"],
                         ["2400", "2400"],
                         ["4800", "4800"],
                         ["9600", "9600"],
                         ["19200", "19200"],
                         ["38400", "38400"],
                         ["57600", "57600"],
                         ["115200", "115200"]]),

                       (self.cmbNPTSerialParity,
                        [[_("Default"), ""],
                         [_("None"), "none"],
                         [_("Odd"), "odd"],
                         [_("Even"), "even"]]),

                       (self.cmbNPTSerialBits,
                        [[_("Default"), ""],
                         ["8", "8"],
                         ["7", "7"]]),

                       (self.cmbNPTSerialFlow,
                        [[_("Default"), ""],
                         [_("None"), "none"],
                         [_("XON/XOFF (Software)"), "soft"],
                         [_("RTS/CTS (Hardware)"), "hard"],
                         [_("DTR/DSR (Hardware)"), "hard"]]),

                       ]:
            store = Gtk.ListStore (str, str)
            for row in opts:
                store.append (row)

            widget.set_model (store)
            cell = Gtk.CellRendererText ()
            widget.clear ()
            widget.pack_start (cell, True)
            widget.add_attribute (cell, 'text', 0)

        # Set up some lists
        m = Gtk.SelectionMode.MULTIPLE
        s = Gtk.SelectionMode.SINGLE
        b = Gtk.SelectionMode.BROWSE
        for name, model, treeview, selection_mode in (
            (_("Members of this class"), Gtk.ListStore(str),
             self.tvNCMembers, m),
            (_("Others"), Gtk.ListStore(str), self.tvNCNotMembers, m),
            (_("Devices"), Gtk.ListStore(str), self.tvNPDevices, s),
            (_("Connections"), Gtk.ListStore(str), self.tvNPDeviceURIs, s),
            (_("Makes"), Gtk.ListStore(str, str), self.tvNPMakes,s),
            (_("Models"), Gtk.ListStore(str, str), self.tvNPModels,s),
            (_("Drivers"), Gtk.ListStore(str), self.tvNPDrivers,s),
            (_("Downloadable Drivers"), Gtk.ListStore(str),
             self.tvNPDownloadableDrivers, b),
            ):

            cell = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(name, cell, text=0)
            treeview.set_model(model)
            treeview.append_column(column)
            treeview.get_selection().set_mode(selection_mode)

        # Since some dialogs are reused we can't let the delete-event's
        # default handler destroy them
        self.SMBBrowseDialog.connect ("delete-event", on_delete_just_hide)
        self.WaitWindow_handler = self.WaitWindow.connect ("delete-event",
                                                           on_delete_just_hide)

        self.ntbkNewPrinter.set_show_tabs(False)
        self.ntbkPPDSource.set_show_tabs(False)
        self.ntbkNPType.set_show_tabs(False)
        self.ntbkNPDownloadableDriverProperties.set_show_tabs(False)

        self.spinner_count = 0

        # Set up OpenPrinting widgets.
        self.opreq = None
        self.opreq_handlers = None
        combobox = self.cmbNPDownloadableDriverFoundPrinters
        cell = Gtk.CellRendererText()
        combobox.pack_start (cell, True)
        combobox.add_attribute(cell, 'text', 0)
        if config.DOWNLOADABLE_ONLYFREE:
            for widget in [self.cbNPDownloadableDriverLicenseFree,
                           self.cbNPDownloadableDriverLicensePatents]:
                widget.hide ()
        if os.path.exists('/etc/apt/sources.list') or os.path.exists(
            '/etc/apt/sources.list.d'):
            config.packagesystem = 'deb'
            self.packageinstaller = 'apt'
        elif os.path.exists('/etc/yum.conf'):
            config.packagesystem = 'rpm'
            self.packageinstaller = 'yum'
        else:
            # No known package system, so we only load single PPDs via
            # OpenPrinting
            config.DOWNLOADABLE_ONLYPPD = True

        def protect_toggle (toggle_widget):
            active = getattr (toggle_widget, 'protect_active', None)
            if active is not None:
                toggle_widget.set_active (active)

        for widget in [self.cbNPDownloadableDriverSupplierVendor,
                       self.cbNPDownloadableDriverLicenseFree,
                       self.cbNPDownloadableDriverLicensePatents]:
            widget.connect ('clicked', protect_toggle)

        for widget in [self.hsDownloadableDriverPerfText,
                       self.hsDownloadableDriverPerfLineArt,
                       self.hsDownloadableDriverPerfGraphics,
                       self.hsDownloadableDriverPerfPhoto]:
            widget.connect ('change-value',
                            lambda x, y, z: True)

        # Device list
        slct = self.tvNPDevices.get_selection ()
        slct.set_select_function (self.device_select_function, None)
        self.tvNPDevices.set_row_separator_func (self.device_row_separator_fn, None)
        self.tvNPDevices.connect ("row-activated", self.device_row_activated)
        self.tvNPDevices.connect ("row-expanded", self.device_row_expanded)

        # Devices expander
        self.expNPDeviceURIs.connect ("notify::expanded",
                                      self.on_expNPDeviceURIs_expanded)
        self.expNPDeviceURIs.set_expanded(1)

        # SMB browser
        self.smb_store = Gtk.TreeStore (GObject.TYPE_PYOBJECT)
        self.btnSMBBrowse.set_sensitive (True)
        if not PYSMB_AVAILABLE:
            self.btnSMBBrowse.set_tooltip_text (_("Browsing requires pysmbc "
                                                  "module"))
        self.tvSMBBrowser.set_model (self.smb_store)

        # SMB list columns
        col = Gtk.TreeViewColumn (_("Share"))
        cell = Gtk.CellRendererText ()
        col.pack_start (cell, False)
        col.set_cell_data_func (cell, self.smbbrowser_cell_share, None)
        self.tvSMBBrowser.append_column (col)

        col = Gtk.TreeViewColumn (_("Comment"))
        cell = Gtk.CellRendererText ()
        col.pack_start (cell, False)
        col.set_cell_data_func (cell, self.smbbrowser_cell_comment, None)
        self.tvSMBBrowser.append_column (col)

        slct = self.tvSMBBrowser.get_selection ()
        slct.set_select_function (self.smb_select_function, None)

        self.SMBBrowseDialog.set_transient_for(self.NewPrinterWindow)

        self.tvNPDrivers.set_has_tooltip(True)
        self.tvNPDrivers.connect("query-tooltip", self.on_NPDrivers_query_tooltip)

        ppd_filter = Gtk.FileFilter()
        ppd_filter.set_name(_("PostScript Printer Description files (*.ppd, *.PPD, *.ppd.gz, *.PPD.gz, *.PPD.GZ)"))
        ppd_filter.add_pattern("*.ppd")
        ppd_filter.add_pattern("*.PPD")
        ppd_filter.add_pattern("*.ppd.gz")
        ppd_filter.add_pattern("*.PPD.gz")
        ppd_filter.add_pattern("*.PPD.GZ")
        self.filechooserPPD.add_filter(ppd_filter)

        ppd_filter = Gtk.FileFilter()
        ppd_filter.set_name(_("All files (*)"))
        ppd_filter.add_pattern("*")
        self.filechooserPPD.add_filter(ppd_filter)

        self.device_selected = -1
        self.dialog_mode = "printer"
        self.connect_signals ()
        debugprint ("+%s" % self)

    def __del__ (self):
        debugprint ("-%s" % self)

    def do_destroy (self):
        debugprint ("DESTROY: %s" % self)
        if self.SMBBrowseDialog:
            self.SMBBrowseDialog.destroy ()
            self.SMBBrowseDialog = None

        if self.NewPrinterWindow:
            self.NewPrinterWindow.destroy ()
            self.NewPrinterWindow = None

        if self.WaitWindow:
            self.WaitWindow.destroy ()
            self.WaitWindow = None

    def inc_spinner_task (self):
        if self.spinner_count == 0:
            self.spinner.show ()
            self.spinner.start ()

        self.spinner_count += 1

    def dec_spinner_task (self):
        self.spinner_count -= 1
        if self.spinner_count == 0:
            self.spinner.hide ()
            self.spinner.stop ()

    def show_IPP_Error (self, exception, message):
        debugprint ("%s: IPP error dialog (%s, %s)" % (self, repr (exception),
                                                       message))
        return show_IPP_Error (exception, message, parent=self.NewPrinterWindow)

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

        return

    def setDataButtonState(self):
        self.btnNPForward.set_sensitive(not bool(self.conflicts))

    def makeNameUnique(self, name):
        """Make a suggested queue name valid and unique."""
        name = name.replace (" ", "-")
        name = name.replace ("/", "-")
        name = name.replace ("#", "-")
        if not checkNPName (self.printers, name):
            suffix=2
            while not checkNPName (self.printers, name + "-" + str (suffix)):
                suffix += 1
                if suffix == 100:
                    break
            name += "-" + str (suffix)
        return name

    def destroy (self):
        self.emit ('destroy')

    def init(self, dialog_mode, device_uri=None, name=None, ppd=None,
             devid="", host=None, encryption=None, parent=None, xid=0):
        self.parent = parent
        if not self.parent:
            self.NewPrinterWindow.set_focus_on_map (False)

        self.dialog_mode = dialog_mode
        self._device_uri = device_uri
        self.orig_ppd = ppd
        self.devid = devid
        self._host = host
        self._encryption = encryption
        self._name = name
        if not host:
            self._host = cups.getServer ()
        if not encryption:
            self._encryption = cups.getEncryption ()

        self.options = {} # keyword -> Option object
        self.changed = set()
        self.conflicts = set()
        self.fetchDevices_conn = None
        self.ppds = None
        self.ppdsmatch_result = None
        self.printer_finder = None

        if not self._validInitParameters ():
            raise RuntimeError

        # Get a current list of printers so that we can know whether
        # the chosen name is unique.
        try:
            self.cups = authconn.Connection (parent=self.NewPrinterWindow,
                                             host=self._host,
                                             encryption=self._encryption)
        except cups.HTTPError as e:
            (s,) = e.args
            show_HTTP_Error (s, self.parent)
            return False
        except RuntimeError:
            show_HTTP_Error (-1, self.parent)
            return False
        except Exception as e:
            nonfatalException (e)
            return False

        try:
            self.printers = cupshelpers.getPrinters (self.cups)
        except cups.IPPError as e:
            (e, m) = e.args
            show_IPP_Error (e, m, parent=self.parent)
            return False

        # Initialise widgets.
        self.lblNetworkFindSearching.hide ()
        self.entNPTNetworkHostname.set_sensitive (True)
        self.entNPTNetworkHostname.set_text ('')
        self.btnNetworkFind.set_sensitive (True)
        self.lblNetworkFindNotFound.hide ()

        # Clear out any previous list of makes.
        model = self.tvNPMakes.get_model()
        model.clear()

        combobox = self.cmbNPDownloadableDriverFoundPrinters
        combobox.set_model (Gtk.ListStore (str, str))
        self.entNPDownloadableDriverSearch.set_text ('')
        label = self.btnNPDownloadableDriverSearch_label
        label.set_text (_("Search"))

        self.entNPTJetDirectPort.set_text('9100')
        self.rbtnSMBAuthPrompt.set_active(True)

        if xid != 0 and self.parent:
            self.NewPrinterWindow.show_now()
            self.NewPrinterWindow.set_transient_for (self.parent)

        if self.dialog_mode == "printer":
            self._initialisePrinterMode ()
        elif self.dialog_mode == "class":
            self._initialiseClassMode ()
        elif self.dialog_mode == "device":
            self._initialiseDeviceMode ()
        elif self.dialog_mode == "printer_with_uri":
            self._initialisePrinterWithURIMode ()
        elif self.dialog_mode == "ppd":
            self._initialisePPDMode ()
        elif self.dialog_mode == "download_driver":
            self._initialiseDownloadDriverMode ()
            return True

        if xid == 0 and self.parent:
            self.NewPrinterWindow.set_transient_for (parent)

        self.NewPrinterWindow.show()
        self.setNPButtons()
        return True

    def _validInitParameters (self):
        if self.dialog_mode in ['printer_with_uri', 'device', 'ppd']:
            return self._device_uri is not None
        elif self.dialog_mode == 'download_driver':
            return self.devid != ""
        return True

    def _initialiseClassMode (self):
        self._initialiseWidgetsForMode ("class")
        self.NewPrinterWindow.set_title (_("New Class"))

        self.fillNewClassMembers ()

        # Start on name page
        self.ntbkNewPrinter.set_current_page (self.PAGE_DESCRIBE_PRINTER)

    def _initialisePrinterMode (self):
        self._initialiseWidgetsForMode ("printer")
        self.NewPrinterWindow.set_title (_("New Printer"))

        # Start on devices page (SELECT_DEVICE, not DESCRIBE_PRINTER)
        self.ntbkNewPrinter.set_current_page (self.PAGE_SELECT_DEVICE)
        self.fillDeviceTab ()
        self.rbtnNPFoomatic.set_active (True)
        self.on_rbtnNPFoomatic_toggled (self.rbtnNPFoomatic)

    def _initialiseDeviceMode (self):
        self.NewPrinterWindow.set_title (_("Change Device URI"))
        self.ntbkNewPrinter.set_current_page (self.PAGE_SELECT_DEVICE)
        self.fillDeviceTab (self._device_uri)

    def _initialisePrinterWithURIMode (self):
        self._initialiseWidgetsForMode ("printer")
        self._initialiseDeviceFromURI ()

        self.NewPrinterWindow.set_title (_("New Printer"))

        self.ntbkNewPrinter.set_current_page (self.PAGE_SELECT_INSTALL_METHOD)
        self.rbtnNPFoomatic.set_active (True)
        self.on_rbtnNPFoomatic_toggled (self.rbtnNPFoomatic)
        self.rbtnChangePPDKeepSettings.set_active (True)

        self._initialiseAutoVariables ()
        self.nextNPTab (step = 0)

    def _initialiseDownloadDriverMode (self):
        self.NewPrinterWindow.set_title (_("Download Printer Driver"))

        self.ntbkNewPrinter.set_current_page (self.PAGE_DOWNLOAD_DRIVER)
        self.nextnptab_rerun = True
        self.nextNPTab (step = 0)

    def _initialisePPDMode (self):
        self._initialiseDeviceFromURI ()

        self.NewPrinterWindow.set_title (_("Change Driver"))

        # We'll need to know the Device ID for this device.
        if not self.devid:
            scheme = str (self._device_uri.split (":", 1)[0])
            schemes = [scheme]
            if scheme in ["socket", "lpd", "ipp"]:
                schemes.extend (["snmp", "dnssd"])
            self.fetchDevices_conn = asyncconn.Connection ()
            self.fetchDevices_conn._begin_operation (_("fetching device list"))
            self.inc_spinner_task ()
            cupshelpers.getDevices (self.fetchDevices_conn,
                                    include_schemes=schemes,
                                    reply_handler=self.change_ppd_got_devs,
                                    error_handler=self.change_ppd_got_devs)

        self.ntbkNewPrinter.set_current_page (self.PAGE_SELECT_INSTALL_METHOD)
        self.rbtnNPFoomatic.set_active (True)
        self.on_rbtnNPFoomatic_toggled (self.rbtnNPFoomatic)
        self.rbtnChangePPDKeepSettings.set_active (True)

        self._initialiseAutoVariables ()

    def _initialiseWidgetsForMode (self, mode_name):
        self.entNPName.set_text (self.makeNameUnique (mode_name))
        self.entNPName.grab_focus ()
        self.isSharedCbx.set_active(False)
        for widget in [self.entNPLocation,
                       self.entNPDescription,
                       self.entSMBURI, self.entSMBUsername,
                       self.entSMBPassword]:
            widget.set_text ('')

    def _initialiseDeviceFromURI (self):
        device_dict = { }
        self.device = cupshelpers.Device (self._device_uri, **device_dict)

    def _initialiseAutoVariables (self):
        self.auto_make = ""
        self.auto_model = ""
        self.auto_driver = None

    def change_ppd_got_devs (self, conn, result):
        self.fetchDevices_conn._end_operation ()
        self.fetchDevices_conn.destroy ()
        self.fetchDevices_conn = None
        self.dec_spinner_task ()
        if isinstance (result, Exception):
            current_devices = {}
        else:
            current_devices = result

        devid = None
        mm = None
        if self.devid != "":
            devid = self.devid
        else:
            device = current_devices.get (self.device.uri)
            if device:
                devid = device.id
                mm = device.make_and_model
                self.device = device

        # We'll also need the list of PPDs
        self.ntbkNewPrinter.set_current_page (self.PAGE_SELECT_INSTALL_METHOD)
        self.nextNPTab(step = 0)

    def on_ppdsloader_finished_next (self, ppdsloader):
        """
        This method is called when the PPDs loader has finished
        loading PPDs in preparation for the next screen the user will
        see, having clicked 'Forward'.  We are creating a new queue,
        and dialog_mode is either "printer" or "printer_with_uri".
        """

        self._getPPDs_reply (ppdsloader)
        if not self.ppds:
            return

        if ppdsloader._jockey_has_answered:
            self.searchedfordriverpackages = True

        debugprint ("Loaded PPDs this time; try nextNPTab again...")
        self.nextnptab_rerun = True
        if self.ntbkNewPrinter.get_current_page () == self.PAGE_SELECT_INSTALL_METHOD:
            self.nextNPTab (step = 0)
        else:
            self.nextNPTab ()

    # get PPDs

    def _getPPDs_reply (self, ppdsloader):
        exc = ppdsloader.get_error ()
        if exc:
            ppdsloader.destroy ()
            try:
                raise exc
            except cups.IPPError as e:
                (e, m) = e.args
                self.show_IPP_Error (e, m)
                return

        ppds = ppdsloader.get_ppds ()
        if ppds:
            self.ppds = ppds
            self.ppdsmatch_result = ppdsloader.get_ppdsmatch_result ()
            if ppdsloader._jockey_has_answered:
                self.installed_driver_files = ppdsloader.get_installed_files ()
        else:
            self.ppds = None
            self.ppdsmatch_result = None

        ppdsloader.destroy ()
        self.ppdsloader = None

    # Class members

    def fillNewClassMembers(self):
        model = self.tvNCMembers.get_model()
        model.clear()
        model = self.tvNCNotMembers.get_model()
        model.clear()
        try:
            self.printers = cupshelpers.getPrinters (self.cups)
        except cups.IPPError:
            self.printers = {}

        for printer in self.printers.keys():
            if not self.printers[printer].type & cups.CUPS_PRINTER_CLASS:
                model.append((printer,))

    def on_btnNCAddMember_clicked(self, button):
        moveClassMembers(self.tvNCNotMembers, self.tvNCMembers)
        self.btnNPApply.set_sensitive(
            bool(getCurrentClassMembers(self.tvNCMembers)))
        button.set_sensitive(False)

    def on_btnNCDelMember_clicked(self, button):
        moveClassMembers(self.tvNCMembers, self.tvNCNotMembers)
        self.btnNPApply.set_sensitive(
            bool(getCurrentClassMembers(self.tvNCMembers)))
        button.set_sensitive(False)

    def on_tvNCMembers_cursor_changed(self, widget):
        selection = widget.get_selection()
        if selection is None:
            return

        model_from, rows = selection.get_selected_rows()
        self.btnNCDelMember.set_sensitive(rows != [])

    def on_tvNCNotMembers_cursor_changed(self, widget):
        selection = widget.get_selection()
        if selection is None:
            return

        model_from, rows = selection.get_selected_rows()
        self.btnNCAddMember.set_sensitive(rows != [])

    # Navigation buttons

    def on_NPCancel(self, widget, event=None):
        if self.fetchDevices_conn:
            self.fetchDevices_conn.destroy ()
            self.fetchDevices_conn = None
            self.dec_spinner_task ()

        if self.ppdsloader:
            self.ppdsloader.destroy ()
            self.ppdsloader = None

        if self.printer_finder:
            self.printer_finder.cancel ()
            self.printer_finder = None
            self.dec_spinner_task ()

        self.NewPrinterWindow.hide()
        if self.opreq is not None:
            for handler in self.opreq_handlers:
                self.opreq.disconnect (handler)

            self.opreq_handlers = None
            self.opreq.cancel ()
            self.opreq = None

        self.device = None
        self.printers = {}
        self.emit ('dialog-canceled')
        return True

    def on_btnNPBack_clicked(self, widget):
        self.nextNPTab(-1)

    def on_btnNPForward_clicked(self, widget):
        self.nextNPTab()

    def installdriverpackage (self, driver):
        install_info = self._getDriverInstallationInfo (driver)
        if not install_info:
            return False

        name = install_info['name']
        repo = install_info['repo']
        keyid = install_info['keyid']

        fmt = _("Installing driver %s") % name
        self._installdialog = Gtk.MessageDialog (parent=self.NewPrinterWindow,
                                                 modal=True, destroy_with_parent=True,
                                                 type=Gtk.MessageType.INFO,
                                                 buttons=Gtk.ButtonsType.CANCEL,
                                                 text=fmt)

        self._installdialog.format_secondary_text (_("Installing ..."))
        # Add a progress bar to the message box
        dialogarea = self._installdialog.get_message_area()
        pbar = Gtk.ProgressBar()
        dialogarea.add(pbar)
        pbar.show()

        # Save a reference to the progress bar in the dialog, so that
        # we can easily reference it from do_installdriverpackage()
        self._installdialog._progress_bar = pbar

        self._installdialog.connect ("response", self._installdialog_response)
        self._installdialog.show_all ()

        # Perform the actual installation of the printer driver
        ret = self.do_installdriverpackage (name, repo, keyid)

        if self._installdialog:
            self._installdialog.hide ()
            self._installdialog.destroy ()
            self._installdialog = None

        return ret

    def do_installdriverpackage(self, name, repo, keyid):
        debugprint('Installing driver: %s; Repo: %s; Key ID: %s' %
                   (repr (name),
                    repr (repo),
                    repr (keyid)))

        # Do the installation with a command line helper script
        new_environ = os.environ.copy()
        new_environ['LC_ALL'] = "C"
        if keyid:
            args = ["install-printerdriver", name, repo, keyid]
        else:
            args = ["install-printerdriver", name, repo]
        debugprint ("Running command: " + repr(args))
        ret = True
        try:
            self.p = subprocess.Popen (args, env=new_environ, close_fds=True,
                                       stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE)
            # Keep the UI refreshed while we wait for
            # the drivers query to complete.
            (stdout, stderr) = (self.p.stdout, self.p.stderr)

            done = False
            pbar = self._installdialog._progress_bar
            while self.p.poll() is None:
                line = stdout.readline ().strip()
                if (len(line) > 0):
                    if line == "done":
                        done = True
                        break
                    elif line.startswith(b"P"):
                        try:
                            percentage = float(line[1:])
                            if percentage >= 0:
                                pbar.set_fraction(percentage/100)
                            else:
                                pbar.set_pulse_step(-percentage/100)
                                pbar.pulse()
                        except:
                            pass
                    else:
                        self.installed_driver_files.append(line.decode("utf-8"));
                while Gtk.events_pending ():
                    Gtk.main_iteration ()
                if not line:
                    time.sleep (0.1)
            if self.p.returncode != 0 and not done:
                ret = False
        except:
            # Problem executing command.
            ret = False

        if not ret:
            self.installed_driver_files = [];

        return ret

    def _getDriverInstallationInfo (self, driver):
        pkgs = driver.get('packages', {})
        arches = list(pkgs.keys())
        if len(arches) == 0:
            debugprint('No packages for driver')
            return None
        if len(arches) > 1:
            debugprint('Returned more than one matching architecture, please report this as a bug: %s' % repr (arches))
            return None

        pkgs = pkgs[arches[0]]

        if len(pkgs) != 1:
            debugprint('Returned more than one package, this is currently not handled')
            return None
        pkg = list(pkgs.keys())[0]

        name = ''
        if pkg.endswith('.deb'):
            name = pkg.split('_')[0]
        elif pkg.endswith('.rpm'):
            name = '-'.join(pkg.split('-')[0:-2])
        else:
            raise ValueError('Unknown package type: ' + pkg)

        # require signature for binary packages; architecture
        # independent packages are usually PPDs, which we trust enough
        keyid = None
        if 'fingerprint' not in pkgs[pkg]:
            if config.DOWNLOADABLE_PKG_ONLYSIGNED and arches[0] not in ['all', 'noarch']:
                debugprint('Not installing driver as it does not have a GPG fingerprint URL')
                return None
        else:
            keyid = download_gpg_fingerprint(pkgs[pkg]['fingerprint'])
            if config.DOWNLOADABLE_PKG_ONLYSIGNED and arches[0] not in ['all', 'noarch'] and not keyid:
                debugprint('Not installing driver as it does not have a valid GPG fingerprint')
                return None


        repo = pkgs[pkg].get('repositories', {}).get(self.packageinstaller)
        if not repo:
            debugprint('Local package system %s not found in %s' %
                       (self.packageinstaller,
                        repr (pkgs[pkg].get('repositories', {}))))
            return None

        # All good: return necessary information to install the driver
        return { 'name': name, 'repo': repo, 'keyid': keyid }

    def _installdialog_response (self, dialog, response):
        self.p.terminate ()

    def nextNPTab(self, step=1):
        page_nr = self.ntbkNewPrinter.get_current_page()
        debugprint ("Next clicked on page %d" % page_nr)

        keep_going = True
        if self.dialog_mode == "printer" or self.dialog_mode == "printer_with_uri" or \
              self.dialog_mode == "ppd" or self.dialog_mode == "download_driver":
            install_result = self._handlePrinterInstallationMode (step)
            if install_result == self.INSTALL_RESULT_OPS_PENDING:
                # Do not continue if the installation process says so
                # (e.g. waiting for a CUPS to return a list of PPDs)
                keep_going = False

        if not keep_going:
            debugprint ('Interrupting execution of nextNPTab(): Operations pending')
            return

        order = self._getPagesOrderForDialogMode ()
        next_page_nr = order[order.index(page_nr)+step]

        # fill Installable Options tab
        fetch_ppd = False
        try:
            if order.index (self.PAGE_APPLY) > -1:
                # There is a copy settings page in this set
                fetch_ppd = next_page_nr == self.PAGE_APPLY and step >= 0
        except ValueError:
            fetch_ppd = next_page_nr == self.PAGE_INSTALLABLE_OPTIONS and step >= 0

        debugprint ("Will fetch ppd? %d" % fetch_ppd)
        if fetch_ppd:
            self.ppd = self.getNPPPD()
            self.installable_options = False
            if self.ppd is None:
                return

            # Prepare Installable Options screen.
            if isinstance(self.ppd, cups.PPD):
                self.fillNPInstallableOptions()
            else:
                # Put a label there explaining why the page is empty.
                ppd = self.ppd
                self.ppd = None
                self.fillNPInstallableOptions()
                self.ppd = ppd

            if not self.installable_options:
                if next_page_nr == self.PAGE_INSTALLABLE_OPTIONS:
                    # step over if empty
                    next_page_nr = order[order.index(next_page_nr)+1]

        # Step over empty Installable Options tab when moving backwards.
        if next_page_nr == self.PAGE_INSTALLABLE_OPTIONS and \
                not self.installable_options and step < 0:
            next_page_nr = order[order.index(next_page_nr)-1]

        debugprint ("Will advance to page %d" % next_page_nr)
        if step >= 0 and next_page_nr == self.PAGE_DOWNLOAD_DRIVER: # About to show downloadable drivers
            self.fillDownloadableDrivers ()

        if step >= 0 and next_page_nr == self.PAGE_DESCRIBE_PRINTER: # About to choose a name.
            # Suggest an appropriate name.
            name = None
            descr = None

            try:
                if (self.device.id and
                    not self.device.type in ("socket", "lpd", "ipp",
                                             "http", "https", "bluetooth")):
                    name = "%s %s" % (self.device.id_dict["MFG"], 
                                      self.device.id_dict["MDL"])
            except:
                nonfatalException ()

            try:
                if name is None and isinstance (self.ppd, cups.PPD):
                    mname = self.ppd.findAttr ("modelName").value
                    make, model = cupshelpers.ppds.ppdMakeModelSplit (mname)
                    if make and model:
                        name = "%s %s" % (make, model)
                    elif make or model:
                        name = "%s%s" % (make, model)
            except:
                nonfatalException ()

            if name:
                descr = name
            else:
                name = 'printer'

            name = self.makeNameUnique (name)
            self.entNPName.set_text (name)

            if descr:
                self.entNPDescription.set_text (descr)

        self.ntbkNewPrinter.set_current_page(next_page_nr)

        self.setNPButtons()


    def _getPagesOrderForDialogMode (self):
        order = []
        if self.dialog_mode == "class":
            order = [
                self.PAGE_DESCRIBE_PRINTER,
                self.PAGE_CHOOSE_CLASS_MEMBERS,
                self.PAGE_APPLY,
            ]
        elif self.dialog_mode == "download_driver":
            order = [
                self.PAGE_DOWNLOAD_DRIVER
            ]
        elif self.dialog_mode == "printer":
            if self.remotecupsqueue:
                order = [
                    self.PAGE_SELECT_DEVICE,
                    self.PAGE_DESCRIBE_PRINTER
                ]
            elif (self.founddownloadabledrivers and
                  not self.rbtnNPDownloadableDriverSearch.get_active()):
                if self.exactdrivermatch:
                    order = [
                        self.PAGE_SELECT_DEVICE,
                        self.PAGE_DOWNLOAD_DRIVER,
                        self.PAGE_INSTALLABLE_OPTIONS,
                        self.PAGE_DESCRIBE_PRINTER
                    ]
                else:
                    order = [
                        self.PAGE_SELECT_DEVICE,
                        self.PAGE_DOWNLOAD_DRIVER,
                        self.PAGE_SELECT_INSTALL_METHOD,
                        self.PAGE_CHOOSE_DRIVER_FROM_DB,
                        self.PAGE_INSTALLABLE_OPTIONS,
                        self.PAGE_DESCRIBE_PRINTER
                    ]
            elif (self.exactdrivermatch and
                  not self.rbtnNPDownloadableDriverSearch.get_active()):
                order = [
                    self.PAGE_SELECT_DEVICE,
                    self.PAGE_INSTALLABLE_OPTIONS,
                    self.PAGE_DESCRIBE_PRINTER
                ]
            elif self.rbtnNPFoomatic.get_active():
                order = [
                    self.PAGE_SELECT_DEVICE,
                    self.PAGE_SELECT_INSTALL_METHOD,
                    self.PAGE_CHOOSE_DRIVER_FROM_DB,
                    self.PAGE_INSTALLABLE_OPTIONS,
                    self.PAGE_DESCRIBE_PRINTER
                ]
            elif self.rbtnNPPPD.get_active():
                order = [
                    self.PAGE_SELECT_DEVICE,
                    self.PAGE_SELECT_INSTALL_METHOD,
                    self.PAGE_INSTALLABLE_OPTIONS,
                    self.PAGE_DESCRIBE_PRINTER
                ]
            else:
                # Downloadable driver
                order = [
                    self.PAGE_SELECT_DEVICE,
                    self.PAGE_SELECT_INSTALL_METHOD,
                    self.PAGE_DOWNLOAD_DRIVER,
                    self.PAGE_INSTALLABLE_OPTIONS,
                    self.PAGE_DESCRIBE_PRINTER
                ]
        elif self.dialog_mode == "ppd":
            if self.rbtnNPFoomatic.get_active():
                order = [
                    self.PAGE_SELECT_INSTALL_METHOD,
                    self.PAGE_CHOOSE_DRIVER_FROM_DB,
                    self.PAGE_APPLY,
                    self.PAGE_INSTALLABLE_OPTIONS
                ]
            elif self.rbtnNPPPD.get_active():
                order = [
                    self.PAGE_SELECT_INSTALL_METHOD,
                    self.PAGE_APPLY,
                    self.PAGE_INSTALLABLE_OPTIONS
                ]
            else:
                # Downloadable driver
                order = [
                    self.PAGE_SELECT_INSTALL_METHOD,
                    self.PAGE_DOWNLOAD_DRIVER,
                    self.PAGE_APPLY,
                    self.PAGE_INSTALLABLE_OPTIONS
                ]
        elif self.dialog_mode == "device":
            order = [
                self.PAGE_SELECT_DEVICE,
            ]
        else: # dialog_mode == "printer-from-uri"
            if self.remotecupsqueue:
                order = [
                    self.PAGE_DESCRIBE_PRINTER,
                ]
            elif (self.founddownloadabledrivers and
                  not self.rbtnNPDownloadableDriverSearch.get_active()):
                if self.exactdrivermatch:
                    order = [
                        self.PAGE_DOWNLOAD_DRIVER,
                        self.PAGE_INSTALLABLE_OPTIONS,
                        self.PAGE_DESCRIBE_PRINTER
                    ]
                else:
                    order = [
                        self.PAGE_DOWNLOAD_DRIVER,
                        self.PAGE_SELECT_INSTALL_METHOD,
                        self.PAGE_CHOOSE_DRIVER_FROM_DB,
                        self.PAGE_INSTALLABLE_OPTIONS,
                        self.PAGE_DESCRIBE_PRINTER
                    ]
            elif (self.exactdrivermatch and
                  not self.rbtnNPDownloadableDriverSearch.get_active()):
                order = [
                    self.PAGE_INSTALLABLE_OPTIONS,
                    self.PAGE_DESCRIBE_PRINTER
                ]
            elif self.rbtnNPFoomatic.get_active():
                order = [
                    self.PAGE_SELECT_INSTALL_METHOD,
                    self.PAGE_CHOOSE_DRIVER_FROM_DB,
                    self.PAGE_INSTALLABLE_OPTIONS,
                    self.PAGE_DESCRIBE_PRINTER
                ]
            elif self.rbtnNPPPD.get_active():
                order = [
                    self.PAGE_SELECT_INSTALL_METHOD,
                    self.PAGE_INSTALLABLE_OPTIONS,
                    self.PAGE_DESCRIBE_PRINTER
                ]
            else:
                # Downloadable driver
                order = [
                    self.PAGE_SELECT_INSTALL_METHOD,
                    self.PAGE_DOWNLOAD_DRIVER,
                    self.PAGE_INSTALLABLE_OPTIONS,
                    self.PAGE_DESCRIBE_PRINTER
                ]
        return order

    def _handlePrinterInstallationMode (self, step):
        busy (self.NewPrinterWindow)

        page_nr = self.ntbkNewPrinter.get_current_page ()
        page_nr = self.ntbkNewPrinter.get_current_page ()

        # Let's assume everything will be completed by default
        result = self.INSTALL_RESULT_DONE

        if (((page_nr == self.PAGE_SELECT_DEVICE or
              page_nr == self.PAGE_DOWNLOAD_DRIVER) and step > 0) or
            ((page_nr == self.PAGE_SELECT_INSTALL_METHOD or
              page_nr == self.PAGE_DOWNLOAD_DRIVER) and step == 0)):
            # The function below will return INSTALL_RESULT_OPS_PENDING
            # if, for some reason, it spawns an asynchronous operation
            # and needs to wait for its results before continuing.
            result = self._handlePrinterInstallationStage (page_nr, step)

        if page_nr == self.PAGE_CHOOSE_DRIVER_FROM_DB:
            if not self.device.id:
                # Choose an appropriate name when no Device ID
                # is available, based on the model the user has
                # selected.
                try:
                    model, iter = self.tvNPModels.get_selection ().\
                                  get_selected ()
                    name = model.get(iter, 0)[0]
                    name = self.makeNameUnique (name)
                    self.entNPName.set_text (name)
                except:
                    nonfatalException ()

        ready (self.NewPrinterWindow)
        return result

    def _handlePrinterInstallationStage (self, page_nr, step):
        if self.dialog_mode != "download_driver":
            uri = self.device.uri
            if uri and uri.startswith ("smb"):
                # User has selected an smb device
                uri = SMBURI (uri=uri[6:]).sanitize_uri ()
                self._installSMBBackendIfNeeded ()

        if page_nr == self.PAGE_SELECT_DEVICE or page_nr == self.PAGE_SELECT_INSTALL_METHOD:
            self._selectDeviceForInstallation (uri)
        elif page_nr == self.PAGE_DOWNLOAD_DRIVER and self.nextnptab_rerun == False:
            self._handleDriverInstallation ()

        devid = None
        if not self.remotecupsqueue or self.dialog_mode == "ppd":
            if self.dialog_mode != "download_driver":
                devid = self.device.id # ID of selected device
            if not devid:
                devid = self.devid # ID supplied at init()
            if not devid:
                devid = None

            if self.ppds is None and self.dialog_mode != "download_driver":
                self._loadPPDsForDevice (devid, uri)
                # _loadPPDsForDevice () is an asynchronous operation, so
                # let the caller know that it can't continue for now.
                return self.INSTALL_RESULT_OPS_PENDING

        self.nextnptab_rerun = False
        if page_nr == self.PAGE_SELECT_DEVICE or page_nr == self.PAGE_SELECT_INSTALL_METHOD:
            self._installHPScannerFilesIfNeeded ()

        return self._installPrinterFromDeviceID (devid, page_nr, step)

    def _installSMBBackendIfNeeded (self):
        # Does the backend need to be installed?
        if (self.nextnptab_rerun == False and not self.searchedfordriverpackages and
               (self._host == 'localhost' or self._host[0] == '/') and
               not os.access ("/usr/lib/cups/backend/smb", os.F_OK)):
            debugprint ("No smb backend so attempting install")
            try:
                pk = installpackage.PackageKit ()
                # The following call means a blocking, synchronous, D-Bus call
                pk.InstallPackageName (0, 0, "samba-client")
            except:
                nonfatalException ()

    def _selectDeviceForInstallation (self, uri):
        self._initialiseAutoVariables ()
        self.device.uri = self.getDeviceURI ()

        # Cancel the printer finder now as the user has
        # already selected their device.
        if self.fetchDevices_conn:
            self.fetchDevices_conn.destroy ()
            self.fetchDevices_conn = None
            self.dec_spinner_task ()
        if self.printer_finder:
            self.printer_finder.cancel ()
            self.printer_finder = None
            self.dec_spinner_task ()

        if (not self.device.id and
            self.device.type in ["socket", "lpd", "ipp"]):
            # This is a network printer whose model we don't yet know.
            # Try to discover it.
            self.getNetworkPrinterMakeModel ()

        # Try to access the PPD, in this case our detected IPP
        # printer is a queue on a remote CUPS server which is
        # not automatically set up on our local CUPS server
        # (for example DNS-SD broadcasted queue from Mac OS X)
        self.remotecupsqueue = None
        res = re.search (r"ipp://(\S+?)(:\d+|)/printers/(\S+)", uri)
        if res:
            resg = res.groups()
            if len (resg[1]) > 0:
                port = int (resg[1][1:])
            else:
                port = 631
            try:
                debugprint('Download ppd file from remote server')
                conn = http.client.HTTPConnection(resg[0], port)
                conn.request("GET", "/printers/%s.ppd" % resg[2])
                resp = conn.getresponse()
                if resp.status == 200:
                    self.remotecupsqueue = resg[2]

                ppdcontent = resp.read()

                with tempfile.NamedTemporaryFile () as tmpf:
                    tmpf.write(ppdcontent)
                    tmpf.flush()
                    try:
                        ppd = cups.PPD(tmpf.name)
                    except (cups.IPPError, RuntimeError):
                        raise IOError("Server's ppd file is corrupted.")
            except:
                pass

            # We also want to fetch the printer-info and
            # printer-location attributes, to pre-fill those
            # fields for this new queue.
            try:
                encryption = cups.HTTP_ENCRYPT_IF_REQUESTED
                c = cups.Connection (host=resg[0],
                                     port=port,
                                     encryption=encryption)

                r = ['printer-info', 'printer-location']
                attrs = c.getPrinterAttributes (uri=uri,
                                                requested_attributes=r)
                info = attrs.get ('printer-info', '')
                location = attrs.get ('printer-location', '')
                if len (info) > 0:
                    self.entNPDescription.set_text (info)
                if len (location) > 0:
                    self.device.location = location
            except RuntimeError:
                pass
            except:
                nonfatalException ()
        elif ((uri.startswith ("dnssd:") or uri.startswith("mdns:")) and
                uri.find ("/cups") != -1 and self.device.info):
            # Remote CUPS queue discovered by "dnssd" CUPS backend
            self.remotecupsqueue = self.device.info

    def _handleDriverInstallation (self):
        # Install package of the driver found on OpenPrinting
        treeview = self.tvNPDownloadableDrivers
        model, iter = treeview.get_selection ().get_selected ()
        driver = None
        if iter is not None:
            driver = model.get_value (iter, 1)
        if driver is None or driver == 0 or 'packages' not in driver:
            return

        # Find the package name, repository, and fingerprint
        # and install the package
        result = self.installdriverpackage (driver)
        if not result or len(self.installed_driver_files) == 0:
          return

        # We actually installed a package, delete the
        # PPD list to get it regenerated
        self.ppds = None

        if (self.dialog_mode != "download_driver" and
              (not self.device.id and
              (not self.device.make_and_model or self.device.make_and_model == "Unknown") and
              self.downloadable_driver_for_printer)):
            self.device.make_and_model = self.downloadable_driver_for_printer

    def _installHPScannerFilesIfNeeded (self):
        if (hasattr (self.device, 'hp_scannable') and self.device.hp_scannable and
                not os.access ("/etc/sane.d/dll.d/hpaio", os.R_OK) and
                not os.access ("/etc/sane.d/dll.d/hplip", os.R_OK)):
            debugprint ("No HPLIP sane backend so "
                        "attempting install")
            try:
                pk = installpackage.PackageKit ()
                # The following call means a blocking, synchronous, D-Bus call
                pk.InstallPackageName (0, 0, "libsane-hpaio")
            except:
                pass

    def _loadPPDsForDevice (self, devid, uri):
        debugprint ("nextNPTab: need PPDs loaded")
        p = ppdsloader.PPDsLoader (device_id=devid,
                                   device_uri=uri,
                                   parent=self.NewPrinterWindow,
                                   host=self._host,
                                   encryption=self._encryption)
        self.ppdsloader = p
        p.connect ('finished',self.on_ppdsloader_finished_next)
        p.run ()

    def _installPrinterFromDeviceID (self, devid, page_nr, step):
        ppdname = None
        self.id_matched_ppdnames = []
        try:
            if self.dialog_mode == "download_driver":
                ppdname = "download"
                status = "generic"
            elif self.remotecupsqueue:
                # We have a remote CUPS queue, let the client queue
                # stay raw so that the driver on the server gets used
                if self.ppd is None:
                    ppdname = 'raw'
                    self.ppd = ppdname
                name = self.remotecupsqueue
                name = self.makeNameUnique (name)
                self.entNPName.set_text (name)
                status = "exact"
            elif (self.device.id or
                  (self.device.make_and_model and
                   self.device.make_and_model != "Unknown") or
                  devid):
                if self.device.id:
                    id_dict = self.device.id_dict
                elif devid:
                    id_dict = cupshelpers.parseDeviceID (devid)
                else:
                    id_dict = {}
                    (id_dict["MFG"],
                     id_dict["MDL"]) = cupshelpers.ppds.\
                         ppdMakeModelSplit (self.device.make_and_model)
                    id_dict["DES"] = ""
                    id_dict["CMD"] = []
                    devid = "MFG:%s;MDL:%s;" % (id_dict["MFG"],
                                                id_dict["MDL"])

                fit = self.ppds.\
                    getPPDNamesFromDeviceID (id_dict["MFG"],
                                             id_dict["MDL"],
                                             id_dict["DES"],
                                             id_dict["CMD"],
                                             self.device.uri,
                                             self.device.make_and_model)
                debugprint ("Suitable PPDs found: %s" % repr(fit))
                ppdnamelist = self.ppds.\
                    orderPPDNamesByPreference (list(fit.keys ()),
                                               self.installed_driver_files,
                                               devid=id_dict, fit=fit)
                debugprint ("PPDs in priority order: %s" % repr(ppdnamelist))
                self.id_matched_ppdnames = ppdnamelist
                ppdname = ppdnamelist[0]
                status = fit[ppdname]
            elif (self.dialog_mode == "ppd" and self.orig_ppd):
                attr = self.orig_ppd.findAttr("NickName")
                if not attr:
                    attr = self.orig_ppd.findAttr("ModelName")

                if attr and attr.value:
                    value = attr.value
                    if value.endswith (" (recommended)"):
                        value = value[:-14]

                    mfgmdl = cupshelpers.ppds.ppdMakeModelSplit (value)
                    (make, model) = mfgmdl

                    # Search for ppdname with that make-and-model
                    ppds = self.ppds.getInfoFromModel (make, model)
                    for ppd, info in ppds.items ():
                        if (_singleton (info.
                                        get ("ppd-make-and-model")) ==
                            value):
                            ppdname = ppd
                            break
                if ppdname:
                    status = "exact"
                else:
                    ppdname = 'raw'
                    self.ppd = ppdname
                    status = "generic"
            elif self.dialog_mode == "ppd":
                # Special CUPS names for a raw queue.
                ppdname = 'raw'
                self.ppd = ppdname
                status = "exact"
            else:
                (status, ppdname) = self.ppds.\
                    getPPDNameFromDeviceID ("Generic",
                                            "Printer",
                                            "Generic Printer",
                                            [],
                                            self.device.uri)
                status = "generic"
        except:
            nonfatalException ()

        if (ppdname and
            (not self.remotecupsqueue or self.dialog_mode == "ppd")):
            return self._installPrinterOrSearchForDriver (devid, ppdname, status, page_nr, step)

        # No operations are pending if reached.
        return self.INSTALL_RESULT_DONE

    def _installPrinterOrSearchForDriver (self, devid, ppdname, status, page_nr, step):
        try:
            if ppdname != "download":
                ppddict = self.ppds.getInfoFromPPDName (ppdname)
                make_model = _singleton (ppddict['ppd-make-and-model'])
                (make, model) = \
                    cupshelpers.ppds.ppdMakeModelSplit (make_model)
                self.auto_make = make
                self.auto_model = model
                self.auto_driver = ppdname
                self.fillDriverList(make, model)
            if ((status == "exact" or status == "exact-cmd") and \
                self.dialog_mode != "ppd"):
                self.exactdrivermatch = True
                if step == 0:
                    page_nr = self.PAGE_INSTALLABLE_OPTIONS;
            else:
                self.exactdrivermatch = False
                if (self.dialog_mode != "ppd" and
                    self.searchedfordriverpackages == False and
                    devid and len(devid) > 0 and
                    not (devid.find("MFG:generic;") >= 0 or
                         devid.find("MFG:Generic;") >= 0 or
                         devid.find("MFG:unknown") >= 0 or
                         devid.find("MFG:Unknown") >= 0 or
                         devid.find("MDL:unknown") >= 0 or
                         devid.find("MDL:Unknown") >= 0 or
                         devid.find("MFG:;") >= 0 or
                         devid.find("MDL:;") >= 0)):
                    # Query driver packages and PPD files on
                    # OpenPrinting
                    debugprint ("nextNPTab: No exact driver match, querying OpenPrinting")
                    debugprint ('nextNPTab: Searching for "%s"' % devid)
                    self.searchedfordriverpackages = True

                    self._searchdialog_canceled = False
                    fmt = _("Searching")
                    self._searchdialog = Gtk.MessageDialog (
                        parent=self.NewPrinterWindow,
                        modal=True,
                        destroy_with_parent=True,
                        message_type=Gtk.MessageType.INFO,
                        buttons=Gtk.ButtonsType.CANCEL,
                        text=fmt)

                    self._searchdialog.format_secondary_text (
                        _("Searching for drivers"))

                    self.opreq = OpenPrintingRequest ()
                    self._searchdialog.connect (
                        "response", self._searchdialog_response)
                    self._searchdialog.show_all ()

                    self.opreq_handlers = []
                    self.opreq_handlers.append (
                        self.opreq.connect (
                            'finished',
                            self.opreq_id_search_done))
                    self.opreq_handlers.append (
                        self.opreq.connect (
                            'error',
                            self.opreq_id_search_error))
                    self.opreq_user_search = False
                    self.opreq.searchPrinters (devid)

                    # Searching for drivers in OpenPrinting takes times, so
                    # let the caller know that it can't continue for now.
                    return self.INSTALL_RESULT_OPS_PENDING
        except:
            nonfatalException ()

        if (self.dialog_mode == "ppd" or
                (self.dialog_mode != "download_driver" and
                 not self.remotecupsqueue and page_nr != self.PAGE_DOWNLOAD_DRIVER)):
            self.fillMakeList()

        # No operations are pending if reached.
        return self.INSTALL_RESULT_DONE

    def _searchdialog_response (self, dialog, response):
        # Cancel clicked while performing openprinting search

        self.btnNPDownloadableDriverSearch.set_sensitive (True)
        self.btnNPDownloadableDriverSearch_label.set_text (_("Search"))

        self.installed_driver_files = []
        self.searchedfordriverpackages = True
        self.founddownloadabledrivers = False
        self.founddownloadableppd = False

        ready (self.NewPrinterWindow)

        # Cancel the openprinting request.
        GLib.idle_add (self.opreq.cancel)

    def opreq_id_search_done (self, opreq, printers, drivers):
        for handler in self.opreq_handlers:
            opreq.disconnect (handler)

        Gdk.threads_enter ()

        try:
            self.opreq_user_search = False
            self.opreq_handlers = None
            self.opreq = None
            self._searchdialog.hide ()
            self._searchdialog.destroy ()
            self._searchdialog = None

            # Check whether we have found something
            if len (printers) < 1:
                # No.
                ready (self.NewPrinterWindow)

                self.founddownloadabledrivers = False
                if self.dialog_mode == "download_driver":
                    self.on_NPCancel(None)
                else:
                    self.nextNPTab ()
            else:
                self.downloadable_printers = printers
                self.downloadable_drivers = drivers
                self.founddownloadabledrivers = True

                try:
                    self.NewPrinterWindow.show()
                    self.setNPButtons()
                    if not self.fillDownloadableDrivers():
                        ready (self.NewPrinterWindow)

                        self.founddownloadabledrivers = False
                        if self.dialog_mode == "download_driver":
                            self.on_NPCancel(None)
                        else:
                            self.nextNPTab ()
                    else:
                        if self.dialog_mode == "download_driver":
                            self.nextNPTab (step = 0)
                        else:
                            self.nextNPTab ()
                except:
                    nonfatalException ()
                    self.nextNPTab ()

        finally:
            Gdk.threads_leave ()

    def opreq_id_search_error (self, opreq, status, err):
        debugprint ("OpenPrinting request failed (%d): %s" % (status,
                                                              repr (err)))
        self.opreq_id_search_done (opreq, list(), dict())


    def _installSelectedDriverFromOpenPrinting(self):
        # Install package of the driver found on OpenPrinting
        treeview = self.tvNPDownloadableDrivers
        model, iter = treeview.get_selection ().get_selected ()
        driver = None
        if iter is not None:
            driver = model.get_value (iter, 1)
        if (driver is None or driver == 0 or 'packages' not in driver):
            return

        # Find the package name, repository, and fingerprint
        # and install the package
        if not self.installdriverpackage (driver) or \
                len(self.installed_driver_files) <= 0:
            return

        # We actually installed a package, delete the
        # PPD list to get it regenerated
        self.ppds = None
        if self.dialog_mode != "download_driver":
            if (not self.device.id and
                (not self.device.make_and_model or
                 self.device.make_and_model ==
                 "Unknown") and
                self.downloadable_driver_for_printer):
                self.device.make_and_model = \
                    self.downloadable_driver_for_printer

    def setNPButtons(self):
        nr = self.ntbkNewPrinter.get_current_page()

        if self.dialog_mode == "device":
            self.btnNPBack.hide()
            self.btnNPForward.hide()
            self.btnNPApply.show()
            try:
                uri = self.getDeviceURI ()
                valid = validDeviceURI (uri)
            except AttributeError:
                # No device selected yet.
                valid = False
            self.btnNPApply.set_sensitive (valid)
            return

        if self.dialog_mode == "ppd":
            if nr == self.PAGE_APPLY:
                if not self.installable_options:
                    # There are no installable options, so this is the
                    # last page.
                    debugprint ("No installable options")
                    self.btnNPForward.hide ()
                    self.btnNPApply.show ()
                else:
                    self.btnNPForward.show ()
                    self.btnNPApply.hide ()
                return
            elif nr == self.PAGE_INSTALLABLE_OPTIONS:
                self.btnNPForward.hide()
                self.btnNPApply.show()
                return
            else:
                self.btnNPForward.show()
                self.btnNPApply.hide()
            if nr == self.PAGE_SELECT_INSTALL_METHOD:
                self.btnNPBack.hide()
                self.btnNPForward.show()
                downloadable_selected = False
                if self.rbtnNPDownloadableDriverSearch.get_active ():
                    combobox = self.cmbNPDownloadableDriverFoundPrinters
                    iter = combobox.get_active_iter ()
                    if iter and combobox.get_model ().get_value (iter, 1):
                        downloadable_selected = True

                self.btnNPForward.set_sensitive(bool(
                        (self.rbtnNPFoomatic.get_active() and
                         self.tvNPMakes.get_cursor()[0] is not None) or
                        self.filechooserPPD.get_filename() or
                        downloadable_selected))
                return
            else:
                self.btnNPBack.show()

        if self.dialog_mode == "download_driver":
            self.btnNPBack.hide()
            self.btnNPForward.hide()
            self.btnNPApply.show()

            accepted = self._is_driver_license_accepted()
            self.btnNPApply.set_sensitive(accepted)
            return

        # class/printer

        if nr == self.PAGE_SELECT_DEVICE:
            valid = False
            try:
                uri = self.getDeviceURI ()
                valid = validDeviceURI (uri)
            except:
                nonfatalException ()
            self.btnNPForward.set_sensitive(valid)
            self.btnNPBack.hide ()
        else:
            self.btnNPBack.show()

        self.btnNPForward.show()
        self.btnNPApply.hide()

        if nr == self.PAGE_DESCRIBE_PRINTER:
            self.btnNPBack.show()
            if self.dialog_mode == "printer" or \
                    self.dialog_mode == "printer_with_uri":
                self.btnNPForward.hide()
                self.btnNPApply.show()
                self.btnNPApply.set_sensitive(
                    checkNPName(self.printers, self.entNPName.get_text()))
            if self.dialog_mode == "class":
                # This is the first page for the New Class dialog, so
                # hide the Back button.
                self.btnNPBack.hide ()
            if self.dialog_mode == "printer_with_uri" and \
                    (self.remotecupsqueue or \
                         (self.exactdrivermatch and \
                              not self.installable_options)):
                self.btnNPBack.hide ()
        if nr == self.PAGE_SELECT_INSTALL_METHOD:
            downloadable_selected = False
            if self.rbtnNPDownloadableDriverSearch.get_active ():
                combobox = self.cmbNPDownloadableDriverFoundPrinters
                iter = combobox.get_active_iter ()
                if iter and combobox.get_model ().get_value (iter, 1):
                    downloadable_selected = True

            self.btnNPForward.set_sensitive(bool(
                self.rbtnNPFoomatic.get_active() or
                self.filechooserPPD.get_filename() or
                downloadable_selected))
            # If we have an auto-detected printer for which there was no
            # driver found, we have already the URI and so this step is
            # not needed in the wizard. This makes manufacturer?PPD selection
            # the first step
            if self.dialog_mode == "printer_with_uri":
                self.btnNPBack.hide()
        if nr == self.PAGE_CHOOSE_DRIVER_FROM_DB:
            model, iter = self.tvNPDrivers.get_selection().get_selected()
            self.btnNPForward.set_sensitive(bool(iter))
        if nr == self.PAGE_CHOOSE_CLASS_MEMBERS:
            self.btnNPForward.hide()
            self.btnNPApply.show()
            self.btnNPApply.set_sensitive(
                bool(getCurrentClassMembers(self.tvNCMembers)))
        if nr == self.PAGE_INSTALLABLE_OPTIONS:
            if self.dialog_mode == "printer_with_uri" and \
                    self.exactdrivermatch:
                self.btnNPBack.hide ()
        if nr == self.PAGE_DOWNLOAD_DRIVER:
            accepted = self._is_driver_license_accepted()
            self.btnNPForward.set_sensitive(accepted)

    def _is_driver_license_accepted(self):
        current_page = self.ntbkNPDownloadableDriverProperties.get_current_page()
        if current_page == self.PAGE_SELECT_DEVICE:
            return self.rbtnNPDownloadLicenseYes.get_active ()

        treeview = self.tvNPDownloadableDrivers
        model, iter = treeview.get_selection ().get_selected ()
        if not iter:
            path, column = treeview.get_cursor()
            if path:
                iter = model.get_iter (path)
        return iter is not None

    def on_entNPName_changed(self, widget):
        # restrict
        text = widget.get_text()
        new_text = text
        new_text = new_text.replace("/", "")
        new_text = new_text.replace("#", "")
        new_text = new_text.replace(" ", "")
        if text!=new_text:
            widget.set_text(new_text)
        if self.dialog_mode == "printer":
            self.btnNPApply.set_sensitive(
                checkNPName(self.printers, new_text))
        else:
            self.btnNPForward.set_sensitive(
                checkNPName(self.printers, new_text))

    def fetchDevices(self, network=False, current_uri=None):
        debugprint ("fetchDevices")
        self.inc_spinner_task ()

        # Search for Bluetooth printers together with the network printers
        # as the Bluetooth search takes rather long time
        network_schemes = ["dnssd", "snmp", "driverless", "bjnp", "bluetooth"]
        error_handler = self.error_getting_devices
        if network == False:
            reply_handler = (lambda x, y:
                                 self.local_devices_reply (x, y,
                                                           current_uri))
            cupshelpers.getDevices (self.fetchDevices_conn,
                                    exclude_schemes=network_schemes,
                                    reply_handler=reply_handler,
                                    error_handler=error_handler)
        else:
            reply_handler = (lambda x, y:
                                 self.network_devices_reply (x, y,
                                                             current_uri))
            cupshelpers.getDevices (self.fetchDevices_conn,
                                    include_schemes=network_schemes,
                                    reply_handler=reply_handler,
                                    error_handler=error_handler)

    def error_getting_devices (self, conn, exc):
        # Just ignore the error.
        debugprint ("Error fetching devices: %s" % repr (exc))
        self.dec_spinner_task ()
        self.fetchDevices_conn._end_operation ()
        self.fetchDevices_conn.destroy ()
        self.fetchDevices_conn = None

    def local_devices_reply (self, conn, result, current_uri):
        self.dec_spinner_task ()

        # Now we've got the local devices, start a request for the
        # network devices.
        self.fetchDevices (network=True, current_uri=current_uri)

        # Add the local devices to the list.
        self.add_devices (result, current_uri)

    def network_devices_reply (self, conn, result, current_uri):
        self.fetchDevices_conn._end_operation ()
        self.fetchDevices_conn.destroy ()
        self.fetchDevices_conn = None

        # Add the network devices to the list.
        no_more = True
        need_resolving = {}
        for uri, device in result.items ():
            if uri.startswith ("dnssd://"):
                need_resolving[uri] = device
                no_more = False

        for uri in need_resolving.keys ():
            del result[uri]

        self.add_devices (result, current_uri, no_more=no_more)

        if len (need_resolving) > 0:
            resolver = dnssdresolve.DNSSDHostNamesResolver (need_resolving)
            self.inc_spinner_task ()
            resolver.resolve (reply_handler=lambda devices:
                                  self.dnssd_resolve_reply (current_uri,
                                                            devices))

        self.dec_spinner_task ()
        self.check_firewall ()

    def dnssd_resolve_reply (self, current_uri, devices):
        self.add_devices (devices, current_uri, no_more=True)
        self.dec_spinner_task ()
        self.check_firewall ()

    def get_hpfax_device_id(self, faxuri):
        new_environ = os.environ.copy()
        new_environ['LC_ALL'] = "C"
        new_environ['DISPLAY'] = ""
        args = ["hp-info", "-x", "-i", "-d" + faxuri]
        debugprint (faxuri + ": " + repr(args))
        try:
            p = subprocess.Popen (args, env=new_environ, close_fds=True,
                                  stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
            (stdout, stderr) = p.communicate ()
        except:
            # Problem executing command.
            return None

        faxtype = -1
        for line in stdout.decode ().split ("\n"):
            if line.find ("fax-type") == -1:
                continue
            res = re.search (r"(\d+)", line)
            if res:
                resg = res.groups()
                try:
                    faxtype = int(resg[0])
                except:
                    faxtype = -1
            if faxtype >= 0:
                break
        if faxtype <= 0:
            return None
        elif faxtype == 4:
            return 'MFG:HP;MDL:Fax 2;DES:HP Fax 2;'
        else:
            return 'MFG:HP;MDL:Fax;DES:HP Fax;'

    def get_hplip_scan_type_for_uri(self, uri):
        args = ["hp-query", "-k", "scan-type", "-d", uri]
        debugprint (uri + ": " + repr(args))
        try:
            p = subprocess.Popen (args, close_fds=True,
                                  stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
            (stdout, stderr) = p.communicate ()
            if p.returncode != 0:
                return None
        except:
            # Problem executing command.
            return None

        scan_type = stdout.decode ().strip ()
        fields = scan_type.split ("=", 1)
        if len (fields) < 2:
            return None

        value = fields[1]
        if value == '0':
            return None

        return value

    def get_hplip_uri_for_network_printer(self, host, mode):
        if mode == "print": mod = "-c"
        elif mode == "fax": mod = "-f"
        else: mod = "-c"
        args = ["hp-makeuri", mod, host]
        debugprint (host + ": " + repr(args))
        uri = None
        try:
            p = subprocess.Popen (args, close_fds=True,
                                  stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
            (stdout, stderr) = p.communicate ()
            if p.returncode != 0:
                return None
        except:
            # Problem executing command.
            return None

        uri = stdout.decode ().strip ()
        return uri

    def getNetworkPrinterMakeModel(self, host=None, device=None):
        """
        Try to determine the make and model for the currently selected
        network printer, and store this in the data structure for the
        printer.
        Returns (hostname or None, uri or None).
        """
        uri = None
        if device is None:
            device = self.device
        # Determine host name/IP
        if host is None:
            s = device.uri.find ("://")
            if s != -1:
                s += 3
                e = device.uri[s:].find (":")
                if e == -1: e = device.uri[s:].find ("/")
                if e == -1: e = device.uri[s:].find ("?")
                if e == -1: e = len (device.uri)
                host = device.uri[s:s+e]
        # Try to get make and model via SNMP
        if host:
            args = ["/usr/lib/cups/backend/snmp", host]
            debugprint (host + ": " + repr(args))
            stdout = None
            try:
                p = subprocess.Popen (args, close_fds=True,
                                      stdin=subprocess.DEVNULL,
                                      stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE)
                (stdout, stderr) = p.communicate ()
                if p.returncode != 0:
                    stdout = None
            except:
                # Problem executing command.
                pass

            if stdout is not None:
                try:
                    line = stdout.decode ('utf-8').strip ()
                except UnicodeDecodeError:
                    # Work-around snmp backend output encoded as iso-8859-1 (despire RFC 2571).
                    # If it's neither iso-8859-1, make a best guess by ignoring problematic bytes.
                    line = stdout.decode (encoding='iso-8859-1', errors='ignore').strip ()
                words = probe_printer.wordsep (line)
                n = len (words)
                if n < 4:
                    words.extend (['','','',''])
                    words = words[:4]
                    n = 4
                elif n > 6:
                    words = words[:6]
                    n = 6

                if n == 6:
                    (device_class, uri, make_and_model,
                     info, device_id, device_location) = words
                elif n == 5:
                    (device_class, uri, make_and_model,
                     info, device_id) = words
                elif n == 4:
                    (device_class, uri, make_and_model, info) = words

                if n == 4:
                    # No Device ID given so we'll have to make one
                    # up.
                    debugprint ("No Device ID from snmp backend")
                    (mk, md) = cupshelpers.ppds.\
                        ppdMakeModelSplit (make_and_model)
                    device.id = "MFG:%s;MDL:%s;DES:%s %s;" % (mk, md,
                                                              mk, md)
                else:
                    debugprint ("Got Device ID: %s" % device_id)
                    device.id = device_id

                device.id_dict = cupshelpers.parseDeviceID (device.id)
                device.make_and_model = make_and_model
                device.info = info
                if n == 6:
                    device.location = device_location

        return (host, uri)

    def fillDeviceTab(self, current_uri=None):
        self.device_selected = -1
        model = Gtk.TreeStore (str,                   # device-info
                               GObject.TYPE_PYOBJECT, # PhysicalDevice obj
                               bool)                  # Separator?
        other = cupshelpers.Device('', **{'device-info' :_("Enter URI")})
        physother = PhysicalDevice (other)
        self.devices = [physother]
        uri_iter = model.append (None, row=[physother.get_info (),
                                            physother, False])
        network_iter = model.append (None, row=[_("Network Printer"),
                                                None,
                                                False])
        network_dict = { 'device-class': 'network',
                         'device-info': _("Find Network Printer") }
        network = cupshelpers.Device ('network', **network_dict)
        find_nw_iter = model.append (network_iter,
                                     row=[network_dict['device-info'],
                                          PhysicalDevice (network), False])
        model.insert_after (network_iter, find_nw_iter, row=['', None, True])
        smbdev_dict = { 'device-class': 'network',
                        'device-info': _("Windows Printer via SAMBA") }
        smbdev = cupshelpers.Device ('smb', **smbdev_dict)
        find_smb_iter = model.append (network_iter,
                                     row=[smbdev_dict['device-info'],
                                          PhysicalDevice (smbdev), False])
        model.insert_after (find_nw_iter, find_smb_iter, row=['', None, True])
        self.devices_uri_iter = uri_iter
        self.devices_find_nw_iter = find_nw_iter
        self.devices_network_iter = network_iter
        self.devices_network_fetched = False
        self.tvNPDevices.set_model (model)
        self.entNPTDevice.set_text ('')
        self.expNPDeviceURIs.hide ()
        column = self.tvNPDevices.get_column (0)
        self.tvNPDevices.set_cursor (Gtk.TreePath(), column, False)

        self.current_uri = current_uri
        self.firewall = None
        debugprint ("Fetching devices")
        self.start_fetching_devices ()

    def on_firewall_read (self, data):
        f = self.firewall
        allowed = True
        try:
            ipp_allowed = f.check_ipp_client_allowed ()
            mdns_allowed = f.check_mdns_allowed ()
            allowed = (ipp_allowed and mdns_allowed)

            secondary_text = TEXT_adjust_firewall + "\n\n"
            if not ipp_allowed:
                secondary_text += ("- " +
                                   _("Allow all incoming IPP Browse packets") +
                                   "\n")
                f.add_service (firewallsettings.IPP_CLIENT_SERVICE)
            if not mdns_allowed:
                secondary_text += ("- " +
                                   _("Allow all incoming mDNS traffic") + "\n")
                f.add_service (firewallsettings.MDNS_SERVICE)

            if not allowed:
                debugprint ("Asking for permission to adjust firewall:\n%s" %
                            secondary_text)
                dialog = Gtk.MessageDialog (parent=self.NewPrinterWindow,
                                            modal=True, destroy_with_parent=True,
                                            message_type=Gtk.MessageType.QUESTION,
                                            buttons=Gtk.ButtonsType.NONE,
                                            text= _("Adjust Firewall"))
                dialog.format_secondary_markup (secondary_text)
                dialog.add_buttons (_("Do It Later"), Gtk.ResponseType.NO,
                                    _("Adjust Firewall"), Gtk.ResponseType.YES)
                dialog.connect ('response', self.adjust_firewall_response)
                dialog.show ()
        except (dbus.DBusException, Exception):
            nonfatalException ()

        if allowed:
            debugprint ("Firewall all OK, no changes needed")

    def adjust_firewall_response (self, dialog, response):
        dialog.destroy ()
        if response == Gtk.ResponseType.YES:
            ipp_server_allowed = self.firewall.check_ipp_server_allowed ()
            if not ipp_server_allowed:
                self.firewall.add_service (firewallsettings.IPP_SERVER_SERVICE)
            self.firewall.write ()

        debugprint ("Fetching network devices after firewall dialog response")
        self.fetchDevices_conn = asyncconn.Connection ()
        self.fetchDevices_conn._begin_operation (_("fetching device list"))
        self.fetchDevices (network=True)

    def start_fetching_devices (self):
        self.fetchDevices_conn = asyncconn.Connection ()
        self.fetchDevices_conn._begin_operation (_("fetching device list"))
        self.fetchDevices (network=False, current_uri=self.current_uri)
        del self.current_uri

    def add_devices (self, devices, current_uri, no_more=False):
        if current_uri:
            if current_uri in devices:
                current = devices.pop(current_uri)
            elif current_uri.replace (":9100", "") in devices:
                current_uri = current_uri.replace (":9100", "")
                current = devices.pop(current_uri)
            elif no_more:
                current = cupshelpers.Device (current_uri)
                current.info = "Current device"
            else:
                current_uri = None

        devices = list(devices.values())

        for device in devices:
            if device.type == "socket":
                # Remove default port to more easily find duplicate URIs
                device.uri = device.uri.replace (":9100", "")

        # Map generic URIs to something canonical
        def replace_generic (device):
            if device.uri == "hp:/no_device_found":
                device.uri = "hp"
            elif device.uri == "hpfax:/no_device_found":
                device.uri = "hpfax"
            return device

        devices = list(map (replace_generic, devices))

        # Mark duplicate URIs for deletion
        for i in range (len (devices) - 1):
            for j in range (i + 1, len (devices)):
                device1 = devices[i]
                device2 = devices[j]
                if device1.uri == "delete" or device2.uri == "delete":
                    continue
                if device1.uri == device2.uri:
                    # Keep the one with the longer (better) device ID
                    if (not device1.id):
                        device1.uri = "delete"
                    elif (not device2.id):
                        device2.uri = "delete"
                    elif (len (device1.id) < len (device2.id)):
                        device1.uri = "delete"
                    else:
                        device2.uri = "delete"
        devices = [x for x in devices if x.uri not in ("hp", "hpfax",
                                                       "hal", "beh", "smb", 
                                                       "scsi", "http", "bjnp",
                                                       "delete")]
        newdevices = []
        for device in devices:
            debugprint("Adding device with URI %s" % device.uri)
            if (hasattr (device, 'address')):
                debugprint("   Device address %s" % device.address)
            if (hasattr (device, 'hostname')):
                debugprint("   Device host name %s" % device.hostname)
            physicaldevice = PhysicalDevice (device)
            debugprint ("   Created physical device %s" % repr(physicaldevice))
            try:
                i = self.devices.index (physicaldevice)
                debugprint ("   Physical device %d is the same printer" % i)
                self.devices[i].add_device (device)
                debugprint ("   New physical device %s is same as physical device %d: %s" %
                            (repr(physicaldevice), i, repr(self.devices[i])))
                debugprint ("   Joining devices")
            except ValueError:
                self.devices.append (physicaldevice)
                newdevices.append (physicaldevice)
                debugprint ("   Physical device %s is a completely new device" % repr(physicaldevice))

        self.devices.sort()
        if current_uri:
            current_device = PhysicalDevice (current)
            try:
                i = self.devices.index (current_device)
                self.devices[i].add_device (current)
                current_device = self.devices[i]
            except ValueError:
                self.devices.append (current_device)
                newdevices.append (current_device)
        else:
            current_device = None

        model = self.tvNPDevices.get_model ()

        network_iter = self.devices_network_iter
        find_nw_iter = self.devices_find_nw_iter
        for newdevice in newdevices:
            device = None
            try:
                i = self.devices.index (newdevice)
                device = self.devices[i]
            except ValueError:
                debugprint("ERROR: Cannot identify new physical device with its entry in the device list (%s)" %
                           repr(newdevice))
                continue
            devs = device.get_devices ()
            network = devs[0].device_class == 'network'
            info = device.get_info ()
            if device == current_device:
                info += _(" (Current)")
            row=[info, device, False]
            if network:
                if devs[0].uri != devs[0].type:
                    # An actual network printer device.  Put this at the top.
                    iter = model.insert_before (network_iter, find_nw_iter,
                                                row=row)

                    # If this is the currently selected device we need
                    # to expand the "Network Printer" row so that it
                    # is visible.
                    if device == current_device:
                        network_path = model.get_path (network_iter)
                        self.tvNPDevices.expand_row (network_path, False)
                else:
                    # Just a method of finding one.
                    iter = model.append (network_iter, row=row)
            else:
                # Insert this local device in order.
                network_path = model.get_path (network_iter)
                iter = model.get_iter_first ()
                while model.get_path (iter) != network_path:
                    physdev = model.get_value (iter, 1)
                    if physdev > device:
                        break

                    iter = model.iter_next (iter)

                iter = model.insert_before (None, iter, row=row)

            if device == current_device:
                device_select_path = model.get_path (iter)
                self.tvNPDevices.scroll_to_cell (device_select_path,
                                                 row_align=0.5)
                column = self.tvNPDevices.get_column (0)
                self.tvNPDevices.set_cursor (device_select_path, column, False)

        connection_select_path = 0
        if current_uri:
            model = self.tvNPDeviceURIs.get_model ()
            iter = model.get_iter_first ()
            i = 0
            while iter:
                dev = model.get_value (iter, 1)
                if current_uri == dev.uri:
                    connection_select_path = i
                    break

                iter = model.iter_next (iter)
                i += 1
        elif not self.device_selected:
            # Select the device.
            column = self.tvNPDevices.get_column (0)
            self.tvNPDevices.set_cursor (Gtk.TreePath(), column, False)

            # Select the connection.
            column = self.tvNPDeviceURIs.get_column (0)
            self.tvNPDeviceURIs.set_cursor (connection_select_path, column, False)

    ## SMB browsing

    def install_python3_smbc_if_needed (self):
        global PYSMB_AVAILABLE
        global pysmb # Make the import of pysmb globally available
        # Does the SMB client library  need to be installed?
        if PYSMB_AVAILABLE:
            return True

        debugprint ("No SMB client library present so attempting install")

        try:
            pk = installpackage.PackageKit ()
            # The following call means a blocking, synchronous, D-Bus call
            pk.InstallPackageName (0, 0, "python3-smbc")
        except DBusException as e:
            debugprint ("Error during installation/setup of SMB client.")
            debugprint("{}".format(e))
            return False

        try:
            import pysmb
            PYSMB_AVAILABLE=True
        except ModuleNotFoundError as e:
            debugprint ("SMB client setup failed.")
            debugprint("{}".format(e))
            return False

        debugprint ("SMB client successfully installed and set up.")

        return True

    def browse_smb_hosts(self):
        """Initialise the SMB tree store."""
        store = self.smb_store
        store.clear ()
        busy(self.SMBBrowseDialog)
        class X:
            pass
        dummy = X()
        dummy.smbc_type = pysmb.smbc.PRINTER_SHARE
        dummy.name = _('Scanning...')
        dummy.comment = ''
        store.append(None, [dummy])
        while Gtk.events_pending ():
            Gtk.main_iteration ()

        debug = 0
        if get_debugging ():
            debug = 10
        smbc_auth = pysmb.AuthContext (self.SMBBrowseDialog)
        ctx = pysmb.smbc.Context (debug=debug,
                                  auth_fn=smbc_auth.callback)
        entries = None
        try:
            while smbc_auth.perform_authentication () > 0:
                try:
                    entries = ctx.opendir ("smb://").getdents ()
                except Exception as e:
                    smbc_auth.failed (e)
        except RuntimeError as e:
            (e, s) = e.args
            if e != errno.ENOENT:
                debugprint ("Runtime error: %s" % repr ((e, s)))
        except:
            nonfatalException ()

        store.clear ()
        if entries:
            for entry in entries:
                if entry.smbc_type in [pysmb.smbc.WORKGROUP,
                                       pysmb.smbc.SERVER]:
                    iter = store.append (None, [entry])
                    i = store.append (iter)

        specified_uri = SMBURI (uri=self.entSMBURI.get_text ())
        (group, host, share, user, password) = specified_uri.separate ()
        if len (host) > 0:
            # The user has specified a server before clicking Browse.
            # Append the server as a top-level entry.
            class FakeEntry:
                pass
            toplevel = FakeEntry ()
            toplevel.smbc_type = pysmb.smbc.SERVER
            toplevel.name = host
            toplevel.comment = ''
            iter = store.append (None, [toplevel])
            i = store.append (iter)

            # Now expand it.
            path = store.get_path (iter)
            self.tvSMBBrowser.expand_row (path, 0)

        ready(self.SMBBrowseDialog)

        if store.get_iter_first () is None:
            self.SMBBrowseDialog.hide ()
            show_info_dialog (_("No Print Shares"),
                              _("There were no print shares found.  "
                                "Please check that the Samba service is "
                                "marked as trusted in your firewall "
                                "configuration."),
                              parent=self.NewPrinterWindow)

    def smb_select_function (self, selection, model, path, path_selected, data):
        """Don't allow this path to be selected unless it is a leaf."""
        iter = self.smb_store.get_iter (path)
        return not self.smb_store.iter_has_child (iter)

    def smbbrowser_cell_share (self, column, cell, model, iter, data):
        entry = model.get_value (iter, 0)
        share = ''
        if entry is not None:
            share = entry.name
        cell.set_property ('text', share)

    def smbbrowser_cell_comment (self, column, cell, model, iter, data):
        entry = model.get_value (iter, 0)
        comment = ''
        if entry is not None:
            comment = entry.comment
        cell.set_property ('text', comment)

    def on_tvSMBBrowser_row_activated (self, view, path, column):
        """Handle double-clicks in the SMB tree view."""
        store = self.smb_store
        iter = store.get_iter (path)
        entry = store.get_value (iter, 0)
        if entry and entry.smbc_type == pysmb.smbc.PRINTER_SHARE:
            # This is a share, not a host.
            self.btnSMBBrowseOk.clicked ()
            return

        if view.row_expanded (path):
            view.collapse_row (path)
        else:
            self.on_tvSMBBrowser_row_expanded (view, iter, path)

    def on_tvSMBBrowser_row_expanded (self, view, iter, path):
        """Handler for expanding a row in the SMB tree view."""
        model = view.get_model ()
        entry = model.get_value (iter, 0)
        if entry is None:
            return

        if entry.smbc_type == pysmb.smbc.WORKGROUP:
            # Workgroup
            # Be careful though: if there is a server with the
            # same name as the workgroup we will get a list of its
            # shares, not the workgroup's servers.
            try:
                if self.expanding_row:
                    return
            except:
                self.expanding_row = 1

            busy (self.SMBBrowseDialog)
            uri = "smb://%s/" % entry.name
            debug = 0
            if get_debugging ():
                debug = 10
            smbc_auth = pysmb.AuthContext (self.SMBBrowseDialog)
            ctx = pysmb.smbc.Context (debug=debug,
                                      auth_fn=smbc_auth.callback)
            entries = []
            try:
                while smbc_auth.perform_authentication () > 0:
                    try:
                        entries = ctx.opendir (uri).getdents ()
                    except Exception as e:
                        smbc_auth.failed (e)
            except RuntimeError as e:
                (e, s) = e.args
                if e != errno.ENOENT:
                    debugprint ("Runtime error: %s" % repr ((e, s)))
            except:
                nonfatalException()

            while model.iter_has_child (iter):
                i = model.iter_nth_child (iter, 0)
                model.remove (i)

            for entry in entries:
                if entry.smbc_type in [pysmb.smbc.SERVER,
                                       pysmb.smbc.PRINTER_SHARE]:
                    i = model.append (iter, [entry])
                if entry.smbc_type == pysmb.smbc.SERVER:
                    n = model.append (i)

            view.expand_row (path, 0)
            del self.expanding_row
            ready (self.SMBBrowseDialog)

        elif entry.smbc_type == pysmb.smbc.SERVER:
            # Server
            try:
                if self.expanding_row:
                    return
            except:
                self.expanding_row = 1

            busy (self.SMBBrowseDialog)
            uri = "smb://%s/" % entry.name
            debug = 0
            if get_debugging ():
                debug = 10
            smbc_auth = pysmb.AuthContext (self.SMBBrowseDialog)
            ctx = pysmb.smbc.Context (debug=debug,
                                      auth_fn=smbc_auth.callback)
            shares = []
            try:
                while smbc_auth.perform_authentication () > 0:
                    try:
                        shares = ctx.opendir (uri).getdents ()
                    except Exception as e:
                        smbc_auth.failed (e)
            except RuntimeError as e:
                (e, s) = e.args
                if e != errno.EACCES and e != errno.EPERM:
                    debugprint ("Runtime error: %s" % repr ((e, s)))
            except:
                nonfatalException()

            while model.iter_has_child (iter):
                i = model.iter_nth_child (iter, 0)
                model.remove (i)

            for share in shares:
                if share.smbc_type == pysmb.smbc.PRINTER_SHARE:
                    i = model.append (iter, [share])
                    debugprint (repr (share))

            view.expand_row (path, 0)
            del self.expanding_row
            ready (self.SMBBrowseDialog)

    def set_btnSMBVerify_sensitivity (self, on):
        self.btnSMBVerify.set_sensitive (on)
        if not PYSMB_AVAILABLE or not on:
            self.btnSMBVerify.set_tooltip_text (_("Verification requires the "
                                                  "%s module") % "pysmbc")

    def on_entSMBURI_changed (self, ent):
        allowed_chars = string.ascii_letters+string.digits+'_-./:%[]@'
        self.entry_changed(ent, allowed_chars)
        uri = ent.get_text ()
        (group, host, share, user, password) = SMBURI (uri=uri).separate ()
        if user:
            self.entSMBUsername.set_text (user)
        if password:
            self.entSMBPassword.set_text (password)
        if user or password:
            uri = SMBURI (group=group, host=host, share=share).get_uri ()
            ent.set_text(uri)
            self.rbtnSMBAuthSet.set_active(True)
        elif self.entSMBUsername.get_text () == '':
            self.rbtnSMBAuthPrompt.set_active(True)

        self.set_btnSMBVerify_sensitivity (bool(uri))
        self.setNPButtons ()

    def on_tvSMBBrowser_cursor_changed(self, widget):
        selection = self.tvSMBBrowser.get_selection()
        if selection is None:
            return

        store, iter = selection.get_selected()
        is_share = False
        if iter:
            entry = store.get_value (iter, 0)
            if entry:
                is_share = entry.smbc_type == pysmb.smbc.PRINTER_SHARE

        self.btnSMBBrowseOk.set_sensitive(iter is not None and is_share)

    def on_btnSMBBrowse_clicked(self, button):
        """Check whether the needed SMB client library is available and"""
        """install it if needed"""
        if not self.install_python3_smbc_if_needed():
            return

        self.btnSMBBrowseOk.set_sensitive(False)

        try:
            # Note: we do the browsing from *this* machine, regardless
            # of which CUPS server we are connected to.
            f = firewallsettings.FirewallD ()
            if not f.running:
                f = firewallsettings.SystemConfigFirewall ()
            allowed = f.check_samba_client_allowed ()
            secondary_text = TEXT_adjust_firewall + "\n\n"
            if not allowed:
                dialog = Gtk.MessageDialog (parent=self.NewPrinterWindow,
                                            modal=True, destroy_with_parent=True,
                                            message_type=Gtk.MessageType.QUESTION,
                                            buttons=Gtk.ButtonsType.NONE,
                                            text=_("Adjust Firewall"))
                secondary_text += ("- " +
                                   _("Allow all incoming SMB/CIFS "
                                     "browse packets"))
                dialog.format_secondary_markup (secondary_text)
                dialog.add_buttons (_("Do It Later"), Gtk.ResponseType.NO,
                                    _("Adjust Firewall"), Gtk.ResponseType.YES)
                response = dialog.run ()
                dialog.destroy ()

                if response == Gtk.ResponseType.YES:
                    f.add_service (firewallsettings.SAMBA_CLIENT_SERVICE)
                    f.write ()
        except (dbus.DBusException, Exception):
            nonfatalException ()

        self.SMBBrowseDialog.show()
        self.browse_smb_hosts()

    def on_btnSMBBrowseOk_clicked(self, button):
        store, iter = self.tvSMBBrowser.get_selection().get_selected()
        is_share = False
        if iter:
            entry = store.get_value (iter, 0)
            if entry:
                is_share = entry.smbc_type == pysmb.smbc.PRINTER_SHARE

        if not iter or not is_share:
            self.SMBBrowseDialog.hide()
            return

        parent_iter = store.iter_parent (iter)
        domain_iter = store.iter_parent (parent_iter)
        share = store.get_value (iter, 0)
        host = store.get_value (parent_iter, 0)
        if domain_iter:
            group = store.get_value (domain_iter, 0).name
        else:
            group = ''
        uri = SMBURI (group=group,
                      host=host.name,
                      share=share.name).get_uri ()

        self.entSMBUsername.set_text ('')
        self.entSMBPassword.set_text ('')
        self.entSMBURI.set_text (uri)

        self.SMBBrowseDialog.hide()

    def on_btnSMBBrowseCancel_clicked(self, widget, *args):
        self.SMBBrowseDialog.hide()

    def on_btnSMBBrowseRefresh_clicked(self, button):
        self.browse_smb_hosts()

    def on_rbtnSMBAuthSet_toggled(self, widget):
        self.tblSMBAuth.set_sensitive(widget.get_active())

    def on_btnSMBVerify_clicked(self, button):
        """Check whether the needed SMB client library is available and"""
        """install it if needed"""
        if not self.install_python3_smbc_if_needed():
            return

        uri = self.entSMBURI.get_text ()
        (group, host, share, u, p) = SMBURI (uri=uri).separate ()
        user = ''
        passwd = ''
        reason = None
        auth_set = self.rbtnSMBAuthSet.get_active()
        if auth_set:
            user = self.entSMBUsername.get_text ()
            passwd = self.entSMBPassword.get_text ()

        accessible = False
        canceled = False
        busy (self.NewPrinterWindow)
        try:
            debug = 0
            if get_debugging ():
                debug = 10

            if auth_set:
                # No prompting.
                def do_auth (svr, shr, wg, un, pw):
                    return (group, user, passwd)
                ctx = pysmb.smbc.Context (debug=debug, auth_fn=do_auth)
                try:
                    ctx.optionUseKerberos = True
                except AttributeError:
                    # requires pysmbc >= 1.0.12
                    pass

                f = ctx.open ("smb://%s/%s" % (host, share),
                              os.O_RDWR, 0o777)
                accessible = True
            else:
                # May need to prompt.
                smbc_auth = pysmb.AuthContext (self.NewPrinterWindow,
                                               workgroup=group,
                                               user=user,
                                               passwd=passwd)
                ctx = pysmb.smbc.Context (debug=debug,
                                          auth_fn=smbc_auth.callback)
                while smbc_auth.perform_authentication () > 0:
                    try:
                        f = ctx.open ("smb://%s/%s" % (host, share),
                                      os.O_RDWR, 0o777)
                        accessible = True
                    except Exception as e:
                        smbc_auth.failed (e)

                if not accessible:
                    canceled = True
        except RuntimeError as e:
            (e, s) = e.args
            debugprint ("Error accessing share: %s" % repr ((e, s)))
            reason = s
        except:
            nonfatalException()
        ready (self.NewPrinterWindow)

        if accessible:
            show_info_dialog (_("Print Share Verified"),
                              _("This print share is accessible."),
                              parent=self.NewPrinterWindow)
            return

        if not canceled:
            text = _("This print share is not accessible.")
            if reason:
                text = reason
            show_error_dialog (_("Print Share Inaccessible"), text,
                               parent=self.NewPrinterWindow)

    def entry_changed(self, entry, allowed_chars):
        "Remove all chars from entry's text that are not in allowed_chars."
        origtext = entry.get_text()
        new_text = origtext
        for char in origtext:
            if char not in allowed_chars:
                new_text = new_text.replace(char, "")
                debugprint ("removed disallowed character %s" % repr (char))
        if origtext!=new_text:
            entry.set_text(new_text)

    def on_entNPTDevice_changed(self, ent):
        allowed_chars = string.ascii_letters+string.digits+'_-./:%[]()@?=&+'
        self.entry_changed(ent, allowed_chars)
        self.setNPButtons()

    def on_entNPTJetDirectHostname_changed(self, ent):
        allowed_chars = string.ascii_letters+string.digits+'_-.:%[]'
        self.entry_changed(ent, allowed_chars)
        self.setNPButtons()

    def on_entNPTJetDirectPort_changed(self, ent):
        self.entry_changed(ent, string.digits)
        self.setNPButtons()

    def on_expNPDeviceURIs_expanded (self, widget, UNUSED):
        # When the expanded is not expanded we want its packing to be
        # 'expand = false' so that it aligns at the bottom (it packs
        # to the end of its vbox).  But when it is expanded we'd like
        # it to expand with the window.
        #
        # Adjust its 'expand' packing state depending on whether the
        # widget is expanded.

        parent = widget.get_parent ()
        (expand, fill,
         padding, pack_type) = parent.query_child_packing (widget)
        expand = widget.get_expanded ()
        parent.set_child_packing (widget, expand, fill,
                                  padding, pack_type)

    def device_row_separator_fn (self, model, iter, data):
        return model.get_value (iter, 2)

    def device_row_activated (self, view, path, column):
        if view.row_expanded (path):
            view.collapse_row (path)
        else:
            view.expand_row (path, False)

    def check_firewall (self):
        view = self.tvNPDevices
        model = view.get_model ()
        if not model:
            return

        network_path = model.get_path (self.devices_network_iter)
        if not view.row_expanded (network_path):
            # 'Network' not expanded
            return

        if self.firewall is not None:
            # Already checked
            return

        if self.spinner_count > 0:
            # Still discovering devices?
            debugprint ("Skipping firewall adjustment: "
                        "discovery in progress")
            return

        # Any network printers found?
        for physdev in self.devices:
            for device in physdev.get_devices ():
                if (device.device_class == 'network' and
                    device.uri != device.type):
                    debugprint ("Skipping firewall adjustment: "
                                "network printers found")
                    return

        # If not, ask about the firewall
        try:
            if (self._host == 'localhost' or
                self._host[0] == '/'):
                self.firewall = firewallsettings.FirewallD ()
                if not self.firewall.running:
                    self.firewall = firewallsettings.SystemConfigFirewall ()

                debugprint ("Examining firewall")
                self.firewall.read (reply_handler=self.on_firewall_read)
        except (dbus.DBusException, Exception):
            nonfatalException ()

    def device_row_expanded (self, view, iter, path):
        model = view.get_model ()
        if not model or not iter:
            return

        network_path = model.get_path (self.devices_network_iter)
        if path == network_path:
            self.check_firewall ()

    def device_select_function (self, selection, model, path, *UNUSED):
        """
        Allow this path to be selected as long as there
        is a device associated with it.  Otherwise, expand or collapse it.
        """
        model = self.tvNPDevices.get_model ()
        iter = model.get_iter (path)
        if model.get_value (iter, 1) is not None:
            return True

        self.device_row_activated (self.tvNPDevices, path, None)
        return False

    def on_tvNPDevices_cursor_changed(self, widget):
        # Reset previous driver search result
        self.installed_driver_files = []
        self.searchedfordriverpackages = False
        self.founddownloadabledrivers = False
        self.founddownloadableppd = False
        self.downloadable_printers = []

        self.device_selected += 1
        path, column = widget.get_cursor ()
        if path is None:
            return

        model = widget.get_model ()
        iter = model.get_iter (path)
        physicaldevice = model.get_value (iter, 1)
        if physicaldevice is None:
            return
        show_uris = True
        for device in physicaldevice.get_devices ():
            if device.type == "parallel":
                device.menuentry = _("Parallel Port")
            elif device.type == "serial":
                device.menuentry = _("Serial Port")
            elif device.type == "usb":
                if (hasattr(device, "uri") and
                    device.uri.lower().find("fax") > -1):
                    device.menuentry = _("Fax") + " - " + _("USB")
                else:
                    device.menuentry = _("USB")
            elif device.type == "bluetooth":
                device.menuentry = _("Bluetooth")
            elif device.type == "hp":
                device.menuentry = _("HP Linux Imaging and Printing (HPLIP)")
            elif device.type == "hpfax":
                device.menuentry = _("Fax") + " - " + \
                    _("HP Linux Imaging and Printing (HPLIP)")
            elif device.type == "hal":
                device.menuentry = _("Hardware Abstraction Layer (HAL)")
            elif device.type == "socket":
                device.menuentry = _("AppSocket/HP JetDirect")
            elif device.type == "lpd":
                (scheme, rest) = urllib.parse.splittype (device.uri)
                (hostport, rest) = urllib.parse.splithost (rest)
                (queue, rest) = urllib.parse.splitquery (rest)
                if queue != '':
                    if queue[0] == '/':
                        queue = queue[1:]

                    device.menuentry = (_("LPD/LPR queue '%s'")
                                        % queue)
                else:
                    device.menuentry = _("LPD/LPR queue")

            elif device.type == "smb":
                device.menuentry = _("Windows Printer via SAMBA")
            elif device.type == "ipp":
                (scheme, rest) = urllib.parse.splittype (device.uri)
                (hostport, rest) = urllib.parse.splithost (rest)
                (queue, rest) = urllib.parse.splitquery (rest)
                if queue != '':
                    if queue[0] == '/':
                        queue = queue[1:]
                    if queue.startswith("printers/"):
                        queue = queue[9:]
                if 'driverless' in device.info:
                    drvless = "Driverless "
                    device.driverless = True
                else:
                    drvless = ""
                if queue != '':
                    device.menuentry = (("%s" + _("IPP") + " (%s)") %
                                        (drvless, queue))
                else:
                    device.menuentry = (("%s" + _("IPP")) % drvless)
            elif device.type == "http" or device.type == "https":
                device.menuentry = _("HTTP")
            elif device.type == "dnssd" or device.type == "mdns":
                (scheme, rest) = urllib.parse.splittype (device.uri)
                (name, rest) = urllib.parse.splithost (rest)
                (cupsqueue, rest) = urllib.parse.splitquery (rest)
                if cupsqueue != '' and cupsqueue[0] == '/':
                    cupsqueue = cupsqueue[1:]
                if cupsqueue == 'cups':
                    device.menuentry = _("Remote CUPS printer via DNS-SD")
                    if device.info != '':
                        device.menuentry += " (%s)" % device.info
                else:
                    protocol = None
                    if name.find("._ipp") != -1:
                        protocol = "IPP"
                    elif name.find("._printer") != -1:
                        protocol = "LPD"
                    elif name.find("._pdl-datastream") != -1:
                        protocol = "AppSocket/JetDirect"
                    if protocol is not None:
                        device.menuentry = (_("%s network printer via DNS-SD")
                                            % protocol)
                    else:
                        device.menuentry = \
                            _("Network printer via DNS-SD")
            else:
                show_uris = False
                device.menuentry = device.uri

        model = Gtk.ListStore (str,                    # URI description
                               GObject.TYPE_PYOBJECT)  # cupshelpers.Device
        self.tvNPDeviceURIs.set_model (model)

        # If this is a network device, check whether HPLIP can drive it.
        if getattr (physicaldevice, 'checked_hplip', None) != True:
            hp_drivable = False
            hp_scannable = False
            is_network = False
            remotecups = False
            host = None
            device_dict = { 'device-class': 'network' }
            if physicaldevice._network_host:
                host = physicaldevice._network_host
            for device in physicaldevice.get_devices ():
                if device.type == "hp":
                    # We already know that HPLIP can drive this device.
                    hp_drivable = True

                    # But can we scan using it?
                    if self.get_hplip_scan_type_for_uri (device.uri):
                        hp_scannable = True

                    break
                elif device.type in ["socket", "lpd", "ipp", "dnssd", "mdns"]:
                    # This is a network printer.
                    if host is None and device.type in ["socket", "lpd", "ipp"]:
                        (scheme, rest) = urllib.parse.splittype (device.uri)
                        (hostport, rest) = urllib.parse.splithost (rest)
                        if hostport is not None:
                            (host, port) = urllib.parse.splitport (hostport)
                    if host:
                        is_network = True
                        remotecups = ((device.uri.startswith('dnssd:') or \
                                       device.uri.startswith('mdns:')) and \
                                      device.uri.endswith('/cups'))
                        if (not device.make_and_model or \
                            device.make_and_model == "Unknown") and not \
                           remotecups:
                            self.getNetworkPrinterMakeModel(host=host,
                                                            device=device)
                        device_dict['device-info'] = device.info
                        device_dict['device-make-and-model'] = (device.
                                                                make_and_model)
                        device_dict['device-id'] = device.id
                        device_dict['device-location'] = device.location

            if not hp_drivable and is_network and not remotecups and \
               (not device.make_and_model or \
                device.make_and_model == "Unknown" or \
                device.make_and_model.lower ().startswith ("hp") or \
                device.make_and_model.lower ().startswith ("hewlett")):
                if (hasattr (physicaldevice, "dnssd_hostname") and \
                    physicaldevice.dnssd_hostname):
                    hpliphost = physicaldevice.dnssd_hostname
                else:
                    hpliphost = host
                hplipuri = self.get_hplip_uri_for_network_printer (hpliphost,
                                                                   "print")
                if hplipuri:
                    dev = cupshelpers.Device (hplipuri, **device_dict)
                    dev.menuentry = "HP Linux Imaging and Printing (HPLIP)"
                    physicaldevice.add_device (dev)

                    # Can we scan using this device?
                    if self.get_hplip_scan_type_for_uri (device.uri):
                        hp_scannable = True

                    # Now check to see if we can also send faxes using
                    # this device.
                    faxuri = self.get_hplip_uri_for_network_printer (hpliphost,
                                                                     "fax")
                    if faxuri:
                        faxdevid = self.get_hpfax_device_id (faxuri)
                        device_dict['device-id'] = faxdevid
                        device_dict['device-info'] = _("Fax")
                        faxdev = cupshelpers.Device (faxuri, **device_dict)
                        faxdev.menuentry = _("Fax") + " - " + \
                            "HP Linux Imaging and Printing (HPLIP)"
                        physicaldevice.add_device (faxdev)

            if hp_scannable:
                physicaldevice.hp_scannable = True
            physicaldevice.checked_hplip = True

        device.hp_scannable = getattr (physicaldevice, 'hp_scannable', None)

        # Fill the list of connections for this device.
        n = 0
        for device in physicaldevice.get_devices ():
            model.append ((device.menuentry, device))
            n += 1
        column = self.tvNPDeviceURIs.get_column (0)
        self.tvNPDeviceURIs.set_cursor (Gtk.TreePath(), column, False)
        if show_uris:
            self.expNPDeviceURIs.show_all ()
        else:
            self.expNPDeviceURIs.hide ()

    def on_tvNPDeviceURIs_cursor_changed(self, widget):
        path, column = widget.get_cursor ()
        if path is None:
            return

        model = widget.get_model ()
        iter = model.get_iter (path)
        device = model.get_value(iter, 1)
        self.device = device
        self.lblNPDeviceDescription.set_text ('')
        page = self.new_printer_device_tabs.get (device.type, self.PAGE_SELECT_DEVICE)
        self.ntbkNPType.set_current_page(page)

        debugprint("Selected connection type. URI: %s" % device.uri)
        location = ''
        type = device.type
        url = device.uri.split(":", 1)[-1]
        if page == self.PAGE_DESCRIBE_PRINTER:
            # This is the "no options" page, with just a label to describe
            # the selected device.
            if device.type == "parallel":
                text = _("A printer connected to the parallel port.")
            elif device.type == "usb":
                if (hasattr(device, "uri") and
                    device.uri.lower().find("fax") > -1):
                    device.menuentry = _("Fax") + " - " + _("USB")
                    text = _("A fax machine or the fax function "
                             "of a multi-function device connected "
                             "to a USB port.")
                else:
                    text = _("A printer connected to a USB port.")
            elif device.type == "bluetooth":
                text = _("A printer connected via Bluetooth.")
            elif device.type == "hp":
                text = _("HPLIP software driving a printer, "
                         "or the printer function of a multi-function device.")
            elif device.type == "hpfax":
                text = _("HPLIP software driving a fax machine, "
                         "or the fax function of a multi-function device.")
            elif device.type == "hal":
                text = _("Local printer detected by the "
                         "Hardware Abstraction Layer (HAL).")
            elif device.type == "dnssd" or device.type == "mdns":
                (scheme, rest) = urllib.parse.splittype (device.uri)
                (name, rest) = urllib.parse.splithost (rest)
                (cupsqueue, rest) = urllib.parse.splitquery (rest)
                if cupsqueue != '' and cupsqueue[0] == '/':
                    cupsqueue = cupsqueue[1:]
                if cupsqueue == 'cups':
                    text = _("Remote CUPS printer via DNS-SD")
                else:
                    protocol = None
                    if name.find("._ipp") != -1:
                        protocol = "IPP"
                    elif name.find("._printer") != -1:
                        protocol = "LPD"
                    elif name.find("._pdl-datastream") != -1:
                        protocol = "AppSocket/JetDirect"
                    if protocol is not None:
                        text = _("%s network printer via DNS-SD") % protocol
                    else:
                        text = _("Network printer via DNS-SD")
            else:
                text = device.uri

            self.lblNPDeviceDescription.set_text (text)
        elif device.type=="socket":
            (scheme, rest) = urllib.parse.splittype (device.uri)
            host = ''
            port = 9100
            if scheme == "socket":
                (hostport, rest) = urllib.parse.splithost (rest)
                (host, port) = urllib.parse.splitnport (hostport, defport=port)
                debugprint ("socket: host is %s, port is %s" % (host,
                                                                repr (port)))
                if device.location != '':
                    location = device.location
                else:
                    location = host
            self.entNPTJetDirectHostname.set_text (host)
            self.entNPTJetDirectPort.set_text (str (port))
        elif device.type=="serial":
            if not device.is_class:
                parts = device.uri.split("?", 1)
                if len (parts) > 1:
                    options = parts[1]
                else:
                    options = ""

                options = options.split("+")
                option_dict = {}
                for option in options:
                    name, value = option.split("=")
                    option_dict[name] = value

                for widget, name in (
                    (self.cmbNPTSerialBaud, "baud"),
                    (self.cmbNPTSerialBits, "bits"),
                    (self.cmbNPTSerialParity, "parity"),
                    (self.cmbNPTSerialFlow, "flow")):
                    if name in option_dict: # option given in URI?
                        model = widget.get_model()
                        iter = model.get_iter_first()
                        nr = 0
                        while iter:
                            value = model.get(iter,1)[0]
                            if str (value) == str (option_dict[name]):
                                break
                            iter = model.iter_next(iter)
                            nr += 1

                        if iter:
                            widget.set_active(nr)
                        else:
                            widget.set_active (0)
                    else:
                        widget.set_active(0)

        # XXX FILL TABS FOR VALID DEVICE URIs
        elif device.type=="lpd":
            self.entNPTLpdHost.set_text ('')
            self.entNPTLpdQueue.set_text ('')
            self.entNPTLpdQueue.set_completion (None)
            self.btnNPTLpdProbe.set_sensitive (False)
            if len (device.uri) > 6:
                host = device.uri[6:]
                i = host.find ("/")
                if i != -1:
                    printer = host[i + 1:]
                    host = host[:i]
                else:
                    printer = ""
                self.entNPTLpdHost.set_text (host)
                self.entNPTLpdQueue.set_text (printer)
                location = host
                self.btnNPTLpdProbe.set_sensitive (True)
        elif device.uri == "smb":
            self.entSMBURI.set_text('')
            self.btnSMBVerify.set_sensitive(False)
        elif device.type == "smb":
            self.entSMBUsername.set_text ('')
            self.entSMBPassword.set_text ('')
            self.entSMBURI.set_text(device.uri[6:])
            self.set_btnSMBVerify_sensitivity (True)
        else:
            if device.uri:
                self.entNPTDevice.set_text(device.uri)

        try:
            if len (location) == 0 and self.device.device_class == "direct":
                # Set location to the name of this host.
                if (self._host == 'localhost' or
                    self._host[0] == '/'):
                    u = os.uname ()
                    location = u[1]
                else:
                    location = self._host

            # Pre-fill location field.
            self.entNPLocation.set_text (location)
        except:
            nonfatalException ()

        self.setNPButtons()

    def on_entNPTLpdHost_changed(self, ent):
        hostname = ent.get_text()
        self.btnNPTLpdProbe.set_sensitive (len (hostname) > 0)
        self.setNPButtons()

    def on_entNPTLpdQueue_changed(self, ent):
        self.setNPButtons()

    def on_btnNPTLpdProbe_clicked(self, button):
        # read hostname, probe, fill printer names
        hostname = self.entNPTLpdHost.get_text()
        server = probe_printer.LpdServer(hostname)

        self.lblWait.set_markup ('<span weight="bold" size="larger">' +
                                 _('Searching') + '</span>\n\n' +
                                 _('Searching for printers'))
        self.WaitWindow.set_transient_for (self.NewPrinterWindow)
        self.WaitWindow.show_now ()
        busy (self.WaitWindow)
        def stop (widget, event):
            server.destroy ()
            return True

        self.WaitWindow.disconnect (self.WaitWindow_handler)
        signal = self.WaitWindow.connect ("delete-event", stop)
        printers = server.probe()
        self.WaitWindow.disconnect (signal)
        self.WaitWindow_handler = self.WaitWindow.connect ("delete-event",
                                                           on_delete_just_hide)
        self.WaitWindow.hide ()

        model = Gtk.ListStore (str)
        for printer in printers:
            model.append ([printer])

        completion = Gtk.EntryCompletion ()
        completion.set_model (model)
        completion.set_text_column (0)
        completion.set_minimum_key_length (0)
        self.entNPTLpdQueue.set_completion (completion)

    ### Find Network Printer
    def on_entNPTNetworkHostname_changed(self, ent):
        text = ent.get_text ()
        if text.find (":") != -1:
            # The user is typing in a URI.  In that case, switch to URI entry.
            ent.set_text ('')
            debugprint ("URI detected (%s) -> Enter URI" % text)
            self.entNPTDevice.set_text (text)
            model = self.tvNPDevices.get_model ()
            path = model.get_path (self.devices_uri_iter)
            self.tvNPDevices.set_cursor (path=path,
                                         start_editing=False)
            self.entNPTDevice.select_region (0, 0)
            self.entNPTDevice.set_position (-1)
            return

        allowed_chars = string.ascii_letters+string.digits+'_-.:%[]'
        self.entry_changed(ent, allowed_chars)
        s = ent.get_text ()
        self.btnNetworkFind.set_sensitive (len (s) > 0)
        self.lblNetworkFindNotFound.hide ()
        self.setNPButtons ()

    def on_btnNetworkFind_clicked(self, button):
        host = self.entNPTNetworkHostname.get_text ()

        def found_callback (new_device):
            if self.printer_finder is None:
                return

            GLib.idle_add (self.found_network_printer_callback, new_device)

        self.btnNetworkFind.set_sensitive (False)
        self.entNPTNetworkHostname.set_sensitive (False)
        self.network_found = 0
        self.lblNetworkFindNotFound.hide ()
        self.lblNetworkFindSearching.show_all ()
        finder = probe_printer.PrinterFinder ()
        self.inc_spinner_task ()
        finder.find (host, found_callback)
        self.printer_finder = finder

    def found_network_printer_callback (self, new_device):
        Gdk.threads_enter ()
        if new_device:
            self.network_found += 1
            dev = PhysicalDevice (new_device)
            try:
                i = self.devices.index (dev)

                # Adding a new URI to an existing physical device.
                self.devices[i].add_device (new_device)

                (path, column) = self.tvNPDevices.get_cursor ()
                if path:
                    model = self.tvNPDevices.get_model ()
                    iter = model.get_iter (path)
                    if model.get_value (iter, 1) == self.devices[i]:
                        self.on_tvNPDevices_cursor_changed (self.tvNPDevices)
            except ValueError:
                # New physical device.
                dev.checked_hplip = True
                self.devices.append (dev)
                self.devices.sort ()
                model = self.tvNPDevices.get_model ()
                iter = model.insert_before (None, self.devices_find_nw_iter,
                                            row=[dev.get_info (), dev, False])

                # If this is the first one we've found, select it.
                if self.network_found == 1:
                    path = model.get_path (iter)
                    self.tvNPDevices.set_cursor (path, None, False)
        else:
            self.printer_finder = None
            self.dec_spinner_task ()
            self.lblNetworkFindSearching.hide ()
            self.entNPTNetworkHostname.set_sensitive (True)
            self.btnNetworkFind.set_sensitive (True)
            if self.network_found == 0:
                self.lblNetworkFindNotFound.set_markup ('<i>' +
                                                        _("No printer was "
                                                          "found at that "
                                                          "address.") + '</i>')
                self.lblNetworkFindNotFound.show ()

        Gdk.threads_leave ()
    ###

    def getDeviceURI(self):
        if self.dialog_mode in ['printer_with_uri', 'ppd']:
            return self.device.uri

        type = self.device.type
        page = self.new_printer_device_tabs.get (type, self.PAGE_SELECT_DEVICE)
        device = type
        if page == self.PAGE_DESCRIBE_PRINTER:
            # The "no options page".  We already have the URI.
            device = self.device.uri
        elif type == "socket": # JetDirect
            host = self.entNPTJetDirectHostname.get_text()
            port = self.entNPTJetDirectPort.get_text()
            if host:
                device += "://" + host
                if port:
                    device += ":" + port
        elif type == "lpd": # LPD
            host = self.entNPTLpdHost.get_text()
            printer = self.entNPTLpdQueue.get_text()
            if host:
                device += "://" + host
                if printer:
                    device += "/" + printer
        elif type == "serial": # Serial
            options = []
            for widget, name in (
                (self.cmbNPTSerialBaud, "baud"),
                (self.cmbNPTSerialBits, "bits"),
                (self.cmbNPTSerialParity, "parity"),
                (self.cmbNPTSerialFlow, "flow")):
                model = widget.get_model ()
                iter = widget.get_active_iter()
                option = model.get_value (iter, 1)
                if option != "":
                    options.append(name + "=" + option)
            options = "+".join(options)
            device =  self.device.uri.split("?")[0] #"serial:/dev/ttyS%s"
            if options:
                device = device + "?" + options
        elif type == "smb":
            uri = self.entSMBURI.get_text ()
            (group, host, share, u, p) = SMBURI (uri=uri).separate ()
            user = ''
            password = ''
            if self.rbtnSMBAuthSet.get_active ():
                user = self.entSMBUsername.get_text ()
                password = self.entSMBPassword.get_text ()
            uri = SMBURI (group=group, host=host, share=share,
                          user=user, password=password).get_uri ()
            if uri:
                device += "://" + uri
        else:
            device = self.entNPTDevice.get_text()
        return device

    # PPD

    def on_rbtnNPFoomatic_toggled(self, widget):
        rbtn1 = self.rbtnNPFoomatic.get_active()
        rbtn2 = self.rbtnNPPPD.get_active()
        rbtn3 = self.rbtnNPDownloadableDriverSearch.get_active()
        self.tvNPMakes.set_sensitive(rbtn1)
        self.filechooserPPD.set_sensitive(rbtn2)

        if rbtn1:
            page = self.PAGE_DESCRIBE_PRINTER
        if rbtn2:
            page = self.PAGE_SELECT_DEVICE
        if rbtn3:
            page = self.PAGE_SELECT_INSTALL_METHOD
        self.ntbkPPDSource.set_current_page (page)

        if not rbtn3 and self.opreq:
            # Need to cancel a search in progress.
            for handler in self.opreq_handlers:
                self.opreq.disconnect (handler)

            self.opreq_handlers = None
            self.opreq.cancel ()
            self.opreq = None

            self.btnNPDownloadableDriverSearch.set_sensitive (True)
            self.btnNPDownloadableDriverSearch_label.set_text (_("Search"))
            # Clear printer list.
            model = Gtk.ListStore (str, str)
            combobox = self.cmbNPDownloadableDriverFoundPrinters
            combobox.set_model (model)
            combobox.set_sensitive (False)

        for widget in [self.entNPDownloadableDriverSearch,
                       self.cmbNPDownloadableDriverFoundPrinters]:
            widget.set_sensitive(rbtn3)
        self.btnNPDownloadableDriverSearch.\
            set_sensitive (rbtn3 and (self.opreq is None))

        self.setNPButtons()

    def on_filechooserPPD_selection_changed(self, widget):
        self.setNPButtons()

    def on_btnNPDownloadableDriverSearch_clicked(self, widget):
        self.searchedfordriverpackages = True
        if self.opreq is not None:
            for handler in self.opreq_handlers:
                self.opreq.disconnect (handler)

            self.opreq_handlers = None
            self.opreq.cancel ()
            self.opreq = None

        widget.set_sensitive (False)
        label = self.btnNPDownloadableDriverSearch_label
        label.set_text (_("Searching"))
        searchterm = self.entNPDownloadableDriverSearch.get_text ()
        debugprint ('Searching for "%s"' % repr (searchterm))
        self.opreq = OpenPrintingRequest ()
        self.opreq_handlers = []
        self.opreq_handlers.append (
            self.opreq.connect ('finished',
                                self.opreq_user_search_done))
        self.opreq_handlers.append (
            self.opreq.connect ('error',
                                self.opreq_user_search_error))
        self.opreq.searchPrinters (searchterm)
        self.cmbNPDownloadableDriverFoundPrinters.set_sensitive (False)

    def opreq_user_search_done (self, opreq, printers, drivers):
        for handler in self.opreq_handlers:
            opreq.disconnect (handler)

        self.opreq_user_search = True
        self.opreq_handlers = None
        self.opreq = None

        self.founddownloadabledrivers = True
        self.downloadable_printers = printers
        self.downloadable_drivers = drivers

        button = self.btnNPDownloadableDriverSearch
        label = self.btnNPDownloadableDriverSearch_label
        Gdk.threads_enter ()
        try:
            label.set_text (_("Search"))
            button.set_sensitive (True)
            model = Gtk.ListStore (str, str)
            if len (self.downloadable_printers) != 1:
                if len (self.downloadable_printers) > 1:
                    first = _("-- Select from search results --")
                else:
                    first = _("-- No matches found --")

                iter = model.append (None)
                model.set_value (iter, 0, first)
                model.set_value (iter, 1, '')

            sorted_list = []
            for printer_id, printer_name in self.downloadable_printers:
                sorted_list.append ((printer_id, printer_name))

            sorted_list.sort (key=functools.cmp_to_key(lambda x, y: cups.modelSort (x[1], y[1])))
            sought = self.entNPDownloadableDriverSearch.get_text ().lower ()
            select_index = 0
            for id, name in sorted_list:
                iter = model.append (None)
                model.set_value (iter, 0, name)
                model.set_value (iter, 1, id)
                if name.lower () == sought:
                    select_index = model.get_path (iter)[0]
            combobox = self.cmbNPDownloadableDriverFoundPrinters
            combobox.set_model (model)
            combobox.set_active (select_index)
            combobox.set_sensitive (True)
            self.setNPButtons ()
        except:
            nonfatalException()

        Gdk.threads_leave ()

    def opreq_user_search_error (self, opreq, status, err):
        debugprint ("OpenPrinting request failed (%d): %s" % (status,
                                                              repr (err)))
        self.opreq_user_search_done (opreq, list(), dict())

    def on_cmbNPDownloadableDriverFoundPrinters_changed(self, widget):
        self.setNPButtons ()

        if self.opreq is not None:
            for handler in self.opreq_handlers:
                self.opreq.disconnect (handler)

            self.opreq_handlers = None
            self.opreq.cancel ()
            self.opreq = None
            self.btnNPDownloadableDriverSearch.set_sensitive (True)
            self.btnNPDownloadableDriverSearch_label.set_text (_("Search"))

    def fillDownloadableDrivers(self):
        print ("filldownloadableDrivers")
        self.downloadable_driver_for_printer = None
        if self.opreq_user_search == True:
            widget = self.cmbNPDownloadableDriverFoundPrinters
            model = widget.get_model ()
            iter = widget.get_active_iter ()
            if iter:
                printer_id = model.get_value (iter, 1)
                printer_str = model.get_value (iter, 0)
                if printer_id == '':
                    widget.set_active (1)
                    iter = widget.get_active_iter ()
                    if iter:
                        printer_id = model.get_value (iter, 1)
                        printer_str = model.get_value (iter, 0)
                    else:
                        printer_id = None
                        printer_str = None
            else:
                printer_id = None
                printer_str = None
        else:
            printer_id, printer_str = self.downloadable_printers[0]

        if printer_id is None:
            # If none selected, show all.
            # This also happens for ID-matching.
            printer_ids = [x[0] for x in self.downloadable_printers]
        else:
            printer_ids = [printer_id]

        if printer_str:
            self.downloadable_driver_for_printer = printer_str

        model = Gtk.ListStore (str,                     # driver name
                               GObject.TYPE_PYOBJECT)   # driver data
        recommended_iter = None
        first_iter = None
        for printer_id in printer_ids:
            drivers = self.downloadable_drivers[printer_id]
            for driver in drivers.values ():
                if ((not 'ppds' in driver or
                     len(driver['ppds']) <= 0) and
                    (config.DOWNLOADABLE_ONLYPPD or
                     (not self._getDriverInstallationInfo (driver)))):
                    debugprint ("Removed invalid driver entry %s" % \
                                driver['name'])
                    continue
                iter = model.append (None)
                if first_iter is None:
                    first_iter = iter

                model.set_value (iter, 0, driver['name'])
                model.set_value (iter, 1, driver)

                if driver['recommended']:
                    recommended_iter = iter

        if first_iter is None:
            return False

        if not self.rbtnNPDownloadableDriverSearch.get_active() and \
           self.dialog_mode != "download_driver":
            iter = model.append (None)
            model.set_value (iter, 0, _("Local Driver"))
            model.set_value (iter, 1, 0)

        if recommended_iter is None:
            recommended_iter = first_iter

        treeview = self.tvNPDownloadableDrivers
        treeview.set_model (model)
        if recommended_iter is not None:
            treeview.get_selection ().select_iter (recommended_iter)
        self.on_tvNPDownloadableDrivers_cursor_changed(treeview)
        return True

    def on_rbtnNPDownloadLicense_toggled(self, widget):
        self.setNPButtons ()

    # PPD from foomatic

    def fillMakeList(self):
        self.recommended_make_selected = False
        makes = self.ppds.getMakes()
        model = self.tvNPMakes.get_model()
        model.clear()
        found = False
        if self.auto_make:
            auto_make_norm = cupshelpers.ppds.normalize (self.auto_make)
        else:
            auto_make_norm = None

        for make in makes:
            recommended = (auto_make_norm and
                           cupshelpers.ppds.normalize (make) == auto_make_norm)
            if self.device and self.device.make_and_model and recommended:
                text = make + _(" (recommended)")
            else:
                text = make

            iter = model.append((text, make,))
            if recommended:
                path = model.get_path(iter)
                self.tvNPMakes.set_cursor (path, None, False)
                self.tvNPMakes.scroll_to_cell(path, None,
                                              True, 0.5, 0.5)
                found = True

        if not found:
            self.tvNPMakes.set_cursor (Gtk.TreePath(), None, False)
            self.tvNPMakes.scroll_to_cell(0, None, True, 0.0, 0.0)

        # Also pre-fill the OpenPrinting.org search box.
        search = ''
        if self.device and self.device.id_dict:
            devid_dict = self.device.id_dict
            if devid_dict["MFG"] and devid_dict["MDL"]:
                search = devid_dict["MFG"] + " " + devid_dict["MDL"]
            elif devid_dict["DES"]:
                search = devid_dict["DES"]
            elif devid_dict["MFG"]:
                search = devid_dict["MFG"]
        if search == '' and self.auto_make is not None:
            search += self.auto_make
            if self.auto_model is not None:
                search += " " + self.auto_model
        if (search.startswith("Generic") or
            search.startswith("Unknown")):
            search = ''
        self.entNPDownloadableDriverSearch.set_text (search)

    def on_tvNPMakes_cursor_changed(self, tvNPMakes):
        path, column = tvNPMakes.get_cursor()
        if path is not None and self.ppds is not None:
            model = tvNPMakes.get_model ()
            iter = model.get_iter (path)
            self.NPMake = model.get(iter, 1)[0]
            recommended_make = (self.auto_make and
                                cupshelpers.ppds.normalize (self.auto_make) ==
                                cupshelpers.ppds.normalize (self.NPMake))
            self.recommended_make_selected = recommended_make
            self.fillModelList()

    def fillModelList(self):
        self.recommended_model_selected = False
        models = self.ppds.getModels(self.NPMake)
        model = self.tvNPModels.get_model()
        model.clear()
        selected = False
        is_auto_make = (cupshelpers.ppds.normalize (self.NPMake) ==
                        cupshelpers.ppds.normalize (self.auto_make))
        if is_auto_make:
            auto_model_norm = cupshelpers.ppds.normalize (self.auto_model)

        for pmodel in models:
            recommended = (is_auto_make and
                           cupshelpers.ppds.normalize (pmodel) ==
                           auto_model_norm)
            if self.device and self.device.make_and_model and recommended:
                text = pmodel + _(" (recommended)")
            else:
                text = pmodel

            iter = model.append((text, pmodel,))
            if recommended:
                path = model.get_path(iter)
                self.tvNPModels.set_cursor (path, None, False)
                self.tvNPModels.scroll_to_cell(path, None,
                                               True, 0.5, 0.5)
                selected = True
        if not selected:
            self.tvNPModels.set_cursor (Gtk.TreePath(), None, False)
            self.tvNPModels.scroll_to_cell(0, None, True, 0.0, 0.0)
        self.tvNPModels.columns_autosize()

    def fillDriverList(self, pmake, pmodel):
        self.NPModel = pmodel
        model = self.tvNPDrivers.get_model()
        model.clear()

        if self.device:
            devid = self.device.id_dict
        else:
            devid = None

        if (self.device and self.device.make_and_model and
            self.recommended_model_selected and
            self.id_matched_ppdnames):
            # Use the actual device-make-and-model string.
            make_and_model = self.device.make_and_model

            # and the ID-matched list of PPDs.
            self.NPDrivers = self.id_matched_ppdnames
            debugprint ("ID matched PPDs: %s" % repr (self.NPDrivers))
        elif self.ppds:
            # Use a generic make and model string for generating the
            # driver preference list.
            make_and_model = pmake + " " + pmodel
            ppds = self.ppds.getInfoFromModel(pmake, pmodel)
            ppdnames = list(ppds.keys ())

            files = self.installed_driver_files
            try:
                self.NPDrivers = self.ppds.orderPPDNamesByPreference(ppdnames,
                                                                     files,
                                                                     make_and_model,
                                                                     devid)
            except:
                nonfatalException ()
                self.NPDrivers = ppdnames

            # Put the current driver first.
            if self.auto_driver and self.device:
                drivers = []
                for driver in self.NPDrivers:
                    if driver == self.auto_driver:
                        drivers.insert (0, driver)
                    else:
                        drivers.append (driver)

                self.NPDrivers = drivers
        else:
            # No available PPDs for some reason(!)
            debugprint ("No PPDs available?")
            self.NPDrivers = []

        driverlist = []
        NPDrivers = []
        i = 0
        for ppdname in self.NPDrivers:
            ppd = self.ppds.getInfoFromPPDName (ppdname)
            driver = _singleton (ppd["ppd-make-and-model"])
            driver = driver.replace(" (recommended)", "")

            try:
                lpostfix = " [%s]" % _singleton (ppd["ppd-natural-language"])
                driver += lpostfix
            except KeyError:
                pass

            duplicate = driver in driverlist

            if (not (self.device and self.device.make_and_model) and
                self.auto_driver == ppdname):
                driverlist.append (driver)
                NPDrivers.append (ppdname)
                i += 1
                iter = model.append ((driver +
                                      _(" (Current)"),))
                path = model.get_path (iter)
                self.tvNPDrivers.get_selection().select_path(path)
                self.tvNPDrivers.scroll_to_cell(path, None, True, 0.5, 0.0)
            elif self.device and i == 0:
                driverlist.append (driver)
                NPDrivers.append (ppdname)
                i += 1
                iter = model.append ((driver +
                                      _(" (recommended)"),))
                path = model.get_path (iter)
                self.tvNPDrivers.get_selection().select_path(path)
                self.tvNPDrivers.scroll_to_cell(path, None, True, 0.5, 0.0)
            else:
                if duplicate:
                    continue
                driverlist.append (driver)
                NPDrivers.append (ppdname)
                i += 1
                model.append((driver, ))

        self.NPDrivers = NPDrivers
        self.tvNPDrivers.columns_autosize()

    def on_NPDrivers_query_tooltip(self, tv, x, y, keyboard_mode, tooltip):
        if keyboard_mode:
            path = tv.get_cursor()[0]
            if path is None:
                return False
        else:
            bin_x, bin_y = tv.convert_widget_to_bin_window_coords(x, y)
            ret = tv.get_path_at_pos (bin_x, bin_y)
            if ret is None:
                return False
            path = ret[0]

        drivername = self.NPDrivers[path[0]]
        ppddict = self.ppds.getInfoFromPPDName(drivername)
        markup = _singleton (ppddict['ppd-make-and-model'])
        if (drivername.startswith ("foomatic:")):
            markup += " "
            markup += _("This PPD is generated by foomatic.")
        tooltip.set_markup(markup)
        return True

    def on_tvNPModels_cursor_changed(self, widget):
        path, column = widget.get_cursor()
        if path is not None:
            model = widget.get_model ()
            iter = model.get_iter (path)
            pmodel = model.get(iter, 1)[0]

            # Find out if this is the auto-detected make and model
            recommended_model = (self.recommended_make_selected and
                                 self.auto_model and
                                 self.auto_model.lower () == pmodel.lower ())
            self.recommended_model_selected = recommended_model
            self.fillDriverList(self.NPMake, pmodel)
            self.on_tvNPDrivers_cursor_changed(self.tvNPDrivers)

    def on_tvNPDrivers_cursor_changed(self, widget):
        self.setNPButtons()

    def on_tvNPDownloadableDrivers_cursor_changed(self, widget):
        # Clear out the properties.
        self.lblNPDownloadableDriverSupplier.set_text ('')
        self.lblNPDownloadableDriverLicense.set_text ('')
        self.lblNPDownloadableDriverDescription.set_text ('')
        self.lblNPDownloadableDriverSupportContacts.set_text ('')
        self.rbtnNPDownloadLicenseNo.set_active (True)
        self.frmNPDownloadableDriverLicenseTerms.hide ()

        selection = widget.get_selection ()
        if selection is None:
            return

        model, iter = selection.get_selected ()
        if not iter:
            path, column = widget.get_cursor()
            if iter:
                iter = model.get_iter (path)
            else:
                return
        driver = model.get_value (iter, 1)
        if driver == 0:
            self.ntbkNPDownloadableDriverProperties.set_current_page (self.PAGE_DESCRIBE_PRINTER)
            self.setNPButtons()
            return
        self.ntbkNPDownloadableDriverProperties.set_current_page (self.PAGE_SELECT_DEVICE)
        supplier = driver.get('supplier', _("OpenPrinting"))
        vendor = self.cbNPDownloadableDriverSupplierVendor
        active = driver['manufacturersupplied']

        def set_protect_active (widget, active):
            widget.protect_active = active
            widget.set_active (active)

        set_protect_active (vendor, active)
        self.lblNPDownloadableDriverSupplier.set_text (supplier)

        license = driver.get('license', _("Distributable"))
        patents = self.cbNPDownloadableDriverLicensePatents
        free = self.cbNPDownloadableDriverLicenseFree
        set_protect_active (patents, driver['patents'])
        set_protect_active (free, driver['freesoftware'])
        self.lblNPDownloadableDriverLicense.set_text (license)

        description = driver.get('shortdescription', _("None"))
        self.lblNPDownloadableDriverDescription.set_markup (description)

        if 'functionality' in driver:
            functionality = driver['functionality']
            for field in ["Graphics", "LineArt", "Photo", "Text"]:
                key = field.lower ()
                value = None
                hs = self.__dict__.get ("hsDownloadableDriverPerf%s" % field)
                unknown = self.__dict__.get ("lblDownloadableDriverPerf%sUnknown"
                                             % field)
                if key in functionality:
                    if hs:
                        try:
                            value = int (functionality[key])
                            hs.set_range (0, 100)
                            hs.set_value (value)
                            hs.show_all ()
                            unknown.hide ()
                        except:
                            pass

                if value is None:
                    hs.hide ()
                    unknown.show_all ()

        supportcontacts = ""
        if 'supportcontacts' in driver:
            for supportentry in driver['supportcontacts']:
                if supportentry['name']:
                    supportcontact = " - " + supportentry['name']
                    supportcontact_extra = ""
                    if supportentry['url']:
                        supportcontact_extra = supportcontact_extra + \
                            supportentry['url']
                    if supportentry['level']:
                        if supportcontact_extra:
                            supportcontact_extra = supportcontact_extra + _(", ")
                        supportcontact_extra = supportcontact_extra + \
                            supportentry['level']
                    if supportcontact_extra:
                        supportcontact = supportcontact + \
                            _("\n(%s)") % supportcontact_extra
                        if supportcontacts:
                            supportcontacts = supportcontacts + "\n"
                        supportcontacts = supportcontacts + supportcontact
        if not supportcontacts:
            supportcontacts = _("No support contacts known")
        self.lblNPDownloadableDriverSupportContacts.set_text (supportcontacts)
        if 'licensetext' in driver:
            self.frmNPDownloadableDriverLicenseTerms.show ()
            terms = driver.get('licensetext', _("Not specified."))
            self.tvNPDownloadableDriverLicense.get_buffer ().set_text (terms)
        else:
            self.frmNPDownloadableDriverLicenseTerms.hide ()
        if not driver['nonfreesoftware'] and not driver['patents']:
            self.rbtnNPDownloadLicenseYes.set_active (True)
            self.rbtnNPDownloadLicenseYes.hide ()
            self.rbtnNPDownloadLicenseNo.hide ()
        else:
            self.rbtnNPDownloadLicenseNo.set_active (True)
            self.rbtnNPDownloadLicenseYes.show ()
            self.rbtnNPDownloadLicenseNo.show ()
            self.frmNPDownloadableDriverLicenseTerms.show ()
            terms = driver.get('licensetext', _("Not specified."))
            self.tvNPDownloadableDriverLicense.get_buffer ().set_text (terms)

        if 'ppds' in driver and len(driver["ppds"]) > 0:
            self.founddownloadableppd = True
        else:
            self.founddownloadableppd = False

        self.setNPButtons()

    def getNPPPD(self):
        ppd = None
        try:
            if ((self.rbtnNPFoomatic.get_active() or
                    len(self.installed_driver_files) > 0) and
                self.founddownloadableppd == False):
                model, iter = self.tvNPDrivers.get_selection().get_selected()
                nr = model.get_path(iter)[0]
                ppd = self.NPDrivers[nr]
            elif self.rbtnNPPPD.get_active():
                ppd = cups.PPD(self.filechooserPPD.get_filename())
            else:
                # PPD of the driver downloaded from OpenPrinting XXX
                treeview = self.tvNPDownloadableDrivers
                model, iter = treeview.get_selection ().get_selected ()
                driver = model.get_value (iter, 1)
                if driver != 0 and 'ppds' in driver:
                    # Only need to download a PPD.
                    if (len(driver['ppds']) > 0):
                        file_to_download = driver['ppds'][0]
                        debugprint ("ppd file to download [" + file_to_download+ "]")
                        file_to_download = file_to_download.strip()
                        if (len(file_to_download) > 0):
                            ppdurlobj = urllib.request.urlopen(file_to_download)
                            ppdcontent = ppdurlobj.read()
                            ppdurlobj.close()
                            with tempfile.NamedTemporaryFile () as tmpf:
                                tmpf.write(ppdcontent)
                                tmpf.flush ()
                                ppd = cups.PPD(tmpf.name)

        except (RuntimeError, urllib.error.HTTPError) as e:
            debugprint ("RuntimeError: " + repr (e))
            if self.rbtnNPFoomatic.get_active():
                # Foomatic database problem of some sort.
                err_title = _('Database error')
                err_text = _("The '%s' driver cannot be "
                             "used with printer '%s %s'.")
                model, iter = (self.tvNPDrivers.get_selection().
                               get_selected())
                nr = model.get_path(iter)[0]
                driver = self.NPDrivers[nr]
                if driver.startswith ("gutenprint"):
                    # This printer references some XML that is not
                    # installed by default.  Point the user at the
                    # package they need to install.
                    err = _("You will need to install the '%s' package "
                            "in order to use this driver.") % \
                            "gutenprint-foomatic"
                else:
                    err = err_text % (driver, self.NPMake, self.NPModel)
            elif self.rbtnNPPPD.get_active():
                # This error came from trying to open the PPD file.
                err_title = _('PPD error')
                filename = self.filechooserPPD.get_filename()
                err = _('Failed to read PPD file.  Possible reason '
                        'follows:') + '\n'
                try:
                    # We want this to be in the current natural language,
                    # so we intentionally don't set LC_ALL=C here.
                    p = subprocess.Popen (['/usr/bin/cupstestppd',
                                           '-rvv', filename],
                                          close_fds=True,
                                          stdin=subprocess.DEVNULL,
                                          stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE)
                    (stdout, stderr) = p.communicate ()
                    err += stdout.decode ()
                except:
                    # Problem executing command.
                    raise
            else:
                # Failed to get PPD downloaded from OpenPrinting XXX
                err_title = _('Downloadable drivers')
                err = _("Failed to download PPD.")

            show_error_dialog (err_title, err, self.NewPrinterWindow)
            return None

        debugprint("ppd: " + repr(ppd))

        if isinstance(ppd, str):
            self.cups._begin_operation (_("fetching PPD"))
            try:
                if ppd != "raw":
                    f = self.cups.getServerPPD(ppd)
                    ppd = cups.PPD(f)
                    os.unlink(f)
            except RuntimeError:
                nonfatalException()
                debugprint ("libcups from CUPS 1.3 not available: never mind")
            except cups.IPPError:
                nonfatalException()
                debugprint ("CUPS 1.3 server not available: never mind")

            self.cups._end_operation ()

        return ppd

    # Installable Options

    def fillNPInstallableOptions(self):
        debugprint ("Examining installable options")
        self.installable_options = False
        self.options = { }

        container = self.vbNPInstallOptions
        for child in container.get_children():
            container.remove(child)

        if not self.ppd:
            l = Gtk.Label(label=_("No Installable Options"))
            container.add(l)
            l.show()
            debugprint ("No PPD so no installable options")
            return

        # build option tabs
        for group in self.ppd.optionGroups:
            if group.name != "InstallableOptions":
                continue
            self.installable_options = True
            grid = Gtk.Grid()
            grid.set_column_spacing(6)
            grid.set_row_spacing(6)
            container.add(grid)
            rows = 0

            for nr, option in enumerate(group.options):
                if option.keyword == "PageRegion":
                    continue
                rows += 1
                o = OptionWidget(option, self.ppd, self)
                grid.attach(o.conflictIcon, 0, nr, 1, 1)

                hbox = Gtk.Box()
                if o.label:
                    a = Gtk.Alignment.new (0.5, 0.5, 1.0, 1.0)
                    a.set_padding (0, 0, 0, 6)
                    a.add (o.label)
                    grid.attach(a, 1, nr, 1, 1)
                    grid.attach(hbox, 2, nr, 1, 1)
                else:
                    grid.attach(hbox, 1, nr, 2, 1)
                hbox.pack_start(o.selector, False, False, 0)
                self.options[option.keyword] = o
        if not self.installable_options:
            l = Gtk.Label(label=_("No Installable Options"))
            container.add(l)
            l.show()
        self.scrNPInstallableOptions.hide()
        self.scrNPInstallableOptions.show_all()


    # Create new Printer
    def on_btnNPApply_clicked(self, widget):
        if self.fetchDevices_conn:
            self.fetchDevices_conn.destroy ()
            self.fetchDevices_conn = None
            self.dec_spinner_task ()

        if self.ppdsloader:
            self.ppdsloader.destroy ()
            self.ppdsloader = None

        if self.printer_finder:
            self.printer_finder.cancel ()
            self.printer_finder = None
            self.dec_spinner_task ()

        if self.dialog_mode in ("class", "printer", "printer_with_uri"):
            name = self.entNPName.get_text()
            location = self.entNPLocation.get_text()
            info = self.entNPDescription.get_text()
            isShared = self.isSharedCbx.get_active()
        else:
            name = self._name

        ppd = self.ppd

        if self.dialog_mode == "class":
            members = getCurrentClassMembers(self.tvNCMembers)
            try:
                for member in members:
                    try:
                        self.cups.addPrinterToClass(member, name)
                    except RuntimeError:
                        # Printer already in class?
                        continue
            except cups.IPPError as e:
                (e, msg) = e.args
                self.show_IPP_Error(e, msg)
                return
        elif self.dialog_mode == "printer" or \
                self.dialog_mode == "printer_with_uri":
            uri = None
            if self.device.uri:
                uri = self.device.uri
            else:
                uri = self.getDeviceURI()
            if not self.ppd: # XXX needed?
                # Go back to previous page to re-select driver.
                self.nextNPTab(-1)
                return

            # write Installable Options to ppd
            for option in self.options.values():
                option.writeback()

            busy (self.NewPrinterWindow)
            while Gtk.events_pending ():
                Gtk.main_iteration ()
            self.cups._begin_operation (_("adding printer %s") % name)
            try:
                if isinstance(ppd, str):
                    self.cups.addPrinter(name, ppdname=ppd,
                         device=uri, info=info, location=location)
                elif ppd is None: # raw queue
                    self.cups.addPrinter(name, device=uri,
                                         info=info, location=location)
                else:
                    # Note: LC_MESSAGES is used here to determine the
                    # page size instead of LC_PAPER. This is not
                    # really correct, but it's what CUPS does so to
                    # avoid confusion we'll follow that method.
                    cupshelpers.setPPDPageSize(ppd, self.language[0])
                    self.cups.addPrinter(name, ppd=ppd, device=uri,
                                         info=info, location=location)
            except cups.IPPError as e:
                (e, msg) = e.args
                ready (self.NewPrinterWindow)
                self.show_IPP_Error(e, msg)
                self.cups._end_operation()
                return
            except:
                ready (self.NewPrinterWindow)
                self.cups._end_operation()
                fatalException (1)
            self.cups._end_operation()
            ready (self.NewPrinterWindow)
        if self.dialog_mode in ("class", "printer", "printer_with_uri"):
            self.cups._begin_operation (_("modifying printer %s") % name)
            try:
                cupshelpers.activateNewPrinter (self.cups, name)
                self.cups.setPrinterLocation(name, location)
                self.cups.setPrinterInfo(name, info)
                self.cups.setPrinterShared(name, isShared)
            except cups.IPPError as e:
                (e, msg) = e.args
                self.show_IPP_Error(e, msg)
                self.cups._end_operation ()
                return
            self.cups._end_operation ()
        elif self.dialog_mode == "device":
            self.cups._begin_operation (_("modifying printer %s") % name)
            try:
                uri = self.getDeviceURI()
                self.cups.addPrinter(name, device=uri)
            except cups.IPPError as e:
                (e, msg) = e.args
                self.show_IPP_Error(e, msg)
                self.cups._end_operation ()
                return
            self.cups._end_operation ()
        elif self.dialog_mode == "ppd":
            if not ppd:
                ppd = self.ppd = self.getNPPPD()
                if not ppd:
                    # Go back to previous page to re-select driver.
                    self.nextNPTab(-1)
                    return

            self.cups._begin_operation (_("modifying printer %s") % name)
            # set ppd on server and retrieve it
            # cups doesn't offer a way to just download a ppd ;(=
            raw = False
            if isinstance(ppd, str):
                if self.rbtnChangePPDasIs.get_active():
                    # To use the PPD as-is we need to prevent CUPS copying
                    # the old options over.  Do this by setting it to a
                    # raw queue (no PPD) first.
                    try:
                        self.cups.addPrinter(name, ppdname='raw')
                    except cups.IPPError as e:
                        (e, msg) = e.args
                        self.show_IPP_Error(e, msg)
                try:
                    self.cups.addPrinter(name, ppdname=ppd)
                except cups.IPPError as e:
                    (e, msg) = e.args
                    self.show_IPP_Error(e, msg)
                    self.cups._end_operation ()
                    return

                try:
                    filename = self.cups.getPPD(name)
                    ppd = cups.PPD(filename)
                    os.unlink(filename)
                except cups.IPPError as e:
                    (e, msg) = e.args
                    if e == cups.IPP_NOT_FOUND:
                        raw = True
                    else:
                        self.show_IPP_Error(e, msg)
                        self.cups._end_operation ()
                        return
            else:
                # We have an actual PPD to upload, not just a name.
                if ((not self.rbtnChangePPDasIs.get_active()) and
                    isinstance (self.orig_ppd, cups.PPD)):
                    cupshelpers.copyPPDOptions(self.orig_ppd, ppd)
                else:
                    cupshelpers.setPPDPageSize(ppd, self.language[0])

                # write Installable Options to ppd
                for option in self.options.values():
                    option.writeback()

                try:
                    self.cups.addPrinter(name, ppd=ppd)
                except cups.IPPError as e:
                    (e, msg) = e.args
                    self.show_IPP_Error(e, msg)
                    self.cups._end_operation ()
                    return

            self.cups._end_operation ()

        elif self.dialog_mode == "download_driver":
            self.nextNPTab(0);

        self.NewPrinterWindow.hide()
        if self.dialog_mode in ["printer", "printer_with_uri", "class"]:
            self.emit ('printer-added', name)
        elif self.dialog_mode == "download_driver":
            self.emit ('driver-download-checked', self.installed_driver_files)
        else:
            self.emit ('printer-modified', name, self.orig_ppd != self.ppd)

        self.device = None
        self.printers = {}

def show_help():
    print ("\nThis is the test/debug mode of the new-printer dialog of " \
           "system-config-printer.\n\n"
           "Options:\n\n"
           "  --setup-printer URI\n"
           "            Select the (detected) CUPS device URI on start up\n"
           "            and run the new-printer wizard for it.\n\n"
           "  --devid   Supply a device ID which should be used for the\n"
           "            setup of the new printer with \"--setup-printer\".\n"
           "            This can be any printer's ID, so that driver \n"
           "            selection can be tested for printers which are not\n"
           "            physically available.\n")

if __name__ == '__main__':
    import getopt
    try:
        opts, args = getopt.gnu_getopt (sys.argv[1:], '',
                                        ['setup-printer=',
                                         'devid='])
    except getopt.GetoptError:
        show_help ()
        sys.exit (1)

    setup_printer = None
    devid = ""
    for opt, optarg in opts:
        if opt == '--setup-printer':
            setup_printer = optarg
        elif opt == '--devid':
            devid = optarg

    os.environ["SYSTEM_CONFIG_PRINTER_UI"] = "ui"
    import ppdippstr
    locale.setlocale (locale.LC_ALL, "")
    ppdippstr.init ()
    set_debugging (True)
    cupshelpers.set_debugprint_fn (debugprint)

    n = NewPrinterGUI ()
    def on_signal (*args):
        Gtk.main_quit ()

    n.connect ("printer-added", on_signal)
    n.connect ("printer-modified", on_signal)
    n.connect ("dialog-canceled", on_signal)
    if setup_printer is not None:
        n.init ("printer_with_uri", device_uri=setup_printer, devid=devid)
    else:
        n.init ("printer")
    Gtk.main ()

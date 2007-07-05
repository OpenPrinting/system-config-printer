#!/bin/env python

import sys

sys.path.append("/home/ffesti/CVS/pycups")

import gtk.glade, cups
import gobject # for TYPE_STRING
from optionwidgets import OptionWidget
from foomatic import Foomatic
from nametree import BuildTree

domain='system-config-printer'
import locale
locale.setlocale (locale.LC_ALL, "")
from rhpl.translate import _, N_
import rhpl.translate as translate
translate.textdomain (domain)
gtk.glade.bindtextdomain (domain)

class GUI:

    def __init__(self):

        self.password = ''
        self.passwd_retry = False
        cups.setPasswordCB(self.cupsPasswdCallback)        

        self.changed = set() # of options

        self.cups = cups.Connection()
        # XXX Error handling
        
        self.foomatic = Foomatic() # this works on the local db


        # WIDGETS
        # =======
        self.xml = gtk.glade.XML("system-config-printer.glade")
        self.getWidgets("MainWindow", "tvMainList", "ntbkMain",
                        "btnApply", "btnRevert", "imgConflict",
                        "entPDescription", "entPLocation", "lblPMakeModel",
                        "lblPState", "entPDevice",
                        "vbPInstallOptions", "vbPOptions", "ntbkPrinter",
                        "swPInstallOptions", "swPOptions",
                        "btnNewPrinter", "btnNewClass", "btnCopy", "btnDelete",
                        "new_printer", "new_class", "copy", "delete",

                        "ConnectDialog", "chkEncrypted", "cmbServername",
                        "entUser",

                        "PasswordDialog", "lblPasswordPrompt", "entPasswd",

                        "ErrorDialog", "lblError",

                        "NewPrinterWindow", "ntbkNewPrinter",
                        "btnNPBack", "btnNPForward", "btnNPApply",
                        "entNPName", "entNPDescription", "entNPLocation",
                        "cmbNPType", "ntbkNPType",
                        "tvNPDrivers",                        
                        
                        )
        self.setTitle ()
        self.ntbkMain.set_show_tabs(False)
        self.ntbkNewPrinter.set_show_tabs(False)
        self.ntbkNPType.set_show_tabs(False)
        self.prompt_primary = self.lblPasswordPrompt.get_label ()

        # Setup main list
        column = gtk.TreeViewColumn()
        cell = gtk.CellRendererText()
        cell.markup = True
        column.pack_start(cell, True)
        self.tvMainList.append_column(column)
        self.mainlist = gtk.ListStore(str, str)

        self.tvMainList.set_model(self.mainlist)
        column.set_attributes(cell, text=0)
        selection = self.tvMainList.get_selection()
        selection.set_mode(gtk.SELECTION_BROWSE)
        selection.set_select_function(self.maySelectItem)
        
        self.populateList()

        # setup PPD tree
        model = gtk.TreeStore(str)
        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn('States', cell, text=0)
        self.tvNPDrivers.set_model(model)
        self.tvNPDrivers.append_column(column)
        self.tvNPDriversModel = model

        self.tooltips = gtk.Tooltips()
        self.tooltips.enable()
        
        self.xml.signal_autoconnect(self)

    def getWidgets(self, *names):
        for name in names:
            widget = self.xml.get_widget(name)
            if widget is None:
                raise ValueError, "Widget '%s' not found" % name
            setattr(self, name, widget)

    def setTitle(self):
        host = cups.getServer ()
        if host[0] == '/':
            host = 'localhost'
        self.MainWindow.set_title ("Printer configuration - %s" % host)

    def populateList(self):
        self.mainlist.clear()

        self.mainlist.append(("Server Settings", 'Settings'))

        # Printers
        self.printers = self.cups.getPrinters()
        names = self.printers.keys()
        names.sort()

        self.mainlist.append(("Printers:", ''))

        for name in names:
            #if self.printers[name]["printer-type"] & cups.CUPS_PRINTER_REMOTE:
            #    continue
            self.mainlist.append(('  ' + name, 'Printer'))
        
        # Classes
        self.classes = self.cups.getClasses()
        names = self.classes.keys()
        names.sort()
        
        self.mainlist.append(("Classes:", ''))
        for name in names:
            self.mainlist.append((class_, 'Class'))       


        # Selection
        selection = self.tvMainList.get_selection()
        selection.select_path(0)
        self.on_tvMainList_cursor_changed(self.tvMainList)

    def maySelectItem(self, selection):
        result = self.mainlist.get_value(
            self.mainlist.get_iter(selection[0]), 1)
        return bool(result)

    def getSelectedItem(self):
        model, iter = self.tvMainList.get_selection().get_selected()
        name, type = model.get_value(iter, 0), model.get_value(iter, 1)
        return name.strip(), type

    # Connect to Server

    def on_connect_activate(self, widget):
        # Use browsed queues to build up a list of known IPP servers
        known_servers = [ 'localhost' ]
        for name in self.printers:
            printer = self.printers[name]
            if not (printer['printer-type'] & cups.CUPS_PRINTER_REMOTE):
                continue
            if not printer.has_key ('printer-uri-supported'):
                continue
            uri = printer['printer-uri-supported']
            if not uri.startswith ('ipp://'):
                continue
            uri = uri[6:]
            s = uri.find ('/')
            if s != -1:
                uri = uri[:s]
            s = uri.find (':')
            if s != -1:
                uri = uri[:s]
            if known_servers.count (uri) == 0:
                known_servers.append (uri)

        store = gtk.ListStore (gobject.TYPE_STRING)
        self.cmbServername.set_model (store)
        for server in known_servers:
            self.cmbServername.append_text (server)
        self.cmbServername.show ()

        self.cmbServername.child.set_text (cups.getServer ())
        self.entUser.set_text (cups.getUser ())
        self.chkEncrypted.set_active (cups.getEncryption () ==
                                      cups.HTTP_ENCRYPT_ALWAYS)

        # XXX check for unapplied changes
        self.cmbServername.grab_focus ()
        self.ConnectDialog.set_transient_for (self.MainWindow)
        response = self.ConnectDialog.run()
        if response != gtk.RESPONSE_OK:
            self.ConnectDialog.hide ()
            return

        if self.chkEncrypted.get_active():
            cups.setEncryption(cups.HTTP_ENCRYPT_ALWAYS)
        else:
            cups.setEncryption(cups.HTTP_ENCRYPT_IF_REQUESTED)

        servername = self.cmbServername.child.get_text()
        cups.setServer(servername)

        user = self.entUser.get_text()
        if user: cups.setUser(user)
        self.password = ''

        try:
            connection = cups.Connection() # XXX timeout?
            self.setTitle()
        except:
            connection = None

        if not connection: # error handling
            # XXX more Error handling
            return

        self.ConnectDialog.hide()
        self.cups = connection
        self.populateList()

    def on_btnCancelConnect_clicked(self, widget):
        self.ConnectWindow.hide()

    # Password handling

    def cupsPasswdCallback(self, querystring):
        if self.passwd_retry or len(self.password) == 0:
            self.lblPasswordPrompt.set_label (self.prompt_primary +
                                              querystring)
            self.PasswordDialog.set_transient_for (self.MainWindow)
            self.entPasswd.grab_focus ()

            result = self.PasswordDialog.run()
            self.PasswordDialog.hide()
            if result == gtk.RESPONSE_OK:
                self.password = self.entPasswd.get_text()
            else:
                self.password = ''
            self.passwd_retry = False
        else:
            self.passwd_retry = True
        return self.password
    
    def on_btnPasswdOk_clicked(self, widget):
        self.PasswordDialog.response(0)

    def on_btnPasswdCancel_clicked(self, widget):
        self.PasswordDialog.response(1)

    # Data handling

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

    def setDataButtonState(self):
        for button in [self.btnApply, self.btnRevert]:
            button.set_sensitive(bool(self.changed) and
                                 not bool(self.conflicts))

        if self.conflicts:
            self.imgConflict.show()
        else:
            self.imgConflict.hide()
            
    def on_btnApply_clicked(self, widget):
        name, type = self.getSelectedItem()
        if type == "Printer":
            self.save_printer(name)
        elif type == "Class":
            print "Apply Class"
        elif type == "Settings":
            print "Apply Settings"

    #def deselect_entry(self):
    #    if self.changed:

    def show_IPP_Error(self, exception, message):
        if exception == cups.IPP_NOT_AUTHORIZED:
            error_text = ('<span weight="bold" size="larger">' +
                          'Not authorized</span>\n\n' +
                          'The password may be incorrect.')
        else:
            error_text = ('<span weight="bold" size="larger">' +
                          'CUPS server error</span>\n\n' +
                          'There was an error during the CUPS ' +
                          "operation: '%s'." % message)
        self.lblError.set_markup(error_text)
        self.ErrorDialog.set_transient_for (self.MainWindow)
        self.ErrorDialog.run()
        self.ErrorDialog.hide()
        
            
    def save_printer(self, name):
        self.getPrinterSettings()
        self.passwd_retry = False # use cached Passwd 
        try:
            if self.ppd.nondefaultsMarked ():
                self.cups.addPrinter(name, ppd=self.ppd)

            printer = self.printers[name] 
            new_values = {
                "printer-location" : self.entPLocation.get_text(),
                "printer-info" : self.entPDescription.get_text(),
                "device-uri" : self.entPDevice.get_text(),
                }

            if new_values["printer-info"]!=printer["printer-info"]:
                self.passwd_retry = False # use cached Passwd 
                self.cups.setPrinterInfo(name, new_values["printer-info"])
            if new_values["printer-location"]!=printer["printer-location"]:
                self.passwd_retry = False # use cached Passwd 
                self.cups.setPrinterLocation(name,
                                             new_values["printer-location"])
            if new_values["device-uri"]!=printer["device-uri"]:
                self.passwd_retry = False # use cached Passwd 
                self.cups.setPrinterDevice(name, new_values["device-uri"])
            printer.update(new_values)
        except cups.IPPError, (e, s):
            self.show_IPP_Error(e, s)

    def on_tvMainList_cursor_changed(self, list):
        #if self.changed and not self.ask_apply_revert("",""):
        #    
        #    print "NOT DISCARDING"

        name, type = self.getSelectedItem()

        item_selected = True
        if type == "Settings":
            self.ntbkMain.set_current_page(0)
            item_selected = False
        elif type == 'Printer':
            self.fillPrinterTab(name)
            self.ntbkMain.set_current_page(1)
        elif type == 'Class':
            self.fillClassTab(name)
            self.ntbkMain.set_current_page(2)

        for item in [self.copy, self.delete, self.btnCopy, self.btnDelete]:
            item.set_sensitive(item_selected)
            
    def fillPrinterTab(self, name):
        self.changed = set() # of options
        self.options = {} # keyword -> Option object
        self.conflicts = set() # of options

        # XXX self.option_changed(None, False) # set Apply/Revert buttons
        
        # Description page
        printer_states = { cups.IPP_PRINTER_IDLE: "Idle",
                           cups.IPP_PRINTER_PROCESSING: "Processing",
                           cups.IPP_PRINTER_BUSY: "Busy",
                           cups.IPP_PRINTER_STOPPED: "Stopped" }

        printer = self.printers[name] 
        self.entPDescription.set_text(printer.get("printer-info", ""))
        self.entPLocation.set_text(printer.get("printer-location", ""))
        self.lblPMakeModel.set_text(printer.get("printer-make-and-model", ""))

        statestr = "Unknown"
        state = printer.get("printer-state", -1)
        if printer_states.has_key (state):
            statestr = printer_states[state]
        self.lblPState.set_text(statestr)

        self.entPDevice.set_text(printer.get("device-uri", ""))

        # clean Installable Options Tab
        for widget in self.vbPInstallOptions.get_children():
            self.vbPInstallOptions.remove(widget)
        tab_nr = self.ntbkPrinter.page_num(self.swPInstallOptions)
        if tab_nr != -1:
            self.ntbkPrinter.remove_page(tab_nr)
        # clean Options Tab
        for widget in self.vbPOptions.get_children():
            self.vbPOptions.remove(widget)

        ppd = cups.PPD(self.cups.getPPD(name))
        ppd.markDefaults()
        self.ppd = ppd
        
        for group in ppd.optionGroups:
            if group.name == "InstallableOptions":
                container = self.vbPInstallOptions
                self.ntbkPrinter.insert_page(self.swPInstallOptions,
                                             gtk.Label(group.text), 1)
            else:
                frame = gtk.Frame (group.text)
                frame.set_shadow_type (gtk.SHADOW_NONE)
                self.vbPOptions.pack_start (frame, False, False, 0)
                container = gtk.Alignment (0.5, 0.5, 1.0, 1.0)
                container.set_padding (0, 0, 12, 0)
                frame.add (container)

            table = gtk.Table(1, 3, False)
            container.add(table)

            rows = 0
            for nr, option in enumerate(group.options):
                if option.keyword == "PageRegion":
                    continue
                rows += 1
                table.resize (rows, 3)
                o = OptionWidget(option, ppd, self)
                if o.label:
                    a = gtk.Alignment (0.5, 0.5, 1.0, 1.0)
                    a.set_padding (0, 0, 0, 6)
                    a.add (o.label)
                    table.attach(a, 0, 1, nr, nr+1, gtk.FILL, 0, 0, 0)
                    table.attach(o.selector, 1, 2, nr, nr+1, gtk.FILL, 0, 0, 0)
                else:
                    table.attach(o.selector, 0, 2, nr, nr+1, gtk.FILL, 0, 0, 0)
                table.attach(o.conflictIcon, 2, 3, nr, nr+1, gtk.FILL, 0, 0, 0)
                self.options[option.keyword] = o

        for option in self.options.itervalues():
            conflicts = option.checkConflicts()
            if conflicts:
                self.conflicts.add(option)

        self.swPInstallOptions.show_all()
        self.swPOptions.show_all()
        self.setDataButtonState()

    def getPrinterSettings(self):
        self.ppd.markDefaults()
        for option in self.options.itervalues():
            option.writeback()
        print self.ppd.conflicts(), "conflicts"

    def fillClassTab(self, name):
        pass

    def on_quit_activate(self, widget, event=None):
        # XXX check for unapplied changes
        gtk.main_quit()

    # Create/Delete
    
    def on_new_printer_activate(self, widget):
        self.initNewPrinterWindow()
        self.NewPrinterWindow.show()

    def on_new_class_activate(self, widget):
        print "NEW CLASS"
        
    def on_copy_activate(self, widget):
        name, type = self.getSelectedItem()
        if type == "Printer":
            self.initNewPrinterWindow(name)
            self.NewPrinterWindow.show()
        elif type == "Class":
            print "New Class"

    def on_delete_activate(self, widget):
        name, type = self.getSelectedItem()

        # Confirm
        dialog = gtk.MessageDialog(
            self.MainWindow,
            buttons=gtk.BUTTONS_OK_CANCEL,
            message_format="Really delete %s %s" % (type, name))
        result = dialog.run()
        dialog.destroy()

        if result == gtk.RESPONSE_CANCEL:
            return
        
        if type == "Printer":
            self.cups.deletePrinter(name)
            selection = self.tvMainList.get_selection()
            model, iter = selection.get_selected()
            model.remove(iter)
            selection.select_path(0)
            self.on_tvMainList_cursor_changed(self.tvMainList)
        elif type == "Class":
            print "DELETE Class"

    # == New Printer =====================================================

    def initNewPrinterWindow(self, prototype=None):
        self.ntbkNewPrinter.set_current_page(0)
        self.setNPButtons()
        self.fillPPDList()
        if prototype:
            pass
        else:
            pass
            #self.

    def on_NewPrinterWindow_delete_event(self, widget, event):
        self.NewPrinterWindow.hide()
        return True

    def on_btnNPBack_clicked(self, widget):
        self.ntbkNewPrinter.prev_page()
        self.setNPButtons()

    def on_btnNPForward_clicked(self, widget):
        print "XX"
        self.ntbkNewPrinter.next_page()
        self.setNPButtons()

    def setNPButtons(self):
        first_page = not self.ntbkNewPrinter.get_current_page()
        last_page = (self.ntbkNewPrinter.get_current_page() ==
                     len(self.ntbkNewPrinter.get_children()) -1 )        
        self.btnNPBack.set_sensitive(not first_page)
        self.btnNPForward.set_sensitive(not last_page)
        if last_page:
            self.btnNPApply.show()
        else:
            self.btnNPApply.hide()

    def on_entNPName_insert_at_cursor(self, widget, *args):        
        # restrict
        print "X", args

    def on_entNPName_insert_text(self, *args):
        print args

    # Device URI

    def fillDeviceTab(self):
        pass

    def on_cmbNPType_changed(self, widget):
        self.ntbkNPType.set_current_page(widget.get_active())

    def getDeviceURI(self):
        ptype = self.cmbNPType.get_active()
        if pytpe == 0: # Device
            device = self.entNPTDevice.get_text()
        elif ptype == 1: # DirectJet
            host = self.cmbNPTDirectJetHostname.get_text()
            port = self.cmbNPTDirectJetPort.get_text()
            device = "socket://" + host
            if port:
                device = device + ':' + port
        elif pytype == 2: # IPP
            host = self.cmbNPTIPPHostname.get_text()
            printer = self.cmbNPTIPPPrintername.get_text()
            device = "ipp://" + host
            if printer:
                device = device + "/" + printer
        elif ptype == 3: # LPD
            host = self.cmbNPTLPDHostname.get_text()
            printer = self.cmbNPLPDPrintername.get_text()
            device = "lpd://" + host
            if printer:
                device = device + "/" + printer
        elif ptype == 4: # Parallel
            device = "parallel:/dev/lp%d" % self.cmbNPTParallel.get_active()
        elif ptype == 5: # SCSII
            device = ""
        elif ptype == 6: # Serial
            options = []
            for widget, name, optionvalues in (
                (self.cmbNPTSerialBaud, "baud", None),
                (self.cmbNPTSerialBits, "bits", None),
                (self.cmbNPTSerialParity, "parity",
                 ("none", "odd", "even")),
                (self.cmbNPTSerialFlow, "flow",
                 ("none", "soft", "hard", "hard"))):
                nr = widget.get_active()
                if nr:
                    if options is not None:
                        option = optionvalues[nr-1]
                    else:
                        option = widget.get_active_text()
                    options.append(name + "=" + option)

            options = "+".join(options)
            device = "serial:/dev/ttyS%s" 
            if options:
                device = device + "?" + options
                
    # PPD

    def _fillPPDList(self, iter, treenode):
        if treenode.name:
            iter = self.tvNPDriversModel.append(iter, (treenode.name,))
        for leaf in treenode.leafs:
            self._fillPPDList(iter, leaf)

    def fillPPDList(self):
        self.foomatic.load_all() # XXX
        names = []
        for printername in self.foomatic.get_printers():
            printer = self.foomatic.get_printer(printername)
            names.append(printer.make + " " + printer.model)
        names.sort(cups.modelSort)
        tree = BuildTree(names, mindepth=3, minwidth=3)

        self._fillPPDList(None, tree)

    def on_tvNPDrivers_cursor_changed(self, widget):
        model, iter = widget.get_selection().get_selected()
        widget.collapse_all()
        path = model.get_path(iter)
        widget.expand_to_path(path)
        widget.get_selection().select_path(path)

        self.btnNPForward.set_sensitive(not model.iter_has_child(iter))

    # Create new Printer
    def on_btnNPApply_clicked(self, widget):
        name = self.entNPName.get_text()

        # XXX ppd = self.getNPPD()
        
        self.passwd_retry = False # use cached Passwd 
        try:
            self.cups.addPrinter(name, ppd=ppd)
        except cups.IPPError:
            # XXX
            pass

        printer = {
            "printer-location" : self.entNPLocation.get_text(),
            "printer-info" : self.entNPDescription.get_text(),
            "device-uri" : self.getDeviceURI(),
            }

        try:
            self.passwd_retry = False # use cached Passwd 
            self.cups.setPrinterInfo(name, new_values["printer-info"])
            self.passwd_retry = False # use cached Passwd 
            self.cups.setPrinterLocation(name,
                                         new_values["printer-location"])
            self.passwd_retry = False # use cached Passwd 
            self.cups.setPrinterDevice(name, new_values["device-uri"])
        except cups.IPPError:
            # XXX
            pass

        self.printers[name] = printer
        self.NewPrinterWindow.hide()

def main():
    # The default configuration requires root for administration.
    cups.setUser ("root")

    mainwindow = GUI()
    if gtk.__dict__.has_key("main"):
        gtk.main()
    else:
        gtk.mainloop()

if __name__ == "__main__":
    main()

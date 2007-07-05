#!/bin/env python

import gtk.glade, cups, cupshelpers
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
                        "btnNewPrinter", "btnNewClass", "btnCopy", "btnDelete",
                        "new_printer", "new_class", "copy", "delete",
                        "btnGotoServer",

                        "btnApply", "btnRevert", "imgConflict",

                        "ntbkPrinter",
                          "entPDescription", "entPLocation", "lblPMakeModel",
                          "lblPState", "entPDevice",                          
                         "swPInstallOptions", "vbPInstallOptions", 
                         "swPOptions",
                          "lblPOptions", "vbPOptions",
                         "vbClassMembers", "lblClassMembers",
                          "tvClassMembers", "tvClassNotMembers",
                          "btnClassAddMember", "btnClassDelMember",

                        "ConnectDialog", "chkEncrypted", "cmbServername",
                         "entUser",

                        "PasswordDialog", "lblPasswordPrompt", "entPasswd",

                        "ErrorDialog", "lblError",

                        "ApplyDialog",

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
        
        # setup PPD tree
        model = gtk.TreeStore(str)
        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn('States', cell, text=0)
        self.tvNPDrivers.set_model(model)
        self.tvNPDrivers.append_column(column)
        self.tvNPDriversModel = model

        self.tooltips = gtk.Tooltips()
        self.tooltips.enable()

        # setup Class member lists
        for name, treeview in (("Members", self.tvClassMembers),
                               ("Others", self.tvClassNotMembers)):
            model = gtk.ListStore(str)
            cell = gtk.CellRendererText()
            column = gtk.TreeViewColumn(name, cell, text=0)
            treeview.set_model(model)
            treeview.append_column(column)
        
        self.populateList()
        
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
        old_name, old_type = self.getSelectedItem()
        select_path = 0

        self.mainlist.clear()

        self.mainlist.append(("Server Settings", 'Settings'))

        # Printers
        self.printers = cupshelpers.getPrinters(self.cups)
        names = self.printers.keys()
        names.sort()

        self.mainlist.append(("Printers:", ''))

        for name in names:
            #if self.printers[name].remote
            #    continue
            if self.printers[name].is_class:
                continue
            iter = self.mainlist.append(('  ' + name, 'Printer'))
            if name == old_name:
                select_path = self.mainlist.get_path(iter)
        
        # Classes
        self.mainlist.append(("Classes:", ''))
        for name in names:
            if not self.printers[name].is_class: continue
            iter = self.mainlist.append((name, 'Class'))       
            if name == old_name:
                select_path = self.mainlist.get_path(iter)

        # Selection
        selection = self.tvMainList.get_selection()
        selection.select_path(select_path)

        self.on_tvMainList_cursor_changed(self.tvMainList)

    def maySelectItem(self, selection):
        result = self.mainlist.get_value(
            self.mainlist.get_iter(selection[0]), 1)
        return bool(result)

    def getSelectedItem(self):
        model, iter = self.tvMainList.get_selection().get_selected()
        if iter is None:
            return ("Server Settings", 'Settings')
        name, type = model.get_value(iter, 0), model.get_value(iter, 1)
        return name.strip(), type

    # Connect to Server

    def on_connect_activate(self, widget):
        # check for unapplied changes
        if self.changed:
            response = self.ApplyDialog.run()
            self.ApplyDialog.hide()
            err = False
            if response == gtk.RESPONSE_APPLY:
                err = self.apply()
            if err or response == gtk.RESPONSE_CANCEL:
                return

        # Use browsed queues to build up a list of known IPP servers
        known_servers = set(('localhost',))
        for name in self.printers:
            printer = self.printers[name]
            known_servers.add(printer.getServer())
        known_servers.discard(None)
        known_servers = list(known_servers)
        known_servers.sort

        store = gtk.ListStore (gobject.TYPE_STRING)
        self.cmbServername.set_model (store)
        for server in known_servers:
            self.cmbServername.append_text (server)
        self.cmbServername.show ()

        self.cmbServername.child.set_text (cups.getServer ())
        self.entUser.set_text (cups.getUser ())
        self.chkEncrypted.set_active (cups.getEncryption () ==
                                      cups.HTTP_ENCRYPT_ALWAYS)

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

    def on_btnGotoServer_clicked(self, button):
        cups.setServer(self.printer.getServer())
        try:
            connection = cups.Connection() # XXX timeout?
            self.setTitle()
        except:
            connection = None

        if not connection: # error handling
            # XXX more Error handling
            return

        self.cups = connection
        self.populateList()
        

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

    # Handle unapplied changes (dialog)

    def on_btnApplyApply_clicked(self, button):
        self.ApplyDialog.response(gtk.RESPONSE_APPLY)

    def on_btnApplyCancel_clicked(self, button):
        self.ApplyDialog.response(gtk.RESPONSE_CANCEL)

    def on_btnApplyDiscard_clicked(self, button):
        self.ApplyDialog.response(gtk.RESPONSE_REJECT)

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
            

    # Apply Changes
    
    def on_btnApply_clicked(self, widget):
        err = self.apply()
        if not err:
            self.populateList()
        else:
            pass # XXX
        
    def apply(self):
        name, type = self.getSelectedItem()
        if type in ("Printer", "Class"):
            return self.save_printer(name)
        elif type == "Settings":
            print "Apply Settings"
        
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
        printer = self.printers[name] 
        
        try:
            if not printer.is_class: 
                self.getPrinterSettings()
                if True: #self.ppd.nondefaultsMarked():
                    self.passwd_retry = False # use cached Passwd 
                    self.cups.addPrinter(name, ppd=self.ppd)
                else:
                    print "no PPD changes found"
            location = self.entPLocation.get_text()
            info = self.entPDescription.get_text()
            device_uri = self.entPDevice.get_text()

            if info!=printer.info:
                self.passwd_retry = False # use cached Passwd 
                self.cups.setPrinterInfo(name, info)
            if location!=printer.location:
                self.passwd_retry = False # use cached Passwd 
                self.cups.setPrinterLocation(name, location)
            if device_uri!=printer.device_uri:
                self.passwd_retry = False # use cached Passwd 
                self.cups.setPrinterDevice(name, device_uri)

            if printer.is_class:
                # update member list
                new_members = self.getCurrentClassMembers()
                for member in printer.class_members:
                    if member in new_members:
                        new_members.remove(member)
                    else:
                        self.cups.deletePrinterFromClass(member, name)
                for member in new_members:
                    self.cups.addPrinterToClass(member, name)                
        except cups.IPPError, (e, s):
            self.show_IPP_Error(e, s)
            return True
        self.changed = set() # of options
        return False

    def getPrinterSettings(self):
        #self.ppd.markDefaults()
        for option in self.options.itervalues():
            option.writeback()
        print self.ppd.conflicts(), "conflicts"

    # revert changes

    def on_btnRevert_clicked(self, button):
        self.changed = set() # avoid asking the user
        self.on_tvMainList_cursor_changed(self.tvMainList)

    # select Item

    def on_tvMainList_cursor_changed(self, list):
        if self.changed:
            response = self.ApplyDialog.run()
            self.ApplyDialog.hide()
            err = False
            if response == gtk.RESPONSE_APPLY:
                err = self.apply()
            if err or response == gtk.RESPONSE_CANCEL:
                self.tvMainList.get_selection().select_iter(
                    self.mainListSelected)
                return

        name, type = self.getSelectedItem()
        model, self.mainListSelected = self.tvMainList.get_selection().get_selected()
        item_selected = True
        if type == "Settings":
            self.ntbkMain.set_current_page(0)
            self.fillServerTab()
            item_selected = False
        elif type in ['Printer', 'Class']:
            self.fillPrinterTab(name)
            self.ntbkMain.set_current_page(1)

        for widget in [self.copy, self.delete, self.btnCopy, self.btnDelete]:
            widget.set_sensitive(item_selected)


    def fillServerTab(self):
        self.changed = set()
        self.btnGotoServer.set_sensitive(False)

    def fillPrinterTab(self, name):
        self.changed = set() # of options
        self.options = {} # keyword -> Option object
        self.conflicts = set() # of options

        printer = self.printers[name] 
        self.printer = printer

        editable = not self.printer.remote

        self.btnGotoServer.set_sensitive(bool(printer.getServer()))

        # Description page        
        self.entPDescription.set_text(printer.info)
        self.entPDescription.set_sensitive(editable)
        self.entPLocation.set_text(printer.location)
        self.entPLocation.set_sensitive(editable)
        self.lblPMakeModel.set_text(printer.make_and_model)
        self.lblPState.set_text(printer.state_description)

        self.entPDevice.set_text(printer.device_uri)
        self.entPDevice.set_sensitive(editable)

        # remove InstallOptions tab
        tab_nr = self.ntbkPrinter.page_num(self.swPInstallOptions)
        if tab_nr != -1:
            self.ntbkPrinter.remove_page(tab_nr)

        if printer.is_class:
            # Class
            self.fillClassMembers(name, editable)
        else:
            # real Printer
            self.fillPrinterOptions(name, editable)

        self.setDataButtonState()

    def fillPrinterOptions(self, name, editable):
        # remove Class membership tab
        tab_nr = self.ntbkPrinter.page_num(self.vbClassMembers)
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
                self.swPOptions, self.lblPOptions, 2)

        # get PPD
        ppd = cups.PPD(self.cups.getPPD(name))
        ppd.markDefaults()
        self.ppd = ppd

        # build option tabs
        for group in ppd.optionGroups:
            if group.name == "InstallableOptions":
                container = self.vbPInstallOptions
                self.ntbkPrinter.insert_page(self.swPInstallOptions,
                                             gtk.Label(group.text), 2)
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
                o.selector.set_sensitive(editable)

        for option in self.options.itervalues():
            conflicts = option.checkConflicts()
            if conflicts:
                self.conflicts.add(option)

        self.swPInstallOptions.show_all()
        self.swPOptions.show_all()

    # Class members
    
    def fillClassMembers(self, name, editable):
        printer = self.printers[name]

        self.btnClassAddMember.set_sensitive(editable)
        self.btnClassDelMember.set_sensitive(editable)

        # remove Options tab
        tab_nr = self.ntbkPrinter.page_num(self.swPOptions)
        if tab_nr != -1:
            self.ntbkPrinter.remove_page(tab_nr)

        # insert Member Tab
        if self.ntbkPrinter.page_num(self.vbClassMembers) == -1:
            self.ntbkPrinter.insert_page(
                self.vbClassMembers, self.lblClassMembers, 2)
        

        model_members = self.tvClassMembers.get_model()
        model_not_members = self.tvClassNotMembers.get_model()
        model_members.clear()
        model_not_members.clear()

        for name, p in self.printers.iteritems():
            if (not p.is_class and
                p is not printer and
                not p.remote):
                if name in printer.class_members:
                    model_members.append((name, ))
                else:
                    model_not_members.append((name, ))
                
    def on_btnClassAddMember_clicked(self, button):
        self.moveClassMembers(self.tvClassNotMembers,
                              self.tvClassMembers)
        
    def on_btnClassDelMember_clicked(self, button):
        self.moveClassMembers(self.tvClassMembers,
                              self.tvClassNotMembers)
        
    def moveClassMembers(self, treeview_from, treeview_to):
        selection = treeview_from.get_selection()
        model_from, rows = selection.get_selected_rows()
        rows = [gtk.TreeRowReference(model_from, row) for row in rows]

        model_to = treeview_to.get_model()
        
        for row in rows:
            path = row.get_path()
            iter = model_from.get_iter(path)
            
            row_data = model_from.get(iter, 0)
            model_to.append(row_data)
            model_from.remove(iter)

        if self.getCurrentClassMembers() != self.printer.class_members:
            self.changed.add(self.tvClassMembers)
        else:
            self.changed.discard(self.tvClassMembers)
        self.setDataButtonState()

    def getCurrentClassMembers(self):
        model = self.tvClassMembers.get_model()
        iter = model.get_iter_root()
        result = []
        while iter:
            result.append(model.get(iter, 0)[0])
            iter = model.iter_next(iter)
        result.sort()
        return result

    # Quit
    
    def on_quit_activate(self, widget, event=None):
        # check for unapplied changes
        if self.changed:
            response = self.ApplyDialog.run()
            self.ApplyDialog.hide()
            err = False
            if response == gtk.RESPONSE_APPLY:
                err = self.apply()
            if err or response == gtk.RESPONSE_CANCEL:
                return
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
        
        self.cups.deletePrinter(name)
        selection = self.tvMainList.get_selection()
        model, iter = selection.get_selected()
        model.remove(iter)
        selection.select_path(0)
        self.on_tvMainList_cursor_changed(self.tvMainList)

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

        location = self.entNPLocation.get_text(),
        info = self.entNPDescription.get_text(),
        uri = self.getDeviceURI(),

        try:
            self.passwd_retry = False # use cached Passwd 
            self.cups.setPrinterInfo(name, info)
            self.passwd_retry = False # use cached Passwd 
            self.cups.setPrinterLocation(name,
                                         location)
            self.passwd_retry = False # use cached Passwd 
            self.cups.setPrinterDevice(name, device_uri)
        except cups.IPPError:
            # XXX
            pass

        #self.printers[name] = printer
        self.NewPrinterWindow.hide()
        # XXX reread printerlist

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

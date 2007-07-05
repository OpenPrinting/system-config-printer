#!/bin/env python

import gtk.glade, cups, cupshelpers
import gobject # for TYPE_STRING
from optionwidgets import OptionWidget
from foomatic import Foomatic
from nametree import BuildTree
import probe_printer

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

        self.servers = set(("localhost",))

        self.cups = cups.Connection()
        # XXX Error handling
        
        self.foomatic = Foomatic() # this works on the local db


        # WIDGETS
        # =======
        self.xml = gtk.glade.XML("system-config-printer.glade")
        self.getWidgets("MainWindow", "tvMainList", "ntbkMain",
                        "btnNewPrinter", "btnNewClass", "btnCopy", "btnDelete",
                        "new_printer", "new_class", "copy", "delete",
                        "cmbServers", "btnGotoServer",

                        "btnApply", "btnRevert", "imgConflict",

                        "ntbkPrinter",
                          "entPDescription", "entPLocation", "lblPMakeModel",
                          "lblPState", "entPDevice",
                          "chkPEnabled", "chkPAccepting", "chkPShared",
                          "btnPMakeDefault", "lblPDefault",
                         
                          "cmbPStartBanner", "cmbPEndBanner",
                          "cmbPErrorPolicy", "cmbPOperationPolicy",
                          "cmbPExplicitAllow", "entPExceptUsers",
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
                           "cmbNPTSerialBaud", "cmbNPTSerialParity",
                            "cmbNPTSerialBits", "cmbNPTSerialFlow",
                           "cmbentNPTLpdHost", "cmbentNPTLpdQueue",
                           "entNPTDevice",
                           "tvNCMembers",
                          "tvNPModels", "cmbNPDriver",
                           "txtNPModelDescription", "txtNPDriverDescription",
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
        self.mainlist = gtk.TreeStore(str, str)
        
        self.tvMainList.set_model(self.mainlist)
        column.set_attributes(cell, text=0)
        selection = self.tvMainList.get_selection()
        selection.set_mode(gtk.SELECTION_BROWSE)
        selection.set_select_function(self.maySelectItem)

        self.mainlist.append(None, ("Server Settings", 'Settings'))
        self.mainlist.append(None, ("Local Printers", ""))
        self.mainlist.append(None, ("Local Classes", ""))
        self.mainlist.append(None, ("Remote Printers", ""))
        self.mainlist.append(None, ("Remote Classes", ""))

        # setup PPD tree
        model = gtk.TreeStore(str, str)
        cell = gtk.CellRendererText()
        column = gtk.TreeViewColumn('States', cell, text=0)
        self.tvNPModels.set_model(model)
        self.tvNPModels.append_column(column)
        self.tvNPModelsModel = model

        self.tooltips = gtk.Tooltips()
        self.tooltips.enable()

        # setup Class member lists
        for name, treeview in (("Members", self.tvClassMembers),
                               ("Others", self.tvClassNotMembers),
                               ("Select Members", self.tvNCMembers)):
            model = gtk.ListStore(str)
            cell = gtk.CellRendererText()
            column = gtk.TreeViewColumn(name, cell, text=0)
            treeview.set_model(model)
            treeview.append_column(column)
            treeview.get_selection().set_mode(gtk.SELECTION_MULTIPLE)
        
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

    def getServers(self):
        self.servers.discard(None)
        known_servers = list(self.servers)
        known_servers.sort()
        return known_servers

    def setCmbServers(self, server):
        model = self.cmbServers.get_model()
        pos = model.get_iter_first()
        nr = 0
        while True:
            s = model.get(pos, 0)[0]
            if s==server:
                self.cmbServers.set_active(nr)
            pos = model.iter_next(pos)
            nr += 1
            if pos is None: break

    def populateList(self):
        old_name, old_type = self.getSelectedItem()

        select_path = (0, )

        #self.mainlist.clear()

        # get Printers
        self.printers = cupshelpers.getPrinters(self.cups)
        
        self.default_printer = ""

        local_printers = []
        local_classes = []
        remote_printers = []
        remote_classes = []

        for name, printer in self.printers.iteritems():
            if printer.default:
                self.default_printer = name
            self.servers.add(printer.getServer())

            if printer.remote:
                if printer.is_class: remote_classes.append(name)
                else: remote_printers.append(name)
            else:
                if printer.is_class: local_classes.append(name)
                else: local_printers.append(name)

        local_printers.sort()
        local_classes.sort()
        remote_printers.sort()
        remote_classes.sort()

        iter = self.mainlist.get_iter_first()
        iter = self.mainlist.iter_next(iter)
        for printers in (local_printers, local_classes,
                         remote_printers, remote_classes):
            path = self.mainlist.get_path(iter)
            expanded = (self.tvMainList.row_expanded(path) or
                        not self.mainlist.iter_has_child(iter))

            # clear old entries
            while self.mainlist.iter_has_child(iter):
                self.mainlist.remove(self.mainlist.iter_children(iter))
            # add new ones
            for printer_name in printers:
                p_iter = self.mainlist.append(iter, (printer_name, "Printer"))
                if printer_name==old_name:
                    select_path = self.mainlist.get_path(p_iter)
            if expanded:
                self.tvMainList.expand_row(path, False)
            iter = self.mainlist.iter_next(iter)
                
        # server combobox
        model = self.cmbServers.get_model()
        model.clear()
        current_server = cups.getServer()
        select_row = 0
        for nr, server in enumerate(self.getServers()):
            if current_server == server:
                select_row = nr
            model.append((server,))
        self.cmbServers.set_active(select_row)
        
        # Selection
        selection = self.tvMainList.get_selection()
        selection.select_path(select_path)

        self.on_tvMainList_cursor_changed(self.tvMainList)

    def maySelectItem(self, selection):
        result = self.mainlist.get_value(
            self.mainlist.get_iter(selection), 1)
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
        servers = self.getServers()

        store = gtk.ListStore (gobject.TYPE_STRING)
        self.cmbServername.set_model (store)
        for server in servers:
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
        cups.setServer(self.cmbServers.get_active_text())
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

    def on_printer_changed(self, widget):
        if isinstance(widget, gtk.CheckButton):
            value = widget.get_active()
        elif isinstance(widget, gtk.Entry):
            value = widget.get_text()
        elif widget is self.cmbPExplicitAllow:
            value = widget.get_active()
        elif isinstance(widget, gtk.ComboBox):
            value = widget.get_active_text()
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
            self.cmbPExplicitAllow: p.default_allow,
            }
        
        old_value = old_values[widget]
        
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

    def on_tbtnPAllow_changed(self, widget):
        active = widget.get_active()
        if active:
            widget.set_label(_("Allow"))
            widget.set_image(gtk.image_new_from_icon_name("gtk-yes", 1))
        else:
            widget.set_label(_("Deny"))
            widget.set_image(gtk.image_new_from_icon_name("gtk-no", 1))
        
        if not(active ^ self.printer.default_allow):
            self.changed.discard(widget)
        else:
            self.changed.add(widget)
        self.setDataButtonState()

    def on_entPExceptUsers_changed(self, widget):
        if widget.get_text() == self.printer.except_users_string:
            self.changed.discard(widget)
        else:
            self.changed.add(widget)
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
                if self.ppd.nondefaultsMarked():
                    self.passwd_retry = False # use cached Passwd 
                    self.cups.addPrinter(name, ppd=self.ppd)

            if printer.is_class:
                # update member list
                new_members = self.getCurrentClassMembers()
                if not new_members:
                    dialog = gtk.MessageDialog(
                        flags=0, type=gtk.MESSAGE_WARNING,
                        buttons=gtk.BUTTONS_YES_NO,
                        message_format="This will delete this Class!")
                    dialog.format_secondary_text("Proceed anyway?")
                    result = dialog.run()
                    dialog.destroy()
                    if result==gtk.RESPONSE_NO:
                        return True

            location = self.entPLocation.get_text()
            info = self.entPDescription.get_text()
            device_uri = self.entPDevice.get_text()

            enabled = self.chkPEnabled.get_active()
            accepting = self.chkPAccepting.get_active()
            shared = self.chkPShared.get_active()

            if info!=printer.info:
                self.passwd_retry = False # use cached Passwd 
                self.cups.setPrinterInfo(name, info)
            if location!=printer.location:
                self.passwd_retry = False # use cached Passwd 
                self.cups.setPrinterLocation(name, location)
            if device_uri!=printer.device_uri:
                self.passwd_retry = False # use cached Passwd 
                self.cups.setPrinterDevice(name, device_uri)

            if enabled != printer.enabled:
                self.passwd_retry = False # use cached Passwd 
                self.printer.setEnabled(enabled)
            if accepting == printer.rejecting:
                self.passwd_retry = False # use cached Passwd 
                self.printer.setAccepting(accepting)
            if shared != printer.is_shared:
                self.passwd_retry = False # use cached Passwd 
                self.printer.setShared(shared)
                
            job_sheet_start = self.cmbPStartBanner.get_active_text()
            job_sheet_end = self.cmbPEndBanner.get_active_text()
            error_policy = self.cmbPErrorPolicy.get_active_text()
            op_policy = self.cmbPOperationPolicy.get_active_text()

            if (job_sheet_start != printer.job_sheet_start or
                job_sheet_end != printer.job_sheet_end):
                self.passwd_retry = False # use cached Passwd
                printer.setJobSheets(job_sheet_start, job_sheet_end)
            if error_policy != printer.error_policy:
                self.passwd_retry = False # use cached Passwd
                printer.setErrorPolicy(error_policy)
            if op_policy != printer.op_policy:
                self.passwd_retry = False # use cached Passwd
                printer.setOperationPolicy(op_policy)

            default_allow = self.cmbPExplicitAllow.get_active()
            except_users = self.entPExceptUsers.get_text()

            if (default_allow != printer.default_allow or
                except_users != printer.except_users_string):
                self.passwd_retry = False # use cached Passwd
                printer.setAccess(default_allow, except_users)

            if printer.is_class:
                # update member list
                old_members = printer.class_members[:]
                
                for member in new_members:
                    if member in old_members:
                        old_members.remove(member)
                    else:
                        self.cups.addPrinterToClass(member, name)
                for member in old_members:
                    self.cups.deletePrinterFromClass(member, name)
                    
        except cups.IPPError, (e, s):
            self.show_IPP_Error(e, s)
            return True
        self.changed = set() # of options
        return False

    def getPrinterSettings(self):
        #self.ppd.markDefaults()
        for option in self.options.itervalues():
            option.writeback()

    # revert changes

    def on_btnRevert_clicked(self, button):
        self.changed = set() # avoid asking the user
        self.on_tvMainList_cursor_changed(self.tvMainList)

    # set default printer
    
    def on_btnPMakeDefault_pressed(self, button):
        self.cups.setDefault(self.printer.name)
        self.populateList()

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
        self.setCmbServers(cups.getServer())

    def fillComboBox(self, combobox, values, value):
        combobox.get_model().clear()
        for nr, val in enumerate(values):
            combobox.append_text(val)
            if val == value: combobox.set_active(nr)

    def fillPrinterTab(self, name):
        self.changed = set() # of options
        self.options = {} # keyword -> Option object
        self.conflicts = set() # of options

        printer = self.printers[name] 
        self.printer = printer

        editable = True#not self.printer.remote

        self.setCmbServers(printer.getServer())

        # Description page        
        self.entPDescription.set_text(printer.info)
        self.entPDescription.set_sensitive(editable)
        self.entPLocation.set_text(printer.location)
        self.entPLocation.set_sensitive(editable)
        self.lblPMakeModel.set_text(printer.make_and_model)
        self.lblPState.set_text(printer.state_description)

        self.entPDevice.set_text(printer.device_uri)
        self.entPDevice.set_sensitive(editable)

        self.chkPEnabled.set_active(printer.enabled)
        self.chkPEnabled.set_sensitive(editable)
        self.chkPAccepting.set_active(not printer.rejecting)
        self.chkPAccepting.set_sensitive(editable)
        self.chkPShared.set_active(printer.is_shared)
        self.chkPShared.set_sensitive(editable)

        # default printer
        self.btnPMakeDefault.set_sensitive(not printer.default)
        if printer.default:
            self.lblPDefault.set_text(_("This is the default printer"))
        elif self.default_printer:
            self.lblPDefault.set_text(_("Default printer is %s") %
                                      self.default_printer)
        else:
            self.lblPDefault.set_text(_("No default printer set."))

        # Policy tab
        # ----------
        # Job sheets
        self.fillComboBox(self.cmbPStartBanner, printer.job_sheets_supported,
                          printer.job_sheet_start),
        self.fillComboBox(self.cmbPEndBanner, printer.job_sheets_supported,
                          printer.job_sheet_end)

        # Policies
        self.fillComboBox(self.cmbPErrorPolicy, printer.error_policy_supported,
                          printer.error_policy)
        self.fillComboBox(self.cmbPOperationPolicy,
                          printer.op_policy_supported,
                          printer.op_policy)

        # Access control
        self.cmbPExplicitAllow.set_active(printer.default_allow)
        self.entPExceptUsers.set_text(printer.except_users_string)

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
                frame = gtk.Frame("<b>%s</b>" % group.text)
                frame.get_label_widget().set_use_markup(True)
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
                table.attach(o.conflictIcon, 0, 1, nr, nr+1, 0, 0, 0, 0)

                hbox = gtk.HBox()
                if o.label:
                    a = gtk.Alignment (0.5, 0.5, 1.0, 1.0)
                    a.set_padding (0, 0, 0, 6)
                    a.add (o.label)
                    table.attach(a, 1, 2, nr, nr+1, gtk.FILL, 0, 0, 0)
                    table.attach(hbox, 2, 3, nr, nr+1, gtk.FILL, 0, 0, 0)
                else:
                    table.attach(hbox, 1, 3, nr, nr+1, gtk.FILL, 0, 0, 0)
                hbox.pack_start(o.selector, False)
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

        names = self.printers.keys()
        names.sort()
        for name in names:
            p = self.printers[name]
            if p is not printer:
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
        self.new_class = False
        self.initNewPrinterWindow()
        self.NewPrinterWindow.show()

    def on_new_class_activate(self, widget):
        self.new_class = True
        self.initNewPrinterWindow()
        self.NewPrinterWindow.show()
        
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
        self.populateList()
        #selection = self.tvMainList.get_selection()
        #model, iter = selection.get_selected()
        #model.remove(iter)
        #selection.select_path(0)
        #self.on_tvMainList_cursor_changed(self.tvMainList)

    # == New Printer =====================================================

    new_printer_device_tabs = {
        "parallel" : 0, # empty tab
        "usb" : 0,
        "hal" : 0,
        "beh" : 0,
        "hp" : 0,
        "socket": 2,
        "ipp" : 3,
        "http" : 3,
        "lpd" : 4,
        "scsi" : 5,
        "serial" : 6,
        "smb" : 1,
        }

    def initNewPrinterWindow(self, prototype=None):
        self.ntbkNewPrinter.set_current_page(0)
        self.setNPButtons()
        if self.new_class:
            self.fillNewClassMembers()
        else:
            self.fillDeviceTab()
        if prototype:
            pass
        else:
            pass
            #self.

    def fillDeviceTab(self):
        devices = cupshelpers.getDevices(self.cups).values()
        devices.sort()
        self.devices = filter(lambda x: x.uri not in ("hp:/no_device_found",
                                                      "hal", "beh",
                                                      "scsi", "http"),
                              devices) 

        model = self.cmbNPType.get_model()
        model.clear()

        for device in self.devices:
            model.append((device.info,))

        self.cmbNPType.set_active(0)

    def fillNewClassMembers(self):
        model = self.tvNCMembers.get_model()
        model.clear()
        for printer in self.printers.itervalues():
            model.append((printer.name,))

    def on_NPCancel(self, widget, event=None):
        self.NewPrinterWindow.hide()
        return True

    def on_btnNPBack_clicked(self, widget):
        self.nextNPTab(-1)

    def on_btnNPForward_clicked(self, widget):
        self.nextNPTab()

    def nextNPTab(self, step=1):
        page_nr = self.ntbkNewPrinter.get_current_page()
        if self.new_class:
            order = [0, 3, 4]
        else:
            order = [0, 1, 2, 4]
        page_nr = self.ntbkNewPrinter.set_current_page(
            order[order.index(page_nr)+step])
        self.setNPButtons()

    def setNPButtons(self):
        page_nr = self.ntbkNewPrinter.get_current_page()
        first_page = not page_nr
        last_page = (page_nr ==
                     len(self.ntbkNewPrinter.get_children()) -1 )        
        if first_page:
            self.btnNPBack.hide()
            self.btnNPForward.set_sensitive(
                self.check_NPName(self.entNPName.get_text()))
        else:
            self.btnNPBack.show()
        if last_page:
            self.btnNPForward.hide()
            self.btnNPApply.show()
        else:
            self.btnNPForward.show()
            self.btnNPApply.hide()

        if page_nr == 2: self.fillPPDList()
            
    def check_NPName(self, name):
        if not name: return False
        name = name.lower()
        for printer in self.printers.values():
            if not printer.remote and printer.name.lower()==name:
                return False
        return True
    
    def on_entNPName_changed(self, widget):
        # restrict
        text = widget.get_text()
        new_text = text
        new_text = new_text.replace("/", "")
        new_text = new_text.replace("#", "")
        new_text = new_text.replace(" ", "")
        if text!=new_text:
            widget.set_text(new_text)
        self.btnNPForward.set_sensitive(
            self.check_NPName(new_text))

    # Device URI

    def on_cmbNPType_changed(self, widget):
        device = self.devices[widget.get_active()]
        self.device = device
        self.ntbkNPType.set_current_page(
            self.new_printer_device_tabs.get(device.type, 0))

        type = device.type
        if device.type=="serial":
            if not device.is_class:
                options = device.uri.split("?")[1]
                options = options.split("+")
                option_dict = {}
                for option in options:
                    name, value = option.split("=")
                    option_dict[name] = value
                    
                for widget, name, optionvalues in (
                    (self.cmbNPTSerialBaud, "baud", None),
                    (self.cmbNPTSerialBits, "bits", None),
                    (self.cmbNPTSerialParity, "parity",
                     ("none", "odd", "even")),
                    (self.cmbNPTSerialFlow, "flow",
                     ("none", "soft", "hard", "hard"))):
                    if option_dict.has_key(name): # option given in URI?
                        if optionvalues is None: # use text in widget
                            model = widget.get_model()
                            iter = model.get_iter_first()
                            nr = 0
                            while iter:
                                value = model.get(iter,0)[0]
                                if value == option_dict[name]:
                                    widget.set_active(nr)
                                    break
                                iter = model.iter_next(iter)
                                nr += 1
                        else: # use optionvalues
                            nr = optionvalues.index(
                                option_dict[name])
                            widget.set_active(nr+1) # compensate "Default"
                    else:
                        widget.set_active(0)
                                            
        elif device.type in ("ipp", "http"):
            pass
        elif device.type=="":
            pass
        elif device.type=="":
            pass

    def on_btnNPTLpdProbe_pressed(self, button):
        # read hostname, probe, fill printer names
        hostname = self.cmbentNPTLpdHost.get_active_text()
        server = probe_printer.LpdServer(hostname)
        printers = server.probe()
        model = self.cmbentNPTLpdQueue.get_model()
        model.clear()
        for printer in printers:
            self.cmbentNPTLpdQueue.append_text(printer)
        if printers:
            self.cmbentNPTLpdQueue.set_active(0)
        
    def getDeviceURI(self):
        type = self.device.type
        if type == "socket": # DirectJet
            host = self.cmbNPTDirectJetHostname.get_text()
            port = self.cmbNPTDirectJetPort.get_text()
            device = "socket://" + host
            if port:
                device = device + ':' + port
        elif type in ("http", "ipp"): # IPP
            host = self.cmbNPTIPPHostname.get_text()
            printer = self.cmbNPTIPPPrintername.get_text()
            device = "ipp://" + host
            if printer:
                device = device + "/" + printer
        elif type == "lpd": # LPD
            host = self.cmbNPTLPDHostname.get_text()
            printer = self.cmbNPLPDPrintername.get_text()
            device = "lpd://" + host
            if printer:
                device = device + "/" + printer
        elif type == "parallel": # Parallel
            device = self.device.uri
        elif type == "scsi": # SCSII
            device = ""
        elif type == "serial": # Serial
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
                    if optionvalues is not None:
                        option = optionvalues[nr-1]
                    else:
                        option = widget.get_active_text()
                    options.append(name + "=" + option)
            options = "+".join(options)
            device =  self.device.uri.split("?")[0] #"serial:/dev/ttyS%s" 
            if options:
                device = device + "?" + options                
        else:
            device = self.entNPTDevice.get_text()
        return device
    
    # PPD

    #def _fillPPDList(self, iter, treenode):
    #    if treenode.name:
    #        iter = self.tvNPDriversModel.append(iter, (treenode.name,))
    #    for leaf in treenode.leafs:
    #        self._fillPPDList(iter, leaf)

    def fillPPDList(self):
        if self.device.id:
            # try to find the right PPDs
            pass

        makes = self.foomatic.getMakes()
        for make in makes:
            printers = self.foomatic.getModelsNames(make)
            if not printers: continue
            
            iter = self.tvNPModelsModel.append(None, (make, ''))
            for model_name in printers:
                self.tvNPModelsModel.append(iter, model_name)

            #tree = BuildTree(names, 3, 3)
            #tree.name = maker
            #self._fillPPDList(None, tree)
            
            
        #names = []
        #for printername in self.foomatic.get_printers():
        #    printer = self.foomatic.get_printer(printername)
        #    names.append(printer.make + " " + printer.model)
        #names.sort(cups.modelSort)
        #tree = BuildTree(names, mindepth=3, minwidth=3)

        #self._fillPPDList(None, tree)

    def on_tvNPModels_cursor_changed(self, widget):
        model, iter = widget.get_selection().get_selected()
        #widget.collapse_all()
        path = model.get_path(iter)
        #widget.expand_to_path(path)
        #widget.get_selection().select_path(path)

        #self.btnNPForward.set_sensitive(not model.iter_has_child(iter))
        if not model.iter_has_child(iter):
            name = model.get(iter, 1)[0]
            printer = self.foomatic.getPrinter(name)
            self.txtNPModelDescription.get_buffer().set_text(
                printer.comments_dict.get("en", ""))

            model = self.cmbNPDriver.get_model()
            model.clear()
            for nr, driver in enumerate(printer.drivers):
                self.cmbNPDriver.append_text(driver)
                if driver==printer.driver:
                    self.cmbNPDriver.set_active(nr)

    def on_cmbNPDriver_changed(self, widget):
        driver = self.foomatic.getDriver(widget.get_active_text())
        self.txtNPDriverDescription.get_buffer().set_text(
            driver.comments_dict.get("en", ""))

    def getNPPPD(self):
        model, iter = self.tvNPModels.get_selection().get_selected()
        printer_name = model.get(iter, 1)[0]
        printer = self.foomatic.getPrinter(printer_name)
        driver_name = self.cmbNPDriver.get_active_text()
        return self.foomatic.getPPDFilename(printer, driver_name)

    # Create new Printer
    def on_btnNPApply_clicked(self, widget):
        name = self.entNPName.get_text()
        location = self.entNPLocation.get_text()
        info = self.entNPDescription.get_text()

        if self.new_class:
            members = []
            model, paths = self.tvNCMembers.get_selection().get_selected_rows()
            for path in paths:
                iter = model.get_iter(path)
                members.append(model.get(iter, 0)[0])
            try:
                for member in members:
                    self.passwd_retry = False # use cached Passwd 
                    print member, name
                    self.cups.addPrinterToClass(member, name)
                print location
                self.passwd_retry = False # use cached Passwd 
                self.cups.setPrinterLocation(name, location)
                print info
                self.passwd_retry = False # use cached Passwd 
                self.cups.setPrinterInfo(name, info)
            except cups.IPPError, e:
                # XXX
                print e
                pass
        else:
            uri = self.getDeviceURI()
            ppd = self.getNPPPD()
        
            try:
                self.passwd_retry = False # use cached Passwd 
                self.cups.addPrinter(name, filename=ppd,
                                     device=uri, info=info, location=location)
            except cups.IPPError:
                # XXX
                pass

        #self.printers[name] = printer
        self.NewPrinterWindow.hide()
        self.populateList()

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

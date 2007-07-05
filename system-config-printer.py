#!/bin/env python

import sys, os, tempfile, time
import signal, thread
try:
    import gtk.glade
except RuntimeError, e:
    print "system-config-printer:", e
    print "This is a graphical application and requires DISPLAY to be set."
    sys.exit (1)

if len(sys.argv)>1 and sys.argv[1] == '--help':
    print ("\nThis is system-config-printer, " \
           "a CUPS server configuration program.\n")
    sys.exit (0)

import cups, cupshelpers, options
import gobject # for TYPE_STRING
from optionwidgets import OptionWidget
from foomatic import Foomatic
from nametree import BuildTree
from cupsd import CupsConfig
import probe_printer
import gtk_label_autowrap


domain='system-config-printer'
import locale
locale.setlocale (locale.LC_ALL, "")
from rhpl.translate import _, N_
import rhpl.translate as translate
translate.textdomain (domain)
gtk.glade.bindtextdomain (domain)
pkgdata = '/usr/share/' + domain
glade_file = pkgdata + '/' + domain + '.glade'
sys.path.append (pkgdata)

class GUI:

    def __init__(self):

        self.language = locale.getlocale(locale.LC_MESSAGES)
        self.encoding = locale.getlocale(locale.LC_CTYPE)
        
        self.printer = None
        self.conflicts = set() # of options
        self.password = ''
        self.passwd_retry = False
        cups.setPasswordCB(self.cupsPasswdCallback)        

        self.changed = set() # of options

        self.servers = set(("localhost",))

        try:
            self.cups = cups.Connection()
        except RuntimeError:
            self.cups = None

        # WIDGETS
        # =======
        try:
            #raise ValueError # uncomment for development
            self.xml = gtk.glade.XML(glade_file)
        except:
            self.xml = gtk.glade.XML(domain + '.glade')

        self.getWidgets("MainWindow", "tvMainList", "ntbkMain",
                        "statusbarMain",
                        "btnNewPrinter", "btnNewClass", "btnCopy", "btnDelete",
                        "new_printer", "new_class", "copy", "delete",
                        "btnGotoServer",

                        "btnApply", "btnRevert", "btnConflict",

                        "chkServerBrowse", "chkServerShare",
                        "chkServerRemoteAdmin", "chkServerAllowCancelAll",
                        "chkServerLogDebug",

                        "ntbkPrinter",
                         "entPDescription", "entPLocation",
                          "lblPMakeModel", "lblPMakeModel2",
                          "lblPState", "entPDevice", "lblPDevice2",
                          "btnSelectDevice", "btnChangePPD",
                          "chkPEnabled", "chkPAccepting", "chkPShared",
                          "btnPMakeDefault", "lblPDefault",
           
                         "cmbPStartBanner", "cmbPEndBanner",
                          "cmbPErrorPolicy", "cmbPOperationPolicy",

                         "rbtnPAllow", "rbtnPDeny", "tvPUsers",
                          "entPUser", "btnPAddUser", "btnPDelUser", 

                         "swPInstallOptions", "vbPInstallOptions", 
                         "swPOptions",
                          "lblPOptions", "vbPOptions",
                         "vbClassMembers", "lblClassMembers",
                          "tvClassMembers", "tvClassNotMembers",
                          "btnClassAddMember", "btnClassDelMember",
                         "cmbentNewOption", "tblServerOptions", "btnNewOption",
                        
                        "ConnectDialog", "chkEncrypted", "cmbServername",
                         "entUser",
                        "ConnectingDialog", "lblConnecting",
                        "PasswordDialog", "lblPasswordPrompt", "entPasswd",

                        "ErrorDialog", "lblError",

                        "ApplyDialog",

                        "NewPrinterWindow", "ntbkNewPrinter",
                         "btnNPBack", "btnNPForward", "btnNPApply",
                          "entNPName", "entNPDescription", "entNPLocation",
                          "tvNPDevices", "ntbkNPType",
                           "cmbNPTSerialBaud", "cmbNPTSerialParity",
                            "cmbNPTSerialBits", "cmbNPTSerialFlow",
                           "cmbentNPTLpdHost", "cmbentNPTLpdQueue",
                           "entNPTIPPHostname", "entNPTIPPPrintername",
                        "entNPTDirectJetHostname", "entNPTDirectJetPort",
                           "entNPTDevice",
                           "tvNCMembers", "tvNCNotMembers",
                          "rbtnNPPPD", "tvNPMakes", 
                          "rbtnNPFoomatic", "filechooserPPD",
                        
                          "tvNPModels", "tvNPDrivers",
                           "lblNPPDescription", "lblNPDDescription",
                           "lblNPPPDDescription",
                           "frmNPPDescription", "frmNPDDescription",
                           "frmNPPPDDescription",
                          "rbtnChangePPDasIs",
                          "lblNPApply",
                        "NewPrinterName", "entCopyName", "btnCopyOk",
                        "AboutDialog",
                        )

        self.static_tabs = 3

        gtk_label_autowrap.set_autowrap(self.NewPrinterWindow)

        self.status_context_id = self.statusbarMain.get_context_id(
            "Connection")
        self.setConnected()
        self.ntbkMain.set_show_tabs(False)
        self.ntbkNewPrinter.set_show_tabs(False)
        self.ntbkNPType.set_show_tabs(False)
        self.prompt_primary = self.lblPasswordPrompt.get_label ()

        # Paint Description labels black on white
        for label in (self.lblNPPDescription, self.lblNPDDescription,
                      self.lblNPPPDDescription):
            parent = label.get_parent()
            parent.modify_bg(gtk.STATE_NORMAL,
                             gtk.gdk.Color(65535, 65535, 65535))

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

        self.mainlist.append(None, (_("Server Settings"), 'Settings'))
        self.mainlist.append(None, (_("Local Printers"), ""))
        self.mainlist.append(None, (_("Local Classes"), ""))
        self.mainlist.append(None, (_("Remote Printers"), ""))
        self.mainlist.append(None, (_("Remote Classes"), ""))

        self.tooltips = gtk.Tooltips()
        self.tooltips.enable()

        # setup some lists
        m = gtk.SELECTION_MULTIPLE
        s = gtk.SELECTION_SINGLE
        for name, treeview, selection_mode in (
            (_("Members of this Class"), self.tvClassMembers, m),
            (_("Others"), self.tvClassNotMembers, m),
            (_("Members of this Class"), self.tvNCMembers, m),
            (_("Others"), self.tvNCNotMembers, m),
            (_("Devices"), self.tvNPDevices, s),
            (_("Makes"), self.tvNPMakes,s),
            (_("Models"), self.tvNPModels,s),
            (_("Drivers"), self.tvNPDrivers,s),
            (_("Users"), self.tvPUsers, m),
            ):
            
            model = gtk.ListStore(str)
            cell = gtk.CellRendererText()
            column = gtk.TreeViewColumn(name, cell, text=0)
            treeview.set_model(model)
            treeview.append_column(column)
            treeview.get_selection().set_mode(selection_mode)

        ppd_filter = gtk.FileFilter()
        ppd_filter.set_name(_("PostScript Printer Description (*.ppd[.gz])"))
        ppd_filter.add_pattern("*.ppd")
        ppd_filter.add_pattern("*.ppd.gz")
        
        self.filechooserPPD.add_filter(ppd_filter)

        self.conflict_dialog = gtk.MessageDialog(
            parent=None, flags=0, type=gtk.MESSAGE_WARNING,
            buttons=gtk.BUTTONS_OK)
        
        self.populateList()
        
        self.xml.signal_autoconnect(self)

    def getWidgets(self, *names):
        for name in names:
            widget = self.xml.get_widget(name)
            if widget is None:
                raise ValueError, "Widget '%s' not found" % name
            setattr(self, name, widget)
            
    def loadFoomatic(self):
        try:
            return self.foomatic
        except:
            print "Loading foomatic database..."
            self.foomatic = Foomatic() # this works on the local db
            self.foomatic.addCupsPPDs(self.cups.getPPDs(), self.cups)
            return self.foomatic

    def unloadFoomatic(self):
        try:
            del self.foomatic
        except:
            pass

    def setConnected(self):
        connected = bool(self.cups)

        host = cups.getServer()

        if host[0] == '/':
            host = 'localhost'
        self.MainWindow.set_title(_("Printer configuration - %s") % host)

        if connected:
            status_msg = _("Connected to %s") % host
        else:
            status_msg = _("Not connected")
        self.statusbarMain.push(self.status_context_id, status_msg)

        for widget in (self.btnNewPrinter, self.btnNewClass,
                       self.new_printer, self.new_class):
            widget.set_sensitive(connected)
        
    def getServers(self):
        self.servers.discard(None)
        known_servers = list(self.servers)
        known_servers.sort()
        return known_servers

    def populateList(self):
        old_name, old_type = self.getSelectedItem()

        select_path = None

        # get Printers
        if self.cups:
            try:
                self.printers = cupshelpers.getPrinters(self.cups)
            except cups.IPPError, (e, m):
                self.show_IPP_Error(e, m)
                self.printers = {}
        else:
            self.printers = {}
        
        self.default_printer = ""
        #print self.printers

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
        iter = self.mainlist.iter_next(iter) # step over server settings
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
                        
        # Selection
        selection = self.tvMainList.get_selection()
        if select_path:
            selection.select_path(select_path)
        else:
            selection.unselect_all()

        self.on_tvMainList_cursor_changed(self.tvMainList)

    def maySelectItem(self, selection):
        result = self.mainlist.get_value(
            self.mainlist.get_iter(selection), 1)
        return bool(result)

    def getSelectedItem(self):
        model, iter = self.tvMainList.get_selection().get_selected()
        if iter is None:
            return ("", 'None')
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
        current_server = (self.printer and self.printer.getServer()) \
                         or cups.getServer()

        store = gtk.ListStore (gobject.TYPE_STRING)
        self.cmbServername.set_model(store)
        for server in servers:
            self.cmbServername.append_text(server)
        self.cmbServername.show()

        self.cmbServername.child.set_text (current_server)
        self.entUser.set_text (cups.getUser())
        self.chkEncrypted.set_active (cups.getEncryption() ==
                                      cups.HTTP_ENCRYPT_ALWAYS)

        self.cmbServername.grab_focus ()
        self.ConnectDialog.set_transient_for (self.MainWindow)
        response = self.ConnectDialog.run()

        self.ConnectDialog.hide()

        if response != gtk.RESPONSE_OK:
            return

        if self.chkEncrypted.get_active():
            cups.setEncryption(cups.HTTP_ENCRYPT_ALWAYS)
        else:
            cups.setEncryption(cups.HTTP_ENCRYPT_IF_REQUESTED)

        servername = self.cmbServername.child.get_text()
        user = self.entUser.get_text()

        self.lblConnecting.set_text(_("Connecting to Server:\n%s") %
                                    servername)
        self.unloadFoomatic()
        self.ConnectingDialog.show()
        self.connect_thread = thread.start_new_thread(
            self.connect, (servername, user))

    def on_cancel_connect_clicked(self, widget):
        """
        Stop connection to new server
        (Doesn't really stop but sets flag for the connecting thread to
        ignore the connection)
        """
        self.connect_thread = None
        self.ConnectingDialog.hide()

    def connect(self, servername, user):
        """
        Open a connection to a new server. Is executed in a separate thread!
        """
        cups.setServer(servername)
        cups.setPasswordCB(self.cupsPasswdCallback)
        # cups.setEncryption (...)

        if user: cups.setUser(user)
        self.password = ''

        try:
            connection = cups.Connection()
            foomatic = Foomatic()
            foomatic.addCupsPPDs(connection.getPPDs(), connection)
        except RuntimeError, s:
            if self.connect_thread != thread.get_ident(): return
            gtk.threads_enter()
            self.ConnectingDialog.hide()
            self.show_IPP_Error(None, s)
            gtk.threads_leave()
            return        
        except cups.IPPError, (e, s):
            if self.connect_thread != thread.get_ident(): return
            gtk.threads_enter()
            self.ConnectingDialog.hide()
            self.show_IPP_Error(e, s)
            gtk.threads_leave()
            return

        if self.connect_thread != thread.get_ident(): return
        gtk.threads_enter()

        self.foomatic = foomatic
        self.ConnectingDialog.hide()

        self.cups = connection
        self.setConnected()
        self.populateList()
        gtk.threads_leave()

    def on_btnCancelConnect_clicked(self, widget):
        """Close Connect dialog"""
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

    # refresh
    
    def on_btnRefresh_clicked(self, button):
        self.populateList()

    # Unapplied changes dialog

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
        elif isinstance(widget, gtk.RadioButton):
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
            self.rbtnPAllow: p.default_allow,
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


    # Access control
    def getPUsers(self):
        """return list of usernames from the GUI"""
        model = self.tvPUsers.get_model()
        result = []
        model.foreach(lambda model, path, iter:
                      result.append(model.get(iter, 0)[0]))
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
        rows = [gtk.TreeRowReference(model, row) for row in rows]
        for row in rows:
            path = row.get_path()
            iter = model.get_iter(path)
            model.remove(iter)
        self.checkPUsersChanged()

    def on_entPUser_changed(self, widget):
        self.btnPAddUser.set_sensitive(bool(widget.get_text()))

    def on_tvPUsers_cursor_changed(self, widget):
        model, rows = widget.get_selection().get_selected_rows()
        self.btnPDelUser.set_sensitive(bool(rows))

    # Server side options

    def add_option(self, name, value, supported, is_new=False,
                   editable=True):
        option = options.OptionWidget(name, value, supported,
                                      self.option_changed)
        option.is_new = is_new
        rows = self.tblServerOptions.get_property("n-rows")
        self.tblServerOptions.resize(rows+1, 3)
        self.tblServerOptions.attach(option.label, 0, 1, rows, rows+1,
                                     xoptions=gtk.FILL,
                                     yoptions=gtk.FILL)
        option.label.set_alignment(0.0, 0.0)
        option.label.set_padding(5, 5)
        align = gtk.Alignment()
        align.add(option.selector)
        option.align = align
        self.tblServerOptions.attach(align, 1, 2, rows, rows+1,
                                     xoptions=gtk.FILL,
                                     yoptions=0)
        option.selector.set_sensitive(editable)
        if editable:
            # remove button
            btn = gtk.Button(stock="gtk-remove")
            btn.connect("clicked", self.removeOption_clicked)
            btn.set_data("pyobject", option)
            align = gtk.Alignment()
            align.add(btn)
            self.tblServerOptions.attach(align, 2, 3, rows, rows+1,
                                         xoptions=0,
                                         yoptions=gtk.FILL)
            option.remove_button = align
        self.server_side_options[name] = option
        if name in self.changed: # was deleted before
            option.is_new = False
            self.changed.discard(name)
        if option.is_changed():
            self.changed.add(option)

    def removeOption_clicked(self, button):
        option = button.get_data("pyobject")
        self.tblServerOptions.remove(option.label)
        self.tblServerOptions.remove(option.align)
        self.tblServerOptions.remove(option.remove_button)
        if option.is_new:
            self.changed.discard(option)
        else:
            # keep name as reminder that option got deleted
            self.changed.add(option.name)
            del self.server_side_options[option.name]
        self.setDataButtonState()

    def on_btnNewOption_clicked(self, button):
        name = self.cmbentNewOption.get_active_text()
        if name in self.printer.possible_attributes:
            value, supported = self.printer.possible_attributes[name]
        else:
            value, supported = "", ""
        self.add_option(name, value, supported, is_new=True)
        self.tblServerOptions.show_all()
        self.setDataButtonState()

    def on_cmbentNewOption_changed(self, widget):
        self.btnNewOption.set_sensitive(
            bool(self.cmbentNewOption.get_active_text()))

    # set Apply/Revert buttons sensitive    
    def setDataButtonState(self):
        for button in [self.btnApply, self.btnRevert]:
            button.set_sensitive(bool(self.changed) and
                                 not bool(self.conflicts))

        if self.conflicts:
            self.btnConflict.show()
        else:
            self.btnConflict.hide()

    def on_btnConflict_clicked(self, button):
        message = _("There are conflicting options.\n"
                    "Changes can only be applied after\n"
                    "these conflictes are resolved.")
        self.conflict_dialog.set_markup(message)
        self.conflict_dialog.run()
        self.conflict_dialog.hide()

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
            return self.save_printer(self.printer)
        elif type == "Settings":
            return self.save_serversettings()
        
    def show_IPP_Error(self, exception, message):
        if exception == cups.IPP_NOT_AUTHORIZED:
            error_text = _('<span weight="bold" size="larger">' +
                           'Not authorized</span>\n\n' +
                           'The password may be incorrect.')
        else:
            error_text = _('<span weight="bold" size="larger">' +
                           'CUPS server error</span>\n\n' +
                           'There was an error during the CUPS ' +
                           "operation: '%s'.") % message
        self.lblError.set_markup(error_text)
        self.ErrorDialog.set_transient_for (self.MainWindow)
        self.ErrorDialog.run()
        self.ErrorDialog.hide()        
            
    def save_printer(self, printer, saveall=False):
        name = printer.name
        
        try:
            if not printer.is_class and self.ppd: 
                self.getPrinterSettings()
                if self.ppd.nondefaultsMarked() or saveall:
                    self.passwd_retry = False # use cached Passwd 
                    self.cups.addPrinter(name, ppd=self.ppd)

            if printer.is_class:
                # update member list
                new_members = self.getCurrentClassMembers(self.tvClassMembers)
                if not new_members:
                    dialog = gtk.MessageDialog(
                        flags=0, type=gtk.MESSAGE_WARNING,
                        buttons=gtk.BUTTONS_YES_NO,
                        message_format=_("This will delete this Class!"))
                    dialog.format_secondary_text(_("Proceed anyway?"))
                    result = dialog.run()
                    dialog.destroy()
                    if result==gtk.RESPONSE_NO:
                        return True

                # update member list
                old_members = printer.class_members[:]
                
                for member in new_members:
                    if member in old_members:
                        old_members.remove(member)
                    else:
                        self.cups.addPrinterToClass(member, name)
                for member in old_members:
                    self.cups.deletePrinterFromClass(member, name)    

            location = self.entPLocation.get_text()
            info = self.entPDescription.get_text()
            device_uri = self.entPDevice.get_text()

            enabled = self.chkPEnabled.get_active()
            accepting = self.chkPAccepting.get_active()
            shared = self.chkPShared.get_active()

            if info!=printer.info or saveall:
                self.passwd_retry = False # use cached Passwd 
                self.cups.setPrinterInfo(name, info)
            if location!=printer.location or saveall:
                self.passwd_retry = False # use cached Passwd 
                self.cups.setPrinterLocation(name, location)
            if (not printer.is_class and
                (device_uri!=printer.device_uri or saveall)):
                self.passwd_retry = False # use cached Passwd 
                self.cups.setPrinterDevice(name, device_uri)

            if enabled != printer.enabled or saveall:
                self.passwd_retry = False # use cached Passwd 
                self.printer.setEnabled(enabled)
            if accepting == printer.rejecting or saveall:
                self.passwd_retry = False # use cached Passwd 
                self.printer.setAccepting(accepting)
            if shared != printer.is_shared or saveall:
                self.passwd_retry = False # use cached Passwd 
                self.printer.setShared(shared)
                
            job_sheet_start = self.cmbPStartBanner.get_active_text()
            job_sheet_end = self.cmbPEndBanner.get_active_text()
            error_policy = self.cmbPErrorPolicy.get_active_text()
            op_policy = self.cmbPOperationPolicy.get_active_text()

            if (job_sheet_start != printer.job_sheet_start or
                job_sheet_end != printer.job_sheet_end) or saveall:
                self.passwd_retry = False # use cached Passwd
                printer.setJobSheets(job_sheet_start, job_sheet_end)
            if error_policy != printer.error_policy or saveall:
                self.passwd_retry = False # use cached Passwd
                printer.setErrorPolicy(error_policy)
            if op_policy != printer.op_policy or saveall:
                self.passwd_retry = False # use cached Passwd
                printer.setOperationPolicy(op_policy)

            default_allow = self.rbtnPAllow.get_active()
            except_users = self.getPUsers()

            if (default_allow != printer.default_allow or
                except_users != printer.except_users) or saveall:
                self.passwd_retry = False # use cached Passwd
                printer.setAccess(default_allow, except_users)

            for option in printer.attributes:
                if option not in self.server_side_options:
                    print "unset", option
                    printer.unsetOption(option)
            for option in self.server_side_options.itervalues():
                if option.is_changed or saveall:
                    print "save", option.name, option.get_current_value()
                    printer.setOption(option.name, option.get_current_value())

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
    
    def on_btnPMakeDefault_clicked(self, button):
        try:
            self.cups.setDefault(self.printer.name)
        except cups.IPPError, (e, msg):
            self.show_IPP_Error(e, msg)
                                
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
        elif type == "None":
            self.ntbkMain.set_current_page(2)
            self.setDataButtonState()
            item_selected = False

        for widget in [self.copy, self.delete, self.btnCopy, self.btnDelete]:
            widget.set_sensitive(item_selected)

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

        editable = not self.printer.remote

        try:
            self.ppd = printer.getPPD()
        except cups.IPPError, (e, m):
            self.show_IPP_Error(e, m)
            self.ppd = False

        for widget in (self.entPDescription, self.entPLocation,
                       self.entPDevice, self.btnSelectDevice,
                       self.btnChangePPD,
                       self.chkPEnabled, self.chkPAccepting, self.chkPShared,
                       self.cmbPStartBanner, self.cmbPEndBanner,
                       self.cmbPErrorPolicy, self.cmbPOperationPolicy,
                       self.rbtnPAllow, self.rbtnPDeny, self.tvPUsers,
                       self.entPUser, self.btnPAddUser, self.btnPDelUser,
                       self.cmbentNewOption):
            widget.set_sensitive(editable)

        # Description page        
        self.entPDescription.set_text(printer.info)
        self.entPLocation.set_text(printer.location)
        self.lblPMakeModel.set_text(printer.make_and_model)
        self.lblPState.set_text(printer.state_description)

        self.entPDevice.set_text(printer.device_uri)

        # Hide make/model and Device URI for classes
        for widget in (self.lblPMakeModel2, self.lblPMakeModel,
                       self.btnChangePPD, self.lblPDevice2,
                       self.entPDevice, self.btnSelectDevice):
            if printer.is_class:
                widget.hide()
            else:
                widget.show()
            

        self.chkPEnabled.set_active(printer.enabled)
        self.chkPAccepting.set_active(not printer.rejecting)
        self.chkPShared.set_active(printer.is_shared)


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
        self.cmbPStartBanner.set_sensitive(editable)
        self.cmbPEndBanner.set_sensitive(editable)

        # Policies
        self.fillComboBox(self.cmbPErrorPolicy, printer.error_policy_supported,
                          printer.error_policy)
        self.fillComboBox(self.cmbPOperationPolicy,
                          printer.op_policy_supported,
                          printer.op_policy)
        self.cmbPErrorPolicy.set_sensitive(editable)
        self.cmbPOperationPolicy.set_sensitive(editable)

        # Access control
        self.rbtnPAllow.set_active(printer.default_allow)
        self.rbtnPDeny.set_active(not printer.default_allow)
        self.setPUsers(printer.except_users)

        self.entPUser.set_text("")

        # Server side options

        self.server_side_options = {}
        self.cmbentNewOption.get_model().clear()
        self.cmbentNewOption.get_child().set_text("")
        self.btnNewOption.set_sensitive(False)
        attrs = self.printer.possible_attributes.keys()
        attrs.sort()
        for attr in attrs:
            if attr not in self.printer.attributes:
                self.cmbentNewOption.append_text(attr)

        self.tblServerOptions.resize(1, 3)
        for child in self.tblServerOptions.get_children():
            self.tblServerOptions.remove(child)
        
        for attr in printer.attributes:
            value, supported = printer.possible_attributes[attr]
            self.add_option(attr, value, supported, is_new=False,
                            editable=editable)

        self.tblServerOptions.show_all()
        self.tblServerOptions.queue_draw()

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
                self.swPOptions, self.lblPOptions, self.static_tabs)


        if not self.ppd: return
        ppd = self.ppd
        ppd.markDefaults()

        # build option tabs
        for group in ppd.optionGroups:
            if group.name == "InstallableOptions":
                container = self.vbPInstallOptions
                self.ntbkPrinter.insert_page(
                    self.swPInstallOptions, gtk.Label(group.text),
                    self.static_tabs)
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
                self.vbClassMembers, self.lblClassMembers,
                self.static_tabs)

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
        if self.getCurrentClassMembers(self.tvClassMembers) != self.printer.class_members:
            self.changed.add(self.tvClassMembers)
        else:
            self.changed.discard(self.tvClassMembers)
        self.setDataButtonState()
        
    def on_btnClassDelMember_clicked(self, button):
        self.moveClassMembers(self.tvClassMembers,
                              self.tvClassNotMembers)
        if self.getCurrentClassMembers(self.tvClassMembers) != self.printer.class_members:
            self.changed.add(self.tvClassMembers)
        else:
            self.changed.discard(self.tvClassMembers)
        self.setDataButtonState()
        
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

    def getCurrentClassMembers(self, treeview):
        model = treeview.get_model()
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

    # Copy
        
    def on_copy_activate(self, widget):
        # check for unapplied changes
        if self.changed:
            response = self.ApplyDialog.run()
            self.ApplyDialog.hide()
            err = False

            if response == gtk.RESPONSE_REJECT:
                self.changed = set() # avoid asking the user
                self.on_tvMainList_cursor_changed(self.tvMainList)
            elif response == gtk.RESPONSE_APPLY:
                err = self.apply()
            if err or response == gtk.RESPONSE_CANCEL:
                return

        self.entCopyName.set_text(self.printer.name)
        result = self.NewPrinterName.run()
        self.NewPrinterName.hide()

        if result == gtk.RESPONSE_CANCEL:
            return

        self.printer.name = self.entCopyName.get_text()
        self.printer.class_members = [] # for classes make shure all members
                                        # will get added 
        
        self.save_printer(self.printer, saveall=True)
        self.populateList()

    def on_entCopyName_changed(self, widget):
        # restrict
        text = widget.get_text()
        new_text = text
        new_text = new_text.replace("/", "")
        new_text = new_text.replace("#", "")
        new_text = new_text.replace(" ", "")
        if text!=new_text:
            widget.set_text(new_text)
        self.btnCopyOk.set_sensitive(
            self.check_NPName(new_text))

    # Delete

    def on_delete_activate(self, widget):
        name, type = self.getSelectedItem()

        # Confirm
        dialog = gtk.MessageDialog(
            self.MainWindow,
            buttons=gtk.BUTTONS_OK_CANCEL,
            message_format=_("Really delete %s %s?") % (_(type), name))
        result = dialog.run()
        dialog.destroy()

        if result == gtk.RESPONSE_CANCEL:
            return

        try:
            self.cups.deletePrinter(name)
        except cups.IPPError, (e, msg):
            self.show_IPP_Error(e, msg)
                            
        self.populateList()

    # About dialog
    def on_about_activate(self, widget):
        self.AboutDialog.run()
        self.AboutDialog.hide()

    # ====================================================================
    # == New Printer Dialog ==============================================
    # ====================================================================

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

    # new printer
    def on_new_printer_activate(self, widget):
        self.loadFoomatic()
        self.dialog_mode = "printer"
        self.NewPrinterWindow.set_title(_("New Printer"))
        
        self.fillDeviceTab()
        self.fillMakeList()
        self.on_rbtnNPFoomatic_toggled(self.rbtnNPFoomatic)

        self.initNewPrinterWindow()

    # new class
    def on_new_class_activate(self, widget):
        self.dialog_mode = "class"
        self.NewPrinterWindow.set_title(_("New Class"))

        self.fillNewClassMembers()

        self.initNewPrinterWindow()

    # change device
    def on_btnSelectDevice_clicked(self, button):
        self.loadFoomatic()
        self.dialog_mode = "device"
        self.NewPrinterWindow.set_title(_("Change Device URI"))

        self.ntbkNewPrinter.set_current_page(1)
        self.fillDeviceTab(self.printer.device_uri)

        self.initNewPrinterWindow()

    # change PPD
    def on_btnChangePPD_clicked(self, button):
        self.loadFoomatic()
        self.dialog_mode = "ppd"
        self.NewPrinterWindow.set_title(_("Change Driver"))

        self.ntbkNewPrinter.set_current_page(2)
        self.on_rbtnNPFoomatic_toggled(self.rbtnNPFoomatic)

        attr = self.ppd.findAttr("Manufacturer")
        if attr:
            self.auto_make = attr.value
        else:
            self.auto_make = ""
        attr = self.ppd.findAttr("ModelName")
        if not attr: attr = self.ppd.findAttr("ShortNickName")
        if not attr: attr = self.ppd.findAttr("NickName")
        if attr:
            if attr.value.startswith(self.auto_make):
                self.auto_model = attr.value[len(self.auto_make):]
            else:
                try:
                    self.auto_model = attr.value.split(" ", 1)[1]
                except IndexError:
                    self.auto_model = ""
        else:
            self.auto_model = ""

        #print self.auto_make, self.auto_model
        self.fillMakeList()
        self.initNewPrinterWindow()
        

    def initNewPrinterWindow(self):
        if self.dialog_mode in ("printer", "class"):
            self.ntbkNewPrinter.set_current_page(0)
            self.entNPName.grab_focus()
            
            for widget in [self.entNPName, self.entNPLocation,
                           self.entNPDescription]:
                widget.set_text('')
                
        self.setNPButtons()
        self.NewPrinterWindow.set_transient_for(self.MainWindow)
        self.NewPrinterWindow.show()
    

    # Class members

    def fillNewClassMembers(self):
        model = self.tvNCMembers.get_model()
        model.clear()
        model = self.tvNCNotMembers.get_model()
        model.clear()
        for printer in self.printers.itervalues():
            model.append((printer.name,))

    def on_btnNCAddMember_clicked(self, button):
        self.moveClassMembers(self.tvNCNotMembers, self.tvNCMembers)
        self.btnNPForward.set_sensitive(
            bool(self.getCurrentClassMembers(self.tvNCMembers)))
        
    def on_btnNCDelMember_clicked(self, button):
        self.moveClassMembers(self.tvNCMembers, self.tvNCNotMembers)        
        self.btnNPForward.set_sensitive(
            bool(self.getCurrentClassMembers(self.tvNCMembers)))

    # Navigation buttons

    def on_NPCancel(self, widget, event=None):
        self.NewPrinterWindow.hide()
        return True

    def on_btnNPBack_clicked(self, widget):
        self.nextNPTab(-1)

    def on_btnNPForward_clicked(self, widget):
        self.nextNPTab()

    def nextNPTab(self, step=1):
        page_nr = self.ntbkNewPrinter.get_current_page()
        if self.dialog_mode == "class":
            order = [0, 4, 5]
        elif self.dialog_mode == "printer":
            if self.rbtnNPFoomatic.get_active():
                order = [0, 1, 2, 3, 5]
            else:
                order = [0, 1, 2, 5]
        elif self.dialog_mode == "device":
            order = [1]
        elif self.dialog_mode == "ppd":
            if self.rbtnNPFoomatic.get_active():
                order = [2, 3, 6]
            else:
                order = [2, 6]
            
        page_nr = self.ntbkNewPrinter.set_current_page(
            order[order.index(page_nr)+step])
        self.setNPButtons()

    def setNPButtons(self):
        nr = self.ntbkNewPrinter.get_current_page()

        if self.dialog_mode == "device":
            self.btnNPBack.hide()
            self.btnNPForward.hide()
            self.btnNPApply.show()
            return

        if self.dialog_mode == "ppd":
            if nr == 6: # Apply
                self.btnNPForward.hide()
                self.btnNPApply.show()
                self.fillNPApply()
                return
            else:
                self.btnNPForward.show()
                self.btnNPApply.hide()
            if nr == 2:
                self.btnNPBack.hide()
                self.btnNPForward.show()
                self.btnNPForward.set_sensitive(True)
                return
            else:
                self.btnNPBack.show()

        # class/printer

        if nr == 0: # name
            self.btnNPBack.hide()
            self.btnNPForward.set_sensitive(
                self.check_NPName(self.entNPName.get_text()))
        else:
            self.btnNPBack.show()
        if nr == 1: # Device
            pass
        if nr == 2: # Make/PPD file
            self.btnNPForward.set_sensitive(bool(
                self.rbtnNPFoomatic.get_active() or
                self.filechooserPPD.get_filename()))
        if nr == 3: # Model/Driver
            model, iter = self.tvNPDrivers.get_selection().get_selected()
            self.btnNPForward.set_sensitive(bool(iter))
        if nr == 4: # Class Members
            self.btnNPForward.set_sensitive(
                bool(self.getCurrentClassMembers(self.tvNCMembers)))
        if nr == 5: # Apply
            self.btnNPForward.hide()
            self.btnNPApply.show()
            self.fillNPApply()
        else:
            self.btnNPForward.show()
            self.btnNPApply.hide()
            
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

    def fillDeviceTab(self, current_uri=None):
        try:
            devices = cupshelpers.getDevices(self.cups, current_uri)
        except cups.IPPError, (e, msg):
            self.show_IPP_Error(e, msg)
            devices = {}
            
        if current_uri:
            current = devices.pop(current_uri)
        devices = devices.values()
        devices.sort()
        self.devices = filter(lambda x: x.uri not in ("hp:/no_device_found",
                                                      "hal", "beh",
                                                      "scsi", "http"),
                              devices) 

        self.devices.insert(0, cupshelpers.Device('',
             **{'device-info' :_("Other")}))
        if current_uri:
            current.info += _(" (Current)")
            self.devices.insert(0, current)
        model = self.tvNPDevices.get_model()
        model.clear()

        for device in self.devices:
            model.append((device.info,))
            
        self.tvNPDevices.get_selection().select_path(0)
        self.on_tvNPDevices_cursor_changed(self.tvNPDevices)

    def on_tvNPDevices_cursor_changed(self, widget):
        model, iter = widget.get_selection().get_selected()
        path = model.get_path(iter)
        device = self.devices[path[0]]
        self.device = device
        self.ntbkNPType.set_current_page(
            self.new_printer_device_tabs.get(device.type, 1))

        type = device.type
        url = device.uri.split(":", 1)[-1]
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
                     ["none", "odd", "even"]),
                    (self.cmbNPTSerialFlow, "flow",
                     ["none", "soft", "hard", "hard"])):
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
                                            
        # XXX FILL TABS FOR VALID DEVICE URIs
        elif device.type in ("ipp", "http", "lpd"):
            try:
                server, printer = url.split("/", 1)
            except ValueError:
                server, printer = url, ""
            if device.type == "lpd":
                pass # XXX
            else:
                self.entNPTIPPHostname.set_text(server)
                self.entNPTIPPPrintername.set_text(printer)
        else:
            self.entNPTDevice.set_text(device.uri)


        self.auto_make, self.auto_model = None, None

        printer_name = self.foomatic.getPrinterFromCupsDevice(self.device)
        if printer_name:
            printer = self.foomatic.getPrinter(printer_name)
            if printer:
                self.auto_make, self.auto_model = printer.make, printer.model


    def on_btnNPTLpdProbe_clicked(self, button):
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
            host = self.entNPTDirectJetHostname.get_text()
            port = self.entNPTDirectJetPort.get_text()
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
            host = self.cmbentNPTLpdHost.get_active_text()
            printer = self.cmbentNPTLpdQueue.get_active_text()
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
        elif not self.device.is_class:
            device = self.device.uri
        else:
            device = self.entNPTDevice.get_text()
        return device
    
    # PPD

    def on_rbtnNPFoomatic_toggled(self, widget):
        foo = self.rbtnNPFoomatic.get_active()
        self.tvNPMakes.set_sensitive(foo)
        self.filechooserPPD.set_sensitive(not foo)
        self.setNPButtons()

    def on_filechooserPPD_selection_changed(self, widget):
        self.setNPButtons()

    # PPD from foomatic

    def fillMakeList(self):
        makes = self.foomatic.getMakes()
        model = self.tvNPMakes.get_model()
        model.clear()
        found = False
        for make in makes:            
            iter = model.append((make,))
            if make==self.auto_make:
                self.tvNPMakes.get_selection().select_iter(iter)
                path = model.get_path(iter)
                self.tvNPMakes.scroll_to_cell(path, None,
                                              True, 0.0, 0.0)
                found = True

        if not found:
            self.tvNPMakes.get_selection().select_path(0)
            
        self.on_tvNPMakes_cursor_changed(self.tvNPMakes)
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

    #def _fillPPDList(self, iter, treenode):
    #    if treenode.name:
    #        iter = self.tvNPDriversModel.append(iter, (treenode.name,))
    #    for leaf in treenode.leafs:
    #        self._fillPPDList(iter, leaf)

    def on_tvNPMakes_cursor_changed(self, widget):
        model, iter = self.tvNPMakes.get_selection().get_selected()
        self.NPMake = model.get(iter, 0)[0]
        self.fillModelList()

    def fillModelList(self):
        models = self.foomatic.getModels(self.NPMake)
        model = self.tvNPModels.get_model()
        model.clear()
        selected = False
        for pmodel in models:
            iter = model.append((pmodel,))
            if self.NPMake==self.auto_make and pmodel==self.auto_model:
                path = model.get_path(iter)
                self.tvNPModels.scroll_to_cell(path, None,
                                               True, 0.5, 0.5)
                self.tvNPModels.get_selection().select_iter(iter)
                selected = True
        if not selected:
            self.tvNPModels.get_selection().select_path(0)
        self.on_tvNPModels_cursor_changed(self.tvNPModels)
        
    def fillDriverList(self, printer):
        model = self.tvNPDrivers.get_model()
        model.clear()
        self.NPDrivers = printer.drivers.keys()
        self.NPDrivers.sort()
        found = False
        for driver in self.NPDrivers:
            if driver==printer.driver:
                iter = model.append((driver + _(" (recommended)"),))
                path = model.get_path(iter)
                self.tvNPDrivers.get_selection().select_path(path)
                found = True
            else:
                model.append((driver, ))

        if not found:
             self.tvNPDrivers.get_selection().select_path(0)
             
    def on_tvNPModels_cursor_changed(self, widget):        
        model, iter = widget.get_selection().get_selected()
        pmodel = model.get(iter, 0)[0]
        printer = self.foomatic.getMakeModel(self.NPMake, pmodel)
        self.NPModel = pmodel
        self.fillDriverList(printer)

        if self.frmNPPDescription.flags() & gtk.VISIBLE:
            self.lblNPPDescription.set_markup(printer.getCommentPango(
                self.language, "en"))
        self.on_tvNPDrivers_cursor_changed(self.tvNPDrivers)

    def on_tvNPDrivers_cursor_changed(self, widget):
        if ((self.frmNPDDescription.flags() & gtk.VISIBLE) or
            (self.frmNPPPDDescription.flags() & gtk.VISIBLE)):
            model, iter = widget.get_selection().get_selected()
            if iter is None:
                self.lblNPDDescription.set_markup('')
                self.lblNPPPDDescription.set_markup('')
            else:
                nr = model.get_path(iter)[0]
                driver = self.NPDrivers[nr]
                driver = self.foomatic.getDriver(driver)
                if self.frmNPDDescription.flags() & gtk.VISIBLE:
                    self.lblNPDDescription.set_markup(
                        driver.getCommentPango(self.language, "en"))
                if self.frmNPPPDDescription.flags() & gtk.VISIBLE: 
                    # XXX PPD Info
                    pass
        self.setNPButtons()

    # toggle Comments

    def on_tglNPShowPrinterDescription_toggled(self, widget):
        if widget.get_active():
            self.frmNPPDescription.show()
            self.on_tvNPModels_cursor_changed(self.tvNPModels)
        else:
            self.frmNPPDescription.hide()
            
    def on_tglNPShowDriverDescription_toggled(self, widget):
        if widget.get_active():
            self.frmNPDDescription.show()
            self.on_tvNPDrivers_cursor_changed(self.tvNPDrivers)
        else:
            self.frmNPDDescription.hide()

    def on_tglNPShowPPDInfo_toggled(self, widget):
        if widget.get_active():
            self.frmNPPPDDescription.show()
            self.on_tvNPDrivers_cursor_changed(self.tvNPDrivers)
        else:
            self.frmNPPPDDescription.hide()

    def getNPPPD(self):
        if self.rbtnNPFoomatic.get_active():
            model, iter = self.tvNPDrivers.get_selection().get_selected()
            nr = model.get_path(iter)[0]
            driver = self.NPDrivers[nr]
            printer = self.foomatic.getMakeModel(self.NPMake, self.NPModel)
            return printer.getPPD(driver)
        else:
            return cups.PPD(self.filechooserPPD.get_filename())

    def fillNPApply(self):
        name = self.entNPName.get_text()
        if self.dialog_mode=="class":
            # XXX
            msg = _("Going to create a new class %s.") % name
        else:
            # XXX
            uri = self.getDeviceURI()
            msg = _(
"""Going to create a new printer %s at
%s.
""" ) % (name, uri)
        self.lblNPApply.set_markup(msg)
            
    # Create new Printer
    def on_btnNPApply_clicked(self, widget):
        if self.dialog_mode in ("class", "printer"):
            name = self.entNPName.get_text()
            location = self.entNPLocation.get_text()
            info = self.entNPDescription.get_text()
        else:
            name = self.printer.name

        if self.dialog_mode=="class":
            members = self.getCurrentClassMembers(self.tvNCMembers)
            try:
                for member in members:
                    self.passwd_retry = False # use cached Passwd 
                    self.cups.addPrinterToClass(member, name)
            except cups.IPPError, (e, msg):
                self.show_IPP_Error(e, msg)
                return
        elif self.dialog_mode=="printer":
            uri = self.getDeviceURI()
            ppd = self.getNPPPD()
        
            try:
                self.passwd_retry = False # use cached Passwd
                if isinstance(ppd, str) or isinstance(ppd, unicode):
                    self.cups.addPrinter(name, ppdname=ppd,
                         device=uri, info=info, location=location)
                else:
                    self.cups.addPrinter(name, ppd=ppd,
                         device=uri, info=info, location=location)
            except cups.IPPError, (e, msg):
                self.show_IPP_Error(e, msg)
                return
        if self.dialog_mode in ("class", "printer"):
            try:
                self.passwd_retry = False # use cached Passwd 
                self.cups.setPrinterLocation(name, location)
                self.passwd_retry = False # use cached Passwd 
                self.cups.setPrinterInfo(name, info)
            except cups.IPPError, (e, msg):
                self.show_IPP_Error(e, msg)
                return
        elif self.dialog_mode == "device":
            try:
                uri = self.getDeviceURI()
                self.passwd_retry = False # use cached Passwd 
                self.cups.addPrinter(name, device=uri)
            except cups.IPPError, (e, msg):
                self.show_IPP_Error(e, msg)
                return
        elif self.dialog_mode == "ppd":
            ppd = self.getNPPPD()

            # set ppd on server and retrieve it
            # cups doesn't offer a way to just download a ppd ;(=
            if isinstance(ppd, str) or isinstance(ppd, unicode):
                try:
                    self.passwd_retry = False # use cached Passwd
                    self.cups.addPrinter(name, ppdname=ppd)
                    self.passwd_retry = False # use cached Passwd
                    filename = self.cups.getPPD(name)
                    ppd = cups.PPD(filename)
                    os.unlink(filename)
                except cups.IPPError, (e, msg):
                    self.show_IPP_Error(e, msg)
                    return
                                
            # copy over old option settings
            if not self.rbtnChangePPDasIs.get_active():
                print "COPYING OPTIONS"
                cupshelpers.copyPPDOptions(self.ppd, ppd)

            try:
                self.passwd_retry = False # use cached Passwd
                self.cups.addPrinter(name, ppd=ppd)
            except cups.IPPError, (e, msg):
                self.show_IPP_Error(e, msg)
                            
        self.NewPrinterWindow.hide()
        self.populateList()

    ##########################################################################
    ### Server settings
    ##########################################################################

    def fillServerTab(self):
        self.changed = set()
        try:
            self.server_settings = self.cups.adminGetServerSettings()
        except cups.IPPError, (e, m):
            self.show_IPP_Error(e, m)
            self.tvMainList.get_selection().unselect_all()
            self.on_tvMainList_cursor_changed(self.tvMainList)
            return

        for widget, setting in [
            (self.chkServerBrowse, cups.CUPS_SERVER_REMOTE_PRINTERS),
            (self.chkServerShare, cups.CUPS_SERVER_SHARE_PRINTERS),
            (self.chkServerRemoteAdmin, cups.CUPS_SERVER_REMOTE_ADMIN),
            (self.chkServerAllowCancelAll, cups.CUPS_SERVER_USER_CANCEL_ANY),
            (self.chkServerLogDebug, cups.CUPS_SERVER_DEBUG_LOGGING),]:
            widget.set_data("setting", setting)
            if self.server_settings.has_key(setting):
                widget.set_active(int(self.server_settings[setting]))
                widget.show()
            else:
                widget.hide()
        self.setDataButtonState()
        
    def on_server_changed(self, widget):
        if (str(int(widget.get_active())) ==
            self.server_settings[widget.get_data("setting")]):
            self.changed.discard(widget)
        else:
            self.changed.add(widget)
        self.setDataButtonState()

    def save_serversettings(self):
        setting_dict = self.server_settings.copy()
        for widget, setting in [
            (self.chkServerBrowse, cups.CUPS_SERVER_REMOTE_PRINTERS),
            (self.chkServerShare, cups.CUPS_SERVER_SHARE_PRINTERS),
            (self.chkServerRemoteAdmin, cups.CUPS_SERVER_REMOTE_ADMIN),
            (self.chkServerAllowCancelAll, cups.CUPS_SERVER_USER_CANCEL_ANY),
            (self.chkServerLogDebug, cups.CUPS_SERVER_DEBUG_LOGGING),]:
            if not self.server_settings.has_key(setting): continue
            setting_dict[setting] = str(int(widget.get_active()))
        try:
            self.cups.adminSetServerSettings(setting_dict)
        except cups.IPPError, (e, m):
            self.show_IPP_Error(e, m)
            return True
        self.changed = set()
        self.setDataButtonState()
        time.sleep(0.1) # give the server a chance to process our request

def main():
    # The default configuration requires root for administration.
    cups.setUser ("root")
    gtk.gdk.threads_init()
    gtk.threads_enter()

    mainwindow = GUI()
    if gtk.__dict__.has_key("main"):
        gtk.main()
    else:
        gtk.mainloop()

    gtk.threads_leave()

if __name__ == "__main__":
    main()

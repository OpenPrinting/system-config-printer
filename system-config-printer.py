#!/bin/env python

import sys

sys.path.append("/home/ffesti/CVS/pycups")

import gtk.glade, cups
from optionwidgets import OptionWidget
from foomatic import Foomatic

class GUI:

    def __init__(self):
        self.password = ''
        
        self.cups = cups.Connection()
        cups.setPasswordCB(self.cupsPasswdCallback)
        
        self.xml = gtk.glade.XML("system-config-printer.glade")
        self.getWidgets("MainWindow", "tvMainList", "ntbkMain",
                        "entPDescription", "entPLocation", "lblPMakeModel",
                        "lblPState", "entPDevice",
                        "vbPInstallOptions", "vbPOptions", "ntbkPrinter",
                        "swPInstallOptions", "swPOptions",
                        "btnNewPrinter", "btnNewClass", "btnCopy", "btnDelete",
                        "new_printer", "new_class", "copy", "delete",

                        "ConnectWindow", "chkEncrypted", "cmbServername",
                        "entUser", "entPassword",

                        "PasswordDialog", "entPasswd",
                        )
        self.ntbkMain.set_show_tabs(False)
        
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

        self.xml.signal_autoconnect(self)

    def getWidgets(self, *names):
        for name in names:
            widget = self.xml.get_widget(name)
            if widget is None:
                raise ValueError, "Widget '%s' not found" % name
            setattr(self, name, widget)

    def populateList(self):
        self.mainlist.clear()

        self.mainlist.append(("Server Settings", 'Settings'))

        # Printers
        self.printers = self.cups.getPrinters()
        names = self.printers.keys()
        names.sort()

        self.mainlist.append(("Printers:", ''))

        for name in names:
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
        # XXX insert know servers
        # XXX clear passwd field?
        # XXX check for unapplied changes
        self.ConnectWindow.show()

    def on_btnConnect_clicked(self, widget):
        # XXX check for unapplied changes
        if self.chkEncrypted.get_active():
            cups.setEncryption(cups.HTTP_ENCRYPT_ALWAYS) # XXX REQUIRED?
        else:
            cups.setEncryption(cups.HTTP_ENCRYPT_IF_REQUESTED)

        servername = self.cmbServername.child.get_text()
        # XXX append port and protocoll if needed
        cups.setServer(servername)

        user = self.entUser.get_text()
        if user: cups.setUser(user)
        self.password = self.entPassword.get_text()

        try:
            connection = cups.Connection() # XXX timeout?
        except:
            connection = None

        if not connection: # error handling
            # XXX more Error handling
            return

        self.ConnectWindow.hide()
        self.cups = connection
        self.populateList()

    def on_btnCancelConnect_clicked(self, widget):
        self.ConnectWindow.hide()

    # Password handling

    def cupsPasswdCallback(self, *args):
        print args
        if self.PasswordDialog.run():
            self.password = ''
        else:
            self.Password = entPasswd.get_text()
        self.PasswordDialog.hide()
        return self.password
    
    def on_btnPasswdOk_clicked(self, widget):
        self.PasswordDialog.response(0)

    def on_btnPasswdCancel_clicked(self, widget):
        self.PasswordDialog.response(1)

    # Create/Delete
    
    def on_new_printer_activate(self, widget):
        print "NEW PRINTER"

    def on_new_class_activate(self, widget):
        print "NEW CLASS"
        
    def on_copy_activate(self, widget):
        print "COPY"

    def on_delete_activate(self, widget):
        name, type = self.getSelectedItem()
        if type == "Printer":
            print "DELETE Printer"
        elif type == "Class":
            print "DELETE Class"

    def on_btnApply_clicked(self, widget):
        name, type = self.getSelectedItem()
        if type == "Printer":
            self.getPrinterSettings()
            location = self.entPLocation.get_text()
            description = self.entPDescription.get_text()
            device = self.entPDevice.get_text()
            self.cups.addPrinter(name, ppd=self.ppd)
        elif type == "Class":
            print "DELETE Class"
        elif type == "Settings":
            pass

    def on_tvMainList_cursor_changed(self, list):
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
        printer = self.printers[name] 
        self.entPDescription.set_text(printer.get("printer-info", ""))
        self.entPLocation.set_text(printer.get("printer-location", ""))
        self.lblPMakeModel.set_text(printer.get("printer-make-and-model", ""))
        self.lblPState.set_text(str(printer.get("printer-state", 0)))
           # XXX translate into text
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
        self.ppd = ppd

        self.options = []
        
        for group in ppd.optionGroups:
            if group.name == "InstallableOptions":
                container = self.vbPInstallOptions
                self.ntbkPrinter.insert_page(self.swPInstallOptions,
                                             gtk.Label(group.text), 1)
            else:
                container = self.vbPOptions
                label = gtk.Label(group.text)
                label.set_alignment(0.0,0.5)
                container.pack_start(label)

            table = gtk.Table(len(group.options), 2, False)
            #table.set_homogeneous
            container.add(table)

            for nr, option in enumerate(group.options):
                o = OptionWidget(option, ppd, self)
                table.attach(o.label, 0, 1, nr, nr+1, gtk.FILL, False)
                table.attach(o.selector, 1, 2, nr, nr+1, gtk.FILL, False)
                self.options.append(o)
                
        self.swPInstallOptions.show_all()
        self.swPOptions.show_all()

    def getPrinterSettings(self):
        for option in self.options:
            option.writeback()

    def fillClassTab(self, name):
        pass

    def on_quit_activate(self, widget, event=None):
        # XXX check for unapplied changes
        gtk.main_quit()

    # == New Printer =====================================================

    

        
def main():
    mainwindow = GUI()
    if gtk.__dict__.has_key("main"):
        gtk.main()
    else:
        gtk.mainloop()

if __name__ == "__main__":
    main()

#!/usr/bin/env python

## Copyright (C) 2007 Tim Waugh <twaugh@redhat.com>
## Copyright (C) 2007 Red Hat, Inc.

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

import cups
import sys

APPDIR="/usr/share/system-config-printer"
DOMAIN="system-config-printer"
GLADE="applet.glade"
ICON="applet.png"

class JobManager:
    def __init__(self, bus, loop, service_running=False, trayicon=True):
        self.loop = loop
        self.service_running = service_running
        self.trayicon = trayicon

        self.jobs = {}
        self.jobiters = {}
        self.which_jobs = "not-completed"
        self.hidden = False

        self.xml = gtk.glade.XML(APPDIR + "/" + GLADE)
        self.xml.signal_autoconnect(self)
        self.treeview = self.xml.get_widget ('treeview')
        text=0
        for name in [_("Job"),
                     _("Document"),
                     _("Printer"),
                     _("Size"),
                     _("Time submitted"),
                     _("Status")]:
            cell = gtk.CellRendererText()
            if text == 1 or text == 2:
                # Ellipsize the 'Document' and 'Printer' columns.
                cell.set_property ("ellipsize", pango.ELLIPSIZE_END)
                cell.set_property ("width-chars", 20)
            column = gtk.TreeViewColumn(name, cell, text=text)
            column.set_resizable(True)
            self.treeview.append_column(column)
            text += 1

        self.treeview.get_selection().set_mode(gtk.SELECTION_SINGLE)
        self.store = gtk.TreeStore(int, str, str, str, str, str)
        self.store.set_sort_column_id (0, gtk.SORT_DESCENDING)
        self.treeview.set_model(self.store)

        self.MainWindow = self.xml.get_widget ('MainWindow')
        self.MainWindow.set_icon_from_file (APPDIR + "/" + ICON)
        self.MainWindow.hide ()

        self.job_popupmenu = self.xml.get_widget ('job_popupmenu')
        self.icon_popupmenu = self.xml.get_widget ('icon_popupmenu')
        self.cancel = self.xml.get_widget ('cancel')
        self.hold = self.xml.get_widget ('hold')
        self.release = self.xml.get_widget ('release')
        self.reprint = self.xml.get_widget ('reprint')

        self.lblPasswordPrompt = self.xml.get_widget('lblPasswordPrompt')
        self.PasswordDialog = self.xml.get_widget('PasswordDialog')
        self.entPasswd = self.xml.get_widget('entPasswd')
        self.prompt_primary = self.lblPasswordPrompt.get_label ()
        self.lblError = self.xml.get_widget('lblError')
        self.ErrorDialog = self.xml.get_widget('ErrorDialog')

        cups.setPasswordCB(self.cupsPasswdCallback)

        # D-Bus
        bus.add_signal_receiver (self.handle_dbus_signal,
                                 path="/com/redhat/PrinterSpooler",
                                 dbus_interface="com.redhat.PrinterSpooler")

        if self.trayicon:
            self.statusicon = gtk.StatusIcon ()
            self.statusicon.set_from_file (APPDIR + "/" + ICON)
            self.icon_jobs = self.statusicon.get_pixbuf ()
            self.icon_no_jobs = self.icon_jobs.copy ()
            self.icon_no_jobs.fill (0)
            self.icon_jobs.composite (self.icon_no_jobs,
                                      0, 0,
                                      self.icon_no_jobs.get_width(),
                                      self.icon_no_jobs.get_height(),
                                      0, 0,
                                      1.0, 1.0,
                                      gtk.gdk.INTERP_BILINEAR,
                                      127)
            self.statusicon.set_from_pixbuf (self.icon_no_jobs)
            self.statusicon.connect ('activate', self.toggle_window_display)
            self.statusicon.connect ('popup-menu', self.on_icon_popupmenu)

        self.refresh ()

        if not self.trayicon:
            self.MainWindow.show ()

    def on_delete_event(self, *args):
        if self.trayicon:
            self.MainWindow.hide ()
        else:
            self.loop.quit ()
        return True

    def cupsPasswdCallback(self, querystring):
        self.lblPasswordPrompt.set_label (self.prompt_primary + querystring)
        self.PasswordDialog.set_transient_for (self.MainWindow)
        self.entPasswd.grab_focus ()
        result = self.PasswordDialog.run()
        self.PasswordDialog.hide()
        if result == gtk.RESPONSE_OK:
            return self.entPasswd.get_text()
        return ''

    def show_IPP_Error(self, exception, message):
        if exception == cups.IPP_NOT_AUTHORIZED:
            error_text = ('<span weight="bold" size="larger">' +
                          _('Not authorized') + '</span>\n\n' +
                          _('The password may be incorrect.'))
        else:
            error_text = ('<span weight="bold" size="larger">' +
                          _('CUPS server error') + '</span>\n\n' +
                          _("There was an error during the CUPS "\
                            "operation: '%s'.")) % message
        self.lblError.set_markup(error_text)
        self.ErrorDialog.set_transient_for (self.MainWindow)
        self.ErrorDialog.run()
        self.ErrorDialog.hide()

    def toggle_window_display(self, icon):
        if self.MainWindow.get_property('visible'):
            self.MainWindow.hide()
        else:
            self.MainWindow.show()

    def on_show_completed_jobs_activate(self, menuitem):
        if menuitem.get_active():
            self.which_jobs = "all"
        else:
            self.which_jobs = "not-completed"
        self.refresh()

    def refresh(self):
        if self.hidden:
            return
        try:
            c = cups.Connection ()
            jobs = c.getJobs (which_jobs=self.which_jobs, my_jobs=True)
        except cups.IPPError, (e, m):
            self.show_IPP_Error (e, m)
            return
        except RuntimeError:
            return

        if self.which_jobs == "not-completed":
            num_jobs = len (jobs)
        else:
            try:
                num_jobs = len (c.getJobs (my_jobs=True))
            except cups.IPPError, (e, m):
                self.show_IPP_Error (e, m)
                return
            except RuntimeError:
                return

        del c
        if self.trayicon:
            if num_jobs == 0:
                self.statusicon.set_tooltip (_("No documents queued"))
                self.statusicon.set_from_pixbuf (self.icon_no_jobs)
            elif num_jobs == 1:
                self.statusicon.set_tooltip (_("1 document queued"))
                self.statusicon.set_from_pixbuf (self.icon_jobs)
            else:
                self.statusicon.set_tooltip (_("%d documents queued") %
                                             num_jobs)
                self.statusicon.set_from_pixbuf (self.icon_jobs)

        for job in self.jobs:
            if not jobs.has_key (job):
                self.store.remove (self.jobiters[job])
                del self.jobiters[job]

        for job, data in jobs.iteritems():
            if self.jobs.has_key (job):
                iter = self.jobiters[job]
            else:
                iter = self.store.append (None)
                self.store.set_value (iter, 0, job)
                self.store.set_value (iter, 1, data.get('job-name', 'Unknown'))
                self.jobiters[job] = iter

            printer = "Unknown"
            uri = data.get('job-printer-uri', '')
            i = uri.rfind ('/')
            if i != -1:
                printer = uri[i + 1:]
            self.store.set_value (iter, 2, printer)

            if data.has_key ('job-k-octets'):
                size = str (data['job-k-octets']) + 'k'
            else:
                size = 'Unknown'
            self.store.set_value (iter, 3, size)

            t = "Unknown"
            if data.has_key ('time-at-creation'):
                created = data['time-at-creation']
                now = time.time ()
                ago = now - created
                if ago > 86400:
                    t = time.ctime (created)
                elif ago > 3600:
                    hours = ago / 3600
                    mins = (ago % 3600) / 60
                    if hours == 1:
                        if mins == 0:
                            t = _("1 hour ago")
                        elif mins == 1:
                            t = _("1 hour and 1 minute ago")
                        else:
                            t = _("1 hour and %d minutes ago") % mins
                    else:
                        if mins == 0:
                            t = _("%d hours ago")
                        elif mins == 1:
                            t = _("%d hours and 1 minute ago") % hours
                        else:
                            t = _("%d hours and %d minutes ago") % \
                                (hours, mins)
                else:
                    mins = ago / 60
                    if mins < 2:
                        t = _("a minute ago")
                    else:
                        t = _("%d minutes ago") % mins

            self.store.set_value (iter, 4, t)

            state = None
            if data.has_key ('job-state'):
                try:
                    jstate = data['job-state']
                    s = int (jstate)
                    state = { cups.IPP_JOB_PENDING:_("Pending"),
                              cups.IPP_JOB_HELD:_("Held"),
                              cups.IPP_JOB_PROCESSING: _("Processing"),
                              cups.IPP_JOB_STOPPED: _("Stopped"),
                              cups.IPP_JOB_CANCELED: _("Canceled"),
                              cups.IPP_JOB_ABORTED: _("Aborted"),
                              cups.IPP_JOB_COMPLETED: _("Completed") }[s]
                except ValueError:
                    pass
                except IndexError:
                    pass    
            if state == None:
                state = _("Unknown")
            self.store.set_value (iter, 5, state)

        self.jobs = jobs

    def on_treeview_button_press_event(self, treeview, event):
        if event.button != 3:
            return

        # Right-clicked.
        store, iter = treeview.get_selection ().get_selected ()
        if iter == None:
            return

        self.jobid = self.store.get_value (iter, 0)
        job = self.jobs[self.jobid]
        self.cancel.set_sensitive (True)
        self.hold.set_sensitive (True)
        self.release.set_sensitive (True)
        self.reprint.set_sensitive (True)
        if job.has_key ('job-state'):
            s = job['job-state']
            if s >= cups.IPP_JOB_CANCELED:
                self.cancel.set_sensitive (False)
            if s != cups.IPP_JOB_PENDING:
                self.hold.set_sensitive (False)
            if s != cups.IPP_JOB_HELD:
                self.release.set_sensitive (False)
            if (s < cups.IPP_JOB_CANCELED or
                not job.get('job-preserved', False)):
                self.reprint.set_sensitive (False)
        self.job_popupmenu.popup (None, None, None, event.button,
                                  event.get_time ())

    def on_icon_popupmenu(self, icon, button, time):
        self.icon_popupmenu.popup (None, None, None, button, time)

    def on_icon_hide_activate(self, menuitem):
        bus.remove_signal_receiver (self.handle_dbus_signal,
                                    path="/com/redhat/PrinterSpooler",
                                    dbus_interface="com.redhat.PrinterSpooler")
        self.hidden = True
        self.statusicon.set_visible (False)
        if not self.service_running:
            self.loop.quit ()

    def on_job_cancel_activate(self, menuitem):
        try:
            c = cups.Connection ()
            c.cancelJob (self.jobid)
            del c
        except cups.IPPError, (e, m):
            self.show_IPP_Error (e, m)
            return
        except RuntimeError:
            return

    def on_job_hold_activate(self, menuitem):
        try:
            c = cups.Connection ()
            c.setJobHoldUntil (self.jobid, "indefinite")
            del c
        except cups.IPPError, (e, m):
            self.show_IPP_Error (e, m)
            return
        except RuntimeError:
            return

    def on_job_release_activate(self, menuitem):
        try:
            c = cups.Connection ()
            c.setJobHoldUntil (self.jobid, "no-hold")
            del c
        except cups.IPPError, (e, m):
            self.show_IPP_Error (e, m)
            return
        except RuntimeError:
            return

    def on_job_reprint_activate(self, menuitem):
        try:
            c = cups.Connection ()
            c.restartJob (self.jobid)
            del c
        except cups.IPPError, (e, m):
            self.show_IPP_Error (e, m)
            return
        except RuntimeError:
            return

        self.refresh ()

    def on_refresh_activate(self, menuitem):
        self.refresh ()

    def handle_dbus_signal(self, *args):
        self.refresh ()

gtk_loaded = False
def do_imports():
    global gtk_loaded
    if not gtk_loaded:
        gtk_loaded = True
        global gtk, pango, time, gettext, _
        import gtk, gtk.glade, pango
        import time
        import gettext
        from gettext import gettext as _
        gettext.textdomain (DOMAIN)
        gtk.glade.bindtextdomain (DOMAIN)

PROGRAM_NAME="system-config-printer-applet"
def show_help ():
    print "usage: %s [--no-tray-icon]" % PROGRAM_NAME

def show_version ():
    import config
    print "%s %s" % (PROGRAM_NAME, config.VERSION)
    
####
#### Main program entry
####

trayicon = True
service_running = False

import sys, getopt
try:
    opts, args = getopt.gnu_getopt (sys.argv[1:], '',
                                    ['no-tray-icon',
                                     'help',
                                     'version'])
except getopt.GetoptError:
    show_help ()
    sys.exit (1)

for opt, optarg in opts:
    if opt == "--help":
        show_help ()
        sys.exit (0)
    if opt == "--version":
        show_version ()
        sys.exit (0)
    if opt == "--no-tray-icon":
        trayicon = False

import dbus
import dbus.glib
import dbus.service
import gobject

####
#### PrintDriverSelection DBus server
####
PDS_PATH="/com/redhat/PrintDriverSelection"
PDS_IFACE="com.redhat.PrintDriverSelection"
PDS_OBJ="com.redhat.PrintDriverSelection"
class PrintDriverSelection(dbus.service.Object):
    def __init__(self, bus_name):
        dbus.service.Object.__init__(self, bus_name, PDS_PATH)

    @dbus.service.method(PDS_IFACE, in_signature='ssss', out_signature='')
    def PromptPrintDriver (self, make, model, uid, name):
        do_imports ()
        print "Need to implement PromptPrintDriver"

    # Need to add an interface for providing a PPD.

bus = dbus.SystemBus()
if trayicon:
    try:
        name = dbus.service.BusName (PDS_OBJ, bus=bus)
        PrintDriverSelection(name)
        service_running = True
    except:
        print "%s: failed to start PrintDriverSelection service" % PROGRAM_NAME

    # Start off just waiting for print jobs.
    def any_jobs ():
        try:
            c = cups.Connection ()
            if len (c.getJobs (my_jobs=True)):
                return True
        except:
            pass

        return False

    if not any_jobs ():
        def check_for_jobs (*args):
            if any_jobs ():
                loop.quit ()

        bus.add_signal_receiver (check_for_jobs,
                                 path="/com/redhat/PrinterSpooler",
                                 dbus_interface="com.redhat.PrinterSpooler")
        loop = gobject.MainLoop ()
        loop.run()
        bus.remove_signal_receiver (check_for_jobs,
                                    path="/com/redhat/PrinterSpooler",
                                    dbus_interface="com.redhat.PrinterSpooler")

do_imports()
loop = gobject.MainLoop ()
JobManager(bus, loop, service_running=service_running, trayicon=trayicon)
loop.run()

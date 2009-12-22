#!/usr/bin/env python

## Copyright (C) 2007, 2008, 2009 Tim Waugh <twaugh@redhat.com>
## Copyright (C) 2007, 2008, 2009 Red Hat, Inc.

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
cups.require ("1.9.42")
import sys
import statereason
from statereason import StateReason
from debug import *

import dbus
import dbus.glib
import dbus.service
import gobject
import pynotify
import time
import locale
import gettext
from gettext import gettext as _
DOMAIN="system-config-printer"
gettext.textdomain (DOMAIN)
statereason.set_gettext_function (_)
try:
    locale.setlocale (locale.LC_ALL, "")
except locale.Error, e:
    import os
    os.environ['LC_ALL'] = 'C'
    locale.setlocale (locale.LC_ALL, "")

APPDIR="/usr/share/system-config-printer"
DOMAIN="system-config-printer"
ICON="printer"
SEARCHING_ICON="document-print-preview"

# Let gobject know we'll be using threads.
gobject.threads_init ()

# We need to call pynotify.init before we can check the server for caps
pynotify.init('System Config Printer Notification')

####
#### NewPrinterNotification DBus server (the 'new' way).
####
PDS_PATH="/com/redhat/NewPrinterNotification"
PDS_IFACE="com.redhat.NewPrinterNotification"
PDS_OBJ="com.redhat.NewPrinterNotification"
class NewPrinterNotification(dbus.service.Object):
    STATUS_SUCCESS = 0
    STATUS_MODEL_MISMATCH = 1
    STATUS_GENERIC_DRIVER = 2
    STATUS_NO_DRIVER = 3

    def __init__ (self, bus):
        self.bus = bus
        self.getting_ready = 0
        bus_name = dbus.service.BusName (PDS_OBJ, bus=bus)
        dbus.service.Object.__init__ (self, bus_name, PDS_PATH)

    def wake_up (self):
        global waitloop, runloop, viewer
        import jobviewer
        if viewer == None:
            try:
                waitloop.quit ()
            except:
                pass
            runloop = gobject.MainLoop ()
            viewer = jobviewer.JobViewer(bus=bus, loop=runloop,
                                         service_running=service_running,
                                         trayicon=trayicon,
                                         suppress_icon_hide=True)

    @dbus.service.method(PDS_IFACE, in_signature='', out_signature='')
    def GetReady (self):
        self.wake_up ()
        if self.getting_ready == 0:
            viewer.set_special_statusicon (SEARCHING_ICON,
                                           tooltip=_("Configuring new printer"))

        self.getting_ready += 1
        gobject.timeout_add_seconds (60, self.timeout_ready)

    def timeout_ready (self):
        global viewer
        if self.getting_ready > 0:
            self.getting_ready -= 1
        if self.getting_ready == 0:
            viewer.unset_special_statusicon ()

        return False

    @dbus.service.method(PDS_IFACE, in_signature='isssss', out_signature='')
    def NewPrinter (self, status, name, mfg, mdl, des, cmd):
        global viewer
        self.wake_up ()

        if name.find("/") >= 0:
            # name is a URI, no queue was generated, because no suitable
            # driver was found
            title = _("Missing printer driver")
            devid = "MFG:%s;MDL:%s;DES:%s;CMD:%s;" % (mfg, mdl, des, cmd)
            if (mfg and mdl) or des:
                if (mfg and mdl):
                    device = "%s %s" % (mfg, mdl)
                else:
                    device = des
                text = _("No printer driver for %s.") % device
            else:
                text = _("No driver for this printer.")
            n = pynotify.Notification (title, text, 'printer')
            if "actions" in pynotify.get_server_caps():
                n.set_urgency (pynotify.URGENCY_CRITICAL)
                n.add_action ("setup-printer", _("Search"),
                              lambda x, y:
                                  self.setup_printer (x, y, name, devid))
            else:
                args = ["--setup-printer", name, "--devid", devid]
                self.run_config_tool (args)

        else:
            # name is the name of the queue which hal_lpadmin has set up
            # automatically.
            c = cups.Connection ()
            try:
                printer = c.getPrinters ()[name]
            except KeyError:
                return

            try:
                filename = c.getPPD (name)
            except cups.IPPError:
                return

            del c

            # Check for missing packages
            try:
                cups.ppdSetConformance (cups.PPD_CONFORM_RELAXED)
            except AttributeError:
                # Requires pycups 1.9.46
                pass

            ppd = cups.PPD (filename)
            import os
            os.unlink (filename)
            import sys
            sys.path.append (APPDIR)
            import cupshelpers
            (missing_pkgs,
             missing_exes) = cupshelpers.missingPackagesAndExecutables (ppd)

            from cupshelpers.ppds import ppdMakeModelSplit
            (make, model) = ppdMakeModelSplit (printer['printer-make-and-model'])
            driver = make + " " + model
            if status < self.STATUS_GENERIC_DRIVER:
                title = _("Printer added")
            else:
                title = _("Missing printer driver")

            if len (missing_pkgs) > 0:
                pkgs = reduce (lambda x,y: x + ", " + y, missing_pkgs)
                title = _("Install printer driver")
                text = _("`%s' requires driver installation: %s.") % (name, pkgs)
                n = pynotify.Notification (title, text)
                import installpackage
                if "actions" in pynotify.get_server_caps():
                    try:
                        self.packagekit = installpackage.PackageKit ()
                        n.add_action ("install-driver", _("Install"),
                                      lambda x, y:
                                          self.install_driver (x, y,
                                                               missing_pkgs))
                    except:
                        pass
                else:
                    try:
                        self.packagekit = installpackage.PackageKit ()
                        self.packagekit.InstallPackageName (0, 0,
                                                            missing_pkgs[0])
                    except:
                        pass

            elif status == self.STATUS_SUCCESS:
                devid = "MFG:%s;MDL:%s;DES:%s;CMD:%s;" % (mfg, mdl, des, cmd)
                text = _("`%s' is ready for printing.") % name
                n = pynotify.Notification (title, text)
                if "actions" in pynotify.get_server_caps():
                    n.set_urgency (pynotify.URGENCY_NORMAL)
                    n.add_action ("test-page", _("Print test page"),
                                  lambda x, y:
                                      self.print_test_page (x, y, name, devid))
                    n.add_action ("configure", _("Configure"),
                                  lambda x, y: self.configure (x, y, name))
            else: # Model mismatch
                devid = "MFG:%s;MDL:%s;DES:%s;CMD:%s;" % (mfg, mdl, des, cmd)
                text = (_("`%s' has been added, using the `%s' driver.") %
                        (name, driver))
                n = pynotify.Notification (title, text, 'printer')
                if "actions" in pynotify.get_server_caps():
                    n.set_urgency (pynotify.URGENCY_CRITICAL)
                    n.add_action ("test-page", _("Print test page"),
                                  lambda x, y:
                                      self.print_test_page (x, y, name, devid))
                    n.add_action ("find-driver", _("Find driver"),
                                  lambda x, y: 
                                  self.find_driver (x, y, name, devid))
                    n.set_timeout (pynotify.EXPIRES_NEVER)
                else:
                    self.run_config_tool (["--configure-printer",
                                           name, "--no-focus-on-map"])

        viewer.notify_new_printer (name, n)
        # Set the icon back how it was.
        self.timeout_ready ()

    def run_config_tool (self, argv):
        import os
        pid = os.fork ()
        if pid == 0:
            # Child.
            cmd = "/usr/bin/system-config-printer"
            argv.insert (0, cmd)
            os.execvp (cmd, argv)
            sys.exit (1)
        elif pid == -1:
            print "Error forking process"
        else:
            gobject.timeout_add_seconds (60, self.collect_exit_code, pid)

    def print_test_page (self, notification, action, name, devid = ""):
        args = ["--print-test-page", name]
        if devid != "":
            args.extend (["--devid", devid])
        self.run_config_tool (args)

    def configure (self, notification, action, name):
        self.run_config_tool (["--configure-printer", name])

    def find_driver (self, notification, action, name, devid = ""):
        args = ["--choose-driver", name]
        if devid != "": args = args + ["--devid", devid]
        self.run_config_tool (args)

    def setup_printer (self, notification, action, uri, devid = ""):
        args = ["--setup-printer", uri]
        if devid != "": args = args + ["--devid", devid]
        self.run_config_tool (args)

    def install_driver (self, notification, action, missing_pkgs):
        try:
            self.packagekit.InstallPackageName (0, 0, missing_pkgs[0])
        except:
            pass

    def collect_exit_code (self, pid):
        # We do this with timers instead of signals because we already
        # have gobject imported, but don't (yet) import signal;
        # let's try not to inflate the process size.
        import os
        try:
            print "Waiting for child %d" % pid
            (pid, status) = os.waitpid (pid, os.WNOHANG)
            if pid == 0:
                # Run this timer again.
                return True
        except OSError:
            pass

        return False

PROGRAM_NAME="system-config-printer-applet"
def show_help ():
    print "usage: %s [--no-tray-icon]" % PROGRAM_NAME

def show_version ():
    import config
    print "%s %s" % (PROGRAM_NAME, config.VERSION)
    
####
#### Main program entry
####

global waitloop, runloop, viewer

trayicon = True
service_running = False
waitloop = runloop = None
viewer = None

if __name__ == '__main__':
    import sys, getopt
    try:
        opts, args = getopt.gnu_getopt (sys.argv[1:], '',
                                        ['no-tray-icon',
                                         'debug',
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
        elif opt == "--debug":
            set_debugging (True)

    # Must be done before connecting to D-Bus (for some reason).
    if not pynotify.init (PROGRAM_NAME):
        try:
            print >> sys.stderr, ("%s: unable to initialize pynotify" %
                                  PROGRAM_NAME)
        except:
            pass

    if trayicon:
        # Stop running when the session ends.
        def monitor_session (*args):
            pass

        try:
            bus = dbus.SessionBus()
            bus.add_signal_receiver (monitor_session)
        except:
            try:
                print >> sys.stderr, ("%s: failed to connect to "
                                      "session D-Bus" % PROGRAM_NAME)
            finally:
                sys.exit (1)

    try:
        bus = dbus.SystemBus()
    except:
        try:
            print >> sys.stderr, ("%s: failed to connect to system D-Bus" %
                                  PROGRAM_NAME)
        finally:
            sys.exit (1)

    if trayicon:
        try:
            NewPrinterNotification(bus)
            service_running = True
        except:
            try:
                print >> sys.stderr, ("%s: failed to start "
                                      "NewPrinterNotification service" %
                                      PROGRAM_NAME)
            except:
                pass

    if trayicon and get_debugging () == False:
        # Start off just waiting for print jobs.
        def any_jobs ():
            try:
                c = cups.Connection ()
                jobs = c.getJobs (my_jobs=True, limit=1)
                if len (jobs):
                    return True
            except:
                pass

            return False

        if not any_jobs ():

            ###
            class WaitForJobs:
                DBUS_PATH="/com/redhat/PrinterSpooler"
                DBUS_IFACE="com.redhat.PrinterSpooler"

                def __init__ (self, bus, waitloop):
                    self.bus = bus
                    self.waitloop = waitloop
                    self.timer = None
                    bus.add_signal_receiver (self.handle_dbus_signal,
                                             path=self.DBUS_PATH,
                                             dbus_interface=self.DBUS_IFACE)

                def __del__ (self):
                    bus = self.bus
                    bus.remove_signal_receiver (self.handle_dbus_signal,
                                                path=self.DBUS_PATH,
                                                dbus_interface=self.DBUS_IFACE)
                    if self.timer:
                        gobject.source_remove (self.timer)

                def handle_dbus_signal (self, *args):
                    if self.timer:
                        gobject.source_remove (self.timer)
                    self.timer = gobject.timeout_add (200, self.check_for_jobs)

                def check_for_jobs (self, *args):
                    debugprint ("checking for jobs")
                    if any_jobs ():
                        gobject.source_remove (self.timer)
                        self.waitloop.quit ()

                    # Don't run this timer again.
                    return False
            ###

            waitloop = gobject.MainLoop ()
            jobwaiter = WaitForJobs(bus, waitloop)
            waitloop.run()
            del jobwaiter
            waitloop = None

    if viewer == None:
        import jobviewer
        import gtk
        runloop = gobject.MainLoop ()
        gtk.window_set_default_icon_name ('printer')
        viewer = jobviewer.JobViewer(bus=bus, loop=runloop,
                                     service_running=service_running,
                                     trayicon=trayicon)

    try:
        runloop.run()
    except KeyboardInterrupt:
        pass
    viewer.cleanup ()

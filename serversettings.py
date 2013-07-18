#!/usr/bin/python

## system-config-printer

## Copyright (C) 2008, 2009, 2010, 2011, 2012, 2013 Red Hat, Inc.
## Authors:
##  Tim Waugh <twaugh@redhat.com>

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

import config
import gettext
gettext.install(domain=config.PACKAGE, localedir=config.localedir, unicode=True)
import cups
import dbus
from gi.repository import GObject
from gi.repository import Gtk
import os
import socket
import tempfile
import time

import authconn
from debug import *
from errordialogs import *
import firewallsettings
from gui import GtkGUI

try:
    try_CUPS_SERVER_REMOTE_ANY = cups.CUPS_SERVER_REMOTE_ANY
except AttributeError:
    # cups module was compiled with CUPS < 1.3
    try_CUPS_SERVER_REMOTE_ANY = "_remote_any"

# Set up "Problems?" link button
class _UnobtrusiveButton(Gtk.Button):
    def __init__ (self, **args):
        Gtk.Button.__init__ (self, **args)
        self.set_relief (Gtk.ReliefStyle.NONE)
        label = self.get_child ()
        text = label.get_text ()
        label.set_use_markup (True)
        label.set_markup ('<span size="small" ' +
                          'underline="single" ' +
                          'color="#0000ee">%s</span>' % text)

class ServerSettings(GtkGUI):

    __gsignals__ = {
        'settings-applied': (GObject.SignalFlags.RUN_LAST, None, ()),
        'dialog-canceled': (GObject.SignalFlags.RUN_LAST, None, ()),
        'problems-clicked': (GObject.SignalFlags.RUN_LAST, None, ()),
        }

    RESOURCE="/admin/conf/cupsd.conf"

    def __init__ (self, host=None, encryption=None, parent=None):
        GObject.GObject.__init__ (self)
        self.cupsconn = authconn.Connection (host=host, encryption=encryption)
        self._host = host
        self._parent = parent
        self.getWidgets({"ServerSettingsDialog":
                             ["ServerSettingsDialog",
                              "chkServerBrowse",
                              "chkServerShare",
                              "chkServerShareAny",
                              "chkServerRemoteAdmin",
                              "chkServerAllowCancelAll",
                              "chkServerLogDebug",
                              "hboxServerBrowse",
                              "rbPreserveJobFiles",
                              "rbPreserveJobHistory",
                              "rbPreserveJobNone",
                              "tvBrowseServers",
                              "frameBrowseServers",
                              "btAdvServerAdd",
                              "btAdvServerRemove"]},

                        domain=config.PACKAGE)

        problems = _UnobtrusiveButton (label=_("Problems?"))
        self.hboxServerBrowse.pack_end (problems, False, False, 0)
        problems.connect ('clicked', self.problems_clicked)
        problems.show ()

        self.ServerSettingsDialog.connect ('response', self.on_response)

        # Signal handler IDs.
        self.handler_ids = {}

        self.dialog = self.ServerSettingsDialog
        self.browse_treeview = self.tvBrowseServers
        self.add = self.btAdvServerAdd
        self.remove = self.btAdvServerRemove

        selection = self.browse_treeview.get_selection ()
        selection.set_mode (Gtk.SelectionMode.MULTIPLE)
        self._connect (selection, 'changed', self.on_treeview_selection_changed)

        for column in self.browse_treeview.get_columns():
            self.browse_treeview.remove_column(column)
        col = Gtk.TreeViewColumn ('', Gtk.CellRendererText (), text=0)
        self.browse_treeview.append_column (col)

        self._fillAdvanced ()
        self._fillBasic ()

        if parent:
            self.dialog.set_transient_for (parent)

        self.connect_signals ()
        self.dialog.show ()

    def get_dialog (self):
        return self.dialog

    def problems_clicked (self, button):
        self.emit ('problems-clicked')

    def _fillAdvanced(self):
        # Fetch cupsd.conf
        f = tempfile.TemporaryFile ()
        try:
            self.cupsconn.getFile (self.RESOURCE, file=f)
        except cups.HTTPError as e:
            (s,) = e.args
            show_HTTP_Error (s, self._parent)
            raise

        def parse_yesno (line):
            arg1 = line.split (' ')[1].strip ()
            if arg1 in ['true', 'on', 'enabled', 'yes']:
                return True
            if arg1 in ['false', 'off', 'disabled', 'no', '0']:
                return False
            try:
                if int (arg1) != 0:
                    return True
            except:
                pass
            raise RuntimeError

        preserve_job_history = True
        preserve_job_files = False
        browsing = True
        self.browse_poll = []
        f.seek (0)
        for line in f.readlines ():
            l = line.lower ().strip ()
            if l.startswith ("preservejobhistory "):
                try:
                    preserve_job_history = parse_yesno (l)
                except:
                    pass
            elif l.startswith ("preservejobfiles "):
                try:
                    preserve_job_files = parse_yesno (l)
                except:
                    pass
            elif l.startswith ("browsing "):
                try:
                    browsing = parse_yesno (l)
                except:
                    pass
            elif l.startswith ("browsepoll "):
                self.browse_poll.append (line[len ("browsepoll "):].strip ())

        self.frameBrowseServers.set_sensitive (browsing)

        if preserve_job_files:
            self.rbPreserveJobFiles.set_active (True)
        elif preserve_job_history:
            self.rbPreserveJobHistory.set_active (True)
        else:
            self.rbPreserveJobNone.set_active (True)

        self.preserve_job_history = preserve_job_history
        self.preserve_job_files = preserve_job_files

        model = Gtk.ListStore (str)
        self.browse_treeview.set_model (model)
        for server in self.browse_poll:
            model.append (row=[server])

    def _fillBasic(self):
        self.changed = set()
        self.cupsconn._begin_operation (_("fetching server settings"))
        try:
            self.server_settings = self.cupsconn.adminGetServerSettings()
        except cups.IPPError as e:
            (e, m) = e.args
            show_IPP_Error(e, m, self._parent)
            self.cupsconn._end_operation ()
            raise

        self.cupsconn._end_operation ()

        for widget, setting in [
            (self.chkServerBrowse, cups.CUPS_SERVER_REMOTE_PRINTERS),
            (self.chkServerShare, cups.CUPS_SERVER_SHARE_PRINTERS),
            (self.chkServerShareAny, try_CUPS_SERVER_REMOTE_ANY),
            (self.chkServerRemoteAdmin, cups.CUPS_SERVER_REMOTE_ADMIN),
            (self.chkServerAllowCancelAll, cups.CUPS_SERVER_USER_CANCEL_ANY),
            (self.chkServerLogDebug, cups.CUPS_SERVER_DEBUG_LOGGING),]:
            widget.setting = setting
            if self.server_settings.has_key(setting):
                widget.set_active(int(self.server_settings[setting]))
                widget.set_sensitive(True)
                widget.show()
            else:
                widget.set_active(False)
                widget.set_sensitive(False)
                widget.hide()

        if self.server_settings.has_key(cups.CUPS_SERVER_REMOTE_PRINTERS):
            self.frameBrowseServers.show()
        else:
            self.frameBrowseServers.hide()

        try:
            flag = cups.CUPS_SERVER_SHARE_PRINTERS
            publishing = int (self.server_settings[flag])
            self.server_is_publishing = publishing
        except AttributeError:
            pass

        # Set sensitivity of 'Allow printing from the Internet'.
        self.on_server_changed (self.chkServerShare) # (any will do here)

    def on_server_changed(self, widget):
        debugprint ("on_server_changed: %s" % widget)
        setting = widget.setting
        if self.server_settings.has_key (setting):
            if str(int(widget.get_active())) == self.server_settings[setting]:
                self.changed.discard(widget)
            else:
                self.changed.add(widget)

        sharing = self.chkServerShare.get_active ()
        self.chkServerShareAny.set_sensitive (
            sharing and self.server_settings.has_key(try_CUPS_SERVER_REMOTE_ANY))

    def _connect (self, widget, signal, handler, reason=None):
        id = widget.connect (signal, handler)
        if not self.handler_ids.has_key (reason):
            self.handler_ids[reason] = []
        self.handler_ids[reason].append ((widget, id))

    def _disconnect (self, reason=None):
        if self.handler_ids.has_key (reason):
            for (widget, id) in self.handler_ids[reason]:
                widget.disconnect (id)
            del self.handler_ids[reason]

    def on_treeview_selection_changed (self, selection):
        self.remove.set_sensitive (selection.count_selected_rows () != 0)

    def on_add_clicked (self, button):
        model = self.browse_treeview.get_model ()
        iter = model.insert (0, row=[_("Enter hostname")])
        button.set_sensitive (False)
        col = self.browse_treeview.get_columns ()[0]
        cell = col.get_cells ()[0]
        cell.set_property ('editable', True)
        self.browse_treeview.set_cursor (Gtk.TreePath(), col, True)
        self._connect (cell, 'edited', self.on_browse_poll_edited, 'edit')
        self._connect (cell, 'editing-canceled',
                       self.on_browse_poll_edit_cancel, 'edit')

    def on_browse_poll_edited (self, cell, path, newvalue):
        model = self.browse_treeview.get_model ()
        iter = model.get_iter (path)
        model.set_value (iter, 0, newvalue)
        cell.stop_editing (False)
        cell.set_property ('editable', False)
        self.add.set_sensitive (True)
        self._disconnect ('edit')

        valid = True
        # Check that it's a valid IP address or hostname.
        # First, is it an IP address?
        try:
            socket.getaddrinfo (newvalue, '0', socket.AF_UNSPEC, 0, 0,
                                socket.AI_NUMERICHOST)
        except socket.gaierror:
            # No.  Perhaps it's a hostname.
            labels = newvalue.split (".")
            seen_alpha = False
            for label in labels:
                if (label[0] == '-' or
                    label.endswith ('-')):
                    valid = False
                    break
                for char in label:
                    if not seen_alpha:
                        if char.isalpha ():
                            seen_alpha = True

                    if not (char.isalpha () or
                            char.isdigit () or
                            char == '-'):
                        valid = False
                        break

                if not valid:
                    break

            if valid and not seen_alpha:
                valid = False

        if valid:
            count = 0
            i = model.get_iter_first ()
            while i:
                if model.get_value (i, 0) == newvalue:
                    count += 1
                    if count == 2:
                        valid = False
                        selection = self.browse_treeview.get_selection ()
                        selection.select_iter (i)
                        break
                i = model.iter_next (i)
        else:
            model.remove (iter)

    def on_browse_poll_edit_cancel (self, cell):
        cell.stop_editing (True)
        cell.set_property ('editable', False)
        model = self.browse_treeview.get_model ()
        iter = model.get_iter (Gtk.TreePath())
        model.remove (iter)
        self.add.set_sensitive (True)
        self.remove.set_sensitive (False)
        self._disconnect ('edit')

    def on_remove_clicked (self, button):
        model = self.browse_treeview.get_model ()
        selection = self.browse_treeview.get_selection ()
        rows = selection.get_selected_rows ()
        refs = map (lambda path: Gtk.TreeRowReference.new (model, path),
                    rows[1])
        for ref in refs:
            path = ref.get_path ()
            iter = model.get_iter (path)
            model.remove (iter)

    def on_response (self, dialog, response):
        if (response == Gtk.ResponseType.CANCEL or
            response != Gtk.ResponseType.OK):
            self._disconnect ()
            self.dialog.hide ()
            self.emit ('dialog-canceled')
            del self
            return

        self.saveBasic ()
        self.saveAdvanced ()

    def _reconnect (self):
        # Now reconnect, in case the server needed to reload.
        try:
            attempt = 1
            while attempt <= 5:
                try:
                    self.cupsconn._connect ()
                    break
                except RuntimeError:
                    # Connection failed.
                    time.sleep (1)
                    attempt += 1
        except AttributeError:
            # _connect method is part of the authconn.Connection
            # interface, so don't fail if that method doesn't exist.
            pass

    def saveAdvanced (self):
        # See if there are changes.
        preserve_job_files = self.rbPreserveJobFiles.get_active ()
        preserve_job_history = (preserve_job_files or
                                self.rbPreserveJobHistory.get_active ())
        model = self.browse_treeview.get_model ()
        browse_poll = []
        iter = model.get_iter_first ()
        while iter:
            browse_poll.append (model.get_value (iter, 0))
            iter = model.iter_next (iter)

        if (set (browse_poll) == set (self.browse_poll) and
            preserve_job_files == self.preserve_job_files and
            preserve_job_history == self.preserve_job_history):
            self._disconnect ()
            self.dialog.hide ()
            self.emit ('settings-applied')
            del self
            return

        # Fetch cupsd.conf afresh
        f = tempfile.TemporaryFile ()
        try:
            self.cupsconn.getFile (self.RESOURCE, file=f)
        except cups.HTTPError as e:
            (s,) = e.args
            show_HTTP_Error (s, self.dialog)
            return

        job_history_line = job_files_line = browsepoll_lines = ""

        # Default is to preserve job history
        if not preserve_job_history:
            job_history_line = "PreserveJobHistory No\n"

        # Default is not to preserve job files.
        if preserve_job_files:
            job_files_line = "PreserveJobFiles Yes\n"

        for server in browse_poll:
            browsepoll_lines += "BrowsePoll %s\n" % server

        f.seek (0)
        conf = tempfile.TemporaryFile ()
        wrote_preserve_history = wrote_preserve_files = False
        wrote_browsepoll = False
        has_browsepoll = False
        lines = f.readlines ()
        for line in lines:
            l = line.lower ().strip ()
            if l.startswith ("browsepoll "):
                has_browsepoll = True
                break

        for line in lines:
            l = line.lower ().strip ()
            if l.startswith ("preservejobhistory "):
                if wrote_preserve_history:
                    # Don't write out another line with this keyword.
                    continue
                # Alter this line before writing it out.
                line = job_history_line
                wrote_preserve_history = True
            elif l.startswith ("preservejobfiles "):
                if wrote_preserve_files:
                    # Don't write out another line with this keyword.
                    continue
                # Alter this line before writing it out.
                line = job_files_line
                wrote_preserve_files = True
            elif (has_browsepoll and
                  l.startswith ("browsepoll ")):
                if wrote_browsepoll:
                    # Ignore extra BrowsePoll lines.
                    continue
                # Write new BrowsePoll section.
                conf.write (browsepoll_lines)
                wrote_browsepoll = True
                # Don't write out the original BrowsePoll line.
                continue
            elif (not has_browsepoll and
                  l.startswith ("browsing ")):
                if not wrote_browsepoll:
                    # Write original Browsing line.
                    conf.write (line)
                    # Write new BrowsePoll section.
                    conf.write (browsepoll_lines)
                    wrote_browsepoll = True
                    continue

            conf.write (line)

        if not wrote_preserve_history:
            conf.write (job_history_line)
        if not wrote_preserve_files:
            conf.write (job_files_line)
        if not wrote_browsepoll:
            conf.write (browsepoll_lines)

        conf.flush ()
        fd = conf.fileno ()
        os.lseek (fd, 0, os.SEEK_SET)
        try:
            self.cupsconn.putFile ("/admin/conf/cupsd.conf", fd=fd)
        except cups.HTTPError as e:
            (s,) = e.args
            show_HTTP_Error (s, self.dialog)
            return

        # Give the server a chance to process our request.
        time.sleep (1)

        self._reconnect ()

        self._disconnect ()
        self.emit ('settings-applied')
        self.dialog.hide ()
        del self

    def saveBasic (self):
        setting_dict = dict()
        for widget, setting in [
            (self.chkServerBrowse, cups.CUPS_SERVER_REMOTE_PRINTERS),
            (self.chkServerShare, cups.CUPS_SERVER_SHARE_PRINTERS),
            (self.chkServerShareAny, try_CUPS_SERVER_REMOTE_ANY),
            (self.chkServerRemoteAdmin, cups.CUPS_SERVER_REMOTE_ADMIN),
            (self.chkServerAllowCancelAll, cups.CUPS_SERVER_USER_CANCEL_ANY),
            (self.chkServerLogDebug, cups.CUPS_SERVER_DEBUG_LOGGING),]:
            if not self.server_settings.has_key(setting): continue
            setting_dict[setting] = str(int(widget.get_active()))
        self.cupsconn._begin_operation (_("modifying server settings"))
        try:
            self.cupsconn.adminSetServerSettings(setting_dict)
        except cups.IPPError as e:
            (e, m) = e.args
            show_IPP_Error(e, m, self.dialog)
            self.cupsconn._end_operation ()
            return True
        except RuntimeError as s:
            show_IPP_Error(None, s, self.dialog)
            self.cupsconn._end_operation ()
            return True
        self.cupsconn._end_operation ()
        self.changed = set()

        old_setting = self.server_settings.get (cups.CUPS_SERVER_SHARE_PRINTERS,
                                                '0')
        new_setting = setting_dict.get (cups.CUPS_SERVER_SHARE_PRINTERS, '0')
        if (old_setting == '0' and new_setting != '0'):
            # We have just enabled print queue sharing.
            # Let's see if the firewall will allow IPP TCP packets in.
            try:
                if (self._host == 'localhost' or
                    self._host[0] == '/'):
                    f = firewallsettings.FirewallD ()
                    if not f.running:
                        f = firewallsettings.SystemConfigFirewall ()

                    allowed = f.check_ipp_server_allowed ()
                else:
                    # This is a remote server.  Nothing we can do
                    # about the firewall there.
                    allowed = True

                if not allowed:
                    dialog = Gtk.MessageDialog (self.ServerSettingsDialog,
                                                Gtk.DialogFlags.MODAL |
                                                Gtk.DialogFlags.DESTROY_WITH_PARENT,
                                                Gtk.MessageType.QUESTION,
                                                Gtk.ButtonsType.NONE,
                                                _("Adjust Firewall"))
                    dialog.format_secondary_text (_("Adjust the firewall now "
                                                    "to allow all incoming IPP "
                                                    "connections?"))
                    dialog.add_buttons (Gtk.STOCK_CANCEL, Gtk.ResponseType.NO,
                                        _("Adjust Firewall"), Gtk.ResponseType.YES)
                    response = dialog.run ()
                    dialog.destroy ()

                    if response == Gtk.ResponseType.YES:
                        f.add_service (firewallsettings.IPP_SERVER_SERVICE)
                        f.write ()
            except (dbus.DBusException, Exception):
                nonfatalException ()

        time.sleep(1) # give the server a chance to process our request

        # Now reconnect, in case the server needed to reload.
        self._reconnect ()

if __name__ == '__main__':
    os.environ['SYSTEM_CONFIG_PRINTER_UI'] = 'ui'
    loop = GObject.MainLoop ()

    def quit (*args):
        loop.quit ()

    def problems (obj):
        print "%s: problems" % obj

    set_debugging (True)
    s = ServerSettings ()
    s.connect ('dialog-canceled', quit)
    s.connect ('settings-applied', quit)
    s.connect ('problems-clicked', problems)
    loop.run ()

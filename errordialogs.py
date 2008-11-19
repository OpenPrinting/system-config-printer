#!/usr/bin/env python

## system-config-printer

## Copyright (C) 2006, 2007, 2008 Red Hat, Inc.
## Copyright (C) 2006, 2007 Florian Festi <ffesti@redhat.com>
## Copyright (C) 2006, 2007, 2008 Tim Waugh <twaugh@redhat.com>

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
import gtk

_ = lambda x: x
def set_gettext_function (fn):
    global _
    _ = fn

def show_dialog (title, text, type, parent=None):
    dialog = gtk.MessageDialog (parent,
                                gtk.DIALOG_MODAL |
                                gtk.DIALOG_DESTROY_WITH_PARENT,
                                type,
                                gtk.BUTTONS_OK,
                                title)
    dialog.format_secondary_text (text)
    dialog.run ()
    dialog.destroy ()

def show_info_dialog (title, text, parent=None):
    return show_dialog (title, text, gtk.MESSAGE_INFO, parent=parent)

def show_error_dialog (title, text, parent=None):
    return show_dialog (title, text, gtk.MESSAGE_ERROR, parent=parent)

def show_IPP_Error(exception, message, parent=None):
    if exception == 0:
        # In this case, the user has canceled an authentication dialog.
        return
    elif exception == cups.IPP_SERVICE_UNAVAILABLE:
        # In this case, the user has canceled a retry dialog.
        return
    else:
        title = _("CUPS server error")
        text = (_("There was an error during the CUPS "
                  "operation: '%s'.")) % message

    show_error_dialog (title, text, parent)

def show_HTTP_Error(status, parent=None):
    if (status == cups.HTTP_UNAUTHORIZED or
        status == cups.HTTP_FORBIDDEN):
        title = _('Not authorized')
        text = (_('The password may be incorrect, or the '
                  'server may be configured to deny '
                  'remote administration.'))
    else:
        title = _('CUPS server error')
        if status == cups.HTTP_BAD_REQUEST:
            msg = _("Bad request")
        elif status == cups.HTTP_NOT_FOUND:
            msg = _("Not found")
        elif status == cups.HTTP_REQUEST_TIMEOUT:
            msg = _("Request timeout")
        elif status == cups.HTTP_UPGRADE_REQUIRED:
            msg = _("Upgrade required")
        elif status == cups.HTTP_SERVER_ERROR:
            msg = _("Server error")
        elif status == -1:
            msg = _("Not connected")
        else:
            msg = _("status %s") % status

        text = _("There was an HTTP error: %s.") % msg

    show_error_dialog (title, text, parent)

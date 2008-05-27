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

def show_error_dialog (title, text, parent=None):
    dialog = gtk.Dialog (title, parent,
                         gtk.DIALOG_MODAL |
                         gtk.DIALOG_DESTROY_WITH_PARENT,
                         (gtk.STOCK_CLOSE, gtk.RESPONSE_OK))
    dialog.set_default_response (gtk.RESPONSE_OK)
    dialog.set_border_width (6)
    dialog.set_resizable (False)
    hbox = gtk.HBox (False, 12)
    hbox.set_border_width (6)
    image = gtk.Image ()
    image.set_from_stock ('gtk-dialog-error', gtk.ICON_SIZE_DIALOG)
    image.set_alignment (0.0, 0.0)
    hbox.pack_start (image, False, False, 0)
    label = gtk.Label ()
    label.set_markup ('<span weight="bold" size="larger">' + title +
                      '</span>\n\n' + text)
    label.set_use_markup (True)
    label.set_alignment (0, 0)
    label.set_line_wrap (True)
    hbox.pack_start (label, False, False, 0)
    dialog.vbox.pack_start (hbox, False, False, 0)
    dialog.show_all ()
    dialog.run ()
    dialog.hide ()

def show_IPP_Error(exception, message, parent=None):
    if exception == cups.IPP_NOT_AUTHORIZED:
        title = _('Not authorized')
        text = _('The password may be incorrect.')
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
            msg = _("status %d") % status

        text = _("There was an HTTP error: %s.") % msg

    show_error_dialog (title, text, parent)

## This code was translated to python from the original C version in
## Rhythmbox. The original authors are:

## Copyright (C) 2002 Jorn Baayen <jorn@nl.linux.org>
## Copyright (C) 2003 Colin Walters <walters@verbum.org>

## Further modifications by:

## Copyright (C) 2008 Rui Matos <tiagomatos@gmail.com>

## Copyright (C) 2009 Red Hat, Inc.
## Author: Tim Waugh <twaugh@redhat.com>

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

import gobject
import gtk
import HIG
from gettext import gettext as _

class ToolbarSearchEntry (gtk.HBox):
    __gproperties__ = {
        'search_timeout' : (gobject.TYPE_UINT,
                            'search timeout',
                            'search signal rate limiter (in ms)',
                            0,
                            5000,
                            300,
                            gobject.PARAM_READWRITE)
        }

    __gsignals__ = {
        'search' : (gobject.SIGNAL_RUN_LAST,
                    gobject.TYPE_NONE,
                    [ gobject.TYPE_STRING ]),
        'activate' : (gobject.SIGNAL_RUN_LAST,
                      gobject.TYPE_NONE,
                      [])
        }

    def __init__ (self):
        self.entry = None
        self.timeout = 0
        self.is_a11y_theme = False
        self.search_timeout = 300
        self.menu = None

        gtk.HBox.__gobject_init__ (self)
        self.set_spacing (HIG.PAD_NORMAL)
        self.set_border_width (HIG.PAD_NORMAL)

        settings = gtk.settings_get_for_screen (self.get_screen ())
        theme = settings.get_property ('gtk-theme-name')
        self.is_a11y_theme = theme == 'HighContrast' or theme == 'LowContrast'

        label = gtk.Label ()
        label.set_text_with_mnemonic (_("_Filter:"))
        label.set_justify (gtk.JUSTIFY_RIGHT)
        self.pack_start (label, False, True, 0)

        self.entry = gtk.Entry()
        if gtk.__dict__.has_key ('ENTRY_ICON_PRIMARY'):
            # We have primary/secondary icon support.
            self.entry.set_icon_from_stock (gtk.ENTRY_ICON_PRIMARY,
                                            gtk.STOCK_FIND)
            self.entry.set_icon_from_stock (gtk.ENTRY_ICON_SECONDARY,
                                            gtk.STOCK_CLEAR)

            self.entry.set_icon_sensitive (gtk.ENTRY_ICON_SECONDARY, False)
            self.entry.set_icon_activatable (gtk.ENTRY_ICON_SECONDARY, False)
            self.entry.connect ('icon-press', self.on_icon_press)

        label.set_mnemonic_widget (self.entry)

        self.pack_start (self.entry, True, True, 0)

        self.entry.connect ('changed', self.on_changed)
        self.entry.connect ('focus_out_event', self.on_focus_out_event)
        self.entry.connect ('activate', self.on_activate)

    def do_get_property (self, property):
        if property.name == 'search_timeout':
            return self.search_timeout
        else:
            raise AttributeError, 'unknown property %s' % property.name

    def do_set_property (self, property, value):
        if property.name == 'search_timeout':
            self.search_timeout = value
        else:
            raise AttributeError, 'unknown property %s' % property.name

    def clear (self):
        if self.timeout != 0:
            gobject.source_remove (self.timeout)
            self.timeout = 0

        self.entry.set_text ("")

    def get_text (self):
        return self.entry.get_text ()

    def set_text (self, text):
        self.entry.set_text (text)

    def check_style (self):
        if self.is_a11y_theme:
            return

        bg_colour = gtk.gdk.color_parse ('#f7f7be') # yellow-ish
        fg_colour = gtk.gdk.color_parse ('#000000') # black

        text = self.entry.get_text ()
        if len (text) > 0:
            self.entry.modify_text (gtk.STATE_NORMAL, fg_colour)
            self.entry.modify_base (gtk.STATE_NORMAL, bg_colour)
        else:
            self.entry.modify_text (gtk.STATE_NORMAL, None)
            self.entry.modify_base (gtk.STATE_NORMAL, None)

        self.queue_draw ()

    def on_changed (self, UNUSED):
        self.check_style ()

        if self.timeout != 0:
            gobject.source_remove (self.timeout)
            self.timeout = 0

       	# emit it now if we have no more text
        has_text = self.entry.get_text_length () > 0
        if has_text:
            self.timeout = gobject.timeout_add (self.search_timeout,
                                                self.on_search_timeout)
        else:
            self.on_search_timeout ()

        if gtk.__dict__.has_key ("ENTRY_ICON_PRIMARY"):
            self.entry.set_icon_sensitive (gtk.ENTRY_ICON_SECONDARY, has_text)
            self.entry.set_icon_activatable (gtk.ENTRY_ICON_SECONDARY, has_text)

    def on_search_timeout (self):
        self.emit ('search', self.entry.get_text ())
        self.timeout = 0

        return False

    def on_focus_out_event (self, UNUSED_widget, UNUSED_event):
        if self.timeout == 0:
            return False

        gobject.source_remove (self.timeout)
        self.timeout = 0

        self.emit ('search', self.entry.get_text ())

        return False

    def searching (self):
        return self.entry.get_text () != ''

    def on_activate (self, UNUSED_entry):
        self.emit ('search', self.entry.get_text ())

    def grab_focus (self):
        self.entry.grab_focus ()

    def set_drop_down_menu (self, menu):
        if not gtk.__dict__.has_key ("ENTRY_ICON_PRIMARY"):
            return

        if menu:
            self.entry.set_icon_sensitive (gtk.ENTRY_ICON_PRIMARY, True)
            self.entry.set_icon_activatable (gtk.ENTRY_ICON_PRIMARY, True)
            self.menu = menu
        else:
            self.entry.set_icon_sensitive (gtk.ENTRY_ICON_PRIMARY, False)
            self.entry.set_icon_activatable (gtk.ENTRY_ICON_PRIMARY, False)
            self.menu = None

    def on_icon_press (self, UNUSED, icon_position, event):
        if icon_position == gtk.ENTRY_ICON_SECONDARY:
            self.set_text ("")
            return

        if icon_position == gtk.ENTRY_ICON_PRIMARY:
            if not self.menu:
                return

            self.menu.popup (None, None, None, event.button, event.time)

gobject.type_register (ToolbarSearchEntry)

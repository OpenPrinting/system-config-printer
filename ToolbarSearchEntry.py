## This code was translated to python from the original C version in
## Rhythmbox. The original authors are:

## Copyright (C) 2002 Jorn Baayen <jorn@nl.linux.org>
## Copyright (C) 2003 Colin Walters <walters@verbum.org>

## Further modifications by:

## Copyright (C) 2008 Rui Matos <tiagomatos@gmail.com>

## Copyright (C) 2009, 2012 Red Hat, Inc.
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
## Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

from gi.repository import GObject
from gi.repository import GLib
from gi.repository import Gdk
from gi.repository import Gtk
import HIG
import config
import gettext
gettext.install(domain=config.PACKAGE, localedir=config.localedir, unicode=True)

class ToolbarSearchEntry (Gtk.HBox):
    __gproperties__ = {
        'search_timeout' : (GObject.TYPE_UINT,
                            'search timeout',
                            'search signal rate limiter (in ms)',
                            0,
                            5000,
                            300,
                            GObject.PARAM_READWRITE)
        }

    __gsignals__ = {
        'search' : (GObject.SIGNAL_RUN_LAST,
                    None,
                    (str,)),
        'activate' : (GObject.SIGNAL_RUN_LAST,
                      None,
                      ())
        }

    def __init__ (self):
        self.entry = None
        self.timeout = 0
        self.is_a11y_theme = False
        self.search_timeout = 300
        self.menu = None

        Gtk.HBox.__init__ (self)
        self.set_spacing (HIG.PAD_NORMAL)
        self.set_border_width (HIG.PAD_NORMAL)

        settings = Gtk.Settings.get_for_screen (self.get_screen ())
        theme = settings.get_property ('gtk-theme-name')
        self.is_a11y_theme = theme == 'HighContrast' or theme == 'LowContrast'

        label = Gtk.Label ()
        label.set_text_with_mnemonic (_("_Filter:"))
        label.set_justify (Gtk.Justification.RIGHT)
        self.pack_start (label, False, True, 0)

        self.entry = Gtk.Entry()
        if Gtk.EntryIconPosition.__dict__.has_key ('PRIMARY'):
            # We have primary/secondary icon support.
            self.entry.set_icon_from_stock (Gtk.EntryIconPosition.PRIMARY,
                                            Gtk.STOCK_FIND)
            self.entry.set_icon_from_stock (Gtk.EntryIconPosition.SECONDARY,
                                            Gtk.STOCK_CLEAR)

            self.entry.set_icon_sensitive (Gtk.EntryIconPosition.SECONDARY, False)
            self.entry.set_icon_activatable (Gtk.EntryIconPosition.SECONDARY, False)
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
            GLib.source_remove (self.timeout)
            self.timeout = 0

        self.entry.set_text ("")

    def get_text (self):
        return self.entry.get_text ()

    def set_text (self, text):
        self.entry.set_text (text)

    def check_style (self):
        if self.is_a11y_theme:
            return

        bg_colour = Gdk.color_parse ('#f7f7be') # yellow-ish
        fg_colour = Gdk.color_parse ('#000000') # black

        text = self.entry.get_text ()
        if len (text) > 0:
            self.entry.modify_text (Gtk.StateType.NORMAL, fg_colour)
            self.entry.modify_base (Gtk.StateType.NORMAL, bg_colour)
        else:
            self.entry.modify_text (Gtk.StateType.NORMAL, None)
            self.entry.modify_base (Gtk.StateType.NORMAL, None)

        self.queue_draw ()

    def on_changed (self, UNUSED):
        self.check_style ()

        if self.timeout != 0:
            GLib.source_remove (self.timeout)
            self.timeout = 0

       	# emit it now if we have no more text
        has_text = self.entry.get_text_length () > 0
        if has_text:
            self.timeout = GLib.timeout_add (self.search_timeout,
                                             self.on_search_timeout)
        else:
            self.on_search_timeout ()

        if Gtk.EntryIconPosition.__dict__.has_key ('PRIMARY'):
            self.entry.set_icon_sensitive (Gtk.EntryIconPosition.SECONDARY, has_text)
            self.entry.set_icon_activatable (Gtk.EntryIconPosition.SECONDARY, has_text)

    def on_search_timeout (self):
        self.emit ('search', self.entry.get_text ())
        self.timeout = 0

        return False

    def on_focus_out_event (self, UNUSED_widget, UNUSED_event):
        if self.timeout == 0:
            return False

        GLib.source_remove (self.timeout)
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
        if not Gtk.EntryIconPosition.__dict__.has_key ('PRIMARY'):
            return

        if menu:
            self.entry.set_icon_sensitive (Gtk.EntryIconPosition.PRIMARY, True)
            self.entry.set_icon_activatable (Gtk.EntryIconPosition.PRIMARY, True)
            self.menu = menu
        else:
            self.entry.set_icon_sensitive (Gtk.EntryIconPosition.PRIMARY, False)
            self.entry.set_icon_activatable (Gtk.EntryIconPosition.PRIMARY, False)
            self.menu = None

    def on_icon_press (self, UNUSED, icon_position, event):
        if icon_position == Gtk.EntryIconPosition.SECONDARY:
            self.set_text ("")
            return

        if icon_position == Gtk.EntryIconPosition.PRIMARY:
            if not self.menu:
                return

            self.menu.popup (None, None, None, None, event.button, event.time)

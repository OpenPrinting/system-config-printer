#!/usr/bin/python

## Copyright (C) 2009, 2010, 2012 Red Hat, Inc.
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

from gi.repository import Gdk
from gi.repository import Gtk
import cairo

class GtkInkLevel (Gtk.DrawingArea):
    def __init__ (self, color, level=0):
        Gtk.DrawingArea.__init__ (self)
        self.connect ('draw', self.draw)
        self._level = level
        self._color = None
        if color:
            self._color = Gdk.color_parse (color)
        if not self._color:
            self._color = Gdk.color_parse ('#cccccc')

        self.set_size_request (30, 45)

    def set_level (self, level):
        self._level = level
        self.queue_resize ()

    def get_level (self):
        return self._level

    def draw (self, widget, ctx):
        w = widget.get_allocated_width ()
        h = widget.get_allocated_height ()
        ratio = 1.0 * h / w
        if ratio < 1.5:
            w = h * 2.0 / 3.0
        else:
            h = w * 3.0 / 2.0
        thickness = 1
        ctx.translate (thickness, thickness)
        ctx.scale (w - 2 * thickness, h - 2 * thickness)
        thickness = max (ctx.device_to_user_distance (thickness, thickness))

        r = self._color.red / 65535.0
        g = self._color.green / 65535.0
        b = self._color.blue / 65535.0
        fill_point = self._level / 100.0

        ctx.move_to (0.5, 0.0)
        ctx.curve_to (0.5, 0.33, 1.0, 0.5, 1.0, 0.67)
        ctx.curve_to (1.0, 0.85, 0.85, 1.0, 0.5, 1.0)
        ctx.curve_to (0.15, 1.0, 0.0, 0.85, 0.0, 0.67)
        ctx.curve_to (0.0, 0.5, 0.1, 0.2, 0.5, 0.0)
        ctx.close_path ()
        ctx.set_source_rgb (r, g, b)
        ctx.set_line_width (thickness)
        ctx.stroke_preserve ()
        if fill_point > 0.0:
            grad_width = 0.10
            grad_start = fill_point - (grad_width / 2)
            if grad_start < 0:
                grad_start = 0

            pat = cairo.LinearGradient (0, 1, 0, 0)
            pat.add_color_stop_rgba (0, r, g, b, 1)
            pat.add_color_stop_rgba ((self._level - 5) / 100.0, r, g, b, 1)
            pat.add_color_stop_rgba ((self._level + 5)/ 100.0, 1, 1, 1, 1)
            pat.add_color_stop_rgba (1.0, 1, 1, 1, 1)
            ctx.set_source (pat)
            ctx.fill ()
        else:
            ctx.set_source_rgb (1, 1, 1)
            ctx.fill ()

        ctx.set_line_width (thickness / 2)

        ctx.move_to (0.5, 0.0)
        ctx.line_to (0.5, 1.0)
        ctx.set_source_rgb (r, g, b)
        ctx.stroke ()

        # 50% marker
        ctx.move_to (0.4, 0.5)
        ctx.line_to (0.6, 0.5)
        ctx.set_source_rgb (r, g, b)
        ctx.stroke ()

        # 25% marker
        ctx.move_to (0.45, 0.75)
        ctx.line_to (0.55, 0.75)
        ctx.set_source_rgb (r, g, b)
        ctx.stroke ()

        # 75% marker
        ctx.move_to (0.45, 0.25)
        ctx.line_to (0.55, 0.25)
        ctx.set_source_rgb (r, g, b)
        ctx.stroke ()

if __name__ == '__main__':
    # Try it out.
    from gi.repository import GLib
    import time
    def adjust_level (level):
        Gdk.threads_enter ()
        l = level.get_level ()
        l += 1
        if l > 100:
            l = 0
        level.set_level (l)
        Gdk.threads_leave ()
        return True

    w = Gtk.Window ()
    w.set_border_width (12)
    vbox = Gtk.VBox (spacing=6)
    w.add (vbox)
    hbox = Gtk.HBox (spacing=6)
    vbox.pack_start (hbox, False, False, 0)
    klevel = GtkInkLevel ("black", level=100)
    clevel = GtkInkLevel ("cyan", level=60)
    mlevel = GtkInkLevel ("magenta", level=30)
    ylevel = GtkInkLevel ("yellow", level=100)
    hbox.pack_start (klevel, False, False, 0)
    hbox.pack_start (clevel, False, False, 0)
    hbox.pack_start (mlevel, False, False, 0)
    hbox.pack_start (ylevel, False, False, 0)
    GLib.timeout_add (10, adjust_level, klevel)
    GLib.timeout_add (10, adjust_level, clevel)
    GLib.timeout_add (10, adjust_level, mlevel)
    GLib.timeout_add (10, adjust_level, ylevel)
    w.show_all ()
    w.connect ('delete_event', Gtk.main_quit)
    Gdk.threads_init ()
    Gtk.main ()

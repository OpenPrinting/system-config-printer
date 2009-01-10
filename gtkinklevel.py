#!/usr/bin/env python

## Copyright (C) 2009 Tim Waugh <twaugh@redhat.com>
## Copyright (C) 2009 Red Hat, Inc.

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

import gtk
import cairo

class GtkInkLevel (gtk.DrawingArea):
    def __init__ (self, color, level=0):
        gtk.DrawingArea.__init__ (self)
        self.connect ('expose-event', self.expose_event)
        self._level = level
        self._color = gtk.gdk.color_parse (color)
        self.set_size_request (50, 3)

    def set_level (self, level):
        self._level = level
        self.queue_resize ()

    def expose_event (self, widget, event):
        style = self.get_style ()
        style.paint_box (widget.window, gtk.STATE_NORMAL,
                         gtk.SHADOW_IN,
                         event.area,
                         widget,
                         "box",
                         event.area.x, event.area.y,
                         event.area.width, event.area.height)

        ctx = self.window.cairo_create ()

        border = 1
        ctx.rectangle (event.area.x + border, event.area.y + border,
                       event.area.width - 2 * border,
                       event.area.height - 2 * border)
        ctx.clip ()

        (w, h) = self.window.get_size ()
        self.draw (ctx, w, h)

    def draw (self, ctx, width, height):
        #ctx.set_source_rgb (1.0, 1.0, 1.0)
        #ctx.rectangle (0, 0, width, height)
        #ctx.fill ()

        r = self._color.red / 65535.0
        g = self._color.green / 65535.0
        b = self._color.blue / 65535.0
        fill_point = self._level * width / 100
        grad_width = width / 4
        grad_start = fill_point - (grad_width / 2)
        if grad_start < 0:
            grad_start = 0

        pat = cairo.LinearGradient (0, 0, width, 0)
        pat.add_color_stop_rgba (0, r, g, b, 1)
        pat.add_color_stop_rgba ((self._level - 5) / 100.0, r, g, b, 1)
        pat.add_color_stop_rgba ((self._level + 5)/ 100.0, 1, 1, 1, 1)
        pat.add_color_stop_rgba (1.0, 1, 1, 1, 1)
        ctx.set_source (pat)
        ctx.rectangle (0, 0, width, height)
        ctx.fill ()

if __name__ == '__main__':
    # Try it out.
    w = gtk.Window ()
    w.set_border_width (12)
    vbox = gtk.VBox (spacing=6)
    w.add (vbox)
    hbox = gtk.HBox (spacing=6)
    vbox.pack_start (hbox, False, False, 0)
    hbox.pack_start (gtk.Label ("Red"), False, False, 0)
    level = GtkInkLevel ("red", level=60)
    hbox.pack_start (level)
    w.show_all ()
    w.connect ('delete_event', gtk.main_quit)
    gtk.main ()

#!/usr/bin/env python

## system-config-printer

## Copyright (C) 2009 Tim Waugh <twaugh@redhat.com>

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

import glib
import gtk

class Spinner:
    def __init__ (self, image):
        self.image = image
        frames = []
        theme = gtk.icon_theme_get_default ()
        icon_info = theme.lookup_icon ("process-working", 22, 0)
        if icon_info != None:
            size = icon_info.get_base_size ()
            icon = icon_info.get_filename ()
            try:
                pixbuf = gtk.gdk.pixbuf_new_from_file (icon)
                grid_width = pixbuf.get_width ()
                grid_height = pixbuf.get_height ()
                y = 0
                while y < grid_height:
                    x = 0
                    while x < grid_width:
                        frame = pixbuf.subpixbuf (x, y, size, size)
                        frames.append (frame)
                        x += size

                    y += size
            except gobject.GError:
                # Failed to load icon.
                pass

        self.frames = frames
        self.n_frames = len (frames)
        self._rest ()

    def _set_frame (self, n):
        self._current_frame = n
        if self.n_frames == 0:
            self.image.clear ()
            return

        self.image.set_from_pixbuf (self.frames[n])

    def _rest (self):
        self._set_frame (0)

    def _next_frame (self):
        n = self._current_frame + 1
        if n >= self.n_frames:
            n = 1

        self._set_frame (n)
        return True

    def start (self, timeout=125):
        self._task = glib.timeout_add (timeout, self._next_frame)

    def stop (self):
        glib.source_remove (self._task)
        self._rest ()

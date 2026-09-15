#!/usr/bin/env python3
## vectorspinner.py - Custom Cairo-drawn vector spinner widget

## A theme-independent spinner that renders identically across all
## GTK themes and Linux distributions.
## Authors:
##  Alexander Pevzner
##  Ayush Singh <ayushsinghceee@gmail.com>

## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.

## If any error is found in this code, please report it to the author at ayushsinghceee@gmail.com

import math
import cairo

from gi.repository import Gtk
from gi.repository import GLib


class VectorSpinner(Gtk.DrawingArea):
    """A custom spinner widget drawn with Cairo vectors.

    Unlike Gtk.Spinner, this renders identically across all GTK themes
    and distributions since it draws its own animation frames using
    Cairo vector paths.

    The spinner consists of evenly-spaced radial lines arranged in a
    circle. Each frame, the "bright" line advances one position,
    creating the classic rotating spinner effect through opacity fade.
    """

    def __init__(self, size=32, interval=20, num_lines=12):
        """
        Args:
            size:      Widget width and height in pixels.
            interval:  Animation frame interval in milliseconds.
            num_lines: Number of radial lines in the spinner.
        """
        super().__init__()
        self._size = size
        self._interval = interval
        self._num_lines = num_lines
        self._step = 0
        self._timer_id = None

        self.set_size_request(size, size)
        self.connect("draw", self._on_draw)

    def start(self):
        """Start the spinner animation."""
        if self._timer_id is None:
            self._timer_id = GLib.timeout_add(self._interval, self._tick)

    def stop(self):
        """Stop the spinner animation."""
        if self._timer_id is not None:
            GLib.source_remove(self._timer_id)
            self._timer_id = None

    def _tick(self):
        """Advance one animation frame smoothly."""
        
        self._step = (self._step + 1) % 36
        self.queue_draw()
        return True

    def _on_draw(self, widget, cr):
        """Draw a modern, continuous rotating ring."""
        size = self._size
        center = size / 2.0
        radius = size * 0.35
        line_width = max(size * 0.08, 2.0)

        cr.set_line_width(line_width)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_source_rgba(0.4, 0.4, 0.4, 1.0)
        angle_offset = self._step * (2 * math.pi / 36)
        start_angle = angle_offset
        end_angle = angle_offset + (math.pi * 1.5)  # 270 degree solid arc

        cr.arc(center, center, radius, start_angle, end_angle)
        cr.stroke()

        return False


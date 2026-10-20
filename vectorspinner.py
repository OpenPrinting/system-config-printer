#!/usr/bin/env python3
## vectorspinner.py - Custom Cairo-drawn vector spinner widget

## A theme-independent spinner that renders identically across all
## GTK themes and Linux distributions.
## Authors:
##  Alexander Pevzner <pzz@apevzner.com>
##  Ayush Singh <ayushsinghceee@gmail.com>

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

import math
import cairo

from gi.repository import Gtk
from gi.repository import GLib


class VectorSpinner(Gtk.DrawingArea):
    """A custom spinner widget drawn with Cairo vectors.

    Note: We must use a custom implementation because the standard Gtk.Spinner
    is unfortunately not customizable, at least in some Linux distributions 
    and system themes where CSS overrides for size are ignored.

    Unlike Gtk.Spinner, this renders identically across all GTK themes
    and distributions since it draws its own animation frames using
    Cairo vector paths.
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


class DelayedSpinner:
    """A wrapper for GTK/VectorSpinner widgets that delays spinner appearance
    by a specified threshold (e.g. 200-300ms) to prevent visual flicker
    for fast operations.
    """

    def __init__(self, spinner, delay_ms=250):
        self._spinner = spinner
        self._delay_ms = delay_ms
        self._timer_id = None
        self._is_shown = False

    @property
    def is_shown(self):
        return self._is_shown

    def start(self):
        """Schedule delayed appearance of the spinner."""
        if self._spinner is None or self._timer_id is not None or self._is_shown:
            return
        self._timer_id = GLib.timeout_add(self._delay_ms, self._on_delay_timer)

    def _on_delay_timer(self):
        self._timer_id = None
        self._is_shown = True
        if self._spinner is not None:
            try:
                self._spinner.show()
                if hasattr(self._spinner, 'start'):
                    self._spinner.start()
            except (AttributeError, RuntimeError):
                pass
        return False

    def stop(self):
        """Cancel delayed timer if pending, or stop/hide spinner if visible."""
        if self._timer_id is not None:
            GLib.source_remove(self._timer_id)
            self._timer_id = None

        if self._is_shown:
            self._is_shown = False
            if self._spinner is not None:
                try:
                    if hasattr(self._spinner, 'stop'):
                        self._spinner.stop()
                    self._spinner.hide()
                except (AttributeError, RuntimeError):
                    pass


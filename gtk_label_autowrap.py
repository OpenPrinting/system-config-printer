# utils.py
#
# Copyright (c) 2004 Thomas Woerner <twoerner@redhat.com>
# Copyright (c) 2006 Florian Festi <ffesti@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.


import gtk
from pango import SCALE

### set autowrapping for all labels in this widget tree
def set_autowrap(widget):
    if isinstance(widget, gtk.Container):
        children = widget.get_children()
        for i in xrange(len(children)):
            set_autowrap(children[i])
    elif isinstance(widget, gtk.Label) and widget.get_line_wrap():
        widget.connect_after("size-allocate", label_size_allocate)

### set wrap width to the pango.Layout of the labels ###
def label_size_allocate(widget, allocation):
    layout = widget.get_layout()

    lw_old, lh_old = layout.get_size()
    # fixed width labels
    if lw_old/SCALE == allocation.width:
        return
    layout.set_width(allocation.width * SCALE)

    lw, lh = layout.get_size()

    if lh_old != lh:
        widget.set_size_request(-1, lh/SCALE)
        
    return

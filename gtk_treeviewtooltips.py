#
# Copyright 2007 Red Hat, Inc.
# Authors:
# Thomas Woerner <twoerner@redhat.com>
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
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import pygtk
import gtk
import gobject

##############################################################################

class TreeViewTooltips(gobject.GObject):
    __gproperties__ = {
        "show-delay": (gobject.TYPE_UINT,
                       "Show Delay (ms)", "Show Delay (ms), 0 for no delay.",
                       0, 10000, 500,
                       gobject.PARAM_READWRITE),
        "hide-delay": (gobject.TYPE_UINT,
                       "Hide Delay (ms)", "Hide Delay (ms), 0 for unlimited.",
                       0, 99999999, 5*1000,
                       gobject.PARAM_READWRITE),
        }

    def __init__(self, treeview, tooltip_func, *tooltip_func_args):
        self.__gobject_init__()
        self.treeview = treeview
        self.tooltip_func = tooltip_func
        self.tooltip_func_args = tooltip_func_args

        self.popup = gtk.Window(gtk.WINDOW_POPUP)
        self.label = gtk.Label()
        self.label.set_line_wrap(True)
        self.label.set_use_markup(True)
        self.popup.add(self.label)
        self.popup.set_name('gtk-tooltips')
        self.popup.set_resizable(False)
        self.popup.set_border_width(4)
        self.popup.set_app_paintable(True)

        self.show_delay = 500
        self.hide_delay = 5*1000

        self.show_timer = None
        self.hide_timer = None
        self.path = self.col = None

        treeview.connect("motion-notify-event", self.on_motion_notify)
        treeview.connect("leave-notify-event", self.on_leave_notify)
        self.popup.connect("expose-event", self.on_expose_event)

    def do_get_property(self, property):
        if property.name == 'show-delay':
            return self.show_delay
        elif property.name == 'hide-delay':
            return self.hide_delay

    def do_set_property(self, property, value):
        if property.name == 'show-delay':
            self.show_delay = value
        elif property.name == 'hide-delay':
            self.hide_delay = value

    def on_motion_notify(self, treeview, event):
        if event.window != treeview.get_bin_window():
            return

        path = treeview.get_path_at_pos(int(event.x), int(event.y))
        if path:
            path, col, _x, _y = path
            if self.path != path or self.col != col:
                if self.hide_timer:
                    gobject.source_remove(self.hide_timer)
                    self.hide_timer = None
                self.hide_tip()
                self.path = path
                self.col = col
                if self.show_timer:
                    gobject.source_remove(self.show_timer)
                    self.show_timer = None
                self.show_timer = gobject.timeout_add(self.show_delay,
                                                      self.show_tip,
                                                      path, col,
                                                      event.x, event.y)
            else:
                if self.hide_timer:
                    gobject.source_remove(self.hide_timer)
                    if self.hide_delay > 0:
                        self.hide_timer = gobject.timeout_add(self.hide_delay, 
                                                              self.hide_tip)
        elif self.path or self.col:
            if self.show_timer:
                gobject.source_remove(self.show_timer)
                self.show_timer = None
            if self.hide_timer:
                gobject.source_remove(self.hide_timer)
                self.hide_timer = None
            self.hide_tip()

    def on_leave_notify(self, treeview, event):
        if self.show_timer:
            gobject.source_remove(self.show_timer)
            self.show_timer = None
        if self.hide_timer:
            gobject.source_remove(self.hide_timer)
            self.hide_timer = None
        if self.path or self.col:
            self.hide_tip()

    def show_tip(self, path, col, event_x, event_y):
        text = self.tooltip_func(self.treeview.get_model(), path, col,
                                 *self.tooltip_func_args)
        if not text or len(text) == 0:
            return False
        self.label.set_label(text)
        (parent_x, parent_y) = self.treeview.get_bin_window().get_origin()
        (width, height) = self.popup.size_request()
        screen_width = gtk.gdk.screen_width()
        screen_height = gtk.gdk.screen_height()
        x = int(event_x + parent_x)
        y = int(event_y + parent_y + 10)
        if x + width> screen_width:
            x = screen_width - width
        if y + height > screen_height:
            y = int(event_y + parent_y - height - 10)
        self.popup.move(x, y)
        self.popup.show_all()
        if self.hide_delay > 0:
            self.hide_timer = gobject.timeout_add(self.hide_delay,
                                                  self.hide_tip)
        return False

    def on_expose_event(self, window, event):
        (width, height) = window.size_request()
        window.style.paint_flat_box(window.window, gtk.STATE_NORMAL,
                                    gtk.SHADOW_OUT, None, window,
                                    'tooltip', 0, 0, width, height)

    def hide_tip(self):
        self.path = self.col = None
        self.popup.hide()
        return False

##############################################################################

if __name__ == "__main__":
    def getTooltip(model, path, col, cell):
        iter = model.get_iter(path)
        text = "%s" % model.get_value(iter, cell)
        return text

    window = gtk.Window(gtk.WINDOW_TOPLEVEL)
    window.connect("delete_event", gtk.main_quit)
    window.set_default_size(200,250)
        
    scrolledwin = gtk.ScrolledWindow()
    scrolledwin.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
    window.add(scrolledwin)
        
    treeview = gtk.TreeView()
    treeview.get_selection().set_mode(gtk.SELECTION_NONE)
    store = gtk.ListStore(gobject.TYPE_STRING, gobject.TYPE_STRING,
                          gobject.TYPE_STRING)
    treeview.set_model(store)
    scrolledwin.add(treeview)

    column = gtk.TreeViewColumn("Head1", gtk.CellRendererText(), text=0)
    treeview.append_column(column)

    column = gtk.TreeViewColumn("Head2", gtk.CellRendererText(), text=1)
    treeview.append_column(column)

    for i in xrange(10):
        cell1 = "cell data %d.1" % i
        cell2 = "cell data %d.2" % i
        cell3 = "Tooltip %d" % i
        cell3 += """
This program is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation; either version 2 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program; if not, write to the Free Software Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA."""
        store.append([cell1, cell2, cell3])
    
    tips = TreeViewTooltips(treeview, getTooltip, 2)
#    tips.set_property("hide-delay", 20*1000)

    window.show_all()
    gtk.main()

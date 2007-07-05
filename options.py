## system-config-printer

## Copyright (C) 2006, 2007 Red Hat, Inc.
## Copyright (C) 2006 Florian Festi <ffesti@redhat.com>

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

def OptionWidget(name, v, s, on_change):
    if isinstance(v, list):
        # XXX
        if isinstance(s, list):
            for vv in v + s:
                if not isinstance(vv, str): raise ValueError
            return OptionSelectMany(name, v, s, on_change)
        raise NotImplemented
    else:
        if (isinstance(s, int) or isinstance(s, float) or
            (isinstance(s, tuple) and len(s)==2 and
             (isinstance(s[0], int) and isinstance(s[1], int)) or
             (isinstance(s[0], float) and isinstance(s[1], float)))):
            try:
                if (isinstance(s, int) or
                    isinstance(s, tuple) and isinstance(s[0], int)):
                    v = int(v)
                else:
                    v = float(v)
            except ValueError:
                return OptionText(name, v, "", on_change)
            return OptionNumeric(name, v, s, on_change)
        elif isinstance(s, list):
            for sv in s:
                if not isinstance(sv, int):
                    return OptionSelectOne(name, v, s, on_change)
            try:
                v = int(v)
            except ValueError:
                return OptionSelectOne(name, v, s, on_change)
            return OptionSelectOneNumber(name, v, s, on_change)
        elif isinstance(s, str):
            return OptionText(name, v, s, on_change)
        else:
            raise ValueError

# ---------------------------------------------------------------------------

class Option:

    conflicts = None

    def __init__(self, name, value, supported, on_change):
        self.name = name
        self.value = value
        self.supported = supported
        self.on_change = on_change
        self.is_new = False

        label = name
        if not label.endswith (':'):
            label += ':'
        self.label = gtk.Label(label)
        self.label.set_alignment(0.0, 0.5)

    def get_current_value(self):
        raise NotImplemented

    def is_changed(self):
        return (self.is_new or
                str (self.get_current_value()) != str (self.value))

    def changed(self, widget, *args):
        self.on_change(self)
    
# ---------------------------------------------------------------------------

class OptionSelectOne(Option):

    def __init__(self, name, value, supported, on_change):
        Option.__init__(self, name, value, supported, on_change)

        self.selector = gtk.combo_box_new_text()
        
        
        selected = None
        for nr, choice in enumerate(supported):
            self.selector.append_text(str(choice))
            if str (value) == str (choice):
                selected = nr
        if selected is not None:
            self.selector.set_active(selected)
        else:
            print "Unknown value for %s: %s" % (name, value)
            print "Choices:", supported
        self.selector.connect("changed", self.changed)

    def get_current_value(self):
        return self.selector.get_active_text()

# ---------------------------------------------------------------------------

class OptionSelectOneNumber(OptionSelectOne):

    def get_current_value(self):
        return int(self.selector.get_active_text())

# ---------------------------------------------------------------------------

class OptionSelectMany(Option):

    def __init__(self, name, value, supported, on_change):
        Option.__init__(self, name, value, supported, on_change)
        self.checkboxes = []
        vbox = gtk.VBox()

        for s in supported:
            checkbox = gtk.CheckButton(label=s)
            checkbox.set_active(s in value)
            vbox.add(checkbox)
            checkbox.connect("toggled", self.changed)
            self.checkboxes.append(checkbox)
        self.selector = vbox
            
    def get_current_value(self):
        return[s for s, chk in zip(self.supported, self.checkboxes)
               if chk.get_active()]

# ---------------------------------------------------------------------------

class OptionNumeric(Option):
    def __init__(self, name, value, supported, on_change):
        self.is_float = (isinstance(supported, float) or
                         (isinstance(supported, tuple) and
                          isinstance(supported[0], float)))
        if self.is_float:
            digits = 2
        else:
            digits = 0

        if not isinstance(supported, tuple):
            supported = (0, supported)
        Option.__init__(self, name, value, supported, on_change)
        adj = gtk.Adjustment(value, supported[0], supported[1], 1.0, 5.0, 0.0)
        self.selector = gtk.SpinButton(adj, climb_rate=1.0, digits=digits)
        if not self.is_float:
            self.selector.set_numeric(True)
        self.selector.connect("changed", self.changed)

    def get_current_value(self):
        if self.is_float:
            return self.selector.get_value()
        return self.selector.get_value_as_int()

# ---------------------------------------------------------------------------

class OptionText(Option):
    def __init__(self, name, value, supported, on_change):
        Option.__init__(self, name, value, supported, on_change)

        self.selector = gtk.Entry()
        self.selector.set_text(value)
        self.selector.connect("changed", self.changed)

    def get_current_value(self):
        return self.selector.get_text()

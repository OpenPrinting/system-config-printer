## system-config-printer

## Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012 Red Hat, Inc.
## Authors:
##  Tim Waugh <twaugh@redhat.com>
##  Florian Festi <ffesti@redhat.com>

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

from gi.repository import Gtk
import cups
import ppdippstr
import re

cups.require ("1.9.55")

# Special IPP type
class IPPResolution(tuple):
    def __new__ (cls, values):
        cls.UNITS_BY_VAL = { cups.IPP_RES_PER_INCH: "dpi",
                             cups.IPP_RES_PER_CM: "dpc" }
        cls.UNITS_DEFAULT = cups.IPP_RES_PER_INCH

        cls.UNITS_BY_STR = {}
        for v, s in cls.UNITS_BY_VAL.iteritems ():
            cls.UNITS_BY_STR[s] = v

        if isinstance (values, str):
            matches = re.match ("(\d+)\D+(\d+)(.*)", values).groups ()
            xres = int (matches[0])
            yres = int (matches[1])
            units = cls.UNITS_BY_STR.get (matches[2], cls.UNITS_DEFAULT)
        else:
            xres = values[0]
            yres = values[1]
            units = values[2]

        self = tuple.__new__ (cls, (xres, yres, units))
        self.xres = xres
        self.yres = yres
        self.units = units
        return self

    def __init__ (self, values):
        return tuple.__init__ (self, (self.xres, self.yres, self.units))

    def __str__ (self):
        return "%sx%s%s" % (self.xres, self.yres,
                            self.UNITS_BY_VAL.get (self.units,
                                                   self.UNITS_DEFAULT))

def OptionWidget(name, v, s, on_change):
    if isinstance(v, list):
        # XXX
        if isinstance(s, list):
            for vv in v + s:
                if not isinstance(vv, str): raise ValueError
            return OptionSelectMany(name, v, s, on_change)
        print v, s
        raise NotImplementedError
    else:
        if (isinstance(s, int) or
            isinstance(s, float) or
            (isinstance(s, tuple) and
             len(s) == 2 and
             ((isinstance(s[0], int) and isinstance(s[1], int)) or
              (isinstance(s[0], float) and isinstance(s[1], float))))):
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
                if isinstance(sv, tuple) and len (sv) == 3:
                    return OptionSelectOneResolution(name, v, s, on_change)
                elif not isinstance(sv, int):
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

class OptionInterface:
    def get_default(self):
        return None

    def get_current_value(self):
        raise NotImplementedError

    def is_changed(self):
        raise NotImplementedError

class OptionAlwaysShown(OptionInterface):
    # States
    STATE_UNCHANGED=0
    STATE_RESET=1
    STATE_ADJUSTED=2

    def __init__(self, name, ipp_type, system_default,
                 widget, button, combobox_map = None, use_supported = False):
        self.name = name
        self.widget = widget
        self.button = button
        if ipp_type == bool:
            def bool_type (x):
                if type (x) == str:
                    if x.lower () in ("false", "no", "off"):
                        return False
                    # Even the empty string is true.
                    return True
                return bool (x)
            ipp_type = bool_type
        self.ipp_type = ipp_type
        self.set_default (system_default)
        self.combobox_map = combobox_map

        if (type(self.widget) == Gtk.ComboBox and
            self.widget.get_model () == None):
            print "No ComboBox model for %s" % self.name
            model = Gtk.ListStore (str)
            self.widget.set_model (model)

        if combobox_map != None and ipp_type == int:
            model = self.widget.get_model ()
            i = 0
            dict = {}
            iter = model.get_iter_first ()
            while iter:
                dict[combobox_map[i]] = model.get_value (iter, 0)
                i += 1
                iter = model.iter_next (iter)
            self.combobox_dict = dict
        self.use_supported = use_supported
        self.reinit (None)

    def get_default(self):
        return self.system_default

    def set_default(self, system_default):
        # For the media option, the system default depends on the printer's
        # PageSize setting.  This method allows the main module to tell us
        # what that is.
        self.system_default = self.ipp_type (system_default)

    def reinit(self, original_value, supported=None):
        """Set the original value of the option and the supported choices.
        The special value None for original_value resets the option to the
        system default."""
        if (supported != None and
            self.use_supported):
            if (type(self.widget) == Gtk.ComboBox and
                self.ipp_type == str):
                model = self.widget.get_model ()
                model.clear ()
                translations = ppdippstr.job_options.get (self.name)
                if translations:
                    self.combobox_map = []
                    self.combobox_dict = dict()
                    i = 0

                for each in supported:
                    txt = str (self.ipp_type (each))

                    if translations:
                        self.combobox_map.append (txt)
                        text = translations.get (txt)
                        self.combobox_dict[each] = text
                        i += 1
                    else:
                        text = txt

                    iter = model.append ()
                    model.set_value (iter, 0, text)
            elif type(self.widget) == Gtk.ComboBoxText:
                self.widget.remove_all () # emits 'changed'
                translations = ppdippstr.job_options.get (self.name)
                if translations:
                    self.combobox_map = []
                    self.combobox_dict = dict()
                    i = 0

                for each in supported:
                    txt = str (self.ipp_type (each))
                    if translations:
                        self.combobox_map.append (txt)
                        text = translations.get (txt)
                        self.combobox_dict[each] = text
                        i += 1
                    else:
                        text = txt

                    self.widget.append_text (text)
            elif (type(self.widget) == Gtk.ComboBox and
                  self.ipp_type == int and
                  self.combobox_map != None):
                model = self.widget.get_model ()
                model.clear ()
                for each in supported:
                    iter = model.append ()
                    model.set_value (iter, 0, self.combobox_dict[each])

        if original_value != None:
            self.original_value = self.ipp_type (original_value)
            self.set_widget_value (self.original_value)
            self.button.set_sensitive (True)
        else:
            self.original_value = None
            self.set_widget_value (self.system_default)
            self.button.set_sensitive (False)
        self.state = self.STATE_UNCHANGED

    def set_widget_value(self, ipp_value):
        t = type(self.widget)
        if t == Gtk.SpinButton:
            return self.widget.set_value (ipp_value)
        elif t == Gtk.ComboBox or t == Gtk.ComboBoxText:
            if ((self.ipp_type == str or self.ipp_type == IPPResolution)
                and self.combobox_map == None):
                model = self.widget.get_model ()
                iter = model.get_iter_first ()
                while (iter != None and
                       self.ipp_type (model.get_value (iter, 0)) != ipp_value):
                    iter = model.iter_next (iter)
                if iter:
                    self.widget.set_active_iter (iter)
            else:
                # It's an int.
                if self.combobox_map:
                    index = self.combobox_map.index (ipp_value)
                else:
                    index = ipp_value
                return self.widget.set_active (index)
        elif t == Gtk.CheckButton:
            return self.widget.set_active (ipp_value)
        else:
            raise NotImplementedError, (t, self.name)

    def get_widget_value(self):
        t = type(self.widget)
        if t == Gtk.SpinButton:
            # Ideally we would use self.widget.get_value() here, but
            # it doesn't work if the value has been typed in and then
            # the Apply button immediately clicked.  To handle this,
            # we use self.widget.get_text() and fall back to
            # get_value() if the result cannot be interpreted as the
            # type we expect.
            try:
                return self.ipp_type (self.widget.get_text ())
            except ValueError:
                # Can't convert result of get_text() to ipp_type.
                return self.ipp_type (self.widget.get_value ())
        elif t == Gtk.ComboBox:
            if self.combobox_map:
                return self.combobox_map[self.widget.get_active()]
            return self.ipp_type (self.widget.get_active ())
        elif t == Gtk.ComboBoxText:
            s = self.widget.get_active_text ()
            if s == None:
                # If the widget is being re-initialised, there will be
                # a changed signal emitted at the point where there
                # are no entries to select from.
                s = self.system_default
            if self.combobox_map:
                return self.combobox_map (s)
            return self.ipp_type (s)
        elif t == Gtk.CheckButton:
            return self.ipp_type (self.widget.get_active ())

        print t, self.widget, self.ipp_type
        raise NotImplementedError

    def get_current_value(self):
        return self.get_widget_value ()

    def is_changed(self):
        if self.original_value != None:
            # There was a value set previously.
            if self.state == self.STATE_RESET:
                # It's been removed.
                return True
            if self.state == self.STATE_ADJUSTED:
                if self.get_current_value () != self.original_value:
                    return True
                return False

            # The value is the same as before, and not reset.
            return False

        # There was no original value set.
        if self.state == self.STATE_ADJUSTED:
            # It's been adjusted.
            return True

        # It's been left alone, or possible adjusted and then reset.
        return False

    def reset(self):
        self.set_widget_value (self.system_default)
        self.state = self.STATE_RESET
        self.button.set_sensitive (False)

    def changed(self):
        self.state = self.STATE_ADJUSTED
        self.button.set_sensitive (True)

class OptionAlwaysShownSpecial(OptionAlwaysShown):
    def __init__(self, name, ipp_type, system_default,
                 widget, button, combobox_map = None, use_supported = False,
                 special_choice = "System default"):
        self.special_choice = special_choice
        self.special_choice_shown = False
        OptionAlwaysShown.__init__ (self, name, ipp_type, system_default,
                                    widget, button,
                                    combobox_map=combobox_map,
                                    use_supported=use_supported)

    def show_special_choice (self):
        if self.special_choice_shown:
            return

        self.special_choice_shown = True
        # Only works for ComboBox widgets
        model = self.widget.get_model ()
        iter = model.insert (0)
        model.set_value (iter, 0, self.special_choice)
        self.widget.set_active_iter (model.get_iter_first ())

    def hide_special_choice (self):
        if not self.special_choice_shown:
            return

        self.special_choice_shown = False
        # Only works for ComboBox widgets
        model = self.widget.get_model ()
        model.remove (model.get_iter_first ())

    def reinit(self, original_value, supported=None):
        if original_value != None:
            self.hide_special_choice ()
        else:
            self.show_special_choice ()

        OptionAlwaysShown.reinit (self, original_value, supported=supported)

    def reset(self):
        self.show_special_choice ()
        OptionAlwaysShown.reset (self)

    def changed(self):
        OptionAlwaysShown.changed (self)
        if self.widget.get_active () > 0:
            self.hide_special_choice ()

class Option(OptionInterface):

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
        self.label = Gtk.Label(label=label)
        self.label.set_alignment(0.0, 0.5)

    def get_current_value(self):
        raise NotImplementedError

    def is_changed(self):
        return (self.is_new or
                str (self.get_current_value()) != str (self.value))

    def changed(self, widget, *args):
        self.on_change(self)
    
# ---------------------------------------------------------------------------

class OptionSelectOne(Option):

    def __init__(self, name, value, supported, on_change):
        Option.__init__(self, name, value, supported, on_change)

        self.selector = Gtk.ComboBoxText()
        
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
            if len(supported) > 0:
                print "Selecting from choices:", supported[0]
                self.selector.set_active(0)
        self.selector.connect("changed", self.changed)

    def get_current_value(self):
        return self.selector.get_active_text()

# ---------------------------------------------------------------------------

class OptionSelectOneResolution(OptionSelectOne):
    def __init__(self, name, value, supported, on_change):
        self.UNITS_BY_VAL = { cups.IPP_RES_PER_INCH: "dpi",
                              cups.IPP_RES_PER_CM: "dpc" }
        self.UNITS_DEFAULT = cups.IPP_RES_PER_INCH
        self.UNITS_BY_STR = {}
        for v, s in self.UNITS_BY_VAL.iteritems ():
            self.UNITS_BY_STR[s] = v

        value = self.string (value)
        supported = map (self.string, supported)
        OptionSelectOne.__init__ (self, name, value, supported, on_change)

    def string(self, value):
        return "%sx%s%s" % (value[0], value[1],
                            self.UNITS_BY_VAL.get (value[2], ""))

    def value(self, string):
        matches = re.match ("(\d+)\D+(\d+)(.*)", string).groups ()
        return (int (matches[0]), int (matches[1]),
                self.UNITS_BY_STR.get (matches[2], self.UNITS_DEFAULT))

    def get_current_value(self):
        return self.value (self.selector.get_active_text())

# ---------------------------------------------------------------------------

class OptionSelectOneNumber(OptionSelectOne):

    def get_current_value(self):
        return int(self.selector.get_active_text() or 0)

# ---------------------------------------------------------------------------

class OptionSelectMany(Option):

    def __init__(self, name, value, supported, on_change):
        Option.__init__(self, name, value, supported, on_change)
        self.checkboxes = []
        vbox = Gtk.VBox()

        for s in supported:
            checkbox = Gtk.CheckButton(label=s)
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
        adj = Gtk.Adjustment(value, supported[0], supported[1], 1.0, 5.0, 0.0)
        self.selector = Gtk.SpinButton(adj, climb_rate=1.0, digits=digits)
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

        self.selector = Gtk.Entry()
        self.selector.set_text(value)
        self.selector.connect("changed", self.changed)

    def get_current_value(self):
        return self.selector.get_text()

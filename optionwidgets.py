## system-config-printer

## Copyright (C) 2006, 2007, 2008, 2009 Red Hat, Inc.
## Copyright (C) 2006 Florian Festi <ffesti@redhat.com>
## Copyright (C) 2007, 2008, 2009 Tim Waugh <twaugh@redhat.com>

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

import config
from gi.repository import Gtk
import cups
import gettext
gettext.install(domain=config.PACKAGE, localedir=config.localedir, unicode=True)
import ppdippstr

def OptionWidget(option, ppd, gui, tab_label=None):
    """Factory function"""
    ui = option.ui
    if (ui == cups.PPD_UI_BOOLEAN and
        len (option.choices) != 2):
        # This option is advertised as a Boolean but in fact has more
        # than two choices.
        print "Treating Boolean option %s as PickOne" % option.keyword
        ui = cups.PPD_UI_PICKONE

    if ui == cups.PPD_UI_BOOLEAN:
        return OptionBool(option, ppd, gui, tab_label=tab_label)
    elif ui == cups.PPD_UI_PICKONE:
        return OptionPickOne(option, ppd, gui, tab_label=tab_label)
    elif ui == cups.PPD_UI_PICKMANY:
        return OptionPickMany(option, ppd, gui, tab_label=tab_label)

# ---------------------------------------------------------------------------

class Option:
    def __init__(self, option, ppd, gui, tab_label=None):
        self.option = option
        self.ppd = ppd
        self.gui = gui
        self.enabled = True
        self.tab_label = tab_label

        vbox = Gtk.VBox()
        
        self.btnConflict = Gtk.Button()
        icon = Gtk.Image.new_from_stock(Gtk.STOCK_DIALOG_WARNING,
                                        Gtk.IconSize.SMALL_TOOLBAR)
        self.btnConflict.add(icon)
        self.btnConflict.set_no_show_all(True) #avoid the button taking
                                               # over control again
        vbox.add(self.btnConflict)    # vbox reserves space while button
        #vbox.set_size_request(32, 28) # is hidden
        self.conflictIcon = vbox

        self.btnConflict.connect("clicked", self.on_btnConflict_clicked)
        icon.show()

        self.constraints = [c for c in ppd.constraints
                            if (c.option1 == option.keyword or
                                c.option2 == option.keyword)]
        #for c in self.constraints:
        #    if not c.choice1 or not c.choice2:
        #        print c.option1, repr(c.choice1), c.option2, repr(c.choice2)
        self.conflicts = set()
        self.conflict_message = ""

    def enable(self, enabled=True):
        self.selector.set_sensitive (enabled)
        self.enabled = enabled

    def disable(self):
        self.enable (False)

    def is_enabled(self):
        return self.enabled

    def get_current_value(self):
        raise NotImplemented

    def is_changed(self):
        return self.get_current_value()!= self.option.defchoice
    
    def writeback(self):
        #print repr(self.option.keyword), repr(self.get_current_value())
        if self.enabled:
            self.ppd.markOption(self.option.keyword, self.get_current_value())

    def checkConflicts(self, update_others=True):
        value = self.get_current_value()
        for constraint in self.constraints:
            if constraint.option1 == self.option.keyword:
                option2 = self.gui.options.get(constraint.option2, None)
                choice1 = constraint.choice1
                choice2 = constraint.choice2
            else:
                option2 = self.gui.options.get(constraint.option1, None)
                choice1 = constraint.choice2
                choice2 = constraint.choice1

            if option2 is None: continue

            def matches (constraint_choice, value):
                if constraint_choice != '':
                    return constraint_choice == value
                return value not in ['None', 'False', 'Off']

            if (matches (choice1, value) and
                matches (choice2, option2.get_current_value())):
                # conflict
                self.conflicts.add(constraint)
                if update_others:
                    option2.checkConflicts(update_others=False)
            elif constraint in self.conflicts:
                # remove conflict
                self.conflicts.remove(constraint)
                option2.checkConflicts(update_others=False)


        tooltip = [_("Conflicts with:")]
        conflicting_options = dict()
        for c in self.conflicts:
            if c.option1 == self.option.keyword:
                option = self.gui.options.get(c.option2)
            else:
                option = self.gui.options.get(c.option1)

            conflicting_options[option.option.keyword] = option

        for option in conflicting_options.values ():
            opt = option.option.text
            val = option.get_current_value ()
            for choice in option.option.choices:
                if choice['choice'] == val:
                    val = ppdippstr.ppd.get (choice['text'])

            tooltip.append ("%s: %s" % (opt, val))
            
        tooltip = "\n".join(tooltip)

        self.conflict_message = tooltip # XXX more verbose
            
        if self.conflicts:
            self.btnConflict.set_tooltip_text (tooltip)
            self.btnConflict.show()
        else:
            self.btnConflict.hide()

        self.gui.option_changed(self)
        return self.conflicts
            
    def on_change(self, widget):
        self.checkConflicts()

    def on_btnConflict_clicked(self, button):
        parent = self.btnConflict
        while parent != None and not isinstance (parent, Gtk.Window):
            parent = parent.get_parent ()

        dialog = Gtk.MessageDialog (parent,
                                    Gtk.DialogFlags.DESTROY_WITH_PARENT |
                                    Gtk.DialogFlags.MODAL,
                                    Gtk.MessageType.WARNING,
                                    Gtk.ButtonsType.CLOSE,
                                    self.conflict_message)
        dialog.run()
        dialog.destroy()
        
# ---------------------------------------------------------------------------

class OptionBool(Option):

    def __init__(self, option, ppd, gui, tab_label=None):
        self.selector = Gtk.CheckButton(ppdippstr.ppd.get (option.text))
        self.label = None
        self.false = u"False" # hack to allow "None" instead of "False"
        self.true = u"True"
        for c in option.choices:
            if c["choice"] in ("None", "False", "Off"):
                self.false = c["choice"]
            if c["choice"] in ("True", "On"):
                self.true = c["choice"]
        self.selector.set_active(option.defchoice == self.true)
        self.selector.set_alignment(0.0, 0.5)
        self.selector.connect("toggled", self.on_change)
        Option.__init__(self, option, ppd, gui, tab_label=tab_label)

    def get_current_value(self):
        return (self.false, self.true)[self.selector.get_active()]

# ---------------------------------------------------------------------------

class OptionPickOne(Option):
    widget_name = "OptionPickOne"

    def __init__(self, option, ppd, gui, tab_label=None):
        self.selector = Gtk.ComboBoxText()
        #self.selector.set_alignment(0.0, 0.5)

        label = ppdippstr.ppd.get (option.text)
        if not label.endswith (':'):
            label += ':'
        self.label = Gtk.Label(label=label)
        self.label.set_alignment(0.0, 0.5)
        
        selected = None
        for nr, choice in enumerate(option.choices):
            self.selector.append_text(ppdippstr.ppd.get (choice['text']))
            if option.defchoice == choice['choice']:
                selected = nr
        if selected is not None:
            self.selector.set_active(selected)
        else:
            print option.text, "unknown value:", option.defchoice
        self.selector.connect("changed", self.on_change)

        Option.__init__(self, option, ppd, gui, tab_label=tab_label)

    def get_current_value(self):
        return self.option.choices[self.selector.get_active()]['choice']
        
# ---------------------------------------------------------------------------

class OptionPickMany(OptionPickOne):
    widget_name = "OptionPickMany"

    def __init__(self, option, ppd, gui, tab_label=None):
        raise NotImplemented
        Option.__init__(self, option, ppd, gui, tab_label=tab_label)
        

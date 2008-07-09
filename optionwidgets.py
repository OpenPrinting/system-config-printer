## system-config-printer

## Copyright (C) 2006, 2007, 2008 Red Hat, Inc.
## Copyright (C) 2006 Florian Festi <ffesti@redhat.com>
## Copyright (C) 2007, 2008 Tim Waugh <twaugh@redhat.com>

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

import gtk.glade, cups
from gettext import gettext as _

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
    
    dialog = gtk.MessageDialog(parent=None, flags=0, type=gtk.MESSAGE_WARNING,
                               buttons=gtk.BUTTONS_OK)

    def __init__(self, option, ppd, gui, tab_label=None):
        self.option = option
        self.ppd = ppd
        self.gui = gui
        self.enabled = True
        self.tab_label = tab_label

        vbox = gtk.VBox()
        
        self.btnConflict = gtk.Button()
        icon = gtk.image_new_from_stock(gtk.STOCK_DIALOG_WARNING,
                                        gtk.ICON_SIZE_SMALL_TOOLBAR)
        self.btnConflict.add(icon)
        self.btnConflict.set_no_show_all(True) #avoid the button taking
                                               # over control again
        vbox.add(self.btnConflict)    # vbox reserves space while button
        #vbox.set_size_request(32, 28) # is hidden
        self.conflictIcon = vbox

        self.btnConflict.connect("clicked", self.on_btnConflict_clicked)
        icon.show()

        self.constraints = [c for c in ppd.constraints
                            if c.option1 == option.keyword]
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
            option2 = self.gui.options.get(constraint.option2, None)
            if option2 is None: continue

            if (constraint.choice1==value and
                option2.get_current_value() == constraint.choice2):
                # conflict
                self.conflicts.add(constraint)
                if update_others:
                    option2.checkConflicts(update_others=False)
            elif constraint in self.conflicts:
                # remove conflict
                self.conflicts.remove(constraint)
                option2.checkConflicts(update_others=False)


        tooltip = [_("Conflicts with:")]
        for c in self.conflicts:
            option = self.gui.options.get(c.option2)
            tooltip.append(option.option.text)
            
        tooltip = "\n".join(tooltip)

        self.conflict_message = tooltip # XXX more verbose
            
        if self.conflicts:
            self.gui.tooltips.set_tip(self.btnConflict, tooltip,
                                      "OPTION-" + self.option.keyword)
            self.btnConflict.show()
        else:
            self.btnConflict.hide()

        self.gui.option_changed(self)
        return self.conflicts
            
    def on_change(self, widget):
        self.checkConflicts()

    def on_btnConflict_clicked(self, button):
        self.dialog.set_markup(self.conflict_message)
        self.dialog.run()
        self.dialog.hide()
        
# ---------------------------------------------------------------------------

class OptionBool(Option):

    def __init__(self, option, ppd, gui, tab_label=None):
        self.selector = gtk.CheckButton(option.text)
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
        self.selector = gtk.combo_box_new_text()
        #self.selector.set_alignment(0.0, 0.5)

        label = option.text
        if not label.endswith (':'):
            label += ':'
        self.label = gtk.Label(label)
        self.label.set_alignment(0.0, 0.5)
        
        selected = None
        for nr, choice in enumerate(option.choices):
            self.selector.append_text(choice['text'])
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
        

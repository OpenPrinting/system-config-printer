import gtk.glade, cups

def OptionWidget(option, ppd, gui):
    """Factory function"""
    if option.ui == cups.PPD_UI_BOOLEAN:
        return OptionBool(option, ppd, gui)
    elif option.ui == cups.PPD_UI_PICKONE:
        return OptionPickOne(option, ppd, gui)
    elif option.ui == cups.PPD_UI_PICKMANY:
        return OptionPickMany(option, ppd, gui)

# ---------------------------------------------------------------------------

class Option:
    def __init__(self, option, ppd, gui):
        self.option = option
        self.ppd = ppd
        self.gui = gui
        self.eventbox = gtk.EventBox()
        self.imgConflict = gtk.image_new_from_stock("gtk-dialog-warning", 4)
        self.imgConflict.set_padding(10, 3)
        self.imgConflict.hide()
        self.imgConflict.set_no_show_all(True)
        self.eventbox.add(self.imgConflict)
        self.conflictIcon = self.eventbox

        self.constraints = [c for c in ppd.constraints
                            if c.option1 == option.keyword]
        #for c in self.constraints:
        #    if not c.choice1 or not c.choice2:
        #        print c.option1, repr(c.choice1), c.option2, repr(c.choice2)
        self.conflicts = set()
        
    def is_changed(self):
        raise NotImplemented

    def get_current_value(self):
        raise NotImplemented

    def is_changed(self):
        return self.get_current_value()!= self.option.defchoice
    
    def writeback(self):
        #print repr(self.option.keyword), repr(self.get_current_value())
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


        tooltip = ["Conflicts with:"] # XXX i18n
        for c in self.conflicts:
            option = self.gui.options.get(c.option2)
            tooltip.append(option.option.text)
            
        tooltip = "\n".join(tooltip)
            
        if self.conflicts:
            self.gui.tooltips.set_tip(self.eventbox, tooltip,
                                      "OPTION-" + self.option.keyword)
            self.imgConflict.show()
        else:
            self.imgConflict.hide()

        self.gui.option_changed(self)
        return self.conflicts
            
    def on_change(self, widget):
        self.checkConflicts()

# ---------------------------------------------------------------------------

class OptionBool(Option):

    def __init__(self, option, ppd, gui):
        self.selector = gtk.CheckButton(option.text)
        self.label = None
        self.selector.set_active(option.defchoice == 'True')
        self.selector.set_alignment(0.0, 0.5)
        self.selector.connect("toggled", self.on_change)
        Option.__init__(self, option, ppd, gui)

    def get_current_value(self):
        return ('False', 'True')[self.selector.get_active()]

# ---------------------------------------------------------------------------

class OptionPickOne(Option):
    widget_name = "OptionPickOne"

    def __init__(self, option, ppd, gui):
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

        Option.__init__(self, option, ppd, gui)

    def get_current_value(self):
        return self.option.choices[self.selector.get_active()]['choice']
        
# ---------------------------------------------------------------------------

class OptionPickMany(OptionPickOne):
    widget_name = "OptionPickMany"

    def __init__(self, option, ppd, gui):
        raise NotImplemented
        Option.__init__(self, option, ppd, gui)
        

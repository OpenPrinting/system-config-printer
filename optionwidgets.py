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
    
    dialog = gtk.MessageDialog(parent=None, flags=0, type=gtk.MESSAGE_WARNING,
                               buttons=gtk.BUTTONS_OK)
    
    def __init__(self, option, ppd, gui):
        self.option = option
        self.ppd = ppd
        self.gui = gui

        vbox = gtk.VBox()
        
        self.btnConflict = gtk.Button(stock="gtk-dialog-warning")
        # tailor the button to our needs
        btnhbox = self.btnConflict.get_child().get_children()[0]
        img, label = btnhbox.get_children()
        img.show()
        label.hide()
        self.btnConflict.set_no_show_all(True) #avoid the button taking
                                               # over control again

        vbox.add(self.btnConflict)    # vbox reserves space while button
        vbox.set_size_request(32, 28) # is hidden
        self.conflictIcon = vbox

        self.btnConflict.connect("clicked", self.on_btnConflict_clicked)

        self.constraints = [c for c in ppd.constraints
                            if c.option1 == option.keyword]
        #for c in self.constraints:
        #    if not c.choice1 or not c.choice2:
        #        print c.option1, repr(c.choice1), c.option2, repr(c.choice2)
        self.conflicts = set()
        self.conflict_message = ""
        
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
        
# ---------------------------------------------------------------------------

class NonPPDOptionPickOne(OptionPickOne):
    
    def __init__(self, label, default, supported, gui):
        self.default = default
        self.supported = supported

        self.selector = gtk.combo_box_new_text()
        
        label = option.text
        if not label.endswith (':'):
            label += ':'
        self.label = gtk.Label(label)
        self.label.set_alignment(0.0, 0.5)
        
        selected = None
        for nr, choice in enumerate(supported):
            self.selector.append_text(choice)
            if default == choice:
                selected = nr
        if selected is not None:
            self.selector.set_active(selected)
        else:
            print "unknown value:", default
        self.selector.connect("changed", self.on_change)

    def on_change(self, widget):
        pass

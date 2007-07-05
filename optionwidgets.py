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
        label = option.text
        if not label.endswith (':'):
            label += ':'
        self.label = gtk.Label(label)
        self.label.set_alignment(0.0, 0.5)

    def is_changed(self):
        raise NotImplemented

    def get_current_value(self):
        raise NotImplemented

    def is_changed(self):
        return self.get_current_value()!= self.option.defchoice
    
    def writeback(self):
        self.ppd.markOption(self.option.keyword, self.get_current_value())

    def on_change(self, widget):
        value = self.get_current_value()
        for constraint in self.ppd.constraints:
            if constraint.option1 == self.option.keyword:
                if (not constraint.choice1 or
                    constraint.choice1==value):
                    option = self.gui.options.get(constraint.option2, None)
                    if option is None: continue
                    
                    #if not contraint.choice2 or  
                    print (constraint.option1, constraint.choice1,
                           constraint.option2, constraint.choice2)
        self.gui.option_changed(self, self.is_changed())

# ---------------------------------------------------------------------------

class OptionBool(Option):

    def __init__(self, option, ppd, gui):
        self.selector = gtk.CheckButton (option.text)
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
        
        selected = None
        for nr, choice in enumerate(option.choices):
            self.selector.append_text(choice['text'])
            if option.defchoice == choice['choice']:
                selected = nr
        if selected is not None:
            self.selector.set_active(selected)
        else:
            print option.text, "unknown value"
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
        

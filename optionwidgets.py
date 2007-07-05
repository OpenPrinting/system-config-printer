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
        self.label = gtk.Label(option.text)
        self.label.set_alignment(0.0, 0.5)
        
# ---------------------------------------------------------------------------

class OptionBool(Option):

    def __init__(self, option, ppd, gui):
        Option.__init__(self, option, ppd, gui)
        self.selector = gtk.CheckButton (option.text)
        self.label = None
        self.selector.set_active(option.defchoice == 'True')
        self.selector.set_alignment(0.0, 0.5)

    def writeback(self):
        self.ppd.markOption(
            self.option.keyword,
            ('False', 'True')[not self.selector.get_active()])

# ---------------------------------------------------------------------------

class OptionPickOne(Option):
    widget_name = "OptionPickOne"

    def __init__(self, option, ppd, gui):
        Option.__init__(self, option, ppd, gui)
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

    def writeback(self):
        self.ppd.markOption(
            self.option.keyword,
            self.option.choices[self.selector.get_active()]['choice'])
        
            
# ---------------------------------------------------------------------------

class OptionPickMany(OptionPickOne):
    widget_name = "OptionPickMany"

    def __init__(self, option, ppd, gui):
        raise NotImplemented
        Option.__init__(self, option, ppd, gui)
        

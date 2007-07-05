import gtk

def OptionWidget(name, v, s, on_change):

    if isinstance(v, int):
        if (isinstance(s, int) or
            (isinstance(s, tuple) and len(s)==2 and
             isinstance(s[0], int) and isinstance(s[1], int))):
            return OptionNumeric(name, v, s, on_change)
        elif isinstance(s, list):
            for sv in s:
                if not isinstance(sv, int):
                    return OptionSelectOne(name, v, s, on_change)
            return OptionSelectOneNumber(name, v, s, on_change)
    elif isinstance(v, str):
        if isinstance(s, list):
            for sv in s:
                if not isinstance(sv, str):
                    raise ValueError
            return OptionSelectOne(name, v, s, on_change)
        elif isinstance(s, str):
            return OptionText(name, v, s, on_change)
        else:
            raise ValueError
    elif isinstance(v, list) and isinstance(s, list):
        for vv in v + s:
            if not isinstance(vv, str): raise ValueError
        return OptionSelectMany(name, v, s, on_change)
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
        return self.is_new or self.get_current_value()!= self.value

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
            if value == choice:
                selected = nr
        if selected is not None:
            self.selector.set_active(selected)
        else:
            print "Unknown value:", default
        self.selector.connect("changed", self.changed)

    def get_current_value(self):
        return self.selector.get_active_text()

# ---------------------------------------------------------------------------

class OptionSelectOneNumber(OptionSelectOne):

    def get_current_value(self):
        return int(self.selector.get_active_text())

# ---------------------------------------------------------------------------

class OptionSelectMany(Option):
    # XXX
    pass

# ---------------------------------------------------------------------------

class OptionNumeric(Option):
    def __init__(self, name, value, supported, on_change):
        if isinstance(supported, int):
            supported = (0, supported)
        Option.__init__(self, name, value, supported, on_change)

        adj = gtk.Adjustment(value, supported[0], supported[1], 1.0, 5.0, 0.0)
        self.selector = gtk.SpinButton(adj, climb_rate=1.0)
        self.selector.set_numeric(True)
        self.selector.connect("changed", self.changed)

    def get_current_value(self):
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

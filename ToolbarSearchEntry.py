import gtk
import sexy
import HIG
from gettext import gettext as _

class ToolbarSearchEntry (gtk.HBox):
    def __init__ (self):
        gtk.HBox.__init__ (self, spacing = HIG.PAD_NORMAL)
        self.set_border_width (HIG.PAD_NORMAL)

        find_image = gtk.image_new_from_stock (gtk.STOCK_FIND,
                                               gtk.ICON_SIZE_MENU)
        self.entry = sexy.IconEntry ()
        self.entry.set_icon (sexy.ICON_ENTRY_PRIMARY, find_image)
        self.entry.add_clear_button ()

        search_label = gtk.Label ()
        search_label.set_text_with_mnemonic (_("_Search:"))
        search_label.set_mnemonic_widget (self.entry)

        self.add (search_label)
        self.add (self.entry)

        self.entry.connect ('changed', self.on_entry_text_changed)

    def on_entry_text_changed (self, unused):
        text = self.entry.get_text ()


import gobject
import gtk
from gettext import gettext as _

class GroupsPane:
    def __init__ (self, treeview):
        self.list_store = None
        self.all_printers_iter = None
        self.selection = None

        self.list_store = gtk.ListStore (gtk.gdk.Pixbuf,        # icon
                                         gobject.TYPE_STRING,   # label
                                         gobject.TYPE_BOOLEAN)  # separator?
        treeview.set_model (self.list_store)
        tvcolumn = gtk.TreeViewColumn ()
        treeview.append_column (tvcolumn)
        pixbuf_cell = gtk.CellRendererPixbuf ()
        text_cell = gtk.CellRendererText ()
        tvcolumn.pack_start (pixbuf_cell, False)
        tvcolumn.pack_start (text_cell, False)
        tvcolumn.add_attribute (pixbuf_cell, 'pixbuf', 0)
        tvcolumn.add_attribute (text_cell, 'markup', 1)

        theme = gtk.icon_theme_get_default ()
        try:
            pixbuf = theme.load_icon ('gnome-dev-printer',
                                      gtk.ICON_SIZE_MENU, 0)
        except gobject.GError:
            pixbuf = None

        self.all_printers_iter = self.list_store.append (row = [pixbuf,
                                                                _("All Printers"),
                                                                False])

        self.selection = treeview.get_selection ()
        self.selection.select_iter (self.all_printers_iter)

        treeview.set_row_separator_func (self.row_separator_func)
        self.list_store.append (row = [None, None, True])

    def set_searching (self):
        self.selection.unselect_all ()

    def unset_searching (self):
        self.selection.select_iter (self.all_printers_iter)

    def row_separator_func (self, model, iter):
        return model.get_value (iter, 2)

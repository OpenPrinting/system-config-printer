import gobject
import gtk
from gettext import gettext as _

class GroupsPane:
    def __init__ (self, treeview):
        list_store = gtk.ListStore (gtk.gdk.Pixbuf,
                                    gobject.TYPE_STRING)
        treeview.set_model (list_store)
        tvcolumn = gtk.TreeViewColumn ()
        treeview.append_column (tvcolumn)
        pixbuf_cell = gtk.CellRendererPixbuf ()
        text_cell = gtk.CellRendererText ()
        tvcolumn.pack_start (pixbuf_cell, False)
        tvcolumn.pack_start (text_cell, False)
        tvcolumn.add_attribute (pixbuf_cell, 'pixbuf', 0)
        tvcolumn.add_attribute (text_cell, 'text', 1)

        theme = gtk.icon_theme_get_default ()
        try:
            pixbuf = theme.load_icon ('gnome-dev-printer',
                                      gtk.ICON_SIZE_INVALID, 0)
        except gobject.GError:
            pixbuf = None

        iter = list_store.append (row = [pixbuf, _("All Printers")])

        selection = treeview.get_selection ()
        selection.select_iter (iter)

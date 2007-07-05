SUBDIRS=po

SOURCES=cupsd.py         \
	cupshelpers.py   \
	foomatic.py      \
	nametree.py      \
	options.py       \
	optionwidgets.py \
	probe_printer.py \
	system-config-printer.py \
	system-config-printer \
	gtk_label_autowrap.py \
	gtk_html2pango.py

EXTRA_DIST=\
	$(SOURCES) \
	bootstrap \
	system-config-printer.glade \
	system-config-printer.gladep \
	system-config-printer.desktop

tag:
	cvs tag -c @PACKAGE@-`echo @VERSION@ | tr . _`

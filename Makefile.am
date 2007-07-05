SUBDIRS=po
nobase_pkgdata_SCRIPTS=				\
	config.py				\
	cupsd.py				\
	cupshelpers.py				\
	foomatic.py				\
	nametree.py				\
	options.py				\
	optionwidgets.py			\
	probe_printer.py			\
	pysmb.py				\
	system-config-printer.py		\
	gtk_label_autowrap.py			\
	gtk_html2pango.py

nobase_pkgdata_DATA=\
	system-config-printer.glade

nobase_sbin_SCRIPTS=\
	system-config-printer

EXTRA_DIST=\
	$(nobase_pkgdata_SCRIPTS) \
	$(nobase_pkgdata_DATA) \
	$(nobase_sbin_SCRIPTS) \
	bootstrap \
	mkinstalldirs \
	system-config-printer.gladep \
	system-config-printer.desktop

tag:
	cvs tag -c @PACKAGE@-`echo @VERSION@ | tr . _`

DISTCLEANFILES=*.pyc *.pyo *~ *.bak

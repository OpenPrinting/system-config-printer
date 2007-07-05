SUBDIRS=po
nobase_pkgdata_SCRIPTS=				\
	ppds.py					\
	pysmb.py				\
	system-config-printer.py		\
	applet.py

nobase_pkgdata_DATA=				\
	config.py				\
	cupsd.py				\
	cupshelpers.py				\
	foomatic.py				\
	nametree.py				\
	options.py				\
	optionwidgets.py			\
	probe_printer.py			\
	gtk_label_autowrap.py			\
	gtk_html2pango.py			\
	system-config-printer.glade		\
	applet.glade				\
	applet.png				\
	inspecting-printer.png

nobase_sbin_SCRIPTS=\
	system-config-printer

bin_SCRIPTS=\
	system-config-printer-applet

man_MANS=					\
	man/system-config-printer.1		\
	man/system-config-printer-applet.1

dbus_DATA =\
	newprinternotification.conf
dbusdir = $(sysconfdir)/dbus-1/system.d/

desktop_DATA =\
	system-config-printer.desktop \
	print-applet.desktop \
	manage-print-jobs.desktop
desktopdir = $(datadir)/applications/
autostartdir = $(sysconfdir)/xdg/autostart/

install-desktopDATA: $(desktop_DATA)
	mkdir -p $(DESTDIR)$(desktopdir)
	mkdir -p $(DESTDIR)$(desktopdir)
	desktop-file-install --vendor redhat	\
	  --dir $(DESTDIR)$(desktopdir)		\
	  --add-category X-Red-Hat-Base		\
	  --add-category System			\
	  --add-category Settings		\
	  --add-category GTK			\
	  system-config-printer.desktop
	desktop-file-install --vendor redhat	\
	  --dir $(DESTDIR)$(desktopdir)		\
	  --add-category X-Red-Hat-Base		\
	  --add-category System			\
	  --add-category Monitor		\
	  --add-category GTK			\
	  manage-print-jobs.desktop
	desktop-file-install --vendor redhat	\
	  --dir $(DESTDIR)$(autostartdir)	\
	  --add-category X-Red-Hat-Base		\
	  --add-category System			\
	  --add-category Monitor		\
	  --add-category TrayIcon		\
	  --add-category GTK			\
	  print-applet.desktop

uninstall-desktopDATA:
	rm -f $(DESTDIR)$(desktopdir)/redhat-system-config-printer.desktop
	rm -f $(DESTDIR)$(desktopdir)/redhat-manage-print-jobs.desktop
	rm -f $(DESTDIR)$(autostartdir)/redhat-print-applet.desktop

EXTRA_DIST=\
	$(nobase_pkgdata_SCRIPTS) \
	$(nobase_pkgdata_DATA) \
	$(nobase_sbin_SCRIPTS) \
	$(bin_SCRIPTS) \
	man/system-config-printer.xml \
	newprinternotification.conf \
	bootstrap \
	mkinstalldirs \
	system-config-printer.gladep \
	system-config-printer.desktop.in \
	manage-print-jobs.desktop.in \
	print-applet.desktop.in \
	applet.png \
	intltool-extract.in \
	intltool-merge.in \
	intltool-update.in

desktop_in_files = $(desktop_DATA:.desktop=.desktop.in)

@INTLTOOL_DESKTOP_RULE@

# The man pages are generated from DocBook XML.
$(man_MANS): $(top_srcdir)/man/system-config-printer.xml
	xmlto man -o man $<

tag:
	cvs tag -c @PACKAGE@-`echo @VERSION@ | tr . _`

distcheck-hook: update-po

update-po:
	$(MAKE) -C po update-po

missing-languages:
	bash -c '\
	eval $$(grep ALL_LINGUAS configure.in); \
	diff -u <(echo $$ALL_LINGUAS | xargs -rn1 echo) \
		<(cd po; ls -1 *.po | sed -e "s,\.po$$,,")'

DISTCLEANFILES=*.pyc *.pyo *~ *.bak \
	intltool-extract intltool-merge intltool-update \
	*.desktop man/*.1

.PHONY: update-po

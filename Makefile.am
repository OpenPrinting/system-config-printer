SUBDIRS=po
nobase_pkgdata_SCRIPTS=				\
	my-default-printer.py			\
	ppds.py					\
	pysmb.py				\
	system-config-printer.py		\
	applet.py

nobase_pkgdata_DATA=				\
	config.py				\
	cupshelpers.py				\
	options.py				\
	optionwidgets.py			\
	probe_printer.py			\
	gtk_label_autowrap.py			\
	gtk_treeviewtooltips.py			\
	system-config-printer.glade		\
	applet.glade

nobase_sbin_SCRIPTS=\
	system-config-printer

bin_SCRIPTS=\
	system-config-printer-applet		\
	my-default-printer

man_MANS=					\
	man/system-config-printer.1		\
	man/system-config-printer-applet.1

dbus_DATA =\
	newprinternotification.conf
dbusdir = $(sysconfdir)/dbus-1/system.d/

desktop_DATA =\
	system-config-printer.desktop \
	print-applet.desktop \
	manage-print-jobs.desktop \
	my-default-printer.desktop
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
	  --add-category HardwareSettings	\
	  --add-category Printing		\
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
	  --dir $(DESTDIR)$(desktopdir)		\
	  --add-category X-Red-Hat-Base		\
	  --add-category Settings		\
	  --add-category HardwareSettings	\
	  --add-category GTK			\
	  my-default-printer.desktop
	desktop-file-install --vendor redhat	\
	  --dir $(DESTDIR)$(autostartdir)	\
	  --add-category X-Red-Hat-Base		\
	  --add-category System			\
	  --add-category Monitor		\
	  --add-category GTK			\
	  print-applet.desktop

uninstall-desktopDATA:
	rm -f $(DESTDIR)$(desktopdir)/redhat-system-config-printer.desktop
	rm -f $(DESTDIR)$(desktopdir)/redhat-manage-print-jobs.desktop
	rm -f $(DESTDIR)$(desktopdir)/redhat-my-default-printer.desktop
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
	my-default-printer.desktop.in \
	print-applet.desktop.in \
	intltool-extract.in \
	intltool-merge.in \
	intltool-update.in

desktop_in_files = $(desktop_DATA:.desktop=.desktop.in)

@INTLTOOL_DESKTOP_RULE@

# The man pages are generated from DocBook XML.
$(man_MANS): $(top_srcdir)/man/system-config-printer.xml
	xmlto man -o man $<

distcheck-hook: update-po

update-po:
	$(MAKE) -C po update-po

missing-languages:
	bash -c '\
	eval $$(grep ALL_LINGUAS configure.in); \
	diff -u <(echo $$ALL_LINGUAS | xargs -rn1 echo) \
		<(cd po; ls -1 *.po | sed -e "s,\.po$$,,")'

fix-glade:
	sed -i -e '/invisible_char/d' -e '/toolbar_style/d' *.glade

run:
	SYSTEM_CONFIG_PRINTER_GLADE=$(top_srcdir)/system-config-printer.glade \
	python $(top_srcdir)/system-config-printer.py

help:
	@echo "Usage: make <target>"
	@echo "Available targets:"
	@echo " help               Show this help message"
	@echo " update-po          Update the translations"
	@echo " missing-languages  Show which po files are not shipped"
	@echo " fix-glade          Sanitize the glade files"
	@echo " run                Run system-config-printer with local glade file"

DISTCLEANFILES=*.pyc *.pyo *~ *.bak \
	intltool-extract intltool-merge intltool-update \
	*.desktop man/*.1

.PHONY: update-po missing-languages fix-glade run help


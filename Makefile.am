SUBDIRS=po

EXPORT_MODULES=\
	ppds.py

python_SCRIPTS = $(EXPORT_MODULES)

nobase_pkgdata_SCRIPTS=				\
	my-default-printer.py			\
	pysmb.py				\
	system-config-printer.py		\
	troubleshoot/__init__.py		\
	applet.py				\
	$(EXPORT_MODULES)

nobase_pkgdata_DATA=					\
	authconn.py					\
	config.py					\
	contextmenu.py					\
	cupshelpers.py					\
	debug.py					\
	errordialogs.py					\
	glade.py					\
	jobviewer.py					\
	monitor.py					\
	openprinting.py					\
	options.py					\
	optionwidgets.py				\
	probe_printer.py				\
	gtk_label_autowrap.py				\
	gtk_treeviewtooltips.py				\
	smburi.py					\
	statereason.py					\
	userdefault.py					\
	glade/AboutDialog.glade				\
	glade/ConnectDialog.glade				\
	glade/ConnectingDialog.glade			\
	glade/InstallDialog.glade				\
	glade/IPPBrowseDialog.glade			\
	glade/job_popupmenu.glade				\
	glade/JobsWindow.glade				\
	glade/NewPrinterName.glade				\
	glade/NewPrinterWindow.glade			\
	glade/printer_context_menu.glade			\
	glade/PrinterPropertiesDialog.glade		\
	glade/PrinterStatusWindow.glade			\
	glade/PrintersWindow.glade				\
	glade/ServerSettingsDialog.glade			\
	glade/SMBBrowseDialog.glade			\
	glade/statusicon_popupmenu.glade			\
	glade/WaitWindow.glade				\
	icons/i-network-printer.png			\
	troubleshoot/base.py				\
	troubleshoot/CheckLocalServerPublishing.py	\
	troubleshoot/CheckNetworkServerSanity.py	\
	troubleshoot/CheckPPDSanity.py			\
	troubleshoot/CheckPrinterSanity.py		\
	troubleshoot/CheckUSBPermissions.py		\
	troubleshoot/ChooseNetworkPrinter.py		\
	troubleshoot/ChoosePrinter.py			\
	troubleshoot/DeviceListed.py			\
	troubleshoot/ErrorLogCheckpoint.py		\
	troubleshoot/ErrorLogFetch.py			\
	troubleshoot/ErrorLogParse.py			\
	troubleshoot/LocalOrRemote.py			\
	troubleshoot/NetworkCUPSPrinterShared.py	\
	troubleshoot/PrinterStateReasons.py		\
	troubleshoot/PrintTestPage.py			\
	troubleshoot/QueueNotEnabled.py			\
	troubleshoot/QueueRejectingJobs.py		\
	troubleshoot/RemoteAddress.py			\
	troubleshoot/SchedulerNotRunning.py		\
	troubleshoot/ServerFirewalled.py		\
	troubleshoot/Shrug.py				\
	troubleshoot/Welcome.py

bin_SCRIPTS=\
	system-config-printer			\
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

html:	$(EXPORT_MODULES)
	rm -rf html
	epydoc -o html --html $(EXPORT_MODULES)

distcheck-hook: update-po

update-po: missing-languages
	$(MAKE) -C po update-po

missing-languages:
	bash -c '\
	eval $$(grep ALL_LINGUAS configure.in); \
	diff -u <(echo $$ALL_LINGUAS | xargs -rn1 echo) \
		<(cd po; ls -1 *.po | sed -e "s,\.po$$,,")'

fix-glade:
	sed -i -e '/invisible_char/d' -e '/toolbar_style/d' $(top_srcdir)/glade/*.glade

run:
	SYSTEM_CONFIG_PRINTER_GLADE=$(top_srcdir)/glade \
	python $(top_srcdir)/system-config-printer.py --debug

run-applet:
	SYSTEM_CONFIG_PRINTER_GLADE=$(top_srcdir)/glade \
	python $(top_srcdir)/applet.py --debug

help:
	@echo "Usage: make <target>"
	@echo "Available targets:"
	@echo " help               Show this help message"
	@echo " update-po          Update the translations"
	@echo " missing-languages  Show which po files are not shipped"
	@echo " fix-glade          Sanitize the glade files"
	@echo " run                Run system-config-printer with local glade file"
	@echo " run-applet         Run system-config-printer-applet with local glade file"

test-ppd-module.sh:
	echo "#!/bin/sh" > "$@"
	echo "python $(top_srcdir)/ppds.py" >> "$@"
	chmod 755 "$@"

TESTS = test-ppd-module.sh

DISTCLEANFILES=*.pyc *.pyo *~ *.bak \
	troubleshoot/*.pyc troubleshoot/*.pyo troubleshoot/*~ \
	intltool-extract intltool-merge intltool-update \
	*.desktop man/*.1 \
	test-ppd-module.sh pickled-ppds

distclean-local:
	rm -rf html

.PHONY: update-po missing-languages fix-glade run help


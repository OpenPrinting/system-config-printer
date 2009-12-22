AM_CFLAGS=-g -O2 -Wall

SUBDIRS=po

EXPORT_MODULES=					\
	cupshelpers/__init__.py			\
	cupshelpers/cupshelpers.py		\
	cupshelpers/ppds.py			\
	cupshelpers/openprinting.py

### Automake hooks for Distutils.
# The distutils module doesn't understand srcdir != builddir,
# so we copy in, along with the cupshelpers modules, into
# the builddir for 'all', 'install-exec', and 'clean' hooks.
.stamp-distutils-in-builddir:	setup.py $(EXPORT_MODULES)
	if [ "$(top_srcdir)" != "$(top_builddir)" ]; then	\
		cp $(top_srcdir)/setup.py .;			\
		mkdir cupshelpers;				\
		for file in $(EXPORT_MODULES); do		\
			cp $(top_srcdir)/$$file $$file;		\
		done;						\
	fi
	touch .stamp-distutils-in-builddir

dist-hook: mk-ChangeLog
.PHONE: mk-ChangeLog
mk-ChangeLog:
	if test -d .git; then				\
	  $(top_srcdir)/gitlog-to-changelog		\
	    --since=2009-05-01 -- --no-merges		\
	    > $(distdir)/cl ;				\
	  mv -f $(distdir)/cl $(distdir)/ChangeLog ;	\
	fi

config.py: config.py.in Makefile
	sed \
	  -e "s|\@prefix\@|$(prefix)|" \
	  -e "s|\@datadir\@|$(datadir)|" \
	  -e "s|\@localedir\@|$(localedir)|" \
	  -e "s|\@VERSION\@|$(VERSION)|" \
	  -e "s|\@PACKAGE\@|$(PACKAGE)|" \
	  -e "s|\@WITH_POLKIT_1\@|$(WITH_POLKIT_1)|" \
	  $< > $@

# Use distutils to build the module.
all-local: .stamp-distutils-in-builddir config.py
	$(PYTHON) setup.py build

# Use distutils to install the module.
install-exec-local: .stamp-distutils-in-builddir
	$(PYTHON) setup.py install --prefix=$(DESTDIR)$(prefix)

# Uninstall the module, crossing our fingers that we know enough
# about how distutils works to do this.  Unfortunately, distutils
# doesn't provide a way to do this itself.
uninstall-local:
	rm -f $(DESTDIR)/$(pythondir)/cupshelpers*.egg-info
	for file in $(EXPORT_MODULES); do				\
		rm -f $(DESTDIR)/$(pythondir)/$$file*;			\
	done

# Tell distutils to clean up.
clean-local:
	-$(PYTHON) setup.py clean --all
	if [ "$(top_srcdir)" != "$(top_builddir)" ]; then	\
		rm -f setup.py;					\
		for file in $(EXPORT_MODULES); do		\
			rm -f $$file*;				\
		done;						\
	fi
	rm -f .stamp-distutils-in-builddir

nobase_pkgdata_SCRIPTS=				\
	my-default-printer.py			\
	pysmb.py				\
	system-config-printer.py		\
	troubleshoot/__init__.py		\
	applet.py

nobase_pkgdata_DATA=					\
	AdvancedServerSettings.py			\
	asyncconn.py					\
	asyncipp.py					\
	asyncpk0.py					\
	asyncpk1.py					\
	authconn.py					\
	config.py					\
	cupspk.py					\
	debug.py					\
	errordialogs.py					\
	HIG.py						\
	firewall.py					\
	glade.py					\
	GroupsPane.py					\
	GroupsPaneModel.py				\
	gtkinklevel.py					\
	gtkspinner.py					\
	installpackage.py				\
	jobviewer.py					\
	monitor.py					\
	options.py					\
	optionwidgets.py				\
	PhysicalDevice.py				\
	ppdippstr.py					\
	probe_printer.py				\
	gtk_label_autowrap.py				\
	SearchCriterion.py				\
	smburi.py					\
	statereason.py					\
	timedops.py					\
	ToolbarSearchEntry.py				\
	userdefault.py					\
	XmlHelper.py					\
	glade/AboutDialog.glade				\
	glade/ConnectDialog.glade			\
	glade/ConnectingDialog.glade			\
	glade/InstallDialog.glade			\
	glade/JobsWindow.glade				\
	glade/NewPrinterName.glade			\
	glade/NewPrinterWindow.glade			\
	glade/PrinterPropertiesDialog.glade		\
	glade/PrintersWindow.glade			\
	glade/ServerSettingsDialog.glade		\
	glade/SMBBrowseDialog.glade			\
	glade/statusicon_popupmenu.glade		\
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
	troubleshoot/Locale.py				\
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

if UDEV_RULES
udevrulesdir=/lib/udev/rules.d
udevrules_DATA=udev/70-printers.rules
udev_udev_configure_printer_SOURCES=\
	udev/udev-configure-printer.c
udev_udev_configure_printer_LDADD=-lcups -ludev -lusb
udevhelperdir=/lib/udev
udevhelper_PROGRAMS=\
	udev/udev-configure-printer
udevhelper_SCRIPTS=\
	udev/udev-add-printer
endif

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

DESKTOP_VENDOR=@DESKTOPVENDOR@
DESKTOP_PREFIX=@DESKTOPPREFIX@

install-desktopDATA: $(desktop_DATA)
	mkdir -p $(DESTDIR)$(desktopdir)
	mkdir -p $(DESTDIR)$(desktopdir)
	desktop-file-install $(DESKTOP_VENDOR)	\
	  --dir $(DESTDIR)$(desktopdir)		\
	  --add-category System			\
	  --add-category Settings		\
	  --add-category HardwareSettings	\
	  --add-category Printing		\
	  --add-category GTK			\
	  system-config-printer.desktop
	desktop-file-install $(DESKTOP_VENDOR)	\
	  --dir $(DESTDIR)$(desktopdir)		\
	  --add-category System			\
	  --add-category Monitor		\
	  --add-category GTK			\
	  manage-print-jobs.desktop
	desktop-file-install $(DESKTOP_VENDOR)	\
	  --dir $(DESTDIR)$(desktopdir)		\
	  --add-category Settings		\
	  --add-category HardwareSettings	\
	  --add-category GTK			\
	  my-default-printer.desktop
	desktop-file-install $(DESKTOP_VENDOR)	\
	  --dir $(DESTDIR)$(autostartdir)	\
	  --add-category System			\
	  --add-category Monitor		\
	  --add-category GTK			\
	  print-applet.desktop

uninstall-desktopDATA:
	rm -f $(DESTDIR)$(desktopdir)/$(DESKTOP_PREFIX)system-config-printer.desktop
	rm -f $(DESTDIR)$(desktopdir)/$(DESKTOP_PREFIX)manage-print-jobs.desktop
	rm -f $(DESTDIR)$(desktopdir)/$(DESKTOP_PREFIX)my-default-printer.desktop
	rm -f $(DESTDIR)$(autostartdir)/$(DESKTOP_PREFIX)print-applet.desktop

EXTRA_DIST=\
	$(nobase_pkgdata_SCRIPTS) \
	$(nobase_pkgdata_DATA) \
	$(nobase_sbin_SCRIPTS) \
	$(bin_SCRIPTS) \
	udev/udev-add-printer \
	setup.py \
	$(EXPORT_MODULES) \
	man/system-config-printer.xml \
	newprinternotification.conf \
	bootstrap \
	mkinstalldirs \
	ChangeLog-OLD \
	system-config-printer.desktop.in \
	manage-print-jobs.desktop.in \
	my-default-printer.desktop.in \
	print-applet.desktop.in \
	intltool-extract.in \
	intltool-merge.in \
	intltool-update.in \
	config.py.in \
	udev/70-printers.rules

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

run:	config.py
	SYSTEM_CONFIG_PRINTER_GLADE=$(top_srcdir)/glade \
	$(PYTHON) $(top_srcdir)/system-config-printer.py --debug

run-applet:	config.py
	SYSTEM_CONFIG_PRINTER_GLADE=$(top_srcdir)/glade \
	$(PYTHON) $(top_srcdir)/applet.py --debug

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
	echo "#!$(PYTHON)" > "$@"
	echo "import sys; sys.path.append ('$(top_srcdir)')" >> "$@"
	echo "from cupshelpers.ppds import _self_test" >> "$@"
	echo "_self_test(sys.argv)" >> "$@"
	chmod 755 "$@"

TESTS = test-ppd-module.sh

DISTCLEANFILES=*.pyc *.pyo *~ *.bak \
	troubleshoot/*.pyc troubleshoot/*.pyo troubleshoot/*~ \
	intltool-extract intltool-merge intltool-update \
	*.desktop man/*.1 \
	test-ppd-module.sh pickled-ppds \
	config.py

distclean-local:
	rm -rf html

.PHONY: update-po missing-languages fix-glade run help


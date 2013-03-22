CFLAGS=-g -O2 -Wall

SUBDIRS=po

EXPORT_MODULES=					\
	cupshelpers/__init__.py			\
	cupshelpers/cupshelpers.py		\
	cupshelpers/installdriver.py		\
	cupshelpers/ppds.py			\
	cupshelpers/openprinting.py		\
	cupshelpers/xmldriverprefs.py

EXPORT_MODULES_GEN=				\
	cupshelpers/config.py

### Automake hooks for Distutils.
# The distutils module doesn't understand srcdir != builddir,
# so we copy in, along with the cupshelpers modules, into
# the builddir for 'all', 'install-exec', and 'clean' hooks.
.stamp-distutils-in-builddir:	setup.py $(EXPORT_MODULES)
	if [ "$(top_srcdir)" != "$(top_builddir)" ]; then	\
		cp $(top_srcdir)/setup.py .;			\
		$(mkdir_p) cupshelpers;				\
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
	  $< > $@

cupshelpers/config.py: cupshelpers/config.py.in Makefile
	$(mkdir_p) cupshelpers
	sed \
	  -e "s|\@prefix\@|$(prefix)|" \
	  -e "s|\@sysconfdir\@|$(sysconfdir)|" \
	  -e "s|\@cupsserverbindir\@|$(cupsserverbindir)|" \
	  $< > $@

# Use distutils to build the module.
all-local: .stamp-distutils-in-builddir config.py cupshelpers/config.py
	$(PYTHON) setup.py build

# Use distutils to install the module.
install-exec-local: .stamp-distutils-in-builddir
	$(PYTHON) setup.py install --prefix=$(DESTDIR)$(prefix)

# Uninstall the module, crossing our fingers that we know enough
# about how distutils works to do this.  Unfortunately, distutils
# doesn't provide a way to do this itself.
uninstall-local:
	rm -f $(DESTDIR)/$(pythondir)/cupshelpers*.egg-info
	for file in $(EXPORT_MODULES) $(EXPORT_MODULES_GEN); do	\
		rm -f $(DESTDIR)/$(pythondir)/$$file*;		\
	done

# Tell distutils to clean up.
clean-local:
	-$(PYTHON) setup.py clean --all
	if [ "$(top_srcdir)" != "$(top_builddir)" ]; then	\
		rm -f setup.py;					\
		for file in $(EXPORT_MODULES)			\
			$(EXPORT_MODULES_GEN); do		\
			rm -f $$file*;				\
		done;						\
	fi
	rm -f .stamp-distutils-in-builddir

nobase_pkgdata_SCRIPTS=				\
	check-device-ids.py			\
	pysmb.py				\
	scp-dbus-service.py			\
	system-config-printer.py		\
	install-printerdriver.py		\
	troubleshoot/__init__.py		\
	applet.py

nobase_pkgdata_DATA=					\
	asyncconn.py					\
	asyncipp.py					\
	asyncpk1.py					\
	authconn.py					\
	config.py					\
	cupspk.py					\
	debug.py					\
	dnssdresolve.py					\
	errordialogs.py					\
	HIG.py						\
	firewallsettings.py					\
	gui.py						\
	gtkinklevel.py					\
	installpackage.py				\
	jobviewer.py					\
	monitor.py					\
	newprinter.py					\
	options.py					\
	optionwidgets.py				\
	PhysicalDevice.py				\
	ppdcache.py					\
	ppdippstr.py					\
	ppdsloader.py					\
	printerproperties.py				\
	probe_printer.py				\
	SearchCriterion.py				\
	serversettings.py				\
	smburi.py					\
	statereason.py					\
	timedops.py					\
	ToolbarSearchEntry.py				\
	userdefault.py					\
	ui/AboutDialog.ui				\
	ui/ConnectDialog.ui				\
	ui/ConnectingDialog.ui				\
	ui/InstallDialog.ui				\
	ui/JobsWindow.ui				\
	ui/NewPrinterName.ui				\
	ui/NewPrinterWindow.ui				\
	ui/PrinterPropertiesDialog.ui			\
	ui/PrintersWindow.ui				\
	ui/ServerSettingsDialog.ui			\
	ui/SMBBrowseDialog.ui				\
	ui/statusicon_popupmenu.ui			\
	ui/WaitWindow.ui				\
	icons/i-network-printer.png			\
	troubleshoot/base.py				\
	troubleshoot/CheckLocalServerPublishing.py	\
	troubleshoot/CheckNetworkServerSanity.py	\
	troubleshoot/CheckPPDSanity.py			\
	troubleshoot/CheckPrinterSanity.py		\
	troubleshoot/CheckSELinux.py			\
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
	troubleshoot/VerifyPackages.py			\
	troubleshoot/Welcome.py				\
	xml/preferreddrivers.rng			\
	xml/validate.py

cupshelpersdir=$(sysconfdir)/cupshelpers
cupshelpers_DATA=\
	xml/preferreddrivers.xml

bin_SCRIPTS=					\
	system-config-printer			\
	install-printerdriver			\
	system-config-printer-applet		\
	dbus/scp-dbus-service

if UDEV_RULES
udevrulesdir=$(sysconfdir)/udev/rules.d
udevrules_DATA=udev/70-printers.rules
udev_udev_configure_printer_SOURCES=\
	udev/udev-configure-printer.c
udev_udev_configure_printer_LDADD= -lcups -ludev $(libusb_LIBS) $(GLIB_LIBS)
udev_udev_configure_printer_CFLAGS= $(AM_CFLAGS) $(libusb_CFLAGS) $(GLIB_CFLAGS)
udevhelperdir=$(sysconfdir)/udev
udevhelper_PROGRAMS=\
	udev/udev-configure-printer
udevhelper_SCRIPTS=\
	udev/udev-add-printer

if HAVE_SYSTEMD
%.service: %.service.in
	$(AM_V_GEN)sed -e 's,@udevhelperdir\@,$(udevhelperdir),g' $< > $@
systemdsystemunit_DATA = \
	udev/configure-printer@.service
CLEANFILES = \
	$(systemdsystemunit_DATA)
endif

endif

man_MANS=					\
	man/system-config-printer.1		\
	man/system-config-printer-applet.1

dbus_DATA =					\
	dbus/com.redhat.NewPrinterNotification.conf		\
	dbus/com.redhat.PrinterDriversInstaller.conf
dbusdir = $(sysconfdir)/dbus-1/system.d/

dbusinterfaces_DATA =				\
	dbus/org.fedoraproject.Config.Printing.xml
dbusinterfacesdir = $(datadir)/dbus-1/interfaces/

dbusservices_DATA =				\
	dbus/org.fedoraproject.Config.Printing.service
dbusservicesdir = $(datadir)/dbus-1/services/

desktop_DATA =\
	system-config-printer.desktop \
	print-applet.desktop
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
	  --dir $(DESTDIR)$(autostartdir)	\
	  --add-category System			\
	  --add-category Monitor		\
	  --add-category GTK			\
	  print-applet.desktop

uninstall-desktopDATA:
	rm -f $(DESTDIR)$(desktopdir)/$(DESKTOP_PREFIX)system-config-printer.desktop
	rm -f $(DESTDIR)$(autostartdir)/$(DESKTOP_PREFIX)print-applet.desktop

desktop_in_files = $(desktop_DATA:.desktop=.desktop.in)

EXTRA_DIST=\
	$(nobase_pkgdata_SCRIPTS) \
	$(nobase_pkgdata_DATA) \
	$(nobase_sbin_SCRIPTS) \
	$(bin_SCRIPTS) \
	setup.py \
	$(EXPORT_MODULES) \
	man/system-config-printer.xml \
	$(dbus_DATA) \
	$(dbusinterfaces_DATA) \
	$(dbusservices_DATA) \
	bootstrap \
	mkinstalldirs \
	ChangeLog-OLD \
	$(desktop_in_files) \
	intltool-extract.in \
	intltool-merge.in \
	intltool-update.in \
	config.py.in \
	cupshelpers/config.py.in \
	profile-ppds.py \
	udev/udev-add-printer \
	udev/70-printers.rules \
	udev/configure-printer@.service.in \
	xml/preferreddrivers.xml

@INTLTOOL_DESKTOP_RULE@

# The man pages are generated from DocBook XML.
$(man_MANS): $(top_srcdir)/man/system-config-printer.xml
	xmlto man -o man $<

html:	$(EXPORT_MODULES) $(EXPORT_MODULES_GEN)
	rm -rf html
	epydoc -o html --html $(EXPORT_MODULES)

distcheck-hook: update-po missing-imports

update-po: missing-languages
	$(MAKE) -C po update-po

missing-languages:
	bash -c '\
	eval $$(grep ALL_LINGUAS configure.in); \
	diff -u <(echo $$ALL_LINGUAS | xargs -rn1 echo) \
		<(cd po; ls -1 *.po | sed -e "s,\.po$$,,")'

missing-imports:
	s=0; \
	for a in $(top_srcdir)/*.py; do \
		modules=$$(sed -ne 's,^.*except \([a-z]\+\)\..*$$,\1,p' \
				"$$a" | sort -u); \
		for module in $$modules; do \
			if ! grep -q "import \(.*, *\)\?$$module" "$$a"; then \
				echo "$$a should import $$module"; \
				s=1; \
			fi; \
		done; \
	done; \
	exit $$s

run:	config.py cupshelpers/config.py
	SYSTEM_CONFIG_PRINTER_UI=$(top_srcdir)/ui \
	CUPSHELPERS_XMLDIR=$(top_srcdir)/xml \
	$(PYTHON) $(top_srcdir)/system-config-printer.py --debug

run-applet:	config.py cupshelpers/config.py
	$(PYTHON) $(top_srcdir)/applet.py --debug

run-dbus-service:	config.py cupshelpers/config.py
	SYSTEM_CONFIG_PRINTER_UI=$(top_srcdir)/ui \
	CUPSHELPERS_XMLDIR=$(top_srcdir)/xml \
	$(PYTHON) $(top_srcdir)/scp-dbus-service.py --debug

test-xmldriverprefs:	cupshelpers/xmldriverprefs.py xml/preferreddrivers.xml
	python -c 'from cupshelpers.xmldriverprefs import test; test()' \
		2>&1 | less

help:
	@echo "Usage: make <target>"
	@echo "Available targets:"
	@echo " help               Show this help message"
	@echo " update-po          Update the translations"
	@echo " missing-languages  Show which po files are not shipped"
	@echo " run                Run system-config-printer with local UI files"
	@echo " run-applet         Run system-config-printer-applet"
	@echo " run-dbus-service   Run scp-dbus-service with local UI files"
	@echo " test-xmldriverprefs  Show preferred driver order for all models"

test-ppd-module.sh:	FORCE
	echo "#!$(PYTHON)" > "$@"
	echo "import os, sys; sys.path.append ('$(top_srcdir)')" >> "$@"
	echo "os.environ['top_srcdir'] = '$(top_srcdir)'" >> "$@"
	echo "from cupshelpers.ppds import _self_test" >> "$@"
	echo "_self_test(sys.argv)" >> "$@"
	chmod 755 "$@"

test-xml-validity.sh:	FORCE
	echo "#!/bin/bash" > "$@"
	echo "set -e" >> "$@"
	echo "xmllint --relaxng \\" >> "$@"
	echo "    $(top_srcdir)/xml/preferreddrivers.rng \\" >> "$@"
	echo "    $(top_srcdir)/xml/preferreddrivers.xml >/dev/null" >> "$@"
	echo "python $(top_srcdir)/xml/validate.py \\" >> "$@"
	echo "    $(top_srcdir)/xml/preferreddrivers.xml" >> "$@"
	chmod 755 "$@"

TESTS = test-xml-validity.sh test-ppd-module.sh

DISTCLEANFILES=*.pyc *.pyo *~ *.bak \
	troubleshoot/*.pyc troubleshoot/*.pyo troubleshoot/*~ \
	intltool-extract intltool-merge intltool-update \
	*.desktop man/*.1 \
	test-ppd-module.sh test-xml-validity.sh pickled-ppds \
	config.py cupshelpers/config.py

distclean-local:
	rm -rf html

.PHONY: update-po missing-languages run help FORCE

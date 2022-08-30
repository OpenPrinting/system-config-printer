AC_INIT(system-config-printer, 1.5.18)
AC_CONFIG_SRCDIR(system-config-printer.py)
AM_INIT_AUTOMAKE([dist-xz dist-bzip2 subdir-objects 1.6])
AM_GNU_GETTEXT_VERSION(0.20)
AX_REQUIRE_DEFINED([AM_GNU_GETTEXT])
AM_GNU_GETTEXT([external])
AM_PATH_PYTHON([3])
PACKAGE="AC_PACKAGE_NAME"
VERSION="AC_PACKAGE_VERSION"
GETTEXT_PACKAGE="AC_PACKAGE_NAME"
CATOBJEXT=".gmo"
DATADIRNAME=share
AC_SUBST(PACKAGE)
AC_SUBST(VERSION)
AC_SUBST(GETTEXT_PACKAGE)
AC_SUBST(CATOBJEXT)
AC_SUBST(DATADIRNAME)

# Let distributor specify if they want to use a vendor with desktop-file-install
AC_ARG_WITH(desktop-vendor,
              [AC_HELP_STRING([--with-desktop-vendor],
                              [Specify the vendor for use in calls to desktop-file-install @<:@default=@:>@])],,
                              [with_desktop_vendor=""])

VENDOR=$with_desktop_vendor
if test "x$VENDOR" = "x"; then
    DESKTOPVENDOR=
    DESKTOPPREFIX=
else
    DESKTOPVENDOR="--vendor $VENDOR"
    DESKTOPPREFIX="$VENDOR-"
fi
AC_SUBST(DESKTOPVENDOR)
AC_SUBST(DESKTOPPREFIX)

PKG_PROG_PKG_CONFIG

dnl Allow manual definition for CUPS SERVERBIN, if not defined, use value from pkg-config...
AC_MSG_CHECKING([for CUPS SERVERBIN dir])
AC_ARG_WITH([cups_serverbin_dir],
  AS_HELP_STRING([--with-cups-serverbin-dir], [set CUPS SERVERBIN dir, default=value from pkg-config]), [
    cupsserverbindir="$withval"
    AC_MSG_RESULT([$withval])
  ], [
    AS_IF([test "x$PKG_CONFIG" != x], [
      AS_IF([$PKG_CONFIG --exists cups], [
          cupsserverbindir=$($PKG_CONFIG --variable=cups_serverbin cups)
          AC_MSG_RESULT([$cupsserverbindir])
        ], [
          AC_MSG_ERROR([No CUPS pkgconfig file present and no CUPS SERVERBIN dir defined in configure options.])
        ])
    ], [
      AC_MSG_ERROR([No pkg-config present and no CUPS SERVERBIN dir defined in configure options.])
    ])
])

AS_IF([test "x$cupsserverbindir" = x], [
  AC_MSG_ERROR([No CUPS SERVERBIN dir defined in CUPS pkgconfig file or configure options.])
])

AC_SUBST(cupsserverbindir)

PKG_CHECK_MODULES(GLIB, glib-2.0, has_glib=yes, has_glib=no)

AC_ARG_WITH(udev-rules,
	    [AC_HELP_STRING([--with-udev-rules],
			    [Enable automatic USB print queue configuration @<:@default=no@:>@])],
	    [],
	    [with_udev_rules=no])
AM_CONDITIONAL([UDEV_RULES], [test x$with_udev_rules != xno])

AC_ARG_WITH([udevdir],
	AS_HELP_STRING([--with-udevdir=DIR], [Directory for udev helper programs]),
	[], [with_udevdir=$($PKG_CONFIG --variable=udevdir udev)])
if test "x$with_udevdir" != xno; then
	AC_SUBST([udevdir], [$with_udevdir])
	AC_SUBST([udevrulesdir], [$with_udevdir/rules.d])
fi

if test "x$with_udev_rules" != xno -a "x$with_udevdir" != xno; then
   PKG_CHECK_MODULES(libudev, [libudev >= 172], has_libudev=yes, has_libudev=no)
   PKG_CHECK_MODULES(libusb, libusb-1.0, has_libusb=yes, has_libusb=no)
   if test x$has_glib == xno -o \
           x$has_udev == xno -o \
           x$has_libudev == xno -o \
           x$has_libusb == xno ; then
      AC_MSG_ERROR([Missing packages])
   fi

   AM_PROG_CC_C_O
fi

AC_ARG_WITH([systemdsystemunitdir],
        AS_HELP_STRING([--with-systemdsystemunitdir=DIR], [Directory for systemd service files]),
        [], [with_systemdsystemunitdir=$($PKG_CONFIG --variable=systemdsystemunitdir systemd)])
if test "x$with_systemdsystemunitdir" != xno; then
        AC_SUBST([systemdsystemunitdir], [$with_systemdsystemunitdir])
fi
AM_CONDITIONAL(HAVE_SYSTEMD, [test -n "$with_systemdsystemunitdir" -a "x$with_systemdsystemunitdir" != xno ])

AC_ARG_WITH(xmlto,
        [AC_HELP_STRING([--with-xmlto],
                [Enable xmlto manual generation @<:@default=yes@:>@])])
AM_CONDITIONAL([XMLTO], [test x$with_xmlto != xno])

AC_CONFIG_FILES([
Makefile
po/Makefile.in
system-config-printer
system-config-printer-applet
install-printerdriver
dbus/scp-dbus-service
udev/configure-printer@.service
])
AC_OUTPUT

# system-config-printer

[![Build Status](https://travis-ci.org/OpenPrinting/system-config-printer.svg?branch=master)](https://travis-ci.org/OpenPrinting/system-config-printer)

This is a graphical tool for CUPS administration. It uses IPP to
configure a CUPS server.

Build requirements:
-------------------

- development packages for:
  - cups
  - gettext
  - glib2
  - libusb
  - python3
  - systemd
- tools:
  - autoconf
  - automake
  - desktop-file-install
  - intltool
  - xmlto
  
Runtime requirements:
---------------------

- any desktop notification daemon
- dbus-x11
- gobject-introspection
- gtk3
- libnotify
- python3-cairo
- python3-cups
- python3-dbus
- python3-firewall
- python3-gobject
- python3-pycurl
- python3-requests
- (optional) python3-smbc

How to compile and install:
---------------------------

$ ./bootstrap
$ ./configure
$ make
$ sudo make install

How to uninstall:
-----------------

$ sudo make uninstall

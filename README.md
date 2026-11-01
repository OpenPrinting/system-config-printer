# system-config-printer

It uses IPP to configure a CUPS server. Additionally it provides dBUS interface
for several operations which aren't directly available in cupsd, and automatic USB
printer installation daemon for non-IPP-over-USB printers.

The alternatives for the graphical configuration tool are CUPS Web
interface, desktop control-center or lpadmin command line tool if you need
to install printer manually which may not be needed in recent cases.

When I do not need printer setup tool as S-C-P?
-----------------------------------------------

If the application where you print from has an up-to-date print dialog
(uses the current CUPS API) and your printer is set up for driverless printing
(has AirPrint/IPP Everywhere/IPP-over-USB support, opened port 631, lies in your local network
and Avahi is running, IPP and mDNS is enabled in your firewall, ipp-usb is installed if
your printer is connected by USB), you don't to install the printer at all. The dialog
is able to pick up the printer right before you open the dialog and it disappears
once you don't need it (reappearing next time you open the dialog again).
This appearing and disappearing printer is called CUPS temporary queue.

The devices supporting AirPrint/IPP Everywhere appear since 2010 (IPP-over-USB devices a bit later),
so if your device was made after 2010, there is a great chance it supports the standards.

From the dialogs I'm aware of the temporary queues are currently supported in any GTK3
based application (evince, gvim, gedit, firefox if you are on GNOME and choose system
dialog for printing...) and in Libreoffice.

Future with CUPS 3.0:
---------------------

CUPS 3.0 will divide the current CUPS in several modules - command line tools, library,
CUPS Local server and CUPS Sharing server. CUPS Local server will be designed as lightweight
for desktop usage, supporting only CUPS temporary queues. CUPS Sharing server will be more like
the current cupsd, supporting permanent driverless queues, suited for servers.

system-config-printer is often used on desktops where will be CUPS Local server installed by default.
Since the server will support only CUPS temporary queues, system-config-printer will need to work
with IPP services which are on localhost (USB devices, printer applications and permanent driverless
queues from CUPS Sharing server if installed as well), in local network or defined by printer profiles,
if system-config-printer should work with CUPS 3.0.

Is S-C-P required in system with CUPS 3.0?
------------------------------------------

Regarding printer setup tools OpenPrinting current plans are to integrate printer setup dialog into
common print dialog, which would enable non-driverless printer installation (via printer application)
right when user needs it - right before the printing.

dBUS interface (but probably not the same methods) will be available in CUPS 3.0 project
and since non-driverless devices are less common with time OpenPrinting group agreed there
won't be an automatic installation mechanism for them.

So the standalone configuration tool like system-config-printer isn't a priority in system with CUPS 3.0,
but it can exist together with CUPS 3.0 if updated. The next point is connected to the matter.

NEW DEVELOPER OR CO-MAINTAINER WANTED:
--------------------------------------

I'm looking for a new developer or co-maintainer for system-config-printer and pycups,
who would update/help to update them to the current standards.

In case of system-config-printer it consists:
- migration to GTK 4,
- migration of dbus code because dbus-python is deprecated,
- support for installing printer applications from various sources (.rpm, .deb, snap, flatpak),
- support for managing IPP services instead of permanent CUPS queues.
- implementation of unit tests and overall updating the python code to current PEPs

The project is kept in maintenance mode (accepting and testing sent patches, limited new development)
until there is such a person.

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
  - autoconf-archive
  - automake
  - desktop-file-install
  - intltool
  - scdoc
  - gcc
  - python3-setuptools
  - python3-build
  
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
- (optional) python3-smbc

How to compile and install:
---------------------------

```
$ ./bootstrap
$ ./configure
$ make
$ sudo make install
```

How to uninstall:
-----------------

```
$ sudo make uninstall
```

Translations:
-------------

Translations are available at [Fedora Weblate](https://translate.fedoraproject.org).
If you want to update translations, please update it in Weblate. The Weblate then creates
automatic PR, which keeps upstream project and Weblate project in synch.


Printer discovery interface
---------------------------

Add Printer lists discovered USB and network destinations first. Select a
printer to continue. Names wrap rather than being clipped into a narrow column.
The collapsed “Printer not listed?” category contains Find by address, explicit
printer URI entry, SMB, and other available backend methods. Existing driver,
authentication, naming, and installation stages remain in use.

Connection settings are collapsed for discovered printers and open for manual
methods. Search again retains previously found destinations and the chosen
connection; absence from one scan does not prove a printer is offline. A legacy
USB entry superseded by its IPP-over-USB destination is removed and must be
selected again. Search errors differ from an empty successful search. Results
from cancelled or superseded discovery requests are ignored.

Testing the discovery interface
-------------------------------

After generating the build configuration with the commands above, install
pytest and Xvfb in the development environment. The GTK tests mock CUPS and
printer discovery; they do not create queues or submit print jobs. Run them on
a private display and runtime, never the active desktop:

```sh
runtime=$(mktemp -d /tmp/scp-tests.XXXXXX)
chmod 700 "$runtime"
trap 'rm -rf "$runtime"' EXIT
unset DISPLAY WAYLAND_DISPLAY HYPRLAND_INSTANCE_SIGNATURE DBUS_SESSION_BUS_ADDRESS
export XDG_RUNTIME_DIR="$runtime" XDG_CACHE_HOME="$runtime/cache"
export XDG_CONFIG_HOME="$runtime/config" NO_AT_BRIDGE=1
export GIO_USE_VFS=local GIO_USE_VOLUME_MONITOR=unix
export CUPS_SERVER="$runtime/no-cups.sock"
export DBUS_SYSTEM_BUS_ADDRESS="unix:path=$runtime/no-system-bus"
export SYSTEM_CONFIG_PRINTER_UI=ui GDK_BACKEND=x11
xvfb-run -a dbus-run-session -- timeout 45s python3 -m pytest -q test_discovery_ui.py
```

Focused tests cover selection, manual URI validation, refresh, cancellation,
stale callbacks, USB replacement, progress, and supplied-URI modes. They do not
replace real printer/driver, SMB authentication, legacy hardware, or screen
reader testing. No claim is made that the entire upstream test suite or every
printer backend has been validated by these tests.

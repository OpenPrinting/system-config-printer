# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2021 Iñigo Martinez <inigomartinez@gmail.com>

project(
  'system-config-printer', 'c',
  version: '1.5.15',
  license: 'GPL2+',
  default_options: 'buildtype=debugoptimized',
  meson_version: '>= 0.58.0',
)

scp_name = meson.project_name()
scp_version = meson.project_version()
version_array = scp_version.split('.')
scp_major_version = version_array[0].to_int()
scp_minor_version = version_array[1].to_int()
scp_micro_version = version_array[2].to_int()

scp_prefix = get_option('prefix')
scp_bindir = get_option('bindir')
scp_datadir = get_option('datadir')
scp_mandir = get_option('mandir')
scp_localedir = get_option('localedir')
scp_sysconfdir = get_option('sysconfdir')

scp_pkgdatadir = scp_datadir / scp_name

gnome = import('gnome')
i18n = import('i18n')
pkg = import('pkgconfig')

source_root = meson.current_source_dir()

po_dir = source_root / 'po'

intltool_merge = find_program('intltool-merge')
intltool_cache = po_dir / '.intltool-merge-cache'
intltool_desktop_cmd = [intltool_merge, '-d', '-u', '-c', intltool_cache, po_dir, '@INPUT@', '@OUTPUT@']
intltool_xml_cmd = [intltool_merge, '-x', '-u', '-c', intltool_cache, po_dir, '@INPUT@', '@OUTPUT@']

top_inc = include_directories('.')

cc = meson.get_compiler('c')

# compiler flags
common_args = ['-DHAVE_CONFIG_H']

# compiler flags that are always enabled, even in release builds
cc_args = cc.get_supported_arguments([
  # warning on unused parameters is overkill, never do that
  '-Wno-unused-parameter',
  # function type cast disabled: used throughout the code especially to
  # cast GAsyncReadyCallbacks with the real object type instead of GObject
  '-Wno-cast-function-type',
  # all message protocol structs are packed, never complain about it
  '-Wno-packed',
  # we use some floating point ids as unknown, so we want to compare with them
  '-Wno-float-equal',
  # avoid warning if we're ignoring fields on purpose
  '-Wno-missing-field-initializers',
])

# strict flags to use in debug builds
if get_option('buildtype').contains('debug')
  cc_args += cc.get_supported_arguments([
    '-fno-strict-aliasing',
    '-Waggregate-return',
    '-Wcast-align',
    '-Wdeclaration-after-statement',
    '-Wdouble-promotion',
    '-Wduplicated-branches',
    '-Wduplicated-cond',
    '-Wformat=2',
    '-Wformat-nonliteral',
    '-Wformat-security',
    '-Winit-self',
    '-Winline',
    '-Wjump-misses-init',
    '-Wlogical-op',
    '-Wnested-externs',
    '-Wmissing-declarations',
    '-Wmissing-format-attribute',
    '-Wmissing-include-dirs',
    '-Wmissing-noreturn',
    '-Wmissing-prototypes',
    '-Wnull-dereference',
    '-Wpointer-arith',
    '-Wredundant-decls',
    '-Wrestrict',
    '-Wreturn-type',
    '-Wshadow',
    '-Wstrict-prototypes',
    '-Wsuggest-attribute=format',
    '-Wswitch-default',
    '-Wswitch-enum',
    '-Wundef',
    '-Wunused-but-set-variable',
    '-Wwrite-strings',
  ])
endif

add_project_arguments(common_args + cc_args, language: 'c')

# FIXME: required false?
cups_dep = dependency('cups', method: 'config-tool', required: false)

config_conf = {
  'prefix': scp_prefix,
  'bindir': scp_prefix / scp_bindir,
  'datadir': scp_prefix / scp_datadir,
  'datarootdir': f'${prefix}/@scp_datadir@',
  'localedir': scp_prefix / scp_localedir,
  'sysconfdir': scp_prefix / scp_sysconfdir,
  'cupsserverbindir': cups_dep.get_variable(configtool: 'serverbin'),
  'VERSION': meson.project_version(),
  'PACKAGE': scp_name,
}

configure_file(
  input: 'config.py.in',
  output: '@BASENAME@',
  configuration: config_conf,
  install_dir: scp_pkgdatadir,
)

nobase_scripts = files(
  'applet.py',
  'check-device-ids.py',
  'install-printerdriver.py',
  'pysmb.py',
  'scp-dbus-service.py',
  'system-config-printer.py',
)

nobase_data = files(
  'asyncconn.py',
  'asyncipp.py',
  'asyncpk1.py',
  'authconn.py',
  'cupspk.py',
  'debug.py',
  'dnssdresolve.py',
  'errordialogs.py',
  'firewallsettings.py',
  'gtkinklevel.py',
  'gui.py',
  'HIG.py',
  'installpackage.py',
  'jobviewer.py',
  'killtimer.py',
  'monitor.py',
  'newprinter.py',
  'OpenPrintingRequest.py',
  'options.py',
  'optionwidgets.py',
  'PhysicalDevice.py',
  'ppdcache.py',
  'ppdippstr.py',
  'ppdsloader.py',
  'printerproperties.py',
  'probe_printer.py',
  'SearchCriterion.py',
  'serversettings.py',
  'smburi.py',
  'statereason.py',
  'timedops.py',
  'ToolbarSearchEntry.py',
  'userdefault.py',
)

subdir_data = {
  'icons': [],
  'troubleshoot': [],
  'ui': ['remove-gtkalignment.xsl'],
  'xml': ['preferreddrivers.xml'],
}

foreach dir, exclude: subdir_data
  install_subdir(
    dir,
    exclude_files: exclude,
    install_dir: scp_pkgdatadir,
  )
endforeach

install_data(
  nobase_scripts + nobase_data,
  install_dir: scp_pkgdatadir,
)

install_data(
  'xml/preferreddrivers.xml',
  install_dir: scp_sysconfdir / 'cupshelpers',
)

bin_scripts = [
  'dbus/scp-dbus-service',
  'install-printerdriver',
  'system-config-printer',
  'system-config-printer-applet',
]


foreach bin_script: bin_scripts
  configure_file(
    input: f'@bin_script@.in',
    output: '@BASENAME@',
    configuration: config_conf,
    install_dir: scp_bindir,
  )
endforeach

udev_rules = get_option('udev_rules')
if udev_rules


  # udev base directory
  udev_udevdir = get_option('udevdir')
  if udev_udevdir == ''
    udev_udevdir = dependency('udev').get_variable('udevdir')
  endif
  udev_rulesdir = udev_udevdir / 'rules.d'

  program = 'udev-configure-printer'

  deps = [
    cups_dep,
    dependency('glib-2.0'),
    dependency('libudev', version: '>= 172', not_found_message: 'libudev required but not found, please install or disable \'udev_rules\' support'),
    dependency('libusb-1.0', not_found_message: 'libudev required but not found, please install or disable \'udev_rules\' support'),
  ]

  executable(
    program,
    sources: f'udev/@program@.c',
    dependencies: deps,
    install: true,
    install_dir: udev_udevdir,
  )

  install_data(
    'udev/udev-add-printer',
    install_dir: udev_udevdir,
  )

  install_data(
    'udev/70-printers.rules',
    install_dir: udev_rulesdir,
  )

  # systemd unit / service files
  systemd_systemdsystemunitdir = get_option('systemdsystemunitdir')

  if systemd_systemdsystemunitdir != 'no'
    if systemd_systemdsystemunitdir == ''
      systemd_dep = dependency('systemd', not_found_message: 'systemd required but not found, please provide a valid systemd user unit dir or disable it')
      systemd_systemdsystemunitdir = systemd_dep.get_variable('systemdsystemunitdir', pkgconfig_define: ['root_prefix', scp_prefix])
    endif

    # systemd unit file
    configure_file(
      input: 'udev/configure-printer@.service.in',
      output: '@BASENAME@',
      configuration: {'udevdir': udev_udevdir},
      install_dir: systemd_systemdsystemunitdir,
    )
  endif
endif

# DBus system directory
dbus_dep = dependency('dbus-1')
dbus_interfaces_dir = dbus_dep.get_variable('interfaces_dir', pkgconfig_define: ['datadir', scp_datadir])
dbus_policy_dir = dbus_dep.get_variable('sysconfdir', pkgconfig_define: ['sysconfdir', scp_sysconfdir]) / 'dbus-1/system.d'
dbus_session_bus_services_dir = dbus_dep.get_variable('session_bus_services_dir', pkgconfig_define: ['datadir', scp_datadir])

install_data(
  'dbus/org.fedoraproject.Config.Printing.xml',
  install_dir: dbus_interfaces_dir,
)

policy_data = files(
  'dbus/com.redhat.NewPrinterNotification.conf',
  'dbus/com.redhat.PrinterDriversInstaller.conf',
)

install_data(
  policy_data,
  install_dir: dbus_policy_dir,
)

configure_file(
  input: 'dbus/org.fedoraproject.Config.Printing.service.in',
  output: '@BASENAME@',
  configuration: config_conf,
  install_dir: dbus_session_bus_services_dir,
)

desktop_vendor = get_option('desktop_vendor')

# FIXME
'''
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
'''

desktop_data = {
  'system-config-printer.desktop': scp_datadir / 'applications',
  'print-applet.desktop': scp_sysconfdir / 'xdg/autostart',
}

foreach desktop, desktop_dir: desktop_data
  custom_target(
    desktop,
    input: f'@desktop@.in',
    output: (desktop_vendor != '' ? f'@desktop_vendor@-@desktop@' : desktop),
    command: intltool_desktop_cmd,
    install: true,
    install_dir: desktop_dir,
  )
endforeach

appdata = 'system-config-printer.appdata.xml'

custom_target(
  appdata,
  input: f'@appdata@.in',
  output: '@BASENAME@',
  command: intltool_xml_cmd,
  install: true,
  install_dir: scp_datadir / 'metainfo',
)

subdir('po')

subdir('cupshelpers')

xmlto = find_program('xmlto', required: get_option('xmlto'))
subdir('man', if_found: xmlto)

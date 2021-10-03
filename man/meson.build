# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2021 Iñigo Martinez <inigomartinez@gmail.com>

mans = [
  'system-config-printer.1',
  'system-config-printer-applet.1',
]

xml = 'system-config-printer.xml'

custom_target(
  xml,
  input: xml,
  output: mans,
  command: [xmlto, 'man', '-o', meson.current_build_dir(), '@INPUT@'],
  install: true,
  install_dir: scp_mandir / 'man1',
)

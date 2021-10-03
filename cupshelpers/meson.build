# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2021 Iñigo Martinez <inigomartinez@gmail.com>

python = import('python').find_installation('python')

# FIXME: workaround to avoid abosulte paths
# /usr/bin/python setup.py install --prefix=/tmp/scp
module_path = scp_prefix / python.get_path('purelib').substring(5) / 'cupshelpers'

configure_file(
  input: 'config.py.in',
  output: '@BASENAME@',
  configuration: config_conf,
  install: true,
  install_dir: module_path,
)

export_modules = files(
  '__init__.py',
  'cupshelpers.py',
  'installdriver.py',
  'openprinting.py',
  'ppds.py',
  'xmldriverprefs.py',
)

install_data(
  export_modules,
  install_dir: module_path,
)

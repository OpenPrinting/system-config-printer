#!/usr/bin/python3

## system-config-printer

## Copyright (C) 2015 Red Hat, Inc.
## Author:
##     Ayush Singh <ayushsinghceee@gmail.com>

## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.

## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.

## You should have received a copy of the GNU General Public License
## along with this program; if not, write to the Free Software
## Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import os

import gi
gi.require_version('Gtk', '3.0')
import pytest

import options

has_display = bool(os.environ.get('DISPLAY') or
                   os.environ.get('WAYLAND_DISPLAY'))
pytestmark = pytest.mark.skipif(not has_display,
                                reason="needs a GTK display connection")

NAME = "job-cancel-after"
RANGE = (0, 2147483647)


def on_change(option):
    pass


def test_value_from_cups():
    option = options.OptionWidget(NAME, 10800, RANGE, on_change)
    assert isinstance(option, options.OptionNumeric)
    assert option.get_current_value() == 10800
    assert not option.is_changed()


def test_boundary_value():
    option = options.OptionWidget(NAME, 0, RANGE, on_change)
    assert isinstance(option, options.OptionNumeric)
    assert option.get_current_value() == 0
    assert not option.is_changed()


def test_no_value_with_range_supported():
    """A queue default sent with the IPP 'no-value' tag becomes None."""
    option = options.OptionWidget(NAME, None, RANGE, on_change)
    assert option.get_current_value() == ""
    assert not option.is_changed()


def test_no_value_without_supported():
    option = options.OptionWidget(NAME, None, "", on_change)
    assert isinstance(option, options.OptionText)
    assert option.get_current_value() == ""
    assert not option.is_changed()


def test_no_value_with_supported_choices():
    option = options.OptionWidget(NAME, None, ['none', 'day-time'], on_change)
    assert isinstance(option, options.OptionSelectOne)

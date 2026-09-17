#!/usr/bin/python3

## Copyright (C) 2015 Red Hat, Inc.
## Authors:
##  Alexander Pevzner <pzz@apevzner.com>
##  Ayush Singh <ayushsinghceee@gmail.com>

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

import pytest
import newprinter

class MockPrinter:
    def __init__(self, uri):
        self.device_uri = uri

class MockDevice:
    def __init__(self, uri):
        self.uri = uri

def test_configured_uri_exact_match():
    dev = MockDevice("ipp://printer/ipp/print")
    printers = {"Printer1": MockPrinter("ipp://printer/ipp/print")}
    filtered = newprinter._filter_configured_devices([dev], printers)
    assert len(filtered) == 0

def test_configured_uri_no_match():
    dev = MockDevice("ipp://other-printer/ipp/print")
    printers = {"Printer1": MockPrinter("ipp://printer/ipp/print")}
    filtered = newprinter._filter_configured_devices([dev], printers)
    assert len(filtered) == 1
    assert filtered[0].uri == "ipp://other-printer/ipp/print"

def test_configured_uri_missing():
    dev = MockDevice("ipp://printer/ipp/print")
    printers = {
        "Printer1": MockPrinter(None),
        "Printer2": MockPrinter("")
    }
    filtered = newprinter._filter_configured_devices([dev], printers)
    assert len(filtered) == 1

def test_multiple_configured_printers():
    dev1 = MockDevice("usb://dev1")
    dev2 = MockDevice("usb://dev2")
    dev3 = MockDevice("usb://dev3") # not configured
    printers = {
        "P1": MockPrinter("usb://dev1"),
        "P2": MockPrinter("usb://dev2")
    }
    filtered = newprinter._filter_configured_devices([dev1, dev2, dev3], printers)
    assert len(filtered) == 1
    assert filtered[0].uri == "usb://dev3"

def test_default_ports_normalization():
    tests = [
        ("socket://192.168.1.5", "socket://192.168.1.5:9100"),
        ("http://192.168.1.5", "http://192.168.1.5:80"),
        ("https://192.168.1.5", "https://192.168.1.5:443"),
        ("ipp://192.168.1.5", "ipp://192.168.1.5:631"),
        ("ipps://192.168.1.5", "ipps://192.168.1.5:631"),
        ("lpd://192.168.1.5", "lpd://192.168.1.5:515"),
        ("IPP://192.168.1.5:631", "ipp://192.168.1.5"),
    ]
    for disc_uri, conf_uri in tests:
        dev = MockDevice(disc_uri)
        printers = {"Printer1": MockPrinter(conf_uri)}
        filtered = newprinter._filter_configured_devices([dev], printers)
        assert len(filtered) == 0, f"Expected match between {disc_uri} and {conf_uri}"

def test_different_port_no_match():
    dev = MockDevice("socket://192.168.1.5:1234")
    printers = {"Printer1": MockPrinter("socket://192.168.1.5:9100")}
    filtered = newprinter._filter_configured_devices([dev], printers)
    assert len(filtered) == 1, "Different ports should not match"

def test_hp_no_device_found_does_not_match_real_printer():
    dev = MockDevice("hp:/no_device_found")
    printers = {"Printer1": MockPrinter("hp:/net/printer?ip=1.2.3.4")}
    filtered = newprinter._filter_configured_devices([dev], printers)
    assert len(filtered) == 1, "hp:/no_device_found should not match a real HP printer"


class MockPPDAttr:
    def __init__(self, value):
        self.value = value


class MockCupsPPD:
    def __init__(self, attrs):
        self.attrs = attrs

    def findAttr(self, name):
        if name in self.attrs:
            return MockPPDAttr(self.attrs[name])
        return None


class MockPPDsCache:
    def __init__(self, data):
        self.data = data

    def getInfoFromPPDName(self, name):
        if name in self.data:
            return self.data[name]
        raise KeyError(name)


def test_driver_name_from_cups_ppd(monkeypatch):
    import cups
    monkeypatch.setattr(cups, "PPD", MockCupsPPD)

    ppd = MockCupsPPD({"NickName": "HP LaserJet 1200", "modelName": "HP LaserJet"})

    assert newprinter._get_driver_name_from_ppd(ppd, None) == "HP LaserJet 1200"

    ppd2 = MockCupsPPD({"modelName": "HP LaserJet"})
    assert newprinter._get_driver_name_from_ppd(ppd2, None) == "HP LaserJet"


def test_driver_name_from_string():
    cache = MockPPDsCache({
        "foomatic:HP-LaserJet_1200-pxlmono.ppd": {"ppd-make-and-model": "HP LaserJet 1200 Foomatic/pxlmono"},
        "some-other-driver.ppd": {"ppd-make-and-model": ["HP LaserJet", "Something else"]}
    })

    assert newprinter._get_driver_name_from_ppd("raw", cache) == "Raw Queue"
    assert newprinter._get_driver_name_from_ppd(None, cache) == ""
    assert newprinter._get_driver_name_from_ppd("", cache) == ""
    assert newprinter._get_driver_name_from_ppd("foomatic:HP-LaserJet_1200-pxlmono.ppd", cache) == "HP LaserJet 1200 Foomatic/pxlmono"
    assert newprinter._get_driver_name_from_ppd("some-other-driver.ppd", cache) == "HP LaserJet"
    assert newprinter._get_driver_name_from_ppd("unknown.ppd", cache) == "unknown.ppd"


def test_driver_name_from_cups_ppd_missing_attrs(monkeypatch):
    import cups
    monkeypatch.setattr(cups, "PPD", MockCupsPPD)

    ppd = MockCupsPPD({"OtherAttr": "Value"})

    assert newprinter._get_driver_name_from_ppd(ppd, None) == ""

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

import gi
import tempfile
import pytest
import newprinter
gi.require_version('Gtk', '3.0')
from unittest.mock import MagicMock
import cupshelpers
import cups

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

class DummyGUI(newprinter.NewPrinterGUI):
    def __init__(self):
        self.ppds = None
        self.dialog_mode = "printer"
        self.device = cupshelpers.Device("ipp://localhost:60000/ipp/print", **{"device-info": "driverless"})
        if "driverless" in self.device.info:
            self.device.driverless = True
        self.device.type = "ipp"
        self.remotecupsqueue = False
        self.id_matched_ppdnames = []
        self.exactdrivermatch = False
        self.nextnptab_rerun = False
        self.devid = None
        self.searchedfordriverpackages = True
        self.fetchDevices_conn = None
        self.printer_finder = None

def get_dummy_gui():
    np = DummyGUI()
    np._loadPPDsForDevice = MagicMock()
    np._installPrinterFromDeviceID = MagicMock(return_value="install_done")
    np.getNetworkPrinterMakeModel = MagicMock()
    np.getDeviceURI = MagicMock(return_value="ipp://localhost:60000/ipp/print")
    np.dec_spinner_task = MagicMock()
    np.cups = MagicMock()
    np.cups.getServerPPD = MagicMock(return_value='/tmp/mock.ppd')
    return np

def test_driverless_skip_snmp():
    np = get_dummy_gui()
    np._selectDeviceForInstallation("ipp://localhost:60000/ipp/print")
    np.getNetworkPrinterMakeModel.assert_not_called()

def test_driverless_skip_ppd_load():
    np = get_dummy_gui()
    np._selectDeviceForInstallation = MagicMock()
    np._installHPScannerFilesIfNeeded = MagicMock()
    np._handlePrinterInstallationStage(newprinter.NewPrinterGUI.PAGE_SELECT_DEVICE, 1)
    np._loadPPDsForDevice.assert_not_called()

def test_driverless_install_device_id():
    np = get_dummy_gui()
    real_install = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    np._installPrinterOrSearchForDriver = MagicMock()
    real_install(None, 1, 1)
    expected_ppd = "driverless:ipp://localhost:60000/ipp/print"
    np._installPrinterOrSearchForDriver.assert_called_with(None, expected_ppd, "exact", 1, 1)

def test_driverless_search_driver():
    np = get_dummy_gui()
    real_search = newprinter.NewPrinterGUI._installPrinterOrSearchForDriver.__get__(np)
    np.ppds = None  # Ensure ppds is None as it would be from skipping load
    np.fillDriverList = MagicMock()
    np.fillMakeList = MagicMock()
    ppdname = "driverless:ipp://localhost:60000/ipp/print"
    real_search(None, ppdname, "exact", 0, 0)
    assert np.exactdrivermatch
    assert np.auto_make == "Generic"
    assert np.auto_model == "Driverless IPP"
    assert np.auto_driver == ppdname
    np.fillDriverList.assert_not_called()
    np.fillMakeList.assert_not_called()

def test_driverless_get_np_ppd(monkeypatch):

    monkeypatch.setattr(cups, "PPD", MockCupsPPD)

    np = get_dummy_gui()
    np.auto_driver = "driverless:ipp://localhost:60000/ipp/print"
    np.cups._begin_operation = MagicMock()
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        mock_ppd_path = tf.name
    np.cups.getServerPPD = MagicMock(return_value=mock_ppd_path)

    real_get = newprinter.NewPrinterGUI.getNPPPD.__get__(np)
    result = real_get()
    np.cups._begin_operation.assert_called_with("fetching PPD")
    np.cups.getServerPPD.assert_called_with("driverless:ipp://localhost:60000/ipp/print")

    assert isinstance(result, MockCupsPPD)

def test_driverless_installable_options_reached(monkeypatch):
    
    monkeypatch.setattr(cups, "PPD", MockCupsPPD)

    np = get_dummy_gui()
    np.getNPPPD = MagicMock(return_value=MockCupsPPD({}))
    np.exactdrivermatch = True
    np.dialog_mode = 'printer'
    np.remotecupsqueue = False
    np.founddownloadabledrivers = False
    np.rbtnNPDownloadableDriverSearch = MagicMock()
    np.rbtnNPDownloadableDriverSearch.get_active.return_value = False
    np.fillNPInstallableOptions = MagicMock()
    np._selectDeviceForInstallation = MagicMock()
    np.makeNameUnique = MagicMock(return_value="printer")
    np.entNPName = MagicMock()
    np.entNPDescription = MagicMock()
    np.entNPLocation = MagicMock()
    np.entNPDriver = MagicMock()
    np.btnNPApply = MagicMock()
    np.btnNPForward = MagicMock()
    np.btnNPBack = MagicMock()

    real_stage = newprinter.NewPrinterGUI.nextNPTab.__get__(np)
    np.ntbkNewPrinter = MagicMock()

    np.ntbkNewPrinter.get_current_page.return_value = 1
    np._handlePrinterInstallationMode = MagicMock(return_value=1)

    real_stage(1)

    np.getNPPPD.assert_called_once()
    np.fillNPInstallableOptions.assert_called_once()

    np._loadPPDsForDevice.assert_not_called()

    np._loadPPDsForDevice.assert_not_called()

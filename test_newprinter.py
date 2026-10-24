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
import threading
import time
import pytest
import newprinter
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib
from unittest.mock import MagicMock
import cupshelpers
import cups
import authconn

class MockPrinter:
    def __init__(self, uri):
        self.device_uri = uri

class MockExistingPrinter:
    def __init__(self, name):
        self.discovered = False
        self.name = name

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
        self.founddownloadabledrivers = False
        self.rbtnNPDownloadableDriverSearch = MagicMock()
        self.rbtnNPDownloadableDriverSearch.get_active.return_value = False
        self.rbtnNPFoomatic = MagicMock()
        self.rbtnNPFoomatic.get_active.return_value = True
        self.rbtnNPPPD = MagicMock()
        self.rbtnNPPPD.get_active.return_value = False
        self.auto_make = ""
        self.auto_model = ""
        self.auto_driver = None
        self.ppdsloader = None
        self.installed_driver_files = []

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

def test_driverless_loads_ppds_on_forward():
    np = get_dummy_gui()
    np._selectDeviceForInstallation = MagicMock()
    np._installHPScannerFilesIfNeeded = MagicMock()
    res = np._handlePrinterInstallationStage(newprinter.NewPrinterGUI.PAGE_SELECT_DEVICE, 1)
    np._loadPPDsForDevice.assert_called_once()
    assert res == newprinter.NewPrinterGUI.INSTALL_RESULT_OPS_PENDING

def test_driverless_install_device_id():
    np = get_dummy_gui()
    real_install = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    np._installPrinterOrSearchForDriver = MagicMock(return_value=newprinter.NewPrinterGUI.INSTALL_RESULT_DONE)
    np._validateDriverlessPPD = MagicMock(return_value="mock_ppd_object")
    real_install(None, 1, 1)
    expected_ppd = "driverless:ipp://localhost:60000/ipp/print"
    np._installPrinterOrSearchForDriver.assert_called_with(None, expected_ppd, "exact", 1, 1)

    # E. Working driverless:
    # - validation succeeds
    # - no _driverless_failed state
    # - existing driverless behavior remains unchanged
    assert not getattr(np.device, '_driverless_failed', False)

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

def test_searching_spinner_visible_during_driverless_validation():
    """Verify that the searching spinner remains visible while nextNPTab executes."""
    np = get_dummy_gui()

    loader = MagicMock()
    loader._jockey_has_answered = False
    loader.get_error.return_value = None
    loader.get_ppds.return_value = {"driverless:foo": {}}
    loader.get_ppdsmatch_result.return_value = {}

    # We want to intercept nextNPTab and check if the spinner has been hidden yet.
    spinner_states = []

    def mock_hide():
        spinner_states.append("hidden")
    np._hide_searching_spinner = mock_hide

    def mock_nextNPTab(step=1):
        if "hidden" not in spinner_states:
            spinner_states.append("visible")
        else:
            spinner_states.append("already_hidden")

    np.nextNPTab = mock_nextNPTab
    np.ntbkNewPrinter = MagicMock()
    np.ntbkNewPrinter.get_current_page.return_value = np.PAGE_DESCRIBE_PRINTER
    np._set_driver_ppd_loading = MagicMock()

    np.on_ppdsloader_finished_next(loader)

    assert "visible" in spinner_states, "Spinner was hidden before nextNPTab finished"
    assert "hidden" in spinner_states, "Spinner was not hidden eventually"
    assert spinner_states == ["visible", "hidden"], "Unexpected sequence of events"

def test_broken_driverless_getnpppd_returns_none_on_runtime_error(monkeypatch):
    """When cups.PPD() raises RuntimeError for a driverless PPD,
    getNPPPD() must return None (not the stale string)."""
    monkeypatch.setattr(cups, "PPD",
                        MagicMock(side_effect=RuntimeError("ppdOpenFile failed")))

    np = get_dummy_gui()
    np.auto_driver = "driverless:ipp://localhost:60000/ipp/print"
    np.cups._begin_operation = MagicMock()
    np.cups._end_operation = MagicMock()
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        mock_ppd_path = tf.name
    np.cups.getServerPPD = MagicMock(return_value=mock_ppd_path)

    real_get = newprinter.NewPrinterGUI.getNPPPD.__get__(np)
    result = real_get()

    assert result is None
    np.cups.getServerPPD.assert_called_with("driverless:ipp://localhost:60000/ipp/print")

def test_broken_driverless_getnpppd_returns_none_on_ipp_error(monkeypatch):
    """When getServerPPD raises cups.IPPError for a driverless PPD,
    getNPPPD() must return None."""
    monkeypatch.setattr(cups, "PPD", MockCupsPPD)

    np = get_dummy_gui()
    np.auto_driver = "driverless:ipp://localhost:60000/ipp/print"
    np.cups._begin_operation = MagicMock()
    np.cups._end_operation = MagicMock()
    np.cups.getServerPPD = MagicMock(side_effect=cups.IPPError(0, ""))

    real_get = newprinter.NewPrinterGUI.getNPPPD.__get__(np)
    result = real_get()

    assert result is None

def test_broken_driverless_triggers_legacy_fallback():
    """When driverless PPD fetch fails in nextNPTab, device.driverless
    should be set to False and _handlePrinterInstallationMode should
    be called to trigger the legacy PPD catalog load."""
    np = get_dummy_gui()
    np.getNPPPD = MagicMock(return_value=None)
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
    original_mode = MagicMock(
        return_value=newprinter.NewPrinterGUI.INSTALL_RESULT_DONE)

    np._handlePrinterInstallationMode = MagicMock(
        side_effect=[newprinter.NewPrinterGUI.INSTALL_RESULT_DONE,
                     newprinter.NewPrinterGUI.INSTALL_RESULT_OPS_PENDING])

    assert np.device.driverless is True

    real_stage(1)

    assert np.device.driverless is False
    assert np._handlePrinterInstallationMode.call_count == 2
    np.btnNPForward.set_sensitive.assert_called_with(False)
    np.fillNPInstallableOptions.assert_not_called()

def test_non_driverless_ppd_failure_preserves_string(monkeypatch):
    """For non-driverless PPD strings, RuntimeError in cups.PPD()
    should NOT set ppd to None — the existing server-side fallback
    must be preserved."""
    monkeypatch.setattr(cups, "PPD",
                        MagicMock(side_effect=RuntimeError("ppdOpenFile failed")))

    np = get_dummy_gui()
    np.device.driverless = False
    np.ppds = MagicMock()
    np.rbtnNPFoomatic = MagicMock()
    np.rbtnNPFoomatic.get_active.return_value = True
    np.founddownloadableppd = False
    np.installed_driver_files = []
    np.tvNPDrivers = MagicMock()
    selection_mock = MagicMock()
    iter_mock = MagicMock()
    model_mock = MagicMock()
    model_mock.get_path.return_value = [0]
    selection_mock.get_selected.return_value = (model_mock, iter_mock)
    np.tvNPDrivers.get_selection.return_value = selection_mock
    np.NPDrivers = ["foomatic:HP-LaserJet-pxlmono.ppd"]
    np.cups._begin_operation = MagicMock()
    np.cups._end_operation = MagicMock()
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        mock_ppd_path = tf.name
    np.cups.getServerPPD = MagicMock(return_value=mock_ppd_path)

    real_get = newprinter.NewPrinterGUI.getNPPPD.__get__(np)
    result = real_get()

    assert result == "foomatic:HP-LaserJet-pxlmono.ppd"

def test_search_uri_masking_broken_driverless():
    """Verify that a broken driverless fallback masks its URI as None."""
    np = get_dummy_gui()
    np.device.driverless = False
    np.device._driverless_failed = True
    np.device.id = "MFG:A;MDL:B;"
    np.device.id_dict = {"MFG": "A", "MDL": "B", "DES": "", "CMD": []}
    np.device.uri = "ipp://localhost:60000/ipp/print"
    np.device.make_and_model = "A B"
    np.dialog_mode = 'printer'
    np.remotecupsqueue = False
    np.ppds = MagicMock()
    np.ppds.getPPDNamesFromDeviceID.return_value = {"mock_ppd": "exact"}
    np.ppds.orderPPDNamesByPreference.return_value = ["mock_ppd"]
    np._installPrinterOrSearchForDriver = MagicMock(return_value=newprinter.NewPrinterGUI.INSTALL_RESULT_DONE)

    real_install = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    real_install(None, 0, 0)

    np.ppds.getPPDNamesFromDeviceID.assert_called_with("A", "B", "", [], None, "A B")

def test_search_uri_normal_non_driverless():
    """Verify that a normal non-driverless IPP device passes its true URI."""
    np = get_dummy_gui()
    np.device.driverless = False
    np.device._driverless_failed = False
    np.device.id = "MFG:A;MDL:B;"
    np.device.id_dict = {"MFG": "A", "MDL": "B", "DES": "", "CMD": []}
    np.device.uri = "ipp://localhost:60000/ipp/print"
    np.device.make_and_model = "A B"
    np.dialog_mode = 'printer'
    np.remotecupsqueue = False
    np.ppds = MagicMock()
    np.ppds.getPPDNamesFromDeviceID.return_value = {"mock_ppd": "exact"}
    np.ppds.orderPPDNamesByPreference.return_value = ["mock_ppd"]
    np._installPrinterOrSearchForDriver = MagicMock(return_value=newprinter.NewPrinterGUI.INSTALL_RESULT_DONE)

    real_install = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    real_install(None, 0, 0)
    np.ppds.getPPDNamesFromDeviceID.assert_called_with("A", "B", "", [], "ipp://localhost:60000/ipp/print", "A B")

def test_search_uri_working_driverless():
    """Verify that a working driverless device bypasses legacy matching entirely."""
    np = get_dummy_gui()
    np.device.driverless = True
    np.device._driverless_failed = False
    np.device.uri = "ipp://localhost:60000/ipp/print"
    np.dialog_mode = 'printer'
    np.ppds = MagicMock()
    np._installPrinterOrSearchForDriver = MagicMock(return_value=newprinter.NewPrinterGUI.INSTALL_RESULT_DONE)

    real_install = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    real_install(None, 0, 0)
    np.ppds.getPPDNamesFromDeviceID.assert_not_called()

def test_network_broken_driverless_rejected():
    """Network broken driverless candidate is rejected and falls back."""
    np = get_dummy_gui()
    np.device.driverless = False
    np.device.uri = "dnssd://printer._ipp._tcp.local/"
    np.device.make_and_model = "A B"
    np.device.id_dict = {"MFG": "A", "MDL": "B", "DES": "", "CMD": []}
    np.device.id = "MFG:A;MDL:B;"
    np.installed_driver_files = []
    np.dialog_mode = 'printer'
    np.remotecupsqueue = False
    np.ppds = MagicMock()
    np.ppds.getPPDNamesFromDeviceID.return_value = {"driverless:dnssd://...": "exact", "other_ppd": "close"}
    np.ppds.orderPPDNamesByPreference.return_value = ["driverless:dnssd://...", "other_ppd"]

    np._validateDriverlessPPD = MagicMock(return_value=None)
    np._installPrinterOrSearchForDriver = MagicMock(return_value=newprinter.NewPrinterGUI.INSTALL_RESULT_DONE)

    np.searchedfordriverpackages = False
    np.exactdrivermatch = True # Pre-set to verify it gets explicitly forced to False
    real_install = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    result = real_install(None, 0, 0)

    np._validateDriverlessPPD.assert_called_with("driverless:dnssd://...")
    np._installPrinterOrSearchForDriver.assert_called_with(None, None, None, 0, 0)
    assert result == newprinter.NewPrinterGUI.INSTALL_RESULT_DONE

    assert np.device.driverless is False
    assert np.device._driverless_failed is True
    assert np.exactdrivermatch is False
    assert np.id_matched_ppdnames == []
    assert np.searchedfordriverpackages is True
    assert not hasattr(np, '_broken_driverless_ppds')

def test_network_broken_driverless_no_alternative():
    """Network broken driverless with no alternative behaves as no matching PPD."""
    np = get_dummy_gui()
    np.searchedfordriverpackages = False
    np.device.driverless = False
    np.device.uri = "dnssd://printer._ipp._tcp.local/"
    np.device.make_and_model = "A B"
    np.device.id_dict = {"MFG": "A", "MDL": "B", "DES": "", "CMD": []}
    np.device.id = "MFG:A;MDL:B;"
    np.installed_driver_files = []
    np.dialog_mode = 'printer'
    np.remotecupsqueue = False
    np.ppds = MagicMock()
    np.ppds.getPPDNamesFromDeviceID.return_value = {"driverless:dnssd://...": "exact"}
    np.ppds.orderPPDNamesByPreference.return_value = ["driverless:dnssd://..."]

    np._validateDriverlessPPD = MagicMock(return_value=None)
    np._installPrinterOrSearchForDriver = MagicMock(return_value=newprinter.NewPrinterGUI.INSTALL_RESULT_DONE)

    real_install = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    result = real_install(None, 0, 0)

    # B. If all candidates are removed, ppdname=None, status=None
    # exactdrivermatch remains False, and it continues to manual fallback
    np._installPrinterOrSearchForDriver.assert_called_with(None, None, None, 0, 0)
    assert result == newprinter.NewPrinterGUI.INSTALL_RESULT_DONE

    assert np.device.driverless is False
    assert np.device._driverless_failed is True
    assert np.searchedfordriverpackages is True
    assert not hasattr(np, '_broken_driverless_ppds')

def test_usb_broken_driverless_fallback():
    """USB/ipp-usb broken driverless enters manual fallback without re-loading PPDs."""
    np = get_dummy_gui()
    np.device.driverless = True
    np.device.uri = "ipp://localhost:60000/ipp/print"
    np._validateDriverlessPPD = MagicMock(return_value=None)
    np._loadPPDsForDevice = MagicMock()
    np._installPrinterOrSearchForDriver = MagicMock(return_value=newprinter.NewPrinterGUI.INSTALL_RESULT_DONE)

    real_install = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    result = real_install(None, 0, 0)

    assert result == newprinter.NewPrinterGUI.INSTALL_RESULT_DONE
    assert np.device.driverless is False
    assert np.device._driverless_failed is True
    assert np.searchedfordriverpackages is True
    assert np.exactdrivermatch is False
    np._loadPPDsForDevice.assert_not_called()

def test_working_driverless_cached():
    """Working driverless PPD is cached and not fetched twice."""
    np = get_dummy_gui()
    np.device.driverless = True
    np.device.uri = "ipp://localhost:60000/ipp/print"
    np.ppds = None
    np.auto_driver = "driverless:ipp://localhost:60000/ipp/print"
    mock_ppd = MagicMock()
    np._cached_driverless_ppd = mock_ppd

    np.cups = MagicMock()
    real_get = newprinter.NewPrinterGUI.getNPPPD.__get__(np)
    result = real_get()

    assert result == mock_ppd
    np.cups.getServerPPD.assert_not_called()
    assert getattr(np, '_cached_driverless_ppd', None) is None

def test_fillDriverList_excludes_broken_driverless_ppds(monkeypatch):
    """Verify fillDriverList excludes driverless PPDs when _driverless_failed is True."""
    np = get_dummy_gui()
    np.device.make_and_model = "A B"
    np.device.id_dict = {"MFG": "A", "MDL": "B"}
    np.installed_driver_files = []
    np.auto_driver = None
    np.recommended_model_selected = False

    np.device._driverless_failed = True

    np.ppds = MagicMock()
    np.ppds.getInfoFromModel.return_value = {
        "driverless:dnssd://...": {"ppd-make-and-model": "Broken Xerox, Fax, driverless"},
        "other_ppd": {"ppd-make-and-model": "Other Driver"}
    }
    np.ppds.orderPPDNamesByPreference.return_value = ["driverless:dnssd://...", "other_ppd"]

    def get_info(name):
        return np.ppds.getInfoFromModel.return_value[name]
    np.ppds.getInfoFromPPDName.side_effect = get_info

    np.tvNPDrivers = MagicMock()
    mock_model = MagicMock()
    np.tvNPDrivers.get_model.return_value = mock_model

    real_fill = newprinter.NewPrinterGUI.fillDriverList.__get__(np)
    real_fill("A", "B")

    assert "driverless:dnssd://..." not in np.NPDrivers

    assert "other_ppd" in np.NPDrivers
    assert np.NPDrivers == ["other_ppd"]
    appended_strings = [args[0][0] for args, kwargs in mock_model.append.call_args_list]
    assert not any("Broken Xerox" in s for s in appended_strings)
    assert any("Other Driver" in s for s in appended_strings)

def test_ipp_connection_labels():
    """Verify that IPP connection labels distinguish IPP and IPP over USB using dnssdresolve,
    and preserve DNS-SD LPD and AppSocket labels."""
    np = get_dummy_gui()
    np.device_selected = 0
    np.tvNPDeviceURIs = MagicMock()
    np.expNPDeviceURIs = MagicMock()
    np.lblNPDeviceDescription = MagicMock()
    np.ntbkNPType = MagicMock()
    np.new_printer_device_tabs = {}
    np.PAGE_SELECT_DEVICE = 1
    np.PAGE_DESCRIBE_PRINTER = 2

    mock_widget = MagicMock()
    mock_widget.get_cursor.return_value = ("0", 0)
    mock_model = MagicMock()
    mock_widget.get_model.return_value = mock_model
    mock_model.get_iter.return_value = "iter"

    mock_physicaldevice = MagicMock()
    mock_model.get_value.return_value = mock_physicaldevice

    # 1. Normal network DNS-SD IPP printer
    dev_dnssd_net = cupshelpers.Device("dnssd://printer._ipp._tcp.local/", **{'device-info': 'Network Printer'})
    dev_dnssd_net.address = '192.168.1.20'

    # 2. IPP-over-USB printer resolved to 127.0.0.1
    dev_usb_v4 = cupshelpers.Device("ipp://printer%20(USB)._ipp._tcp.local/", **{'device-info': 'ipp-usb (driverless)'})
    dev_usb_v4.address = '127.0.0.1'

    # 3. IPP-over-USB printer resolved to ::1
    dev_usb_v6 = cupshelpers.Device("ipp://printer%20(USB)._ipp._tcp.local/", **{'device-info': 'ipp-usb (driverless)'})
    dev_usb_v6.address = '::1'

    # 4. DNS-SD LPD printer
    dev_dnssd_lpd = cupshelpers.Device("dnssd://printer._printer._tcp.local/", **{'device-info': 'Network LPD Printer'})
    dev_dnssd_lpd.address = '192.168.1.30'

    # 5. DNS-SD AppSocket/JetDirect printer
    dev_dnssd_socket = cupshelpers.Device("dnssd://printer._pdl-datastream._tcp.local/", **{'device-info': 'Network Socket Printer'})
    dev_dnssd_socket.address = '192.168.1.40'

    # 6. Legacy / ipp scheme network printer (non-driverless and driverless)
    dev_net = cupshelpers.Device("ipp://printer.example.com/", **{'device-info': 'Network Printer'})
    dev_net.address = '192.168.1.50'
    dev_net_driverless = cupshelpers.Device("ipp://printer._ipp._tcp.local/", **{'device-info': 'Network Printer (driverless)'})
    dev_net_driverless.address = '192.168.1.10'

    # 7. IPPS network printer (e.g. from simulator publishing _ipps._tcp)
    dev_ipps = cupshelpers.Device("ipps://Broken%20Xerox%20B235%20MFP._ipps._tcp.local", **{'device-info': 'Broken Xerox B235 MFP (driverless)'})

    mock_physicaldevice.get_devices.return_value = [
        dev_dnssd_net, dev_usb_v4, dev_usb_v6, dev_dnssd_lpd, dev_dnssd_socket, dev_net, dev_net_driverless, dev_ipps
    ]

    np.on_tvNPDevices_cursor_changed(mock_widget)

    # 1. normal network DNS-SD IPP -> "IPP"
    assert dev_dnssd_net.menuentry == "IPP"

    # 2. IPP-over-USB -> "IPP over USB"
    assert dev_usb_v4.menuentry == "IPP over USB"
    assert getattr(dev_usb_v4, 'driverless', False) is True
    assert dev_usb_v6.menuentry == "IPP over USB"
    assert getattr(dev_usb_v6, 'driverless', False) is True

    # 3. DNS-SD LPD -> existing LPD label
    assert dev_dnssd_lpd.menuentry == "LPD network printer via DNS-SD"

    # 4. DNS-SD AppSocket -> existing AppSocket/JetDirect label
    assert dev_dnssd_socket.menuentry == "AppSocket/JetDirect network printer via DNS-SD"

    # 5. ipp:// network printers -> "IPP"
    assert dev_net.menuentry == "IPP"
    assert not getattr(dev_net, 'driverless', False)
    assert dev_net_driverless.menuentry == "IPP"
    assert getattr(dev_net_driverless, 'driverless', False) is True

    # 6. ipps:// network printer -> "IPP"
    assert dev_ipps.menuentry == "IPP"
    assert getattr(dev_ipps, 'driverless', False) is True


def test_ipps_network_device_connection_label():
    """Verify that an ipps://..._ipps._tcp.local device displays 'IPP' and keeps Connection section visible."""
    np = get_dummy_gui()
    np.device_selected = 0
    np.tvNPDeviceURIs = MagicMock()
    np.expNPDeviceURIs = MagicMock()
    np.lblNPDeviceDescription = MagicMock()
    np.ntbkNPType = MagicMock()
    np.new_printer_device_tabs = {}
    np.PAGE_SELECT_DEVICE = 1
    np.PAGE_DESCRIBE_PRINTER = 2

    mock_widget = MagicMock()
    mock_widget.get_cursor.return_value = ("0", 0)
    mock_model = MagicMock()
    mock_widget.get_model.return_value = mock_model
    mock_model.get_iter.return_value = "iter"

    mock_physicaldevice = MagicMock()
    mock_model.get_value.return_value = mock_physicaldevice

    dev_ipps = cupshelpers.Device(
        "ipps://Broken%20Xerox%20B235%20MFP._ipps._tcp.local",
        **{'device-info': 'Broken Xerox B235 MFP (driverless)'}
    )
    mock_physicaldevice.get_devices.return_value = [dev_ipps]

    np.on_tvNPDevices_cursor_changed(mock_widget)

    # 1. Connection section remains visible
    np.expNPDeviceURIs.show_all.assert_called_once()
    np.expNPDeviceURIs.hide.assert_not_called()

    # 2. menuentry is "IPP"
    assert dev_ipps.menuentry == "IPP"
    assert getattr(dev_ipps, 'driverless', False) is True


def test_broken_driverless_skips_openprinting(monkeypatch):
    """Broken driverless fallback skips remote OpenPrinting query."""
    np = get_dummy_gui()
    np.searchedfordriverpackages = False
    np.installed_driver_files = []
    np.device.driverless = False
    np.device._driverless_failed = True
    np.device.id = "MFG:Xerox;MDL:B235;"
    np.device.uri = "dnssd://Xerox%20B235._ipp._tcp.local/"
    np.ppds = MagicMock()
    np.ppds.getPPDNamesFromDeviceID.return_value = {}
    np.ppds.orderPPDNamesByPreference.return_value = []
    np.fillMakeList = MagicMock()

    mock_opreq_cls = MagicMock()
    monkeypatch.setattr(newprinter, "OpenPrintingRequest", mock_opreq_cls)

    real_install = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    result = real_install(np.device.id, 0, 0)

    assert np.searchedfordriverpackages is True
    mock_opreq_cls.assert_not_called()
    assert getattr(np, 'opreq', None) is None
    np.fillMakeList.assert_called_once()
    assert result == newprinter.NewPrinterGUI.INSTALL_RESULT_DONE


def test_normal_printer_searches_openprinting_when_no_match(monkeypatch):
    """Normal printer without driver match still queries OpenPrinting."""
    np = get_dummy_gui()
    np.searchedfordriverpackages = False
    np.installed_driver_files = []
    np.device.driverless = False
    np.device._driverless_failed = False
    np.device.id = "MFG:TestMFG;MDL:TestMDL;"
    np.device.uri = "usb://TestMFG/TestMDL"
    np.ppds = MagicMock()
    np.ppds.getPPDNamesFromDeviceID.return_value = {}
    np.ppds.orderPPDNamesByPreference.return_value = []
    np.fillMakeList = MagicMock()
    np._show_searching_spinner = MagicMock()

    mock_opreq_instance = MagicMock()
    mock_opreq_cls = MagicMock(return_value=mock_opreq_instance)
    monkeypatch.setattr(newprinter, "OpenPrintingRequest", mock_opreq_cls)

    real_install = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    result = real_install(np.device.id, 0, 0)

    assert np.searchedfordriverpackages is True
    mock_opreq_cls.assert_called_once()
    mock_opreq_instance.searchPrinters.assert_called_once_with(np.device.id)
    np.fillMakeList.assert_not_called()
    assert result == newprinter.NewPrinterGUI.INSTALL_RESULT_OPS_PENDING


def test_network_broken_driverless_probe_failure_sets_flags_and_skips_packagekit():
    """When driverless PPD validation fails, flags are set immediately and driverless mode is abandoned."""
    np = get_dummy_gui()
    np.device.driverless = True
    np.device.uri = "dnssd://Xerox%20B235._ipp._tcp.local/"
    np.device.id = "MFG:Xerox;MDL:B235;"
    np.searchedfordriverpackages = False
    np._validateDriverlessPPD = MagicMock(return_value=None)
    np._loadPPDsForDevice = MagicMock()
    np._installPrinterOrSearchForDriver = MagicMock(return_value=newprinter.NewPrinterGUI.INSTALL_RESULT_DONE)

    real_install = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    result = real_install(np.device.id, 0, 0)

    assert result == newprinter.NewPrinterGUI.INSTALL_RESULT_DONE
    assert np.device.driverless is False
    assert np.device._driverless_failed is True
    assert np.searchedfordriverpackages is True
    assert np.exactdrivermatch is False
    np._loadPPDsForDevice.assert_not_called()


def test_broken_driverless_guard_prevents_openprinting_even_if_reset(monkeypatch):
    """Even if searchedfordriverpackages is reset to False, _driverless_failed=True prevents OpenPrinting."""
    np = get_dummy_gui()
    np.searchedfordriverpackages = False
    np.device.driverless = False
    np.device._driverless_failed = True
    np.dialog_mode = "printer"
    np.ppds = MagicMock()
    np.fillMakeList = MagicMock()

    mock_opreq_cls = MagicMock()
    monkeypatch.setattr(newprinter, "OpenPrintingRequest", mock_opreq_cls)

    real_search = newprinter.NewPrinterGUI._installPrinterOrSearchForDriver.__get__(np)
    result = real_search("MFG:Xerox;MDL:B235;", None, None, 0, 0)

    mock_opreq_cls.assert_not_called()
    assert getattr(np, 'opreq', None) is None
    np.fillMakeList.assert_called_once()
    assert result == newprinter.NewPrinterGUI.INSTALL_RESULT_DONE


def test_ppdsloader_with_none_device_id_skips_packagekit_and_queries_cups():
    """Passing device_id=None to PPDsLoader skips PackageKit and directly queries CUPS."""
    import ppdsloader
    loader = ppdsloader.PPDsLoader(device_id=None, device_uri="dnssd://Xerox%20B235._ipp._tcp.local/")
    loader._query_packagekit = MagicMock()
    loader._query_cups = MagicMock()

    loader.run()

    loader._query_packagekit.assert_not_called()
    loader._query_cups.assert_called_once()


def test_choose_driver_button_visible_for_driverless():
    np = get_dummy_gui()
    np.ntbkNewPrinter = MagicMock()
    np.ntbkNewPrinter.get_current_page.return_value = newprinter.NewPrinterGUI.PAGE_DESCRIBE_PRINTER
    np.dialog_mode = "printer"
    np.btnNPBack = MagicMock()
    np.btnNPForward = MagicMock()
    np.btnNPApply = MagicMock()
    np.btnNPChooseDriver = MagicMock()
    np.entNPName = MagicMock()
    np.entNPName.get_text.return_value = "TestPrinter"
    np.printers = {}
    np.ppd = "driverless:ipp://localhost:60000/ipp/print"
    np.device.driverless = True

    newprinter.NewPrinterGUI.setNPButtons(np)

    np.btnNPChooseDriver.show.assert_called_once()
    np.btnNPChooseDriver.hide.assert_not_called()


def test_choose_driver_button_visible_for_non_driverless():
    np = get_dummy_gui()
    np.ntbkNewPrinter = MagicMock()
    np.ntbkNewPrinter.get_current_page.return_value = newprinter.NewPrinterGUI.PAGE_DESCRIBE_PRINTER
    np.dialog_mode = "printer"
    np.btnNPBack = MagicMock()
    np.btnNPForward = MagicMock()
    np.btnNPApply = MagicMock()
    np.btnNPChooseDriver = MagicMock()
    np.entNPName = MagicMock()
    np.entNPName.get_text.return_value = "TestPrinter"
    np.printers = {}
    np.ppd = "foomatic:HP-LaserJet_4_Plus-hpijs.ppd"
    np.device.driverless = False

    newprinter.NewPrinterGUI.setNPButtons(np)

    np.btnNPChooseDriver.show.assert_called_once()
    np.btnNPChooseDriver.hide.assert_not_called()


def test_clicking_choose_driver_button_enters_manual_workflow():
    np = get_dummy_gui()
    np.dialog_mode = "duplicate"
    np.device.driverless = True
    np.exactdrivermatch = True
    np.ppds = MagicMock()
    np.ntbkNewPrinter = MagicMock()
    np.rbtnNPFoomatic = MagicMock()
    np.on_rbtnNPFoomatic_toggled = MagicMock()
    np.nextNPTab = MagicMock()
    np._loadPPDsForDevice = MagicMock()
    np._ensure_driver_selection_spinner = MagicMock(return_value=True)
    np._driver_selection_stack = MagicMock()
    np._driver_selection_spinner = MagicMock()
    np.ntbkPPDSource = MagicMock()

    newprinter.NewPrinterGUI.on_btnNPChooseDriver_clicked(np, None)

    assert np.device.driverless is True
    assert np.duplicate_driver_selection is True
    assert np._getPagesOrderForDialogMode() == [
        np.PAGE_SELECT_INSTALL_METHOD,
        np.PAGE_CHOOSE_DRIVER_FROM_DB,
        np.PAGE_INSTALLABLE_OPTIONS,
        np.PAGE_DESCRIBE_PRINTER,
    ]
    assert np.exactdrivermatch is False
    assert np.searchedfordriverpackages is True
    np._driver_selection_stack.set_visible_child_name.assert_any_call("loading")
    np._driver_selection_stack.set_visible_child_name.assert_any_call("content")
    np._driver_selection_spinner.start.assert_called_once()
    np._driver_selection_spinner.stop.assert_called_once()
    np._loadPPDsForDevice.assert_not_called()
    np.ntbkNewPrinter.set_current_page.assert_called_with(newprinter.NewPrinterGUI.PAGE_SELECT_INSTALL_METHOD)
    np.rbtnNPFoomatic.set_active.assert_called_with(True)
    np.on_rbtnNPFoomatic_toggled.assert_called_with(np.rbtnNPFoomatic)
    np.nextNPTab.assert_called_with(step=0)


def test_choose_driver_triggers_ppd_load_when_ppds_none():
    np = get_dummy_gui()
    np.ppds = None
    np.device.driverless = False
    np.dialog_mode = "printer"
    np._selectDeviceForInstallation = MagicMock()
    np._installHPScannerFilesIfNeeded = MagicMock()
    np._loadPPDsForDevice = MagicMock()

    result = newprinter.NewPrinterGUI._handlePrinterInstallationStage(
        np, newprinter.NewPrinterGUI.PAGE_SELECT_INSTALL_METHOD, 0
    )

    np._loadPPDsForDevice.assert_called_once()
    assert result == newprinter.NewPrinterGUI.INSTALL_RESULT_OPS_PENDING


def test_driverless_printer_subsequently_selects_non_driverless_driver(monkeypatch):
    """When on PAGE_SELECT_INSTALL_METHOD, driverless PPD is excluded from ppdnamelist,
    exactdrivermatch is False, and selecting a manual driver shows that driver and hides the button."""
    monkeypatch.setattr(cups, "PPD", MockCupsPPD)

    np = get_dummy_gui()
    np.ppds = MagicMock()
    fit = {
        "driverless:ipp://localhost:60000/ipp/print": "exact",
        "foomatic:HP-LaserJet": "exact",
    }
    np.ppds.getPPDNamesFromDeviceID.return_value = fit
    np.ppds.orderPPDNamesByPreference.return_value = [
        "driverless:ipp://localhost:60000/ipp/print",
        "foomatic:HP-LaserJet",
    ]
    np.ppds.getInfoFromPPDName.return_value = {
        "ppd-make-and-model": "HP LaserJet"
    }
    np.installed_driver_files = []
    np.fillDriverList = MagicMock()
    np.fillMakeList = MagicMock()
    np.device.driverless = False
    np.device.id = "MFG:HP;MDL:LaserJet;"
    np.device.id_dict = {"MFG": "HP", "MDL": "LaserJet", "DES": "", "CMD": []}
    np.device.make_and_model = "HP LaserJet"

    real_install = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    res = real_install(np.device.id, newprinter.NewPrinterGUI.PAGE_SELECT_INSTALL_METHOD, 0)

    assert np.auto_driver == "driverless:ipp://localhost:60000/ipp/print"
    assert np.exactdrivermatch is False
    np.fillMakeList.assert_called_once()
    assert res == newprinter.NewPrinterGUI.INSTALL_RESULT_DONE

    np.remotecupsqueue = False
    np.founddownloadabledrivers = False
    np.rbtnNPDownloadableDriverSearch = MagicMock()
    np.rbtnNPDownloadableDriverSearch.get_active.return_value = False
    np.rbtnNPFoomatic = MagicMock()
    np.rbtnNPFoomatic.get_active.return_value = True

    order = newprinter.NewPrinterGUI._getPagesOrderForDialogMode(np)
    assert newprinter.NewPrinterGUI.PAGE_SELECT_INSTALL_METHOD in order
    assert newprinter.NewPrinterGUI.PAGE_CHOOSE_DRIVER_FROM_DB in order

    np.ppd = "foomatic:HP-LaserJet"
    np.ntbkNewPrinter = MagicMock()
    np.ntbkNewPrinter.get_current_page.return_value = newprinter.NewPrinterGUI.PAGE_DESCRIBE_PRINTER
    np.btnNPBack = MagicMock()
    np.btnNPForward = MagicMock()
    np.btnNPApply = MagicMock()
    np.btnNPChooseDriver = MagicMock()
    np.entNPName = MagicMock()
    np.entNPName.get_text.return_value = "HP_LaserJet"
    np.printers = {}

    newprinter.NewPrinterGUI.setNPButtons(np)
    np.btnNPChooseDriver.show.assert_called_once()
    np.btnNPChooseDriver.hide.assert_not_called()





def test_driverless_xerox_b235_button_visible_on_describe_page():
    """Real go-mfp Xerox B235 scenario: self.ppd is a cups.PPD object with
    cups-filters driverless NickName. btnNPChooseDriver must be visible on PAGE_DESCRIBE_PRINTER."""
    np = get_dummy_gui()
    np.ppd = MockCupsPPD({"NickName": "Xerox Xerox(R) B235 MFP, Fax, driverless, cups-filters 2.0.0"})
    np.device.driverless = False
    np.auto_driver = None
    np.ntbkNewPrinter = MagicMock()
    np.ntbkNewPrinter.get_current_page.return_value = newprinter.NewPrinterGUI.PAGE_DESCRIBE_PRINTER
    np.btnNPBack = MagicMock()
    np.btnNPForward = MagicMock()
    np.btnNPApply = MagicMock()
    np.btnNPChooseDriver = MagicMock()
    np.entNPName = MagicMock()
    np.entNPName.get_text.return_value = "Broken_Xerox_B235"
    np.printers = {}

    newprinter.NewPrinterGUI.setNPButtons(np)
    np.btnNPChooseDriver.show.assert_called_once()
    np.btnNPChooseDriver.hide.assert_not_called()


def test_non_driverless_ppd_object_button_visible_on_describe_page():
    """When self.ppd is a cups.PPD object for a normal non-driverless driver,
    btnNPChooseDriver must remain visible on PAGE_DESCRIBE_PRINTER."""
    np = get_dummy_gui()
    np.ppd = MockCupsPPD({"NickName": "HP LaserJet 4 Plus, hpcups 3.21.2"})
    np.device.driverless = False
    np.auto_driver = None
    np.ntbkNewPrinter = MagicMock()
    np.ntbkNewPrinter.get_current_page.return_value = newprinter.NewPrinterGUI.PAGE_DESCRIBE_PRINTER
    np.btnNPBack = MagicMock()
    np.btnNPForward = MagicMock()
    np.btnNPApply = MagicMock()
    np.btnNPChooseDriver = MagicMock()
    np.entNPName = MagicMock()
    np.entNPName.get_text.return_value = "HP_LaserJet_4"
    np.printers = {}

    newprinter.NewPrinterGUI.setNPButtons(np)
    np.btnNPChooseDriver.show.assert_called_once()
    np.btnNPChooseDriver.hide.assert_not_called()


def test_driverless_validation_success_sets_device_driverless_true():
    """When _validateDriverlessPPD succeeds, self.device.driverless should be set to True."""
    np = get_dummy_gui()
    np.ppds = MagicMock()
    np.ppds.getPPDNamesFromDeviceID.return_value = {"driverless:dnssd://...": "exact"}
    np.ppds.orderPPDNamesByPreference.return_value = ["driverless:dnssd://..."]
    np.installed_driver_files = []
    np.device.driverless = False
    np.device.id = "MFG:Xerox;MDL:B235;"
    np.device.id_dict = {"MFG": "Xerox", "MDL": "B235", "DES": "", "CMD": []}
    np.device.make_and_model = "Xerox B235"
    mock_ppd = MockCupsPPD({"NickName": "Xerox Xerox(R) B235 MFP, Fax, driverless, cups-filters 2.0.0"})
    np._validateDriverlessPPD = MagicMock(return_value=mock_ppd)
    np._installPrinterOrSearchForDriver = MagicMock(return_value=newprinter.NewPrinterGUI.INSTALL_RESULT_DONE)

    res = newprinter.NewPrinterGUI._installPrinterFromDeviceID(np, np.device.id, newprinter.NewPrinterGUI.PAGE_SELECT_DEVICE, 1)

    assert res == newprinter.NewPrinterGUI.INSTALL_RESULT_DONE
    assert np.device.driverless is True
    assert np._cached_driverless_ppd == mock_ppd


def test_choose_driver_ppdsloader_completion_populates_makes_without_back_forward(monkeypatch):
    """When self.ppds is None on Forward from PAGE_SELECT_DEVICE, PPD loader starts.
    Upon loader completion for a broken driverless printer, it automatically continues
    and directs to Choose Driver (PAGE_SELECT_INSTALL_METHOD) with Make list populated."""
    import ppdsloader
    np = get_dummy_gui()
    np._loadPPDsForDevice = newprinter.NewPrinterGUI._loadPPDsForDevice.__get__(np)
    np._installPrinterFromDeviceID = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    np._selectDeviceForInstallation = newprinter.NewPrinterGUI._selectDeviceForInstallation.__get__(np)
    np._handlePrinterInstallationStage = newprinter.NewPrinterGUI._handlePrinterInstallationStage.__get__(np)
    np._handlePrinterInstallationMode = newprinter.NewPrinterGUI._handlePrinterInstallationMode.__get__(np)
    np._getPagesOrderForDialogMode = newprinter.NewPrinterGUI._getPagesOrderForDialogMode.__get__(np)
    np._validateDriverlessPPD = MagicMock(return_value=None)
    np.nextNPTab = newprinter.NewPrinterGUI.nextNPTab.__get__(np)
    np.getDeviceURI = newprinter.NewPrinterGUI.getDeviceURI.__get__(np)
    np.setNPButtons = MagicMock()
    np.NewPrinterWindow = MagicMock()
    np.dialog_mode = "printer"
    np.remotecupsqueue = False
    np.exactdrivermatch = True
    np.searchedfordriverpackages = False
    np.founddownloadabledrivers = False
    np.installed_driver_files = []
    np.devid = None
    np._host = "localhost"
    np._encryption = 0
    np.fetchDevices_conn = None
    np.printer_finder = None
    np.ppds = None
    np.ppdsloader = None
    np.options = {}
    np.opreq = None

    dev = MagicMock()
    dev.id = "MFG:Xerox;MDL:B235 MFP;"
    dev.id_dict = {"MFG": "Xerox", "MDL": "B235 MFP", "DES": "", "CMD": []}
    dev.make_and_model = "Xerox B235 MFP"
    dev.uri = "ipps://Broken%20Xerox%20B235%20MFP._ipps._tcp.local"
    dev.type = "ipps"
    dev.driverless = True
    dev._driverless_failed = False
    dev.device_class = "network"
    np.device = dev

    current_page = [newprinter.NewPrinterGUI.PAGE_SELECT_DEVICE]
    np.ntbkNewPrinter = MagicMock()
    np.ntbkNewPrinter.get_current_page.side_effect = lambda: current_page[0]
    np.ntbkNewPrinter.set_current_page.side_effect = lambda p: current_page.__setitem__(0, p)

    np.ntbkPPDSource = MagicMock()
    np.rbtnNPDownloadableDriverSearch = MagicMock()
    np.rbtnNPDownloadableDriverSearch.get_active.return_value = False
    np.rbtnNPFoomatic = MagicMock()
    np.rbtnNPFoomatic.get_active.return_value = True
    np.rbtnNPPPD = MagicMock()
    np.rbtnNPPPD.get_active.return_value = False
    np.filechooserPPD = MagicMock()
    np.filechooserPPD.get_filename.return_value = ""
    np.btnNPForward = MagicMock()
    np.btnNPBack = MagicMock()
    np.btnNPApply = MagicMock()
    np.tvNPMakes = MagicMock()
    np.tvNPDrivers = MagicMock()
    np.entNPTDevice = MagicMock()
    np.entNPTDevice.get_text.return_value = ""
    np.entNPDownloadableDriverSearch = MagicMock()
    np.cmbNPDownloadableDriverFoundPrinters = MagicMock()
    np.cbNPDownloadableDriverFoundDrivers = MagicMock()
    np.btnNPDownloadableDriverSearch = MagicMock()

    fill_make_called = []
    np.fillMakeList = MagicMock(side_effect=lambda: fill_make_called.append(True))

    mock_opreq_cls = MagicMock()
    monkeypatch.setattr(newprinter, "OpenPrintingRequest", mock_opreq_cls)
    monkeypatch.setattr(newprinter, "busy", MagicMock())
    monkeypatch.setattr(newprinter, "ready", MagicMock())

    loader_callbacks = {}
    class FakeLoader:
        def __init__(self, **kwargs):
            self._jockey_has_answered = False
            self.device_id = kwargs.get('device_id')
            self.device_uri = kwargs.get('device_uri')
        def connect(self, signal, cb):
            loader_callbacks[signal] = cb
        def run(self): pass
        def get_error(self): return None
        def get_ppds(self):
            mock_ppds = MagicMock()
            mock_ppds.findMatches.return_value = []
            mock_ppds.getPPDNamesFromDeviceID.return_value = {}
            mock_ppds.orderPPDNamesByPreference.return_value = []
            mock_ppds.getMakes.return_value = ["Generic", "HP", "Xerox"]
            return mock_ppds
        def get_ppdsmatch_result(self): return None
        def get_installed_files(self): return []
        def destroy(self): pass

    monkeypatch.setattr(ppdsloader, "PPDsLoader", FakeLoader)

    np.btnNPChooseDriver = MagicMock()

    # 1. Forward clicked on PAGE_SELECT_DEVICE
    np.nextNPTab(step=1)

    # 2. PPDs were initially None: loader runs, page stays on PAGE_SELECT_DEVICE
    assert np.ppdsloader is not None
    assert fill_make_called == []
    assert current_page[0] == newprinter.NewPrinterGUI.PAGE_SELECT_DEVICE

    # 3. Simulate PPD loader completion
    finished_cb = loader_callbacks['finished']
    newprinter.NewPrinterGUI.on_ppdsloader_finished_next(np, np.ppdsloader)

    # 4. Without any user Back/Forward action, page transitions to Choose Driver and Make list is populated
    assert fill_make_called == [True]
    assert np.auto_make == "Xerox"
    assert current_page[0] == newprinter.NewPrinterGUI.PAGE_SELECT_INSTALL_METHOD
    assert mock_opreq_cls.called is False
    assert np.device.uri == "ipps://Broken%20Xerox%20B235%20MFP._ipps._tcp.local"


def test_choose_driver_with_existing_ppds_populates_makes_immediately(monkeypatch):
    """When self.ppds is already loaded, clicking 'Choose a different driver...'
    immediately opens PAGE_SELECT_INSTALL_METHOD with the Makes list populated."""
    np = get_dummy_gui()
    np._loadPPDsForDevice = newprinter.NewPrinterGUI._loadPPDsForDevice.__get__(np)
    np._installPrinterFromDeviceID = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    np._selectDeviceForInstallation = newprinter.NewPrinterGUI._selectDeviceForInstallation.__get__(np)
    np._handlePrinterInstallationStage = newprinter.NewPrinterGUI._handlePrinterInstallationStage.__get__(np)
    np._handlePrinterInstallationMode = newprinter.NewPrinterGUI._handlePrinterInstallationMode.__get__(np)
    np._getPagesOrderForDialogMode = newprinter.NewPrinterGUI._getPagesOrderForDialogMode.__get__(np)
    np.nextNPTab = newprinter.NewPrinterGUI.nextNPTab.__get__(np)
    np.getDeviceURI = newprinter.NewPrinterGUI.getDeviceURI.__get__(np)
    np.setNPButtons = MagicMock()
    np.NewPrinterWindow = MagicMock()
    np.dialog_mode = "printer"
    np.remotecupsqueue = False
    np.exactdrivermatch = True
    np.searchedfordriverpackages = False
    np.founddownloadabledrivers = False
    np.installed_driver_files = []
    np.devid = None
    np._host = "localhost"
    np._encryption = 0
    np.fetchDevices_conn = None
    np.printer_finder = None
    np.ppdsloader = None
    np.options = {}
    np.opreq = None

    mock_ppds = MagicMock()
    mock_ppds.findMatches.return_value = []
    mock_ppds.getPPDNamesFromDeviceID.return_value = {}
    mock_ppds.orderPPDNamesByPreference.return_value = []
    mock_ppds.getMakes.return_value = ["Generic", "HP", "Xerox"]
    np.ppds = mock_ppds

    dev = MagicMock()
    dev.id = "MFG:Xerox;MDL:B235 MFP;"
    dev.id_dict = {"MFG": "Xerox", "MDL": "B235 MFP", "DES": "", "CMD": []}
    dev.make_and_model = "Xerox B235 MFP"
    dev.uri = "ipps://Broken%20Xerox%20B235%20MFP._ipps._tcp.local"
    dev.type = "ipps"
    dev.driverless = True
    dev._driverless_failed = False
    dev.device_class = "network"
    np.device = dev

    current_page = [newprinter.NewPrinterGUI.PAGE_DESCRIBE_PRINTER]
    np.ntbkNewPrinter = MagicMock()
    np.ntbkNewPrinter.get_current_page.side_effect = lambda: current_page[0]
    np.ntbkNewPrinter.set_current_page.side_effect = lambda p: current_page.__setitem__(0, p)

    np.ntbkPPDSource = MagicMock()
    np.rbtnNPDownloadableDriverSearch = MagicMock()
    np.rbtnNPDownloadableDriverSearch.get_active.return_value = False
    np.rbtnNPFoomatic = MagicMock()
    np.rbtnNPFoomatic.get_active.return_value = True
    np.rbtnNPPPD = MagicMock()
    np.rbtnNPPPD.get_active.return_value = False
    np.filechooserPPD = MagicMock()
    np.filechooserPPD.get_filename.return_value = ""
    np.btnNPForward = MagicMock()
    np.btnNPBack = MagicMock()
    np.btnNPApply = MagicMock()
    np.tvNPMakes = MagicMock()
    np.tvNPDrivers = MagicMock()
    np.entNPTDevice = MagicMock()
    np.entNPTDevice.get_text.return_value = ""
    np.entNPDownloadableDriverSearch = MagicMock()
    np.cmbNPDownloadableDriverFoundPrinters = MagicMock()
    np.cbNPDownloadableDriverFoundDrivers = MagicMock()
    np.btnNPDownloadableDriverSearch = MagicMock()

    fill_make_called = []
    np.fillMakeList = MagicMock(side_effect=lambda: fill_make_called.append(True))

    mock_opreq_cls = MagicMock()
    monkeypatch.setattr(newprinter, "OpenPrintingRequest", mock_opreq_cls)
    monkeypatch.setattr(newprinter, "busy", MagicMock())
    monkeypatch.setattr(newprinter, "ready", MagicMock())

    np.btnNPChooseDriver = MagicMock()

    newprinter.NewPrinterGUI.on_btnNPChooseDriver_clicked(np, MagicMock())

    # PPDs already exist: no loader is started, button not disabled, directly transitions and populates
    assert np.ppdsloader is None
    np.btnNPChooseDriver.set_sensitive.assert_not_called()
    assert fill_make_called == [True]
    assert np.auto_make == "Xerox"
    assert current_page[0] == newprinter.NewPrinterGUI.PAGE_SELECT_INSTALL_METHOD
    assert mock_opreq_cls.called is False
    assert np.device.uri == "ipps://Broken%20Xerox%20B235%20MFP._ipps._tcp.local"


def test_state_machine_case1_working_driverless(monkeypatch):
    """CASE 1: Working driverless printer:
    Given driverless candidate, driverless PPD validation succeeds, self.ppds is None:
    - Forward starts PPD catalog loader (INSTALL_RESULT_OPS_PENDING)
    - After PPD loading completes, driverless PPD validation succeeds
    - driverless remains enabled
    - workflow reaches Describe Printer
    - driverless driver is selected
    - Choose Driver button is visible on Describe Printer
    """
    np = get_dummy_gui()
    np._installPrinterFromDeviceID = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    np._installPrinterOrSearchForDriver = newprinter.NewPrinterGUI._installPrinterOrSearchForDriver.__get__(np)
    np._loadPPDsForDevice = MagicMock()
    np._installHPScannerFilesIfNeeded = MagicMock()
    np._selectDeviceForInstallation = MagicMock()
    np.device.uri = "ipp://printer.local/ipp/print"
    np.device.driverless = True
    np.device._driverless_failed = False
    np.ppds = None

    mock_ppd = MockCupsPPD({"NickName": "Driverless Xerox Printer"})
    np._validateDriverlessPPD = MagicMock(return_value=mock_ppd)

    # 1. Forward clicked on PAGE_SELECT_DEVICE starts PPD loading
    res = newprinter.NewPrinterGUI._handlePrinterInstallationStage(
        np, newprinter.NewPrinterGUI.PAGE_SELECT_DEVICE, 1
    )
    np._loadPPDsForDevice.assert_called_once()
    assert res == newprinter.NewPrinterGUI.INSTALL_RESULT_OPS_PENDING

    # 2. Simulate PPD loading completion
    mock_ppds = MagicMock()
    mock_ppds.getMakes.return_value = ["Generic", "HP", "Xerox"]
    np.ppds = mock_ppds
    np.fillDriverList = MagicMock()
    np.fillMakeList = MagicMock()

    # Second run of stage after PPDs loaded
    res2 = newprinter.NewPrinterGUI._handlePrinterInstallationStage(
        np, newprinter.NewPrinterGUI.PAGE_SELECT_DEVICE, 1
    )
    assert res2 == newprinter.NewPrinterGUI.INSTALL_RESULT_DONE

    # Driverless remains enabled and driverless driver selected
    assert np.device.driverless is True
    assert np.exactdrivermatch is True
    assert np.auto_driver == "driverless:ipp://printer.local/ipp/print"

    # In dialog mode 'printer', with exactdrivermatch=True, order reaches PAGE_DESCRIBE_PRINTER
    order = newprinter.NewPrinterGUI._getPagesOrderForDialogMode(np)
    assert order == [
        newprinter.NewPrinterGUI.PAGE_SELECT_DEVICE,
        newprinter.NewPrinterGUI.PAGE_INSTALLABLE_OPTIONS,
        newprinter.NewPrinterGUI.PAGE_DESCRIBE_PRINTER,
    ]

    # Verify Choose Driver button is visible on Describe Printer
    np.ntbkNewPrinter = MagicMock()
    np.ntbkNewPrinter.get_current_page.return_value = newprinter.NewPrinterGUI.PAGE_DESCRIBE_PRINTER
    np.dialog_mode = "printer"
    np.btnNPBack = MagicMock()
    np.btnNPForward = MagicMock()
    np.btnNPApply = MagicMock()
    np.btnNPChooseDriver = MagicMock()
    np.entNPName = MagicMock()
    np.entNPName.get_text.return_value = "TestPrinter"
    np.printers = {}
    np.ppd = "driverless:ipp://printer.local/ipp/print"

    newprinter.NewPrinterGUI.setNPButtons(np)
    np.btnNPChooseDriver.show.assert_called_once()


def test_state_machine_case2_normal_non_driverless():
    """CASE 2: Normal non-driverless printer:
    Given normal printer, self.ppds is None:
    - Forward on PAGE_SELECT_DEVICE starts PPD catalog loader (INSTALL_RESULT_OPS_PENDING)
    - After PPD loading completes, driverless capability validation is not used
    - exactdrivermatch is False, so workflow directs to Choose Driver (PAGE_SELECT_INSTALL_METHOD)
    - Makes list is populated
    """
    np = get_dummy_gui()
    np._installPrinterFromDeviceID = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    np._installPrinterOrSearchForDriver = newprinter.NewPrinterGUI._installPrinterOrSearchForDriver.__get__(np)
    np._loadPPDsForDevice = MagicMock()
    np._installHPScannerFilesIfNeeded = MagicMock()
    np._selectDeviceForInstallation = MagicMock()
    np.device.uri = "socket://192.168.1.50"
    np.device.driverless = False
    np.device._driverless_failed = False
    np.ppds = None

    # 1. Forward clicked on PAGE_SELECT_DEVICE
    res = newprinter.NewPrinterGUI._handlePrinterInstallationStage(
        np, newprinter.NewPrinterGUI.PAGE_SELECT_DEVICE, 1
    )

    # Assert PPD loader is started and operations are pending
    np._loadPPDsForDevice.assert_called_once()
    assert res == newprinter.NewPrinterGUI.INSTALL_RESULT_OPS_PENDING

    # 2. Simulate PPD loading completion
    mock_ppds = MagicMock()
    mock_ppds.getMakes.return_value = ["Generic", "HP"]
    mock_ppds.getPPDNamesFromDeviceID.return_value = {"foomatic:HP-Generic": "exact"}
    mock_ppds.orderPPDNamesByPreference.return_value = ["foomatic:HP-Generic"]
    mock_ppds.getInfoFromPPDName.return_value = {"ppd-make-and-model": "HP Generic"}
    np.ppds = mock_ppds
    np.fillDriverList = MagicMock()
    np.fillMakeList = MagicMock()

    res2 = newprinter.NewPrinterGUI._handlePrinterInstallationStage(
        np, newprinter.NewPrinterGUI.PAGE_SELECT_DEVICE, 1
    )
    assert res2 == newprinter.NewPrinterGUI.INSTALL_RESULT_DONE
    assert np.exactdrivermatch is False
    np.fillMakeList.assert_called_once()

    order = newprinter.NewPrinterGUI._getPagesOrderForDialogMode(np)
    assert order == [
        newprinter.NewPrinterGUI.PAGE_SELECT_DEVICE,
        newprinter.NewPrinterGUI.PAGE_SELECT_INSTALL_METHOD,
        newprinter.NewPrinterGUI.PAGE_CHOOSE_DRIVER_FROM_DB,
        newprinter.NewPrinterGUI.PAGE_INSTALLABLE_OPTIONS,
        newprinter.NewPrinterGUI.PAGE_DESCRIBE_PRINTER,
    ]
    assert order[order.index(newprinter.NewPrinterGUI.PAGE_SELECT_DEVICE) + 1] == \
        newprinter.NewPrinterGUI.PAGE_SELECT_INSTALL_METHOD


def test_state_machine_case3_broken_driverless():
    """CASE 3: Broken driverless printer:
    Given driverless candidate, self.ppds is None:
    - Forward on PAGE_SELECT_DEVICE starts PPD catalog loader (INSTALL_RESULT_OPS_PENDING)
    - After PPD loading completes, driverless PPD validation fails:
      - driverless is disabled (device.driverless = False, device._driverless_failed = True, searchedfordriverpackages = True)
      - broken driverless URI is NOT selected as driver
      - OpenPrinting is NOT queried
      - workflow goes to Choose Driver (PAGE_SELECT_INSTALL_METHOD)
      - Makes list is populated
    """
    np = get_dummy_gui()
    np._installPrinterFromDeviceID = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    np._installPrinterOrSearchForDriver = newprinter.NewPrinterGUI._installPrinterOrSearchForDriver.__get__(np)
    np._loadPPDsForDevice = MagicMock()
    np._installHPScannerFilesIfNeeded = MagicMock()
    np._selectDeviceForInstallation = MagicMock()
    np.device.uri = "ipps://broken-xerox._ipps._tcp.local"
    np.device.id = "MFG:Xerox;MDL:B235 MFP;"
    np.device.id_dict = {"MFG": "Xerox", "MDL": "B235 MFP", "DES": "", "CMD": []}
    np.device.make_and_model = "Xerox B235 MFP"
    np.device.driverless = True
    np.ppds = None
    np._validateDriverlessPPD = MagicMock(return_value=None)

    # 1. Forward clicked on PAGE_SELECT_DEVICE starts PPD loading
    res = newprinter.NewPrinterGUI._handlePrinterInstallationStage(
        np, newprinter.NewPrinterGUI.PAGE_SELECT_DEVICE, 1
    )
    np._loadPPDsForDevice.assert_called_once()
    assert res == newprinter.NewPrinterGUI.INSTALL_RESULT_OPS_PENDING

    # 2. Simulate PPD loading completion
    mock_ppds = MagicMock()
    mock_ppds.getMakes.return_value = ["Generic", "Xerox"]
    mock_ppds.getPPDNamesFromDeviceID.return_value = {
        "driverless:ipps://broken-xerox._ipps._tcp.local": "exact",
        "foomatic:Xerox-Fallback": "close",
    }
    mock_ppds.orderPPDNamesByPreference.return_value = [
        "driverless:ipps://broken-xerox._ipps._tcp.local",
        "foomatic:Xerox-Fallback",
    ]
    np.ppds = mock_ppds
    np.fillDriverList = MagicMock()
    np.fillMakeList = MagicMock()

    # Second run of stage: driverless validation fails
    res2 = newprinter.NewPrinterGUI._handlePrinterInstallationStage(
        np, newprinter.NewPrinterGUI.PAGE_SELECT_DEVICE, 1
    )
    assert res2 == newprinter.NewPrinterGUI.INSTALL_RESULT_DONE
    assert np.device.driverless is False
    assert np.device._driverless_failed is True
    assert np.searchedfordriverpackages is True
    assert np.exactdrivermatch is False
    assert np.auto_driver != "driverless:ipps://broken-xerox._ipps._tcp.local"
    np.fillMakeList.assert_called_once()

    order = newprinter.NewPrinterGUI._getPagesOrderForDialogMode(np)
    assert order == [
        newprinter.NewPrinterGUI.PAGE_SELECT_DEVICE,
        newprinter.NewPrinterGUI.PAGE_SELECT_INSTALL_METHOD,
        newprinter.NewPrinterGUI.PAGE_CHOOSE_DRIVER_FROM_DB,
        newprinter.NewPrinterGUI.PAGE_INSTALLABLE_OPTIONS,
        newprinter.NewPrinterGUI.PAGE_DESCRIBE_PRINTER,
    ]
    assert order[order.index(newprinter.NewPrinterGUI.PAGE_SELECT_DEVICE) + 1] == \
        newprinter.NewPrinterGUI.PAGE_SELECT_INSTALL_METHOD


def test_state_machine_case4_choose_different_driver_with_ppds_available():
    """CASE 4: Choose different driver with PPDs available:
    Given Describe Printer, self.ppds is already populated.
    Click "Choose a different driver...":
    - driverless is disabled
    - manual selection mode is entered
    - PAGE_SELECT_INSTALL_METHOD is reached
    - Makes are populated
    - no PPD loader is started
    """
    np = get_dummy_gui()
    np._loadPPDsForDevice = MagicMock()
    np.device.driverless = True
    np.exactdrivermatch = True
    mock_ppds = MagicMock()
    mock_ppds.getMakes.return_value = ["Generic", "HP", "Xerox"]
    np.ppds = mock_ppds

    current_page = [newprinter.NewPrinterGUI.PAGE_DESCRIBE_PRINTER]
    np.ntbkNewPrinter = MagicMock()
    np.ntbkNewPrinter.get_current_page.side_effect = lambda: current_page[0]
    np.ntbkNewPrinter.set_current_page.side_effect = lambda p: current_page.__setitem__(0, p)
    np.rbtnNPFoomatic = MagicMock()
    np.on_rbtnNPFoomatic_toggled = MagicMock()
    fill_make_called = []
    np.fillMakeList = MagicMock(side_effect=lambda: fill_make_called.append(True))
    np.nextNPTab = MagicMock(side_effect=lambda step=1: fill_make_called.append(True))
    np.btnNPChooseDriver = MagicMock()

    newprinter.NewPrinterGUI.on_btnNPChooseDriver_clicked(np, MagicMock())

    assert np.device.driverless is False
    assert np.exactdrivermatch is False
    assert np.searchedfordriverpackages is True
    assert current_page[0] == newprinter.NewPrinterGUI.PAGE_SELECT_INSTALL_METHOD
    np._loadPPDsForDevice.assert_not_called()
    assert np.btnNPChooseDriver.set_sensitive.called is False
    assert len(fill_make_called) > 0


def test_state_machine_case5_choose_different_driver_after_legacy_fallback():
    """CASE 5: Choose different driver after legacy fallback:
    Given Broken driverless printer, PPD catalog already loaded, Describe Printer.
    Click "Choose a different driver...":
    - manual driver-selection workflow opens
    - Makes are populated
    - no second PPD loader is started
    """
    np = get_dummy_gui()
    np._loadPPDsForDevice = MagicMock()
    np.device.driverless = False
    np.device._driverless_failed = True
    np.exactdrivermatch = False
    mock_ppds = MagicMock()
    mock_ppds.getMakes.return_value = ["Generic", "HP", "Xerox"]
    np.ppds = mock_ppds
    np.ppdsloader = None

    current_page = [newprinter.NewPrinterGUI.PAGE_DESCRIBE_PRINTER]
    np.ntbkNewPrinter = MagicMock()
    np.ntbkNewPrinter.get_current_page.side_effect = lambda: current_page[0]
    np.ntbkNewPrinter.set_current_page.side_effect = lambda p: current_page.__setitem__(0, p)
    np.rbtnNPFoomatic = MagicMock()
    np.on_rbtnNPFoomatic_toggled = MagicMock()
    fill_make_called = []
    np.nextNPTab = MagicMock(side_effect=lambda step=1: fill_make_called.append(True))
    np.btnNPChooseDriver = MagicMock()

    newprinter.NewPrinterGUI.on_btnNPChooseDriver_clicked(np, MagicMock())

    assert np.device.driverless is False
    assert np.searchedfordriverpackages is True
    assert current_page[0] == newprinter.NewPrinterGUI.PAGE_SELECT_INSTALL_METHOD
    np._loadPPDsForDevice.assert_not_called()
    assert np.ppdsloader is None
    assert len(fill_make_called) > 0


def test_ppdsloader_separates_normal_and_driverless_ppds():
    """1. Verify ppdsloader.PPDsLoader calls getPPDs2 without exclude_schemes and separates normal and driverless PPDs."""
    import ppdsloader
    mock_conn = MagicMock()
    loader = ppdsloader.PPDsLoader()
    loader._cups_connect_reply(mock_conn, None)
    mock_conn.getPPDs2.assert_called_once()
    assert mock_conn.getPPDs2.call_args[1].get("exclude_schemes") is None

    cups_result = {
        "foomatic:HP-LaserJet.ppd": {
            "ppd-make-and-model": ["HP LaserJet"],
            "ppd-natural-language": ["en"],
            "ppd-make": ["HP"],
        },
        "driverless:ipps://Xerox%20B235._ipps._tcp.local/": {
            "ppd-make-and-model": ["Xerox B235 MFP, driverless, cups-filters 2.0.0"],
            "ppd-natural-language": ["en"],
            "ppd-make": ["Xerox"],
            "ppd-device-id": ["MFG:Xerox;MDL:B235 MFP;"],
        },
        "driverless-fax:ipps://Xerox%20B235%20Fax._ipps._tcp.local/": {
            "ppd-make-and-model": ["Xerox B235 Fax, driverless, cups-filters 2.0.0"],
            "ppd-natural-language": ["en"],
            "ppd-make": ["Xerox"],
        }
    }
    loader._cups_reply(mock_conn, cups_result)
    assert "foomatic:HP-LaserJet.ppd" in loader.get_ppds().ppds
    assert "driverless:ipps://Xerox%20B235._ipps._tcp.local/" not in loader.get_ppds().ppds
    assert "driverless-fax:ipps://Xerox%20B235%20Fax._ipps._tcp.local/" not in loader.get_ppds().ppds

    driverless = loader.get_driverless_ppds()
    assert "driverless:ipps://Xerox%20B235._ipps._tcp.local/" in driverless
    assert "driverless-fax:ipps://Xerox%20B235%20Fax._ipps._tcp.local/" in driverless
    assert driverless["driverless:ipps://Xerox%20B235._ipps._tcp.local/"] == cups_result["driverless:ipps://Xerox%20B235._ipps._tcp.local/"]


def test_scp_dbus_service_no_exclude_schemes():
    """1b. Verify scp-dbus-service FetchedPPDs calls getPPDs2 without exclude_schemes."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("scp_dbus_service", "scp-dbus-service.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mock_conn = MagicMock()
    f = mod.FetchedPPDs(mock_conn, "en")
    f.run()
    mock_conn.getPPDs2.assert_called_once()
    assert mock_conn.getPPDs2.call_args[1].get("exclude_schemes") is None


def test_broken_driverless_printer_no_catalog_entry():
    """2. A broken driverless printer:
       - driverless validation fails
       - no driverless:* entry is added to self.ppds
       - driverless does not appear as a selectable catalog driver
    """
    np = get_dummy_gui()
    np.device = cupshelpers.Device("ipp://broken-printer.local/ipp/print", **{"device-info": "driverless"})
    np.device.driverless = True
    np.ppds = cupshelpers.ppds.PPDs({
        "foomatic:sample.ppd": {
            "ppd-make-and-model": ["Sample Printer"],
            "ppd-natural-language": ["en"],
            "ppd-make": ["Sample"],
            "ppd-device-id": [""],
        }
    })
    np._validateDriverlessPPD = MagicMock(return_value=None)
    np._installPrinterOrSearchForDriver = MagicMock(return_value=newprinter.NewPrinterGUI.INSTALL_RESULT_DONE)

    real_install = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    real_install(None, 0, 1)

    assert np.device.driverless is False
    assert np.device._driverless_failed is True
    assert not any(k.startswith("driverless:") for k in np.ppds.ppds.keys())
    assert "Generic" not in np.ppds.getMakes()

    np.tvNPDrivers = MagicMock()
    mock_model = MagicMock()
    np.tvNPDrivers.get_model.return_value = mock_model
    real_fill = newprinter.NewPrinterGUI.fillDriverList.__get__(np)
    real_fill("Generic", "Driverless IPP")
    assert not any(p.startswith("driverless:") for p in np.NPDrivers)
    assert np.NPDrivers == []

    real_fill("Sample", "Printer")
    assert np.NPDrivers == ["foomatic:sample.ppd"]


def test_working_driverless_printer_catalog_entry_and_indexes():
    """3. A working driverless printer:
       - validation succeeds
       - exactly its current driverless:<URI> entry is added from saved driverless_ppds
       - the entry has the real printer identity metadata returned by CUPS
       - lazy indexes are invalidated/rebuilt correctly
    """
    uri = "ipp://working-printer.local/ipp/print"
    np = get_dummy_gui()
    np.device = cupshelpers.Device(
        uri,
        **{
            "device-info": "driverless",
            "device-id": "MFG:Xerox;MDL:B235 MFP;CMD:PCLM,POSTSCRIPT;",
            "device-make-and-model": "Xerox B235 MFP",
        }
    )
    np.device.driverless = True
    np.ppds = cupshelpers.ppds.PPDs({})
    np.ppds.makes = {"StaleMake": {}}
    np.ppds.ids = {"stale": {}}
    expected_entry = {
        "ppd-make-and-model": ["Xerox B235 MFP, driverless, cups-filters 2.0.0"],
        "ppd-natural-language": ["en"],
        "ppd-make": ["Xerox"],
        "ppd-device-id": ["MFG:Xerox;MDL:B235 MFP;CMD:PCLM,POSTSCRIPT;"],
        "ppd-type": ["pdf"],
    }
    np.driverless_ppds = {
        f"driverless:{uri}": expected_entry
    }
    mock_ppd = MagicMock(spec=cups.PPD)
    mock_ppd.findAttr.return_value = None
    np._validateDriverlessPPD = MagicMock(return_value=mock_ppd)
    np._installPrinterOrSearchForDriver = MagicMock(return_value=newprinter.NewPrinterGUI.INSTALL_RESULT_DONE)

    real_install = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    real_install(None, 0, 1)

    expected_key = f"driverless:{uri}"
    assert expected_key in np.ppds.ppds
    assert len([k for k in np.ppds.ppds if k.startswith("driverless:")]) == 1
    entry = np.ppds.ppds[expected_key]
    assert entry == expected_entry
    assert np._cached_driverless_ppd == mock_ppd
    assert np.ppds.makes is None
    assert np.ppds.ids is None

    assert "Xerox" in np.ppds.getMakes()
    assert "B235 MFP" in np.ppds.getModels("Xerox")


def test_legacy_printer_flow_unchanged():
    """4. A normal legacy printer:
       - no driverless validation is attempted
       - existing PPD matching remains unchanged
    """
    np = get_dummy_gui()
    np.device = cupshelpers.Device("usb://HP/LaserJet%201200", **{"device-id": "MFG:HP;MDL:LaserJet 1200;"})
    np.device.driverless = False
    mock_ppds = MagicMock()
    mock_ppds.getPPDNamesFromDeviceID.return_value = {"foomatic:HP-LaserJet_1200.ppd": "exact"}
    mock_ppds.orderPPDNamesByPreference.return_value = ["foomatic:HP-LaserJet_1200.ppd"]
    np.ppds = mock_ppds
    np._validateDriverlessPPD = MagicMock()
    np._installPrinterOrSearchForDriver = MagicMock(return_value=newprinter.NewPrinterGUI.INSTALL_RESULT_DONE)

    real_install = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    real_install("MFG:HP;MDL:LaserJet 1200;", 0, 1)

    np._validateDriverlessPPD.assert_not_called()
    assert np.id_matched_ppdnames == ["foomatic:HP-LaserJet_1200.ppd"]


def test_driverless_fax_never_added_to_catalog():
    """5. driverless-fax is never re-added to catalog."""
    np = get_dummy_gui()
    np.ppds = cupshelpers.ppds.PPDs({})
    np.driverless_ppds = {
        "driverless-fax:ipps://fax-device.local/": {
            "ppd-make": ["Xerox"],
            "ppd-make-and-model": ["Xerox Fax"],
        }
    }
    np._add_validated_driverless_ppd_to_catalog("driverless-fax:ipps://fax-device.local/")
    assert len(np.ppds.ppds) == 0


@pytest.mark.parametrize("uri", [
    "ipp://localhost:60000/ipp/print",
    "ipps://OfficeJet._ipps._tcp.local/",
])
def test_driverless_ipp_over_usb_and_network_ipps(uri):
    """6. Existing driverless behavior for working IPP-over-USB and network IPP/IPPS printers continues to work."""
    np = get_dummy_gui()
    np.device = cupshelpers.Device(uri, **{"device-info": "driverless"})
    np.device.driverless = True
    np.ppds = cupshelpers.ppds.PPDs({})
    expected_entry = {
        "ppd-make-and-model": ["HP OfficeJet, driverless"],
        "ppd-natural-language": ["en"],
        "ppd-make": ["HP"],
        "ppd-device-id": ["MFG:HP;MDL:OfficeJet;"],
        "ppd-type": ["pdf"],
    }
    np.driverless_ppds = {
        f"driverless:{uri}": expected_entry
    }
    mock_ppd = MagicMock(spec=cups.PPD)
    np._validateDriverlessPPD = MagicMock(return_value=mock_ppd)
    np._installPrinterOrSearchForDriver = MagicMock(return_value=newprinter.NewPrinterGUI.INSTALL_RESULT_DONE)

    real_install = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    real_install(None, 0, 1)

    expected_key = f"driverless:{uri}"
    assert expected_key in np.ppds.ppds
    assert np._cached_driverless_ppd == mock_ppd
    np._installPrinterOrSearchForDriver.assert_called_with(None, expected_key, "exact", 0, 1)


def test_regression_catalog_entry_contains_real_printer_identity():
    """Requirement 6-A: Catalog entry preserves exact CUPS-returned driverless metadata."""
    uri = "ipp://Xerox(R)%20B235%20MFP%20(USB)._ipp._tcp.local/"
    np = get_dummy_gui()
    np.device = cupshelpers.Device(
        uri,
        **{
            "device-info": "driverless",
            "device-id": "MFG:Xerox(R);MDL:B235 MFP;CMD:PCLM,PCL,PJL,PDF,POSTSCRIPT,FWV,URF;",
            "device-make-and-model": "Xerox(R) B235 MFP",
        }
    )
    np.device.driverless = True
    np.ppds = cupshelpers.ppds.PPDs({})
    cups_entry = {
        "ppd-make": ["Xerox"],
        "ppd-make-and-model": ["Xerox B235 MFP, driverless, cups-filters 2.0.0"],
        "ppd-device-id": ["MFG:Xerox;MDL:B235 MFP;CMD:PCLM,PCL,PJL,PDF,POSTSCRIPT,FWV,URF;"],
        "ppd-type": ["pdf"],
        "ppd-natural-language": ["en"],
    }
    np.driverless_ppds = {
        f"driverless:{uri}": cups_entry
    }

    np._add_validated_driverless_ppd_to_catalog(f"driverless:{uri}")

    expected_key = f"driverless:{uri}"
    assert expected_key in np.ppds.ppds
    entry = np.ppds.ppds[expected_key]
    assert entry == cups_entry


def test_regression_get_ppd_names_from_device_id_matches_validated_driverless():
    """Requirement 6-B: getPPDNamesFromDeviceID() matches the validated driverless PPD."""
    uri = "ipp://Xerox(R)%20B235%20MFP%20(USB)._ipp._tcp.local/"
    ppdname = f"driverless:{uri}"
    entry = {
        "ppd-make-and-model": ["Xerox B235 MFP, driverless, cups-filters 1.28.17"],
        "ppd-natural-language": ["en"],
        "ppd-make": ["Xerox"],
        "ppd-device-id": ["MFG:Xerox(R);MDL:B235 MFP;CMD:PCLM,PCL,PJL,PDF,POSTSCRIPT,FWV,URF;"],
        "ppd-type": ["pdf"],
    }
    ppds = cupshelpers.ppds.PPDs({ppdname: entry})
    devid_dict = cupshelpers.parseDeviceID(entry["ppd-device-id"][0])

    fit = ppds.getPPDNamesFromDeviceID(
        devid_dict["MFG"],
        devid_dict["MDL"],
        devid_dict["DES"],
        devid_dict["CMD"],
        uri,
        "Xerox(R) B235 MFP"
    )
    assert ppdname in fit
    assert fit[ppdname] == cupshelpers.ppds.PPDs.FIT_EXACT_CMD


def test_regression_order_ppd_names_by_preference_puts_driverless_first():
    """Requirement 6-C: orderPPDNamesByPreference() puts driverless first according to preferreddrivers.xml."""
    driverless_ppd = "driverless:ipp://Xerox(R)%20B235%20MFP%20(USB)._ipp._tcp.local/"
    legacy_ppd = "postscript-hp:0/ppd/hplip/HP/hp-designjet_t920-postscript.ppd"
    generic_ps_ppd = "drv:///sample.drv/generic.ppd"

    catalog_dict = {
        driverless_ppd: {
            "ppd-make-and-model": ["Xerox B235 MFP, driverless"],
            "ppd-natural-language": ["en"],
            "ppd-make": ["Xerox"],
            "ppd-device-id": ["MFG:Xerox(R);MDL:B235 MFP;CMD:PCLM,POSTSCRIPT;"],
            "ppd-type": ["pdf"],
        },
        legacy_ppd: {
            "ppd-make-and-model": ["HP DesignJet T920 Postscript"],
            "ppd-natural-language": ["en"],
            "ppd-make": ["HP"],
            "ppd-device-id": ["MFG:HP;MDL:DesignJet T920;CMD:POSTSCRIPT;"],
            "ppd-type": ["postscript"],
        },
        generic_ps_ppd: {
            "ppd-make-and-model": ["Generic PostScript Printer"],
            "ppd-natural-language": ["en"],
            "ppd-make": ["Generic"],
            "ppd-device-id": ["MFG:Generic;MDL:PostScript Printer;CMD:POSTSCRIPT;"],
            "ppd-type": ["postscript"],
        },
    }
    ppds = cupshelpers.ppds.PPDs(catalog_dict, xml_dir="xml")
    devid_dict = {"MFG": "Xerox(R)", "MDL": "B235 MFP", "DES": "", "CMD": ["PCLM", "POSTSCRIPT"]}
    fit = {
        driverless_ppd: cupshelpers.ppds.PPDs.FIT_EXACT_CMD,
        legacy_ppd: cupshelpers.ppds.PPDs.FIT_GENERIC,
        generic_ps_ppd: cupshelpers.ppds.PPDs.FIT_GENERIC,
    }
    ordered = ppds.orderPPDNamesByPreference(list(fit.keys()), [], devid=devid_dict, fit=fit)
    assert ordered[0] == driverless_ppd


def test_regression_xerox_b235_ipp_device_does_not_match_hp_designjet():
    uri = "ipp://Xerox(R)%20B235%20MFP%20(USB)._ipp._tcp.local/"
    driverless_ppd = f"driverless:{uri}"
    hp_designjet_ppd = "postscript-hp:0/ppd/hplip/HP/hp-designjet_t920-postscript.ppd"

    catalog_dict = {
        driverless_ppd: {
            "ppd-make-and-model": ["Xerox B235 MFP, driverless"],
            "ppd-natural-language": ["en"],
            "ppd-make": ["Xerox"],
            "ppd-device-id": ["MFG:Xerox(R);MDL:B235 MFP;CMD:PCLM,PCL,PJL,PDF,POSTSCRIPT,FWV,URF;"],
            "ppd-type": ["pdf"],
        },
        hp_designjet_ppd: {
            "ppd-make-and-model": ["HP DesignJet T920 Postscript"],
            "ppd-natural-language": ["en"],
            "ppd-make": ["HP"],
            "ppd-device-id": ["MFG:HP;MDL:DesignJet T920;CMD:POSTSCRIPT;"],
            "ppd-type": ["postscript"],
        },
    }
    ppds = cupshelpers.ppds.PPDs(catalog_dict, xml_dir="xml")

    np = get_dummy_gui()
    np.device = cupshelpers.Device(
        uri,
        **{
            "device-info": "driverless",
            "device-id": "MFG:Xerox(R);MDL:B235 MFP;CMD:PCLM,PCL,PJL,PDF,POSTSCRIPT,FWV,URF;",
            "device-make-and-model": "Xerox(R) B235 MFP",
        }
    )
    np.device.driverless = False
    np.ppds = ppds
    np.installed_driver_files = []
    np.fillDriverList = MagicMock()
    np.fillMakeList = MagicMock()
    np._validateDriverlessPPD = MagicMock(return_value=MagicMock(spec=cups.PPD))

    real_install = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    res = real_install(np.device.id, newprinter.NewPrinterGUI.PAGE_SELECT_INSTALL_METHOD, 0)

    assert hp_designjet_ppd not in np.id_matched_ppdnames
    assert np.auto_driver == driverless_ppd
    assert np.auto_make in ("Xerox", "Xerox(R)")
    assert np.auto_model == "B235 MFP"
    assert np.exactdrivermatch is False
    np.fillDriverList.assert_called_with(np.auto_make, "B235 MFP")


def test_regression_broken_driverless_validation_does_not_add_driverless_entry():
    """Requirement 6-E: Broken driverless validation does not add driverless entry."""
    uri = "ipp://Broken%20Xerox%20B235%20MFP._ipp._tcp.local/"
    np = get_dummy_gui()
    np.device = cupshelpers.Device(
        uri,
        **{
            "device-info": "driverless",
            "device-id": "MFG:Xerox(R);MDL:B235 MFP;CMD:PCLM,POSTSCRIPT;",
            "device-make-and-model": "Xerox(R) B235 MFP",
        }
    )
    np.device.driverless = True
    np.ppds = cupshelpers.ppds.PPDs({})
    np._validateDriverlessPPD = MagicMock(return_value=None)
    np._installPrinterOrSearchForDriver = MagicMock(return_value=newprinter.NewPrinterGUI.INSTALL_RESULT_DONE)

    real_install = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    real_install(None, 0, 1)

    assert len(np.ppds.ppds) == 0
    assert np.device._driverless_failed is True
    assert np.device.driverless is False
    assert np.id_matched_ppdnames == []
    np._installPrinterOrSearchForDriver.assert_called_with(None, None, None, 0, 1)


def test_regression_choose_driver_preserves_validated_driverless_and_strips_broken():
    """Requirement 6-F: 'Choose a different driver...' preserves the validated driverless
    option as recommended, but strips it if _driverless_failed is True."""
    uri = "ipp://Xerox%20B235._ipp._tcp.local/"
    driverless_ppd = f"driverless:{uri}"
    legacy_ppd = "foomatic:Generic-PostScript.ppd"

    np1 = get_dummy_gui()
    np1.device = cupshelpers.Device(
        uri,
        **{
            "device-id": "MFG:Xerox;MDL:B235 MFP;CMD:POSTSCRIPT;",
            "device-make-and-model": "Xerox B235 MFP",
        }
    )
    np1.device.driverless = False
    np1.device._driverless_failed = False
    np1.ppds = cupshelpers.ppds.PPDs({
        driverless_ppd: {
            "ppd-make-and-model": ["Xerox B235 MFP, driverless"],
            "ppd-natural-language": ["en"],
            "ppd-make": ["Xerox"],
            "ppd-device-id": ["MFG:Xerox;MDL:B235 MFP;CMD:POSTSCRIPT;"],
            "ppd-type": ["pdf"],
        },
        legacy_ppd: {
            "ppd-make-and-model": ["Generic PostScript Printer"],
            "ppd-natural-language": ["en"],
            "ppd-make": ["Generic"],
            "ppd-device-id": ["MFG:Generic;MDL:PostScript;CMD:POSTSCRIPT;"],
            "ppd-type": ["postscript"],
        },
    }, xml_dir="xml")
    np1.installed_driver_files = []
    np1.fillDriverList = MagicMock()
    np1.fillMakeList = MagicMock()
    np1._validateDriverlessPPD = MagicMock(return_value=MagicMock(spec=cups.PPD))

    install1 = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np1)
    install1(np1.device.id, newprinter.NewPrinterGUI.PAGE_SELECT_INSTALL_METHOD, 0)

    assert driverless_ppd in np1.id_matched_ppdnames
    assert np1.id_matched_ppdnames[0] == driverless_ppd
    assert np1.auto_driver == driverless_ppd
    assert np1.auto_make == "Xerox"
    assert np1.auto_model == "B235 MFP"
    assert np1.exactdrivermatch is False

    np2 = get_dummy_gui()
    np2.device = cupshelpers.Device(
        uri,
        **{
            "device-id": "MFG:Xerox;MDL:B235 MFP;CMD:POSTSCRIPT;",
            "device-make-and-model": "Xerox B235 MFP",
        }
    )
    np2.device.driverless = False
    np2.device._driverless_failed = True
    np2.ppds = cupshelpers.ppds.PPDs({
        driverless_ppd: {
            "ppd-make-and-model": ["Xerox B235 MFP, driverless"],
            "ppd-natural-language": ["en"],
            "ppd-make": ["Xerox"],
            "ppd-device-id": ["MFG:Xerox;MDL:B235 MFP;CMD:POSTSCRIPT;"],
            "ppd-type": ["pdf"],
        },
        legacy_ppd: {
            "ppd-make-and-model": ["Generic PostScript Printer"],
            "ppd-natural-language": ["en"],
            "ppd-make": ["Generic"],
            "ppd-device-id": ["MFG:Generic;MDL:PostScript;CMD:POSTSCRIPT;"],
            "ppd-type": ["postscript"],
        },
    }, xml_dir="xml")
    np2.installed_driver_files = []
    np2.fillDriverList = MagicMock()
    np2.fillMakeList = MagicMock()

    install2 = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np2)
    install2(np2.device.id, newprinter.NewPrinterGUI.PAGE_SELECT_INSTALL_METHOD, 0)

    assert driverless_ppd not in np2.id_matched_ppdnames
    assert np2.exactdrivermatch is False

def test_getNPPPD_explicit_legacy_override():
    np = get_dummy_gui()
    mock_ppd = MagicMock(spec=cups.PPD)
    np._cached_driverless_ppd = mock_ppd
    np._cached_driverless_ppd_name = "driverless:ipp://test"
    np.device = cupshelpers.Device("usb://test", **{"device-id": "MFG:HP;MDL:Test;", "device-make-and-model": "HP Test"})
    np.device.driverless = False
    np.founddownloadableppd = False

    np.rbtnNPFoomatic = MagicMock()
    np.rbtnNPFoomatic.get_active.return_value = True
    np.installed_driver_files = []

    legacy_ppd_str = "foomatic:HP/hp-designjet.ppd"
    np.NPDrivers = {0: legacy_ppd_str}

    mock_model = MagicMock()
    mock_iter = MagicMock()
    mock_model.get_path.return_value = (0,)

    np.tvNPDrivers = MagicMock()
    np.tvNPDrivers.get_selection.return_value.get_selected.return_value = (mock_model, mock_iter)

    result = np.getNPPPD()

    assert result == legacy_ppd_str
    assert result is not mock_ppd


def test_e2e_driverless_ppd_preserved_from_loader_to_catalog():
    """End-to-end test verifying that driverless PPD metadata comes purely from CUPS
    and is not reconstructed from device.id / device.make_and_model."""
    import ppdsloader
    mock_conn = MagicMock()
    loader = ppdsloader.PPDsLoader()

    cups_driverless_entry = {
        "ppd-make": ["Original CUPS Xerox"],
        "ppd-make-and-model": ["Original CUPS Xerox B235 MFP, driverless, cups-filters 2.0.0"],
        "ppd-device-id": ["MFG:Original CUPS Xerox;MDL:B235 MFP;CMD:PCLM,POSTSCRIPT;"],
        "ppd-type": ["pdf"],
        "ppd-natural-language": ["en"],
        "ppd-product": [""],
        "ppd-psversion": [""],
        "ppd-model-number": [0],
    }

    cups_result = {
        "foomatic:Generic-PostScript.ppd": {
            "ppd-make-and-model": ["Generic PostScript Printer"],
            "ppd-natural-language": ["en"],
            "ppd-make": ["Generic"],
        },
        "driverless:ipps://Xerox%20B235._ipps._tcp.local/": cups_driverless_entry,
        "driverless-fax:ipps://Xerox%20B235%20Fax._ipps._tcp.local/": {
            "ppd-make-and-model": ["Xerox Fax, driverless"],
            "ppd-natural-language": ["en"],
            "ppd-make": ["Xerox"],
        }
    }
    loader._cups_reply(mock_conn, cups_result)

    np = get_dummy_gui()
    np._getPPDs_reply(loader)

    # Catalog initially contains ONLY normal PPDs
    assert "foomatic:Generic-PostScript.ppd" in np.ppds.ppds
    assert "driverless:ipps://Xerox%20B235._ipps._tcp.local/" not in np.ppds.ppds
    assert "driverless-fax:ipps://Xerox%20B235%20Fax._ipps._tcp.local/" not in np.ppds.ppds

    # Device has different attributes (e.g. from IPP Get-Printer-Attributes firmware bug)
    uri = "ipps://Xerox%20B235._ipps._tcp.local/"
    np.device = cupshelpers.Device(
        uri,
        **{
            "device-info": "driverless",
            "device-id": "MFG:Inconsistent Firmware Xerox;MDL:Broken Firmware MDL;",
            "device-make-and-model": "Inconsistent Firmware Xerox Broken MDL",
        }
    )
    np.device.driverless = True

    # 1. Successful validation
    mock_cups_ppd = MagicMock(spec=cups.PPD)
    np._validateDriverlessPPD = MagicMock(return_value=mock_cups_ppd)
    np._installPrinterOrSearchForDriver = MagicMock(return_value=newprinter.NewPrinterGUI.INSTALL_RESULT_DONE)

    real_install = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    real_install(None, 0, 1)

    expected_key = f"driverless:{uri}"
    assert expected_key in np.ppds.ppds
    saved_entry = np.ppds.ppds[expected_key]

    # Verify that the entry is EXACTLY what CUPS returned, not what device.id reported
    assert saved_entry == cups_driverless_entry
    assert saved_entry["ppd-make"] == ["Original CUPS Xerox"]
    assert saved_entry["ppd-make"] != ["Inconsistent Firmware Xerox"]

    # 2. Failed validation scenario
    np_broken = get_dummy_gui()
    loader_broken = ppdsloader.PPDsLoader()
    loader_broken._cups_reply(mock_conn, cups_result)
    np_broken._getPPDs_reply(loader_broken)

    np_broken.device = cupshelpers.Device(uri, **{"device-info": "driverless"})
    np_broken.device.driverless = True
    np_broken._validateDriverlessPPD = MagicMock(return_value=None)
    np_broken._installPrinterOrSearchForDriver = MagicMock(return_value=newprinter.NewPrinterGUI.INSTALL_RESULT_DONE)

    real_install_broken = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np_broken)
    real_install_broken(None, 0, 1)

    assert expected_key not in np_broken.ppds.ppds
    assert np_broken.device._driverless_failed is True


def test_driverless_ppd_display_formatting():
    driverless_rec = "driverless:ipp://Xerox.local/"
    driverless_other = "driverless:ipp://Xerox2.local/"
    legacy_rec = "foomatic:Generic-PostScript.ppd"

    ppds = cupshelpers.ppds.PPDs({
        driverless_rec: {
            "ppd-make": ["Xerox"],
            "ppd-make-and-model": ["Xerox(R) B235 MFP, driverless, cups-filters 2.0.0"],
            "ppd-natural-language": ["en"],
            "ppd-device-id": ["MFG:Xerox;MDL:B235 MFP;"],
        },
        driverless_other: {
            "ppd-make": ["Xerox"],
            "ppd-make-and-model": ["Xerox(R) B235 MFP Alt, driverless"],
            "ppd-natural-language": ["en"],
            "ppd-device-id": ["MFG:Xerox;MDL:B235 MFP Alt;"],
        },
        legacy_rec: {
            "ppd-make": ["Generic"],
            "ppd-make-and-model": ["Generic PostScript Printer"],
            "ppd-natural-language": ["en"],
            "ppd-device-id": ["MFG:Generic;MDL:PostScript;"],
        }
    })

    np = get_dummy_gui()
    np.device = cupshelpers.Device("ipp://Xerox.local/", **{"device-make-and-model": "Xerox(R) B235 MFP"})
    np.device.id_dict = {"MFG": "Xerox", "MDL": "B235 MFP"}
    np.recommended_model_selected = True
    np.id_matched_ppdnames = [driverless_rec, driverless_other]
    np.ppds = ppds
    np.auto_driver = None
    np.installed_driver_files = []

    model = Gtk.ListStore(str)
    np.tvNPDrivers = MagicMock()
    np.tvNPDrivers.get_model.return_value = model
    np.tvNPDrivers.get_selection.return_value.select_path = MagicMock()
    np.tvNPDrivers.scroll_to_cell = MagicMock()
    np.tvNPDrivers.columns_autosize = MagicMock()

    real_fill = newprinter.NewPrinterGUI.fillDriverList.__get__(np)
    real_fill("Xerox", "B235 MFP")

    rows = [r[0] for r in model]
    assert rows[0] == "Xerox(R) B235 MFP, driverless, cups-filters 2.0.0 (driverless, recommended)"
    assert rows[1] == "Xerox(R) B235 MFP Alt, driverless (driverless)"

    np.id_matched_ppdnames = [legacy_rec]
    model.clear()
    real_fill("Generic", "PostScript")
    rows_legacy = [r[0] for r in model]
    assert rows_legacy[0] == "Generic PostScript Printer [en] (recommended)"

    np.device.make_and_model = None
    np.auto_driver = driverless_rec
    model.clear()
    real_fill("Xerox(R)", "B235 MFP")
    rows_current = [r[0] for r in model]
    assert rows_current[0] == "Xerox(R) B235 MFP, driverless, cups-filters 2.0.0 (driverless, Current)"


def test_choose_different_driver_recommends_validated_driverless_printer():
    import ppdsloader
    mock_conn = MagicMock()
    loader = ppdsloader.PPDsLoader()

    working_uri = "ipp://Xerox-B235.local/"
    working_ppdname = f"driverless:{working_uri}"
    working_cups_entry = {
        "ppd-make": ["Xerox"],
        "ppd-make-and-model": ["Xerox(R) B235 MFP, driverless, cups-filters 2.0.0"],
        "ppd-device-id": ["MFG:Xerox;MDL:Xerox(R) B235 MFP;CMD:PCLM,POSTSCRIPT;"],
        "ppd-type": ["pdf"],
        "ppd-natural-language": ["en"],
    }

    broken_uri = "ipp://Broken-Xerox-B235.local/"
    broken_ppdname = f"driverless:{broken_uri}"
    broken_cups_entry = {
        "ppd-make": ["Xerox"],
        "ppd-make-and-model": ["Broken Xerox B235 MFP, driverless, cups-filters 2.0.0"],
        "ppd-device-id": ["MFG:Xerox;MDL:Broken B235;CMD:PCLM;"],
        "ppd-type": ["pdf"],
        "ppd-natural-language": ["en"],
    }

    hp_ppdname = "postscript-hp:0/ppd/hplip/HP/hp-designjet_t920-postscript.ppd"
    hp_entry = {
        "ppd-make": ["HP"],
        "ppd-make-and-model": ["HP DesignJet T920 Postscript"],
        "ppd-natural-language": ["en"],
        "ppd-device-id": ["MFG:HP;MDL:DesignJet T920;CMD:POSTSCRIPT;"],
        "ppd-type": ["postscript"],
    }

    generic_entry = {
        "ppd-make": ["Generic"],
        "ppd-make-and-model": ["Generic PostScript Printer"],
        "ppd-natural-language": ["en"],
        "ppd-device-id": ["MFG:Generic;MDL:PostScript;CMD:POSTSCRIPT;"],
        "ppd-type": ["postscript"],
    }

    cups_result = {
        working_ppdname: working_cups_entry,
        broken_ppdname: broken_cups_entry,
        hp_ppdname: hp_entry,
        "foomatic:Generic-PostScript.ppd": generic_entry,
    }

    loader._cups_reply(mock_conn, cups_result)

    np = get_dummy_gui()
    np.device = cupshelpers.Device(working_uri, **{
        "device-info": "driverless",
        "device-id": "MFG:Xerox;MDL:B235 MFP;CMD:POSTSCRIPT;",
        "device-make-and-model": "Xerox(R) B235 MFP",
    })
    np.device.driverless = True
    np.installed_driver_files = []
    np.searchedfordriverpackages = False
    np.exactdrivermatch = False
    np.id_matched_ppdnames = []
    np.auto_make = ""
    np.auto_model = ""
    np.auto_driver = None
    np.recommended_make_selected = False
    np.recommended_model_selected = False

    makes_model = Gtk.ListStore(str, str)
    np.tvNPMakes = MagicMock()
    np.tvNPMakes.get_model.return_value = makes_model
    np.tvNPMakes.get_cursor.return_value = (Gtk.TreePath.new_first(), None)

    np.tvNPModels = MagicMock()
    np.models_liststore = Gtk.ListStore(str, str)
    np.models_filter = np.models_liststore.filter_new()
    np.entryNPModelsSearch = MagicMock()
    np.entryNPModelsSearch.get_text.return_value = ""

    drivers_model = Gtk.ListStore(str)
    np.tvNPDrivers = MagicMock()
    np.tvNPDrivers.get_model.return_value = drivers_model
    np.tvNPDrivers.get_selection.return_value.select_path = MagicMock()
    np.tvNPDrivers.scroll_to_cell = MagicMock()
    np.tvNPDrivers.columns_autosize = MagicMock()

    np.entNPDownloadableDriverSearch = MagicMock()
    np.rbtnNPFoomatic = MagicMock()
    np.on_rbtnNPFoomatic_toggled = MagicMock()
    np.ntbkNewPrinter = MagicMock()

    np._getPPDs_reply(loader)
    assert working_ppdname not in np.ppds.ppds
    assert broken_ppdname not in np.ppds.ppds
    assert "foomatic:Generic-PostScript.ppd" in np.ppds.ppds

    mock_ppd = MagicMock(spec=cups.PPD)
    np._validateDriverlessPPD = MagicMock(side_effect=lambda name: mock_ppd if name == working_ppdname else None)

    install_func = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    install_func(np.device.id, newprinter.NewPrinterGUI.PAGE_SELECT_DEVICE, 1)

    assert working_ppdname in np.ppds.ppds
    assert np.ppds.ppds[working_ppdname] == working_cups_entry
    assert np.auto_driver == working_ppdname
    assert np.auto_make in ("Xerox", "Xerox(R)")

    choose_driver_func = newprinter.NewPrinterGUI.on_btnNPChooseDriver_clicked.__get__(np)
    np.nextNPTab = MagicMock()
    choose_driver_func(None)

    assert np.device.driverless is False
    np.id_matched_ppdnames = []
    install_func(np.device.id, newprinter.NewPrinterGUI.PAGE_SELECT_INSTALL_METHOD, 0)

    assert np.auto_driver == working_ppdname
    assert hp_ppdname not in np.id_matched_ppdnames
    assert np.auto_make in ("Xerox", "Xerox(R)")
    assert np.auto_model == "B235 MFP"

    np.fillMakeList()
    makes_rows = [r[0] for r in makes_model]

    assert "Xerox(R) B235 MFP (driverless, recommended)" in makes_rows
    assert not any("Generic" in r and "(recommended)" in r for r in makes_rows)

    np.NPMake = np.auto_make
    np.recommended_make_selected = True
    np.fillModelList()

    models_rows = [r[0] for r in np.models_liststore]
    assert "B235 MFP (recommended)" in models_rows

    np.recommended_model_selected = True
    np.fillDriverList(np.NPMake, np.auto_model)
    driver_rows = [r[0] for r in drivers_model]

    assert driver_rows[0] == "Xerox(R) B235 MFP, driverless, cups-filters 2.0.0 (driverless, recommended)"
    assert not any("Generic" in r and "(recommended)" in r for r in driver_rows)
    assert not any("HP" in r and "(recommended)" in r for r in driver_rows)

    np_broken = get_dummy_gui()
    np_broken.device = cupshelpers.Device(broken_uri, **{
        "device-info": "driverless",
        "device-id": "MFG:Xerox;MDL:Broken B235;CMD:PCLM;",
        "device-make-and-model": "Broken Xerox B235",
    })
    np_broken.device.driverless = True
    np_broken.installed_driver_files = []
    np_broken.searchedfordriverpackages = False
    np_broken._validateDriverlessPPD = MagicMock(return_value=None)
    np_broken._installPrinterOrSearchForDriver = MagicMock(return_value=newprinter.NewPrinterGUI.INSTALL_RESULT_DONE)
    np_broken._getPPDs_reply(loader)

    install_broken = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np_broken)
    install_broken(np_broken.device.id, newprinter.NewPrinterGUI.PAGE_SELECT_DEVICE, 1)

    assert np_broken.device.driverless is False
    assert np_broken.device._driverless_failed is True
    assert broken_ppdname not in np_broken.ppds.ppds
    assert np_broken.id_matched_ppdnames == []

def test_legacy_recommended_labels():
    np = get_dummy_gui()
    np.device = cupshelpers.Device("usb://HP/LaserJet%201018", **{
        "device-id": "MFG:HP;MDL:LaserJet 1018;CMD:ZJS;",
        "device-make-and-model": "HP LaserJet 1018",
    })
    np.device.driverless = False
    np.auto_driver = "foomatic:HP-LaserJet_1018-foo.ppd"
    np.auto_make = "HP"
    np.auto_model = "LaserJet 1018"

    np.ppds = MagicMock(spec=cupshelpers.ppds.PPDs)
    np.ppds.getMakes.return_value = ["HP", "Epson"]
    np.ppds.getModels.return_value = ["LaserJet 1018", "LaserJet 1020"]

    makes_model = Gtk.ListStore(str, str)
    np.tvNPMakes = MagicMock()
    np.tvNPMakes.get_model.return_value = makes_model
    np.entNPDownloadableDriverSearch = MagicMock()

    np.fillMakeList()
    makes_rows = [r[0] for r in makes_model]

    assert "HP (recommended)" in makes_rows

    np.tvNPModels = MagicMock()
    np.models_liststore = Gtk.ListStore(str, str)
    np.models_filter = MagicMock()
    np.entryNPModelsSearch = MagicMock()
    np.entryNPModelsSearch.get_text.return_value = ""

    np.NPMake = "HP"
    np.fillModelList()
    models_rows = [r[0] for r in np.models_liststore]
    assert "LaserJet 1018 (recommended)" in models_rows

def test_driverless_uri_variations_trailing_slash_and_encoding():
    import ppdsloader
    mock_conn = MagicMock()
    loader = ppdsloader.PPDsLoader()

    cups_uri = "ipps://Xerox%28R%29%20B235%20MFP._ipps._tcp.local/"
    cups_ppdname = f"driverless:{cups_uri}"
    cups_entry = {
        "ppd-make": ["Xerox"],
        "ppd-make-and-model": ["Xerox(R) B235 MFP, driverless, cups-filters 2.0.0"],
        "ppd-device-id": ["MFG:Xerox;MDL:Xerox(R) B235 MFP;CMD:POSTSCRIPT;"],
        "ppd-type": ["pdf"],
        "ppd-natural-language": ["en"],
    }
    hp_fallback = "postscript-hp:0/ppd/hplip/HP/hp-designjet_t920-postscript.ppd"
    cups_result = {
        cups_ppdname: cups_entry,
        hp_fallback: {
            "ppd-make": ["HP"],
            "ppd-make-and-model": ["HP DesignJet T920 Postscript"],
            "ppd-device-id": ["MFG:HP;MDL:DesignJet T920;CMD:POSTSCRIPT;"],
            "ppd-type": ["postscript"],
            "ppd-natural-language": ["en"],
        },
    }
    loader._cups_reply(mock_conn, cups_result)

    device_uri = "ipps://Xerox(R)%20B235%20MFP._ipps._tcp.local"
    np = get_dummy_gui()
    np.device = cupshelpers.Device(device_uri, **{
        "device-info": "driverless",
        "device-id": "MFG:Xerox;MDL:B235 MFP;CMD:POSTSCRIPT;",
        "device-make-and-model": "Xerox(R) B235 MFP",
    })
    np.device.driverless = True
    np.installed_driver_files = []
    np.searchedfordriverpackages = False
    np.exactdrivermatch = False
    np.id_matched_ppdnames = []
    np.auto_make = ""
    np.auto_model = ""
    np.auto_driver = None
    np.fillDriverList = MagicMock()
    np.fillMakeList = MagicMock()
    np.rbtnNPFoomatic = MagicMock()
    np.on_rbtnNPFoomatic_toggled = MagicMock()
    np.ntbkNewPrinter = MagicMock()

    mock_ppd = MagicMock(spec=cups.PPD)
    np._validateDriverlessPPD = MagicMock(return_value=mock_ppd)

    np._getPPDs_reply(loader)
    install_func = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    install_func(np.device.id, newprinter.NewPrinterGUI.PAGE_SELECT_DEVICE, 1)

    assert any(k.startswith("driverless:ipps://Xerox") for k in np.ppds.ppds)
    assert np.auto_driver.startswith("driverless:ipps://Xerox")

    choose_driver_func = newprinter.NewPrinterGUI.on_btnNPChooseDriver_clicked.__get__(np)
    np.nextNPTab = MagicMock()
    choose_driver_func(None)

    assert np.device.driverless is False
    np.id_matched_ppdnames = []
    install_func(np.device.id, newprinter.NewPrinterGUI.PAGE_SELECT_INSTALL_METHOD, 0)

    assert np.auto_driver.startswith("driverless:ipps://Xerox")
    assert hp_fallback not in np.id_matched_ppdnames
    assert np.auto_make in ("Xerox", "Xerox(R)")
    assert np.auto_model == "B235 MFP"

def test_cached_driverless_ppd_survives_getNPPPD_clearing():
    import ppdsloader

    device_uri = "ipps://Xerox(R)%20B235%20MFP._ipps._tcp.local/"
    ppdname = f"driverless:{device_uri}"

    hp_ppdname = "postscript-hp:0/ppd/hplip/HP/hp-designjet_t920-postscript.ppd"
    hp_entry = {
        "ppd-make": ["HP"],
        "ppd-make-and-model": ["HP DesignJet T920 Postscript"],
        "ppd-natural-language": ["en"],
        "ppd-device-id": ["MFG:HP;MDL:DesignJet T920;CMD:POSTSCRIPT;"],
        "ppd-type": ["postscript"],
    }
    generic_entry = {
        "ppd-make": ["Generic"],
        "ppd-make-and-model": ["Generic PostScript Printer"],
        "ppd-natural-language": ["en"],
        "ppd-device-id": ["MFG:Generic;MDL:PostScript;CMD:POSTSCRIPT;"],
        "ppd-type": ["postscript"],
    }

    mock_conn = MagicMock()
    loader = ppdsloader.PPDsLoader()
    cups_result_no_driverless = {
        hp_ppdname: hp_entry,
        "foomatic:Generic-PostScript.ppd": generic_entry,
    }
    loader._cups_reply(mock_conn, cups_result_no_driverless)

    np = get_dummy_gui()
    np.device = cupshelpers.Device(device_uri, **{
        "device-info": "driverless",
        "device-id": "MFG:Xerox;MDL:Xerox(R) B235 MFP;CMD:PCLM,PS,PWGRaster;",
        "device-make-and-model": "Xerox(R) B235 MFP",
    })
    np.device.driverless = True
    np.installed_driver_files = []
    np.searchedfordriverpackages = False
    np.exactdrivermatch = False
    np.id_matched_ppdnames = []
    np.auto_make = ""
    np.auto_model = ""
    np.auto_driver = None
    np.recommended_make_selected = False
    np.recommended_model_selected = False
    np.fillDriverList = MagicMock()
    np.fillMakeList = MagicMock()
    np.rbtnNPFoomatic = MagicMock()
    np.on_rbtnNPFoomatic_toggled = MagicMock()
    np.ntbkNewPrinter = MagicMock()

    mock_ppd = MagicMock(spec=cups.PPD)
    mock_nickname = MagicMock()
    mock_nickname.value = "Xerox B235 MFP, driverless, 2.0.0"
    mock_manufacturer = MagicMock()
    mock_manufacturer.value = "Xerox"
    def mock_findAttr(name):
        if name == "NickName":
            return mock_nickname
        if name == "Manufacturer":
            return mock_manufacturer
        return None
    mock_ppd.findAttr = mock_findAttr
    np._validateDriverlessPPD = MagicMock(return_value=mock_ppd)

    np._getPPDs_reply(loader)
    assert np.driverless_ppds == {}

    install_func = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    install_func(np.device.id, newprinter.NewPrinterGUI.PAGE_SELECT_DEVICE, 1)

    assert np._cached_driverless_ppd is mock_ppd
    assert np._cached_driverless_ppd_name == ppdname
    assert ppdname in np.ppds.ppds
    assert np.auto_driver == ppdname

    assert ppdname in np.driverless_ppds
    assert np.driverless_ppds[ppdname]["ppd-make-and-model"] == \
        "Xerox B235 MFP, driverless, 2.0.0"

    np._cached_driverless_ppd = None

    assert np._cached_driverless_ppd_name == ppdname

    np.device.driverless = False
    np.exactdrivermatch = False
    np.searchedfordriverpackages = True
    np.id_matched_ppdnames = []
    np.auto_make = ""
    np.auto_model = ""
    np.auto_driver = None

    install_func(np.device.id, newprinter.NewPrinterGUI.PAGE_SELECT_INSTALL_METHOD, 0)

    assert np.auto_driver == ppdname
    assert hp_ppdname not in np.id_matched_ppdnames
    assert np.auto_make in ("Xerox", "Xerox(R)")

    assert np._cached_driverless_ppd is mock_ppd
def test_ppdsloader_packagekit_private_bus_disables_exit_on_disconnect_and_falls_back(monkeypatch):
    """Verify that PPDsLoader's PackageKit worker disables exit_on_disconnect on its private
    D-Bus connection, transfers the bus to the main thread callback where it is closed, and
    falls back to querying CUPS."""
    import ppdsloader
    import dbus
    import threading
    from gi.repository import GLib

    loader = ppdsloader.PPDsLoader(device_id="MFG:Test;MDL:Printer;", device_uri="ipp://test/ipp/print")
    loader._gpk_device_id = "MFG:Test;MDL:Printer;"
    loader._query_cups = MagicMock()

    mock_bus = MagicMock()
    monkeypatch.setattr(dbus, "SessionBus", MagicMock(return_value=mock_bus))

    mock_proxy = MagicMock()
    mock_proxy.InstallPrinterDrivers.side_effect = dbus.exceptions.DBusException("AppArmor blocked")
    monkeypatch.setattr(dbus, "Interface", MagicMock(return_value=mock_proxy))

    idle_add_mock = MagicMock(side_effect=lambda func, *args: func(*args))
    monkeypatch.setattr(threading, "Thread", lambda target, daemon=True: MagicMock(start=target))
    monkeypatch.setattr(GLib, "idle_add", idle_add_mock)

    loader._query_packagekit()

    dbus.SessionBus.assert_called_once_with(private=True)
    mock_bus.set_exit_on_disconnect.assert_called_once_with(False)
    idle_add_mock.assert_called_once_with(loader._on_packagekit_done, False, mock_bus)
    mock_bus.close.assert_called_once()
    loader._query_cups.assert_called_once()

def test_duplicate_mode_page_order():
    np = get_dummy_gui()
    np.dialog_mode = "duplicate"
    order = np._getPagesOrderForDialogMode()
    assert order == [
        np.PAGE_DESCRIBE_PRINTER,
        np.PAGE_INSTALLABLE_OPTIONS,
    ]


def test_make_name_unique_uses_incrementing_collision_suffixes():
    np = get_dummy_gui()
    np.printers = {}
    assert np.makeNameUnique("printer") == "printer"

    existing = type("ExistingPrinter", (), {
        "discovered": False,
        "name": "printer",
    })()
    np.printers = {"printer": existing}
    assert np.makeNameUnique("printer") == "printer-2"

    np.printers["printer-1"] = type("ExistingPrinter", (), {
        "discovered": False,
        "name": "printer-1",
    })()
    assert np.makeNameUnique("printer") == "printer-2"

    np.printers["printer-2"] = type("ExistingPrinter", (), {
        "discovered": False,
        "name": "printer-2",
    })()
    assert np.makeNameUnique("printer") == "printer-3"


@pytest.mark.parametrize("source_name,existing_names,expected_name", [
    ("Printer", ["Printer"], "Printer-1"),
    ("Printer", ["Printer", "Printer-1", "Printer-2"], "Printer-3"),
    ("Printer-2", ["Printer-2"], "Printer-3"),
    ("Printer-2", ["Printer-2", "Printer-3"], "Printer-4"),
    ("Printer2", ["Printer2"], "Printer2-1"),
    ("Printer123", ["Printer123"], "Printer123-1"),
    ("Printer-2024-A", ["Printer-2024-A"], "Printer-2024-A-1"),
    ("Boomaga", ["Boomaga"], "Boomaga-1"),
    ("Boomaga", ["Boomaga", "Boomaga-1"], "Boomaga-2"),
    ("Boomaga", ["Boomaga", "Boomaga-1", "Boomaga-2"], "Boomaga-3"),
    ("Boomaga-2", ["Boomaga-2"], "Boomaga-3"),
    ("Boomaga-2", ["Boomaga-2", "Boomaga-3"], "Boomaga-4"),
    ("Xerox-Xerox(R)-B235-MFP", ["Xerox-Xerox(R)-B235-MFP"],
     "Xerox-Xerox(R)-B235-MFP-1"),
])
def test_duplicate_name_uses_existing_queue_name(source_name, existing_names,
                                                 expected_name):
    np = get_dummy_gui()
    np.printers = {
        name: MockExistingPrinter(name)
        for name in existing_names
    }

    assert np._makeDuplicateNameUnique(source_name) == expected_name


def test_duplicate_initialisation_preserves_metadata_and_original_ppd(monkeypatch):
    monkeypatch.setattr(cups, "PPD", MockCupsPPD)
    np = get_dummy_gui()
    np._name = "Office Printer"
    np._device_uri = "ipp://printer.example/ipp/print"
    np._description = "Original description"
    np._location = "Reception"
    np._is_shared = True
    np.orig_ppd = MockCupsPPD({"NickName": "Xerox B235 MFP"})
    np._makeDuplicateNameUnique = MagicMock(return_value="Office-Printer")
    np.entNPName = MagicMock()
    np.entNPLocation = MagicMock()
    np.entNPDescription = MagicMock()
    np.entNPDriver = MagicMock()
    np.entSMBURI = MagicMock()
    np.entSMBUsername = MagicMock()
    np.entSMBPassword = MagicMock()
    np.isSharedCbx = MagicMock()
    np.rbtnChangePPDKeepSettings = MagicMock()
    np.NewPrinterWindow = MagicMock()
    np.ntbkNewPrinter = MagicMock()

    np._initialiseDuplicateMode()

    assert np.ppd is np.orig_ppd
    assert np.device.id == ""
    assert np.device.make_and_model == ""
    np.entNPName.set_text.assert_called_with("Office-Printer")
    np.entNPDescription.set_text.assert_called_with("Original description")
    np.entNPLocation.set_text.assert_called_with("Reception")
    np.isSharedCbx.set_active.assert_called_with(True)
    np.entNPDriver.set_text.assert_called_with("Xerox B235 MFP")
    np._makeDuplicateNameUnique.assert_called_with("Office Printer")
    np.ntbkNewPrinter.set_current_page.assert_called_with(
        np.PAGE_DESCRIBE_PRINTER)


def test_duplicate_initialisation_reuses_discovered_device_identity(monkeypatch):
    monkeypatch.setattr(cups, "PPD", MockCupsPPD)
    np = get_dummy_gui()
    np._name = "Office Printer"
    np._device_uri = "ipps://Xerox%20B235._ipps._tcp.local"
    np._description = "Original description"
    np._location = "Reception"
    np._is_shared = True
    np.orig_ppd = MockCupsPPD({"NickName": "Xerox B235 MFP"})
    np.discovered_device = cupshelpers.Device(
        np._device_uri,
        **{"device-id": "MFG:Xerox;MDL:Xerox(R) B235 MFP;"
           "CMD:PCLM,PS,PWGRaster;",
              "device-info": "Xerox printer (driverless)",
           "device-make-and-model": "Xerox Xerox(R) B235 MFP"})
    np._makeDuplicateNameUnique = MagicMock(return_value="Office-Printer")
    np.entNPName = MagicMock()
    np.entNPLocation = MagicMock()
    np.entNPDescription = MagicMock()
    np.entNPDriver = MagicMock()
    np.entSMBURI = MagicMock()
    np.entSMBUsername = MagicMock()
    np.entSMBPassword = MagicMock()
    np.isSharedCbx = MagicMock()
    np.rbtnChangePPDKeepSettings = MagicMock()
    np.NewPrinterWindow = MagicMock()
    np.ntbkNewPrinter = MagicMock()

    np._initialiseDuplicateMode()

    assert np.device is np.discovered_device
    assert np.device.driverless is True
    assert np.device.id_dict["MFG"] == "Xerox"
    assert np.device.id_dict["MDL"] == "Xerox(R) B235 MFP"
    assert np.device.id_dict["CMD"] == ["PCLM", "PS", "PWGRaster"]
    np._makeDuplicateNameUnique.assert_called_with("Office Printer")


def test_duplicate_uses_queue_name_for_suffixed_source(monkeypatch):
    monkeypatch.setattr(cups, "PPD", MockCupsPPD)
    np = get_dummy_gui()
    np._name = "Xerox-Xerox(R)-B235-MFP-2"
    np._device_uri = "ipps://Xerox%20B235._ipps._tcp.local"
    np._description = "Original description"
    np._location = "Reception"
    np._is_shared = True
    np.orig_ppd = MockCupsPPD({"NickName": "Xerox B235 MFP"})
    np.discovered_device = cupshelpers.Device(
        np._device_uri,
        **{"device-id": "MFG:Xerox;MDL:Xerox(R) B235 MFP;",
           "device-make-and-model": "Xerox Xerox(R) B235 MFP"})
    np._makeDuplicateNameUnique = MagicMock(
        return_value="Xerox-Xerox(R)-B235-MFP-4")
    np.entNPName = MagicMock()
    np.entNPLocation = MagicMock()
    np.entNPDescription = MagicMock()
    np.entNPDriver = MagicMock()
    np.entSMBURI = MagicMock()
    np.entSMBUsername = MagicMock()
    np.entSMBPassword = MagicMock()
    np.isSharedCbx = MagicMock()
    np.rbtnChangePPDKeepSettings = MagicMock()
    np.NewPrinterWindow = MagicMock()
    np.ntbkNewPrinter = MagicMock()

    np._initialiseDuplicateMode()

    np._makeDuplicateNameUnique.assert_called_with("Xerox-Xerox(R)-B235-MFP-2")
    np.entNPName.set_text.assert_called_with(
        "Xerox-Xerox(R)-B235-MFP-4")


def test_duplicate_initialisation_falls_back_without_fake_device_identity(monkeypatch):
    monkeypatch.setattr(cups, "PPD", MockCupsPPD)
    np = get_dummy_gui()
    np._name = "Unavailable Printer"
    np._device_uri = "ipps://unavailable.example/ipp/print"
    np._description = "Original description"
    np._location = "Reception"
    np._is_shared = False
    np.orig_ppd = MockCupsPPD({"NickName": "Original Driver"})
    np.device_id = ""
    np.device_make_and_model = ""
    np._makeDuplicateNameUnique = MagicMock(return_value="Unavailable-Printer")
    np.entNPName = MagicMock()
    np.entNPLocation = MagicMock()
    np.entNPDescription = MagicMock()
    np.entNPDriver = MagicMock()
    np.entSMBURI = MagicMock()
    np.entSMBUsername = MagicMock()
    np.entSMBPassword = MagicMock()
    np.isSharedCbx = MagicMock()
    np.rbtnChangePPDKeepSettings = MagicMock()
    np.NewPrinterWindow = MagicMock()
    np.ntbkNewPrinter = MagicMock()

    np._initialiseDuplicateMode()

    assert np.ppd is np.orig_ppd
    assert np.device.id == ""
    assert np.device.make_and_model == ""
    assert np.device.id_dict["MFG"] == ""
    assert np.device.id_dict["MDL"] == ""
def test_duplicate_forward_uses_original_ppd_without_loading_or_matching():
    np = get_dummy_gui()
    np.dialog_mode = "duplicate"
    np.duplicate_driver_selection = False
    np.orig_ppd = MockCupsPPD({"NickName": "Xerox B235 MFP"})
    np.ppd = np.orig_ppd
    np.ntbkNewPrinter = MagicMock()
    np.ntbkNewPrinter.get_current_page.return_value = np.PAGE_DESCRIBE_PRINTER
    np.btnNPForward = MagicMock()
    np.btnNPApply = MagicMock()
    np.btnNPBack = MagicMock()
    np.entNPName = MagicMock()
    np.entNPDriver = MagicMock()
    np.entNPName.get_text.return_value = "Xerox"
    np.printers = {}
    np.installable_options = False
    np.fillNPInstallableOptions = MagicMock(
        side_effect=lambda: setattr(np, "installable_options", True))
    np._handlePrinterInstallationMode = MagicMock()
    np.getNPPPD = MagicMock()
    np.setNPButtons = MagicMock()

    newprinter.NewPrinterGUI.nextNPTab(np)

    np._handlePrinterInstallationMode.assert_not_called()
    np.getNPPPD.assert_not_called()
    np._loadPPDsForDevice.assert_not_called()
    np.ntbkNewPrinter.set_current_page.assert_called_with(
        np.PAGE_INSTALLABLE_OPTIONS)
    assert np.ppd is np.orig_ppd


def test_duplicate_state_two_uses_existing_ppd_loader():
    np = get_dummy_gui()
    np.dialog_mode = "duplicate"
    np.duplicate_driver_selection = True
    np.ppds = None
    np._selectDeviceForInstallation = MagicMock()
    np._installHPScannerFilesIfNeeded = MagicMock()
    np._loadPPDsForDevice = MagicMock()

    result = newprinter.NewPrinterGUI._handlePrinterInstallationStage(
        np, newprinter.NewPrinterGUI.PAGE_SELECT_INSTALL_METHOD, 0)

    np._loadPPDsForDevice.assert_called_once()
    assert result == newprinter.NewPrinterGUI.INSTALL_RESULT_OPS_PENDING

def test_regression_getServerPPD_cancellation_real_v2_race(monkeypatch):
    """
    Test the V2 worker + nested GLib + on_NPCancel() production path.
    Verifies that real cancellation respects the worker thread lifecycle
    and does not trigger AttributeError when the late worker completes.
    """
    import authconn
    import threading
    from gi.repository import GLib

    np = get_dummy_gui()
    np.device = cupshelpers.Device(
        "ipp://test",
        **{
            "device-info": "driverless",
            "device-id": "MFG:Test;MDL:Printer;",
            "device-make-and-model": "Test Printer",
        }
    )
    np.device.driverless = True

    np.NewPrinterWindow = MagicMock()
    np.emit = MagicMock()

    np.cups = authconn.Connection(host='127.0.0.1', port=631, encryption=cups.HTTP_ENCRYPT_NEVER)
    np.cups._begin_operation = MagicMock()
    np.cups._end_operation = MagicMock()

    worker_blocked = threading.Event()
    cancel_completed = threading.Event()

    main_thread_id = threading.get_ident()
    worker_thread_id = [None]

    class SlowSpyConnection:
        def __init__(self, *args, **kwargs):
            pass

        def getServerPPD(self, ppdname):
            worker_thread_id[0] = threading.get_ident()
            worker_blocked.set()

            if not cancel_completed.wait(timeout=5.0):
                raise RuntimeError("Test timeout: GLib callback did not complete cancellation")

            return "/tmp/fake_ppd"

        def setClientName(self, name):
            pass

    monkeypatch.setattr(cups, "Connection", SlowSpyConnection)
    monkeypatch.setattr(cups, "PPD", MagicMock())

    def fire_cancel():
        if not worker_blocked.is_set():
            return True

        real_cancel = newprinter.NewPrinterGUI.on_NPCancel.__get__(np)
        real_cancel(None)

        cancel_completed.set()
        return False

    GLib.idle_add(fire_cancel)

    np._validateDriverlessPPD = newprinter.NewPrinterGUI._validateDriverlessPPD.__get__(np)
    real_install = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)

    real_install(None, 0, 1)

    assert worker_thread_id[0] is not None, "Worker never executed"
    assert worker_thread_id[0] != main_thread_id, "Worker executed on the main thread"
    assert np.device is None, "on_NPCancel failed to clear device state"
def test_regression_worker_timeout_races(monkeypatch):
    import authconn
    import threading
    import time
    from gi.repository import GLib

    np = get_dummy_gui()
    np.device = cupshelpers.Device(
        "ipp://test",
        **{
            "device-info": "driverless",
            "device-id": "MFG:Test;MDL:Printer;",
            "device-make-and-model": "Test Printer",
        }
    )
    np.device.driverless = True

    np.NewPrinterWindow = MagicMock()
    np.emit = MagicMock()

    np.cups = authconn.Connection(host='127.0.0.1', port=631, encryption=cups.HTTP_ENCRYPT_NEVER)
    np.cups._begin_operation = MagicMock()
    np.cups._end_operation = MagicMock()
    np.cups._cancel = False

    worker_block_event = threading.Event()
    worker_can_finish = threading.Event()
    conn_created = [0]

    class MasterSpyConnection:
        def __init__(self, *args, **kwargs):
            conn_created[0] += 1

        def getServerPPD(self, ppdname):
            if ppdname == "driverless:timeout":
                worker_block_event.set()
                worker_can_finish.wait()
                return "/tmp/fake_ppd"
            elif ppdname == "driverless:valueerror":
                raise ValueError("Intentional worker exception")
            elif ppdname == "driverless:authfail":
                raise cups.IPPError(cups.IPP_NOT_AUTHORIZED, 'auth')
            elif ppdname == "driverless:cancel":
                worker_block_event.set()
                worker_can_finish.wait()
                return "/tmp/fake_ppd"
            elif ppdname == "driverless:race":
                worker_block_event.set()
                worker_can_finish.wait()
                return "/tmp/fake_ppd"
            else:
                return "/tmp/fake_ppd"

        def setClientName(self, name):
            pass

    monkeypatch.setattr(cups, "Connection", MasterSpyConnection)
    monkeypatch.setattr(cups, "PPD", MagicMock())
    np._validateDriverlessPPD = newprinter.NewPrinterGUI._validateDriverlessPPD.__get__(np)

    original_execute = np.cups._execute_in_worker
    def execute_with_timeout(fname, *args, **kwds):
        kwds.setdefault('_timeout', 0.1)
        return original_execute(fname, *args, **kwds)
    np.cups._execute_in_worker = execute_with_timeout

    # Initialize worker by doing a normal request first
    res = np.cups._execute_in_worker('getServerPPD', 'driverless:normal', _timeout=2.0)
    assert res == "/tmp/fake_ppd"

    worker_finished = threading.Event()
    original_task_done = np.cups._worker_queue.task_done

    def mock_task_done():
        original_task_done()
        worker_finished.set()

    # Wrap the test body in try/finally to ensure background threads don't hang the suite on failure
    try:
        np.cups._worker_queue.task_done = mock_task_done



        # 2. Blocked worker & Fail-fast
        worker_block_event.clear()
        worker_can_finish.clear()
        worker_finished.clear()
        try:
            np.cups._execute_in_worker('getServerPPD', 'driverless:timeout', _timeout=0.1)
            assert False, "Should have timed out"
        except authconn.WorkerTimeoutError:
            pass

        assert worker_block_event.is_set(), "Worker should be blocked"

        try:
            np.cups._execute_in_worker('getServerPPD', 'driverless:normal')
            assert False, "Should have raised WorkerUnavailableError immediately"
        except authconn.WorkerUnavailableError as e:
            assert "unavailable or busy" in str(e)

        # Wait for IDLE deterministically
        worker_can_finish.set() # Let it recover
        worker_finished.wait(2.0)

        with np.cups._worker_lock:
            assert np.cups._worker_state == 'IDLE', "Did not recover to IDLE"

        # 3. Late result isolation (Worker finishes after timeout has already triggered)
        worker_block_event.clear()
        worker_can_finish.clear()
        worker_finished.clear()

        try:
            np.cups._execute_in_worker('getServerPPD', 'driverless:timeout', _timeout=0.1)
            assert False, "Should have timed out"
        except authconn.WorkerTimeoutError:
            pass

        # Main thread has exited timeout loop. Unblock worker.
        worker_can_finish.set()
        worker_finished.wait(2.0)

        assert np.cups._worker_state == 'IDLE', "Worker must be IDLE after late completion"

        # 4. Recovery safe
        conn_count_before = conn_created[0]
        res = np.cups._execute_in_worker('getServerPPD', 'driverless:normal', _timeout=2.0)
        assert res == "/tmp/fake_ppd"
        assert conn_created[0] > conn_count_before, "Connection must have been recreated"

        # 5. Auth retry behavior through _authloop()
        auth_called = [False]
        orig_perform_auth = np.cups._perform_authentication
        def mock_perform_auth(*args, **kwds):
            auth_called[0] = True
            np.cups._cancel = True
            np.cups._cannot_auth = False
            return -1 # Cancel further retry

        try:
            np.cups._perform_authentication = mock_perform_auth
            try:
                np.cups.run_on_worker(np.cups.getServerPPD)('driverless:authfail')
            except cups.IPPError:
                pass
        finally:
            np.cups._perform_authentication = orig_perform_auth
        assert auth_called[0], "Authloop should have triggered _perform_authentication"

        # 6. Cancellation during GLib loop
        worker_block_event.clear()
        worker_can_finish.clear()
        def fire_cancel():
            if worker_block_event.wait(0.5):
                np.on_NPCancel(None)
                worker_can_finish.set()
            return False
        GLib.idle_add(fire_cancel)

        res = np._validateDriverlessPPD('driverless:cancel')
        assert res is None, "Should discard late result due to cancellation"
        assert np.device is None
        assert np.cups._worker_state == 'IDLE'

        # 7. Unavoidable Race Window (Worker finishes while main thread is evaluating timeout)
        worker_block_event.clear()
        worker_can_finish.clear()
        worker_finished.clear()

        original_monotonic = time.monotonic
        mock_calls = [0]
        def mock_monotonic():
            mock_calls[0] += 1
            if mock_calls[0] > 1 and worker_block_event.is_set() and not worker_can_finish.is_set():
                # We have entered the poll() evaluation and the worker is blocked on the CUPS call.
                # Unblock the worker and wait for it to finish publishing the result.
                worker_can_finish.set()
                worker_finished.wait(2.0)
                # Advance the clock to guarantee the timeout condition evaluates to True.
                return original_monotonic() + 100.0
            return original_monotonic()

        monkeypatch.setattr(authconn.time, "monotonic", mock_monotonic)

        res_race = np.cups._execute_in_worker('getServerPPD', 'driverless:race', _timeout=0.1)
        assert res_race == "/tmp/fake_ppd", "Must succeed because worker finished during the poll evaluation"
        assert np.cups._worker_state == 'IDLE'

        # 8. Transient BUSY state
        res1 = np.cups._execute_in_worker('getServerPPD', 'driverless:normal', _timeout=2.0)
        assert res1 == "/tmp/fake_ppd"
        res2 = np.cups._execute_in_worker('getServerPPD', 'driverless:normal', _timeout=2.0)
        assert res2 == "/tmp/fake_ppd"

        # 9. Exception propagation
        try:
            np.cups._execute_in_worker('getServerPPD', 'driverless:valueerror', _timeout=2.0)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Intentional worker exception" in str(e)

        assert np.cups._worker_state == 'IDLE', "Worker must be IDLE after exception"

        res_after_err = np.cups._execute_in_worker('getServerPPD', 'driverless:normal', _timeout=2.0)
        assert res_after_err == "/tmp/fake_ppd"

    finally:
        worker_can_finish.set()
        worker_block_event.set()
        worker_finished.set()
        np.cups._worker_queue.task_done = original_task_done


def test_generic_worker_wrapper_api(monkeypatch):
    """Verify run_on_worker executes off the main thread, pumps GLib events, supports both
    string method names and worker-bound callables, and executes sequentially without leaks."""
    c = authconn.Connection(host='127.0.0.1', port=631, encryption=cups.HTTP_ENCRYPT_NEVER)
    main_thread = threading.current_thread()
    worker_threads = []
    glib_pumped = []

    class SpyConn:
        def __init__(self, *args, **kwargs):
            pass

        def getPPD(self, name):
            worker_threads.append(threading.current_thread())
            time.sleep(0.04)
            if name == "broken":
                raise cups.IPPError(cups.IPP_INTERNAL_ERROR, "failed")
            return f"/tmp/ppd_{name}"

    monkeypatch.setattr(authconn.cups, "Connection", SpyConn)

    # Schedule a GLib idle callback with standard priority to verify main loop pumps during worker wait
    def on_idle():
        glib_pumped.append(True)
        return False

    GLib.idle_add(on_idle, priority=GLib.PRIORITY_DEFAULT)

    # 1. String method name wrapper
    res = c.run_on_worker('getPPD')("myprinter")
    assert res == "/tmp/ppd_myprinter"
    assert len(worker_threads) == 1
    assert worker_threads[0] != main_thread
    assert len(glib_pumped) > 0, "GLib main loop must pump events while worker is executing"

    # 2. Worker-bound callable wrapper
    def custom_worker_op(conn, x, y):
        worker_threads.append(threading.current_thread())
        assert isinstance(conn, SpyConn)
        return x + y
    custom_worker_op._with_connection = True

    res2 = c.run_on_worker(custom_worker_op)(10, 20)
    assert res2 == 30
    assert len(worker_threads) == 2
    assert worker_threads[1] != main_thread

    # 3. Sequential execution immediately after previous completion
    res3 = c.run_on_worker('getPPD')("secondprinter")
    assert res3 == "/tmp/ppd_secondprinter"
    assert c._worker_state == 'IDLE'

    # 4. Exception propagation out of wrapper
    try:
        c.run_on_worker('getPPD')("broken")
        assert False, "Should have raised IPPError"
    except cups.IPPError as e:
        assert e.args[0] == cups.IPP_INTERNAL_ERROR

    assert c._worker_state == 'IDLE', "Worker must be IDLE after exception"


def test_authloop_getPPD_offloading_and_retry(monkeypatch):
    """Verify getPPD offloads through _authloop and handles authentication challenge and retry."""
    c = authconn.Connection(host='127.0.0.1', port=631, encryption=cups.HTTP_ENCRYPT_NEVER)
    c._prompt_allowed = True
    c._cancel = False

    auth_calls = [0]
    ppd_calls = []

    class SpyConn:
        def __init__(self, *args, **kwargs):
            pass

        def getPPD(self, name):
            ppd_calls.append(len(ppd_calls))
            if len(ppd_calls) == 1:
                raise cups.IPPError(cups.IPP_NOT_AUTHORIZED, "unauthorized")
            return f"/tmp/ppd_{name}"

    monkeypatch.setattr(authconn.cups, "Connection", SpyConn)

    def mock_perform_authentication():
        auth_calls[0] += 1
        c._has_failed = False
        return 1 if len(ppd_calls) < 2 else 0

    monkeypatch.setattr(c, "_perform_authentication", mock_perform_authentication)

    res = c.run_on_worker(c.getPPD)("secure_printer")
    assert res == "/tmp/ppd_secure_printer"
    assert auth_calls[0] >= 2, "Authentication callback must be invoked on challenge"
    assert len(ppd_calls) == 2, "Worker must retry operation after authentication"
    assert c._worker_state == 'IDLE'


def test_ppdsloader_background_worker_responsiveness():
    """Verify PPDsLoader processes CPU-bound PPD indexing in background thread without freezing GTK."""
    import ppdsloader
    loader = ppdsloader.PPDsLoader(device_id="MFG:Test;MDL:Printer;", device_uri="ipp://test/printer")
    mock_conn = MagicMock()

    cups_result = {
        "foomatic:HP-LaserJet.ppd": {
            "ppd-make-and-model": ["HP LaserJet"],
            "ppd-natural-language": ["en"],
            "ppd-make": ["HP"],
        },
        "driverless:ipps://TestPrinter._ipps._tcp.local/": {
            "ppd-make-and-model": ["Test Printer, driverless"],
            "ppd-natural-language": ["en"],
            "ppd-make": ["Test"],
            "ppd-device-id": ["MFG:Test;MDL:Printer;"],
        }
    }

    finished_fired = []
    glib_pumped_while_loading = []
    loop = GLib.MainLoop()

    def on_idle():
        glib_pumped_while_loading.append(True)
        return False

    GLib.idle_add(on_idle, priority=GLib.PRIORITY_DEFAULT)

    def on_finished(p):
        finished_fired.append(True)
        loop.quit()

    loader.connect("finished", on_finished)

    # Start processing via _cups_reply
    loader._cups_reply(mock_conn, cups_result)
    assert loader._processing_thread is not None, "Processing thread must be spawned"
    assert loader._processing_thread != threading.current_thread(), "PPD processing must run outside GTK main thread"

    # Run loop until finished signal fires from background worker completion
    loop.run()

    assert len(finished_fired) == 1
    assert len(glib_pumped_while_loading) > 0, "GTK main loop must pump events while PPDs are parsed"
    ppds_obj = loader.get_ppds()
    assert "foomatic:HP-LaserJet.ppd" in ppds_obj.ppds
    assert hasattr(ppds_obj, "makes") and bool(ppds_obj.makes), "Makes index must be pre-indexed on worker thread"
    assert "driverless:ipps://TestPrinter._ipps._tcp.local/" in loader.get_driverless_ppds()
    assert loader.get_ppdsmatch_result() is not None


def test_ppdsloader_destroy_cancels_emission():
    """Verify calling destroy() on PPDsLoader prevents finished signal emission."""
    import ppdsloader
    loader = ppdsloader.PPDsLoader(device_id="MFG:Test;MDL:Printer;", device_uri="ipp://test/printer")
    mock_conn = MagicMock()

    finished_fired = []
    loader.connect("finished", lambda p: finished_fired.append(True))

    loader.destroy()
    loader._cups_reply(mock_conn, {})

    if getattr(loader, '_processing_thread', None) is not None:
        loader._processing_thread.join()

    # Flush main loop
    ctx = GLib.MainContext.default()
    while ctx.pending():
        ctx.iteration(False)

    assert len(finished_fired) == 0, "Finished signal must not be emitted when destroyed"


def test_choose_driver_responsiveness_and_spinner_lifecycle():
    """Verify on_btnNPChooseDriver_clicked sets loading spinner, resets driverless flag,
    and advances tab responsively."""
    np = newprinter.NewPrinterGUI.__new__(newprinter.NewPrinterGUI)
    np.dialog_mode = 'printer'
    np.device = MagicMock()
    np.device.driverless = True
    np.exactdrivermatch = True
    np.searchedfordriverpackages = False
    spinner_states = []
    np._set_driver_ppd_loading = lambda state: spinner_states.append(state)
    np.rbtnNPFoomatic = MagicMock()
    np.on_rbtnNPFoomatic_toggled = MagicMock()
    np.ntbkNewPrinter = MagicMock()
    np.PAGE_SELECT_INSTALL_METHOD = 1
    next_tab_calls = []
    np.nextNPTab = lambda step=None: next_tab_calls.append(step)
    np.ppds = None
    np.ppdsloader = None

    np.on_btnNPChooseDriver_clicked(MagicMock())

    assert spinner_states[0] is True, "Driver loading spinner must be started immediately"
    assert np.device.driverless is False
    assert np.exactdrivermatch is False
    assert np.searchedfordriverpackages is True
    assert next_tab_calls == [0]


def test_duplicate_device_lookup_preserves_policykit_and_keeps_gtk_responsive(monkeypatch):
    """Verify _get_discovered_device_for_uri uses asyncconn (PolicyKit) when cups is authconn.Connection,
    pumps the GLib main loop while pending, limits schemes, cleans up connection, and spawns no threads."""
    import importlib
    import authconn
    import asyncconn
    scp_module = importlib.import_module("system-config-printer")

    class DummySCP:
        _get_discovered_device_for_uri = scp_module.GUI._get_discovered_device_for_uri

    gui = DummySCP()
    gui.PrintersWindow = MagicMock()
    gui.connect_server = "local"
    gui.connect_encrypt = 0
    # Simulate production authconn
    gui.cups = authconn.Connection.__new__(authconn.Connection)

    events_pumped = []
    conn_instances = []
    get_devices_calls = []

    class FakeAsyncConn:
        def __init__(self, parent=None, host=None, encryption=None):
            self.parent = parent
            self.host = host
            self.encryption = encryption
            self.destroyed = False
            conn_instances.append(self)

        def destroy(self):
            self.destroyed = True

    def fake_get_devices(conn, **kwds):
        get_devices_calls.append((conn, kwds))
        reply_handler = kwds.get("reply_handler")

        def deliver_reply():
            dev_dict = {
                "device-id": "MFG:Xerox;MDL:B235;",
                "device-info": "Xerox B235 (driverless)",
                "device-make-and-model": "Xerox B235",
            }
            fake_device = cupshelpers.Device("ipps://Xerox%20B235._ipps._tcp.local", **dev_dict)
            reply_handler(conn, {fake_device.uri: fake_device})
            return False

        def on_idle():
            events_pumped.append("idle_ran")
            GLib.idle_add(deliver_reply)
            return False

        GLib.idle_add(on_idle)

    monkeypatch.setattr(asyncconn, "Connection", FakeAsyncConn)
    monkeypatch.setattr(cupshelpers, "getDevices", fake_get_devices)

    thread_count_before = threading.active_count()
    device = gui._get_discovered_device_for_uri("ipps://Xerox%20B235._ipps._tcp.local")
    thread_count_after = threading.active_count()

    assert thread_count_after == thread_count_before, "No extra threads must be created"
    assert len(events_pumped) > 0, "GLib main loop must actively pump events while device lookup is pending"
    assert device is not None
    assert device.uri == "ipps://Xerox%20B235._ipps._tcp.local"
    assert device.id_dict["MFG"] == "Xerox"
    assert len(conn_instances) == 1
    assert conn_instances[0].parent is gui.PrintersWindow
    assert conn_instances[0].host == "local"
    assert conn_instances[0].destroyed is True, "Connection must be destroyed after lookup"

    conn_arg, kwds_arg = get_devices_calls[0]
    assert "include_schemes" in kwds_arg
    assert "ipps" in kwds_arg["include_schemes"]
    assert "dnssd" in kwds_arg["include_schemes"]


def test_duplicate_device_lookup_error_and_timeout_resilience(monkeypatch):
    """Verify _get_discovered_device_for_uri exits cleanly on timeout or D-Bus error without freezing or raising."""
    import importlib
    import authconn
    import asyncconn
    scp_module = importlib.import_module("system-config-printer")

    class DummySCP:
        _get_discovered_device_for_uri = scp_module.GUI._get_discovered_device_for_uri

    gui = DummySCP()
    gui.PrintersWindow = MagicMock()
    gui.connect_server = None
    gui.connect_encrypt = None
    gui.cups = authconn.Connection.__new__(authconn.Connection)

    # 1. Error callback path
    class ErrorAsyncConn:
        def __init__(self, *a, **k):
            self.destroyed = False

        def destroy(self):
            self.destroyed = True

    def error_get_devices(conn, **kwds):
        err_handler = kwds.get("error_handler")
        GLib.idle_add(lambda: err_handler(conn, RuntimeError("PolicyKit error")) and False)

    monkeypatch.setattr(asyncconn, "Connection", ErrorAsyncConn)
    monkeypatch.setattr(cupshelpers, "getDevices", error_get_devices)

    res_err = gui._get_discovered_device_for_uri("ipp://test/printer")
    assert res_err is None, "Must return None on discovery error"

    # 2. Timeout path & late reply isolation
    captured_reply_handler = [None]
    class TimeoutAsyncConn:
        def __init__(self, *a, **k):
            self.destroyed = False

        def destroy(self):
            self.destroyed = True

    def timeout_get_devices(conn, **kwds):
        captured_reply_handler[0] = kwds.get("reply_handler")

    monkeypatch.setattr(asyncconn, "Connection", TimeoutAsyncConn)
    monkeypatch.setattr(cupshelpers, "getDevices", timeout_get_devices)
    orig_timeout_add = GLib.timeout_add
    def fast_timeout_add(interval, callback):
        return orig_timeout_add(10, callback)
    monkeypatch.setattr(GLib, "timeout_add", fast_timeout_add)

    res_timeout = gui._get_discovered_device_for_uri("ipp://test/printer")
    assert res_timeout is None, "Must return None on discovery timeout"

    # 3. Late reply after timeout does not raise or corrupt state
    if captured_reply_handler[0]:
        fake_dev = cupshelpers.Device("ipp://test/printer")
        # Invoking late reply handler on destroyed/abandoned connection must be safe
        captured_reply_handler[0](TimeoutAsyncConn(), {fake_dev.uri: fake_dev})


def test_duplicate_printer_loading_ui_responsiveness(monkeypatch):
    import importlib
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, GLib

    scp_module = importlib.import_module("system-config-printer")

    gui = scp_module.GUI.__new__(scp_module.GUI)
    gui.PrintersWindow = Gtk.Window()
    gui.dests_iconview = MagicMock()
    gui.printers = {}
    gui._duplicating = False
    gui.desensitise_new_printer_widgets = MagicMock()
    gui.sensitise_new_printer_widgets = MagicMock()
    gui.monitor = MagicMock()
    gui.newPrinterGUI = MagicMock()
    gui.connect_server = None
    gui.connect_encrypt = None

    gui.cups = MagicMock()

    # Set up selected item
    gui.dests_iconview.get_selected_items.return_value = ["path"]
    model_mock = MagicMock()
    model_mock.get_value.return_value = "TestPrinter"
    gui.dests_iconview.get_model.return_value = model_mock

    printer_mock = MagicMock()
    printer_mock.is_class = False
    printer_mock.device_uri = "test://uri"
    gui.printers["TestPrinter"] = printer_mock

    # We will track dialog visibility by patching Gtk.Dialog.show_all and destroy
    dialog_state = {"visible": False, "created": False}
    original_show_all = Gtk.Dialog.show_all
    original_destroy = Gtk.Dialog.destroy

    def mock_show_all(self):
        dialog_state["visible"] = True
        dialog_state["created"] = True
        original_show_all(self)

    def mock_destroy(self):
        dialog_state["visible"] = False
        original_destroy(self)

    monkeypatch.setattr(Gtk.Dialog, "show_all", mock_show_all)
    monkeypatch.setattr(Gtk.Dialog, "destroy", mock_destroy)

    events_pumped = []

    def fake_getPPD(name):
        assert dialog_state["visible"], "Loading dialog must be visible during retrieval"

        # simulate user repeatedly clicking duplicate
        gui.on_duplicate_activate()
        assert gui.cups.getPPD.call_count == 1, "Repeated click should not launch concurrent operation"

        def on_idle():
            events_pumped.append("idle_ran")
            loop.quit()
            return False

        loop = GLib.MainLoop()
        GLib.idle_add(on_idle)
        loop.run()

        return "fake_ppd.ppd"

    gui.cups.getPPD = MagicMock(side_effect=fake_getPPD)

    gui._get_discovered_device_for_uri = MagicMock(return_value=None)

    gui.on_duplicate_activate()

    assert "idle_ran" in events_pumped, "GLib events were not processed"
    assert not dialog_state["visible"], "Dialog was not cleaned up on success"
    assert not gui._duplicating, "Duplicating flag was not reset on success"

    # Now test error path
    gui.cups.getPPD = MagicMock(side_effect=RuntimeError("timeout"))
    dialog_state["visible"] = False
    dialog_state["created"] = False
    gui.on_duplicate_activate()

    assert not dialog_state["visible"], "Dialog was not cleaned up on error"
    assert not gui._duplicating, "Duplicating flag was not reset on error"
def test_duplicate_choose_different_driver_preserves_uri():
    """Verify that in duplicate mode, getDeviceURI returns the original device URI, and does not parse unvisited UI widgets."""
    np = get_dummy_gui()
    np.getDeviceURI = newprinter.NewPrinterGUI.getDeviceURI.__get__(np)
    np.dialog_mode = "duplicate"
    np.duplicate_driver_selection = True

    np.device = MagicMock()
    np.device.uri = "socket://192.168.1.50"
    np.device.type = "socket"

    uri = np.getDeviceURI()
    assert uri == "socket://192.168.1.50", "getDeviceURI must preserve the device URI in duplicate driver selection."


def test_duplicate_driver_selection_fallback_to_orig_ppd():
    """Verify that if the device is not discovered on the network, duplicate mode falls back to matching the original PPD's Make/Model."""
    np = get_dummy_gui()
    np._installPrinterFromDeviceID = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    np.dialog_mode = "duplicate"
    np.duplicate_driver_selection = True

    np.device = MagicMock()
    np.device.id = ""
    np.device.make_and_model = ""
    np.device.driverless = False
    np.devid = ""
    np.device._driverless_failed = False

    np.orig_ppd = MockCupsPPD({"NickName": "Original Make Model Printer"})

    np.ppds = MagicMock()
    np.ppds.getInfoFromModel.return_value = {"original-driver": {"ppd-make-and-model": "Original Make Model Printer"}}

    np._installPrinterOrSearchForDriver = MagicMock(return_value=True)

    newprinter.nonfatalException = lambda *args: None

    np._installPrinterFromDeviceID("", 2, 1)

    np._installPrinterOrSearchForDriver.assert_called_with("", "original-driver", "exact", 2, 1)


def test_duplicate_printer_driverless_ppd_selection_fallback():
    import os
    os.environ["SYSTEM_CONFIG_PRINTER_UI"] = "ui"
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, GLib
    import newprinter
    import cupshelpers

    gui = newprinter.NewPrinterGUI()
    gui.printers = {}
    gui.cups = MagicMock()

    class FakePPD:
        def findAttr(self, name):
            class Attr:
                pass
            a = Attr()
            if name == "1284DeviceID":
                a.value = "MFG:Xerox;MDL:B235;"
                return a
            elif name == "ModelName":
                a.value = "Xerox B235"
                return a
            elif name == "NickName":
                a.value = "Xerox B235, driverless, cups-filters 1.28.15"
                return a
            return None

    orig_ppd = FakePPD()

    gui.init("duplicate", device_uri="socket://192.168.1.100", name="Xerox", ppd=orig_ppd, discovered_device=None)

    assert gui.device.id == "MFG:Xerox;MDL:B235;"
    assert gui.device.make_and_model == "Xerox B235"
    assert gui.device.driverless is True

    gui.on_btnNPChooseDriver_clicked(None)
    assert gui.device.driverless is True


def test_driverless_validation_does_not_pass_duplicate_spinner(monkeypatch):
    """Verify driverless PPD validation runs on worker without passing a duplicate spinner,
    preserving the 'Searching for drivers' UI spinner as the sole progress indicator."""
    np = get_dummy_gui()
    np.device = cupshelpers.Device(
        "ipp://test-printer.local",
        **{
            "device-info": "Xerox Test Printer",
            "device-id": "MFG:Xerox;MDL:B235;",
            "device-make-and-model": "Xerox B235",
        }
    )
    np.device.driverless = True
    np.spinner = MagicMock(name="bottom_left_spinner")
    np.cups = authconn.Connection(host='127.0.0.1', port=631, encryption=cups.HTTP_ENCRYPT_NEVER)
    np.cups._begin_operation = MagicMock()
    np.cups._end_operation = MagicMock()

    captured_worker_calls = []

    def spy_run_on_worker(op, **kwargs):
        captured_worker_calls.append({
            "op": op,
            "spinner": kwargs.get("spinner", None),
            "feedback": kwargs.get("feedback", None),
        })
        def fake_worker_call(ppdname):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".ppd") as tmp:
                tmp.write(b"*PPD-Adobe: \"4.3\"\n")
                return tmp.name
        return fake_worker_call

    np.cups.run_on_worker = spy_run_on_worker
    monkeypatch.setattr(cups, "PPD", MagicMock())

    real_validate = newprinter.NewPrinterGUI._validateDriverlessPPD.__get__(np)
    result = real_validate("driverless:ipp://test-printer.local")

    assert len(captured_worker_calls) == 1, "Validation must run through run_on_worker"
    call_info = captured_worker_calls[0]
    assert call_info["op"] == np.cups.getServerPPD
    assert call_info["spinner"] is None, "Must NOT pass self.spinner to run_on_worker to prevent duplicate spinner"
    assert call_info["feedback"] is None, "Must NOT pass feedback to run_on_worker"
    assert np.spinner.show.call_count == 0, "Bottom-left spinner must not be shown"
    assert np.spinner.start.call_count == 0, "Bottom-left spinner must not be started"


def test_multiprotocol_device_grouped_in_ui_and_connection_selection():
    """Verify that when a physical printer is discovered via multiple protocols
    (e.g. IPPS and LPD), it appears only ONCE in the device list and that
    the Connections view allows switching between connection methods."""
    import os
    os.environ["SYSTEM_CONFIG_PRINTER_UI"] = "ui"
    from unittest.mock import MagicMock
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
    import newprinter
    import cupshelpers

    gui = newprinter.NewPrinterGUI()
    gui.start_fetching_devices = MagicMock()
    gui.fillDeviceTab()

    dev1 = cupshelpers.Device(
        'ipps://Broken%20Xerox%20B235%20MFP._ipps._tcp.local/',
        **{'device-class': 'network',
           'device-info': 'Broken Xerox B235 MFP',
           'device-make-and-model': 'Broken Xerox B235 MFP',
           'device-id': 'MFG:Broken Xerox;MDL:B235 MFP;CMD:PCLM,AppleRaster,URF,PWGRaster,PWG,JPEG,PS,TEXT;'})

    dev2 = cupshelpers.Device(
        'lpd://Broken%20Xerox%20B235%20MFP._printer._tcp.local/',
        **{'device-class': 'network',
           'device-info': 'Broken Xerox B235 MFP',
           'device-make-and-model': 'Xerox(R) B235 MFP',
           'device-id': 'MFG:Broken Xerox;MDL:B235 MFP;CMD:PS;'})

    devices_dict = {dev1.uri: dev1, dev2.uri: dev2}
    gui.add_devices(devices_dict, None, no_more=True)

    model = gui.tvNPDevices.get_model()
    matched_rows = []
    def scan(it):
        while it:
            pd = model.get_value(it, 1)
            if pd and pd.devices and any('Broken' in d.uri for d in pd.devices):
                matched_rows.append((model.get_path(it), pd))
            child = model.iter_children(it)
            if child:
                scan(child)
            it = model.iter_next(it)

    scan(model.get_iter_first())
    assert len(matched_rows) == 1, f"Expected 1 physical printer row, got {len(matched_rows)}"
    path, phys = matched_rows[0]
    assert len(phys.get_devices()) == 2

    row_label = model.get_value(model.get_iter(path), 0)
    assert row_label == 'Broken Xerox B235 MFP'
    assert '.local' not in row_label

    if path.get_depth() > 1:
        p = path.copy()
        p.up()
        gui.tvNPDevices.expand_row(p, False)

    gui.tvNPDevices.set_cursor(path)
    gui.on_tvNPDevices_cursor_changed(gui.tvNPDevices)

    uris_model = gui.tvNPDeviceURIs.get_model()
    assert len(uris_model) == 2, f"Expected 2 connections, got {len(uris_model)}"

    conn_labels = [uris_model[i][0] for i in range(len(uris_model))]
    assert 'LPD/LPR (queue "")' in conn_labels

    gui.tvNPDeviceURIs.set_cursor(Gtk.TreePath.new_from_indices([0]))
    gui.on_tvNPDeviceURIs_cursor_changed(gui.tvNPDeviceURIs)
    assert gui.device.uri == dev1.uri

    gui.tvNPDeviceURIs.set_cursor(Gtk.TreePath.new_from_indices([1]))
    gui.on_tvNPDeviceURIs_cursor_changed(gui.tvNPDeviceURIs)
    assert gui.device.uri == dev2.uri


def test_lpd_queue_formatting():
    """Verify LPD queue formatting in connections view:
    Empty queue should display as 'LPD/LPR (queue "")',
    and named queue should display as 'LPD/LPR (queue <name>)'."""
    import os
    os.environ["SYSTEM_CONFIG_PRINTER_UI"] = "ui"
    from unittest.mock import MagicMock
    import newprinter
    import cupshelpers
    from PhysicalDevice import PhysicalDevice

    gui = newprinter.NewPrinterGUI()
    gui.start_fetching_devices = MagicMock()
    gui.fillDeviceTab()

    dev_empty = cupshelpers.Device(
        'lpd://printer.example.com/',
        **{'device-class': 'network',
           'device-make-and-model': 'Test Printer',
           'device-id': 'MFG:Test;MDL:Printer;'})
    phys_empty = PhysicalDevice(dev_empty)
    model = gui.tvNPDevices.get_model()
    path = model.append(None, [phys_empty.get_info(), phys_empty, False])
    gui.tvNPDevices.set_cursor(model.get_path(path))
    gui.on_tvNPDevices_cursor_changed(gui.tvNPDevices)
    uris_model = gui.tvNPDeviceURIs.get_model()
    assert uris_model[0][0] == 'LPD/LPR (queue "")'

    dev_named = cupshelpers.Device(
        'lpd://printer.example.com/print',
        **{'device-class': 'network',
           'device-make-and-model': 'Test Printer 2',
           'device-id': 'MFG:Test;MDL:Printer 2;'})
    phys_named = PhysicalDevice(dev_named)
    path2 = model.append(None, [phys_named.get_info(), phys_named, False])
    gui.tvNPDevices.set_cursor(model.get_path(path2))
    gui.on_tvNPDevices_cursor_changed(gui.tvNPDevices)
    uris_model = gui.tvNPDeviceURIs.get_model()
    assert uris_model[0][0] == 'LPD/LPR (queue print)'


def _setup_make_list_gui(device_kwargs, auto_make, makes=None):
    gui = newprinter.NewPrinterGUI.__new__(newprinter.NewPrinterGUI)
    if device_kwargs is not None:
        gui.device = cupshelpers.Device('lpd://192.168.1.50/queue', **device_kwargs)
    else:
        gui.device = None
    gui.auto_make = auto_make
    gui.auto_model = ""
    gui.auto_driver = None
    gui.ppds = MagicMock()
    if makes is None:
        makes = ["Generic", "Alps", "Brother", "Canon", "Epson", "HP"]
    gui.ppds.getMakes.return_value = makes
    makes_model = Gtk.ListStore(str, str)
    gui.tvNPMakes = MagicMock()
    gui.tvNPMakes.get_model.return_value = makes_model
    gui.entNPDownloadableDriverSearch = MagicMock()
    return gui, makes_model


def test_fill_make_list_detected_make_preselected():
    """Case 1: Detected make: Canon MF645C, auto_make '' -> Canon selected and scrolled."""
    dev = {"device-class": "network", "device-make-and-model": "Canon MF645C", "device-id": "MFG:Canon;MDL:MF645C;"}
    gui, model = _setup_make_list_gui(dev, "")
    gui.fillMakeList()

    cursor_path = gui.tvNPMakes.set_cursor.call_args[0][0]
    idx = cursor_path.get_indices()[0]
    assert model[idx][1] == "Canon"
    gui.tvNPMakes.scroll_to_cell.assert_called_with(cursor_path, None, True, 0.5, 0.5)


def test_fill_make_list_generic_recommended_selects_detected_make():
    """Case 2: Generic-recommended: Canon MF645C, auto_make 'Generic' -> Canon selected."""
    dev = {"device-class": "network", "device-make-and-model": "Canon MF645C", "device-id": "MFG:Canon;MDL:MF645C;"}
    gui, model = _setup_make_list_gui(dev, "Generic")
    gui.fillMakeList()

    cursor_path = gui.tvNPMakes.set_cursor.call_args[0][0]
    idx = cursor_path.get_indices()[0]
    assert model[idx][1] == "Canon"
    gui.tvNPMakes.scroll_to_cell.assert_called_with(cursor_path, None, True, 0.5, 0.5)


def test_fill_make_list_unavailable_make_keeps_generic():
    """Case 3: Unavailable: empty or Unknown make -> first row (Generic) unchanged."""
    dev = {"device-class": "network", "device-make-and-model": "Unknown", "device-id": ""}
    gui, model = _setup_make_list_gui(dev, "")
    gui.fillMakeList()

    cursor_path = gui.tvNPMakes.set_cursor.call_args[0][0]
    assert not cursor_path.get_indices() or cursor_path.get_indices() == [0]
    gui.tvNPMakes.scroll_to_cell.assert_called_with(0, None, True, 0.0, 0.0)


def test_fill_make_list_not_in_list_keeps_generic():
    """Case 4: Not in list: CustomBrand 1000 -> first row (Generic) unchanged."""
    dev = {"device-class": "network", "device-make-and-model": "CustomBrand 1000", "device-id": "MFG:CustomBrand;MDL:1000;"}
    gui, model = _setup_make_list_gui(dev, "")
    gui.fillMakeList()

    cursor_path = gui.tvNPMakes.set_cursor.call_args[0][0]
    assert not cursor_path.get_indices() or cursor_path.get_indices() == [0]
    gui.tvNPMakes.scroll_to_cell.assert_called_with(0, None, True, 0.0, 0.0)


def test_fill_make_list_case_normalization():
    """Case 5: Normalization: CANON MF645C -> Canon selected."""
    dev = {"device-class": "network", "device-make-and-model": "CANON MF645C", "device-id": "MFG:CANON;MDL:MF645C;"}
    gui, model = _setup_make_list_gui(dev, "")
    gui.fillMakeList()

    cursor_path = gui.tvNPMakes.set_cursor.call_args[0][0]
    idx = cursor_path.get_indices()[0]
    assert model[idx][1] == "Canon"
    gui.tvNPMakes.scroll_to_cell.assert_called_with(cursor_path, None, True, 0.5, 0.5)


def test_fill_make_list_longest_prefix_match():
    """Longest prefix: Hewlett-Packard HP LaserJet with makes containing HP and Hewlett-Packard -> Hewlett-Packard selected."""
    dev = {"device-class": "network", "device-make-and-model": "Hewlett-Packard HP LaserJet 4000", "device-id": ""}
    gui, model = _setup_make_list_gui(
        dev, "",
        makes=["Generic", "Brother", "Canon", "HP", "Hewlett-Packard", "Xerox"]
    )
    gui.fillMakeList()

    cursor_path = gui.tvNPMakes.set_cursor.call_args[0][0]
    idx = cursor_path.get_indices()[0]
    assert model[idx][1] == "Hewlett-Packard"
    gui.tvNPMakes.scroll_to_cell.assert_called_with(cursor_path, None, True, 0.5, 0.5)


def test_fill_make_list_prefix_match_no_mfg_needed():
    """Xerox(R) B235 MFP with no device-id/MFG -> Xerox selected by prefix."""
    dev = {"device-class": "network",
           "device-make-and-model": "Xerox(R) B235 MFP",
           "device-id": ""}
    gui, model = _setup_make_list_gui(
        dev, "",
        makes=["Generic", "Alps", "Brother", "Canon", "Epson", "HP", "Xerox"]
    )
    gui.fillMakeList()

    cursor_path = gui.tvNPMakes.set_cursor.call_args[0][0]
    idx = cursor_path.get_indices()[0]
    assert model[idx][1] == "Xerox"
    gui.tvNPMakes.scroll_to_cell.assert_called_with(cursor_path, None, True, 0.5, 0.5)


def test_fill_make_list_properties_change_driverless_xerox_simulation():
    """Properties -> Change Make and Model with simulated Xerox driverless printer -> Xerox selected."""
    dev = {"device-class": "network",
           "device-make-and-model": "Xerox B235 MFP, driverless, cups-filters 1.28.17",
           "device-id": ""}
    gui, model = _setup_make_list_gui(
        dev, "Generic",
        makes=["Generic", "Alps", "Brother", "Canon", "Epson", "HP", "Xerox"]
    )
    gui.fillMakeList()

    cursor_path = gui.tvNPMakes.set_cursor.call_args[0][0]
    idx = cursor_path.get_indices()[0]
    assert model[idx][1] == "Xerox"
    gui.tvNPMakes.scroll_to_cell.assert_called_with(cursor_path, None, True, 0.5, 0.5)


def test_fill_make_list_real_recommended_make_preserved_when_no_prefix_match():
    """A valid real auto_make remains selected when there is no matching make-and-model prefix."""
    dev = {"device-class": "network", "device-make-and-model": "CustomBrand 1000", "device-id": ""}
    gui, model = _setup_make_list_gui(dev, "Brother")
    gui.fillMakeList()

    cursor_path = gui.tvNPMakes.set_cursor.call_args[0][0]
    idx = cursor_path.get_indices()[0]
    assert model[idx][1] == "Brother"
    gui.tvNPMakes.scroll_to_cell.assert_called_with(cursor_path, None, True, 0.5, 0.5)


def test_fill_make_list_fallback_to_auto_make_when_no_make_and_model():
    """When device has no make_and_model, fallback to valid auto_make (e.g. Brother)."""
    gui, model = _setup_make_list_gui(None, "Brother")
    gui.fillMakeList()

    cursor_path = gui.tvNPMakes.set_cursor.call_args[0][0]
    idx = cursor_path.get_indices()[0]
    assert model[idx][1] == "Brother"
    gui.tvNPMakes.scroll_to_cell.assert_called_with(cursor_path, None, True, 0.5, 0.5)


def test_fill_make_list_auto_make_not_in_list_no_detected_make_keeps_generic():
    """4. auto_make not in list and no detected make -> Generic."""
    dev = {"device-class": "network",
           "device-make-and-model": "Unknown",
           "device-id": ""}
    gui, model = _setup_make_list_gui(dev, "CustomBrand")
    gui.fillMakeList()

    cursor_path = gui.tvNPMakes.set_cursor.call_args[0][0]
    assert not cursor_path.get_indices() or cursor_path.get_indices() == [0]
    gui.tvNPMakes.scroll_to_cell.assert_called_with(0, None, True, 0.0, 0.0)


def test_fit_none_fallback_uses_detected_xerox_make():
    """A non-matching HP fallback must not override detected Xerox."""
    np = get_dummy_gui()
    np.device = cupshelpers.Device(
        "lpd://192.168.1.50/queue",
        **{"device-class": "network",
           "device-make-and-model": "Xerox B235",
           "device-id": "MFG:Xerox;MDL:B235;"}
    )
    np.device.driverless = False
    np.ppds = MagicMock()
    np.ppds.FIT_NONE = "none"
    np.ppds.getInfoFromPPDName.return_value = {
        "ppd-make-and-model": ["HP LaserJet Postscript"]
    }
    np.fillDriverList = MagicMock()
    np.fillMakeList = MagicMock()

    real_search = newprinter.NewPrinterGUI._installPrinterOrSearchForDriver.__get__(np)
    real_search(np.device.id, "postscript-hp:0/ppd/hp.ppd", "none", 0, 1)

    assert np.auto_make == "Xerox"
    assert np.auto_driver is None



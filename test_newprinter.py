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
from gi.repository import Gtk
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
    np.device.driverless = True
    np.exactdrivermatch = True
    np.ppds = MagicMock()
    np.ntbkNewPrinter = MagicMock()
    np.rbtnNPFoomatic = MagicMock()
    np.on_rbtnNPFoomatic_toggled = MagicMock()
    np.nextNPTab = MagicMock()
    np._loadPPDsForDevice = MagicMock()

    newprinter.NewPrinterGUI.on_btnNPChooseDriver_clicked(np, None)

    assert np.device.driverless is False
    assert np.exactdrivermatch is False
    assert np.searchedfordriverpackages is True
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
    """Requirement 6-D: Xerox B235 IPP device does not match hp-designjet_t920-postscript.ppd,
    but recommends its driverless PPD."""
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
    """Verify that driverless PPD entries in fillDriverList display the actual model name
    from CUPS and explicitly indicate driverless status (recommended, Current, or plain driverless),
    while preserving normal legacy driver display formatting."""
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

    # Legacy driver formatting check
    np.id_matched_ppdnames = [legacy_rec]
    model.clear()
    real_fill("Generic", "PostScript")
    rows_legacy = [r[0] for r in model]
    assert rows_legacy[0] == "Generic PostScript Printer [en] (recommended)"

    # Current driverless formatting check
    np.device.make_and_model = None
    np.auto_driver = driverless_rec
    model.clear()
    real_fill("Xerox(R)", "B235 MFP")
    rows_current = [r[0] for r in model]
    assert rows_current[0] == "Xerox(R) B235 MFP, driverless, cups-filters 2.0.0 (driverless, Current)"


def test_choose_different_driver_recommends_validated_driverless_printer():
    """Verify that when a driverless printer's PPD is validated and its CUPS
    metadata preserved, selecting 'Choose a different driver' recommends the
    actual printer make and model (with driverless formatting) rather than Generic,
    and that an unvalidated driverless PPD is discarded."""
    import ppdsloader
    mock_conn = MagicMock()
    loader = ppdsloader.PPDsLoader()

    working_uri = "ipp://Xerox-B235.local/"
    working_ppdname = f"driverless:{working_uri}"
    working_cups_entry = {
        "ppd-make": ["Xerox"],
        "ppd-make-and-model": ["Xerox(R) B235 MFP, driverless, cups-filters 2.0.0"],
        "ppd-device-id": ["MFG:Xerox;MDL:B235 MFP;CMD:PCLM,POSTSCRIPT;"],
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

    # Gtk TreeView mock models
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

    # Step 1: Loader reply segregates driverless PPDs
    np._getPPDs_reply(loader)
    assert working_ppdname not in np.ppds.ppds
    assert broken_ppdname not in np.ppds.ppds
    assert "foomatic:Generic-PostScript.ppd" in np.ppds.ppds

    # Mock validation: working succeeds, broken fails
    mock_ppd = MagicMock(spec=cups.PPD)
    np._validateDriverlessPPD = MagicMock(side_effect=lambda name: mock_ppd if name == working_ppdname else None)

    # Step 2: Forward on working printer adds preserved CUPS metadata
    install_func = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    install_func(np.device.id, newprinter.NewPrinterGUI.PAGE_SELECT_DEVICE, 1)

    assert working_ppdname in np.ppds.ppds
    assert np.ppds.ppds[working_ppdname] == working_cups_entry
    assert np.auto_driver == working_ppdname
    assert np.auto_make in ("Xerox", "Xerox(R)")

    # Step 3: Choose a different driver
    choose_driver_func = newprinter.NewPrinterGUI.on_btnNPChooseDriver_clicked.__get__(np)
    np.nextNPTab = MagicMock()
    choose_driver_func(None)

    assert np.device.driverless is False
    np.id_matched_ppdnames = []
    install_func(np.device.id, newprinter.NewPrinterGUI.PAGE_SELECT_INSTALL_METHOD, 0)

    assert np.auto_driver == working_ppdname
    assert np.auto_make in ("Xerox", "Xerox(R)")
    assert np.auto_model == "B235 MFP"

    # Fill make list
    np.fillMakeList()
    makes_rows = [r[0] for r in makes_model]
    assert any("Xerox" in r and "(recommended)" in r for r in makes_rows)
    assert not any("Generic" in r and "(recommended)" in r for r in makes_rows)

    # Select recommended make and fill model list
    np.NPMake = np.auto_make
    np.recommended_make_selected = True
    np.fillModelList()

    models_rows = [r[0] for r in np.models_liststore]
    assert any("B235 MFP (recommended)" in r for r in models_rows)

    # Fill driver list
    np.recommended_model_selected = True
    np.fillDriverList(np.NPMake, np.auto_model)
    driver_rows = [r[0] for r in drivers_model]

    assert driver_rows[0] == "Xerox(R) B235 MFP, driverless, cups-filters 2.0.0 (driverless, recommended)"
    assert not any("Generic" in r and "(recommended)" in r for r in driver_rows)

    # Step 4: Verify broken simulator scenario
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

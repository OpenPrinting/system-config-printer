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
    """USB/ipp-usb broken driverless still enters existing fallback."""
    np = get_dummy_gui()
    np.device.driverless = True
    np.device.uri = "ipp://localhost:60000/ipp/print"
    np._validateDriverlessPPD = MagicMock(return_value=None)
    np._loadPPDsForDevice = MagicMock()

    real_install = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    result = real_install(None, 0, 0)

    assert result == newprinter.NewPrinterGUI.INSTALL_RESULT_OPS_PENDING
    assert np.device.driverless is False
    assert np.device._driverless_failed is True
    assert np.searchedfordriverpackages is True
    np._loadPPDsForDevice.assert_called_once_with(None, "ipp://localhost:60000/ipp/print")

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
    """When driverless PPD validation fails, flags are set immediately and PPDs are loaded with devid=None to skip PackageKit."""
    np = get_dummy_gui()
    np.device.driverless = True
    np.device.uri = "dnssd://Xerox%20B235._ipp._tcp.local/"
    np.device.id = "MFG:Xerox;MDL:B235;"
    np.searchedfordriverpackages = False
    np._validateDriverlessPPD = MagicMock(return_value=None)
    np._loadPPDsForDevice = MagicMock()

    real_install = newprinter.NewPrinterGUI._installPrinterFromDeviceID.__get__(np)
    result = real_install(np.device.id, 0, 0)

    assert result == newprinter.NewPrinterGUI.INSTALL_RESULT_OPS_PENDING
    assert np.device.driverless is False
    assert np.device._driverless_failed is True
    assert np.searchedfordriverpackages is True
    np._loadPPDsForDevice.assert_called_once_with(None, "dnssd://Xerox%20B235._ipp._tcp.local/")


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

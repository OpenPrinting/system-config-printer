"""Apply double-activation guard tests: real GTK dialog, stubbed CUPS.

These tests prove the entry guard in on_btnNPApply_clicked, not a physical
double click: activation is delivered with emit("clicked") on the real
button, which bypasses button sensitivity by design. That is exactly what
the guard is for -- it must reject an activation that arrives while a
blocking operation is in flight even if the button was re-enabled by a
refresh that does not check for an operation in flight. Synthesized
pointer clicks (Gtk.test_widget_click) cannot prove more than this here:
on Broadway they are silently dropped even for a realized, mapped button,
and on an unrealized button they segfault.
"""
from unittest.mock import MagicMock

import gi
import pytest

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

import newprinter
from test_discovery_ui import device, select


@pytest.fixture
def ui(monkeypatch):
    monkeypatch.setattr(newprinter.PhysicalDevice, "_get_address", lambda self, host: None)
    gui = newprinter.NewPrinterGUI()
    gui.start_fetching_devices = MagicMock()
    gui.check_firewall = MagicMock()
    connection = MagicMock()
    connection.adminGetServerSettings.return_value = {}
    monkeypatch.setattr(newprinter.authconn, "Connection", lambda **kwargs: connection)
    monkeypatch.setattr(newprinter.cupshelpers, "getPrinters", lambda *args: {})
    assert gui.init("printer", host="localhost")
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    yield gui
    for window in Gtk.Window.list_toplevels():
        window.destroy()


def prepare_describe(ui):
    printer = device("ipp://192.0.2.10/ipp/print")
    ui.add_devices({printer.uri: printer}, None, no_more=True)
    select(ui, printer.uri)
    ui._set_discovery_status(searching=False)
    ui.on_search_again_clicked(ui.btnSearchAgain)
    ui._select_notebook_page(ui.ntbkNewPrinter, ui.PAGE_DESCRIBE_PRINTER)
    ui.ppd = "fixture.ppd"
    ui.options = {}
    ui.entNPName.set_text("fixture")
    ui.setNPButtons()
    assert ui.btnNPApply.get_visible()
    assert ui.btnNPApply.get_sensitive()
    return printer


def test_apply_rejected_while_blocking_operation_in_flight(ui, monkeypatch):
    prepare_describe(ui)
    fetch_conn = MagicMock()
    ui.fetchDevices_conn = fetch_conn
    # The fixture replaces authconn.Connection with a lambda, which makes
    # _run_blocking raise TypeError on isinstance; use the real class shape
    # (as the allow-path test does) so the no-guard path can reach addPrinter.
    monkeypatch.setattr(newprinter.authconn, "Connection", type(ui.cups))

    def run_on_worker(op):
        def deliver(*args, **kwargs):
            kwargs.pop("_timeout", None)
            return op(*args, **kwargs)
        return deliver

    ui.cups.run_on_worker.side_effect = run_on_worker
    ui._blocking_operation_in_flight = True
    ui.btnNPApply.emit("clicked")
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    assert ui.cups.addPrinter.call_count == 0
    # The guard returns before the handler touches any state.
    assert ui.fetchDevices_conn is fetch_conn
    fetch_conn.destroy.assert_not_called()
    assert ui.device is not None
    assert ui.ppd == "fixture.ppd"
    assert ui.NewPrinterWindow.get_visible()


def test_apply_allowed_when_not_in_flight(ui, monkeypatch):
    prepare_describe(ui)
    monkeypatch.setattr(newprinter.cupshelpers, "activateNewPrinter", MagicMock())
    monkeypatch.setattr(newprinter.authconn, "Connection", type(ui.cups))

    def run_on_worker(op):
        def deliver(*args, **kwargs):
            kwargs.pop("_timeout", None)
            return op(*args, **kwargs)
        return deliver

    ui.cups.run_on_worker.side_effect = run_on_worker
    ui.btnNPApply.emit("clicked")
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    assert ui.cups.addPrinter.call_count == 1
    assert not ui.NewPrinterWindow.get_visible()
    assert ui.device is None

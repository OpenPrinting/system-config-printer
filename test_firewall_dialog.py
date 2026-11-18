"""Probe/regression: firewall reply must not interrupt a blocking operation.

Bug: a delayed on_firewall_read landing while _run_blocking pumps the
nested MainLoop opens a modal "Adjust Firewall" dialog mid-validation, and
adjust_firewall_response then fires fetchDevices(network=True) unconditionally.
"""
from unittest.mock import MagicMock

import gi
import pytest

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

import newprinter


class FakeFirewall:
    running = True

    def __init__(self):
        self.write = MagicMock()
        self.add_service = MagicMock()

    def read(self, reply_handler, error_handler):
        self.reply_handler = reply_handler
        self.error_handler = error_handler

    def deliver_reply(self):
        self.reply_handler(None)

    def check_mdns_allowed(self):
        return False


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
    gui.ntbkNewPrinter.set_current_page(gui.PAGE_SELECT_DEVICE)
    yield gui
    for window in Gtk.Window.list_toplevels():
        window.destroy()


def _firewall_dialogs():
    return [w for w in Gtk.Window.list_toplevels()
            if isinstance(w, Gtk.MessageDialog) and w.get_visible()]


def test_firewall_read_opens_dialog_when_idle(ui):
    ui.firewall = FakeFirewall()
    ui.on_firewall_read(None)
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    assert len(_firewall_dialogs()) == 1


def test_firewall_read_does_not_open_dialog_while_blocking(ui, monkeypatch):
    ui.firewall = FakeFirewall()
    ui._blocking_operation_in_flight = True
    ui.on_firewall_read(None)
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    assert _firewall_dialogs() == []
    assert ui.firewall is None  # dropped read must allow a later re-check


def test_firewall_response_does_not_fetch_devices_while_blocking(ui, monkeypatch):
    ui.firewall = FakeFirewall()
    ui.on_firewall_read(None)
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    dialogs = _firewall_dialogs()
    assert len(dialogs) == 1
    monkeypatch.setattr(ui, "fetchDevices", MagicMock())
    ui._blocking_operation_in_flight = True
    ui.adjust_firewall_response(dialogs[0], Gtk.ResponseType.NO)
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    ui.fetchDevices.assert_not_called()


def test_firewall_response_fetches_devices_when_idle(ui, monkeypatch):
    ui.firewall = FakeFirewall()
    ui.on_firewall_read(None)
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    dialogs = _firewall_dialogs()
    assert len(dialogs) == 1
    monkeypatch.setattr(ui, "fetchDevices", MagicMock())
    monkeypatch.setattr(ui, "_show_searching_spinner", MagicMock())
    ui.adjust_firewall_response(dialogs[0], Gtk.ResponseType.NO)
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    ui.fetchDevices.assert_called_once_with(network=True)


def test_dropped_read_does_not_lose_prompt_on_next_read(ui):
    # A read dropped while blocking must be recoverable: with the flag
    # cleared and a fresh read, the dialog appears again.
    ui.firewall = FakeFirewall()
    ui._blocking_operation_in_flight = True
    ui.on_firewall_read(None)
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    assert _firewall_dialogs() == []
    assert ui.firewall is None
    ui._blocking_operation_in_flight = False
    ui.firewall = FakeFirewall()
    ui.on_firewall_read(None)
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    assert len(_firewall_dialogs()) == 1


def test_firewall_read_dropped_after_leaving_device_page(ui):
    ui.ntbkNewPrinter.set_current_page(ui.PAGE_DESCRIBE_PRINTER)
    ui.firewall = FakeFirewall()
    ui.on_firewall_read(None)
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    assert _firewall_dialogs() == []
    assert ui.firewall is None


def test_firewall_read_landing_inside_run_blocking_op(ui, monkeypatch):
    # Closest mirror of the reported ordering: the reply is delivered from
    # inside a blocking operation (as the nested MainLoop would deliver
    # it during PPD validation). No dialog may open.
    monkeypatch.setattr(newprinter.authconn, "Connection", type(ui.cups))

    def run_on_worker(op):
        def deliver(*args, **kwargs):
            kwargs.pop("_timeout", None)
            return op(*args, **kwargs)
        return deliver

    ui.cups.run_on_worker.side_effect = run_on_worker
    ui.firewall = FakeFirewall()

    def probe_op():
        ui.on_firewall_read(None)
        return "done"

    assert ui._run_blocking(probe_op) == "done"
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    assert _firewall_dialogs() == []
    assert ui.firewall is None


def test_firewall_yes_while_blocking_writes_but_does_not_fetch(ui, monkeypatch):
    ui.firewall = FakeFirewall()
    ui.on_firewall_read(None)
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    dialogs = _firewall_dialogs()
    assert len(dialogs) == 1
    monkeypatch.setattr(ui, "fetchDevices", MagicMock())
    ui._blocking_operation_in_flight = True
    ui.adjust_firewall_response(dialogs[0], Gtk.ResponseType.YES)
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    ui.fetchDevices.assert_not_called()
    assert ui.firewall is None


def test_firewall_yes_while_blocking_writes_exactly_once(ui, monkeypatch):
    fake = FakeFirewall()
    ui.firewall = fake
    ui.on_firewall_read(None)
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    dialogs = _firewall_dialogs()
    assert len(dialogs) == 1
    monkeypatch.setattr(ui, "fetchDevices", MagicMock())
    ui._blocking_operation_in_flight = True
    ui.adjust_firewall_response(dialogs[0], Gtk.ResponseType.YES)
    fake.write.assert_called_once_with()


def test_firewall_no_while_blocking_does_not_write(ui, monkeypatch):
    fake = FakeFirewall()
    ui.firewall = fake
    ui.on_firewall_read(None)
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    dialogs = _firewall_dialogs()
    assert len(dialogs) == 1
    monkeypatch.setattr(ui, "fetchDevices", MagicMock())
    ui._blocking_operation_in_flight = True
    ui.adjust_firewall_response(dialogs[0], Gtk.ResponseType.NO)
    fake.write.assert_not_called()
    ui.fetchDevices.assert_not_called()
    assert ui.firewall is None


def test_firewall_read_suppressed_after_cancel(ui):
    ui._cancelled = True
    ui.firewall = FakeFirewall()
    ui.on_firewall_read(None)
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    assert _firewall_dialogs() == []
    assert ui.firewall is None


def test_firewall_response_suppressed_after_cancel(ui, monkeypatch):
    fake = FakeFirewall()
    ui.firewall = fake
    ui.on_firewall_read(None)
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    dialogs = _firewall_dialogs()
    assert len(dialogs) == 1
    monkeypatch.setattr(ui, "fetchDevices", MagicMock())
    ui._cancelled = True
    ui.adjust_firewall_response(dialogs[0], Gtk.ResponseType.NO)
    ui.fetchDevices.assert_not_called()
    assert ui.firewall is None


@pytest.fixture
def network_gate(ui, monkeypatch):
    firewall = FakeFirewall()
    monkeypatch.setattr(newprinter.firewallsettings, "FirewallD", lambda: firewall)
    monkeypatch.setattr(newprinter.asyncconn, "Connection", MagicMock())
    get_devices = MagicMock()
    monkeypatch.setattr(newprinter.cupshelpers, "getDevices", get_devices)
    ui.fetchDevices_conn = MagicMock()
    return firewall, get_devices


@pytest.mark.parametrize("response", [Gtk.ResponseType.NO, Gtk.ResponseType.YES])
def test_network_discovery_waits_for_firewall_dialog(ui, network_gate, response):
    firewall, get_devices = network_gate
    conn = ui.fetchDevices_conn
    uri = "usb://printer"
    local_devices = {uri: object()}
    ui.add_devices = MagicMock()
    ui.local_devices_reply(conn, local_devices, uri)
    get_devices.assert_not_called()
    assert not _firewall_dialogs()

    firewall.deliver_reply()
    get_devices.assert_not_called()
    dialog, = _firewall_dialogs()

    def check_write_before_fetch(*args, **kwargs):
        if response == Gtk.ResponseType.YES:
            firewall.write.assert_called_once_with()
        else:
            firewall.write.assert_not_called()

    get_devices.side_effect = check_write_before_fetch
    dialog.response(response)
    get_devices.assert_called_once()
    args, kwargs = get_devices.call_args
    assert args == (conn,)
    assert "dnssd" in kwargs["include_schemes"]
    newprinter.asyncconn.Connection.assert_not_called()
    conn.destroy.assert_not_called()
    assert ui._pending_network_discovery is None

    kwargs["reply_handler"](conn, {})
    conn._end_operation.assert_called_once_with()
    conn.destroy.assert_called_once_with()
    assert ui.fetchDevices_conn is None
    ui.add_devices.assert_called_once_with(local_devices, uri, no_more=True)


def test_network_discovery_starts_when_mdns_is_allowed(ui, network_gate):
    firewall, get_devices = network_gate
    firewall.check_mdns_allowed = lambda: True
    ui.local_devices_reply(ui.fetchDevices_conn, {}, None)
    get_devices.assert_not_called()

    firewall.deliver_reply()
    firewall.deliver_reply()
    get_devices.assert_called_once()
    assert not _firewall_dialogs()
    assert ui._pending_network_discovery is None


@pytest.mark.parametrize("async_error", [False, True])
def test_network_discovery_proceeds_on_firewall_read_failure(
        ui, network_gate, monkeypatch, async_error):
    firewall, get_devices = network_gate
    if not async_error:
        firewall.running = False
        monkeypatch.setattr(newprinter.firewallsettings, "SystemConfigFirewall",
                            MagicMock(side_effect=RuntimeError("No firewall backend")))
    ui.local_devices_reply(ui.fetchDevices_conn, {}, None)
    if async_error:
        get_devices.assert_not_called()
        firewall.error_handler(RuntimeError("Firewall read failed"))
        firewall.deliver_reply()

    get_devices.assert_called_once()
    assert not _firewall_dialogs()
    assert ui._pending_network_discovery is None
    assert ui.firewall is None


@pytest.mark.parametrize("state", ["cancelled", "blocking", "off-page"])
@pytest.mark.parametrize("dialog_open", [False, True])
def test_stale_firewall_gate_abandons_network_discovery(
        ui, network_gate, state, dialog_open):
    firewall, get_devices = network_gate
    conn = ui.fetchDevices_conn
    ui.local_devices_reply(conn, {}, None)
    if dialog_open:
        firewall.deliver_reply()
        dialog, = _firewall_dialogs()

    if state == "cancelled":
        ui._cancelled = True
    elif state == "blocking":
        ui._blocking_operation_in_flight = True
    else:
        ui.ntbkNewPrinter.set_current_page(ui.PAGE_DESCRIBE_PRINTER)

    if dialog_open:
        dialog.response(Gtk.ResponseType.YES)
        firewall.write.assert_called_once_with()
    else:
        firewall.deliver_reply()

    get_devices.assert_not_called()
    assert not _firewall_dialogs()
    assert ui._pending_network_discovery is None
    assert ui.firewall is None
    conn._end_operation.assert_called_once_with()
    conn.destroy.assert_called_once_with()
    assert ui.fetchDevices_conn is None

"""Probe/regression: firewall reply must not interrupt a blocking operation.

Bug: a delayed on_firewall_read landing while _run_blocking pumps the
nested MainLoop opens a modal "Adjust Firewall" dialog mid-validation, and
adjust_firewall_response then fires fetchDevices(network=True) unconditionally.
"""
from unittest.mock import MagicMock, call

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

    def read(self, reply_handler, error_handler=None):
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


def test_superseded_legacy_reply_leaves_new_gate_pending(
        ui, network_gate, monkeypatch):
    gate_firewall, get_devices = network_gate
    legacy_firewall = FakeFirewall()
    conn = ui.fetchDevices_conn
    ui.fetchDevices_conn = None
    ui.firewall = None
    view = MagicMock()
    view.row_expanded.return_value = True
    monkeypatch.setattr(ui, "tvNPDevices", view)
    monkeypatch.setattr(ui, "_get_firewall",
                        MagicMock(side_effect=[legacy_firewall, gate_firewall]))
    newprinter.NewPrinterGUI.check_firewall(ui)
    assert ui.firewall is legacy_firewall

    # A new device scan resets the legacy firewall before local discovery.
    ui.firewall = None
    ui.fetchDevices_conn = conn
    ui.local_devices_reply(conn, {}, None)
    pending = ui._pending_network_discovery
    assert pending is not None

    ui._blocking_operation_in_flight = True
    legacy_firewall.deliver_reply()
    assert ui.firewall is gate_firewall
    assert ui._pending_network_discovery is pending
    assert ui.fetchDevices_conn is conn
    assert not _firewall_dialogs()
    get_devices.assert_not_called()

    ui._blocking_operation_in_flight = False
    gate_firewall.check_mdns_allowed = lambda: True
    gate_firewall.deliver_reply()
    assert ui._pending_network_discovery is None
    get_devices.assert_called_once()
    assert get_devices.call_args.args == (conn,)


def test_superseded_legacy_dialog_writes_without_replacing_gate(ui, network_gate):
    gate_firewall, get_devices = network_gate
    legacy_firewall = FakeFirewall()
    ui.firewall = legacy_firewall
    ui.on_firewall_read(None)
    dialog, = _firewall_dialogs()

    conn = ui.fetchDevices_conn
    ui.firewall = None
    ui.local_devices_reply(conn, {}, None)
    pending = ui._pending_network_discovery
    assert pending is not None

    dialog.response(Gtk.ResponseType.YES)
    legacy_firewall.write.assert_called_once_with()
    gate_firewall.write.assert_not_called()
    assert ui.firewall is gate_firewall
    assert ui._pending_network_discovery is pending
    assert ui.fetchDevices_conn is conn
    get_devices.assert_not_called()
    newprinter.asyncconn.Connection.assert_not_called()


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


@pytest.mark.parametrize("state", ["cancelled", "off-page"])
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


@pytest.mark.parametrize("response", [Gtk.ResponseType.NO, Gtk.ResponseType.YES])
def test_firewall_error_after_dialog_is_ignored(ui, network_gate, response):
    firewall, get_devices = network_gate
    conn = ui.fetchDevices_conn
    ui.local_devices_reply(conn, {}, None)
    firewall.deliver_reply()
    dialog, = _firewall_dialogs()

    firewall.error_handler(RuntimeError("Late firewall error"))
    get_devices.assert_not_called()
    assert ui.firewall is firewall

    dialog.response(response)
    get_devices.assert_called_once()
    assert get_devices.call_args.args == (conn,)
    newprinter.asyncconn.Connection.assert_not_called()
    if response == Gtk.ResponseType.YES:
        firewall.write.assert_called_once_with()
    else:
        firewall.write.assert_not_called()


@pytest.mark.parametrize("response", [Gtk.ResponseType.NO, Gtk.ResponseType.YES])
def test_firewall_dialog_response_after_gate_finishes(ui, network_gate, response):
    firewall, get_devices = network_gate
    conn = ui.fetchDevices_conn
    ui.local_devices_reply(conn, {}, None)
    firewall.deliver_reply()
    dialog, = _firewall_dialogs()

    ui._finish_pending_network_discovery()
    assert get_devices.call_count == 1
    ui.firewall = None
    dialog.response(response)

    get_devices.assert_called_once()
    newprinter.asyncconn.Connection.assert_not_called()
    if response == Gtk.ResponseType.YES:
        firewall.write.assert_called_once_with()
    else:
        firewall.write.assert_not_called()


def test_duplicate_denied_firewall_replies_open_one_dialog(ui, network_gate):
    firewall, get_devices = network_gate
    ui.local_devices_reply(ui.fetchDevices_conn, {}, None)
    firewall.deliver_reply()
    firewall.deliver_reply()

    assert len(_firewall_dialogs()) == 1
    firewall.add_service.assert_called_once()
    get_devices.assert_not_called()


@pytest.mark.parametrize("dialog_open", [False, True])
def test_blocking_firewall_gate_defers_network_discovery(
        ui, network_gate, monkeypatch, dialog_open):
    firewall, get_devices = network_gate
    conn = ui.fetchDevices_conn
    uri = "usb://printer"
    local_devices = {uri: object()}
    ui.local_devices_reply(conn, local_devices, uri)
    original_reply = firewall.reply_handler
    if dialog_open:
        firewall.deliver_reply()
        dialog, = _firewall_dialogs()

    ui._blocking_operation_in_flight = True
    if dialog_open:
        dialog.response(Gtk.ResponseType.YES)
        firewall.write.assert_called_once_with()
    else:
        firewall.deliver_reply()

    get_devices.assert_not_called()
    conn._end_operation.assert_not_called()
    conn.destroy.assert_not_called()
    assert ui.fetchDevices_conn is conn
    assert ui._pending_devices == local_devices
    assert ui.firewall is None

    monkeypatch.setattr(newprinter.authconn, "Connection", type(ui.cups))
    ui.cups.run_on_worker.side_effect = lambda op: lambda **kwargs: op()
    assert ui._run_blocking(lambda: "done") == "done"
    assert not ui._blocking_operation_in_flight
    assert firewall.reply_handler is not original_reply
    assert ui._deferred_network_discovery is None
    get_devices.assert_not_called()

    firewall.check_mdns_allowed = lambda: True
    original_reply(None)
    get_devices.assert_not_called()
    firewall.deliver_reply()
    get_devices.assert_called_once()
    assert get_devices.call_args.args == (conn,)
    assert "dnssd" in get_devices.call_args.kwargs["include_schemes"]
    assert ui._pending_devices == local_devices


def test_nested_blocking_resumes_firewall_gate_at_outer_exit(
        ui, network_gate, monkeypatch):
    firewall, get_devices = network_gate
    ui.local_devices_reply(ui.fetchDevices_conn, {}, None)
    ui._blocking_operation_in_flight = True
    firewall.deliver_reply()
    deferred = ui._deferred_network_discovery
    assert deferred is not None

    monkeypatch.setattr(newprinter.authconn, "Connection", type(ui.cups))
    ui.cups.run_on_worker.side_effect = lambda op: lambda **kwargs: op()
    resume = MagicMock(wraps=ui._resume_deferred_network_discovery)
    monkeypatch.setattr(ui, "_resume_deferred_network_discovery", resume)
    busy = MagicMock()
    monkeypatch.setattr(ui, "_set_wizard_busy", busy)
    monkeypatch.setattr(firewall, "read",
                        lambda reply_handler, error_handler: reply_handler(None))
    ui.cups._cancel = True

    def outer():
        assert ui._run_blocking(lambda: "inner", spinner_text="Inner") == "inner"
        assert ui._blocking_operation_in_flight
        assert ui._deferred_network_discovery is deferred
        assert ui.cups._cancel is True
        assert busy.call_args_list == [
            call(True, "Outer", cancelable=False),
            call(True, "Inner", cancelable=False),
            call(True, "Outer", cancelable=False),
        ]
        resume.assert_not_called()
        assert not _firewall_dialogs()

    ui._run_blocking(outer, spinner_text="Outer")
    assert not ui._blocking_operation_in_flight
    assert ui._deferred_network_discovery is None
    assert ui.cups._cancel is False
    assert busy.call_args_list[-1] == call(False)
    resume.assert_called_once_with()
    dialog, = _firewall_dialogs()
    dialog.response(Gtk.ResponseType.NO)
    get_devices.assert_called_once()


@pytest.mark.parametrize("outer_cancelable,inner_cancelable",
                         [(True, False), (False, True)])
def test_nested_blocking_restores_outer_cancelable(
        ui, monkeypatch, outer_cancelable, inner_cancelable):
    monkeypatch.setattr(newprinter.authconn, "Connection", type(ui.cups))
    ui.cups.run_on_worker.side_effect = lambda op: lambda **kwargs: op()
    busy = MagicMock()
    monkeypatch.setattr(ui, "_set_wizard_busy", busy)
    resume = MagicMock()
    monkeypatch.setattr(ui, "_resume_deferred_network_discovery", resume)
    expected_calls = [
        call(True, "Outer", cancelable=outer_cancelable),
        call(True, "Inner", cancelable=inner_cancelable),
        call(True, "Outer", cancelable=outer_cancelable),
    ]

    def outer():
        ui._run_blocking(lambda: None, spinner_text="Inner",
                         cancelable=inner_cancelable)
        assert ui._blocking_operation_in_flight
        assert busy.call_args_list == expected_calls
        resume.assert_not_called()

    ui._run_blocking(outer, spinner_text="Outer", cancelable=outer_cancelable)
    assert not ui._blocking_operation_in_flight
    assert ui._blocking_busy_stack == []
    assert busy.call_args_list == expected_calls + [call(False)]
    resume.assert_called_once_with()


def test_nested_blocking_busy_setup_error_allows_later_discovery(
        ui, network_gate, monkeypatch):
    firewall, get_devices = network_gate
    conn = ui.fetchDevices_conn
    monkeypatch.setattr(newprinter.authconn, "Connection", type(ui.cups))
    ui.cups.run_on_worker.side_effect = lambda op: lambda **kwargs: op()
    resume = MagicMock(wraps=ui._resume_deferred_network_discovery)
    monkeypatch.setattr(ui, "_resume_deferred_network_discovery", resume)

    def set_busy(busy, spinner_text="", *, cancelable=True):
        if busy and spinner_text == "Inner":
            raise TypeError("busy setup failed")

    busy = MagicMock(side_effect=set_busy)
    monkeypatch.setattr(ui, "_set_wizard_busy", busy)

    def outer():
        with pytest.raises(TypeError, match="busy setup failed") as setup_error:
            ui._run_blocking(lambda: None, spinner_text="Inner", cancelable=True)
        assert ui._blocking_operation_depth == 1
        assert ui._blocking_operation_in_flight
        assert ui._blocking_busy_stack == [("Outer", False)]
        assert busy.call_args_list == [
            call(True, "Outer", cancelable=False),
            call(True, "Inner", cancelable=True),
            call(True, "Outer", cancelable=False),
        ]
        resume.assert_not_called()
        raise setup_error.value

    with pytest.raises(TypeError, match="busy setup failed"):
        ui._run_blocking(outer, spinner_text="Outer")
    assert ui._blocking_operation_depth == 0
    assert ui._blocking_operation_in_flight is False
    assert ui._blocking_busy_stack == []
    assert busy.call_args_list[-1] == call(False)
    resume.assert_called_once_with()

    resume.reset_mock()
    ui.local_devices_reply(conn, {}, None)

    def defer_scan():
        firewall.deliver_reply()
        assert ui._deferred_network_discovery is not None
        get_devices.assert_not_called()
        return "done"

    assert ui._run_blocking(defer_scan) == "done"
    resume.assert_called_once_with()
    assert ui._deferred_network_discovery is None
    monkeypatch.setattr(firewall, "check_mdns_allowed", lambda: True)
    firewall.deliver_reply()
    get_devices.assert_called_once()


def test_deferred_firewall_gate_is_dropped_after_leaving_device_page(
        ui, network_gate, monkeypatch):
    firewall, get_devices = network_gate
    conn = ui.fetchDevices_conn
    ui.local_devices_reply(conn, {"usb://printer": object()}, None)
    monkeypatch.setattr(newprinter.authconn, "Connection", type(ui.cups))
    ui.cups.run_on_worker.side_effect = lambda op: lambda **kwargs: op()

    def leave_device_page():
        firewall.deliver_reply()
        conn.destroy.assert_not_called()
        ui.ntbkNewPrinter.set_current_page(ui.PAGE_DESCRIBE_PRINTER)

    ui._run_blocking(leave_device_page)

    get_devices.assert_not_called()
    conn._end_operation.assert_called_once_with()
    conn.destroy.assert_called_once_with()
    assert ui.fetchDevices_conn is None
    assert ui._pending_devices is None
    assert ui._deferred_network_discovery is None


def test_synchronous_network_dispatch_error_displays_local_devices(
        ui, network_gate, monkeypatch):
    firewall, get_devices = network_gate
    conn = ui.fetchDevices_conn
    local_devices = {"usb://printer": newprinter.cupshelpers.Device("usb://printer")}
    ui.add_devices = MagicMock(wraps=ui.add_devices)
    hide_spinner = MagicMock()
    monkeypatch.setattr(ui, "_hide_searching_spinner", hide_spinner)
    firewall.check_mdns_allowed = lambda: True
    get_devices.side_effect = RuntimeError("Network dispatch failed")
    ui.local_devices_reply(conn, local_devices, None)
    firewall.deliver_reply()

    get_devices.assert_called_once()
    conn._end_operation.assert_called_once_with()
    conn.destroy.assert_called_once_with()
    assert ui.fetchDevices_conn is None
    assert ui._pending_devices is None
    ui.add_devices.assert_called_once_with(local_devices, None, no_more=True)
    hide_spinner.assert_called_once_with()


def test_firewall_write_error_still_releases_gate(ui, network_gate, monkeypatch):
    firewall, get_devices = network_gate
    report_error = MagicMock()
    monkeypatch.setattr(newprinter, "nonfatalException", report_error)
    firewall.write.side_effect = RuntimeError("Firewall write failed")
    ui.local_devices_reply(ui.fetchDevices_conn, {}, None)
    firewall.deliver_reply()
    dialog, = _firewall_dialogs()
    dialog.response(Gtk.ResponseType.YES)

    firewall.write.assert_called_once_with()
    report_error.assert_called_once_with()
    get_devices.assert_called_once()
    newprinter.asyncconn.Connection.assert_not_called()
    assert ui._pending_network_discovery is None


def test_missing_firewall_gate_host_fetches_directly(ui, network_gate):
    _, get_devices = network_gate
    ui._host = None
    conn = ui.fetchDevices_conn
    ui.local_devices_reply(conn, {}, None)

    get_devices.assert_called_once()
    assert get_devices.call_args.args == (conn,)
    assert "dnssd" in get_devices.call_args.kwargs["include_schemes"]
    assert ui._pending_network_discovery is None

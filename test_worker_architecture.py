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

import os
from pathlib import Path
import tempfile
import threading
import time
import pytest
import cups
import authconn
from vectorspinner import DelayedSpinner, VectorSpinner
from gi.repository import GLib, Gtk


def test_vector_spinner_does_not_import_python_cairo():
    source = (Path(__file__).parent / "vectorspinner.py").read_text()
    assert "import cairo" not in source
    assert "from cairo" not in source


def test_vector_spinner_draws_with_gtk_context():
    # Avoid constructing a native widget in the headless unit-test process;
    # exercise the drawing logic with the same state the constructor sets.
    spinner = VectorSpinner.__new__(VectorSpinner)
    spinner._size = 32
    spinner._step = 0
    calls = []

    class DrawContext:
        def set_line_width(self, value):
            calls.append(("line_width", value))

        def set_line_cap(self, value):
            calls.append(("line_cap", value))

        def set_source_rgba(self, *values):
            calls.append(("color", values))

        def arc(self, *values):
            calls.append(("arc", values))

        def stroke(self):
            calls.append(("stroke",))

    assert spinner._on_draw(spinner, DrawContext()) is False
    assert ("line_cap", 1) in calls
    assert any(call[0] == "arc" for call in calls)
    assert ("stroke",) in calls


class FakeCupsConnection:
    """Mock cups.Connection for worker unit tests."""
    def __init__(self, *args, **kwargs):
        self.host = kwargs.get('host', 'localhost')
        self.port = kwargs.get('port', 631)
        self.user = cups.getUser()
        self.client_name = "test"

    def getPrinters(self):
        return {}

    def addPrinter(self, *args, **kwargs):
        pass

    def getServerPPD(self, name):
        return f"/tmp/fake_server_{name}.ppd"

    def getPPD(self, name):
        return f"/tmp/fake_local_{name}.ppd"

    def getDevices(self, *args, **kwargs):
        return {"test://uri": {"device-info": "Test Printer"}}


@pytest.fixture(autouse=True)
def patch_cups_connection(monkeypatch):
    monkeypatch.setattr(cups, "Connection", FakeCupsConnection)
    monkeypatch.setattr(authconn.cups, "Connection", FakeCupsConnection)


def test_generic_worker_callable():
    conn = authconn.Connection(host="127.0.0.1", port=631, encryption=cups.HTTP_ENCRYPT_NEVER)
    main_thread = threading.current_thread()
    exec_threads = []

    # Standalone function without connection parameter
    def compute(x, y):
        exec_threads.append(threading.current_thread())
        return x + y

    res1 = conn.run_on_worker(compute)(10, 25)
    assert res1 == 35
    assert exec_threads[0] != main_thread
    assert exec_threads[0] == conn._worker_thread

    # Function expecting worker connection
    def probe_conn(c, prefix):
        exec_threads.append(threading.current_thread())
        return f"{prefix}:{c.host}"
    probe_conn._with_connection = True

    res2 = conn.run_on_worker(probe_conn)("server")
    assert res2 == "server:127.0.0.1"
    assert exec_threads[1] == conn._worker_thread


def test_bound_cups_method():
    conn = authconn.Connection(host="127.0.0.1", port=631, encryption=cups.HTTP_ENCRYPT_NEVER)
    res = conn.run_on_worker(conn.getServerPPD)("my_printer")
    assert res == "/tmp/fake_server_my_printer.ppd"


def test_string_operation():
    conn = authconn.Connection(host="127.0.0.1", port=631, encryption=cups.HTTP_ENCRYPT_NEVER)
    res = conn.run_on_worker("getServerPPD")("string_printer")
    assert res == "/tmp/fake_server_string_printer.ppd"


def test_fifo_sequential_execution():
    conn = authconn.Connection(host="127.0.0.1", port=631, encryption=cups.HTTP_ENCRYPT_NEVER)
    execution_order = []

    def op1():
        execution_order.append(1)
        return "first"

    def op2():
        execution_order.append(2)
        return "second"

    res1 = conn.run_on_worker(op1)()
    res2 = conn.run_on_worker(op2)()

    assert res1 == "first"
    assert res2 == "second"
    assert execution_order == [1, 2]


def test_multiple_queued_operations():
    conn = authconn.Connection(host="127.0.0.1", port=631, encryption=cups.HTTP_ENCRYPT_NEVER)
    results = []

    def make_op(idx):
        def op():
            results.append(idx)
            return idx * 10
        return op

    out = [conn.run_on_worker(make_op(i))() for i in range(5)]
    assert out == [0, 10, 20, 30, 40]
    assert results == [0, 1, 2, 3, 4]


def test_worker_thread_reentrancy():
    conn = authconn.Connection(host="127.0.0.1", port=631, encryption=cups.HTTP_ENCRYPT_NEVER)

    def inner_op(n):
        return n * 2

    def outer_op():
        return conn.run_on_worker(inner_op)(21)

    result = conn.run_on_worker(outer_op)()
    assert result == 42


def test_clean_exception_propagation():
    conn = authconn.Connection(host="127.0.0.1", port=631, encryption=cups.HTTP_ENCRYPT_NEVER)

    def failing_op():
        raise ValueError("Intentional worker test failure")

    with pytest.raises(ValueError, match="Intentional worker test failure"):
        conn.run_on_worker(failing_op)()

    def type_error_op(val):
        return val + 123  # If val is str, raises TypeError

    with pytest.raises(TypeError):
        conn.run_on_worker(type_error_op)("invalid_string_argument")


def test_worker_timeout():
    conn = authconn.Connection(host="127.0.0.1", port=631, encryption=cups.HTTP_ENCRYPT_NEVER)
    finish_event = threading.Event()

    def slow_op():
        finish_event.wait(timeout=2.0)
        return "late"

    start = time.monotonic()
    with pytest.raises(authconn.WorkerTimeoutError):
        
        conn.run_on_worker(slow_op)(_timeout=0.1)
    duration = time.monotonic() - start
    assert duration < 1.0
    finish_event.set()


def test_worker_recovery_after_timeout():
    conn = authconn.Connection(host="127.0.0.1", port=631, encryption=cups.HTTP_ENCRYPT_NEVER)
    stuck_gate = threading.Event()

    def stuck_op():
        stuck_gate.wait(timeout=2.0)
        return "done_stuck"

    with pytest.raises(authconn.WorkerTimeoutError):
        conn.run_on_worker(stuck_op)(_timeout=0.08)

    with pytest.raises(authconn.WorkerUnavailableError):
        conn.run_on_worker(lambda: "fail_fast")()

    stuck_gate.set()
    conn._worker_queue.join()

    res = conn.run_on_worker(lambda: "recovered")()
    assert res == "recovered"
    assert conn._worker_state == 'IDLE'


def test_concurrency_caller_abandons_a_while_b_queued():
    conn = authconn.Connection(host="127.0.0.1", port=631, encryption=cups.HTTP_ENCRYPT_NEVER)
    a_started = threading.Event()
    a_release = threading.Event()
    a_finished = threading.Event()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".ppd") as tmp:
        a_temp_file = tmp.name

    assert os.path.exists(a_temp_file)

    ui_state = {'alive': True, 'result': None}

    def op_a():
        a_started.set()
        a_release.wait(timeout=5.0)
        a_finished.set()
        return a_temp_file

    def caller_a_task():
        res = conn.run_on_worker(op_a)()
        if ui_state['alive']:
            ui_state['result'] = res
        else:
            # Emulate NewPrinterGUI lifecycle: discard result and unlink temporary file
            try:
                os.unlink(res)
            except OSError:
                pass

    t_a = threading.Thread(target=caller_a_task, daemon=True)
    t_a.start()
    assert a_started.wait(timeout=2.0), "Request A failed to start in worker"

    b_results = []

    def caller_b_task():
        res = conn.run_on_worker(lambda: "result_b")()
        b_results.append(res)

    t_b = threading.Thread(target=caller_b_task, daemon=True)
    t_b.start()
    time.sleep(0.05)

    # Caller A abandons/cancels UI operation
    ui_state['alive'] = False

    # Release A to finish
    a_release.set()

    t_a.join(timeout=2.0)
    assert not t_a.is_alive()
    assert a_finished.is_set(), "A must run to completion in worker"
    assert ui_state['result'] is None, "A's result must not be applied to abandoned caller"
    assert not os.path.exists(a_temp_file), "A's temporary file must be unlinked when abandoned"

    t_b.join(timeout=2.0)
    assert not t_b.is_alive()
    assert b_results == ["result_b"], "B must execute normally and return expected result"

    assert conn._worker_thread.is_alive(), "Worker thread must remain alive"
    assert conn._worker_state == 'IDLE'

    res_c = conn.run_on_worker(lambda: "result_c")()
    assert res_c == "result_c", "Worker must remain usable for subsequent request C"
    assert conn._worker_state == 'IDLE'


def test_concurrency_a_raises_exception_b_and_c_still_run():
    conn = authconn.Connection(host="127.0.0.1", port=631, encryption=cups.HTTP_ENCRYPT_NEVER)

    def failing_op():
        raise cups.IPPError(cups.IPP_NOT_FOUND, "printer not found")

    with pytest.raises(cups.IPPError) as exc_info:
        conn.run_on_worker(failing_op)()
    assert exc_info.value.args[0] == cups.IPP_NOT_FOUND

    res_b = conn.run_on_worker(lambda: "result_b")()
    assert res_b == "result_b"

    res_c = conn.run_on_worker(lambda: "result_c")()
    assert res_c == "result_c"


def test_authentication_retry(monkeypatch):
    conn = authconn.Connection(host="127.0.0.1", port=631, encryption=cups.HTTP_ENCRYPT_NEVER)
    attempts = [0]
    auth_dialog_shown = [0]

    class AuthChallengedConnection(FakeCupsConnection):
        def getPPD(self, name):
            attempts[0] += 1
            if attempts[0] == 1:
                raise cups.IPPError(cups.IPP_NOT_AUTHORIZED, "Not authorized")
            return f"/tmp/authenticated_{name}.ppd"

    monkeypatch.setattr(cups, "Connection", AuthChallengedConnection)
    monkeypatch.setattr(authconn.cups, "Connection", AuthChallengedConnection)

    def mock_perform_auth():
        auth_dialog_shown[0] += 1
        conn._has_failed = False
        return 1 if attempts[0] < 2 else 0

    monkeypatch.setattr(conn, "_perform_authentication", mock_perform_auth)

    res = conn.run_on_worker(conn.getPPD)("secure_queue")
    assert res == "/tmp/authenticated_secure_queue.ppd"
    assert attempts[0] == 2
    assert auth_dialog_shown[0] >= 2


def test_authentication_cancellation(monkeypatch):
    conn = authconn.Connection(host="127.0.0.1", port=631, encryption=cups.HTTP_ENCRYPT_NEVER)
    attempts = [0]
    auth_passes = [0]

    class AlwaysFailsConn(FakeCupsConnection):
        def getPPD(self, name):
            attempts[0] += 1
            raise cups.IPPError(cups.IPP_NOT_AUTHORIZED, "Not authorized")

    monkeypatch.setattr(cups, "Connection", AlwaysFailsConn)
    monkeypatch.setattr(authconn.cups, "Connection", AlwaysFailsConn)

    orig_perform_auth = conn._perform_authentication

    def mock_cancel_auth():
        auth_passes[0] += 1
        if auth_passes[0] == 1:
            return orig_perform_auth()
        conn.cancel()
        return -1

    monkeypatch.setattr(conn, "_perform_authentication", mock_cancel_auth)

    with pytest.raises(cups.IPPError) as exc_info:
        conn.run_on_worker(conn.getPPD)("secret_queue")

    err_code, err_msg = exc_info.value.args
    assert err_code == 0
    assert "canceled" in str(err_msg).lower()
    # Ensure cancellation remained set and did not enter an infinite retry loop
    assert conn._cancel is True
    assert attempts[0] == 1, "Must execute once, then abort on cancelled auth"

    monkeypatch.setattr(AlwaysFailsConn, "getPPD", lambda self, name: f"/tmp/next_{name}.ppd")
    monkeypatch.setattr(conn, "_perform_authentication", orig_perform_auth)

    res_next = conn.run_on_worker(conn.getPPD)("next_queue")
    assert res_next == "/tmp/next_next_queue.ppd"
    assert conn._cancel is False


def test_worker_credential_change_recreates_connection(monkeypatch):
    monkeypatch.setattr(authconn.global_authinfocache, "lookup_auth_info", lambda *a, **k: None)
    conn = authconn.Connection(host="127.0.0.1", port=631, encryption=cups.HTTP_ENCRYPT_NEVER)
    connections_created = []

    class TrackedConnection(FakeCupsConnection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            connections_created.append(cups.getUser())

        def getServerPPD(self, name):
            return f"/tmp/{cups.getUser()}_{name}.ppd"

    monkeypatch.setattr(cups, "Connection", TrackedConnection)
    monkeypatch.setattr(authconn.cups, "Connection", TrackedConnection)

    conn._use_user = "alice"
    res1 = conn.run_on_worker("getServerPPD")("test1")
    assert "alice" in res1

    conn._use_user = "root"
    res2 = conn.run_on_worker("getServerPPD")("test2")
    assert "root" in res2

    assert len(connections_created) >= 2
    assert "alice" in connections_created
    assert "root" in connections_created


def test_concurrency_fifo_ordering_preserved():
    conn = authconn.Connection(host="127.0.0.1", port=631, encryption=cups.HTTP_ENCRYPT_NEVER)
    a_started = threading.Event()
    a_release = threading.Event()
    execution_order = []

    def op_a():
        a_started.set()
        a_release.wait(timeout=5.0)
        execution_order.append("A")
        return "result_a"

    def op_b():
        execution_order.append("B")
        return "result_b"

    def op_c():
        execution_order.append("C")
        return "result_c"

    results = {}

    def run_op(name, fn):
        results[name] = conn.run_on_worker(fn)()

    t_a = threading.Thread(target=run_op, args=("A", op_a), daemon=True)
    t_a.start()
    assert a_started.wait(timeout=2.0)

    t_b = threading.Thread(target=run_op, args=("B", op_b), daemon=True)
    t_b.start()
    time.sleep(0.05)

    t_c = threading.Thread(target=run_op, args=("C", op_c), daemon=True)
    t_c.start()
    time.sleep(0.05)

    a_release.set()

    t_a.join(timeout=2.0)
    t_b.join(timeout=2.0)
    t_c.join(timeout=2.0)

    assert execution_order == ["A", "B", "C"], "FIFO execution order must be preserved"
    assert results == {"A": "result_a", "B": "result_b", "C": "result_c"}


def test_cleanup_of_discarded_temporary_files():
    conn = authconn.Connection(host="127.0.0.1", port=631, encryption=cups.HTTP_ENCRYPT_NEVER)
    worker_started = threading.Event()
    worker_finish = threading.Event()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".ppd") as tmp:
        temp_ppd_path = tmp.name

    assert os.path.exists(temp_ppd_path)

    def blocking_ppd_op():
        worker_started.set()
        worker_finish.wait(timeout=2.0)
        return temp_ppd_path

    with pytest.raises(authconn.WorkerTimeoutError):
        conn.run_on_worker(blocking_ppd_op)(_timeout=0.08)

    assert os.path.exists(temp_ppd_path), "File still exists while worker is blocked"

    worker_finish.set()
    conn._worker_queue.join()

    assert not os.path.exists(temp_ppd_path), "Timed out temporary file must be unlinked by worker"

    res = conn.run_on_worker(lambda: "recovered")()
    assert res == "recovered"
    assert conn._worker_state == 'IDLE'


def test_gtk_responsiveness_during_worker_execution():
    conn = authconn.Connection(host="127.0.0.1", port=631, encryption=cups.HTTP_ENCRYPT_NEVER)
    worker_started = threading.Event()
    worker_can_proceed = threading.Event()
    glib_event_ran = threading.Event()

    def slow_worker():
        worker_started.set()
        assert worker_can_proceed.wait(timeout=5.0)
        return "finished"

    def on_glib_idle():
        glib_event_ran.set()
        worker_can_proceed.set()
        return False

    def pump_glib():
        while not worker_started.is_set():
            time.sleep(0.01)
        GLib.idle_add(on_glib_idle)

    threading.Thread(target=pump_glib, daemon=True).start()

    res = conn.run_on_worker(slow_worker)()
    assert res == "finished"
    assert glib_event_ran.is_set()


def test_delayed_spinner_fast_operation():
    spinner = VectorSpinner()
    spinner.show = VectorSpinner.show
    spinner.hide = VectorSpinner.hide
    delayed = DelayedSpinner(spinner, delay_ms=250)

    assert not delayed.is_shown

    delayed.start()
    time.sleep(0.02)
    delayed.stop()

    assert not delayed.is_shown
    assert delayed._timer_id is None


def test_delayed_spinner_slow_operation():
    spinner = VectorSpinner()
    shown_events = []
    stopped_events = []

    spinner.show = lambda: shown_events.append(True)
    spinner.start = lambda: None
    spinner.stop = lambda: stopped_events.append(True)
    spinner.hide = lambda: None

    delayed = DelayedSpinner(spinner, delay_ms=50)
    loop = GLib.MainLoop()

    delayed.start()

    def on_after_delay():
        assert delayed.is_shown
        assert len(shown_events) == 1
        delayed.stop()
        assert not delayed.is_shown
        assert len(stopped_events) == 1
        loop.quit()
        return False

    GLib.timeout_add(80, on_after_delay)
    loop.run()

    assert len(shown_events) == 1
    assert len(stopped_events) == 1

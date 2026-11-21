#!/usr/bin/python3

## Copyright (C) 2026 Red Hat, Inc.
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

import json
import os
import socket
import threading
import pytest

import ippusb


class _MockUnixSocketServer:
    def __init__(self, socket_path, handler_callback):
        self.socket_path = socket_path
        self.handler_callback = handler_callback
        self.server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_sock.bind(socket_path)
        self.server_sock.listen(5)
        self._running = True
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while self._running:
            try:
                client_sock, _ = self.server_sock.accept()
            except OSError:
                break
            threading.Thread(target=self._handle_client, args=(client_sock,), daemon=True).start()

    def _handle_client(self, client_sock):
        try:
            req_data = b""
            while b"\r\n\r\n" not in req_data:
                chunk = client_sock.recv(4096)
                if not chunk:
                    break
                req_data += chunk
            if not req_data:
                client_sock.close()
                return

            header_part, _, body_part = req_data.partition(b"\r\n\r\n")
            lines = header_part.decode("utf-8").split("\r\n")
            method, path = lines[0].split(" ")[:2]

            content_len = 0
            for line in lines[1:]:
                if line.lower().startswith("content-length:"):
                    content_len = int(line.split(":", 1)[1].strip())

            while len(body_part) < content_len:
                chunk = client_sock.recv(4096)
                if not chunk:
                    break
                body_part += chunk

            status_code, resp_headers, resp_body = self.handler_callback(
                method, path, body_part.decode("utf-8", errors="replace"))

            reason = "OK" if status_code == 200 else ("Not Found" if status_code == 404 else "Error")
            resp = f"HTTP/1.1 {status_code} {reason}\r\n"
            for k, v in resp_headers.items():
                resp += f"{k}: {v}\r\n"
            resp += f"Content-Length: {len(resp_body)}\r\n\r\n{resp_body}"
            client_sock.sendall(resp.encode("utf-8"))
        except Exception:
            pass
        finally:
            try:
                client_sock.close()
            except Exception:
                pass

    def close(self):
        self._running = False
        try:
            self.server_sock.close()
        except Exception:
            pass
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except Exception:
                pass


def test_parse_version():
    assert ippusb.parse_version("0.9.35") == (0, 9, 35)
    assert ippusb.parse_version("0.9.35-1") == (0, 9, 35, 1)
    assert ippusb.parse_version("0.9.22") == (0, 9, 22)
    assert ippusb.parse_version("") == ()


def test_version_200_supported(tmp_path):
    sock_path = str(tmp_path / "ctrl.sock")
    server = _MockUnixSocketServer(sock_path, lambda m, p, b: (200, {"Content-Type": "text/plain"}, "0.9.35\n"))
    try:
        assert ippusb.get_api_version(socket_path=sock_path) == "0.9.35"
        assert ippusb.is_control_api_available(socket_path=sock_path) is True
    finally:
        server.close()


def test_version_200_below_min_version(tmp_path):
    sock_path = str(tmp_path / "ctrl.sock")
    server = _MockUnixSocketServer(sock_path, lambda m, p, b: (200, {"Content-Type": "text/plain"}, "0.9.34"))
    try:
        assert ippusb.get_api_version(socket_path=sock_path) == "0.9.34"
        assert ippusb.is_control_api_available(socket_path=sock_path) is False
    finally:
        server.close()


def test_version_404_assumes_0_9_22(tmp_path):
    sock_path = str(tmp_path / "ctrl.sock")
    server = _MockUnixSocketServer(sock_path, lambda m, p, b: (404, {}, "Not Found"))
    try:
        assert ippusb.get_api_version(socket_path=sock_path) == "0.9.22"
        assert ippusb.is_control_api_available(socket_path=sock_path) is False
    finally:
        server.close()


def test_socket_missing(tmp_path):
    sock_path = str(tmp_path / "nonexistent.sock")
    assert ippusb.get_api_version(socket_path=sock_path) is None
    assert ippusb.is_control_api_available(socket_path=sock_path) is False
    assert ippusb.set_device_disabled(device_uri="usb://HP/LaserJet", disabled=True, socket_path=sock_path) is False


def test_normalize_usb_uri():
    raw = "usb://Xerox/B235%20MFP?serial=34004H030206H&interface=1"
    assert ippusb._normalize_usb_uri(raw) == "usb://Xerox/B235%20MFP?serial=34004H030206H"
    assert ippusb._normalize_usb_uri("usb://HP/LaserJet?serial=ABC%20123&interface=1") == "usb://HP/LaserJet?serial=ABC%20123"
    assert ippusb._normalize_usb_uri("ipp://localhost:631") == "ipp://localhost:631"


def test_set_device_disabled_true(tmp_path):
    sock_path = str(tmp_path / "ctrl.sock")
    payloads = []

    def handler(method, path, body):
        if path == "/version":
            return 200, {"Content-Type": "text/plain"}, "0.9.35"
        if path == "/set/conf":
            payloads.append(json.loads(body))
            return 200, {"Content-Type": "application/json"}, json.dumps({"data": {}})
        return 404, {}, ""

    server = _MockUnixSocketServer(sock_path, handler)
    try:
        res = ippusb.set_device_disabled(
            device_uri="usb://Xerox/B235%20MFP?serial=34004H030206H&interface=1",
            disabled=True,
            socket_path=sock_path)
        assert res is True
        assert len(payloads) == 1
        assert payloads[0] == {
            "disabled": True,
            "usb_URI": "usb://Xerox/B235%20MFP?serial=34004H030206H"
        }
    finally:
        server.close()


def test_set_device_disabled_false(tmp_path):
    sock_path = str(tmp_path / "ctrl.sock")
    payloads = []

    def handler(method, path, body):
        if path == "/version":
            return 200, {"Content-Type": "text/plain"}, "0.9.35"
        if path == "/set/conf":
            payloads.append(json.loads(body))
            return 200, {"Content-Type": "application/json"}, json.dumps({"data": {}})
        return 404, {}, ""

    server = _MockUnixSocketServer(sock_path, handler)
    try:
        res = ippusb.set_device_disabled(
            device_uri="usb://Xerox/B235%20MFP?serial=34004H030206H",
            disabled=False,
            socket_path=sock_path)
        assert res is True
        assert len(payloads) == 1
        assert payloads[0] == {
            "disabled": False,
            "usb_URI": "usb://Xerox/B235%20MFP?serial=34004H030206H"
        }
    finally:
        server.close()


def test_set_device_disabled_api_unavailable(tmp_path):
    sock_path = str(tmp_path / "ctrl.sock")
    server = _MockUnixSocketServer(sock_path, lambda m, p, b: (404, {}, "Not Found"))
    try:
        res = ippusb.set_device_disabled(
            device_uri="usb://HP/LaserJet?serial=123",
            disabled=True,
            socket_path=sock_path)
        assert res is False
    finally:
        server.close()

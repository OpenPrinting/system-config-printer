#!/usr/bin/python3

## system-config-printer

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

import http.client
import json
import os
import re
import socket
import urllib.parse
from debug import debugprint

DEFAULT_CTRL_SOCKET = "/var/ipp-usb/ctrl"
MIN_VERSION = (0, 9, 35)


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path, timeout=2.0):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


def parse_version(ver_str):
    if not ver_str or not isinstance(ver_str, str):
        return ()
    digits = re.findall(r"\d+", ver_str.split()[0] if ver_str.strip() else "")
    return tuple(map(int, digits))


def _request(method, path, body=None, socket_path=DEFAULT_CTRL_SOCKET, timeout=2.0):
    if not hasattr(socket, "AF_UNIX") or not os.path.exists(socket_path):
        return None, None
    conn = _UnixHTTPConnection(socket_path, timeout=timeout)
    try:
        headers = {"Content-Type": "application/json"} if body is not None else {}
        data = json.dumps(body) if isinstance(body, (dict, list)) else body
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        return resp.status, resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        debugprint(f"ipp-usb: request {method} {path} failed: {e}")
        return None, None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_api_version(socket_path=DEFAULT_CTRL_SOCKET, timeout=2.0):
    status, body = _request("GET", "/version", socket_path=socket_path, timeout=timeout)
    if status == 200 and body:
        return body.strip()
    if status == 404:
        return "0.9.22"
    return None


def is_control_api_available(socket_path=DEFAULT_CTRL_SOCKET, timeout=2.0):
    ver = get_api_version(socket_path=socket_path, timeout=timeout)
    return bool(ver and parse_version(ver) >= MIN_VERSION)


def _normalize_usb_uri(uri):
    """Strip extraneous query parameters like &interface=1 for ipp-usb URI matching."""
    if not uri or not isinstance(uri, str):
        return uri
    try:
        parsed = urllib.parse.urlsplit(uri)
        if parsed.scheme == "usb":
            q = urllib.parse.parse_qs(parsed.query)
            clean_q = {"serial": q["serial"][0]} if "serial" in q and q["serial"] else {}
            new_query = urllib.parse.urlencode(clean_q, quote_via=urllib.parse.quote)
            return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, new_query, ""))
    except Exception:
        pass
    return uri


def set_device_disabled(device_uri=None, disabled=True, sn=None,
                        socket_path=DEFAULT_CTRL_SOCKET, timeout=2.0):
    if not is_control_api_available(socket_path=socket_path, timeout=timeout):
        return False
    payload = {"disabled": bool(disabled)}
    if device_uri:
        payload["usb_URI"] = _normalize_usb_uri(device_uri)
    if sn:
        payload["usb_SN"] = sn
    if not (device_uri or sn):
        return False

    status, resp_body = _request("POST", "/set/conf", body=payload,
                                 socket_path=socket_path, timeout=timeout)
    if status == 200:
        if resp_body:
            try:
                res = json.loads(resp_body)
                if isinstance(res, dict) and res.get("err"):
                    return False
            except ValueError:
                pass
        return True
    return False

import pytest

pytest.importorskip("dbus")

import dbus
import dnssdresolve


class DummyDevice:
    def __init__(self):
        self.id_dict = {'SN': ''}


def test_dns_sd_usb_ser_populates_sn():
    resolver = dnssdresolve.DNSSDHostNamesResolver.__new__(dnssdresolve.DNSSDHostNamesResolver)
    device = DummyDevice()
    resolver._devices = {'dnssd://printer': device}
    resolver._device_uri_by_name = {('printer', '_ipp._tcp', 'local'): 'dnssd://printer'}
    resolver._unresolved = 1
    resolver._reply_handler = lambda devices: None

    resolver._reply('iface', 'proto', 'printer', '_ipp._tcp', 'local',
                    'printer.local', 0, '192.0.2.1', 631,
                    ['usb_SER=34004H030206H', 'pdl=application/pdf'], 0)

    assert device.id_dict['SN'] == '34004H030206H'


class DummyIPPUSBDevice:
    def __init__(self, uri, device_class, serial):
        self.uri = uri
        self.device_class = device_class
        self.type = uri.split(':', 1)[0]
        self.id_dict = {'SN': serial}


def test_ipp_usb_helper_suppresses_legacy_usb_when_serial_matches():
    devices = [
        DummyIPPUSBDevice('usb://Xerox/B235%20MFP?serial=34004H030206H&interface=1',
                          'direct', '34004H030206H'),
        DummyIPPUSBDevice('ipp://Xerox(R)%20B235%20MFP%20(USB)._ipp._tcp.local/',
                          'network', '34004H030206H'),
    ]

    filtered = dnssdresolve.suppress_legacy_usb_devices(devices)

    assert [device.uri for device in filtered] == [
        'ipp://Xerox(R)%20B235%20MFP%20(USB)._ipp._tcp.local/'
    ]


def test_ipp_usb_helper_keeps_usb_when_no_matching_ipp_usb_exists():
    devices = [
        DummyIPPUSBDevice('usb://Xerox/B235%20MFP?serial=34004H030206H&interface=1',
                          'direct', '34004H030206H'),
    ]

    filtered = dnssdresolve.suppress_legacy_usb_devices(devices)

    assert [device.uri for device in filtered] == [
        'usb://Xerox/B235%20MFP?serial=34004H030206H&interface=1'
    ]


def test_ipp_usb_helper_leaves_lan_ipp_unchanged():
    devices = [
        DummyIPPUSBDevice('usb://Xerox/B235%20MFP?serial=34004H030206H&interface=1',
                          'direct', '34004H030206H'),
        DummyIPPUSBDevice('ipp://printer.example.com/ipp/print',
                          'network', '34004H030206H'),
    ]

    filtered = dnssdresolve.suppress_legacy_usb_devices(devices)

    assert [device.uri for device in filtered] == [
        'usb://Xerox/B235%20MFP?serial=34004H030206H&interface=1',
        'ipp://printer.example.com/ipp/print',
    ]


def test_ipp_over_usb_uri_is_resolved_but_lan_ipp_is_not():
    assert dnssdresolve.needs_service_resolution(
        'ipp://Xerox(R)%20B235%20MFP%20(USB)._ipp._tcp.local/')
    assert not dnssdresolve.needs_service_resolution(
        'ipp://printer.example.com/ipp/print')


def test_ipp_over_usb_usb_ser_populates_sn():
    uri = 'ipp://Xerox(R)%20B235%20MFP%20(USB)._ipp._tcp.local/'
    resolver = dnssdresolve.DNSSDHostNamesResolver.__new__(dnssdresolve.DNSSDHostNamesResolver)
    device = DummyDevice()
    resolver._devices = {uri: device}
    service = dnssdresolve._service_tuple_from_uri(uri)
    resolver._device_uri_by_name = {service: uri}
    resolver._unresolved = 1
    resolver._reply_handler = lambda devices: None

    resolver._reply('iface', 'proto', 'Xerox(R) B235 MFP (USB)', '_ipp._tcp', 'local',
                    'printer.local', 0, '192.0.2.1', 631,
                    ['usb_SER=34004H030206H', 'pdl=application/pdf'], 0)

    assert device.id_dict['SN'] == '34004H030206H'

def test_ipp_usb_cache_suppresses_previously_discovered_usb_when_serial_matches():
    cache = dnssdresolve.LegacyUSBDeviceCache()
    usb = DummyIPPUSBDevice('usb://Xerox/B235%20MFP?serial=34004H030206H&interface=1',
                            'direct', '34004H030206H')
    ipp_usb = DummyIPPUSBDevice('ipp://Xerox(R)%20B235%20MFP%20(USB)._ipp._tcp.local/',
                                'network', '34004H030206H')

    visible = dnssdresolve.suppress_legacy_usb_devices([usb], cache)
    superseded = cache.superseded_usb_serials([ipp_usb])
    assert superseded == {'34004H030206H'}
    visible = [d for d in visible
               if not (d.device_class == 'direct' and d.type == 'usb' and d.id_dict.get('SN', '') in superseded)]
    visible.extend(dnssdresolve.suppress_legacy_usb_devices([ipp_usb], cache))

    assert [device.uri for device in visible] == [
        'ipp://Xerox(R)%20B235%20MFP%20(USB)._ipp._tcp.local/'
    ]


def test_ipp_usb_cache_keeps_both_devices_when_serials_differ():
    cache = dnssdresolve.LegacyUSBDeviceCache()
    usb = DummyIPPUSBDevice('usb://Xerox/B235%20MFP?serial=34004H030206H&interface=1',
                            'direct', '34004H030206H')
    ipp_usb = DummyIPPUSBDevice('ipp://Xerox(R)%20B235%20MFP%20(USB)._ipp._tcp.local/',
                                'network', 'DIFFERENT')

    visible = dnssdresolve.suppress_legacy_usb_devices([usb], cache)
    superseded = cache.superseded_usb_serials([ipp_usb])
    assert superseded == set()
    visible.extend(dnssdresolve.suppress_legacy_usb_devices([ipp_usb], cache))

    assert [device.uri for device in visible] == [
        'usb://Xerox/B235%20MFP?serial=34004H030206H&interface=1',
        'ipp://Xerox(R)%20B235%20MFP%20(USB)._ipp._tcp.local/',
    ]


def test_ipp_usb_cache_does_not_affect_lan_ipp():
    cache = dnssdresolve.LegacyUSBDeviceCache()
    usb = DummyIPPUSBDevice('usb://Xerox/B235%20MFP?serial=34004H030206H&interface=1',
                            'direct', '34004H030206H')
    ipp_lan = DummyIPPUSBDevice('ipp://printer.example.com/ipp/print',
                                'network', '34004H030206H')

    visible = dnssdresolve.suppress_legacy_usb_devices([usb], cache)
    superseded = cache.superseded_usb_serials([ipp_lan])
    assert superseded == set()
    visible.extend(dnssdresolve.suppress_legacy_usb_devices([ipp_lan], cache))

    assert [device.uri for device in visible] == [
        'usb://Xerox/B235%20MFP?serial=34004H030206H&interface=1',
        'ipp://printer.example.com/ipp/print',
    ]


def test_ipp_usb_cache_does_not_suppress_usb_without_serial():
    cache = dnssdresolve.LegacyUSBDeviceCache()
    usb = DummyIPPUSBDevice('usb://Xerox/B235%20MFP?serial=&interface=1',
                            'direct', '')
    ipp_usb = DummyIPPUSBDevice('ipp://Xerox(R)%20B235%20MFP%20(USB)._ipp._tcp.local/',
                                'network', '34004H030206H')

    visible = dnssdresolve.suppress_legacy_usb_devices([usb], cache)
    superseded = cache.superseded_usb_serials([ipp_usb])
    assert superseded == set()
    visible.extend(dnssdresolve.suppress_legacy_usb_devices([ipp_usb], cache))

    assert [device.uri for device in visible] == [
        'usb://Xerox/B235%20MFP?serial=&interface=1',
        'ipp://Xerox(R)%20B235%20MFP%20(USB)._ipp._tcp.local/',
    ]

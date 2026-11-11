#!/usr/bin/python3

## Copyright (C) 2015 Red Hat, Inc.
## Authors:
##  Tim Waugh <twaugh@redhat.com>

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

import pytest
try:
    import cups
    from PhysicalDevice import PhysicalDevice
    from cupshelpers import cupshelpers
except ImportError:
    cups = None


def _make_device(uri, device_class, serial, make_and_model='Xerox B235 MFP'):
   return cupshelpers.Device(
      uri,
      **{'device-class': device_class,
         'device-make-and-model': make_and_model,
         'device-id': 'MFG:Xerox;MDL:B235 MFP;SN:%s;' % serial})

@pytest.mark.skipif(cups is None, reason="cups module not available")
def test_ordering():
    # See https://bugzilla.redhat.com/show_bug.cgi?id=1154686
    device = cupshelpers.Device("dnssd://Abc%20Def%20%5BABCDEF%5D._ipp._tcp.local/",
                                **{'device-class': "network",
                                   'device-make-and-model': "Abc Def",
                                   'device-id': "MFG:Abc;MDL:Def;"})
    phys = PhysicalDevice (device)

    device = cupshelpers.Device("hp:/net/Abc_Def?hostname=ABCDEF",
                                **{'device-class': "network",
                                   'device-make-and-model': "Abc Def",
                                   'device-id': "MFG:Abc;MDL:Def;"})
    phys.add_device (device)
    devices = phys.get_devices ()
    assert devices[0].uri.startswith ("hp:")

    device = cupshelpers.Device("usb://Abc/Def",
                                **{'device-class': "direct",
                                   'device-make-and-model': "Abc Def",
                                   'device-id': "MFG:Abc;MDL:Def;"})
    phys = PhysicalDevice (device)
    device = cupshelpers.Device("hp://Abc/Def",
                                **{'device-class': "direct",
                                   'device-make-and-model': "Abc Def",
                                   'device-id': "MFG:Abc;MDL:Def;"})
    phys.add_device (device)
    devices = phys.get_devices ()
    assert devices[0].uri.startswith ("hp")

    dev1 = cupshelpers.Device("hp:/usb/HP_Color_LaserJet_CP3525?serial=CNCTC8G0QX",
                              **{'device-id':'MFG:Hewlett-Packard;CMD:PJL,MLC,BIDI-ECP,PJL,PCLXL,PCL,POSTSCRIPT,PDF;MDL:HP Color LaserJet CP3525;CLS:PRINTER;DES:Hewlett-Packard Color LaserJet CP3525;',
                                 'device-make-and-model':'HP Color LaserJet CP3525',
                                 'device-class':'direct'})
    phys = PhysicalDevice (dev1)
    dev2 = cupshelpers.Device('usb://HP/Color%20LaserJet%20CP3525?serial=CNCTC8G0QX',
                              **{'device-id':'MFG:Hewlett-Packard;CMD:PJL,MLC,BIDI-ECP,PJL,PCLXL,PCL,POSTSCRIPT,PDF;MDL:HP Color LaserJet CP3525;CLS:PRINTER;DES:Hewlett-Packard Color LaserJet CP3525;',
                                 'device-make-and-model':'HP Color LaserJet CP3525',
                                 'device-class':'direct'})

    # hp device should sort < usb device
    assert dev1 < dev2

    phys.add_device (dev2)
    devices = phys.get_devices ()
    assert devices[0] < devices[1]
    assert devices[0].uri.startswith ("hp")


@pytest.mark.skipif(cups is None, reason="cups module not available")
def test_usb_serial_drops_interface_suffix():
   device = cupshelpers.Device(
      "usb://HP/Color%20LaserJet%20CP3525?serial=34004H030206H&interface=1",
      **{'device-id':'MFG:Hewlett-Packard;CMD:PJL,MLC,BIDI-ECP,PJL,PCLXL,PCL,POSTSCRIPT,PDF;MDL:HP Color LaserJet CP3525;CLS:PRINTER;DES:Hewlett-Packard Color LaserJet CP3525;',
         'device-make-and-model':'HP Color LaserJet CP3525',
         'device-class':'direct'})
   assert device.id_dict['SN'] == '34004H030206H'


def _make_dnssd_device(uri, device_class='network',
                       make_and_model='Xerox B235 MFP',
                       device_id='MFG:Xerox;MDL:B235 MFP;'):
    """Helper to build a cupshelpers.Device for DNS-SD test URIs."""
    return cupshelpers.Device(
        uri,
        **{'device-class': device_class,
           'device-make-and-model': make_and_model,
           'device-id': device_id})


@pytest.mark.skipif(cups is None, reason="cups module not available")
def test_multiprotocol_same_printer_grouped():
    """Case A: Two protocols for same printer must become one PhysicalDevice."""
    dev_ipps = _make_dnssd_device('ipps://Office._ipps._tcp.local/')
    dev_lpd = _make_dnssd_device('lpd://Office._printer._tcp.local/')

    phys1 = PhysicalDevice(dev_ipps)
    phys2 = PhysicalDevice(dev_lpd)
    assert phys1 == phys2
    phys1.add_device(dev_lpd)
    assert len(phys1.get_devices()) == 2


@pytest.mark.skipif(cups is None, reason="cups module not available")
def test_same_instance_different_serial_not_merged():
    """Case C: Same instance name but different serial numbers must NOT merge."""
    dev1 = _make_dnssd_device(
        'ipps://Office._ipps._tcp.local/',
        device_id='MFG:Xerox;MDL:B235 MFP;SN:SER001;')
    dev2 = _make_dnssd_device(
        'lpd://Office._printer._tcp.local/',
        device_id='MFG:Xerox;MDL:B235 MFP;SN:SER002;')
    assert PhysicalDevice(dev1) != PhysicalDevice(dev2)


@pytest.mark.skipif(cups is None, reason="cups module not available")
def test_normal_hostnames_not_misinterpreted():
    """Cases D & E: Regular hostnames or hostnames with underscores must remain network hosts."""
    for uri, expected_host in [
        ('ipp://printer.office.local/ipp/print', 'printer.office.local'),
        ('ipp://my_printer.local/ipp/print', 'my_printer.local'),
    ]:
        dev = cupshelpers.Device(uri, **{'device-class': 'network',
                                         'device-make-and-model': 'Generic Printer',
                                         'device-id': 'MFG:Generic;MDL:Printer;'})
        phys = PhysicalDevice(dev)
        assert phys._network_host == expected_host
        assert phys.dnssd_hostname is None


@pytest.mark.skipif(cups is None, reason="cups module not available")
def test_instance_name_with_dots():
    """Case J: DNS-SD instance names containing dots must extract instance correctly."""
    dev1 = _make_dnssd_device('ipps://Office.Floor2._ipps._tcp.local/')
    dev2 = _make_dnssd_device('lpd://Office.Floor2._printer._tcp.local/')
    p1 = PhysicalDevice(dev1)
    p2 = PhysicalDevice(dev2)
    assert p1.dnssd_hostname == 'Office.Floor2'
    assert p1 == p2


@pytest.mark.skipif(cups is None, reason="cups module not available")
def test_different_printers_same_model_not_merged():
    """Two printers with the same model but different instance names must
    remain separate, even if their make/model are identical."""
    dev_a = _make_dnssd_device(
        'ipps://Printer%20A._ipps._tcp.local/')
    dev_b = _make_dnssd_device(
        'ipps://Printer%20B._ipps._tcp.local/')

    phys_a = PhysicalDevice(dev_a)
    phys_b = PhysicalDevice(dev_b)
    assert phys_a != phys_b, (
        "Different DNS-SD instance names must produce different PhysicalDevices")


@pytest.mark.skipif(cups is None, reason="cups module not available")
def test_single_protocol_unchanged():
    """A printer discovered via a single protocol must behave as before."""
    dev = _make_dnssd_device(
        'ipps://Solo%20Printer._ipps._tcp.local/')
    phys = PhysicalDevice(dev)
    assert len(phys.get_devices()) == 1
    assert phys.get_devices()[0].uri == \
        'ipps://Solo%20Printer._ipps._tcp.local/'


@pytest.mark.skipif(cups is None, reason="cups module not available")
def test_usb_device_not_affected():
    """USB devices must not be affected by DNS-SD hostname extraction."""
    dev = cupshelpers.Device(
        'usb://HP/LaserJet?serial=XYZ',
        **{'device-class': 'direct',
           'device-make-and-model': 'HP LaserJet',
           'device-id': 'MFG:HP;MDL:LaserJet;SN:XYZ;'})
    phys = PhysicalDevice(dev)
    assert phys._network_host is None
    assert phys.dnssd_hostname is None
    assert phys.sn == 'XYZ'


@pytest.mark.skipif(cups is None, reason="cups module not available")
def test_regular_ip_printer_not_affected():
    """Network printers discovered by IP (not DNS-SD names) must behave
    as before."""
    dev = cupshelpers.Device(
        'ipp://192.168.1.100/ipp/print',
        **{'device-class': 'network',
           'device-make-and-model': 'HP LaserJet',
           'device-id': 'MFG:HP;MDL:LaserJet;'})
    phys = PhysicalDevice(dev)
    assert phys._network_host == '192.168.1.100'
    assert phys.dnssd_hostname is None


@pytest.mark.skipif(cups is None, reason="cups module not available")
def test_socket_printer_not_affected():
    """Socket printers discovered by IP must behave as before."""
    dev = cupshelpers.Device(
        'socket://10.0.0.5',
        **{'device-class': 'network',
           'device-make-and-model': 'Brother MFC-L2700DW',
           'device-id': 'MFG:Brother;MDL:MFC-L2700DW;'})
    phys = PhysicalDevice(dev)
    assert phys._network_host == '10.0.0.5'
    assert phys.dnssd_hostname is None


@pytest.mark.skipif(cups is None, reason="cups module not available")
def test_dnssd_scheme_device_unchanged():
    """Devices with dnssd:// URIs (classic CUPS dnssd backend) must still
    work correctly — _get_host_from_uri returns (None, None) for them,
    and hostname/address are set via Avahi resolution."""
    dev = cupshelpers.Device(
        'dnssd://Printer%20Name._ipp._tcp.local/',
        **{'device-class': 'network',
           'device-make-and-model': 'HP LaserJet',
           'device-id': 'MFG:HP;MDL:LaserJet;'})
    dev.address = '192.168.1.50'
    dev.hostname = 'printer-name'

    phys = PhysicalDevice(dev)
    assert phys._network_host == '192.168.1.50'
    assert phys.dnssd_hostname == 'printer-name.local'


@pytest.mark.skipif(cups is None, reason="cups module not available")
def test_multiprotocol_grouping_loop():
    """End-to-end grouping loop as performed by newprinter.add_devices()."""
    devices = [
        _make_dnssd_device(
            'ipps://Xerox%20B235._ipps._tcp.local/',
            device_id='MFG:Xerox;MDL:B235 MFP;CMD:PCLM,PS;'),
        _make_dnssd_device(
            'lpd://Xerox%20B235._printer._tcp.local/',
            device_id='MFG:Xerox;MDL:B235 MFP;CMD:PS;'),
        _make_dnssd_device(
            'ipp://Xerox%20B235._ipp._tcp.local/',
            device_id='MFG:Xerox;MDL:B235 MFP;CMD:PCLM;'),
        # Unrelated USB printer
        cupshelpers.Device(
            'usb://HP/LaserJet?serial=AAA',
            **{'device-class': 'direct',
               'device-make-and-model': 'HP LaserJet',
               'device-id': 'MFG:HP;MDL:LaserJet;SN:AAA;'}),
    ]

    physical_devices = []
    for device in devices:
        pd = PhysicalDevice(device)
        try:
            i = physical_devices.index(pd)
            physical_devices[i].add_device(device)
        except ValueError:
            physical_devices.append(pd)

    assert len(physical_devices) == 2

    xerox = [p for p in physical_devices if p.mdl == 'B235 MFP']
    hp = [p for p in physical_devices if p.mdl == 'LaserJet']
    assert len(xerox) == 1
    assert len(hp) == 1
    assert len(xerox[0].get_devices()) == 3
    assert len(hp[0].get_devices()) == 1


@pytest.mark.skipif(cups is None, reason="cups module not available")
def test_extract_dnssd_instance():
    """Verify _extract_dnssd_instance accurately parses DNS-SD service hostnames
    and ignores normal hostnames and IP addresses."""
    phys = PhysicalDevice(cupshelpers.Device('ipp://localhost'))

    assert phys._extract_dnssd_instance('Broken%20Xerox%20B235%20MFP._ipps._tcp.local') == 'Broken Xerox B235 MFP'
    assert phys._extract_dnssd_instance('Office._printer._tcp.local.') == 'Office'
    assert phys._extract_dnssd_instance('Floor.2.Printer._ipp._tcp.local') == 'Floor.2.Printer'
    assert phys._extract_dnssd_instance('Device._service._udp.local') == 'Device'
    assert phys._extract_dnssd_instance('B%C3%BCro%20Drucker._ipps._tcp.local') == 'Büro Drucker'

    assert phys._extract_dnssd_instance('printer.example.com') is None
    assert phys._extract_dnssd_instance('printer.local') is None
    assert phys._extract_dnssd_instance('192.168.1.100') is None
    assert phys._extract_dnssd_instance('server.sub.example.local') is None
    assert phys._extract_dnssd_instance('') is None
    assert phys._extract_dnssd_instance(None) is None


@pytest.mark.skipif(cups is None, reason="cups module not available")
def test_get_info_clean_printer_name():
    """Verify get_info() displays a clean printer name without cryptic .local hostnames."""
    dnssd_dev = cupshelpers.Device(
        'ipps://Broken%20Xerox%20B235%20MFP._ipps._tcp.local/',
        **{'device-class': 'network',
           'device-make-and-model': 'Broken Xerox B235 MFP',
           'device-id': 'MFG:Xerox;MDL:B235 MFP;'})
    phys_dnssd = PhysicalDevice(dnssd_dev)
    assert phys_dnssd.get_info() == 'Xerox B235 MFP'
    assert '.local' not in phys_dnssd.get_info()

    ip_dev = cupshelpers.Device(
        'socket://192.168.1.100',
        **{'device-class': 'network',
           'device-make-and-model': 'HP LaserJet 4000',
           'device-id': 'MFG:HP;MDL:LaserJet 4000;'})
    phys_ip = PhysicalDevice(ip_dev)
    assert phys_ip.get_info() == 'HP LaserJet 4000 (192.168.1.100)'

    local_dev = cupshelpers.Device(
        'ipp://printer.local/ipp/print',
        **{'device-class': 'network',
           'device-make-and-model': 'HP LaserJet 4000',
           'device-id': 'MFG:HP;MDL:LaserJet 4000;'})
    phys_local = PhysicalDevice(local_dev)
    assert phys_local.get_info() == 'HP LaserJet 4000 (printer.local)'

    fqdn_dev = cupshelpers.Device(
        'ipp://printer.example.com/ipp/print',
        **{'device-class': 'network',
           'device-make-and-model': 'HP LaserJet 4000',
           'device-id': 'MFG:HP;MDL:LaserJet 4000;'})
    phys_fqdn = PhysicalDevice(fqdn_dev)
    assert phys_fqdn.get_info() == 'HP LaserJet 4000 (printer.example.com)'

    usb_dev = cupshelpers.Device(
        'usb://HP/LaserJet?serial=XYZ123',
        **{'device-class': 'direct',
           'device-make-and-model': 'HP LaserJet',
           'device-id': 'MFG:HP;MDL:LaserJet;SN:XYZ123;'})
    phys_usb = PhysicalDevice(usb_dev)
    assert phys_usb.get_info() == 'HP LaserJet (XYZ123)'


@pytest.mark.skipif(cups is None, reason="cups module not available")
def test_multiprotocol_encoded_unicode_instance_grouped():
    """Verify that multi-protocol printers with percent-encoded Unicode instance names
    (e.g., spaces and non-ASCII chars) are correctly unquoted and grouped."""
    dev_ipps = _make_dnssd_device('ipps://B%C3%BCro%20Drucker._ipps._tcp.local/')
    dev_lpd = _make_dnssd_device('lpd://B%C3%BCro%20Drucker._printer._tcp.local/')

    p_ipps = PhysicalDevice(dev_ipps)
    p_lpd = PhysicalDevice(dev_lpd)
    assert p_ipps.dnssd_hostname == 'Büro Drucker.local'
    assert p_lpd.dnssd_hostname == 'Büro Drucker.local'
    assert p_ipps == p_lpd


def test_canonical_id_fallback_when_mfg_mdl_empty():
    """Test A: A device with empty MFG/MDL in id_dict must fall back to
    make_and_model instead of returning ('', '')."""
    dev = cupshelpers.Device(
        'ipp://Xerox(R)%20B235%20MFP%20(USB)._ipp._tcp.local/',
        **{'device-class': 'network',
           'device-info': 'Xerox(R) B235 MFP (USB)',
           'device-make-and-model': 'Xerox(R) B235 MFP (USB)',
           'device-id': 'MFG:;MDL:;SN:34004H030206H;'})

    phys = PhysicalDevice(dev)
    assert phys.mfg != ''
    assert phys.mdl != ''
    assert (phys.mfg, phys.mdl) == ('Xerox(R)', 'B235 MFP')


def test_get_info_falls_back_to_device_info_when_translation_absent():
    """Test B: A device whose info string is not present in _ppdippstr
    must have get_info() return the original device.info rather than None."""
    dev = cupshelpers.Device(
        'ipp://Xerox(R)%20B235%20MFP%20(USB)._ipp._tcp.local/',
        **{'device-class': 'network',
           'device-info': 'Xerox(R) B235 MFP (USB)',
           'device-make-and-model': 'Xerox(R) B235 MFP (USB)',
           'device-id': 'MFG:;MDL:;SN:34004H030206H;'})

    phys = PhysicalDevice(dev)
    # Manually clear mfg to trigger the backend translation lookup branch
    phys.mfg = ''
    info = phys.get_info()
    assert info is not None
    assert info == 'Xerox(R) B235 MFP (USB)'


@pytest.mark.skipif(cups is None, reason="cups module not available")
def test_lpd_dnssd_and_lpd_schemes_merge():
    """Alex regression test: dnssd://..._printer._tcp.local/?uuid=UUID and
    lpd://..._printer._tcp.local/ must resolve to the SAME PhysicalDevice,
    canonicalize to the appropriate LPD connection representation, and
    UUID differences must not create another PhysicalDevice.
    Also tests discovery order both ways."""
    uuid1 = "cbca9fde-d208-4156-9a2f-82857dd0be5f"
    uuid2 = "12345678-abcd-ef01-2345-6789abcdef01"

    # 1. Forward order: dnssd first, then lpd
    dev_dnssd = _make_dnssd_device(
        f'dnssd://OpenPrinting%20LPD%20Printer._printer._tcp.local/?uuid={uuid1}',
        make_and_model='OpenPrinting LPD Printer',
        device_id='MFG:OpenPrinting;MDL:LPD Printer;')
    dev_lpd = _make_dnssd_device(
        'lpd://OpenPrinting%20LPD%20Printer._printer._tcp.local/',
        make_and_model='OpenPrinting LPD Printer',
        device_id='MFG:OpenPrinting;MDL:LPD Printer;')

    phys_dnssd = PhysicalDevice(dev_dnssd)
    phys_lpd = PhysicalDevice(dev_lpd)
    assert phys_dnssd == phys_lpd

    # Merging via grouping loop
    pds = []
    for d in [dev_dnssd, dev_lpd]:
        pd = PhysicalDevice(d)
        try:
            i = pds.index(pd)
            pds[i].add_device(d)
        except ValueError:
            pds.append(pd)

    assert len(pds) == 1
    devices = pds[0].get_devices()
    assert len(devices) == 1
    assert devices[0].uri == 'lpd://OpenPrinting%20LPD%20Printer._printer._tcp.local/'
    assert devices[0].type == 'lpd'

    # 2. Reverse order: lpd first, then dnssd
    dev_dnssd_rev = _make_dnssd_device(
        f'dnssd://OpenPrinting%20LPD%20Printer._printer._tcp.local/?uuid={uuid1}',
        make_and_model='OpenPrinting LPD Printer',
        device_id='MFG:OpenPrinting;MDL:LPD Printer;')
    dev_lpd_rev = _make_dnssd_device(
        'lpd://OpenPrinting%20LPD%20Printer._printer._tcp.local/',
        make_and_model='OpenPrinting LPD Printer',
        device_id='MFG:OpenPrinting;MDL:LPD Printer;')

    pds_rev = []
    for d in [dev_lpd_rev, dev_dnssd_rev]:
        pd = PhysicalDevice(d)
        try:
            i = pds_rev.index(pd)
            pds_rev[i].add_device(d)
        except ValueError:
            pds_rev.append(pd)

    assert len(pds_rev) == 1
    devices_rev = pds_rev[0].get_devices()
    assert len(devices_rev) == 1
    assert devices_rev[0].uri == 'lpd://OpenPrinting%20LPD%20Printer._printer._tcp.local/'
    assert devices_rev[0].type == 'lpd'

    # 3. UUID differences do not create another PhysicalDevice
    dev_dnssd_diff_uuid = _make_dnssd_device(
        f'dnssd://OpenPrinting%20LPD%20Printer._printer._tcp.local/?uuid={uuid2}',
        make_and_model='OpenPrinting LPD Printer',
        device_id='MFG:OpenPrinting;MDL:LPD Printer;')

    phys_diff_uuid = PhysicalDevice(dev_dnssd_diff_uuid)
    assert phys_dnssd == phys_diff_uuid
    pds[0].add_device(dev_dnssd_diff_uuid)
    assert len(pds[0].get_devices()) == 1


@pytest.mark.skipif(cups is None, reason="cups module not available")
def test_appsocket_dnssd_and_socket_schemes_merge():
    """Alex regression test: dnssd://..._pdl-datastream._tcp.local/?uuid=UUID and
    socket://..._pdl-datastream._tcp.local/ must resolve to the SAME PhysicalDevice,
    canonicalize to the appropriate AppSocket connection representation.
    Also tests discovery order both ways."""
    uuid = "cbca9fde-d208-4156-9a2f-82857dd0be5f"

    # Forward order
    dev_dnssd = _make_dnssd_device(
        f'dnssd://OpenPrinting%20AppSocket%20Printer._pdl-datastream._tcp.local/?uuid={uuid}',
        make_and_model='OpenPrinting AppSocket Printer',
        device_id='MFG:OpenPrinting;MDL:AppSocket Printer;')
    dev_socket = _make_dnssd_device(
        'socket://OpenPrinting%20AppSocket%20Printer._pdl-datastream._tcp.local/',
        make_and_model='OpenPrinting AppSocket Printer',
        device_id='MFG:OpenPrinting;MDL:AppSocket Printer;')

    phys_dnssd = PhysicalDevice(dev_dnssd)
    phys_socket = PhysicalDevice(dev_socket)
    assert phys_dnssd == phys_socket

    pds = []
    for d in [dev_dnssd, dev_socket]:
        pd = PhysicalDevice(d)
        try:
            i = pds.index(pd)
            pds[i].add_device(d)
        except ValueError:
            pds.append(pd)

    assert len(pds) == 1
    devices = pds[0].get_devices()
    assert len(devices) == 1
    assert devices[0].uri == 'socket://OpenPrinting%20AppSocket%20Printer._pdl-datastream._tcp.local/'
    assert devices[0].type == 'socket'

    # Reverse order
    dev_dnssd_rev = _make_dnssd_device(
        f'dnssd://OpenPrinting%20AppSocket%20Printer._pdl-datastream._tcp.local/?uuid={uuid}',
        make_and_model='OpenPrinting AppSocket Printer',
        device_id='MFG:OpenPrinting;MDL:AppSocket Printer;')
    dev_socket_rev = _make_dnssd_device(
        'socket://OpenPrinting%20AppSocket%20Printer._pdl-datastream._tcp.local/',
        make_and_model='OpenPrinting AppSocket Printer',
        device_id='MFG:OpenPrinting;MDL:AppSocket Printer;')

    pds_rev = []
    for d in [dev_socket_rev, dev_dnssd_rev]:
        pd = PhysicalDevice(d)
        try:
            i = pds_rev.index(pd)
            pds_rev[i].add_device(d)
        except ValueError:
            pds_rev.append(pd)

    assert len(pds_rev) == 1
    devices_rev = pds_rev[0].get_devices()
    assert len(devices_rev) == 1
    assert devices_rev[0].uri == 'socket://OpenPrinting%20AppSocket%20Printer._pdl-datastream._tcp.local/'
    assert devices_rev[0].type == 'socket'


@pytest.mark.skipif(cups is None, reason="cups module not available")
def test_network_printer_protocols_separation():
    """Verify that OpenPrinting LPD, OpenPrinting AppSocket, and two different
    AppSocket printer names remain separate PhysicalDevices."""
    dev_lpd = _make_dnssd_device(
        'dnssd://OpenPrinting%20LPD%20Printer._printer._tcp.local/?uuid=111',
        make_and_model='OpenPrinting LPD Printer',
        device_id='MFG:OpenPrinting;MDL:LPD Printer;')
    dev_appsocket = _make_dnssd_device(
        'dnssd://OpenPrinting%20AppSocket%20Printer._pdl-datastream._tcp.local/?uuid=222',
        make_and_model='OpenPrinting AppSocket Printer',
        device_id='MFG:OpenPrinting;MDL:AppSocket Printer;')
    dev_appsocket2 = _make_dnssd_device(
        'socket://Another%20AppSocket%20Printer._pdl-datastream._tcp.local/',
        make_and_model='Another AppSocket Printer',
        device_id='MFG:Another;MDL:AppSocket Printer;')

    p_lpd = PhysicalDevice(dev_lpd)
    p_appsocket = PhysicalDevice(dev_appsocket)
    p_appsocket2 = PhysicalDevice(dev_appsocket2)

    assert p_lpd != p_appsocket
    assert p_lpd != p_appsocket2
    assert p_appsocket != p_appsocket2

    pds = []
    for d in [dev_lpd, dev_appsocket, dev_appsocket2]:
        pd = PhysicalDevice(d)
        try:
            i = pds.index(pd)
            pds[i].add_device(d)
        except ValueError:
            pds.append(pd)

    assert len(pds) == 3

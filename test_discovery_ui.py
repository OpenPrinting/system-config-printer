"""Discovery-page interaction tests with real GTK and no CUPS/discovery I/O."""
from unittest.mock import MagicMock
import gi
import pytest

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
import newprinter
import cupshelpers


@pytest.fixture
def ui(monkeypatch):
    gui = newprinter.NewPrinterGUI()
    gui.start_fetching_devices = MagicMock()
    gui.check_firewall = MagicMock()
    connection = MagicMock()
    connection.adminGetServerSettings.return_value = {}
    monkeypatch.setattr(newprinter.authconn, 'Connection', lambda **kwargs: connection)
    monkeypatch.setattr(newprinter.cupshelpers, 'getPrinters', lambda *args: {})
    assert gui.init('printer', host='localhost')
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    yield gui
    for window in Gtk.Window.list_toplevels():
        window.destroy()


def device(uri, serial='A', kind='network'):
    return cupshelpers.Device(uri, **{'device-class': kind,
        'device-make-and-model': 'Example Printer',
        'device-id': 'MFG:Example;MDL:Printer;SN:%s;' % serial})


def select(ui, uri):
    model = ui.tvNPDevices.get_model()
    paths = []
    def visit(model, path, it, data):
        physical = model.get_value(it, 1)
        if physical and any(d.uri == uri for d in physical.get_devices()):
            paths.append(path.copy())
        return False
    model.foreach(visit, None)
    assert len(paths) == 1
    ui.tvNPDevices.expand_to_path(paths[0])
    ui.tvNPDevices.set_cursor(paths[0])
    return paths[0]


def test_initial_manual_category_collapsed_and_no_selection(ui):
    model = ui.tvNPDevices.get_model()
    assert not ui.tvNPDevices.row_expanded(model.get_path(ui.devices_network_iter))
    assert model.get_value(ui.devices_uri_iter, 0) == "Enter printer URI"
    first_manual = model.iter_children(ui.devices_network_iter)
    assert model.get_value(first_manual, 0) == "Find by address"
    assert ui.tvNPDevices.get_selection().get_selected()[1] is None
    assert ui.device is None
    assert ui.getDeviceURI() == ''
    assert not ui.btnNPForward.get_sensitive()
    assert not ui.expConnectionDetails.get_visible()


def test_arriving_usb_and_network_do_not_select_or_expand_manual(ui):
    records = [device('usb://Example/Printer?serial=A', kind='direct'),
               device('ipp://192.0.2.11/ipp/print', 'B')]
    ui.add_devices({d.uri:d for d in records}, None, no_more=True)
    model = ui.tvNPDevices.get_model()
    assert model.iter_n_children(None) == 3
    assert not ui.tvNPDevices.row_expanded(model.get_path(ui.devices_network_iter))
    assert ui.device is None
    assert not ui.btnNPForward.get_sensitive()
    assert ui.btnSearchAgain.get_sensitive()
    assert '2' in ui.lblDiscoveryStatus.get_text()


def test_manual_uri_validation_preserved(ui):
    select(ui, '')
    assert ui.expConnectionDetails.get_visible()
    assert ui.expConnectionDetails.get_expanded()
    ui.entNPTDevice.set_text('not-a-uri')
    assert not ui.btnNPForward.get_sensitive()
    ui.entNPTDevice.set_text('ipp://printer.example.test/ipp/print')
    assert ui.btnNPForward.get_sensitive()
    assert ui.getDeviceURI() == 'ipp://printer.example.test/ipp/print'


def test_refresh_preserves_selected_connection(ui):
    records = [device('ipp://192.0.2.10/ipp/print'), device('socket://192.0.2.10')]
    ui.add_devices({d.uri:d for d in records}, None, no_more=True)
    select(ui, records[0].uri)
    assert not ui.expConnectionDetails.get_expanded()
    connections = ui.tvNPDeviceURIs.get_model()
    for row in connections:
        if row[1].type == 'socket':
            ui.tvNPDeviceURIs.set_cursor(connections.get_path(row.iter))
    chosen = ui.device.uri
    model = ui.tvNPDevices.get_model()
    ui.on_search_again_clicked(ui.btnSearchAgain)
    assert ui.tvNPDevices.get_model() is model
    assert not ui.btnSearchAgain.get_sensitive()
    ui.add_devices({d.uri:d for d in records}, None, no_more=True)
    assert ui.device.uri == chosen
    assert ui.btnSearchAgain.get_sensitive()


def test_failure_with_buffered_devices_stays_failure(ui):
    printer = device('usb://Example/Printer?serial=A', kind='direct')
    ui.fetchDevices_conn = MagicMock()
    ui._pending_devices = {printer.uri:printer}
    ui.error_getting_devices(None, RuntimeError('fixture'))
    assert 'Could not search' in ui.lblDiscoveryStatus.get_text()
    assert ui.btnSearchAgain.get_sensitive()
    assert ui.tvNPDevices.get_model().iter_n_children(None) == 2


def test_address_search_result_is_in_main_list(ui):
    ui.network_found = 0
    ui.found_network_printer_callback(device('ipp://192.0.2.10/ipp/print'))
    model = ui.tvNPDevices.get_model()
    selected = ui.tvNPDevices.get_cursor()[0]
    assert selected.get_depth() == 1
    assert model.iter_n_children(None) == 2


def test_driver_progress_visible_without_opening_methods(ui):
    printer = device('ipp://192.0.2.10/ipp/print')
    ui.add_devices({printer.uri:printer}, None, no_more=True)
    select(ui, printer.uri)
    ui._show_searching_spinner('Searching for drivers')
    assert ui.lblDiscoveryStatus.get_text() == 'Searching for drivers'
    assert ui.discoveryProgress.get_visible()
    assert not ui.expConnectionDetails.get_expanded()
    assert not ui.btnSearchAgain.get_sensitive()
    ui._hide_searching_spinner()
    assert not ui.discoveryProgress.get_visible()
    assert ui.btnSearchAgain.get_sensitive()


def test_connection_selector_precedes_protocol_settings(ui):
    parent = ui.expNPDeviceURIs.get_parent()
    assert parent.get_children()[0] is ui.expNPDeviceURIs


@pytest.mark.parametrize('mode', ['printer_with_uri', 'ppd'])
def test_supplied_uri_preserved_before_device_reconstruction(ui, mode):
    ui.dialog_mode = mode
    ui._device_uri = 'ipp://192.0.2.10/printers/existing'
    ui.device = None
    assert ui.getDeviceURI() == ui._device_uri


def test_discovery_callbacks_ignored_after_cancel_and_reopen(ui, monkeypatch):
    callbacks = {}
    monkeypatch.setattr(newprinter.cupshelpers, 'getDevices',
        lambda conn, **kwargs: callbacks.update(kwargs))
    ui.fetchDevices_conn = MagicMock()
    ui.fetchDevices(network=False)
    ui.on_NPCancel(None)
    ui.fillDeviceTab()
    ui.local_devices_reply = MagicMock()
    callbacks['reply_handler'](None, {})
    callbacks['error_handler'](None, RuntimeError('late'))
    ui.local_devices_reply.assert_not_called()
    assert ui._pending_devices is None


def test_dnssd_callback_ignored_after_cancel(ui, monkeypatch):
    captured = {}
    resolver = MagicMock()
    resolver.resolve.side_effect = lambda **kwargs: captured.update(kwargs)
    monkeypatch.setattr(newprinter.dnssdresolve, 'DNSSDHostNamesResolver', lambda devices: resolver)
    ui.fetchDevices_conn = MagicMock()
    printer = device('ipp://Example._ipp._tcp.local/')
    ui.network_devices_reply(None, {printer.uri:printer}, None)
    ui.on_NPCancel(None)
    ui.fillDeviceTab()
    captured['reply_handler']({printer.uri:printer})
    assert ui.tvNPDevices.get_model().iter_n_children(None) == 1


def test_forward_during_refresh_allows_search_after_back(ui):
    printer = device('usb://Example/Printer?serial=A', kind='direct')
    ui.add_devices({printer.uri:printer}, None, no_more=True)
    select(ui, printer.uri)
    ui.on_search_again_clicked(ui.btnSearchAgain)
    ui.fetchDevices_conn = MagicMock()
    ui._selectDeviceForInstallation(printer.uri)
    assert not ui._discovery_searching
    assert ui.btnSearchAgain.get_sensitive()


def test_superseded_selected_usb_requires_new_selection(ui):
    old = device('usb://Example/Printer?serial=A', kind='direct')
    ui.add_devices({old.uri:old}, None, no_more=True)
    select(ui, old.uri)
    replacement = device('ipp://Example._ipp._tcp.local/')
    replacement.address = '127.0.0.1'
    ui.add_devices({replacement.uri:replacement}, None, no_more=True)
    assert ui.device is None
    assert not ui.btnNPForward.get_sensitive()
    assert not ui.expConnectionDetails.get_visible()


def test_explicit_address_result_updates_empty_summary(ui):
    ui.add_devices({}, None, no_more=True)
    assert 'No printers' in ui.lblDiscoveryStatus.get_text()
    ui.network_found = 0
    ui.found_network_printer_callback(device('ipp://192.0.2.10/ipp/print'))
    ui.found_network_printer_callback(None)
    assert '1 printer found' in ui.lblDiscoveryStatus.get_text()


def test_manual_category_opens_only_on_explicit_activation(ui):
    model = ui.tvNPDevices.get_model()
    path = model.get_path(ui.devices_network_iter)
    assert not ui.device_select_function(None, model, path)
    assert not ui.tvNPDevices.row_expanded(path)
    ui.device_row_activated(ui.tvNPDevices, path, None)
    assert ui.tvNPDevices.row_expanded(path)


@pytest.mark.parametrize('uri', ['serial:/dev/ttyS0?baud=9600', 'parallel:/dev/lp0'])
def test_legacy_ports_stay_manual(ui, uri):
    port = device(uri, kind='direct')
    ui.add_devices({uri:port}, None, no_more=True)
    assert ui.tvNPDevices.get_model().iter_n_children(None) == 1
    assert 'No printers' in ui.lblDiscoveryStatus.get_text()
    path = select(ui, uri)
    assert path.get_depth() == 2
    assert ui.expConnectionDetails.get_expanded()


def test_smb_manual_form_remains_available(ui):
    select(ui, 'smb')
    assert ui.expConnectionDetails.get_expanded()
    assert ui.ntbkNPType.get_current_page() == ui.new_printer_device_tabs['smb']
    assert not ui.expNPDeviceURIs.get_visible()


def test_plural_count_uses_application_translation_domain(ui, monkeypatch):
    translate = MagicMock(return_value='%d printers')
    monkeypatch.setattr(newprinter.gettext, 'dngettext', translate)
    printer = device('ipp://192.0.2.10/ipp/print')
    ui.add_devices({printer.uri:printer}, None, no_more=True)
    assert translate.call_args[0][0] == newprinter.config.PACKAGE


def test_address_search_ignores_queued_result_from_old_finder(ui, monkeypatch):
    finders = [MagicMock(), MagicMock()]
    monkeypatch.setattr(newprinter.probe_printer, 'PrinterFinder',
                        lambda: finders.pop(0))
    queued = []
    monkeypatch.setattr(newprinter.GLib, 'idle_add',
                        lambda callback, *args: queued.append((callback, args)))
    ui.entNPTNetworkHostname.set_text('printer.example')
    ui.on_btnNetworkFind_clicked(None)
    old = ui.printer_finder
    old.find.call_args[0][1](device('ipp://192.0.2.20/ipp/print'))
    ui.on_NPCancel(None)
    ui.fillDeviceTab()
    ui.on_btnNetworkFind_clicked(None)
    current = ui.printer_finder
    delivery, args = queued[-1]
    assert delivery(*args) is False
    assert ui.printer_finder is current
    assert ui.network_found == 0
    assert ui.tvNPDevices.get_model().iter_n_children(None) == 1


def settle_layout():
    import time
    deadline = time.monotonic() + 0.25
    while time.monotonic() < deadline:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.01)


def test_compact_discovery_and_expanded_description_not_clipped(ui):
    settle_layout()
    scroller = ui.tvNPDevices.get_parent()
    assert scroller.get_preferred_height().natural_height <= 182
    records = [device('ipp://192.0.2.10/ipp/print'),
               device('socket://192.0.2.10')]
    ui.add_devices({d.uri: d for d in records}, None, no_more=True)
    select(ui, records[0].uri)
    ui.expConnectionDetails.set_expanded(True)
    settle_layout()
    scroll = ui.expConnectionDetails.get_child()
    label = ui.lblNPDeviceDescription
    assert label.get_mapped()
    _, y = label.translate_coordinates(scroll, 0, 0)
    assert y >= 0
    assert y + label.get_allocated_height() <= scroll.get_allocated_height()


def test_protocol_switches_keep_indices_and_conditional_children(ui):
    records = [device('ipp://192.0.2.10/ipp/print'),
               device('serial:/dev/ttyS0?baud=9600', kind='direct')]
    ui.add_devices({d.uri: d for d in records}, None, no_more=True)
    pages = [ui.ntbkNPType.get_nth_page(i)
             for i in range(ui.ntbkNPType.get_n_pages())]
    for uri in ['smb', records[0].uri, records[1].uri, 'smb']:
        select(ui, uri)
        current = ui.ntbkNPType.get_current_page()
        assert [p.get_visible() for p in pages] == [
            i == current for i in range(len(pages))]
        assert all(ui.ntbkNPType.get_nth_page(i) is p
                   for i, p in enumerate(pages))
    child = ui.entSMBUsername
    child.hide()
    select(ui, records[0].uri)
    select(ui, 'smb')
    assert not child.get_visible()


def test_wizard_pages_preserve_fields_and_indices(ui):
    ui.entNPName.set_text('Preserved-name')
    for page in [ui.PAGE_DESCRIBE_PRINTER, ui.PAGE_SELECT_DEVICE,
                 ui.PAGE_SELECT_INSTALL_METHOD, ui.PAGE_SELECT_DEVICE]:
        ui._select_notebook_page(ui.ntbkNewPrinter, page)
        assert ui.ntbkNewPrinter.get_current_page() == page
        assert sum(ui.ntbkNewPrinter.get_nth_page(i).get_visible()
                   for i in range(ui.ntbkNewPrinter.get_n_pages())) == 1
    assert ui.entNPName.get_text() == 'Preserved-name'

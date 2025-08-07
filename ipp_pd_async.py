import dbus
import dbus.mainloop.glib
import gi
from gi.repository import GLib
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
import avahi

SERVICE_TYPES = [
    "_http._tcp", "_https._tcp"
    # "_ipp._tcp", "_ipps-system._tcp", 
    # "_nvstream._tcp", "_nvstream_dbd._tcp", "_airplay._tcp", "_raop._tcp"
]

class AvahiServiceBrowser:
    def __init__(self):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.discovered_services = []  # List to store unique discovered services

    def get_all_discovered_services(self):
        return self.discovered_services

    def on_service_found(self, interface, protocol, name, stype, domain, adminurl=None):
        # Check for duplicates before adding
        if not any(service['name'] == name and service['link'] == adminurl for service in self.discovered_services):
            print(f"Service found: {name}, type: {stype}, domain: {domain}, admin URL: {adminurl}")
            service_info = {
                "name": name,
                "link": adminurl
            }
            self.discovered_services.append(service_info)

    def resolve_service(self, interface, protocol, name, stype, domain, flags):
        server = self.bus.get_object(avahi.DBUS_NAME, avahi.DBUS_PATH_SERVER)
        
        try:
            # Resolve the service to obtain its host and port
            resolved = server.ResolveService(
                interface, protocol, name, stype, domain,
                avahi.PROTO_UNSPEC, dbus.UInt32(0),
                dbus_interface=avahi.DBUS_INTERFACE_SERVER
            )
            
            # Construct the admin URL
            host = resolved[5]  # The resolved hostname
            port = resolved[8]  # The resolved port
            adminurl = f"http://{host}:{port}"
            
            # Pass all information to `on_service_found`
            self.on_service_found(interface, protocol, name, stype, domain, adminurl)
        
        except dbus.DBusException as e:
            print(f"Failed to resolve service {name}: {e}")

    def get_services(self, service_type):
        try:
            server = dbus.Interface(
                self.bus.get_object(avahi.DBUS_NAME, avahi.DBUS_PATH_SERVER),
                avahi.DBUS_INTERFACE_SERVER
            )
            sbrowser = dbus.Interface(
                self.bus.get_object(avahi.DBUS_NAME, server.ServiceBrowserNew(
                    avahi.IF_UNSPEC, avahi.PROTO_UNSPEC, service_type, 'local', dbus.UInt32(0))),
                avahi.DBUS_INTERFACE_SERVICE_BROWSER
            )
            # Connect ItemNew to resolve service when a new item is found
            sbrowser.connect_to_signal("ItemNew", self.resolve_service)
            print(f"Started service browser for: {service_type}")
        
        except dbus.DBusException as e:
            print(f"DBusException: {e}")

    def run(self):
        for service_type in SERVICE_TYPES:
            self.get_services(service_type)
        loop = GLib.MainLoop()
        loop.run()

if __name__ == "__main__":
    browser = AvahiServiceBrowser()
    browser.run()


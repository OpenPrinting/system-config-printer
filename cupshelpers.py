#!/bin/env python
import cups

class Printer:

    printer_states = { cups.IPP_PRINTER_IDLE: "Idle",
                       cups.IPP_PRINTER_PROCESSING: "Processing",
                       cups.IPP_PRINTER_BUSY: "Busy",
                       cups.IPP_PRINTER_STOPPED: "Stopped" }

    def __init__(self, name, **kw):
        self.name = name
        self.class_members = []
        self.device_uri = kw.get('device-uri', "")
        self.info = kw.get('printer-info', "")
        self.is_shared = kw.get('printer-is-shared', None)
        self.location = kw.get('printer-location', "")
        self.make_and_model = kw.get('printer-make-and-model', "")
        self.state = kw.get('printer-state', 0)
        self.type = kw.get('printer-type', 0)
        self.uri_supported = kw.get('printer-uri-supported', "")
        self._expand_flags()

        self.state_description = self.printer_states.get(
            self.state, "Unknown")


        if self.is_shared is None:
            self.is_shared = not self.not_shared
        del self.not_shared

    _flags_blacklist = ["options", "local"]

    def _expand_flags(self):
        prefix = "CUPS_PRINTER_"
        prefix_length = len(prefix)
        # loop over cups constants
        for name in cups.__dict__:
            if name.startswith(prefix):
                attr_name = name[prefix_length:].lower()
                if attr_name in self._flags_blacklist: continue
                if attr_name == "class": attr_name = "is_class"
                # set as attribute
                setattr(self, attr_name,
                        bool(self.type & getattr(cups, name)))

    def getServer(self):
        """return Server URI or None"""
        if (not self.remote or
            not self.uri_supported.startswith('ipp://')):
            return None
        uri = self.uri_supported[6:]
        uri = uri.split('/')[0]
        uri = uri.split(':')[0]
        return uri
        
def getPrinters(connection):
    printers = connection.getPrinters()
    classes = connection.getClasses()
    for name, printer in printers.iteritems():
        printer = Printer(name, **printer)
        printers[name] = printer
        if classes.has_key(name):
            printer.class_members = classes[name]
            printer.class_members.sort()
    return printers

class Device:

    prototypes = {
        'ipp' : "ipp://%s"
        }

    def __init__(self, uri, **kw):
        self.uri = uri
        self.device_class = kw.get('device-class', 'Unknown') # XXX better default
        self.info = kw.get('device-info', '')
        self.make_and_model = kw.get('device-make-and-model', 'Unknown')
        self.id = kw.get('device-id', '')

        uri_pieces = uri.split(":")[0] 

        self.type =  uri_pieces[0]
        self.is_class = len(uri_pieces)==1 
        

def getDevices(connection):
    devices = connection.getDevices()
    for uri, data in devices.iteritem():
        device = Device(uri, data)
        devices[uri] = device
    return devices
    
def main():
    c = cups.Connection()
    printers = getPrinters(c)

    for name in cups.__dict__:
        if name.startswith("CUPS_PRINTER_"):
            print name, "%x" % getattr(cups, name)


if __name__=="__main__":
    main()

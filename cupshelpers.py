#!/bin/env python
import cups, pprint

class Printer:

    printer_states = { cups.IPP_PRINTER_IDLE: "Idle",
                       cups.IPP_PRINTER_PROCESSING: "Processing",
                       cups.IPP_PRINTER_BUSY: "Busy",
                       cups.IPP_PRINTER_STOPPED: "Stopped" }

    def __init__(self, name, connection, **kw):
        self.name = name
        self.connection = connection
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

        self._getAttributes()

        self.enabled = self.state != cups.IPP_PRINTER_STOPPED

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

    def _getAttributes(self):
        attrs = self.connection.getPrinterAttributes(self.name)

        self.job_sheet_start, self.job_sheet_end = attrs.get(
            'job-sheets-default', ('none', 'none'))
        self.job_sheets_supported = attrs.get('job-sheets-supported', ['none'])
        self.error_policy = attrs.get('printer-error-policy', 'none')
        self.error_policy_supported = attrs.get(
            'printer-error-policy-supported', ['none'])
        self.op_policy = attrs.get('printer-op-policy', "") or "default"
        self.op_policy_supported = attrs.get(
            'printer-op-policy-supported', ["default"])

        self.default_allow = True
        self.except_users = []
        if attrs.has_key('requesting-user-name-allowed'):
            self.except_users = attrs['requesting-user-name-allowed']
            self.default_allow = False
        elif attrs.has_key('requesting-user-name-denied'):
            self.except_users = attrs['requesting-user-name-denied']
        self.except_users_string = ', '.join(self.except_users)

    def getServer(self):
        """return Server URI or None"""
        if not self.uri_supported.startswith('ipp://'):
            return None
        uri = self.uri_supported[6:]
        uri = uri.split('/')[0]
        uri = uri.split(':')[0]
        if uri == "localhost.localdomain":
            uri = "localhost"
        return uri

    def setEnabled(self, on):
        if on:
            self.connection.enablePrinter(self.name)
        else:
            self.connection.disablePrinter(self.name)

    def setAccepting(self, on):
        if on:
            self.connection.acceptJobs(self.name)
        else:
            self.connection.rejectJobs(self.name)

    def setShared(self,on):
        self.connection.setPrinterShared(self.name, on)

    def setErrorPolicy (self, policy):
        self.connection.setPrinterErrorPolicy(self.name, policy)

    def setOperationPolicy(self, policy):
        self.connection.setPrinterOpPolicy(self.name, policy)    

    def setJobSheets(self, start, end):
        self.connection.setPrinterJobSheets(self.name, start, end)

    def setAccess(self, allow, except_users):
        if isinstance(except_users, str):
            users = except_users.split()
            users = [u.split(",") for u in users]
            except_users = []
            for u in users:
                except_users.extend(u)
            except_users = [u.strip() for u in except_users]
            except_users = filter(None, except_users)
            
        if allow:
            self.connection.setPrinterUsersDenied(self.name, except_users)
        else:
            self.connection.setPrinterUsersAllowed(self.name, except_users)

def getPrinters(connection):
    printers = connection.getPrinters()
    classes = connection.getClasses()
    for name, printer in printers.iteritems():
        printer = Printer(name, connection, **printer)
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

        uri_pieces = uri.split(":")
        self.type =  uri_pieces[0]
        self.is_class = len(uri_pieces)==1 

        self.id_dict = {}
        pieces = self.id.split(";")
        for piece in pieces:
            if not piece: continue
            name, value = piece.split(":",1)
            if name=="CMD":
                value = value.split(',') 
            self.id_dict[name] = value

    def __cmp__(self, other):
        result = cmp(self.is_class, other.is_class)
        if not result:
            result = cmp(bool(self.id), bool(other.id))
        if not result:
            result = cmp(self.info, other.info)
        
        return result

def getDevices(connection):
    devices = connection.getDevices()
    for uri, data in devices.iteritems():
        device = Device(uri, **data)
        devices[uri] = device
    return devices
    
def main():
    c = cups.Connection()
    #printers = getPrinters(c)
    for device in getDevices(c).itervalues():
        print device.uri, device.id_dict

if __name__=="__main__":
    main()

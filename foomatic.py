#!/bin/env python

import os, signal
from xml.utils import qp_xml

class FoomaticXMLFile:

    def __init__(self, name, foomatic):
        self.name = name
        self.foomatic = foomatic

    def parse_lang_tree(self, node):
        ret = {}
        for lang in node.children:
            ret[lang.name] = lang.first_cdata
        return ret

    def read(self):
        root_node = qp_xml.Parser().parse(open(self.filename))
        self.parse_xml(root_node)
        

class Driver(FoomaticXMLFile):
    """
    Attributes:

     name : String
     id : String 'driver/name'
     filename : String
     url : String
     comments : dict lang -> text
     printers : list of id strings

     foomatic : Foomatic

    """
    def __init__(self, name, foomatic):
        self.filename = os.path.join(foomatic.path, 'driver',
                                     foomatic.quote_filename(name))
        FoomaticXMLFile.__init__(self, name, foomatic)


    def parse_xml(self, root_node):
        self.printers = []

        if root_node.name != "driver":
            raise ValueError, "'driver' node expected"

        self.id = root_node.attrs.get(('', u'id'), None)
        if self.id:
            self.name = self.id[len('driver/'):]
            self.filename = os.path.join(
                self.foomatic.path, 'driver',
                self.foomatic.quote_filename(self.name))
        
        for node in root_node.children:
            if node.name in ("name", "url"):
                setattr(self, node.name, node.first_cdata)
            elif node.name == "comments":
                self.comments_dict = self.parse_lang_tree(node)
            elif node.name == "printers":
                for sub_node in node.children:
                    if sub_node.name == "printer":
                        for sub_sub_node in sub_node.children:
                            if sub_sub_node.name == "id":
                                self.printers.append(sub_sub_node.first_cdata)
                            elif sub_sub_node.name == "comments":
                                pass # XXX
            #elif node.name == 'execution':
            # XXX

class Printer(FoomaticXMLFile):
    """
    Attributes:

     name : String
     id : String 'printer/name'
     filename : String
     make, model, functionality : String
     drivers : list of driver names
     autodetect : dict with keys 'snmp', 'parallel', 'usb', 'general'
        -> dict with keys 'ieee1284', 'manufacturer', 'model',
                          'description', 'commandset'     
     unverified : Bool
     foomatic : Foomatic
    """

    def __init__(self, name, foomatic):
        self.filename = os.path.join(foomatic.path, 'printer',
                                     foomatic.quote_filename(name))
        FoomaticXMLFile.__init__(self, name, foomatic)


    def parse_autodetect(self, root_node):
        data = { }
        for node in root_node.children:
            if node.name in ('ieee1284', 'manufacturer', 'model',
                             'description', 'commandset'):
                if node.first_cdata != "(see notes)":
                    data[node.name] = node.first_cdata
        return data

    def parse_xml(self, root_node):

        if root_node.name != "printer":
            raise ValueError, "'printer' node expected"

        self.id = root_node.attrs.get(('', u'id'),None)
        
        self.unverified = False
        self.functionality = None
        self.drivers = []
        self.autodetect = {}

        for child in root_node.children:
            if child.name in ("id", "make", "model",
                              "functionality"):
                setattr(self, child.name, child.first_cdata)
    
            elif child.name == "drivers":
                for sub_child in child.children:
                    if (sub_child.name == "driver" and
                        len (sub_child.first_cdata.strip())):
                        self.drivers.append(sub_child.first_cdata)

            elif (child.name == "driver" and
                  len (child.first_cdata.strip())):
                self.drivers.append(child.first_cdata)
    
            elif child.name == "autodetect":
                for sub_child in child.children:
                    if (sub_child.name in ("snmp", "parallel",
                                           "usb","general")):
                        self.autodetect[sub_child.name] = \
                          self.parse_autodetect(sub_child)
            elif child.name == "unverified":
                self.unverified = True
                
        if self.id:
            if self.id.startswith('printer/'):                
                self.name = self.id[len('printer/'):]
            else:
                self.name = self.id
                self.id = 'printer/' + self.id
            self.filename = os.path.join(
                self.foomatic.path, 'driver',
                self.foomatic.quote_filename(self.name))

class CupsPrinter:
    """
    Attributes:

     name : String
     id : String 'printer/name'
     filename : String
     make, model, functionality : String
     drivers : list of driver names
     autodetect : dict with keys 'snmp', 'parallel', 'usb', 'general'
        -> dict with keys 'ieee1284', 'manufacturer', 'model',
                          'description', 'commandset'     
     unverified : Bool
     foomatic : Foomatic
    """

    def __init__(self, name, foomatic, ppd):
        self.name = name

        self.make, self.model = ppd['ppd-make-and-model'].split(' ', 1)
        self.functionality = ''
        self.drivers = []
        self.autoddetect = {}
        self.unverified = False
        
        self.foomatic = foomatic

    

class Foomatic:

    def __init__(self):
        self.path = '/usr/share/foomatic/db/source'
        self.foomatic_configure = "/usr/bin/foomatic-configure"

        self._printer_names = None
        self._driver_names = None
        self._printers = {}
        self._drivers = {}

        self._makers = {}

        
    def quote_filename(self, name):
        return name + '.xml'
    
    def unquote_filename(self, file):
        return file.replace('.xml', '')


    def _add_printer(self, printer):
        printers = self._makers.setdefault(printer.make, {})
        printers[printer.name] = printer

        printers = self._makers.setdefault(printer.make.lower(), {})
        printers[printer.name.lower()] = printer
        
    def _read_all_printers(self):

        self._printer_names = []
        self._printers = {}

        parser = qp_xml.Parser()
        signal.signal (signal.SIGCHLD, signal.SIG_DFL)
        raw_xml = os.popen ("%s -O" % (self.foomatic_configure))
        root = qp_xml.Parser().parse(raw_xml)
        raw_xml.close ()
        
        for node in root.children:
            if node.name == "printer":
                printer = Printer("", self)
                printer.parse_xml(node)
                self._printers[printer.name] = printer
                self._printer_names.append(printer.name)
                self._add_printer(printer)
            elif node.name == "driver":
                driver = Driver('', self)
                driver.parser_xml(node)
                self._drivers[driver.name] = driver
                self._driver_names.append(driver)

        self._printer_names.sort()

    # ----

    def addCupsPDDs(self, connection):
        ppds = connection.getPPDs
        for name, ppd in ppds.iteritems():
            
            ppd['file-name'] = name
            self.makemodel[ppd['ppd-make-and-model']] = ppd
    # ----

    def load_all(self):
        # XXX do pickling
        self._read_all_printers()

    # ----

    def get_printers(self):
        if self._printer_names is None:
            filenames = os.listdir(os.path.join(self.path, 'printer'))
            self._printer_names = [self.unquote_filename(name)
                                   for name in filenames]
            self._printer_names.sort()
        return self._printer_names
        
    # ----

    def get_drivers(self):
        if self._driver_names is None:
            filenames = os.listdir(os.path.join(self.path, 'driver'))
            self._driver_names = [self.unquote_filename(name)
                                  for name in filenames]
            self._driver_names.sort()
        return self._driver_names

    # ----

    def get_printer(self, name):
        if not self._printers.has_key(name):
            printer = Printer(name, self)
            printer.read()
            self._printers[name] = printer
            self._add_printer(printer)
        return self._printers[name]

    def get_driver(self, name):
        if not self._drivers.has_key(name):
            self._drivers[name] = Driver(name, self)
            self._drivers[name].read()
        return self._drivers[name]

    def getMakeModelFromName(self, name):
        make , model = name.split('-', 1)
        model = model.replace('_', ' ')
        return make, model

    def getPPD(self, printer):
        return

def main():
    foo = Foomatic()

    foo._read_all_printers()
    for name in foo.get_printers():
        #print name
        printer = foo.get_printer(name)
        if foo.getMakeModelFromName(name) != (printer.make, printer.model):
            print foo.getMakeModelFromName(name), (printer.make, printer.model)

    #for name in foo.get_drivers():
    #    print name
    #    foo.get_driver(name)


if __name__ == "__main__":
    main()

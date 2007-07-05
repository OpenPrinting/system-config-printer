#!/bin/env python

import os, signal, pickle, tempfile, glob
from xml.utils import qp_xml

import sys
sys.path.append("/home/ffesti/CVS/pycups")

import cups

############################################################################# 
###  FoomaticXMLFile
#############################################################################


class FoomaticXMLFile:

    def __init__(self, name, foomatic):
        self.name = name
        self.foomatic = foomatic

    def parse_xml(self, root_node):
        raise NotImplemented

    def parse_lang_tree(self, node):
        result = {}
        for lang in node.children:
            result[lang.name] = lang.first_cdata
        return result

    def read(self):
        root_node = qp_xml.Parser().parse(open(self.filename))
        self.parse_xml(root_node)
        
    def __cmp__(self, other):
        if isinstance(other, str):
            return cmp(self.name, other) # XXX is .name really what we want?
        else:
            return cmp(self.name, other.name)

############################################################################# 
###  Driver
#############################################################################

class Driver(FoomaticXMLFile):
    """
    Attributes:

     name : String
     id : String 'driver/name'
     filename : String
     url : String
     comments_dict : dict lang -> text
     printers : list of id strings

     foomatic : Foomatic

    """
    def __init__(self, name, foomatic):
        self.filename = os.path.join(foomatic.path, 'driver',
                                     foomatic.quote_filename(name))
        FoomaticXMLFile.__init__(self, name, foomatic)


    def parse_xml(self, root_node):
        self.printers = []
        self.comments_dict = {}

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

############################################################################# 
###  Driver
#############################################################################

class Printer(FoomaticXMLFile):
    """
    Attributes:

     name : String
     id : String 'printer/name'
     filename : String
     make, model, functionality : String
     driver : name of default driver
     drivers : dict driver name -> ppd file
     comments_dict : dict lang -> text
     autodetect : dict with keys 'snmp', 'parallel', 'usb', 'general'
        -> dict with keys 'ieee1284', 'make', 'model',
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
            if node.name.lower() in (
                'ieee1284', 'manufacturer', 'model',
                'description', 'commandset', 'cmdset'):
                name = node.name.lower()
                if name == 'manufacturer': name = "make"
                if name == 'cmdset': name = "commandset"
                if node.first_cdata != "(see notes)":
                    data[name] = node.first_cdata
            else:
                pass
                #print node.name
        return data

    def parse_xml(self, root_node):

        if root_node.name != "printer":
            raise ValueError, "'printer' node expected"

        self.id = root_node.attrs.get(('', u'id'),None)
        
        self.unverified = False
        self.functionality = None
        self.driver = ''
        self.drivers = {}
        self.autodetect = {}
        self.comments_dict = {}

        for child in root_node.children:
            if child.name in ("id", "make", "model",
                              "functionality"):
                setattr(self, child.name, child.first_cdata)
    
            elif child.name == "drivers":
                for sub_child in child.children:
                    if sub_child.name == "driver":
                        if len(sub_child.children) == 2:
                            # single xml file
                            driver = sub_child.children[0].first_cdata.strip()
                            ppd = sub_child.children[1].first_cdata.strip()
                            self.drivers[driver] = ppd
                        elif len(sub_child.children) == 0:
                            # foomatic-config output
                            self.drivers.setdefault(sub_child.first_cdata, '')
            
            elif (child.name == "driver" and
                  len (child.first_cdata.strip())):
                self.driver = child.first_cdata
    
            elif child.name == "ppds":
                for sub_child in child.children:
                    if (sub_child.name != "ppd" or
                        len(sub_child.children)!=2): continue
                    driver = sub_child.children[0].first_cdata.strip()
                    ppd = sub_child.children[1].first_cdata.strip()
                    self.drivers[driver] = ppd
                
            elif child.name == "autodetect":
                for sub_child in child.children:
                    if (sub_child.name in ("snmp", "parallel",
                                           "usb", "general")):
                        self.autodetect[sub_child.name] = \
                          self.parse_autodetect(sub_child)
            elif child.name == "unverified":
                self.unverified = True

            elif child.name == "comments":
                self.comments_dict = self.parse_lang_tree(child)
            else:
                pass
                #print "Ignoring", child.name
                
        if self.id:
            if self.id.startswith('printer/'):                
                self.name = self.id[len('printer/'):]
            else:
                self.name = self.id
                self.id = 'printer/' + self.id
            self.filename = os.path.join(
                self.foomatic.path, 'printer',
                self.foomatic.quote_filename(self.name))
            if not os.path.exists(self.filename):
                print self.filename
        if self.driver and not self.drivers:
            self.drivers[self.driver] = ''

############################################################################# 
###  PPDDriver
#############################################################################

class PPDPrinter:
    """
    Attributes:

     name : String
     id : String 'printer/name'
     filename : String
     make, model, functionality : String
     drivers : list of driver names
     autodetect : dict with keys 'snmp', 'parallel', 'usb', 'general'
        -> dict with keys 'ieee1284', 'make', 'model',
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

############################################################################# 
###  Foomatic database
#############################################################################

class Foomatic:

    def __init__(self):
        self.path = '/usr/share/foomatic/db/source'
        self.foomatic_configure = "/usr/bin/foomatic-configure"

        self._printer_names = None
        self._driver_names = None
        self._printers = {}
        self._drivers = {}

        self.makes = {}

        self._auto_ieee1284 = {}
        self._auto_make = {}
        self._auto_description = {}
        
        err = self._load_pickle()
        if err:
            self.loadAll()
            self._write_pickle()
        
    def quote_filename(self, name):
        return name + '.xml'
    
    def unquote_filename(self, file):
        return file.replace('.xml', '')

    def calculated_name(self, make, model):
        model = model.replace("/", "_")
        model = model.replace(" ", "_")
        model = model.replace("+", "plus")
        model = model.replace("(", "")
        model = model.replace(")", "")
        model = model.replace(",", "")
        return make + "-" + model

    def getMakeModelFromName(self, name):
        make , model = name.split('-', 1)
        model = model.replace('_', ' ')
        return make, model

    def _add_printer(self, printer):
        printers = self.makes.setdefault(printer.make, {})
        printers[printer.name] = printer.name

        for dict in printer.autodetect.values():
            if dict.has_key("make") and dict.has_key("model"):
                d = self._auto_make.setdefault(dict["make"], {})
                d[dict["model"]] = printer.name
            if dict.has_key("ieee1284"):
                self._auto_ieee1284[dict["ieee1284"]] = printer.name
            if dict.has_key("description"):
                self._auto_description[dict["description"]] = printer.name
        
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

    def _read_all_printers_from_files(self):
        for name in self.getPrinters():
            printer = self.getPrinter(name)

    def _read_printer_list(self):
        self._printer_names = []
        for line in os.popen("foomatic-ppdfile -A"):
            parts = line.split("=")
            name = "make_model"
            values = {}
            for part in parts:
                try:
                    value, next_name = part.rsplit(" ", 1)
                except ValueError:
                    value = part
                if value.startswith("'"): value = value[1:-1]
                value = value.split()
                if len(value)==1: value = value[0]
                values[name] = value
                name = next_name
            printer = Printer(values["Id"], self)
            printer.driver = values.get("Driver", "")
            printer.drivers = {}
            for driver in values.get("CompatibleDrivers", []):
                printer.drivers[driver] = ''
            printer.make = values["make_model"][0]
            printer.model = " ".join(values["make_model"][1:])

            self._printers[printer.name] = printer
            self._printer_names.append(printer.name)
            self._add_printer(printer)

    # ----

    def addCupsPDDs(self, connection):
        ppds = connection.getPPDs
        for name, ppd in ppds.iteritems():
            
            ppd['file-name'] = name
            self.makemodel[ppd['ppd-make-and-model']] = ppd
    # ----

    def loadAll(self):
        # XXX do pickling
        #self._read_all_printers()
        self._read_all_printers_from_files()
        #self._read_printer_list()

    # ----

    def _write_pickle(self, filename="/tmp/foomatic.pickle"):
        data = {
            "_printer_names" : self._printer_names,
            #"_driver_names" : self._driver_names,
            "makes" : self.makes,
            "_auto_ieee1284" : self._auto_ieee1284,
            "_auto_make" : self._auto_make,
            "_auto_description" : self._auto_description,
            }
        f = open(filename, "w")
        pickle.dump(data, f, -1)
        f.close()
        
    def _load_pickle(self, filename="/tmp/foomatic.pickle"):
        try:
            f = open(filename, "r")
            data = pickle.load(f)
            f.close()
        except IOError:
            return True
        for name, value in data.iteritems():
            setattr(self, name, value)
        return False
    
    # ----

    def getPrinters(self):
        if self._printer_names is None:
            filenames = glob.glob(os.path.join(self.path, 'printer') + "/*.xml")
            self._printer_names = [self.unquote_filename(name)
                                   for name in filenames]
            self._printer_names.sort()
        return self._printer_names
        
    # ----

    def getDrivers(self):
        if self._driver_names is None:
            filenames = glob.glob(os.path.join(self.path, 'driver') + "/*.xml")
            self._driver_names = [self.unquote_filename(name)
                                  for name in filenames]
            self._driver_names.sort()
        return self._driver_names

    # ----

    def getPrinter(self, name):
        if not self._printers.has_key(name):
            printer = Printer(name, self)
            printer.read()
            self._printers[name] = printer
            self._add_printer(printer)
        return self._printers[name]

    def getMakeModel(self, make, model):
        try:
            return self.getPrinter(self.makes[make][model])
        except KeyError:
            return None
        
    def getDriver(self, name):
        if not self._drivers.has_key(name):
            self._drivers[name] = Driver(name, self)
            self._drivers[name].read()
        return self._drivers[name]

    def getPPDFilename(self, printer, driver_name=None):
        if driver_name is None: driver_name = printer.driver
        if printer.drivers.has_key(driver_name):
            if printer.drivers[driver_name]:
                return printer.drivers[driver_name]
            else:
                fd, fname = tempfile.mkstemp(
                    ".ppd", printer.name + "-" + driver_name)
                data = os.popen("foomatic-ppdfile -p %s -d %s" %
                                (printer.name, driver_name)).read()
                os.write(fd, data)
                os.close(fd)
                return fname
        else:
            return None
    def getMakes(self):
        result = self.makes.keys()
        result.sort()
        return result

    def getModels(self, make):
        result = self.makes[make].keys()
        result.sort()
        return result

    def getModelsNames(self, make):
        result = self.makes[make].items()
        result.sort()
        return result

def main():

    from nametree import BuildTree

    foo = Foomatic()
    #foo.loadAll()
    #print foo.makes
    for make in foo.getMakes():
        print make
        for model, name in foo.makes[make].iteritems():
            print "  ", model, name

    return
    for name in foo.getPrinters():
        printer = foo.getPrinter(name)
        print printer.name, printer.drivers
    return
    models = []
        
            
    return
    for name in foo.getPrinters():
        printer = foo.getPrinter(name)
        models.append(printer.make + ' ' + printer.model)

        if (name != printer.calculated_name() and
            name != printer.calculated_name()+ "PS"):
            print name, printer.calculated_name()
    models.sort(cups.modelSort)

    
    #tree = BuildTree(models, 3, 3)

    #print tree

    #    if foo.getMakeModelFromName(name) != (printer.make, printer.model):
    #        print foo.getMakeModelFromName(name), (printer.make, printer.model)

    #for name in foo.get_drivers():
    #    print name
    #    foo.get_driver(name)


if __name__ == "__main__":
    main()

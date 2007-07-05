#!/bin/env python

## system-config-printer

## Copyright (C) 2006 Red Hat, Inc.
## Copyright (C) 2006 Florian Festi <ffesti@redhat.com>
## Copyright (C) 2006 Tim Waugh <twaugh@redhat.com>

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
## Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.

import os, signal, pickle, tempfile, glob, re
from xml.utils import qp_xml

import cups
from gtk_html2pango import HTML2PangoParser
from cStringIO import StringIO
from pprint import pprint

def _ppdMakeModelSplit (ppd_make_and_model):
    """Convert the ppd-make-and-model field into a (make, model) pair."""
    try:
        make, model = ppd_make_and_model.split(" ", 1)
    except:
        make = ppd_make_and_model
        model = ''

    for suffix in [" PS",
                   " PXL"]:
        if model.endswith (suffix):
            model = model[:-len(suffix)]
            break

    # HP PPDs give NickNames like:
    # *NickName: "HP LaserJet 4 Plus v2013.111 Postscript (recommended)"
    hp_suffix = " Postscript (recommended)"
    if model.endswith (hp_suffix):
        # Find the version number.
        v = model.find (" v")
        if v != -1 and model[v + 2].isdigit ():
            # Truncate at that point.
            model = model[:v]
        else:
            # Otherwise just remove the 'Postscript (recommended)' bit.
            model = model[:-len(hp_suffix)]

    return (make, model)

############################################################################# 
###  FoomaticXMLFile
#############################################################################


class FoomaticXMLFile:

    def __init__(self, name, foomatic):
        self.name = name
        self.foomatic = foomatic
        self.pango_comment_dict = {}

    def parse_xml(self, root_node):
        raise NotImplemented

    def parse_lang_tree(self, node):
        result = {}
        for lang in node.children:
            result[lang.name] = lang.first_cdata
        return result

    def read(self):
        try:
            root_node = qp_xml.Parser().parse(open(self.filename))
        except IOError:
            self.valid = False
            return True
        self.parse_xml(root_node)
        self.valid = True
        return False
    
    def __cmp__(self, other):
        if isinstance(other, str):
            return cmp(self.name, other) # XXX is .name really what we want?
        else:
            return cmp(self.name, other.name)

    def getComment(self, *languages):
        lang, comment = self.getLangComment(*languages)
        return comment

    def getLangComment(self, *languages):

        for lang in languages:
            if self.comments_dict.has_key(lang):
                return lang, self.comments_dict[lang]
            if "_" in lang:
                country, dialect = lang.split("_", 1)
                if self.comments_dict.has_key(country):
                    return country, self.comments_dict[country]
        
        for lang_comment in self.comments_dict.iteritems():
            return lang_comment # return first one
        return None, ""

    def getCommentPango(self, *languages):
        lang, comment = self.getLangComment(*languages)
        if not self.pango_comment_dict.has_key(lang):
            output = StringIO()
            parser = HTML2PangoParser(output)
            parser.feed(comment)
            parser.close()
            pango_comment = output.getvalue()
            self.pango_comment_dict[lang] = pango_comment
        return self.pango_comment_dict[lang]
        
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
        self.filename = foomatic.quote_filename(name, "driver")
        FoomaticXMLFile.__init__(self, name, foomatic)

    def parse_xml(self, root_node):
        self.printers = []
        self.comments_dict = {}

        if root_node.name != "driver":
            raise ValueError, "'driver' node expected"

        self.id = root_node.attrs.get(('', u'id'), None)
        if self.id:
            self.name = self.id[len('driver/'):]
            self.filename = self.foomatic.quote_filename(self.name, "driver")
        
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
###  PPD Driver
#############################################################################

class PPDDriver(Driver):

    def __init__(self, name, foomatic):
        FoomaticXMLFile.__init__(self, name, foomatic)
        self.comments_dict = {}

#############################################################################
### No Driver (for Raw Queues
#############################################################################
        
class NoDriver(PPDDriver): 
    pass
        
############################################################################# 
###  Printer
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
        self.filename = foomatic.quote_filename(name, "printer")
        self.id = ''
        self.unverified = False
        self.functionality = None
        self.driver = ''
        self.drivers = {}
        self.autodetect = {}
        self.comments_dict = {}

        FoomaticXMLFile.__init__(self, name, foomatic)


    def getPPD(self, driver_name=None):
        """
        return cups.PPD object or string for PPD on Cups server
        """
        if driver_name is None: driver_name = self.driver
        if self.drivers.has_key(driver_name):
            print self.name, driver_name
            if self.drivers[driver_name]:
                print "PPD name:", self.drivers[driver_name]
                # XXX cups ppds
                if self.foomatic.ppds.has_key(self.drivers[driver_name]):
                    print "Cups PPD"
                    return self.drivers[driver_name]
                    #try:
                    #    filename = self.foomatic.connection.getPPD(
                    #        self.drivers[driver_name])
                    #    ppd = cups.PPD(filename)
                    #    os.unlink(filename)
                    #    return ppd
                    #except cups.IPPError:
                    #    raise
                    #    return None
                else:
                    return cups.PPD(self.drivers[driver_name])
            else:
                try:
                    fd, fname = tempfile.mkstemp(
                        ".ppd", self.name + "-" + driver_name)
                    data = os.popen("foomatic-ppdfile -p %s -d %s" %
                                    (self.name, driver_name)).read()
                    os.write(fd, data)
                    os.close(fd)
                except IOError:
                    raise
                    return None
                return cups.PPD(fname)
        else:
            print self.name, driver_name
            return None
    
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
        
        for child in root_node.children:
            if child.name in ("id", "make", "model",
                              "functionality"):
                setattr(self, child.name, child.first_cdata)
    
            elif child.name == "drivers":
                for sub_child in child.children:
                    if sub_child.name == "driver":
                        if len(sub_child.children) == 2:
                            # PPD driver
                            driver = sub_child.children[0].first_cdata.strip()
                            ppd = sub_child.children[1].first_cdata.strip()
                            self.drivers[driver] = ppd
                        elif len(sub_child.children) == 0:
                            # Non-PPD driver
                            self.drivers.setdefault(sub_child.first_cdata, '')
            
            elif (child.name == "driver" and
                  len (child.first_cdata.strip())):
                self.driver = child.first_cdata
    
            elif child.name == "lang":
                for sub_child in child.children:
                    if (len (sub_child.children) > 0 and
                        sub_child.children[0].name == "ppd"):
                        driver = sub_child.name
                        if driver == "postscript":
                            driver = "Postscript"
                        ppd = sub_child.children[0].first_cdata.strip()
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
            self.filename = self.foomatic.quote_filename(self.name, "printer")
            if not os.path.exists(self.filename):
                print "File does not exists:", self.filename

        self.getPPDDrivers()
                
        if self.driver and not self.drivers:
            self.drivers[self.driver] = ''

    def getPPDDrivers(self):
        # add PPD files to drivers list
        if (self.foomatic.ppd_makes.has_key(self.make) and
            self.foomatic.ppd_makes[self.make].has_key(self.model)):
            ppds = self.foomatic.ppd_makes[self.make][self.model]
        else:
            return
        
        for ppd_name in ppds:
            lang = self.foomatic.ppds[ppd_name]['ppd-natural-language']
            if ppd_name.startswith("foomatic-db-ppds/"):
                p = ppd_name
                if p.endswith(".gz"):
                    p = p[:-3]
                foomatic_name = p.replace("foomatic-db-ppds/", "PPD/")
                if foomatic_name in self.drivers.itervalues():
                    continue
            self.drivers[ppd_name] = ppd_name

############################################################################# 
###  PPD Printer
#############################################################################

class PPDPrinter(Printer):
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

    def __init__(self, name, foomatic):
        FoomaticXMLFile.__init__(self, name, foomatic)

        ppd = foomatic.ppds[name]
        self.make, self.model = _ppdMakeModelSplit (ppd['ppd-make-and-model'])
        self.functionality = ''
        self.driver = ''
        self.drivers = {}
        self.autodetect = {}
        self.unverified = False
        self.comments_dict = {}
        self.getPPDDrivers()

#############################################################################
### Raw Printer
#############################################################################

class RawPrinter(Printer):

    def __init__(self, foomatic):
        FoomaticXMLFile.__init__(self, "Generic-Raw", foomatic)
        self.make, self.model = "Generic", "Raw"
        self.functionality = ''
        self.driver = ''
        self.drivers = {'None' : ''}
        self.autodetect = {}
        self.unverified = False
        self.comments_dict = {}        

    def getPPD(self, driver=None):
        return None
    

############################################################################# 
###  Foomatic database
#############################################################################

class Foomatic:

    def __init__(self):
        self.path = '/usr/share/foomatic/db/source'
        self.foomatic_configure = "/usr/bin/foomatic-configure"
        self.pickle_file = "/var/cache/foomatic/foomatic.pickle"

        self._printer_names = None
        self._driver_names = None
        self._printers = {}
        self._drivers = {}

        self.makes = {}

        self._auto_ieee1284 = {}
        self._auto_make = {}
        self._auto_description = {}

        self.ppds = {}
        self.ppd_makes = {}
        
        err = self._load_pickle(self.pickle_file)
        if err:
            print "Writing new pickle"
            self.loadAll()
            self._write_pickle(self.pickle_file)

        # Add entries for raw printers
        self._add_printer(RawPrinter(self))
        self._drivers["None"] = NoDriver("None", self)
        
    def quote_filename(self, name, type):
        return os.path.join(self.path, type, name + '.xml')
    
    def unquote_filename(self, file):
        return os.path.basename(file).replace('.xml', '')

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
        self._printers[printer.name] = printer
        
        printers = self.makes.setdefault(printer.make, {})
        printers[printer.model] = printer.name

        for dict in printer.autodetect.values():
            if dict.has_key("make") and dict.has_key("model"):
                d = self._auto_make.setdefault(dict["make"], {})
                d[dict["model"]] = printer.name
            if dict.has_key("ieee1284"):
                self._auto_ieee1284[dict["ieee1284"]] = printer.name
            if dict.has_key("description"):
                self._auto_description[dict["description"]] = printer.name
        
    def addCupsPPDs(self, ppds, connection):
        ppds = ppds.copy()
        self.connection = connection
        # remove foomatic ppds
        for name in ppds.keys():
            if name.startswith("foomatic-db-ppds/"):
                ppds.pop(name)
        self.ppds = ppds
        for name, ppd in self.ppds.iteritems():
            (make, model) = _ppdMakeModelSplit (ppd['ppd-make-and-model'])

            # ppd_makes[make][model] -> [names]
            models = self.ppd_makes.setdefault(make, {})
            ppd_list = models.setdefault(model, [])
            ppd_list.append(name)
            
            # add to printers if not yet exist
            printers = self.makes.setdefault(make, {})
            if printers.has_key(model):
                if self._printers.has_key(printers[model]): # printer loaded
                    printer = self._printers[printers[model]] # add as driver
                    lang = ppd['ppd-natural-language']
                    self._drivers["CUPS: %s (%s)" % (name, lang)] = name
                    printer.getPPDDrivers()
            else:
                #print make, model, name
                printers[model] = name # add as printer
            if ppd.has_key('ppd-device-id') and ppd['ppd-device-id']:
                self._auto_ieee1284.setdefault(ppd['ppd-device-id'],
                                               name)

#     def clearCupsPPDs(self):
#         for name, ppd in self.ppds.iteritems():
#             make, model = ppd['ppd-make-and-model'].split(" ", 1)
#             if self.makes[make][model] == name:
#                 del self.makes[make][model]
#                 if not self.makes[make]: # remove emtpy dicts
#                     del self.makes[make]
#         # XXX remove ppd "drivers"

    # ----

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

            self._printer_names.append(printer.name)
            self._add_printer(printer)

    # ----

    def loadAll(self):
        #self._read_all_printers()
        self._read_all_printers_from_files()
        #self._read_printer_list()

    # ----

    def _write_pickle(self, filename="/var/cache/foomatic/foomatic.pickle"):
        data = {
            "_printer_names" : self._printer_names,
            #"_driver_names" : self._driver_names,
            "makes" : self.makes,
            "_auto_ieee1284" : self._auto_ieee1284,
            "_auto_make" : self._auto_make,
            "_auto_description" : self._auto_description,
            }
        path = os.path.dirname(filename)
        try:
            # temp file
            fd, tempname = tempfile.mkstemp(".tmp", "foomatic", dir=path)
            os.write(fd, pickle.dumps(data, -1))
            os.close(fd)
        
            os.rename(tempname, filename) # atomically replace old file
        except OSError:
            pass
        
    def _load_pickle(self, filename="/var/cache/foomatic/foomatic.pickle"):
        if not os.path.exists(filename): return True
        
        pickle_mtime = os.path.getmtime(filename)
        if os.path.getmtime(__file__)>pickle_mtime: return True

        # check for changes in printer and driver directories
        for dir_name in ["printer", "driver"]:
            path = os.path.join(self.path, dir_name)
            if os.path.getmtime(path)>pickle_mtime: return True

            for file in glob.glob(os.path.join(path, "*.xml")):
                if os.path.getmtime(file)>pickle_mtime:
                    return True
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
            if self.ppds.has_key(name):
                printer = PPDPrinter(name, self)
                self._printers[name] = printer
            else:
                printer = Printer(name, self)
                printer.read()
                self._add_printer(printer)
        return self._printers[name]

    def getMakeModel(self, make, model):
        try:
            return self.getPrinter(self.makes[make][model])
        except KeyError:
            return None
        
    def getDriver(self, name):
        if not self._drivers.has_key(name):
            if self.ppds.has_key(name):
                self._drivers[name] = PPDDriver(name, self)
            else:
                self._drivers[name] = Driver(name, self)
                self._drivers[name].read()
        return self._drivers[name]

    def getMakes(self):
        result = self.makes.keys()        
        result.sort()
        try:
            result.remove("Generic")
            result.insert(0, "Generic")
        except ValueError:
            pass
        return result

    def getModels(self, make):
        result = self.makes[make].keys()
        result.sort(cups.modelSort)
        return result
    
    def getModelsNames(self, make):
        def cmpModels(first, second):
            return cups.modelSort(first[0], second[0])
        result = self.makes[make].items()
        result.sort(cmpModels)
        return result

    def getPrinterFromCupsDevice(self, device):
        """return name of printer or None"""
        if not device.id: return None

        # check for make, model
        mfg = device.id_dict["MFG"]
        if (self._auto_make.has_key(mfg) and
            self._auto_make[mfg].has_key(device.id_dict["MDL"])):
            return self._auto_make[mfg][device.id_dict["MDL"]]

        # check whole ieee1284 string
        pieces = device.id.split(';')
        for length in xrange(len(pieces), 0, -1):
            ieee1284 = ";".join(pieces[:length]) + ';'
            if self._auto_ieee1284.has_key(ieee1284):
                return self._auto_ieee1284[ieee1284]                

        # check description
        if self._auto_description.has_key(device.id_dict["DES"]):
            return self._auto_description[device.id_dict["DES"]]

        # Try matching against the foomatic names
        best_mdl = None
        for attempt in range (2):
            if self.makes.has_key (mfg):
                mdl = device.id_dict["MDL"]
                mdls = self.makes[mfg]
                if mdls.has_key (mdl):
                    print "Please report a bug in Bugzilla against 'foomatic':"
                    print "  https://bugzilla.redhat.com/bugzilla"
                    print "Include this complete message."
                    print "Deducing %s from IEEE 1284 ID:" % best_mdl
                    print "      <manufacturer>%s</manufacturer>" % mfg
                    print "      <model>%s</model>" % mdl
                    print "      <description>%s</description>" %\
                          device.id_dict["DES"]
                    print "URI: %s" % device.uri
                    print "This message is harmless."
                    return mdls[mdl]

                # Try to find the best match
                best_matchlen = 0
                for each in mdls.keys():
                    if mdl[:1 + best_matchlen] == each[:1 + best_matchlen]:
                        extra = 2
                        while (mdl[1 + best_matchlen:extra + best_matchlen] ==
                               each[1 + best_matchlen:extra + best_matchlen]):
                            extra += 1
                        best_matchlen += extra
                        best_mdl = mdls[each]

            # Try again with replacements
            if mfg == "Hewlett-Packard":
                mfg = "HP"
                continue

            break

        if best_mdl:
            print "Please report a bug in Bugzilla against 'foomatic':"
            print "  https://bugzilla.redhat.com/bugzilla"
            print "Include this complete message."
            print "Guessing %s from IEEE 1284 ID:" % best_mdl
            print "      <manufacturer>%s</manufacturer>" % mfg
            print "      <model>%s</model>" % mdl
            print "      <description>%s</description>" % device.id_dict["DES"]
            print "URI: %s" % device.uri
            return best_mdl

        return None

    def getPPD(self, make, model, description="", languages=[]):
        # check for make, model
        if (self._auto_make.has_key(make) and
            self._auto_make[make].has_key(model)):
            printer = self.getPrinter(self._auto_make[make][model])
        # check description
        elif self._auto_description.has_key(description):
            printer = self.getPrinter(self._auto_description[description])

        # generic ppd
        # XXX
        else:
            return None
        return printer.getPPD()

    def getCupsPPD(self, printer, ppds):
        make_model = "%s %s" % (printer.make, printer.model)
        result = []
        for name, ppd_dict in ppds.iteritems():
            if ppd_dict['ppd-make-and-model'] == make_model:
                result.append((name, pd_dict['ppd-natural-language']))
        return result

        
def main():
    from nametree import BuildTree

    foo = Foomatic()
    pprint(foo._auto_make)
    #for make in foo.getMakes():
    #    print make
    #    for model, name in foo.makes[make].iteritems():
    #        print "  ", model, name

    for name in foo.getPrinters():
        printer = foo.getPrinter(name)
        if len(printer.drivers)>1:
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

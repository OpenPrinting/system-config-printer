#!/usr/bin/python3

## system-config-printer

## Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2014, 2015 Red Hat, Inc.
## Copyright (C) 2006 Florian Festi <ffesti@redhat.com>
## Copyright (C) 2006, 2007, 2008, 2009 Tim Waugh <twaugh@redhat.com>

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

try:
    import cups
    from cupshelpers.cupshelpers import parseDeviceID
    from cupshelpers.ppds import PPDs
except ImportError:
    cups = None

import itertools
import string
import time
import locale
import os.path
import functools
import re
import sys, getopt
import pickle
import pytest

def _singleton (x):
    """If we don't know whether getPPDs() or getPPDs2() was used, this
    function can unwrap an item from a list in either case."""
    if isinstance (x, list):
        return x[0]
    return x

@pytest.mark.skipif(cups is None, reason="cups module not available")
def test_ppds():
    picklefile="pickled-ppds"
    try:
        with open (picklefile, "rb") as f:
            cupsppds = pickle.load (f)
    except IOError:
        with open (picklefile, "wb") as f:
            c = cups.Connection ()
            try:
                cupsppds = c.getPPDs2 ()
                print ("Using getPPDs2()")
            except AttributeError:
                # Need pycups >= 1.9.52 for getPPDs2
                cupsppds = c.getPPDs ()
                print ("Using getPPDs()")

            pickle.dump (cupsppds, f)

    xml_dir = os.path.join (os.environ.get ("top_srcdir", "."), "xml")
    ppds = PPDs (cupsppds, xml_dir=xml_dir)
    makes = ppds.getMakes ()
    models_count = 0
    for make in makes:
        models = ppds.getModels (make)
        models_count += len (models)

    print ("%d makes, %d models" % (len (makes), models_count))
    ppds.getPPDNameFromDeviceID ("HP", "PSC 2200 Series")
    makes = list(ppds.ids.keys ())
    models_count = 0
    for make in makes:
        models = ppds.ids[make]
        models_count += len (models)

    print ("%d ID makes, %d ID models" % (len (makes), models_count))

    print ("\nID matching tests\n")

    MASK_STATUS = (1 << 2) - 1
    FLAG_INVERT = (1 << 2)
    FLAG_IGNORE_STATUS = (1 << 3)
    idlist = [
        # Format is:
        # (ID string, max status code (plus flags),
        #  expected ppd-make-and-model RE match)

        # Specific models
        ("MFG:EPSON;CMD:ESCPL2,BDC,D4,D4PX;MDL:Stylus D78;CLS:PRINTER;"
         "DES:EPSON Stylus D78;", 1, 'Epson Stylus D68'),
        ("MFG:Hewlett-Packard;MDL:LaserJet 1200 Series;"
         "CMD:MLC,PCL,POSTSCRIPT;CLS:PRINTER;", 0, 'HP LaserJet 1200'),
        ("MFG:Hewlett-Packard;MDL:LaserJet 3390 Series;"
         "CMD:MLC,PCL,POSTSCRIPT;CLS:PRINTER;", 0, 'HP LaserJet 3390'),
        ("MFG:Hewlett-Packard;MDL:PSC 2200 Series;CMD:MLC,PCL,PML,DW-PCL,DYN;"
         "CLS:PRINTER;1284.4DL:4d,4e,1;", 0, "HP PSC 22[01]0"),
        ("MFG:HEWLETT-PACKARD;MDL:DESKJET 990C;CMD:MLC,PCL,PML;CLS:PRINTER;"
         "DES:Hewlett-Packard DeskJet 990C;", 0, "HP DeskJet 990C"),
        ("CLASS:PRINTER;MODEL:HP LaserJet 6MP;MANUFACTURER:Hewlett-Packard;"
         "DESCRIPTION:Hewlett-Packard LaserJet 6MP Printer;"
         "COMMAND SET:PJL,MLC,PCLXL,PCL,POSTSCRIPT;", 0, "HP LaserJet (6P/)?6MP"),
        # Canon PIXMA iP3000 (from gutenprint)
        ("MFG:Canon;CMD:BJL,BJRaster3,BSCCe;SOJ:TXT01;MDL:iP3000;CLS:PRINTER;"
         "DES:Canon iP3000;VER:1.09;STA:10;FSI:03;", 1, "Canon PIXMA iP3000"),
        ("MFG:HP;MDL:Deskjet 5400 series;CMD:MLC,PCL,PML,DW-PCL,DESKJET,DYN;"
         "1284.4DL:4d,4e,1;CLS:PRINTER;DES:5440;",
         1, "HP DeskJet (5440|5550)"), # foomatic-db-hpijs used to say 5440
        ("MFG:Hewlett-Packard;MDL:HP LaserJet 3390;"
         "CMD:PJL,MLC,PCL,POSTSCRIPT,PCLXL;",
         0, "HP LaserJet 3390"),
        # Ricoh printers should use PostScript versions of
        # manufacturer's PPDs (bug #550315 comment #8).
        ("MFG:RICOH;MDL:Aficio 3045;",
         0, "Ricoh Aficio 3045 PS"),
        # Don't mind which driver gets used here so long as it isn't
        # gutenprint (bug #645993).
        ("MFG:Brother;MDL:HL-2030;",
         0 | FLAG_INVERT | FLAG_IGNORE_STATUS, ".*Gutenprint"),
        # Make sure we get a colour driver for this one, see launchpad
        # #669152.
        ("MFG:Xerox;MDL:6250DP;",
         1, ".*(Postscript|pcl5e)"),

        # Generic models
        ("MFG:New;MDL:Unknown PS Printer;CMD:POSTSCRIPT;",
         2, "Generic postscript printer"),
        # Make sure pxlcolor is used for PCLXL.  The gutenprint driver
        # is black and white, and pxlcolor is the foomatic-recommended
        # generic driver for "Generic PCL 6/PCL XL Printer".
        ("MFG:New;MDL:Unknown PCL6 Printer;CMD:PCLXL;", 2,
         "Generic PCL 6.*pxlcolor"),
        ("MFG:New;MDL:Unknown PCL5e Printer;CMD:PCL5e;", 2, "Generic PCL 5e"),
        ("MFG:New;MDL:Unknown PCL5c Printer;CMD:PCL5c;", 2, "Generic PCL 5c"),
        ("MFG:New;MDL:Unknown PCL5 Printer;CMD:PCL5;", 2, "Generic PCL 5"),
        ("MFG:New;MDL:Unknown PCL3 Printer;CMD:PCL;", 2, "Generic PCL"),
        ("MFG:New;MDL:Unknown Printer;", 100, None),
        ]

    all_passed = True
    for id, max_status_code, modelre in idlist:
        flags = max_status_code & ~MASK_STATUS
        max_status_code &= MASK_STATUS
        id_dict = parseDeviceID (id)
        (status, ppdname) = ppds.getPPDNameFromDeviceID (id_dict["MFG"],
                                                         id_dict["MDL"],
                                                         id_dict["DES"],
                                                         id_dict["CMD"])
        ppddict = ppds.getInfoFromPPDName (ppdname)
        if flags & FLAG_IGNORE_STATUS:
            status = max_status_code

        if status < max_status_code:
            success = True
        else:
            if status == max_status_code:
                match = re.match (modelre,
                                  _singleton (ppddict['ppd-make-and-model']),
                                  re.I)
                success = match is not None
            else:
                success = False


        if flags & FLAG_INVERT:
            success = not success

        if success:
            result = "PASS"
        else:
            result = "*** FAIL ***"

        print ("%s: %s %s (%s)" % (result, id_dict["MFG"], id_dict["MDL"],
                                  _singleton (ppddict['ppd-make-and-model'])))
        all_passed = all_passed and success

    assert all_passed


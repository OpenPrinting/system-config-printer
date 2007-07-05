#!/usr/bin/env python

## system-config-printer

## Copyright (C) 2006, 2007 Red Hat, Inc.
## Copyright (C) 2006 Florian Festi <ffesti@redhat.com>
## Copyright (C) 2006, 2007 Tim Waugh <twaugh@redhat.com>

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

import cups
from cupshelpers import parseDeviceID
import string

def ppdMakeModelSplit (ppd_make_and_model):
    """Convert the ppd-make-and-model field into a (make, model) pair."""
    try:
        make, model = ppd_make_and_model.split(" ", 1)
    except:
        make = ppd_make_and_model
        model = ''

    def strip_suffix (model, suffix):
        if model.endswith (suffix):
            return model[:-len(suffix)]
        return model

    # HP PPDs give NickNames like:
    # *NickName: "HP LaserJet 4 Plus v2013.111 Postscript (recommended)"
    # Find the version number.
    v = model.find (" v")
    if v != -1 and (model[v + 2].isdigit () or
                    (model[v + 2] == '.' and
                     model[v + 3].isdigit ())):
        # Truncate at that point.
        model = model[:v]

    f = model.find (" Foomatic/")
    if f != -1:
        model = model[:f]

    # Gutenprint PPDs have NickNames that end:
    # ... - CUPS+Gutenprint v5.0.0
    gutenprint = model.find (" - CUPS+Gutenprint")
    if gutenprint != -1:
        model = model[:gutenprint]

    # Gimp-Print PPDs have NickNames that end:
    # ... - CUPS+Gimp-Print v4.2.7
    gimpprint = model.find (" - CUPS+Gimp-Print")
    if gimpprint != -1:
        model = model[:gimpprint]

    model = strip_suffix (model, " (recommended)")
    model = strip_suffix (model, " Postscript")
    model = strip_suffix (model, " Series")
    model = strip_suffix (model, " PS")
    model = strip_suffix (model, " PXL")

    for mfr in [ "Apple", "Canon", "Epson", "Lexmark", "Okidata" ]:
        if make == mfr.upper ():
            make = mfr

    model = model.strip ()
    return (make, model)

class PPDs:
    # Status of match.
    STATUS_SUCCESS = 0
    STATUS_MODEL_MISMATCH = 1
    STATUS_GENERIC_DRIVER = 2
    STATUS_NO_DRIVER = 3

    def __init__ (self, ppds):
        """Takes a dict of PPDs, as returned by cups.Connection.getPPDs()."""
        self.ppds = ppds.copy ()
        self.makes = None
        self.ids = None

    def getMakes (self):
        """Returns a sorted list of strings."""
        self._init_makes ()
        makes_list = self.makes.keys ()
        makes_list.sort ()
        try:
            # "Generic" should be listed first.
            makes_list.remove ("Generic")
            makes_list.insert (0, "Generic")
        except ValueError:
            pass
        return makes_list

    def getModels (self, make):
        """Returns a sorted list of strings."""
        self._init_makes ()
        try:
            models_list = self.makes[make].keys ()
        except KeyError:
            return []
        models_list.sort (cups.modelSort)
        return models_list

    def getInfoFromModel (self, make, model):
        """Returns a dict of ppd-name:ppd-dict."""
        self._init_makes ()
        try:
            return self.makes[make][model]
        except KeyError:
            return {}

    def getInfoFromPPDName (self, ppdname):
        """Returns a ppd-dict."""
        return self.ppds[ppdname]

    def orderPPDNamesByPreference (self, ppdnamelist=[]):
        """Returns a sorted list of ppd-names."""
        def sort_ppdnames (a, b):
            # Prefer real PPDs to generated ones.
            reala = a.find (":") == -1
            realb = b.find (":") == -1
            if reala != realb:
                if realb:
                    return 1
                else:
                    return -1

            def is_C_locale (x):
                while x:
                    i = x.find ("C")
                    if i == -1:
                        return False
                    lword = False
                    if i == 0:
                        lword = True
                    elif x[i - 1] not in string.letters:
                        lword = True

                    if lword:
                        rword = False
                        if i == (len (x) - 1):
                            rword = True
                        elif x[i + 1] not in string.letters:
                            rword = True
                        if rword:
                            return True
                        
                    x = x[i + 1:]

            ca = is_C_locale (a)
            cb = is_C_locale (b)
            if ca != cb:
                # If they compare equal stringwise up to "C", sort.
                if ca:
                    l = a.find ("C")
                else:
                    l = b.find ("C")

                if a[:l] == b[:l]:
                    if cb:
                        return 1
                    else:
                        return -1

            if a > b:
                return 1
            elif a < b:
                return -1
            return 0

        ppdnamelist.sort (sort_ppdnames)
        return ppdnamelist

    def getPPDNameFromDeviceID (self, mfg, mdl, description="",
                                commandsets=[], uri=None):
        """Returns a (status,ppd-name) integer,string pair."""
        print "\n%s %s" % (mfg, mdl)
        self._init_ids ()
        id_matched = False
        try:
            ppdnamelist = self.ids[mfg.lower ()][mdl.lower ()]
            status = self.STATUS_SUCCESS
            id_matched = True
        except KeyError:
            ppdnamelist = None

        if not ppdnamelist:
            # No ID match.  Try comparing make/model names.
            print "Trying make/model names"
            mfgl = mfg.lower ()
            mdls = None
            for attempt in range (2):
                for (make, models) in self.makes.iteritems ():
                    if make.lower () == mfgl:
                        mdls = models
                        break

                # Try again with replacements.
                if mfg == "hewlett-packard":
                    mfg = "hp"

            # Handle bogus HPLIP Device IDs
            if mdl.startswith (mfg + ' '):
                mdl = mdl[len (mfg) + 1:]

            if mdls and mdls.has_key (mdl):
                ppdnamelist = mdls[mdl].keys ()
                status = self.STATUS_SUCCESS

        if not ppdnamelist and mdls:
            (s, ppds) = self._findBestMatchPPDs (mdls, mdl)
            if s != self.STATUS_NO_DRIVER:
                status = s
                ppdnamelist = ppds

        if not ppdnamelist and commandsets:
            if type (commandsets) != list:
                commandsets = commandsets.split (',')

            generic = self._getPPDNameFromCommandSet (commandsets)
            if generic:
                status = self.STATUS_GENERIC_DRIVER
                ppdnamelist = generic

        if not ppdnamelist:
            print "Text-only fallback"
            status = self.STATUS_NO_DRIVER
            ppdnamelist = ["textonly.ppd"]
            if not self.ppds.has_key (ppdnamelist[0]):
                print "No text-only driver?!"
                ppdnamelist = [self.ppds[0]]

        if id_matched:
            print "Checking DES field"
            inexact = set()
            if description:
                for ppdname in ppdnamelist:
                    ppddict = self.ppds[ppdname]
                    id = ppddict['ppd-device-id']
                    # Fetch description field.
                    id_dict = parseDeviceID (id)
                    if id_dict["DES"] != description:
                        inexact.add (ppdname)

            exact = set (ppdnamelist).difference (inexact)
            print "discarding:", inexact
            if len (exact) >= 1:
                ppdnamelist = list (exact)

        # We've got a set of PPDs, any of which will drive the device.
        # Now we have to choose the "best" one.  This is quite tricky
        # to decide, so let's sort them in order of preference and
        # take the first.
        ppdnamelist = self.orderPPDNamesByPreference (ppdnamelist)
        print ppdnamelist
        return (status, ppdnamelist[0])

    def _findBestMatchPPDs (self, mdls, mdl):
        print "Trying best match"
        mdl = mdl.lower ()
        best_mdl = None
        best_matchlen = 0
        mdlnames = mdls.keys ()
        mdlnames.sort (cups.modelSort)
        mdlitems = map (lambda x: (x.lower (), mdls[x]), mdlnames)
        for (name, ppds) in mdlitems:
            if mdl[:1 + best_matchlen] == name[:1 + best_matchlen]:
                # We know we've got one more character matching.
                # Can we match any more on this entry?
                extra = 1
                while (mdl[1 + best_matchlen:1 + best_matchlen + extra] ==
                       name[1 + best_matchlen:1 + best_matchlen + extra]):
                    # Yes!  Try another!
                    extra += 1
                    if extra + best_matchlen >= len (name):
                        break
                best_matchlen += extra
                best_mdl = ppds.keys ()

        if best_mdl and best_matchlen > (len (mdl) / 2):
            ppdnamelist = best_mdl
            if best_matchlen == len (mdl):
                status = self.STATUS_SUCCESS
            else:
                status = self.STATUS_MODEL_MISMATCH
        else:
            status = self.STATUS_NO_DRIVER
            ppdnamelist = None

        return (status, ppdnamelist)

    def _getPPDNameFromCommandSet (self, commandsets=[]):
        """Return ppd-name list or None, given a list of strings representing
        the command sets supported."""
        try:
            self._init_makes ()
            models = self.makes["Generic"]
        except KeyError:
            return None

        def get (*candidates):
            for model in candidates:
                (s, ppds) = self._findBestMatchPPDs (models, model)
                if s == self.STATUS_SUCCESS:
                    return ppds
            return None

        cmdsets = map (lambda x: x.lower (), commandsets)
        if (("postscript" in cmdsets) or ("postscript2" in cmdsets) or
            ("postscript level 2 emulation" in cmdsets)):
            return get ("PostScript Printer")
        elif (("pclxl" in cmdsets) or ("pcl-xl" in cmdsets) or
              ("pcl6" in cmdsets) or ("pcl 6 emulation" in cmdsets)):
            return get ("PCL 6/PCL XL Printer")
        elif "pcl5e" in cmdsets:
            return get ("PCL 5e Printer")
        elif "pcl5c" in cmdsets:
            return get ("PCL 5c Printer")
        elif ("pcl5" in cmdsets) or ("pcl 5 emulation" in cmdsets):
            return get ("PCL 5 Printer")
        elif "pcl" in cmdsets:
            return get ("PCL 3 Printer")
        elif (("escpl2" in cmdsets) or ("esc/p2" in cmdsets) or
              ("escp2e" in cmdsets)):
            return get ("ESC/P Dot Matrix Printer")
        return None

    def _init_makes (self):
        if self.makes:
            return

        makes = {}
        lmakes = {}
        lmodels = {}
        for ppdname, ppddict in self.ppds.iteritems ():
            ppd_make_and_model = ppddict['ppd-make-and-model']
            (make, model) = ppdMakeModelSplit (ppd_make_and_model)
            lmake = make.lower ()
            lmodel = model.lower ()
            if not lmakes.has_key (lmake):
                lmakes[lmake] = make
                lmodels[lmake] = {}
                makes[make] = {}
            else:
                make = lmakes[lmake]

            if not lmodels[lmake].has_key (lmodel):
                lmodels[lmake][lmodel] = model
                makes[make][model] = {}
            else:
                model = lmodels[lmake][lmodel]

            makes[make][model][ppdname] = ppddict

        self.makes = makes
        self.lmakes = lmakes
        self.lmodels = lmodels

    def _init_ids (self):
        if self.ids:
            return

        ids = {}
        for ppdname, ppddict in self.ppds.iteritems ():
            if not ppddict.has_key ('ppd-device-id'):
                continue
            id = ppddict['ppd-device-id']
            if not id:
                continue

            # Fix up broken Kyocera IDs
            v = id.find (":Model")
            if v != -1:
                id = id[:v] + ';' + id[v + 1:]

            id_dict = parseDeviceID (id)
            lmfg = id_dict['MFG'].lower ()
            lmdl = id_dict['MDL'].lower ()

            bad = False
            if len (lmfg) == 0:
                print "Missing MFG field for %s" % ppdname
                bad = True
            if len (lmdl) == 0:
                print "Missing MDL field for %s" % ppdname
                bad = True
            if bad:
                continue

            if not ids.has_key (lmfg):
                ids[lmfg] = {}

            if not ids[lmfg].has_key (lmdl):
                ids[lmfg][lmdl] = []

            ids[lmfg][lmdl].append (ppdname)

        self.ids = ids

def main():
    list_models = True
    list_ids = False

    picklefile="pickled-ppds"
    import pickle
    try:
        f = open (picklefile, "r")
        cupsppds = pickle.load (f)
    except IOError:
        f = open (picklefile, "w")
        c = cups.Connection ()
        cupsppds = c.getPPDs ()
        pickle.dump (cupsppds, f)

    ppds = PPDs (cupsppds)
    makes = ppds.getMakes ()
    models_count = 0
    for make in makes:
        models = ppds.getModels (make)
        models_count += len (models)
        if list_models:
            print make
            for model in models:
                print "  " + model
    print "%d makes, %d models" % (len (makes), models_count)
    ppds.getPPDNameFromDeviceID ("HP", "PSC 2200 Series")
    makes = ppds.ids.keys ()
    models_count = 0
    for make in makes:
        models = ppds.ids[make]
        models_count += len (models)
        if list_ids:
            print make
            for model in models:
                print "  %s (%d)" % (model, len (ppds.ids[make][model]))
                for driver in ppds.ids[make][model]:
                    print "    " + driver
    print "%d ID makes, %d ID models" % (len (makes), models_count)

    for id in [
        "MFG:EPSON;CMD:ESCPL2,BDC,D4,D4PX;MDL:Stylus D78;CLS:PRINTER;DES:EPSON Stylus D78;",
        "MFG:Hewlett-Packard;MDL:PSC 2200 Series;CMD:MLC,PCL,PML,DW-PCL,DYN;CLS:PRINTER;1284.4DL:4d,4e,1;",
        "MFG:HEWLETT-PACKARD;MDL:DESKJET 990C;CMD:MLC,PCL,PML;CLS:PRINTER;DES:Hewlett-Packard DeskJet 990C;",
        "MFG:New;MDL:Unknown PS Printer;CMD:POSTSCRIPT;",
        "MFG:New;MDL:Unknown PCL6 Printer;CMD:PCLXL;",
        "MFG:New;MDL:Unknown PCL5e Printer;CMD:PCL5e;",
        "MFG:New;MDL:Unknown PCL5c Printer;CMD:PCL5c;",
        "MFG:New;MDL:Unknown PCL5 Printer;CMD:PCL5;",
        "MFG:New;MDL:Unknown PCL3 Printer;CMD:PCL;",
        "MFG:New;MDL:Unknown ESC/P Printer;CMD:ESCP2E;",
        ]:
        id_dict = parseDeviceID (id)
        print ppds.getPPDNameFromDeviceID (id_dict["MFG"],
                                           id_dict["MDL"],
                                           id_dict["DES"],
                                           id_dict["CMD"])

if __name__ == "__main__":
    main()

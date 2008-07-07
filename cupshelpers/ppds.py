#!/usr/bin/env python

## system-config-printer

## Copyright (C) 2006, 2007, 2008 Red Hat, Inc.
## Copyright (C) 2006 Florian Festi <ffesti@redhat.com>
## Copyright (C) 2006, 2007, 2008 Tim Waugh <twaugh@redhat.com>

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
from .cupshelpers import parseDeviceID
import string
import locale
import os.path
import re
from . import _debugprint

__all__ = ['ppdMakeModelSplit',
           'PPDs',
           'self_test']

def ppdMakeModelSplit (ppd_make_and_model):
    """
    Split a ppd-make-and-model string into a canonical make and model pair.

    @type ppd_make_and_model: string
    @param ppd_make_and_model: IPP ppd-make-and-model attribute
    @return: a string pair representing the make and the model
    """

    # If the string starts with a known model name (like "LaserJet") assume
    # that the manufacturer name is missing and add the manufacturer name
    # corresponding to the model name
    if re.search ("^(deskjet|laserjet|designjet|officejet|photosmart|psc|edgeline)", \
                      ppd_make_and_model, re.I):
        make = "HP"
        model = ppd_make_and_model
    elif re.search ("^(stylus|aculaser)", \
                      ppd_make_and_model, re.I):
        make = "Epson"
        model = ppd_make_and_model
    elif re.search ("^(stylewriter|imagewriter|deskwriter|laserwriter)", \
                      ppd_make_and_model, re.I):
        make = "Apple"
        model = ppd_make_and_model
    elif re.search ("^(pixus|pixma|selphy|imagerunner|\bbjc\b|\bbj\b|\blbp\b)",\
                      ppd_make_and_model, re.I):
        make = "Canon"
        model = ppd_make_and_model
    elif re.search ("^(\bhl\b|\bdcp\b|\bmfc\b)", \
                      ppd_make_and_model, re.I):
        make = "Brother"
        model = ppd_make_and_model
    elif re.search ("^(docuprint|docupage|phaser|workcentre|homecentre)", \
                      ppd_make_and_model, re.I):
        make = "Xerox"
        model = ppd_make_and_model
    elif re.search ("^(optra|(color\s*|)jetprinter)", \
                      ppd_make_and_model, re.I):
        make = "Lexmark"
        model = ppd_make_and_model
    elif re.search ("^(magicolor|pageworks|pagepro)", \
                      ppd_make_and_model, re.I):
        make = "KONICA MINOLTA"
        model = ppd_make_and_model
    elif re.search ("^(aficio)", \
                      ppd_make_and_model, re.I):
        make = "Ricoh"
        model = ppd_make_and_model
    elif re.search ("^(varioprint)", \
                      ppd_make_and_model, re.I):
        make = "Oce"
        model = ppd_make_and_model
    elif re.search ("^(okipage|microline)", \
                      ppd_make_and_model, re.I):
        make = "Okidata"
        model = ppd_make_and_model
    elif re.search ("^(konica[\s_-]*minolta)", \
                      ppd_make_and_model, re.I):
        make = "KONICA MINOLTA"
        model = ppd_make_and_model
        model = re.sub ("(?i)KONICA[\s_-]*MINOLTA\s*", "", model, 1)
    else:
        try:
            make, model = ppd_make_and_model.split(" ", 1)
        except:
            make = ppd_make_and_model
            model = ''

    def strip_suffix (model, suffix):
        if model.endswith (suffix):
            return model[:-len(suffix)]
        return model

    # Model names do not contain a comma, truncate all from the
    # comma on
    c = model.find (",")
    if c != -1:
        model = model[:c]

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

    wth = model.find (" w/")
    if wth != -1:
        model = model[:wth]

    make = re.sub (r"(?i)KONICA[\s_-]*MINOLTA", "KONICA MINOLTA", make, 1)
    model = re.sub (r"(?i)\s*\(recommended\)", "", model)
    model = re.sub (r"(?i)\s*-\s*PostScript\b", "", model)
    model = re.sub (r"(?i)\s*\bseries\b", "", model)
    model = re.sub (r"(?i)\s*\bPS[123]?\b", "", model)
    model = re.sub (r"(?i)\s*\bPXL", "", model)
    model = re.sub (r"(?i)[\s_-]+BT\b", "", model)
    model = re.sub (r"(?i)\s*\(Bluetooth\)", "", model)
    model = re.sub (r"(?i)\s*-\s*(RC|Ver(|sion))\s*-*\s*[0-9\.]+", "", model)
    model = re.sub (r"(?i)\s*-\s*(RC|Ver(|sion))\b", "", model)
    model = re.sub (r"(?i)\s*PostScript\s*$", "", model)
    model = re.sub (r"(?i)\s*-\s*$", "", model)

    for mfr in [ "Apple", "Canon", "Epson", "Lexmark", "Okidata" ]:
        if make == mfr.upper ():
            make = mfr

    model = model.strip ()
    return (make, model)

# Some drivers are just generally better than others.
# Here is the preference list:
DRIVER_TYPE_FOOMATIC_RECOMMENDED_NON_POSTSCRIPT = 8
DRIVER_TYPE_VENDOR = 10
DRIVER_TYPE_FOOMATIC_RECOMMENDED_POSTSCRIPT = 15
DRIVER_TYPE_FOOMATIC_HPIJS_ON_HP = 17
DRIVER_TYPE_GUTENPRINT_NATIVE_SIMPLIFIED = 20
DRIVER_TYPE_GUTENPRINT_NATIVE = 25
DRIVER_TYPE_SPLIX = 27
DRIVER_TYPE_FOOMATIC_PS = 30
DRIVER_TYPE_FOOMATIC_HPIJS = 40
DRIVER_TYPE_FOOMATIC_GUTENPRINT_SIMPLIFIED = 50
DRIVER_TYPE_FOOMATIC_GUTENPRINT = 60
DRIVER_TYPE_FOOMATIC = 70
DRIVER_TYPE_CUPS = 80
DRIVER_TYPE_FOOMATIC_GENERIC = 90
DRIVER_DOES_NOT_WORK = 999
def _getDriverType (ppdname, ppds=None):
    """Decides which of the above types ppdname is."""
    if ppdname.find ("gutenprint") != -1:
        if (ppdname.find ("/simple/") != -1 or
            ppdname.find (".sim-") != -1):
            return DRIVER_TYPE_GUTENPRINT_NATIVE_SIMPLIFIED
        else:
            return DRIVER_TYPE_GUTENPRINT_NATIVE
    if ppdname.find ("splix")!= -1:
        return DRIVER_TYPE_SPLIX
    if (ppdname.find (":") == -1 and
        ppdname.find ("/cups-included/") != -1):
        return DRIVER_TYPE_CUPS
    if ppdname.startswith ("foomatic:"):
        # Foomatic (generated) -- but which driver?
        if ppdname.find ("Generic")!= -1:
            return DRIVER_TYPE_FOOMATIC_GENERIC
        if (ppds != None and
            ppds.getInfoFromPPDName (ppdname).\
            get ('ppd-make-and-model', '').find ("(recommended)") != -1):
            if ppds.getInfoFromPPDName (ppdname).\
               get ('ppd-make-and-model', '').find ("Postscript") != -1:
                return DRIVER_TYPE_FOOMATIC_RECOMMENDED_POSTSCRIPT
            else:
                return DRIVER_TYPE_FOOMATIC_RECOMMENDED_NON_POSTSCRIPT
        if ppdname.find ("-Postscript")!= -1:
            return DRIVER_TYPE_FOOMATIC_PS
        if ppdname.find ("-hpijs") != -1:
            if ppdname.find ("hpijs-rss") == -1:
                return DRIVER_TYPE_FOOMATIC_HPIJS
        if ppdname.find ("-gutenprint") != -1:
            if ppdname.find ("-simplified")!= -1:
                return DRIVER_TYPE_FOOMATIC_GUTENPRINT_SIMPLIFIED
            return DRIVER_TYPE_FOOMATIC_GUTENPRINT
        return DRIVER_TYPE_FOOMATIC
    if ppdname.find ("-hpijs") != -1:
        if ppdname.find ("hpijs-rss") == -1:
            return DRIVER_TYPE_FOOMATIC_HPIJS
    # Anything else should be a vendor's PPD.
    return DRIVER_TYPE_VENDOR # vendor's own


class PPDs:
    """
    This class is for handling the list of PPDs returned by CUPS.  It
    indexes by PPD name and device ID, filters by natural language so
    that foreign-language PPDs are not included, and sorts by driver
    type.  If an exactly-matching PPD is not available, it can
    substitute with a PPD for a similar model or for a generic driver.
    """

    # Status of match.
    STATUS_SUCCESS = 0
    STATUS_MODEL_MISMATCH = 1
    STATUS_GENERIC_DRIVER = 2
    STATUS_NO_DRIVER = 3

    def __init__ (self, ppds, language=None):
        """
        @type ppds: dict
        @param ppds: dict of PPDs as returned by cups.Connection.getPPDs()

        @type language: string
	@param language: language name, as given by the first element
        of the pair returned by locale.getlocale()
        """
        print _debugprint
        self.ppds = ppds.copy ()
        self.makes = None
        self.ids = None

        if (language == None or
            language == "C" or
            language == "POSIX"):
            language = "en_US"

        u = language.find ("_")
        if u != -1:
            short_language = language[:u]
        else:
            short_language = language

        to_remove = []
        for ppdname, ppddict in self.ppds.iteritems ():
            try:
                natural_language = ppddict['ppd-natural-language']
            except KeyError:
                continue

            if natural_language == "en":
                # Some manufacturer's PPDs are only available in this
                # language, so always let them though.
                continue

            if natural_language == language:
                continue

            if natural_language == short_language:
                continue

            to_remove.append (ppdname)

        for ppdname in to_remove:
            del self.ppds[ppdname]

        # CUPS sets the 'raw' model's ppd-make-and-model to 'Raw Queue'
        # which unfortunately then appears as manufacturer Raw and
        # model Queue.  Use 'Generic' for this model.
        if self.ppds.has_key ('raw'):
            makemodel = self.ppds['raw']['ppd-make-and-model']
            if not makemodel.startswith ("Generic "):
                self.ppds['raw']['ppd-make-and-model'] = "Generic " + makemodel

    def getMakes (self):
        """
	@returns: a list of strings representing makes, sorted according
        to the current locale
	"""
        self._init_makes ()
        makes_list = self.makes.keys ()
        makes_list.sort (locale.strcoll)
        try:
            # "Generic" should be listed first.
            makes_list.remove ("Generic")
            makes_list.insert (0, "Generic")
        except ValueError:
            pass
        return makes_list

    def getModels (self, make):
        """
	@returns: a list of strings representing models, sorted using
	cups.modelSort()
	"""
        self._init_makes ()
        try:
            models_list = self.makes[make].keys ()
        except KeyError:
            return []
        models_list.sort (cups.modelSort)
        return models_list

    def getInfoFromModel (self, make, model):
        """
	Obtain a list of PPDs that are suitable for use with a
        particular printer model, given its make and model name.

	@returns: a dict, indexed by ppd-name, of dicts representing
        PPDs (as given by cups.Connection.getPPDs)"
	"""
        self._init_makes ()
        try:
            return self.makes[make][model]
        except KeyError:
            return {}

    def getInfoFromPPDName (self, ppdname):
        """
	@returns: a dict representing a PPD, as given by
	cups.Connection.getPPDs
	"""
        return self.ppds[ppdname]

    def orderPPDNamesByPreference (self, ppdnamelist=[]):
        """

	Sort a list of PPD names by (hard-coded) preferred driver
	type.

	@param ppdnamelist: PPD names
	@type ppdnamelist: string list
	@returns: string list
	"""
        if len (ppdnamelist) < 1:
            return ppdnamelist

        dict = self.getInfoFromPPDName (ppdnamelist[0])
        make_model = dict['ppd-make-and-model']
        mfg, mdl = ppdMakeModelSplit (make_model)
        def getDriverTypeWithBias (x, mfg):
            t = _getDriverType (x, ppds=self)
            if mfg == "HP":
                if t == DRIVER_TYPE_FOOMATIC_HPIJS:
                    # Prefer HPIJS for HP devices.
                    t = DRIVER_TYPE_FOOMATIC_HPIJS_ON_HP
                    # For HP LaserJet 12xx/13xx prefer HPIJS over
                    # PostScript, as they do not have enough memory
                    # to render complex graphics with their on-board
                    # PostScript interpreter
                    if re.search(r"(?i)HP[-_]LaserJet_1[23]\d\d", x):
                        t = DRIVER_TYPE_FOOMATIC_RECOMMENDED_NON_POSTSCRIPT
            return t

        def sort_ppdnames (a, b):
            ta = getDriverTypeWithBias (a, mfg)
            tb = getDriverTypeWithBias (b, mfg)
            if ta != tb:
                if tb < ta:
                    return 1
                else:
                    return -1

            # Prefer C locale localized PPDs to other languages,
            # just because we don't know the user's locale.
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

            # String-wise compare.
            if a > b:
                return 1
            elif a < b:
                return -1
            return 0

        ppdnamelist.sort (sort_ppdnames)
        return ppdnamelist

    def getPPDNameFromDeviceID (self, mfg, mdl, description="",
                                commandsets=[], uri=None):
        """
	Obtain a best-effort PPD match for an IEEE 1284 Device ID.
	The status is one of:

	  - L{STATUS_SUCCESS}: the match was successful, and an exact
            match was found

	  - L{STATUS_MODEL_MISMATCH}: a similar match was found, but
            the model name does not exactly match

	  - L{STATUS_GENERIC_DRIVER}: no match was found, but a
            generic driver is available that can drive this device
            according to its command set list

	  - L{STATUS_NO_DRIVER}: no match was found at all, and the
            returned PPD name is a last resort

	@param mfg: MFG or MANUFACTURER field
	@type mfg: string
	@param mdl: MDL or MODEL field
	@type mdl: string
	@param description: DES or DESCRIPTION field, optional
	@type description: string
	@param commandsets: CMD or COMMANDSET field, optional
	@type commandsets: string
	@param uri: device URI, optional (only needed for debugging)
	@type uri: string
	@returns: an integer,string pair of (status,ppd-name)
	"""
        _debugprint ("\n%s %s" % (mfg, mdl))
        self._init_ids ()
        id_matched = False
        try:
            ppdnamelist = self.ids[mfg.lower ()][mdl.lower ()]
            status = self.STATUS_SUCCESS
            id_matched = True
        except KeyError:
            if uri and (uri.startswith ("hp:") or uri.startswith ("hpfax:")):
                # The HPLIP backends make up incorrect IDs.
                if mfg == "HP":
                    try:
                        ppdnamelist = self.ids['hewlett-packard'][mdl.lower ()]
                        status = self.STATUS_SUCCESS
                        id_matched = True
                    except KeyError:
                        pass
            if not id_matched:
                ppdnamelist = None

        _debugprint ("Trying make/model names")
        mfgl = mfg.lower ()
        mdls = None
        self._init_makes ()
        for attempt in range (2):
            for (make, models) in self.makes.iteritems ():
                if make.lower () == mfgl:
                    mdls = models
                    break

            # Try again with replacements.
            if mfgl == "hewlett-packard":
                mfgl = "hp"

        # Remove manufacturer name from model field
        ppdnamelist2 = None
        if mdl.startswith (mfg + ' '):
            mdl = mdl[len (mfg) + 1:]
        if mdl.startswith ('Hewlett-Packard '):
            mdl = mdl[16:]
        if mdl.startswith ('HP '):
            mdl = mdl[3:]
        if mdls and mdls.has_key (mdl):
            ppdnamelist2 = mdls[mdl].keys ()
            status = self.STATUS_SUCCESS
        else:
            # Make use of the model name clean-up in the ppdMakeModelSplit ()
            # function
            (mfg2, mdl2) = ppdMakeModelSplit (mfg + " " + mdl)
            if mdls and mdls.has_key (mdl2):
                ppdnamelist2 = mdls[mdl2].keys ()
                status = self.STATUS_SUCCESS
      
        if ppdnamelist:
            if ppdnamelist2:
                ppdnamelist = ppdnamelist + ppdnamelist2
        elif ppdnamelist2:
            ppdnamelist = ppdnamelist2

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
            _debugprint ("Text-only fallback")
            status = self.STATUS_NO_DRIVER
            ppdnamelist = ["textonly.ppd"]
            tppdfound = 0
            for ppdpath in self.ppds.keys ():
                if ppdpath.endswith (ppdnamelist[0]):
                    tppdfound = 1
                    ppdnamelist = [ppdpath]
                    break
            if tppdfound == 0:
                _debugprint ("No text-only driver?!  Using postscript.ppd")
                ppdnamelist = ["postscript.ppd"]
                psppdfound = 0
                for ppdpath in self.ppds.keys ():
                    if ppdpath.endswith (ppdnamelist[0]):
                        psppdfound = 1
                        ppdnamelist = [ppdpath]
                        break
                if psppdfound == 0:
                    _debugprint ("No postscript.ppd; choosing any")
                    ppdnamelist = [self.ppds.keys ()[0]]

        if id_matched:
            _debugprint ("Checking DES field")
            inexact = set()
            if description:
                for ppdname in ppdnamelist:
                    ppddict = self.ppds[ppdname]
                    id = ppddict['ppd-device-id']
                    if not id: continue
                    # Fetch description field.
                    id_dict = parseDeviceID (id)
                    if id_dict["DES"] != description:
                        inexact.add (ppdname)

            exact = set (ppdnamelist).difference (inexact)
            _debugprint ("discarding: %s" % inexact)
            if len (exact) >= 1:
                ppdnamelist = list (exact)

        # We've got a set of PPDs, any of which will drive the device.
        # Now we have to choose the "best" one.  This is quite tricky
        # to decide, so let's sort them in order of preference and
        # take the first.
        ppdnamelist = self.orderPPDNamesByPreference (ppdnamelist)
        _debugprint (str (ppdnamelist))

        if not id_matched:
            print "No ID match for device %s:" % uri
            print "  <manufacturer>%s</manufacturer>" % mfg
            print "  <model>%s</model>" % mdl
            print "  <description>%s</description>" % description
            try:
                cmd = reduce (lambda x, y: x + ","+ y, commandsets)
            except TypeError:
                cmd = ""

            print "  <commandset>%s</commandset>" % cmd
            print "Using %s" % ppdnamelist[0]

        return (status, ppdnamelist[0])

    def _findBestMatchPPDs (self, mdls, mdl):
        """
        Find the best-matching PPDs based on the MDL Device ID.
        This function could be made a lot smarter.
        """

        _debugprint ("Trying best match")
        mdll = mdl.lower ()
        if mdll.endswith (" series"):
            # Strip " series" from the end of the MDL field.
            mdll = mdll[:-7]
            mdl = mdl[:-7]
        best_mdl = None
        best_matchlen = 0
        mdlnames = mdls.keys ()

        # Perform a case-insensitive model sort on the names.
        mdlnamesl = map (lambda x: (x, x.lower()), mdlnames)
        mdlnamesl.append ((mdl, mdll))
        mdlnamesl.sort (lambda x, y: cups.modelSort(x[1], y[1]))
        i = mdlnamesl.index ((mdl, mdll))
        candidates = [mdlnamesl[i - 1]]
        if i + 1 < len (mdlnamesl):
            candidates.append (mdlnamesl[i + 1])
            _debugprint (candidates[0][0] + " <= " + mdl + " <= " +
                        candidates[1][0])
        else:
            _debugprint (candidates[0][0] + " <= " + mdl)

        # Look at the models immediately before and after ours in the
        # sorted list, and pick the one with the longest initial match.
        for (candidate, candidatel) in candidates:
            prefix = os.path.commonprefix ([candidatel, mdll])
            if len (prefix) > best_matchlen:
                best_mdl = mdls[candidate].keys ()
                best_matchlen = len (prefix)
                _debugprint ("%s: match length %d" % (candidate, best_matchlen))

        # Did we match more than half of the model name?
        if best_mdl and best_matchlen > (len (mdll) / 2):
            ppdnamelist = best_mdl
            if best_matchlen == len (mdll):
                status = self.STATUS_SUCCESS
            else:
                status = self.STATUS_MODEL_MISMATCH
        else:
            status = self.STATUS_NO_DRIVER
            ppdnamelist = None

            # Last resort.  Find the "most important" word in the MDL
            # field and look for a match based solely on that.  If
            # there are digits, try lowering the number of
            # significant figures.
            mdlnames.sort (cups.modelSort)
            mdlitems = map (lambda x: (x.lower (), mdls[x]), mdlnames)
            modelid = None
            for word in mdll.split (' '):
                if modelid == None:
                    modelid = word

                have_digits = False
                for i in range (len (word)):
                    if word[i].isdigit ():
                        have_digits = True
                        break

                if have_digits:
                    modelid = word
                    break

            digits = 0
            digits_start = -1
            digits_end = -1
            for i in range (len (modelid)):
                if modelid[i].isdigit ():
                    if digits_start == -1:
                        digits_start = i
                    digits_end = i
                    digits += 1
            digits_end += 1
            modelnumber = 0
            if digits > 0:
                modelnumber = int (modelid[digits_start:digits_end])
            modelpattern = (modelid[:digits_start] + "%d" +
                            modelid[digits_end:])
            _debugprint ("Searching for model ID '%s', '%s' %% %d" %
                        (modelid, modelpattern, modelnumber))
            ignore_digits = 0
            best_mdl = None
            found = False
            while ignore_digits < digits:
                div = pow (10, ignore_digits)
                modelid = modelpattern % ((modelnumber / div) * div)
                _debugprint ("Ignoring %d of %d digits, trying %s" %
                            (ignore_digits, digits, modelid))

                for (name, ppds) in mdlitems:
                    for word in name.split (' '):
                        if word.lower () == modelid:
                            found = True
                            break

                    if found:
                        best_mdl = ppds.keys ()
                        break

                if found:
                    break

                ignore_digits += 1
                if digits < 2:
                    break

            if found:
                ppdnamelist = best_mdl
                status = self.STATUS_MODEL_MISMATCH

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
                _debugprint ("Missing MFG field for %s" % ppdname)
                bad = True
            if len (lmdl) == 0:
                _debugprint ("Missing MDL field for %s" % ppdname)
                bad = True
            if bad:
                continue

            if not ids.has_key (lmfg):
                ids[lmfg] = {}

            if not ids[lmfg].has_key (lmdl):
                ids[lmfg][lmdl] = []

            ids[lmfg][lmdl].append (ppdname)

        self.ids = ids

def _show_help():
    print "usage: ppds.py [--deviceid] [--list-models] [--list-ids] [--debug]"

def self_test():
    import sys, getopt
    try:
        opts, args = getopt.gnu_getopt (sys.argv[1:], '',
                                        ['help',
                                         'deviceid',
                                         'list-models',
                                         'list-ids',
                                         'debug'])
    except getopt.GetoptError:
        _show_help()
        sys.exit (1)

    stdin_deviceid = False
    list_models = False
    list_ids = False

    for opt, optarg in opts:
        if opt == "--help":
            show_help ()
            sys.exit (0)
        if opt == "--deviceid":
            stdin_deviceid = True
        elif opt == "--list-models":
            list_models = True
        elif opt == "--list-ids":
            list_ids = True

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

    print "\nID matching tests\n"

    idlist = [
        # Format is:
        # (ID string, max status code, expected driver RE match)

        # Specific models
        ("MFG:EPSON;CMD:ESCPL2,BDC,D4,D4PX;MDL:Stylus D78;CLS:PRINTER;"
         "DES:EPSON Stylus D78;", 1, 'Epson Stylus D68'),
        ("MFG:Hewlett-Packard;MDL:LaserJet 1200 Series;"
         "CMD:MLC,PCL,POSTSCRIPT;CLS:PRINTER;", 0, 'HP LaserJet 1200'),
        ("MFG:Hewlett-Packard;MDL:LaserJet 3390 Series;"
         "CMD:MLC,PCL,POSTSCRIPT;CLS:PRINTER;", 0, 'HP LaserJet 3390'),
        ("MFG:Hewlett-Packard;MDL:PSC 2200 Series;CMD:MLC,PCL,PML,DW-PCL,DYN;"
         "CLS:PRINTER;1284.4DL:4d,4e,1;", 0, "HP PSC 2210"),
        ("MFG:HP;MDL:PSC 2200 Series;CLS:PRINTER;DES:PSC 2200 Series;",
         1, "HP PSC 2210"),# from HPLIP
        ("MFG:HEWLETT-PACKARD;MDL:DESKJET 990C;CMD:MLC,PCL,PML;CLS:PRINTER;"
         "DES:Hewlett-Packard DeskJet 990C;", 0, "HP DeskJet 990C"),
        ("CLASS:PRINTER;MODEL:HP LaserJet 6MP;MANUFACTURER:Hewlett-Packard;"
         "DESCRIPTION:Hewlett-Packard LaserJet 6MP Printer;"
         "COMMAND SET:PJL,MLC,PCLXL,PCL,POSTSCRIPT;", 0, "HP LaserJet 6MP"),
        ("MFG:Canon;CMD:BJL,BJRaster3,BSCCe;SOJ:TXT01;MDL:iP3000;CLS:PRINTER;"
         "DES:Canon iP3000;VER:1.09;STA:10;FSI:03;", 1, "Canon PIXMA iP3000"),
        ("MFG:HP;MDL:Deskjet 5400 series;CMD:MLC,PCL,PML,DW-PCL,DESKJET,DYN;"
         "1284.4DL:4d,4e,1;CLS:PRINTER;DES:5440;", 1, "HP DeskJet 5440"),
        ("MFG:Hewlett-Packard;MDL:HP LaserJet 3390;"
         "CMD:PJL,MLC,PCL,POSTSCRIPT,PCLXL;",
         0, "HP LaserJet 3390.*Postscript"),

        # Generic models
        ("MFG:New;MDL:Unknown PS Printer;CMD:POSTSCRIPT;",
         2, "Generic postscript printer"),
        ("MFG:New;MDL:Unknown PCL6 Printer;CMD:PCLXL;", 2, "Generic PCL 6"),
        ("MFG:New;MDL:Unknown PCL5e Printer;CMD:PCL5e;", 2, "Generic PCL 5e"),
        ("MFG:New;MDL:Unknown PCL5c Printer;CMD:PCL5c;", 2, "Generic PCL 5c"),
        ("MFG:New;MDL:Unknown PCL5 Printer;CMD:PCL5;", 2, "Generic PCL 5"),
        ("MFG:New;MDL:Unknown PCL3 Printer;CMD:PCL;", 2, "Generic PCL"),
        ("MFG:New;MDL:Unknown ESC/P Printer;CMD:ESCP2E;", 2, "Generic ESC/P"),
        ("MFG:New;MDL:Unknown Printer;", 100, None),
        ]

    if stdin_deviceid:
        idlist = [raw_input ('Device ID: ')]

    all_passed = True
    for id, max_status_code, modelre in idlist:
        id_dict = parseDeviceID (id)
        (status, ppdname) = ppds.getPPDNameFromDeviceID (id_dict["MFG"],
                                                         id_dict["MDL"],
                                                         id_dict["DES"],
                                                         id_dict["CMD"])
        if status < max_status_code:
            success = True
        elif status == max_status_code:
            ppddict = ppds.getInfoFromPPDName (ppdname)
            match = re.match (modelre, ppddict['ppd-make-and-model'], re.I)
            success = match != None
        else:
            success = False

        if success:
            result = "PASS"
        else:
            result = "*** FAIL ***"

        print "%s: %s %s" % (result, id_dict["MFG"], id_dict["MDL"])
        all_passed = all_passed and success

    if not all_passed:
        raise RuntimeError

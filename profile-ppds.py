#!/usr/bin/python
import cups
import cupshelpers
import hotshot
import hotshot.stats

ppds = cupshelpers.ppds.PPDs (cups.Connection ().getPPDs ())
prof = hotshot.Profile ("a.prof")
prof.runcall (lambda: ppds.getPPDNameFromDeviceID('','',''))
prof.close ()
stats = hotshot.stats.load ("a.prof")
stats.sort_stats ('time')
stats.print_stats (100)

#!/usr/bin/python

## system-config-printer

## Copyright (C) 2008, 2009, 2010 Red Hat, Inc.
## Authors:
##  Tim Waugh <twaugh@redhat.com>

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

import config
import gettext
gettext.install(domain=config.PACKAGE, localedir=config.localedir, unicode=True)

printer_error_policy = dict()
printer_op_policy = dict()
job_sheets = dict()
job_options = dict()
ppd = dict()
backends = dict()

class TranslationDict:
    STR = {}

    def __init__ (self, d):
        self.STR = d

    def get (self, str):
        return self.STR.get (str, str)

def init ():
    ## IPP strings

    # Names of printer error policies
    global printer_error_policy
    printer_error_policy = TranslationDict ({
            "abort-job": _("Abort job"),
            "retry-current-job": _("Retry current job"),
            "retry-job": _("Retry job"),
            "stop-printer": _("Stop printer")
            })
    
    # Names of printer operation policies
    global printer_op_policy
    printer_op_policy = TranslationDict ({
            "default": _("Default behavior"),
            "authenticated": _("Authenticated")
            })

    # Names of banner pages.
    global job_sheets
    job_sheets = TranslationDict ({
            "none": _("None"),
            "classified": _("Classified"),
            "confidential": _("Confidential"),
            "secret": _("Secret"),
            "standard": _("Standard"),
            "topsecret": _("Top secret"),
            "unclassified": _("Unclassified")
            })

    # Names of job-hold-until values.
    global job_options
    job_options["job-hold-until"] = TranslationDict ({
            "no-hold": _("No hold"),
            "indefinite": _("Indefinite"),
            "day-time": _("Daytime"),
            "evening": _("Evening"),
            "night": _("Night"),
            "second-shift": _("Second shift"),
            "third-shift": _("Third shift"),
            "weekend": _("Weekend")
            })

    ## Common PPD strings

    # Foomatic strings

    # These are PPD option and group names and values.
    global ppd
    ppd = TranslationDict ({
            "General": _("General"),

            # HPIJS options
            "Printout Mode": _("Printout mode"),
            "Draft (auto-detect paper type)":
                _("Draft (auto-detect-paper type)"),
            "Draft Grayscale (auto-detect paper type)":
                _("Draft grayscale (auto-detect-paper type)"),
            "Normal (auto-detect paper type)":
                _("Normal (auto-detect-paper type)"),
            "Normal Grayscale (auto-detect paper type)":
                _("Normal grayscale (auto-detect-paper type)"),
            "High Quality (auto-detect paper type)":
                _("High quality (auto-detect-paper type)"),
            "High Quality Grayscale (auto-detect paper type)":
                _("High quality grayscale (auto-detect-paper type)"),
            "Photo (on photo paper)": _("Photo (on photo paper)"),
            "Best Quality (color on photo paper)":
                _("Best quality (color on photo paper)"),
            "Normal Quality (color on photo paper)":
                _("Normal quality (color on photo paper)"),

            "Media Source": _("Media source"),
            "Printer default": _("Printer default"),
            "Photo Tray": _("Photo tray"),
            "Upper Tray": _("Upper tray"),
            "Lower Tray": _("Lower tray"),
            "CD or DVD Tray": _("CD or DVD tray"),
            "Envelope Feeder": _("Envelope feeder"),
            "Large Capacity Tray": _("Large capacity tray"),
            "Manual Feeder": _("Manual feeder"),
            "Multi Purpose Tray": _("Multi-purpose tray"),

            "Page Size": _("Page size"),
            "Custom": _("Custom"),
            "Photo or 4x6 inch index card": _("Photo or 4x6 inch index card"),
            "Photo or 5x7 inch index card": _("Photo or 5x7 inch index card"),
            "Photo with tear-off tab": _("Photo with tear-off tab"),
            "3x5 inch index card": _("3x5 inch index card"),
            "5x8 inch index card": _("5x8 inch index card"),
            "A6 with tear-off tab": _("A6 with tear-off tab"),
            "CD or DVD 80 mm": _("CD or DVD 80mm"),
            "CD or DVD 120 mm": _("CD or DVD 120mm"),

            "Double-Sided Printing": _("Double-sided printing"),
            "Long Edge (Standard)": _("Long edge (standard)"),
            "Short Edge (Flip)": _("Short edge (flip)"),
            "Off": _("Off"),

            "Resolution, Quality, Ink Type, Media Type":
                _("Resolution, quality, ink type, media type"),
            "Controlled by 'Printout Mode'": _("Controlled by 'Printout mode'"),
            "300 dpi, Color, Black + Color Cartr.":
                _("300 dpi, color, black + color cartridge"),
            "300 dpi, Draft, Color, Black + Color Cartr.":
                _("300 dpi, draft, color, black + color cartridge"),
            "300 dpi, Draft, Grayscale, Black + Color Cartr.":
                _("300 dpi, draft, grayscale, black + color cartridge"),
            "300 dpi, Grayscale, Black + Color Cartr.":
                _("300 dpi, grayscale, black + color cartridge"),
            "600 dpi, Color, Black + Color Cartr.":
                _("600 dpi, color, black + color cartridge"),
            "600 dpi, Grayscale, Black + Color Cartr.":
                _("600 dpi, grayscale, black + color cartridge"),
            "600 dpi, Photo, Black + Color Cartr., Photo Paper":
                _("600 dpi, photo, black + color cartridge, photo paper"),
            "600 dpi, Color, Black + Color Cartr., Photo Paper, Normal":
                _("600 dpi, color, black + color cartridge, photo paper, normal"),
            "1200 dpi, Photo, Black + Color Cartr., Photo Paper":
                _("1200 dpi, photo, black + color cartridge, photo paper"),
            })

    ## Common backend descriptions
    global backends
    backends = TranslationDict ({
            "Internet Printing Protocol (ipp)":
                _("Internet Printing Protocol (ipp)"),
            "Internet Printing Protocol (http)":
                _("Internet Printing Protocol (http)"),
            "Internet Printing Protocol (https)":
                _("Internet Printing Protocol (https)"),
            "LPD/LPR Host or Printer":
                _("LPD/LPR Host or Printer"),
            "AppSocket/HP JetDirect":
                _("AppSocket/HP JetDirect"),
            "Serial Port #1":
                _("Serial Port #1"),
            "LPT #1":
                _("LPT #1"),
            "Windows Printer via SAMBA":
                _("Windows Printer via SAMBA"),
            })

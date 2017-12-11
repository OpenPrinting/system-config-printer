#!/usr/bin/python3

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
gettext.install(domain=config.PACKAGE, localedir=config.localedir)

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
           
           #HP
            "Print Quality": _("Print Quality"),
            "Automatic": _("Automatic"),
           
            "Printing Quality": _("Printing Quality"),
            "Draft": _("Draft"),
            "Normal": _("Normal"),
            "Normal Color": _("Normal Color"),
            "Normal Grayscale": _("Normal Grayscale"),
            "Draft Color": _("Draft Color"),
            "Draft Grayscale": _("Draft Grayscale"),
            "Best": _("Best"),
            "High-Resolution Photo": _("High-Resolution Photo"),
            "Fast Draft": _("Fast Draft"),
            
            "Installed Cartridges": _("Installed Cartridges"),
            "Black Only": _("Fast Only"),
            "TriColor Only": _("Fast Only"),
            "Photo Only": _("Photo Only"),
            "Black and TriColor": _("Black and TriColor"),
            "Photo and TriColor": _("Photo and TriColor"),
            
            "Resolution": _("Resolution"),
            
            "Color Mode": _("Color Mode"),
            "Hight Quality Grayscale": _("Hight Quality Grayscale"),
            "Black Only Grayscale": _("Black Only Grayscale"),
            
            "Quality": _("Quality"),
            "High Resolution ": _("High Resolution "),
            "Paper Source": _("Paper source"),
                "Auto Source": _("Auto Source"),
                "Manual Feed": _("Manual Feed"),
                "Middle Tray": _("Middle Tray"),
                "Upper or Only One InputSlot": _("Upper or Only One InputSlot"),
                "Multi-purpose Tray": _("Multi-purpose Tray"),
                "Drawer 1 ": _("Drawer 1 "),
                "Drawer 2 ": _("Drawer 2 "),
                "Tray 1": _("Tray 1"),
                "Auto Select": _("Auto Select"),
                    
            "Media Type": _("Media Type"),
                "Bond": _("Bond"),
                "Color": _("Color"),
                "Envelope": _("Envelope"),
                "Labels": _("Labels"),
                "Standard Paper": _("Standard Paper"),
                "Heavy": _("Heavy"),
                "Light": _("Light"),
                "Recycled": _("Recycled"),
                "Transparency": _("Transparency"),
                "Plain Paper": _("Plain Paper"),
                "Plain": _("Plain"),
                "Photo Paper)": _("Photo Paper)"),
                "Transparency Film": _("Transparency Film"),
                "CD or DVD Media": _("CD or DVD Media"),
            "Print Density": _("Print Density"),
            "Extra Light (1)": _("Extra Light (1)"),
            "Light (2)": _("Light (2)"),
            "Medium (3)": _("Medium (3)"),
            "Dark (4)": _("Dark (4)"),
            "Extra Dark (5)": _("Extra Dark (5)"),
            "Copies": _("Copies"),
            
            "Adjustment": _("Adjustment"),
            "Halftone Algorithm": _("Halftone Algorithm"),
            "Default": _("Default"),
            
            "Miscellaneous": _("Miscellaneous"),
            "N-up Orientation": _("N-up Orientation"),
            "N-up Printing": _("N-up Printing"),
            "Landscape": _("Landscape"),
            "Seascape": _("Seascape"),
            "Media Size": _("Media Size"),
            "Output Mode": _("Output Mode"),
                 "Grayscale": _("Grayscale"),
            
            #Brother      
            "Two-Sided": _("Two-Sided"),
            "Print Settings": _("Print Settings"),
            "Print Settings (Advanced)": _("Print Settings  (Advanced)"),
            "Color Settings": _("Color Settings"),
            "Color Settings (Advanced)": _("Color Settings (Advanced)"),                     
            "Brightness": _("Brightness"),
            "Contrast": _("Contrast"),
            "Red": _("Red"),            
            "Green": _("Green"),            
            "Blue": _("Blue"),
                      
            #Epson xp serie
            "_Media Size": _("_Media Size"),
            "_Grayscale": _("_Grayscale"),
            "_Brightness": _("_Brightness"),
            "_Contrast": _("_Contrast"),
            "_Saturation": _("_Saturation"),
            "On": _("On"),
            # Options 
            "Installable Options": _("Installable Options"),
            "Duplexer Installed": _("Duplexer Installed"),
            
            # Canon
            "Color Model": _("Color Model"),
            "Color Precision": _("Color Precision"),
            "Resolution ": _("Resolution "),
            "Printer Features Common": _("Printer Features Common"),
            "CD Hub Size": _("CD Hub Size"),
            "Ink Type": _("Ink Type"),
            "Toner Save ": _("Toner Save "),
            "ON": _("ON"),      
            "Toner Density": _("Toner Density"),
            "Media Type ": _("Media Type "),
            "Collate ": _("Collate "),
            "Image Refinement ": _("Image Refinement "),
            "Halftones ": _("Halftones "),
            "Duplex": _("Duplex"),
            "OFF": _("OFF"),
            "ON (Long-edged Binding)": _("ON (Long-edged Binding)"),
            "ON (Short-edged Binding)": _("ON (Short-edged Binding)"),
            #Samsung
            "Paper Size": _("Paper Size"),
            "Paper Type": _("Paper Type"),
            "Thin": _("Thin"),
            "Thick": _("Thick"),
            "Thicker": _("Thicker") ,     
            "Edge Enhance": _("Edge Enhance"),
            "Skip Blank Pages": _("Skip Blank Pages"),
            "Double-sided Printing": _("Double-sided Printing"),
            "None": _("None"),
            "Reverse Duplex Printing": _("Reverse Duplex Printing"),
            "Long Edge": _("Long Edge"),
            "Short Edge": _("Short Edge"),
            "Two-sided": _("Two-sided"),
            "Long Edge": _("Long Edge"),
            "Short Edge": _("Short Edge"),
      
            #Ricoh
            "Finisher": _("Finisher"),
            "Option Tray": _("Option Tray"),
            "External Tray": _("External Tray"),
            "Internal Tray": _("Internal Tray"),
            "Internal Tray 2": _("Internal Tray 2"),
            "Internal Shift Tray": _("Internal Shift Tray"),
            "Not Installed": _("Not Installed"),
            "Installed": _("Installed"),
            "PageSize": _("PageSize"),
            "InputSlot": _("InputSlot"),
                "Tray 2": _("Tray 2"),
                "Tray 3": _("Tray 3"),
            "Tray 4": _("Tray 4"),        
                "Bypass Tray": _("Bypass Tray"),        
            "Destination": _("Destination"),
            "Staple": _("Staple"),    
            "Punch": _("Punch"),
            "Toner Saving": _("Toner Saving"),
            "Gradation": _("Gradation"),
            "Fast": _("Fast"),
            
            # HPIJS options
            "Printout Mode": _("Printout mode"),
            "Draft (auto-detect paper type)":
                _("Draft (auto-detect-paper type)"),
            "Draft (Color cartridge)":
                _("Draft (Color cartridge)"),    
            "Draft Grayscale (Black cartridge)":
                _("Draft grayscale (Black cartridge)"),
            "Draft Grayscale (auto-detect paper type)":
                _("Draft grayscale (auto-detect-paper type)"),
            "Normal (Color cartridge)":
                _("Normal (Color cartridge)"),
            "Normal Grayscale (Black cartridge)":
                _("Normal grayscale (Black cartridge)"),
            "Normal (auto-detect paper type)":
                _("Normal (auto-detect-paper type)"),
            "Normal Grayscale (auto-detect paper type)":
                _("Normal grayscale (auto-detect-paper type)"),
            "High Quality (auto-detect paper type)":
                _("High quality (auto-detect-paper type)"),
            "High Quality Grayscale (auto-detect paper type)":
                _("High quality grayscale (auto-detect-paper type)"),
            "High Quality (Color cartridge)":
                _("High quality (Color cartridge)"),
            "High Quality Grayscale (Black cartridge)":
                _("High quality grayscale (Black cartridge)"),
            "Photo (on photo paper)": _("Photo (on photo paper)"),
            "Photo (Color cartridge, on photo paper)": _("Photo (Color cartridge, on photo paper)"),
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
            "Multi Purpose Tray ": _("Multi-purpose tray "),

            "Page Size": _("Page size"),
            "Custom": _("Custom"),
            "Letter": _("Letter"),
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
            "300 dpi, Color, Color Cartr.":
                _("300 dpi, Color, Color Cartr."),
            "300 dpi, Color, Black + Color Cartr.":
                _("300 dpi, color, black + color cartridge"),
            "300 dpi, Draft, Color, Color Cartr.":
                _("300 dpi, Draft, Color, Color Cartr."),
            "300 dpi, Draft, Color, Black + Color Cartr.":
                _("300 dpi, draft, color, black + color cartridge"),
            "300 dpi, Draft, Grayscale, Black Cartr.":
                _("300 dpi, Draft, Grayscale, Black Cartr."),
            "300 dpi, Grayscale, Black Cartr.":
                _("300 dpi, Grayscale, Black Cartr."),
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

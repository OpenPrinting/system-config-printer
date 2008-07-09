#!/usr/bin/env python

## Printing troubleshooter

## Copyright (C) 2008 Red Hat, Inc.
## Copyright (C) 2008 Tim Waugh <twaugh@redhat.com>

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

import locale

from base import *

class Locale(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Locale issues")
        troubleshooter.new_page (gtk.Label (), self)

    def display (self):
        return False

    def collect_answer (self):
        answers = {}

        (messages, encoding) = locale.getlocale (locale.LC_MESSAGES)
        (ctype, encoding) = locale.getlocale (locale.LC_CTYPE)
        answers['user_locale_messages'] = messages
        answers['user_locale_ctype'] = ctype

        try:
            i18n = file ("/etc/sysconfig/i18n").readlines ()
            for line in i18n:
                if line.startswith ("LANG="):
                    system_lang = line[5:].strip ('\n"')
                    dot = system_lang.find ('.')
                    if dot != -1:
                        system_lang = system_lang[:dot]
        except:
            system_lang = None

        answers['system_locale_lang'] = system_lang

        return answers

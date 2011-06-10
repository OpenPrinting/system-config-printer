## Copyright (C) 2008 Rui Matos <tiagomatos@gmail.com>

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

class SearchCriterion:
    SUBJECT_NAME     = 0
    SUBJECT_DESC     = 1
    SUBJECT_MANUF    = 2
    SUBJECT_MODEL    = 3
    SUBJECT_URI      = 4
    SUBJECT_MEDIA    = 5
    SUBJECT_STAT     = 6
    SUBJECT_COUNT    = 7
    SUBJECT_LOCATION = 8

    RULE_IS      = 0
    RULE_ISNOT   = 1
    RULE_CONT    = 2
    RULE_NOTCONT = 3
    RULE_COUNT   = 4

    def __init__ (self,
                  subject = SUBJECT_NAME,
                  rule    = RULE_CONT,
                  value   = ""):
        self.subject = subject
        self.rule = rule
        self.value = value

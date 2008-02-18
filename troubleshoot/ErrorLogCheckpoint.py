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

import cups
import os
import tempfile
from base import *
from base import _
class ErrorLogCheckpoint(Question):
    def __init__ (self, troubleshooter):
        Question.__init__ (self, troubleshooter, "Error log checkpoint")
        troubleshooter.new_page (gtk.Label (), self)

    def display (self):
        return False

    def collect_answer (self):
        answers = self.troubleshooter.answers
        if not answers['cups_queue_listed']:
            return {}

        # Fail if auth required.
        cups.setPasswordCB (lambda x: '')
        cups.setServer ('')
        try:
            c = cups.Connection ()
        except RuntimeError:
            return {}

        (tmpfd, tmpfname) = tempfile.mkstemp ()
        os.close (tmpfd)
        try:
            c.getFile ('/admin/log/error_log', tmpfname)
        except cups.IPPError:
            os.remove (tmpfname)
            return {}

        statbuf = os.stat (tmpfname)
        os.remove (tmpfname)
        return { 'error_log_checkpoint': statbuf[6] }

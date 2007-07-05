## system-config-printer

## Copyright (C) 2006 Red Hat, Inc.
## Copyright (C) 2006 Florian Festi <ffesti@redhat.com>

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

from HTMLParser import HTMLParser
import htmlentitydefs

class HTML2PangoParser(HTMLParser):

    supported_tags = {
        "b" : "b",
        "big" : "big",
        "i" : "i",
        "s" : "s",
        "strike" : "s",
        "sub" : "sub",
        "small" : "small",
        "tt" : "tt",
        "u" : "u",
        #"a" : "u",
        }

    def __init__(self, output, show_urls=True):
        HTMLParser.__init__(self)
        self.output = output
        self.show_urls = show_urls
        self.a_href = '' 

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag=="a":
            for attr, value in attrs:
                if attr=="href":
                    self.a_href = value
            self.output.write("<u>")
        if tag=="span":
            pass
            # XXX
            #self.output.write("<span>")
        
        if self.supported_tags.has_key(tag):
            self.output.write("<%s>" % self.supported_tags[tag])

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag=="a":
            if self.a_href and self.show_urls:
                self.output.write("</u> (<u>")
                self.handle_data(self.a_href)
                self.output.write("</u>)")
            else:
                self.output.write("</u>")

        if (self.supported_tags.has_key(tag) or
            tag=="span"):
            self.output.write("</%s>" % self.supported_tags[tag])

    def handle_data(self, data):
        # & quoting
        data = data.replace("&", "&amp;")
        self.output.write(data)

    def handle_charref(self, name):
        self.output.write("&%s;" % name) # XXX convert to unicode?

    def handle_entityref(self, name):
        if htmlentitydefs.name2codepoint.has_key(name):
            self.output.write(unichr(htmlentitydefs.name2codepoint[name]))
        else:
            self.handle_data("&" + name)

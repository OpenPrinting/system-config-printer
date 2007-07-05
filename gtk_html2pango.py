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
        print name
        if htmlentitydefs.name2codepoint.has_key(name):
            self.output.write(unichr(htmlentitydefs.name2codepoint[name]))
        else:
            self.handle_data(name)

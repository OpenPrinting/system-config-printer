#!/usr/bin/env python
import re
from rhpl.Conf import Conf

class Directive:
    separator = ' '
    separators = ' '

    def __init__(self, name, values, line=None, line_nr=0):

        if line is None:
            line = name + self.separator + self.separator.join(self.values)
            
        self.name = name
        self.values = values
        self.line = line
        self.line_rn = line_nr
        self.block = None # set if added to block

    def change(self, name, values):
        line = name + self.separator + self.separator.join(self.values)
        self.block.config.seek(self.line)
        self.block.config.setline(line)
        self.line = line

    def __str__(self):
        return "%s: %r" % (self.name, self.values)

class Block(dict):
    def __init__(self, config, name, values, start_line, start_line_nr):
        self.name = name
        self.values = values
        self.line = start_line
        self.line_nr = start_line_nr
        self.lines = [start_line]
        
    def __str__(self):
        result = []
        for subdirectives in self.itervalues():
            for directive in subdirectives:
                result.append(str(directive))
        return ("<%s %r>\n" % (self.name, self.values)  +
                '\n'.join(result) +
                '\n<%s/>\n' % self.name)

    def _end(self, line, line_nr):
        self.end_line = line
        self.end_line_nr = line_nr

    def _add(self, directive):
        l = self.setdefault(directive.name, [])
        l.append(directive)
        directive.block = self

    def add(self, directive):
        name = directive.name
        if self.has_key(name):
            self.config.seek(self[name][-1])
            self.config.nextline()
        else:
            self.config.seek(self.end_line)
            self[name] = []
        self.config.insertline(directive.line)            
        self[name].append(directive)
        directive.block = self

    def remove(self, directive):
        self.conf.deleteline(directive.line)
        self[directive.name].remove(directive)
        if not self[directive.name]:
            del self[directive.name]

class CupsConfig(Conf):

    comment = "#"
    
    directives = [
        'AccessLog',
        'Allow',
        'AuthClass',
        'AuthGroupName',
        'AuthType',
        'AutoPurgeJobs',
        'BrowseAddress',
        'BrowseAllow',
        'BrowseDeny',
        'BrowseInterval',
        'BrowseOrder',
        'BrowsePoll',
        'BrowsePort',
        'BrowseProtocols',
        'BrowseRelay',
        'BrowseShortNames',
        'BrowseTimeout',
        'Browsing',
        'Classification',
        'ClassifyOverride',
        'ConfigFilePerm',
        'DataDir',
        'DefaultCharset',
        'DefaultLanguage',
        'Deny',
        'DocumentRoot',
        'Encryption',
        'ErrorLog',
        'FaxRetryInterval',
        'FaxRetryLimit',
        'FileDevice',
        'FilterLimit',
        'FilterNice',
        'FontPath',
        'Group',
        'HideImplicitMembers',
        'HostNameLookups',
        'ImplicitAnyClasses',
        'ImplicitClasses',
        'Include',
        'KeepAlive',
        'KeepAliveTimeout',
        'LimitRequestBody',
        'Listen',
        'LogFilePerm',
        'LogLevel',
        'MaxClients',
        'MaxClientsPerHost',
        'MaxCopies',
        'MaxJobs',
        'MaxJobsPerPrinter',
        'MaxJobsPerUser',
        'MaxLogSize',
        'MaxRequestSize',
        'Order',
        'PageLog',
        'Port',
        'PreserveJobFiles',
        'PreserveJobHistory',
        'Printcap',
        'PrintcapFormat',
        'PrintcapGUI',
        'ReloadTimeout',
        'RemoteRoot',
        'RequestRoot',
        'Require',
        'RIPCache',
        'RunAsUser',
        'Satisfy',
        'ServerAdmin',
        'ServerBin',
        'ServerCertificate',
        'ServerKey',
        'ServerName',
        'ServerRoot',
        'ServerTokens',
        'SSLListen',
        'SSLPort',
        'SystemGroup',
        'TempDir',
        'Timeout',
        'User',]


    sections = [
        '<Limit',
        '<LimitExcept',
        '<Location',]

    end_sections = [
        '</Limit>',
        '</LimitExcept>',
        '</Location>',]

    def __init__(self, filename='cups.conf'):
        Conf.__init__(self, filename, '#', '\t ,', ' \t',
                      merge=1)
        self.read()

    def read(self):
        Conf.read(self)
        self.parse()

    def parse(self):
        block_stack = []

        block = Block(self, '__MAIN__', [], None, -1)
        self.start_block = block

        self.rewind()

        for line in self:
            fields = self.getfields()
            if len(fields) == 0: continue
            directive = fields[0]
            values = fields[1:]
            #line = line.lstrip()
            #directive = re.match('\S+', line)
            if directive:
                nr = self.tell()
                #directive = directive.group()
                if directive in self.sections:
                    block_stack.append(block)
                    block = Block(self, directive, values, line, nr)
                    block_stack[-1]._add(block)
                elif directive in self.end_sections:
                    block._end(line, nr)
                    block = block_stack.pop()
                elif directive in self.directives:
                    block._add(Directive(directive, values, line, nr))

    def seek(self, position):
        if isinstance(position, object):
            position = position.line
            
        if isinstance(position, int):
            self.line = line
        else:
            for nr, cfg_line in enumerate(self.lines):
                if cfg_line is position:
                    self.line = nr
                    break
            self.line = len(self.lines)

    def __iter__(self):
        """does not rewind!!! Starts at current position"""
        while self.findnextcodeline():
            yield self.getline()
            self.nextline()
            
def main():
    cupsd_conf = CupsConfig("cupsd.conf")
    block = cupsd_conf.start_block
    print block

if __name__=="__main__":
    main()

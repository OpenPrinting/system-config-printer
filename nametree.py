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

from pprint import pprint

import bisect, os.path

class TreeNode:

    def __init__(self, name, start, depth, leafs):
        self.name = name
        self.leafs = leafs
        self.start = start
        if leafs:
            self.end = leafs[-1].end
        else:
            self.end = self.start + 1
        self.depth = depth

    def __str__(self, indent=0):
        return (" " * indent + self.name  + '\n' +
                "".join(
            [leaf.__str__(indent + len(self.name)) for leaf in self.leafs]))

    def __cmp__(self, other):
        try:
            return cmp(self.start, other.start)
        except AttributeError:
            return cmp(self.start, other)
        
    def collapse(self, start, end, depth, mindepth=1, minwidth=0):
        _depth = depth - self.depth
        if _depth<mindepth: return

        # get first leaf
        _start = bisect.bisect_left(self.leafs, start)
        if _start==len(self.leafs):
            _start -=  1
        if self.leafs[_start].start>start:
            _start -= 1

        # if already collapsed
        if self.leafs[_start].end >= end:
            # go down the tree
            self.leafs[_start].collapse(start, end, depth,
                                        mindepth, minwidth)
            return
        
        # get last leaf
        _end = bisect.bisect_left(self.leafs, end)
        if _end==len(self.leafs) or self.leafs[_end].end > end:
            _end -= 1
        
        name = self.leafs[_start].name[:_depth]

        _end += 1 # compensate Python slicing

        if minwidth and (_end-_start<minwidth): return

        self.leafs[_start:_end] = [
            TreeNode(name, start, depth,
                     [l.reduce(_depth) for l in self.leafs[_start:_end]])]
        # check if everything worked
        if self.leafs[_start].start != start or self.leafs[_start].end != end:
            print "ERROR", self.leafs[_start].start, self.leafs[_start].end
            raise ValueError

    def reduce(self, length):
        if len(self.name) < length:
            print `self.name`, length
            raise ValueError
        self.name = self.name[length:]
        return self


def BuildTree(names, mindepth=1, minwidth=0):
    # len of common prefix between two following lines
    matches = [len(os.path.commonprefix([first, second]))
               for first, second in zip([""]+ names[:-1],
                                        names)]
    
    collapse = {}
    length = len(matches)
    for nr, match in enumerate(matches):
        # check if already found
        found = False
        for start, end in collapse.get(match, []):
            if start<=nr<end:
                found = True
                break
        if found: continue
        # get range
        start = end = nr
        while True:
            if matches[start]<match or start==0: break
            start -= 1
        while True:
            end += 1
            if end==length or matches[end]<match: break
        collapse.setdefault(match, []).append((start, end))

    # tree with empty root and leafs
    tree = TreeNode('', 0, 0,
                    [TreeNode(name, nr, 0, [])
                     for nr, name in enumerate(names)])
    
    depths = collapse.keys()
    depths.sort()

    for depth in depths:
        for start, end in collapse[depth]:
            tree.collapse(start, end, depth, mindepth, minwidth)

    return tree

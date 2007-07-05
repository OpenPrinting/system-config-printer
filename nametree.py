class NamedList(list):

    def __init__(self, name, *entries):
        self.name = name
        self.extend(entries)

class NameTree:

    def __init__(self, names):
        self.names = names
        
    def match(self, first, second):
        i = 0
        for f, s in zip(first, second):
            if f!=s: return i
            i += 1
        return i
            
    def collapse(self, names, matches, from_, to, depth):
        names[from_:to] = [NamedList(list[from_][:depth],
                                   [name[depth:] for name in names[from_:to]])]
        matches[from_:to] = [[match-depth for match in matches[from_:to]]]

    def get_tree(self):
        stack = []
        list = []
        prefix = ""
        length = 0

        previous = ""
        matches = []
        for name in self.names:
            match = self.match(name, previous)
            print name, match
            matches.append(match)
            previous = name

        print matches

        idx = 0
        while True:
            if matches[idx]>0:
                i = idx
            else:
                idx+=1


                
        split_names = []
        for nr, name in enumerate(self.names):
            split = matches[nr:nr+2]
            split.sort()
            splitnames = ()

            for name in names: print name

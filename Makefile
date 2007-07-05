NAME=system-config-printer
VERSION=0.7.6
TAG=`echo $(NAME)-$(VERSION) | tr . _`

SOURCES=cupsd.py         \
	cupshelpers.py   \
	foomatic.py      \
	nametree.py      \
	optionwidgets.py \
	probe_printer.py \
	system-config-printer.py \
	system-config-printer \
	gtk_label_autowrap.py \
	gtk_html2pango.py \
	system-config-printer.glade \
	system-config-printer.gladep

DIST=Makefile \
	COPYING NEWS README TODO ChangeLog \
	system-config-printer.desktop

clean:
	-rm -rf *.pyc *~ *.bak *.orig

tag:
	cvs tag -c $(TAG)

dist:
	rm -rf $(NAME)
	cvs export -r $(TAG) $(NAME)
	mkdir $(NAME)-$(VERSION)
	cd $(NAME); cp -a $(SOURCES) $(DIST) ../$(NAME)-$(VERSION); cd ..
	tar jcf $(NAME)-$(VERSION).tar.bz2 $(NAME)-$(VERSION)
	rm -rf $(NAME)-$(VERSION) $(NAME)

.PHONY: clean tag dist install


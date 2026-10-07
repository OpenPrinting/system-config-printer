SYSTEM-CONFIG-PRIN(1) ["system-config-printer" ["Man pages"]]

# NAME

system-config-printer - configure a CUPS server

# SYNOPSIS

*system-config-printer* [[--show-jobs _printer_] | [--debug] | [--help]]

# DESCRIPTION

*system-config-printer* configures a CUPS server. It uses the CUPS API (bound
to Python with pycups) to do this.  The communication with the server is
performed using IPP.  As a result, it is equally able to configure a remote
CUPS server as a local one.

# OPTIONS

*--help*
	Display a short usage message.

*--show-jobs* _printer_
	Show the named print queue.

*--debug*
	Enable debugging output.

# AUTHOR

*Tim Waugh* <twaugh@redhat.com>
	Author.

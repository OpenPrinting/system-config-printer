/* -*- Mode: C; c-file-style: "gnu" -*-
 * udev-configure-printer - a udev callout to configure print queues
 * Copyright (C) 2009 Red Hat, Inc.
 * Author: Tim Waugh <twaugh@redhat.com>
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
 *
 */

/*
 * The protocol for this program is that it is called by udev with
 * these arguments:
 *
 * 1. "add" or "remove"
 * 2. For "add":    the path (%p) of the device
 *    For "remove": the CUPS device URI corresponding to the queue
 *
 * For "add", it will output the following to stdout:
 *
 * REMOVECMD="$0 remove $DEVICE_URI"
 *
 * where $0 is argv[0] and $DEVICE_URI is the CUPS device URI
 * corresponding to the queue.
 */

#include <stdio.h>
#include <syslog.h>

int
do_add (const char *cmd, const char *path)
{
  syslog (LOG_DEBUG, "add %s", path);
  printf ("REMOVECMD=\"%s remove %s\"\n", cmd, "uri");
  return 0;
}

int
do_remove (const char *uri)
{
  syslog (LOG_DEBUG, "remove %s", uri);
  return 0;
}

int
main (int argc, char **argv)
{
  int add;

  openlog ("udev-configure-printer", 0, LOG_LPR);
  if (argc != 3 ||
      !((add = !strcmp (argv[1], "add")) ||
	!strcmp (argv[1], "remove")))
    {
      fprintf (stderr,
	       "Syntax: %s add {USB device path}\n"
	       "        %s remove {CUPS device URI}\n",
	       argv[0], argv[0]);
      return 1;
    }

  if (add)
    return do_add (argv[0], argv[2]);

  return do_remove (argv[2]);
}

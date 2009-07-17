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
 * REMOVE_CMD="$0 remove $DEVICE_URI"
 *
 * where $0 is argv[0] and $DEVICE_URI is the CUPS device URI
 * corresponding to the queue.
 */

#define LIBUDEV_I_KNOW_THE_API_IS_SUBJECT_TO_CHANGE 1

#include <cups/cups.h>
#include <cups/http.h>
#include <libudev.h>
#include <stdio.h>
#include <syslog.h>
#include <unistd.h>

static int
do_add (const char *cmd, const char *devpath)
{
  int tries = 6;
  http_t *cups = NULL;
  struct udev *udev;
  struct udev_device *dev, *dev_iface;
  const char *sys;
  size_t syslen, devpathlen;
  char *syspath;
  const char *ieee1284_id;

  syslog (LOG_DEBUG, "add %s", devpath);

  udev = udev_new ();
  if (udev == NULL)
    {
      syslog (LOG_ERR, "udev_new failed");
      return 1;
    }

  sys = udev_get_sys_path (udev);
  syslen = strlen (sys);
  devpathlen = strlen (devpath);
  syspath = malloc (syslen + devpathlen + 1);
  if (syspath == NULL)
    {
      udev_unref (udev);
      syslog (LOG_ERR, "out of memory");
      return 1;
    }

  memcpy (syspath, sys, syslen);
  memcpy (syspath + syslen, devpath, devpathlen);
  syspath[syslen + devpathlen] = '\0';

  dev = udev_device_new_from_syspath (udev, syspath);
  if (dev == NULL)
    {
      udev_device_unref (dev);
      udev_unref (udev);
      syslog (LOG_ERR, "unable to access %s", syspath);
      return 1;
    }

  dev_iface = udev_device_get_parent_with_subsystem_devtype (dev, "usb",
							     "usb_interface");
  if (dev_iface == NULL)
    {
      udev_device_unref (dev);
      udev_unref (udev);
      syslog (LOG_ERR, "unable to access usb_interface device of %s",
	      syspath);
      return 1;
    }

  ieee1284_id = udev_device_get_sysattr_value (dev_iface, "ieee1284_id");
  if (ieee1284_id != NULL)
    {
      syslog (LOG_DEBUG, "ieee1284_id=%s", ieee1284_id);
    }

  udev_device_unref (dev);

  while (cups == NULL && tries-- > 0)
    {
      cups = httpConnectEncrypt ("localhost", 631,
				 HTTP_ENCRYPT_IF_REQUESTED);
      if (cups)
	break;

      syslog (LOG_DEBUG, "failed to connect to CUPS server; retrying in 5s");
      sleep (5);
    }

  if (cups == NULL)
    {
      syslog (LOG_DEBUG, "failed to connect to CUPS server; giving up");
      return 0;
    }

  httpClose (cups);
  printf ("REMOVE_CMD=\"%s remove %s\"\n", cmd, "uri");
  return 0;
}

static int
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

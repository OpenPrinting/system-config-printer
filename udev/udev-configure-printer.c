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
#include <fcntl.h>
#include <libudev.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <syslog.h>
#include <unistd.h>

#define DISABLED_REASON "Unplugged or turned off"
#define MATCH_ONLY_DISABLED 1

struct device_id
{
  char *full_device_id;
  char *mfg;
  char *mdl;
  char *sern;
};

static void
free_device_id (struct device_id *id)
{
  free (id->full_device_id);
  free (id->mfg);
  free (id->mdl);
  free (id->sern);
}

static void
parse_device_id (const char *device_id,
		 struct device_id *id)
{
  char *fieldname;
  char *start, *end;
  size_t len;

  id->full_device_id = strdup (device_id);
  fieldname = strdup (device_id);
  if (id->full_device_id == NULL || fieldname == NULL)
    {
      syslog (LOG_ERR, "out of memory");
      exit (1);
    }

  fieldname[0] = '\0';

  start = id->full_device_id;
  while (*start != '\0')
    {
      /* New field. */

      end = start;
      while (*end != '\0' && *end != ':')
	end++;

      if (*end == '\0')
	break;

      len = end - start;
      memcpy (fieldname, start, len);
      fieldname[len] = '\0';

      start = end + 1;
      while (*end != '\0' && *end != ';')
	end++;

      len = end - start;

      if (!id->mfg &&
	  !strncasecmp (fieldname, "MANUFACTURER", 12) ||
	  !strncasecmp (fieldname, "MFG", 3))
	id->mfg = strndup (start, len);
      else if (!id->mdl &&
	       !strncasecmp (fieldname, "MODEL", 5) ||
	       !strncasecmp (fieldname, "MDL", 3))
	id->mdl = strndup (start, len);
      else if (!id->sern &&
	       !strncasecmp (fieldname, "SERIALNUMBER", 12) ||
	       !strncasecmp (fieldname, "SERN", 4) ||
	       !strncasecmp (fieldname, "SN", 2))
	id->sern = strndup (start, len);

      if (*end != '\0')
	start = end + 1;
    }

  free (fieldname);
}

static void
device_id_from_devpath (const char *devpath,
			struct device_id *id)
{
  struct udev *udev;
  struct udev_device *dev, *dev_iface;
  const char *sys;
  size_t syslen, devpathlen;
  char *syspath;
  const char *ieee1284_id;

  id->full_device_id = id->mfg = id->mdl = id->sern = NULL;

  udev = udev_new ();
  if (udev == NULL)
    {
      syslog (LOG_ERR, "udev_new failed");
      exit (1);
    }

  sys = udev_get_sys_path (udev);
  syslen = strlen (sys);
  devpathlen = strlen (devpath);
  syspath = malloc (syslen + devpathlen + 1);
  if (syspath == NULL)
    {
      udev_unref (udev);
      syslog (LOG_ERR, "out of memory");
      exit (1);
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
      exit (1);
    }

#if 0
  dev_iface = udev_device_get_parent_with_subsystem_devtype (dev, "usb",
							     "usb_interface");
  if (dev_iface == NULL)
    {
      udev_device_unref (dev);
      udev_unref (udev);
      syslog (LOG_ERR, "unable to access usb_interface device of %s",
	      syspath);
      exit (1);
    }

  ieee1284_id = udev_device_get_sysattr_value (dev_iface, "ieee1284_id");
#endif
  ieee1284_id = "MFG:EPSON;CMD:ESCPL2,BDC,D4,D4PX;MDL:Stylus D78;CLS:PRINTER;DES:EPSON Stylus D78;";
  if (ieee1284_id != NULL)
    {
      syslog (LOG_DEBUG, "ieee1284_id=%s", ieee1284_id);
      parse_device_id (ieee1284_id, id);
    }

  udev_device_unref (dev);
}

static const char *
no_password (const char *prompt)
{
  return "";
}

static http_t *
cups_connection (void)
{
  http_t *cups = NULL;
  static int first_time = 1;
  int tries = 1;

  if (first_time)
    {
      cupsSetPasswordCB (no_password);
      tries = 6;
      first_time = 0;
    }

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
      exit (1);
    }
 
  return cups;
}

static ipp_t *
cupsDoRequestOrDie (http_t *http,
		    ipp_t *request,
		    const char *resource)
{
  ipp_t *answer = cupsDoRequest (http, request, resource);
  if (answer == NULL)
    {
      syslog (LOG_ERR, "failed to send IPP request %d",
	      request->request.op.operation_id);
      exit (1);
    }

  if (answer->request.status.status_code > IPP_OK_CONFLICT)
    {
      syslog (LOG_ERR, "IPP request %d failed (%d)",
	      request->request.op.operation_id,
	      answer->request.status.status_code);
      exit (1);
    }

  return answer;
}

static char *
find_matching_device_uri (struct device_id *id)
{
  http_t *cups;
  ipp_t *request, *answer;
  ipp_attribute_t *attr;
  const char *include_schemes[] = { "usb" };
  char *device_uri;

  /* Leave the bus to settle. */
  sleep (1);

  cups = cups_connection ();
  request = ippNewRequest (CUPS_GET_DEVICES);
  ippAddStrings (request, IPP_TAG_OPERATION, IPP_TAG_NAME, "include-schemes",
		 sizeof (include_schemes) / sizeof(include_schemes[0]),
		 NULL, include_schemes);

  answer = cupsDoRequestOrDie (cups, request, "/");
  httpClose (cups);

  for (attr = answer->attrs; attr; attr = attr->next)
    {
      while (attr && attr->group_tag != IPP_TAG_PRINTER)
	attr = attr->next;

      if (!attr)
	break;

      for (; attr && attr->group_tag == IPP_TAG_PRINTER; attr = attr->next)
	{
	  if (!strcmp (attr->name, "device-uri") &&
	      attr->value_tag == IPP_TAG_URI)
	    {
	      char scheme[HTTP_MAX_URI];
	      char username[HTTP_MAX_URI];
	      char mfg[HTTP_MAX_URI];
	      char resource[HTTP_MAX_URI];
	      int port;
	      char *mdl;
	      char *serial;
	      size_t seriallen, mdllen = 0;
	      syslog (LOG_DEBUG, "uri:%s", attr->values[0].string.text);
	      httpSeparateURI (HTTP_URI_CODING_ALL,
			       attr->values[0].string.text,
			       scheme, sizeof(scheme),
			       username, sizeof(username),
			       mfg, sizeof(mfg),
			       &port,
			       resource, sizeof(resource));

	      mdl = resource;
	      if (*mdl == '/')
		mdl++;

	      serial = strstr (mdl, "?serial=");
	      if (serial)
		{
		  mdllen = serial - mdl;
		  serial += 8;
		  seriallen = strspn (serial, "&");
		}

	      syslog (LOG_DEBUG, "%s <=> %s", mfg, id->mfg);
	      if (strcasecmp (mfg, id->mfg))
		continue;

	      syslog (LOG_DEBUG, "%s <=> %s (%d)", mdl, id->mdl, mdllen);
	      if (mdllen)
		{
		  if (strncasecmp (mdl, id->mdl, mdllen))
		    continue;
		}
	      else if (strcasecmp (mdl, id->mdl))
		continue;

	      if (serial)
		{
		  if (id->sern)
		    {
		      if (!strcasecmp (serial, id->sern))
			{
			  /* Serial number matches so stop looking. */
			  device_uri = strdup (attr->values[0].string.text);
			  break;
			}
		      else
			continue;
		    }
		  else
		    continue;
		}

	      device_uri = strdup (attr->values[0].string.text);
	      syslog (LOG_DEBUG, "Device URI is %s", device_uri);
	    }
	}

      if (!attr)
	break;
    }

  ippDelete (answer);
  return device_uri;
}

/* Call a function for each queue with the given device-uri and printer-state.
 * Returns the number of queues with a matching device-uri. */
static size_t
for_each_matching_queue (const char *device_uri,
			 int flags,
			 void (*fn) (const char *, void *),
			 void *context)
{
  size_t matched = 0;
  http_t *cups = cups_connection ();
  ipp_t *request, *answer;
  ipp_attribute_t *attr;
  const char *attributes[] = {
    "printer-uri-supported",
    "device-uri",
    "printer-state",
    "printer-state-message",
  };

  request = ippNewRequest (CUPS_GET_PRINTERS);
  ippAddStrings (request, IPP_TAG_OPERATION, IPP_TAG_KEYWORD,
		 "requested-attributes",
		 sizeof (attributes) / sizeof (attributes[0]),
		 NULL, attributes);
  answer = cupsDoRequest (cups, request, "/");
  httpClose (cups);
  if (answer == NULL)
    {
      syslog (LOG_ERR, "failed to send CUPS-Get-Printers request");
      exit (1);
    }

  if (answer->request.status.status_code > IPP_OK_CONFLICT)
    {
      if (answer->request.status.status_code == IPP_NOT_FOUND)
	{
	  /* No printer queues configured. */
	  ippDelete (answer);
	  return;
	}

      syslog (LOG_ERR, "CUPS-Get-Printers request failed (%d)",
	      answer->request.status.status_code);
      exit (1);
    }

  for (attr = answer->attrs; attr; attr = attr->next)
    {
      const char *this_printer_uri = NULL;
      const char *this_device_uri = NULL;
      const char *printer_state_message;
      int state = 0;

      while (attr && attr->group_tag != IPP_TAG_PRINTER)
	attr = attr->next;

      if (!attr)
	break;

      for (; attr && attr->group_tag == IPP_TAG_PRINTER; attr = attr->next)
	{
	  if (attr->value_tag == IPP_TAG_URI)
	    {
	      if (!strcmp (attr->name, "device-uri"))
		this_device_uri = attr->values[0].string.text;
	      else if (!strcmp (attr->name, "printer-uri-supported"))
		this_printer_uri = attr->values[0].string.text;
	    }
	  else if (attr->value_tag == IPP_TAG_TEXT &&
		   !strcmp (attr->name, "printer-state-message"))
	    printer_state_message = attr->values[0].string.text;
	  else if (attr->value_tag == IPP_TAG_ENUM &&
		   !strcmp (attr->name, "printer-state"))
	    state = attr->values[0].integer;
	}

      if (!strcmp (device_uri, this_device_uri))
	{
	  matched++;
	  if (((flags & MATCH_ONLY_DISABLED) &&
	       state == IPP_PRINTER_STOPPED &&
	       !strcmp (printer_state_message, DISABLED_REASON)) ||
	      (flags & MATCH_ONLY_DISABLED) == 0)
	    {
	      syslog (LOG_DEBUG ,"Queue %s has matching device URI",
		      this_printer_uri);
	      (*fn) (this_printer_uri, context);
	    }
	}

      if (!attr)
	break;
    }

  ippDelete (answer);
  return matched;
}

static void
enable_queue (const char *printer_uri, void *context)
{
  /* Disable it. */
  http_t *cups = cups_connection ();
  ipp_t *request, *answer;
  request = ippNewRequest (IPP_RESUME_PRINTER);
  ippAddString (request, IPP_TAG_OPERATION, IPP_TAG_URI,
		"printer-uri", NULL, printer_uri);
  answer = cupsDoRequest (cups, request, "/admin/");
  if (!answer)
    {
      syslog (LOG_ERR, "Failed to send IPP-Resume-Printer request");
      httpClose (cups);
      return;
    }

  if (answer->request.status.status_code > IPP_OK_CONFLICT)
    syslog (LOG_ERR, "IPP-Resume-Printer request failed");
  else
    syslog (LOG_INFO, "Re-enabled printer %s", printer_uri);

  ippDelete (answer);
  httpClose (cups);
}

static int
do_add (const char *cmd, const char *devpath)
{
  struct device_id id;
  char *device_uri = NULL;
  char *printer_uri;
  int i;

  syslog (LOG_DEBUG, "add %s", devpath);

  device_id_from_devpath (devpath, &id);
  if (!id.mfg || !id.mdl)
    {
      syslog (LOG_ERR, "invalid IEEE 1284 Device ID");
      exit (1);
    }

  syslog (LOG_DEBUG, "MFG:%s MDL:%s SERN:%s", id.mfg, id.mdl,
	  id.sern ? id.sern : "-");

  /* If the manufacturer's name appears as the start of the model
     name, remove it. */
  i = 0;
  while (id.mfg[i] != '\0')
    if (id.mfg[i] != id.mdl[i])
      break;
  if (id.mfg[i] == '\0')
    {
      char *old = id.mdl;
      id.mdl = strdup (id.mdl + i);
      free (old);
    }

  syslog (LOG_DEBUG, "Match MFG:%s MDL:%s SERN:%s", id.mfg, id.mdl,
	  id.sern ? id.sern : "-");

  device_uri = find_matching_device_uri (&id);
  if (device_uri == NULL)
    {
      free_device_id (&id);
      return 0;
    }

  printf ("REMOVE_CMD=\"%s remove %s\"\n", cmd, device_uri);

  /* Re-enable any queues we'd previously disabled. */
  if (for_each_matching_queue (device_uri, MATCH_ONLY_DISABLED,
			       enable_queue, NULL) == 0)
    {
      pid_t pid;
      int f;
      char argv0[PATH_MAX];
      char *p;
      char *argv[] = { argv0, device_uri, id.full_device_id, NULL }
;
      /* No queue is configured for this device yet. */
      syslog (LOG_DEBUG, "About to add queue");
      strcpy (argv0, cmd);
      p = strrchr (argv0, '/');
      if (p++ == NULL)
	p = argv0;

      strcpy (p, "udev-add-printer");

      if ((pid = fork ()) == -1)
	syslog (LOG_ERR, "Failed to fork process");
      else if (pid != 0)
	/* Parent. */
	exit (0);

      close (STDIN_FILENO);
      close (STDOUT_FILENO);
      close (STDERR_FILENO);
      f = open ("/dev/null", O_RDWR);
      if (f != STDIN_FILENO)
	dup2 (f, STDIN_FILENO);
      if (f != STDOUT_FILENO)
	dup2 (f, STDOUT_FILENO);
      if (f != STDERR_FILENO)
	dup2 (f, STDERR_FILENO);

      setsid ();

      execv (argv0, argv);
      syslog (LOG_ERR, "Failed to execute %s", argv0);
    }

  free_device_id (&id);
  free (device_uri);
  free (printer_uri);

  return 0;
}

static void
disable_queue (const char *printer_uri, void *context)
{
  /* Disable it. */
  http_t *cups = cups_connection ();
  ipp_t *request, *answer;
  request = ippNewRequest (IPP_PAUSE_PRINTER);
  ippAddString (request, IPP_TAG_OPERATION, IPP_TAG_URI,
		"printer-uri", NULL, printer_uri);
  ippAddString (request, IPP_TAG_OPERATION, IPP_TAG_TEXT,
		"printer-state-message", NULL, DISABLED_REASON);
  answer = cupsDoRequest (cups, request, "/admin/");
  if (!answer)
    {
      syslog (LOG_ERR, "Failed to send IPP-Pause-Printer request");
      httpClose (cups);
      return;
    }

  if (answer->request.status.status_code > IPP_OK_CONFLICT)
    syslog (LOG_ERR, "IPP-Pause-Printer request failed");
  else
    syslog (LOG_INFO, "Disabled printer %s as the corresponding device "
	    "was unplugged or turned off", printer_uri);

  ippDelete (answer);
  httpClose (cups);
}

static int
do_remove (const char *device_uri)
{
  syslog (LOG_DEBUG, "remove %s", device_uri);

  /* Find the relevant queues and disable them if they are enabled. */
  for_each_matching_queue (device_uri, 0, disable_queue, NULL);
  return 0;
}

int
main (int argc, char **argv)
{
  int add;

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

  openlog ("udev-configure-printer", 0, LOG_LPR);
  if (add)
    return do_add (argv[0], argv[2]);

  return do_remove (argv[2]);
}

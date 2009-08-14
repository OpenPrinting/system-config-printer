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
 * The protocol for this program is:
 *
 * udev-configure-printer add {DEVPATH}
 * udev-configure-printer remove {DEVPATH}
 *
 * where DEVPATH is the path (%p) of the device
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
#include <usb.h>

#define DISABLED_REASON "Unplugged or turned off"
#define MATCH_ONLY_DISABLED 1
#define USB_URI_MAP "/var/run/udev-configure-printer/usb-uris"

struct device_uris
{
  size_t n_uris;
  char **uri;
};

struct usb_uri_map_entry
{
  struct usb_uri_map_entry *next;

  /* The devpath of the ("usb","usb_device") device. */
  char *devpath;

  /* List of matching device URIs. */
  struct device_uris uris;
};

struct usb_uri_map
{
  struct usb_uri_map_entry *entries;

  /* Open file descriptor for the map, or -1 if it has already been
   * written. */
  int fd;
};

struct device_id
{
  char *full_device_id;
  char *mfg;
  char *mdl;
  char *sern;
};

/* Device URI schemes in decreasing order of preference. */
static const char *device_uri_types[] =
  {
    "hp",
    "usb",
  };

static int
device_uri_type (const char *uri)
{
  int slen = strcspn (uri, ":");
  int i;
  int n = sizeof (device_uri_types) / sizeof (device_uri_types[0]);
  for (i = 0; i < n; i++)
    if (!strncmp (uri, device_uri_types[i], slen) &&
	device_uri_types[i][slen] == '\0')
      break;

  return i;
}

static void
add_device_uri (struct device_uris *uris,
		const char *uri)
{
  char *uri_copy = strdup (uri);
  if (!uri_copy)
    {
      syslog (LOG_ERR, "out of memory");
      return;
    }

  if (uris->n_uris == 0)
    {
      uris->uri = malloc (sizeof (char *));
      if (uris->uri)
	{
	  uris->n_uris = 1;
	  uris->uri[0] = uri_copy;
	}
    }
  else
    {
      char **old = uris->uri;
      if (++uris->n_uris < UINT_MAX / sizeof (char *))
	{
	  uris->uri = realloc (uris->uri,
			       sizeof (char *) * uris->n_uris);
	  if (uris->uri)
	    uris->uri[uris->n_uris - 1] = uri_copy;
	  else
	    {
	      uris->uri = old;
	      uris->n_uris--;
	      free (uri_copy);
	    }
	}
      else
	{
	  uris->n_uris--;
	  free (uri_copy);
	}
    }
}

static void
free_device_uris (struct device_uris *uris)
{
  size_t i;
  for (i = 0; i < uris->n_uris; i++)
    free (uris->uri[i]);
  free (uris->uri);
}

static void
add_usb_uri_mapping (struct usb_uri_map **map,
		     const char *devpath,
		     const struct device_uris *uris)
{
  struct usb_uri_map_entry *entry, **prev;
  size_t i;
  prev = &(*map)->entries;
  while (*prev)
    prev = &((*prev)->next);

  entry = malloc (sizeof (struct usb_uri_map_entry));
  if (!entry)
    {
      syslog (LOG_ERR, "out of memory");
      return;
    }

  entry->devpath = strdup (devpath);
  entry->uris.n_uris = uris->n_uris;
  entry->uris.uri = malloc (sizeof (char *) * uris->n_uris);
  for (i = 0; i < uris->n_uris; i++)
    entry->uris.uri[i] = strdup (uris->uri[i]);
  entry->next = NULL;
  *prev = entry;
}

static struct usb_uri_map *
read_usb_uri_map (void)
{
  int fd = open (USB_URI_MAP, O_RDWR);
  struct usb_uri_map *map = NULL;
  struct flock lock;
  struct stat st;
  char *buf, *line;

  if (fd == -1)
    {
      char dir[] = USB_URI_MAP;
      char *p = strrchr (dir, '/');
      if (p)
	{
	  *p = '\0';
	  mkdir (dir, 0755);
	  fd = open (USB_URI_MAP, O_RDWR | O_TRUNC | O_CREAT, 0644);
	  if (fd == -1)
	    {
	      syslog (LOG_ERR, "failed to create " USB_URI_MAP);
	      exit (1);
	    }
	}
    }

  map = malloc (sizeof (struct usb_uri_map));
  if (!map)
    {
      syslog (LOG_ERR, "out of memory");
      exit (1);
    }

  lock.l_type = F_WRLCK;
  lock.l_whence = SEEK_SET;
  lock.l_start = 0;
  lock.l_len = 0;
  if (fcntl (fd, F_SETLKW, &lock) == -1)
    {
      syslog (LOG_ERR, "failed to lock " USB_URI_MAP);
      exit (1);
    }

  map->entries = NULL;
  map->fd = fd;
  if (fstat (fd, &st) == -1)
    {
      syslog (LOG_ERR, "failed to fstat " USB_URI_MAP " (fd %d)", fd);
      exit (1);
    }

  /* Read the entire file into memory. */
  buf = malloc (1 + (sizeof (char) * st.st_size));
  if (!buf)
    {
      syslog (LOG_ERR, "out of memory");
      exit (1);
    }

  if (read (fd, buf, st.st_size) < 0)
    {
      syslog (LOG_ERR, "failed to read " USB_URI_MAP);
      exit (1);
    }

  buf[st.st_size] = '\0';
  line = buf;
  while (line)
    {
      char *saveptr = NULL;
      const char *devpath, *uri;
      struct device_uris uris;
      char *nextline = strchr (line, '\n');
      if (!nextline)
	break;

      *nextline++ = '\0';
      if (nextline >= buf + st.st_size)
	nextline = NULL;

      devpath = strtok_r (line, "\t", &saveptr);
      uri = strtok_r (NULL, "\t", &saveptr);
      if (!devpath || !uri)
	{
	  syslog (LOG_DEBUG, "Incorrect line in " USB_URI_MAP ": %s",
		  line);
	  continue;
	}

      uris.n_uris = 1;
      uris.uri = malloc (sizeof (char *));
      if (uris.uri == NULL)
	break;

      uris.uri[0] = strdup (uri);
      while ((uri = strtok_r (NULL, "\t", &saveptr)) != NULL)
	add_device_uri (&uris, uri);

      add_usb_uri_mapping (&map, devpath, &uris);

      line = nextline;
    }

  free (buf);
  return map;
}

static void
write_usb_uri_map (struct usb_uri_map *map)
{
  struct usb_uri_map_entry *entry;
  int fd = map->fd;
  FILE *f;

  lseek (fd, SEEK_SET, 0);
  ftruncate (fd, 0);
  f = fdopen (fd, "w");
  if (!f)
    {
      syslog (LOG_ERR, "failed to fdopen " USB_URI_MAP " (fd %d)", fd);
      exit (1);
    }

  for (entry = map->entries; entry; entry = entry->next)
    {
      size_t i;
      fprintf (f, "%s\t%s", entry->devpath, entry->uris.uri[0]);
      for (i = 1; i < entry->uris.n_uris; i++)
	fprintf (f, "\t%s", entry->uris.uri[i]);
      fwrite ("\n", 1, 1, f);
    }

  fclose (f);
  map->fd = -1;
}

static void
free_usb_uri_map (struct usb_uri_map *map)
{
  struct usb_uri_map_entry *entry, *next;
  for (entry = map->entries; entry; entry = next)
    {
      next = entry->next;
      free (entry->devpath);
      free_device_uris (&entry->uris);
      free (entry);
    }

  if (map->fd != -1)
    close (map->fd);

  free (map);
}

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

  len = strlen (device_id);
  if (len == 0)
    return;

  if (device_id[len - 1] == '\n')
    len--;

  id->full_device_id = malloc (len + 1);
  fieldname = malloc (len + 1);
  if (!id->full_device_id || !fieldname)
    {
      syslog (LOG_ERR, "out of memory");
      exit (1);
    }

  memcpy (id->full_device_id, device_id, len);
  id->full_device_id[len] = '\0';
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
	  (!strncasecmp (fieldname, "MANUFACTURER", 12) ||
	   !strncasecmp (fieldname, "MFG", 3)))
	id->mfg = strndup (start, len);
      else if (!id->mdl &&
	       (!strncasecmp (fieldname, "MODEL", 5) ||
		!strncasecmp (fieldname, "MDL", 3)))
	id->mdl = strndup (start, len);
      else if (!id->sern &&
	       (!strncasecmp (fieldname, "SERIALNUMBER", 12) ||
		!strncasecmp (fieldname, "SERN", 4) ||
		!strncasecmp (fieldname, "SN", 2)))
	id->sern = strndup (start, len);

      if (*end != '\0')
	start = end + 1;
    }

  free (fieldname);
}

static char *
device_id_from_devpath (const char *devpath,
			const struct usb_uri_map *map,
			struct device_id *id,
			char *usbserial, size_t usbseriallen)
{
  struct usb_uri_map_entry *entry;
  struct udev *udev;
  struct udev_device *dev, *parent_dev = NULL;
  const char *sys;
  const char *idVendorStr, *idProductStr, *serial;
  char *end;
  unsigned long idVendor, idProduct;
  size_t syslen, devpathlen;
  char *syspath;
  struct usb_bus *bus;
  struct usb_dev_handle *handle = NULL;
  char ieee1284_id[1024];
  const char *device_id = NULL;
  int conf = 0, iface = 0;
  int got = 0;
  char *usb_device_devpath;

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

  parent_dev = udev_device_get_parent_with_subsystem_devtype (dev,
							      "usb",
							      "usb_device");
  if (!parent_dev)
    {
      udev_unref (udev);
      syslog (LOG_ERR, "Failed to get parent");
      exit (1);
    }

  usb_device_devpath = strdup (udev_device_get_devpath (parent_dev));
  syslog (LOG_DEBUG, "parent devpath is %s", usb_device_devpath);

  for (entry = map->entries; entry; entry = entry->next)
    if (!strcmp (entry->devpath, usb_device_devpath))
      break;

  if (entry)
    /* The map already had an entry so has already been dealt
     * with.  This can happen because there are two "add"
     * triggers: one for the usb_device device and the other for
     * the usblp device.  We have most likely been triggered by
     * the usblp device, so the usb_device rule got there before
     * us and succeeded.
     *
     * Pretend we didn't find any device URIs that matched, and
     * exit.
     */
    exit (0);

  serial = udev_device_get_sysattr_value (parent_dev, "serial");
  if (serial)
    {
      strncpy (usbserial, serial, usbseriallen);
      usbserial[usbseriallen - 1] = '\0';
    }
  else
    usbserial[0] = '\0';

  /* See if we were triggered by a usblp add event. */
  device_id = udev_device_get_sysattr_value (dev, "device/ieee1284_id");
  if (device_id)
    {
      got = 1;
      goto got_deviceid;
    }

  /* This is a low-level USB device.  Use libusb to fetch the Device ID. */
  idVendorStr = udev_device_get_sysattr_value (parent_dev, "idVendor");
  idProductStr = udev_device_get_sysattr_value (parent_dev, "idProduct");

  if (!idVendorStr || !idProductStr)
    {
      udev_device_unref (dev);
      udev_unref (udev);
      syslog (LOG_ERR, "Missing sysattr %s",
	      idVendorStr ?
	      (idProductStr ? "serial" : "idProduct") : "idVendor");
      exit (1);
    }

  idVendor = strtoul (idVendorStr, &end, 16);
  if (end == idVendorStr)
    {
      syslog (LOG_ERR, "Invalid idVendor: %s", idVendorStr);
      exit (1);
    }

  idProduct = strtoul (idProductStr, &end, 16);
  if (end == idProductStr)
    {
      syslog (LOG_ERR, "Invalid idProduct: %s", idProductStr);
      exit (1);
    }

  syslog (LOG_DEBUG, "Device vendor/product is %04zX:%04zX",
	  idVendor, idProduct);

  usb_init ();
  usb_find_busses ();
  usb_find_devices ();
  for (bus = usb_get_busses (); bus && !got; bus = bus->next)
    {
      struct usb_device *device;
      for (device = bus->devices; device && !got; device = device->next)
	{
	  struct usb_config_descriptor *confptr;
	  if (device->descriptor.idVendor != idVendor ||
	      device->descriptor.idProduct != idProduct ||
	      !device->config)
	    continue;

	  conf = 0;
	  for (confptr = device->config;
	       conf < device->descriptor.bNumConfigurations && !got;
	       conf++, confptr++)
	    {
	      struct usb_interface *ifaceptr;
	      iface = 0;
	      for (ifaceptr = confptr->interface;
		   iface < confptr->bNumInterfaces && !got;
		   iface++, ifaceptr++)
		{
		  struct usb_interface_descriptor *altptr;
		  int altset = 0;
		  for (altptr = ifaceptr->altsetting;
		       altset < ifaceptr->num_altsetting && !got;
		       altset++, altptr++)
		    {
		      if (altptr->bInterfaceClass == USB_CLASS_PRINTER &&
			  altptr->bInterfaceSubClass == 1)
			{
			  int n;
			  handle = usb_open (device);
			  if (!handle)
			    {
			      syslog (LOG_DEBUG, "failed to open device");
			      continue;
			    }

			  n = altptr->bInterfaceNumber;
			  if (usb_claim_interface (handle, n) < 0)
			    {
			      usb_close (handle);
			      handle = NULL;
			      syslog (LOG_DEBUG, "failed to claim interface");
			      continue;
			    }

			  if (n != 0 && usb_claim_interface (handle, 0) < 0)
			    {
			      usb_close (handle);
			      handle = NULL;
			      syslog (LOG_DEBUG, "failed to claim interface 0");
			      continue;
			    }

			  n = altptr->bAlternateSetting;
			  if (usb_set_altinterface (handle, n) < 0)
			    {
			      usb_close (handle);
			      handle = NULL;
			      syslog (LOG_DEBUG, "failed set altinterface");
			      continue;
			    }

			  memset (ieee1284_id, '\0', sizeof (ieee1284_id));
			  if (usb_control_msg (handle,
					       USB_TYPE_CLASS |
					       USB_ENDPOINT_IN |
					       USB_RECIP_INTERFACE,
					       0, conf, iface,
					       ieee1284_id,
					       sizeof (ieee1284_id),
					       5000) < 0)
			    {
			      usb_close (handle);
			      handle = NULL;
			      syslog (LOG_ERR, "Failed to fetch Device ID");
			      continue;
			    }

			  got = 1;
			  usb_close (handle);
			  break;
			}
		    }
		}
	    }
	}
    }

 got_deviceid:
  if (got)
    {
      if (!device_id)
	device_id = ieee1284_id + 2;
      parse_device_id (device_id, id);
    }

  udev_device_unref (dev);
  udev_unref (udev);
  return usb_device_devpath;
}

static const char *
no_password (const char *prompt)
{
  return "";
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

static int
find_matching_device_uris (struct device_id *id,
			   const char *usbserial,
			   struct device_uris *uris,
			   const char *devpath,
			   struct usb_uri_map *map)
{
  http_t *cups;
  ipp_t *request, *answer;
  ipp_attribute_t *attr;
  struct device_uris uris_noserial;
  struct device_uris all_uris;
  size_t i, n;
  const char *exclude_schemes[] = {
    "beh",
    "bluetooth",
    "http",
    "https",
    "ipp",
    "lpd",
    "ncp",
    "parallel",
    "scsi",
    "smb",
    "snmp",
    "socket",
  };

  uris->n_uris = uris_noserial.n_uris = all_uris.n_uris = 0;
  uris->uri = uris_noserial.uri = all_uris.uri = NULL;

  /* Leave the bus to settle. */
  sleep (1);

  cups = httpConnectEncrypt ("localhost", 631, HTTP_ENCRYPT_IF_REQUESTED);
  if (cups == NULL)
    {
      /* Don't bother retrying here.  Instead, the CUPS initscript
	 should run these commands after cupsd is started:

	 udevadm trigger --subsystem-match=usb \
	                 --attr-match=bInterfaceClass=07 \
			 --attr-match=bInterfaceSubClass=01

	 udevadm trigger --subsystem-match=usb \
	                 --property-match=DEVNAME="/dev/usb/lp*"
      */

      syslog (LOG_DEBUG, "failed to connect to CUPS server; giving up");
      exit (1);
    }

  request = ippNewRequest (CUPS_GET_DEVICES);
  ippAddStrings (request, IPP_TAG_OPERATION, IPP_TAG_NAME, "exclude-schemes",
		 sizeof (exclude_schemes) / sizeof(exclude_schemes[0]),
		 NULL, exclude_schemes);

  answer = cupsDoRequestOrDie (cups, request, "/");
  httpClose (cups);

  for (attr = answer->attrs; attr; attr = attr->next)
    {
      const char *device_uri = NULL;
      struct device_id this_id;
      this_id.full_device_id = this_id.mfg = this_id.mdl = this_id.sern = NULL;

      while (attr && attr->group_tag != IPP_TAG_PRINTER)
	attr = attr->next;

      if (!attr)
	break;

      for (; attr && attr->group_tag == IPP_TAG_PRINTER; attr = attr->next)
	{
	  if (attr->value_tag == IPP_TAG_URI &&
	      !strcmp (attr->name, "device-uri"))
	    device_uri = attr->values[0].string.text;
	  else if (attr->value_tag == IPP_TAG_TEXT &&
		   !strcmp (attr->name, "device-id"))
	    parse_device_id (attr->values[0].string.text, &this_id);
	}

      /* Only use device schemes in our preference order for matching
       * against the IEEE 1284 Device ID. */

      for (i = 0;
	   device_uri &&
	   i < sizeof (device_uri_types) / sizeof (device_uri_types[0]);
	   i++)
	{
	  size_t len = strlen (device_uri_types[i]);
	  if (!strncmp (device_uri_types[i], device_uri, len) &&
	      device_uri[len] == ':')
	    break;
	}

      if (device_uri)
	add_device_uri (&all_uris, device_uri);

      if (i == sizeof (device_uri_types) / sizeof (device_uri_types[0]))
	/* Not what we want to match against.  Ignore this one. */
	device_uri = NULL;

      /* Now check the manufacturer and model names. */
      if (device_uri && this_id.mfg && this_id.mdl &&
	  !strcasecmp (this_id.mfg, id->mfg) &&
	  !strcasecmp (this_id.mdl, id->mdl))
	{
	  /* We've checked everything except the serial numbers.  This
	   * is more complicated.  Some devices include a serial
	   * number (SERN) field in their IEEE 1284 Device ID.  Others
	   * don't -- this was not a mandatory field in the
	   * specification.
	   *
	   * If the device includes SERN field in its, it must match
	   * what the device-id attribute has.
	   *
	   * Otherwise, the only means we have of knowing which device
	   * is meant is the USB serial number.
	   *
	   * CUPS backends may choose to insert the USB serial number
	   * into the SERN field when reporting a device-id attribute.
	   * HPLIP does this, and it seems not to stray too far from
	   * the intent of that field.  We accommodate this.
	   *
	   * Alternatively, CUPS backends may include the USB serial
	   * number somewhere in their reported device-uri attributes.
	   * For instance, the CUPS 1.4 usb backend, when compiled
	   * with libusb support, gives device URIs containing the USB
	   * serial number for devices without a SERN field, like
	   * this: usb://HP/DESKJET%20990C?serial=US05M1D20CIJ
	   *
	   * To accommodate this we examine tokens between '?', '='
	   * and '&' delimiters to check for USB serial number
	   * matches.
	   *
	   * CUPS 1.3, and CUPS 1.4 without libusb support, doesn't do this.
	   * As a result we also need to deal with devices that don't report a
	   * SERN field where the backends that don't add a SERN field from
	   * the USB serial number and also don't include the USB serial
	   * number in the URI.
	   */

	  int match = 0;
	  if ((id->sern && this_id.sern && !strcmp (id->sern, this_id.sern)))
	    {
	      syslog (LOG_DEBUG, "SERN fields match");
	      match = 1;
	    }

	  if (!match && usbserial[0] != '\0')
	    {
	      if (!id->sern)
		{
		  if (this_id.sern && !strcmp (usbserial, this_id.sern))
		    {
		      syslog (LOG_DEBUG,
			      "SERN field matches USB serial number");
		      match = 1;
		    }
		}

	      if (!match)
		{
		  char *saveptr, *uri = strdup (device_uri);
		  const char *token;
		  const char *sep = "?=&/";
		  for (token = strtok_r (uri, sep, &saveptr);
		       token;
		       token = strtok_r (NULL, sep, &saveptr))
		    if (!strcmp (token, usbserial))
		      {
			syslog (LOG_DEBUG, "URI contains USB serial number");
			match = 1;
			break;
		      }

		  free (uri);
		}
	    }

	  if (match)
	    {
	      syslog (LOG_DEBUG, "URI match: %s", device_uri);
	      add_device_uri (uris, device_uri);
	    }
	  else if (!id->sern)
	    {
	      syslog (LOG_DEBUG, "URI matches without serial number: %s",
		      device_uri);
	      add_device_uri (&uris_noserial, device_uri);
	    }
	}

      if (!attr)
	break;
    }

  ippDelete (answer);

  /* Decide what to do about device URIs that did not match a serial
   * number.  The device had no SERN field, and the USB serial number
   * was nowhere to be found from the device URI or device-id field.
   *
   * Device URIs with no reference to serial number can only each ever
   * work when only one printer of that model is connected.
   * Accordingly, it is safe to disable queues using such URIs, as we
   * know the removed/added device is that lone printer.
   *
   * When adding queues it is best to avoid URIs that don't
   * distinguish serial numbers.
   *
   * What we'll do, then, is concatenate the list of "non-serial" URIs
   * onto the end of the list of "serial" URIs.
   */

  if (uris->n_uris == 0 && uris_noserial.n_uris > 0)
    {
      syslog (LOG_DEBUG, "No serial number URI matches so using those without");
      uris->n_uris = uris_noserial.n_uris;
      uris->uri = uris_noserial.uri;
      uris_noserial.n_uris = 0;
      uris_noserial.uri = NULL;
    }
  else if (uris_noserial.n_uris > 0)
    {
      char **old = uris->uri;
      uris->uri = realloc (uris->uri,
			   sizeof (char *) * (uris->n_uris +
					      uris_noserial.n_uris));
      if (!uris->uri)
	uris->uri = old;
      else
	{
	  for (i = 0; i < uris_noserial.n_uris; i++)
	    uris->uri[uris->n_uris + i] = uris_noserial.uri[i];
	  uris->n_uris += uris_noserial.n_uris;
	}

      uris_noserial.n_uris = 0;
      uris_noserial.uri = NULL;
    }

  free_device_uris (&uris_noserial);

  /* Having decided which device URIs match based on IEEE 1284 Device
   * ID, we now need to look for "paired" URIs for other functions of
   * a multi-function device.  This are the same except for the
   * scheme. */

  n = uris->n_uris;
  for (i = 0; i < n; i++)
    {
      size_t j;
      char *me = uris->uri[i];
      char *my_rest = strchr (me, ':');
      size_t my_schemelen;
      if (!my_rest)
	continue;

      my_schemelen = my_rest - me;
      for (j = 0; j < all_uris.n_uris; j++)
	{
	  char *twin = all_uris.uri[j];
	  char *twin_rest = strchr (twin, ':');
	  size_t twin_schemelen;
	  if (!twin_rest)
	    continue;

	  twin_schemelen = twin_rest - twin;
	  if (my_schemelen == twin_schemelen &&
	      !strncmp (me, twin, my_schemelen))
	    /* This is the one we are looking for the twin of. */
	    continue;

	  if (!strcmp (my_rest, twin_rest))
	    {
	      syslog (LOG_DEBUG, "%s twinned with %s", me, twin);
	      add_device_uri (uris, twin);
	    }
	}
    }

  free_device_uris (&all_uris);
  if (uris->n_uris > 0)
    {
      add_usb_uri_mapping (&map, devpath, uris);
      write_usb_uri_map (map);
      free_usb_uri_map (map);
    }

  return uris->n_uris;
}

/* Call a function for each queue with the given device-uri and printer-state.
 * Returns the number of queues with a matching device-uri. */
static size_t
for_each_matching_queue (struct device_uris *device_uris,
			 int flags,
			 void (*fn) (const char *, void *),
			 void *context)
{
  size_t matched = 0;
  http_t *cups = httpConnectEncrypt ("localhost", 631,
				     HTTP_ENCRYPT_IF_REQUESTED);
  ipp_t *request, *answer;
  ipp_attribute_t *attr;
  const char *attributes[] = {
    "printer-uri-supported",
    "device-uri",
    "printer-state",
    "printer-state-message",
  };

  if (cups == NULL)
    return 0;

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
	  return 0;
	}

      syslog (LOG_ERR, "CUPS-Get-Printers request failed (%d)",
	      answer->request.status.status_code);
      exit (1);
    }

  for (attr = answer->attrs; attr; attr = attr->next)
    {
      const char *this_printer_uri = NULL;
      const char *this_device_uri = NULL;
      const char *printer_state_message = NULL;
      int state = 0;
      size_t i;

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

      for (i = 0; i < device_uris->n_uris; i++)
	if (!strcmp (device_uris->uri[i], this_device_uri))
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
  http_t *cups = httpConnectEncrypt ("localhost", 631,
				     HTTP_ENCRYPT_IF_REQUESTED);
  ipp_t *request, *answer;

  if (cups == NULL)
    return;

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
  pid_t pid;
  int f;
  struct device_id id;
  struct device_uris device_uris;
  struct usb_uri_map *map;
  char *usb_device_devpath;
  char usbserial[256];

  if (getenv ("DEBUG") == NULL)
    {
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
    }

  syslog (LOG_DEBUG, "add %s", devpath);

  map = read_usb_uri_map ();
  usb_device_devpath = device_id_from_devpath (devpath, map, &id,
					       usbserial, sizeof (usbserial));

  if (!id.mfg || !id.mdl)
    {
      syslog (LOG_ERR, "invalid or missing IEEE 1284 Device ID%s%s",
	      id.full_device_id ? " " : "",
	      id.full_device_id ? id.full_device_id : "");
      exit (1);
    }

  syslog (LOG_DEBUG, "MFG:%s MDL:%s SERN:%s serial:%s", id.mfg, id.mdl,
	  id.sern ? id.sern : "-", usbserial);

  find_matching_device_uris (&id, usbserial, &device_uris, usb_device_devpath,
			     map);
  free (usb_device_devpath);
  if (device_uris.n_uris == 0)
    {
      free_device_id (&id);
      return 0;
    }

  /* Re-enable any queues we'd previously disabled. */
  if (for_each_matching_queue (&device_uris, MATCH_ONLY_DISABLED,
			       enable_queue, NULL) == 0)
    {
      size_t i;
      int type;
      char argv0[PATH_MAX];
      char *p;
      char **argv = malloc (sizeof (char *) * (3 + device_uris.n_uris));

      /* No queue is configured for this device yet.
	 Decide on a URI to use. */
      type = device_uri_type (device_uris.uri[0]);
      for (i = 1; i < device_uris.n_uris; i++)
	{
	  int new_type = device_uri_type (device_uris.uri[i]);
	  if (new_type < type)
	    {
	      char *swap = device_uris.uri[0];
	      device_uris.uri[0] = device_uris.uri[i];
	      device_uris.uri[i] = swap;
	      type = new_type;
	    }
	}

      argv[0] = argv0;
      argv[1] = id.full_device_id;
      for (i = 0; i < device_uris.n_uris; i++)
	argv[i + 2] = device_uris.uri[i];
      argv[i + 2] = NULL;

      syslog (LOG_DEBUG, "About to add queue for %s", argv[2]);
      strcpy (argv0, cmd);
      p = strrchr (argv0, '/');
      if (p++ == NULL)
	p = argv0;

      strcpy (p, "udev-add-printer");

      execv (argv0, argv);
      syslog (LOG_ERR, "Failed to execute %s", argv0);
    }

  free_device_id (&id);
  free_device_uris (&device_uris);
  return 0;
}

static void
disable_queue (const char *printer_uri, void *context)
{
  /* Disable it. */
  http_t *cups = httpConnectEncrypt ("localhost", 631,
				     HTTP_ENCRYPT_IF_REQUESTED);
  ipp_t *request, *answer;

  if (cups == NULL)
    return;

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
do_remove (const char *devpath)
{
  struct usb_uri_map *map;
  struct usb_uri_map_entry *entry, **prev;
  struct device_uris *uris = NULL;
  syslog (LOG_DEBUG, "remove %s", devpath);

  map = read_usb_uri_map ();
  prev = &map->entries;
  for (entry = map->entries; entry; entry = entry->next)
    {
      if (!strcmp (entry->devpath, devpath))
	{
	  uris = &entry->uris;
	  break;
	}

      prev = &(entry->next);
    }

  if (uris)
    {
      /* Find the relevant queues and disable them if they are enabled. */
      for_each_matching_queue (uris, 0, disable_queue, NULL);
      *prev = entry->next;
      write_usb_uri_map (map);
    }

  free_usb_uri_map (map);
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
	       "        %s remove {USB device path}\n",
	       argv[0], argv[0]);
      return 1;
    }

  openlog ("udev-configure-printer", 0, LOG_LPR);
  cupsSetPasswordCB (no_password);
  if (add)
    return do_add (argv[0], argv[2]);

  return do_remove (argv[2]);
}

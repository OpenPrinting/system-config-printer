/* -*- Mode: C; c-file-style: "gnu" -*-
 * udev-configure-printer - a udev callout to configure print queues
 * Copyright (C) 2009, 2010, 2011, 2012 Red Hat, Inc.
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
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
 *
 */

/*
 * The protocol for this program is:
 *
 * udev-configure-printer add {DEVADDR}
 * udev-configure-printer remove {DEVADDR}
 *
 * where DEVADDR is one of:
 *   the USB address of the device in the form usb-$env{BUSNUM}-$env{DEVNUM}
 *   the device path of the device (%p)
 *   the bluetooth address of the device
 */

#define LIBUDEV_I_KNOW_THE_API_IS_SUBJECT_TO_CHANGE 1

#include <cups/cups.h>
#include <cups/http.h>
#include <errno.h>
#include <fcntl.h>
#include <libudev.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <ctype.h>
#include <syslog.h>
#include <unistd.h>
#include <libusb.h>
#include <glib.h>
#include <dirent.h>

#define DISABLED_REASON "Unplugged or turned off"
#define MATCH_ONLY_DISABLED 1
#define USB_URI_MAP "/var/run/udev-configure-printer/usb-uris"

#if (CUPS_VERSION_MAJOR > 1) || (CUPS_VERSION_MINOR > 5)
#define HAVE_CUPS_1_6 1
#endif

/*
 * CUPS 1.6 makes various structures private and
 * introduces these ippGet and ippSet functions
 * for all of the fields in these structures.
 * http://www.cups.org/str.php?L3928
 * We define (same signatures) our own accessors when CUPS < 1.6.
 */
#ifndef HAVE_CUPS_1_6
const char *
ippGetName(ipp_attribute_t *attr)
{
  return (attr->name);
}

ipp_op_t
ippGetOperation(ipp_t *ipp)
{
  return (ipp->request.op.operation_id);
}

ipp_status_t
ippGetStatusCode(ipp_t *ipp)
{
  return (ipp->request.status.status_code);
}

ipp_tag_t
ippGetGroupTag(ipp_attribute_t *attr)
{
  return (attr->group_tag);
}

ipp_tag_t
ippGetValueTag(ipp_attribute_t *attr)
{
  return (attr->value_tag);
}

int
ippGetInteger(ipp_attribute_t *attr,
              int             element)
{
  return (attr->values[element].integer);
}

const char *
ippGetString(ipp_attribute_t *attr,
             int             element,
             const char      **language)
{
  return (attr->values[element].string.text);
}

ipp_attribute_t	*
ippFirstAttribute(ipp_t *ipp)
{
  if (!ipp)
    return (NULL);
  return (ipp->current = ipp->attrs);
}

ipp_attribute_t *
ippNextAttribute(ipp_t *ipp)
{
  if (!ipp || !ipp->current)
    return (NULL);
  return (ipp->current = ipp->current->next);
}

#endif

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
  if (ftruncate (fd, 0) == -1)
    {
      syslog (LOG_ERR, "failed to ftruncate " USB_URI_MAP " (fd %d, errno %d)",
	      fd, errno);
      exit (1);
    }

  f = fdopen (fd, "w");
  if (!f)
    {
      syslog (LOG_ERR, "failed to fdopen " USB_URI_MAP " (fd %d, errno %d)",
	      fd, errno);
      exit (1);
    }

  for (entry = map->entries; entry; entry = entry->next)
    {
      size_t i;
      fprintf (f, "%s\t%s", entry->devpath, entry->uris.uri[0]);
      for (i = 1; i < entry->uris.n_uris; i++)
	{
	  if (fprintf (f, "\t%s", entry->uris.uri[i]) < 0)
	    {
	      syslog (LOG_ERR, "failed to fprintf " USB_URI_MAP " (errno %d)",
		      errno);
	      exit (1);
	    }
	}

      if (fwrite ("\n", 1, 1, f) < 1)
	{
	  syslog (LOG_ERR, "failed to fwrite " USB_URI_MAP " (errno %d)",
		  errno);
	  exit (1);
	}
    }

  if (fclose (f) == EOF)
    syslog (LOG_ERR, "error closing " USB_URI_MAP " (errno %d)", errno);

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

int
device_file_filter(const struct dirent *entry)
{
  return ((strstr(entry->d_name, "lp") != NULL) ? 1 : 0);
}

static char *
get_ieee1284_id_from_child (struct udev *udev, struct udev_device *parent)
{
  struct udev_enumerate *udev_enum;
  struct udev_list_entry *item, *first = NULL;
  char *device_id = NULL;

  udev_enum = udev_enumerate_new (udev);
  if (!udev_enum)
    {
      syslog (LOG_ERR, "udev_enumerate_new failed");
      exit (1);
    }

  if (udev_enumerate_add_match_parent (udev_enum, parent) < 0)
    {
      udev_enumerate_unref (udev_enum);
      syslog (LOG_ERR, "uname to add parent match");
      exit (1);
    }

  if (udev_enumerate_scan_devices (udev_enum) < 0)
    {
      udev_enumerate_unref (udev_enum);
      syslog (LOG_ERR, "udev_enumerate_scan_devices failed");
      exit (1);
    }

  first = udev_enumerate_get_list_entry (udev_enum);
  udev_list_entry_foreach (item, first)
    {
      const char *ieee1284_id = NULL;
      struct udev_device *dev;
      dev = udev_device_new_from_syspath (udev,
					  udev_list_entry_get_name (item));
      if (dev == NULL)
	continue;

      ieee1284_id = udev_device_get_sysattr_value (dev, "ieee1284_id");
      if (ieee1284_id)
	device_id = g_strdup (ieee1284_id);

      udev_device_unref (dev);
      if (device_id)
	break;
    }

  udev_enumerate_unref (udev_enum);
  return device_id;
}

static char *
get_ieee1284_id_using_libusb (struct udev_device *dev,
			      const char *usbserial)
{
  const char *idVendorStr, *idProductStr;
  unsigned long idVendor, idProduct;
  char *end;
  int conf = 0, iface = 0, altset = 0, numdevs = 0, i, n, m;
  libusb_device **list;
  struct libusb_device *device;
  struct libusb_device_handle *handle = NULL;
  struct libusb_device_descriptor devdesc;
  struct libusb_config_descriptor *confptr = NULL;
  const struct libusb_interface *ifaceptr = NULL;
  const struct libusb_interface_descriptor *altptr = NULL;
  char libusbserial[1024];
  char ieee1284_id[1024];
  int got = 0;

  idVendorStr = udev_device_get_sysattr_value (dev, "idVendor");
  idProductStr = udev_device_get_sysattr_value (dev, "idProduct");

  if (!idVendorStr || !idProductStr)
    {
      syslog (LOG_ERR, "Missing sysattr %s",
	      idVendorStr ?
	      (idProductStr ? "serial" : "idProduct") : "idVendor");
      return NULL;
    }

  idVendor = strtoul (idVendorStr, &end, 16);
  if (end == idVendorStr)
    {
      syslog (LOG_ERR, "Invalid idVendor: %s", idVendorStr);
      return NULL;
    }

  idProduct = strtoul (idProductStr, &end, 16);
  if (end == idProductStr)
    {
      syslog (LOG_ERR, "Invalid idProduct: %s", idProductStr);
      return NULL;
    }

  syslog (LOG_DEBUG, "Device vendor/product is %04zX:%04zX",
	  idVendor, idProduct);

  libusb_init(NULL);
  numdevs = libusb_get_device_list(NULL, &list);
  if (numdevs > 0)
    for (i = 0; i < numdevs; i++)
      {
	device = list[i];

	if (libusb_get_device_descriptor(device, &devdesc) < 0)
	  continue;

	if (!devdesc.bNumConfigurations || !devdesc.idVendor ||
	    !devdesc.idProduct)
	  continue;

	if (devdesc.idVendor != idVendor || devdesc.idProduct != idProduct)
	  continue;

	for (conf = 0; conf < devdesc.bNumConfigurations; conf ++)
	  {
	    if (libusb_get_config_descriptor(device, conf, &confptr) < 0)
	      continue;
	    for (iface = 0, ifaceptr = confptr->interface;
		 iface < confptr->bNumInterfaces;
		 iface ++, ifaceptr ++)
	      {
		for (altset = 0, altptr = ifaceptr->altsetting;
		     altset < ifaceptr->num_altsetting;
		     altset ++, altptr ++)
		  {
		    if (altptr->bInterfaceClass != LIBUSB_CLASS_PRINTER ||
			altptr->bInterfaceSubClass != 1)
		      continue;
		    
		    if (libusb_open(device, &handle) < 0)
		      {
			syslog (LOG_DEBUG, "failed to open device");
			continue;
		      }

		    if (usbserial[0] != '\0' &&
			(libusb_get_string_descriptor_ascii(handle,
						devdesc.iSerialNumber,
						(unsigned char *)libusbserial,
						sizeof(libusbserial))) > 0 &&
			strcmp(usbserial, libusbserial) != 0)
		      {
			libusb_close (handle);
			handle = NULL;
			continue;
		      }
		      
		    n = altptr->bInterfaceNumber;
		    if (libusb_claim_interface(handle, n) < 0)
		      {
			libusb_close (handle);
			handle = NULL;
			syslog (LOG_DEBUG, "failed to claim interface");
			continue;
		      }
		    if (n != 0 && libusb_claim_interface(handle, 0) < 0)
		      {
			syslog (LOG_DEBUG, "failed to claim interface 0");
		      }
		    
		    m = altptr->bAlternateSetting;
		    if (libusb_set_interface_alt_setting(handle, n, m)
			< 0)
		      {
			libusb_close (handle);
			handle = NULL;
			syslog (LOG_DEBUG, "failed set altinterface");
			continue;
		      }

		    memset (ieee1284_id, '\0', sizeof (ieee1284_id));
		    if (libusb_control_transfer(handle,
						LIBUSB_REQUEST_TYPE_CLASS |
						LIBUSB_ENDPOINT_IN |
						LIBUSB_RECIPIENT_INTERFACE,
						0, conf,
						(n << 8) | m,
						(unsigned char *)ieee1284_id,
						sizeof (ieee1284_id),
						5000) < 0)
		      {
			libusb_close (handle);
			handle = NULL;
			syslog (LOG_ERR, "Failed to fetch Device ID");
			continue;
		      }

		    got = 1;
		    libusb_close (handle);
		    break;
		  }
	      }
	  }
      }

  libusb_free_device_list(list, 1);
  libusb_exit(NULL);

  if (got)
    return g_strdup (ieee1284_id + 2);
  return NULL;
}

static char *
device_id_from_devpath (struct udev *udev, const char *devpath,
			const struct usb_uri_map *map,
			struct device_id *id,
			char *usbserial, size_t usbseriallen,
			char *usblpdev, size_t usblpdevlen)
{
  struct usb_uri_map_entry *entry;
  struct udev_device *dev;
  const char *serial;
  size_t syslen, devpathlen;
  char *syspath, *devicefilepath;
  const char *device_id = NULL;
  char *usb_device_devpath;
  char *usblpdevpos, *dest;
  struct dirent **namelist;
  int num_names;

  id->full_device_id = id->mfg = id->mdl = id->sern = NULL;

  syslen = strlen ("/sys");
  devpathlen = strlen (devpath);
  syspath = malloc (syslen + devpathlen + 1);
  if (syspath == NULL)
    {
      syslog (LOG_ERR, "out of memory");
      exit (1);
    }
  memcpy (syspath, "/sys", syslen);
  memcpy (syspath + syslen, devpath, devpathlen);
  syspath[syslen + devpathlen] = '\0';

  devicefilepath = malloc (syslen + devpathlen + 5);
  if (devicefilepath == NULL)
    {
      syslog (LOG_ERR, "out of memory");
      exit (1);
    }
  memcpy (devicefilepath, syspath, syslen + devpathlen);
  memcpy (devicefilepath + syslen + devpathlen, "/usb", 4);
  devicefilepath[syslen + devpathlen + 4] = '\0';

  /* For devices under control of the usblp kernel module we read out the number
   * of the /dev/usb/lp* device file, as there can be queues set up with 
   * non-standard CUPS backends based on the /dev/usb/lp* device file and
   * we want to avoid that an additional queue with a standard CUPS backend
   * gets set up.
   */
  num_names = scandir(devicefilepath, &namelist, device_file_filter, alphasort);
  if (num_names <= 0)
    num_names = scandir(syspath, &namelist, device_file_filter, alphasort);
  if (num_names > 0)
    {
      usblpdevpos = strstr(namelist[0]->d_name, "lp");
      if (usblpdevpos != NULL)
	{
	  usblpdevpos += 2;
	  for (dest = usblpdev;
	       (*usblpdevpos >= '0') && (*usblpdevpos <= '9') &&
		 (dest - usblpdev < usblpdevlen);
	       usblpdevpos ++, dest ++)
	    *dest = *usblpdevpos;
	  *dest = '\0';
	}
    }

  dev = udev_device_new_from_syspath (udev, syspath);
  if (dev == NULL)
    {
      udev_device_unref (dev);
      syslog (LOG_ERR, "unable to access %s", syspath);
      return NULL;
    }

  usb_device_devpath = strdup (udev_device_get_devpath (dev));
  syslog (LOG_DEBUG, "device devpath is %s", usb_device_devpath);

  for (entry = map->entries; entry; entry = entry->next)
    if (!strcmp (entry->devpath, usb_device_devpath))
      break;

  if (entry)
    {
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
      syslog (LOG_DEBUG, "Device already handled");
      return NULL;
    }

  serial = udev_device_get_sysattr_value (dev, "serial");
  if (serial)
    {
      strncpy (usbserial, serial, usbseriallen);
      usbserial[usbseriallen - 1] = '\0';
    }
  else
    usbserial[0] = '\0';

  device_id = get_ieee1284_id_from_child (udev, dev);
  if (!device_id)
    /* Use libusb to fetch the Device ID. */
    device_id = get_ieee1284_id_using_libusb (dev, usbserial);

  if (device_id)
    parse_device_id (device_id, id);

  udev_device_unref (dev);
  return usb_device_devpath;
}

static void
device_id_from_bluetooth (const char *bdaddr, struct device_id *id)
{
  gint exit_status;
  char *device_id;
  gchar *argv[4];

  id->full_device_id = id->mfg = id->mdl = id->sern = NULL;
  argv[0] = g_strdup ("/usr/lib/cups/backend/bluetooth");
  argv[1] = g_strdup ("--get-deviceid");
  argv[2] = g_strdup (bdaddr);
  argv[3] = NULL;
  if (g_spawn_sync (NULL, argv, NULL,
		    G_SPAWN_STDERR_TO_DEV_NULL, NULL, NULL,
		    &device_id, NULL, &exit_status, NULL) == FALSE) {
    g_free (argv[0]);
    g_free (argv[1]);
    g_free (argv[2]);
    return;
  }
  g_free (argv[0]);
  g_free (argv[1]);
  g_free (argv[2]);

  if (WEXITSTATUS(exit_status) == 0)
    parse_device_id (device_id, id);

  g_free (device_id);
}

static char *
devpath_from_usb_devaddr (struct udev *udev, const char *devaddr)
{
  char *devname_ending = g_strdup (devaddr);
  char *devname;
  const char *devpath;
  struct udev_enumerate *udev_enum;
  struct udev_list_entry *first = NULL;
  struct udev_device *device;

  g_strdelimit (devname_ending, "-", '/');
  devname = g_strdup_printf("/dev/bus/%s", devname_ending);
  g_free (devname_ending);

  udev_enum = udev_enumerate_new (udev);
  if (udev_enum == NULL)
    {
      syslog (LOG_ERR, "udev_enumerate_new failed");
      exit (1);
    }

  if (udev_enumerate_add_match_property (udev_enum, "DEVNAME", devname) < 0)
    {
      udev_enumerate_unref (udev_enum);
      syslog (LOG_ERR, "udev_enumerate_add_match_property failed");
      exit (1);
    }

  if (udev_enumerate_scan_devices (udev_enum) < 0)
    {
      udev_enumerate_unref (udev_enum);
      syslog (LOG_ERR, "udev_enumerate_scan_devices failed");
      exit (1);
    }

  first = udev_enumerate_get_list_entry (udev_enum);
  if (first == NULL)
    {
      udev_enumerate_unref (udev_enum);
      syslog (LOG_ERR, "no device named %s found", devname);
      exit (1);
    }

  device = udev_device_new_from_syspath (udev,
					 udev_list_entry_get_name (first));
  if (device == NULL)
    {
      udev_enumerate_unref (udev_enum);
      syslog (LOG_ERR, "unable to examine device");
      exit (1);
    }

  devpath = udev_device_get_devpath (device);
  udev_enumerate_unref (udev_enum);
  if (!devpath)
    {
      syslog (LOG_ERR, "no devpath for device");
      exit (1);
    }

  g_free (devname);
  return g_strdup (devpath);
}

static char *
uri_from_bdaddr (const char *devpath)
{
  return g_strdup_printf("bluetooth://%c%c%c%c%c%c%c%c%c%c%c%c",
			 devpath[0], devpath[1],
			 devpath[3], devpath[4],
			 devpath[6], devpath[7],
			 devpath[9], devpath[10],
			 devpath[12], devpath[13],
			 devpath[15], devpath[16]);
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
	      ippGetOperation (request));
      exit (1);
    }

  if (ippGetStatusCode (answer) > IPP_OK_CONFLICT)
    {
      syslog (LOG_ERR, "IPP request %d failed (%d)",
	      ippGetOperation (request),
	      ippGetStatusCode (answer));
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
    "cups-pdf",
    "bluetooth",
    "dnssd",
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

  cups = httpConnectEncrypt (cupsServer (), ippPort(), cupsEncryption ());
  if (cups == NULL)
    {
      /* Don't bother retrying here.  We've probably been run from
	 udev before the cups.socket systemd unit is running.  We'll
	 get run again, as the systemd service
	 udev-configure-printer.service, after cups.socket.  For more
	 information:
	 http://0pointer.de/blog/projects/socket-activation2.html
      */

      syslog (LOG_DEBUG, "failed to connect to CUPS server; giving up");
      exit (1);
    }

  request = ippNewRequest (CUPS_GET_DEVICES);
  ippAddStrings (request, IPP_TAG_OPERATION, IPP_TAG_NAME, "exclude-schemes",
		 sizeof (exclude_schemes) / sizeof(exclude_schemes[0]),
		 NULL, exclude_schemes);
  ippAddInteger (request, IPP_TAG_OPERATION, IPP_TAG_INTEGER, "timeout",
                 2);

  answer = cupsDoRequestOrDie (cups, request, "/");
  httpClose (cups);

  for (attr = ippFirstAttribute (answer); attr; attr = ippNextAttribute (answer))
    {
      const char *device_uri = NULL;
      struct device_id this_id;
      this_id.full_device_id = this_id.mfg = this_id.mdl = this_id.sern = NULL;

      while (attr && ippGetGroupTag (attr) != IPP_TAG_PRINTER)
	attr = ippNextAttribute (answer);

      if (!attr)
	break;

      for (; attr && ippGetGroupTag (attr) == IPP_TAG_PRINTER; attr = ippNextAttribute (answer))
	{
	  if (ippGetValueTag (attr) == IPP_TAG_URI &&
	      !strcmp (ippGetName (attr), "device-uri"))
	    device_uri = ippGetString (attr, 0, NULL);
	  else if (ippGetValueTag (attr) == IPP_TAG_TEXT &&
		   !strcmp (ippGetName (attr), "device-id"))
	    parse_device_id (ippGetString (attr, 0, NULL), &this_id);
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

char *
normalize_device_uri(const char *str_orig)
{
  int i, j;
  int havespace = 0;
  char *str;

  if (str_orig == NULL)
    return NULL;

  str = strdup(str_orig);
  for (i = 0, j = 0; i < strlen(str); i++, j++)
    {
      if (((str[i] >= 'A') && (str[i] <= 'Z')) ||
	  ((str[i] >= 'a') && (str[i] <= 'z')) ||
	  ((str[i] >= '0') && (str[i] <= '9')))
	{
	  /* Letter or number, keep it */
	  havespace = 0;
	  str[j] = tolower(str[i]);
	}
      else
	{
	  if ((str[i] == '%') && (i <= strlen(str)-3) &&
	      (((str[i+1] >= 'A') && (str[i+1] <= 'F')) ||
	       ((str[i+1] >= 'a') && (str[i+1] <= 'f')) ||
	       ((str[i+1] >= '0') && (str[i+1] <= '9'))) &&
	    (((str[i+2] >= 'A') && (str[i+2] <= 'F')) ||
	     ((str[i+2] >= 'a') && (str[i+2] <= 'f')) ||
	     ((str[i+2] >= '0') && (str[i+2] <= '9'))))
	    /* Hex-encoded special characters replace by a single space if the
	       last character is not already a space */
	    i += 2;
	  if (havespace == 1)
	    j --;
	  else
	    {
	      havespace = 1;
	      str[j] = ' ';
	    }
	}
    }
  /* Add terminating zero */
  str[j] = '\0';
  /* Cut off trailing white space */
  while (str[strlen(str)-1] == ' ')
    str[strlen(str)-1] = '\0';
  /* Cut off all before model name */
  while ((strstr(str, "hp ") == str) ||
	 (strstr(str, "hewlett ") == str) ||
	 (strstr(str, "packard ") == str) ||
	 (strstr(str, "apollo ") == str) ||
	 (strstr(str, "usb ") == str))
    str = strchr(str, ' ') + 1;

  return str;
}

/* Call a function for each queue with the given device-uri and printer-state.
 * Returns the number of queues with a matching device-uri. */
static size_t
for_each_matching_queue (struct device_uris *device_uris,
			 int flags,
			 void (*fn) (const char *, void *),
			 void *context,
			 char *usblpdev, size_t usblpdevlen)
{
  size_t matched = 0;
  http_t *cups = httpConnectEncrypt (cupsServer (), ippPort (),
				     cupsEncryption ());
  ipp_t *request, *answer;
  ipp_attribute_t *attr;
  const char *attributes[] = {
    "printer-uri-supported",
    "device-uri",
    "printer-state",
    "printer-state-message",
  };
  char usblpdevstr1[32] = "", usblpdevstr2[32] = "";
  int firstqueue = 1;

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

  if (ippGetStatusCode (answer) > IPP_OK_CONFLICT)
    {
      if (ippGetStatusCode (answer) == IPP_NOT_FOUND)
	{
	  /* No printer queues configured. */
	  ippDelete (answer);
	  return 0;
	}

      syslog (LOG_ERR, "CUPS-Get-Printers request failed (%d)",
	      ippGetStatusCode (answer));
      exit (1);
    }

  if (strlen(usblpdev) > 0)
    {
      /* If one of these strings is contained in one of the existing queue's
	 device URIs, consider the printer as already configured. Some
	 non-standard CUPS backend use the (obsolete) reference to the
	 usblp device file. This avoids that in such a case a second queue
	 with a standard CUPS backend is auto-created. */
      snprintf(usblpdevstr1, sizeof(usblpdevstr1), "/usb/lp%s",
	       usblpdev);
      snprintf(usblpdevstr2, sizeof(usblpdevstr2), "/usblp%s",
	       usblpdev);
    }

  for (attr = ippFirstAttribute (answer); attr; attr = ippNextAttribute (answer))
    {
      const char *this_printer_uri = NULL;
      const char *this_device_uri = NULL;
      const char *printer_state_message = NULL;
      int state = 0;
      size_t i, l;
      char *this_device_uri_n, *device_uri_n;
      const char *ps1, *ps2, *pi1, *pi2;

      while (attr && ippGetGroupTag (attr) != IPP_TAG_PRINTER)
	attr = ippNextAttribute (answer);

      if (!attr)
	break;

      for (; attr && ippGetGroupTag (attr) == IPP_TAG_PRINTER; attr = ippNextAttribute (answer))
	{
	  if (ippGetValueTag (attr) == IPP_TAG_URI)
	    {
	      if (!strcmp (ippGetName (attr), "device-uri"))
		this_device_uri = ippGetString (attr, 0, NULL);
	      else if (!strcmp (ippGetName (attr), "printer-uri-supported"))
		this_printer_uri = ippGetString (attr, 0, NULL);
	    }
	  else if (ippGetValueTag (attr) == IPP_TAG_TEXT &&
		   !strcmp (ippGetName (attr), "printer-state-message"))
	    printer_state_message = ippGetString (attr, 0, NULL);
	  else if (ippGetValueTag (attr) == IPP_TAG_ENUM &&
		   !strcmp (ippGetName (attr), "printer-state"))
	    state = ippGetInteger (attr, 0);
	}

      if (!this_device_uri)
	/* CUPS didn't include a device-uri attribute in the response
	   for this printer (shouldn't happen). */
	goto skip;

      this_device_uri_n = normalize_device_uri(this_device_uri);
      pi1 = strstr (this_device_uri, "interface=");
      ps1 = strstr (this_device_uri, "serial=");
      for (i = 0; i < device_uris->n_uris; i++)
	{
	  device_uri_n = normalize_device_uri(device_uris->uri[i]);
	  /* As for the same device different URIs can come out when the
	     device is accessed via the usblp kernel module or via low-
	     level USB (libusb) we cannot simply compare URIs, must
	     consider also URIs as equal if one has an "interface"
	     or "serial" attribute and the other not. If both have
	     the attribute it must naturally match. We check which attributes
             are there and this way determine up to which length the two URIs
             must match. Here we can assume that if a URI has an "interface"
	     attribute it has also a "serial" attribute, as this URI is
	     an URI obtained via libusb and these always have a "serial"
	     attribute. usblp-based URIs never have an "interface"
	     attribute.*/
	  pi2 = strstr (device_uris->uri[i], "interface=");
	  ps2 = strstr (device_uris->uri[i], "serial=");
	  if (pi1 && !pi2)
	    l = strlen(device_uris->uri[i]);
	  else if (!pi1 && pi2)
	    l = strlen(this_device_uri);
	  else if (ps1 && !ps2)
	    l = strlen(device_uris->uri[i]);
	  else if (!ps1 && ps2)
	    l = strlen(this_device_uri);
	  else if (strlen(this_device_uri) > strlen(device_uris->uri[i]))
	    l = strlen(this_device_uri);
	  else
	    l = strlen(device_uris->uri[i]);
	  if (firstqueue == 1)
	    {
	      syslog (LOG_DEBUG, "URI of detected printer: %s, normalized: %s",
		      device_uris->uri[i], device_uri_n);
	      if (i == 0 && strlen(usblpdev) > 0)
		syslog (LOG_DEBUG,
			"Consider also queues with \"%s\" or \"%s\" in their URIs as matching",
			usblpdevstr1, usblpdevstr2);
	    }
	  if (i == 0)
	    syslog (LOG_DEBUG, "URI of print queue: %s, normalized: %s",
		    this_device_uri, this_device_uri_n);
	  if ((!strncmp (device_uris->uri[i], this_device_uri, l)) ||
	      (strstr (device_uri_n, this_device_uri_n) ==
	       device_uri_n) ||
	      (strstr (this_device_uri_n, device_uri_n) ==
	       this_device_uri_n) ||
	      ((strlen(usblpdev) > 0) &&
	       ((strstr (this_device_uri, usblpdevstr1) != NULL) ||
	       (strstr (this_device_uri, usblpdevstr2) != NULL))))
	    {
	      matched++;
	      syslog (LOG_DEBUG, "Queue %s has matching device URI",
		      this_printer_uri);
	      if (((flags & MATCH_ONLY_DISABLED) &&
		   state == IPP_PRINTER_STOPPED &&
		   !strcmp (printer_state_message, DISABLED_REASON)) ||
		  (flags & MATCH_ONLY_DISABLED) == 0)
		{
		  (*fn) (this_printer_uri, context);
		  break;
		}
	    }
	}

      firstqueue = 0;

    skip:
      if (!attr)
	break;
    }

  ippDelete (answer);
  return matched;
}

static void
enable_queue (const char *printer_uri, void *context)
{
  /* Enable it. */
  http_t *cups = httpConnectEncrypt (cupsServer (), ippPort (),
				     cupsEncryption ());
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

  if (ippGetStatusCode (answer) > IPP_OK_CONFLICT)
    syslog (LOG_ERR, "IPP-Resume-Printer request failed");
  else
    syslog (LOG_INFO, "Re-enabled printer %s", printer_uri);

  ippDelete (answer);
  httpClose (cups);
}

static gboolean
bluetooth_verify_address (const char *bdaddr)
{
  gboolean retval = TRUE;
  char **elems;
  guint i;

  g_return_val_if_fail (bdaddr != NULL, FALSE);

  if (strlen (bdaddr) != 17)
    return FALSE;

  elems = g_strsplit (bdaddr, ":", -1);
  if (elems == NULL)
    return FALSE;
  if (g_strv_length (elems) != 6) {
    g_strfreev (elems);
    return FALSE;
  }
  for (i = 0; i < 6; i++) {
    if (strlen (elems[i]) != 2 ||
        g_ascii_isxdigit (elems[i][0]) == FALSE ||
        g_ascii_isxdigit (elems[i][1]) == FALSE) {
	  retval = FALSE;
	  break;
    }
  }

  g_strfreev (elems);
  return retval;
}

static int
do_add (const char *cmd, const char *devaddr)
{
  struct device_id id;
  struct device_uris device_uris;
  struct usb_uri_map *map;
  struct udev *udev;
  char *devpath = NULL;
  char *usb_device_devpath = NULL;
  char usbserial[256];
  char usblpdev[8] = "";
  gboolean is_bluetooth;

  syslog (LOG_DEBUG, "add %s", devaddr);

  is_bluetooth = bluetooth_verify_address (devaddr);

  map = read_usb_uri_map ();
  if (is_bluetooth) {
    usbserial[0] = '\0';
    device_id_from_bluetooth (devaddr, &id);
  } else {
    udev = udev_new ();
    if (udev == NULL)
      {
	syslog (LOG_ERR, "udev_new failed");
	exit (1);
      }

    if (!strncmp (devaddr, "usb-", 4))
      devpath = devpath_from_usb_devaddr (udev, devaddr);
    else
      devpath = g_strdup (devaddr);

    usb_device_devpath = device_id_from_devpath (udev, devpath, map, &id,
						 usbserial, sizeof (usbserial),
						 usblpdev, sizeof (usblpdev));
    g_free (devpath);
    udev_unref (udev);
  }

  if (!id.mfg || !id.mdl)
    return 1;

  syslog (LOG_DEBUG, "MFG:%s MDL:%s SERN:%s serial:%s", id.mfg, id.mdl,
	  id.sern ? id.sern : "-", usbserial[0] ? usbserial : "-");

  if (!is_bluetooth)
    {
      find_matching_device_uris (&id, usbserial, &device_uris, usb_device_devpath,
				 map);
      free (usb_device_devpath);
    } else {
      char *device_uri;

      device_uri = uri_from_bdaddr (devpath);
      add_device_uri (&device_uris, device_uri);
      g_free (device_uri);
    }

  if (device_uris.n_uris == 0)
    {
      syslog (LOG_ERR, "no corresponding CUPS device found");
      free_device_id (&id);
      return 0;
    }

  /* Re-enable any queues we'd previously disabled. */
  if (for_each_matching_queue (&device_uris, MATCH_ONLY_DISABLED,
			       enable_queue, NULL,
			       usblpdev, sizeof (usblpdev)) == 0)
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
remove_queue (const char *printer_uri)
{
  /* Disable it. */
  http_t *cups = httpConnectEncrypt (cupsServer (), ippPort (),
				     cupsEncryption ());
  ipp_t *request, *answer;

  if (cups == NULL)
    return;

  request = ippNewRequest (CUPS_DELETE_PRINTER);
  ippAddString (request, IPP_TAG_OPERATION, IPP_TAG_URI,
		"printer-uri", NULL, printer_uri);
  answer = cupsDoRequest (cups, request, "/admin/");
  if (!answer)
    {
      syslog (LOG_ERR, "Failed to send IPP-Delete-Printer request");
      httpClose (cups);
      return;
    }

  if (ippGetStatusCode (answer) > IPP_OK_CONFLICT)
    syslog (LOG_ERR, "IPP-Delete-Printer request failed");
  else
    syslog (LOG_INFO, "Deleted printer %s as the corresponding device "
	    "was unpaired", printer_uri);

  ippDelete (answer);
  httpClose (cups);
}

static void
disable_queue (const char *printer_uri, void *context)
{
  /* Disable it. */
  http_t *cups = httpConnectEncrypt (cupsServer (), ippPort (),
				     cupsEncryption ());
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

  if (ippGetStatusCode (answer) > IPP_OK_CONFLICT)
    syslog (LOG_ERR, "IPP-Pause-Printer request failed");
  else
    syslog (LOG_INFO, "Disabled printer %s as the corresponding device "
	    "was unplugged or turned off", printer_uri);

  ippDelete (answer);
  httpClose (cups);
}

static int
do_remove (const char *devaddr)
{
  struct usb_uri_map *map;
  struct usb_uri_map_entry *entry, **prev;
  struct device_uris *uris = NULL;
  char usblpdev[8] = "";
  gchar *devpath = NULL;
  syslog (LOG_DEBUG, "remove %s", devaddr);

  if (bluetooth_verify_address (devaddr))
    {
      char *device_uri;

      device_uri = uri_from_bdaddr (devaddr);
      remove_queue (devpath);
      g_free (device_uri);
      return 0;
    }

  if (!strncmp (devaddr, "usb-", 4))
    {
      struct udev *udev = udev_new ();
      if (udev == NULL)
	{
	  syslog (LOG_ERR, "udev_new failed");
	  exit (1);
	}

      devpath = devpath_from_usb_devaddr (udev, devaddr);
      udev_unref (udev);
    }
  else
    devpath = g_strdup (devaddr);

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
      for_each_matching_queue (uris, 0, disable_queue, NULL,
			       usblpdev, sizeof (usblpdev));
      *prev = entry->next;
      write_usb_uri_map (map);
    }

  free_usb_uri_map (map);
  g_free (devpath);
  return 0;
}

int
main (int argc, char **argv)
{
  int add = 0;
  int enumerate = 0;

  if (argc > 1)
    {
      add = !strcmp (argv[1], "add");
      enumerate = !strcmp (argv[1], "enumerate");
    }

  if (!(argc == 3 &&
        (add || !strcmp (argv[1], "remove"))) &&
      !(argc == 2 && enumerate))
    {
      fprintf (stderr,
	       "Syntax: %s add {USB device path}\n"
	       "        %s remove {USB device path}\n"
               "        %s enumerate\n",
	       argv[0], argv[0], argv[0]);
      return 1;
    }

  openlog ("udev-configure-printer", 0, LOG_LPR);
  cupsSetPasswordCB (no_password);
  if (add)
    return do_add (argv[0], argv[2]);
  if (enumerate)
    return 0; // no-op

  return do_remove (argv[2]);
}

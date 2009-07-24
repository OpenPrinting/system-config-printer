/* -*- Mode: C; c-file-style: "gnu" -*-
 * udev-usb-printer - a udev callout to configure print queues
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
 * udev-usb-printer add {DEVPATH}
 * udev-usb-printer remove {DEVPATH}
 *
 * where DEVPATH is the path (%p) of the device
 */

#define LIBUDEV_I_KNOW_THE_API_IS_SUBJECT_TO_CHANGE 1

#include <dbus/dbus-glib-bindings.h>
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

#include "printer-config-client-bindings.h"

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
syspath_from_devpath (struct udev *udev, const char *devpath)
{
  const char *sys;
  char *syspath;
  size_t syslen, devpathlen = strlen (devpath);
  sys = udev_get_sys_path (udev);
  syslen = strlen (sys);
  syspath = malloc (syslen + devpathlen + 1);
  if (syspath == NULL)
    return NULL;

  memcpy (syspath, sys, syslen);
  memcpy (syspath + syslen, devpath, devpathlen);
  syspath[syslen + devpathlen] = '\0';
  return syspath;
}

static char *
device_id_from_devpath (const char *devpath,
			struct device_id *id,
			char *usbserial, size_t usbseriallen)
{
  struct udev *udev;
  struct udev_device *dev, *parent_dev = NULL;
  const char *idVendorStr, *idProductStr, *serial;
  char *end;
  unsigned long idVendor, idProduct;
  struct usb_bus *bus;
  struct usb_dev_handle *handle = NULL;
  char ieee1284_id[1024];
  const char *device_id = NULL;
  char *syspath;
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

  syspath = syspath_from_devpath (udev, devpath);
  if (syspath == NULL)
    {
      udev_unref (udev);
      exit (1);
    }

  dev = udev_device_new_from_syspath (udev, syspath);
  if (dev == NULL)
    {
      udev_device_unref (dev);
      udev_unref (udev);
      syslog (LOG_ERR, "unable to access %s", syspath);
      free (syspath);
      exit (1);
    }

  free (syspath);
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

static int
do_add (DBusGProxy *proxy, const char *devpath)
{
  GError *error = NULL;
  struct device_id id;
  char *usb_device_devpath;
  char usbserial[256];

  syslog (LOG_DEBUG, "add %s", devpath);

  usb_device_devpath = device_id_from_devpath (devpath, &id,
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

  com_redhat_PrinterConfig_usb_printer_add (proxy,
					    usb_device_devpath,
					    id.full_device_id,
					    &error);
  free (usb_device_devpath);
  free_device_id (&id);
  return 0;
}

static int
do_remove (DBusGProxy *proxy, const char *devpath)
{
  GError *error = NULL;
  syslog (LOG_DEBUG, "remove %s", devpath);

  com_redhat_PrinterConfig_usb_printer_remove (proxy,
					       devpath,
					       &error);
  return 0;
}

int
main (int argc, char **argv)
{
  DBusGConnection *connection;
  DBusGProxy *proxy;
  GError *error = NULL;
  int add;

  g_type_init ();

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

  openlog ("udev-usb-printer", 0, LOG_LPR);

  connection = dbus_g_bus_get (DBUS_BUS_SYSTEM, &error);
  if (connection == NULL)
    {
      syslog (LOG_ERR, "unable to connect to D-Bus: %s", error->message);
      g_error_free (error);
      exit (1);
    }

  proxy = dbus_g_proxy_new_for_name (connection,
				     "com.redhat.PrinterConfig",
				     "/com/redhat/PrinterConfig",
				     "com.redhat.PrinterConfig");

  if (add)
    do_add (proxy, argv[2]);
  else
    do_remove (proxy, argv[2]);

  g_object_unref (proxy);
  return 0;
}

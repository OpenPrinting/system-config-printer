/* -*- Mode: C; c-file-style: "gnu" -*-
 *
 * Copyright (C) 2007 David Zeuthen <davidz@redhat.com>
 * Copyright (C) 2009 Red Hat, Inc.
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
 * Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
 *
 */

#ifdef HAVE_CONFIG_H
#  include "config.h"
#endif

#include <stdlib.h>
#include <stdio.h>
#include <unistd.h>
#include <signal.h>
#include <errno.h>
#include <string.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <pwd.h>
#include <grp.h>

#include <glib.h>
#include <glib-object.h>

#define DBUS_API_SUBJECT_TO_CHANGE
#include <dbus/dbus-glib.h>
#include <dbus/dbus-glib-lowlevel.h>

#include "printer-config.h"

#define NAME_TO_CLAIM "com.redhat.PrinterConfig"

static gboolean
acquire_name_on_proxy (DBusGProxy *bus_proxy)
{
  GError     *error;
  guint       result;
  gboolean    res;
  gboolean    ret;

  ret = FALSE;

  if (bus_proxy == NULL) {
    goto out;
  }

  error = NULL;
  res = dbus_g_proxy_call (bus_proxy,
			   "RequestName",
			   &error,
			   G_TYPE_STRING, NAME_TO_CLAIM,
			   G_TYPE_UINT, 0,
			   G_TYPE_INVALID,
			   G_TYPE_UINT, &result,
			   G_TYPE_INVALID);
  if (! res) {
    if (error != NULL) {
      g_warning ("Failed to acquire %s: %s", NAME_TO_CLAIM, error->message);
      g_error_free (error);
    } else {
      g_warning ("Failed to acquire %s", NAME_TO_CLAIM);
    }
    goto out;
  }

  if (result != DBUS_REQUEST_NAME_REPLY_PRIMARY_OWNER) {
    if (error != NULL) {
      g_warning ("Failed to acquire %s: %s", NAME_TO_CLAIM, error->message);
      g_error_free (error);
    } else {
      g_warning ("Failed to acquire %s", NAME_TO_CLAIM);
    }
    goto out;
  }

  ret = TRUE;

 out:
  return ret;
}

static GMainLoop *loop;

void main_quit (void);

void
main_quit (void)
{
  g_main_loop_quit (loop);
}

int
main (int argc, char **argv)
{
  PrinterConfigDaemon *daemon;
  GError *error;
  DBusGProxy *bus_proxy;
  DBusGConnection *bus;
  int ret = 1;

  g_type_init ();

  error = NULL;
  bus = dbus_g_bus_get (DBUS_BUS_SYSTEM, &error);
  if (bus == NULL) {
    g_warning ("Couldn't connect to system bus: %s", error->message);
    g_error_free (error);
    goto out;
  }

  bus_proxy = dbus_g_proxy_new_for_name (bus,
					 DBUS_SERVICE_DBUS,
					 DBUS_PATH_DBUS,
					 DBUS_INTERFACE_DBUS);
  if (bus_proxy == NULL) {
    g_warning ("Could not construct bus_proxy object; bailing out");
    goto out;
  }

  if (!acquire_name_on_proxy (bus_proxy) ) {
    g_warning ("Could not acquire name; bailing out");
    goto out;
  }

  g_debug ("Starting printer-config-daemon version %s", VERSION);

  daemon = printer_config_daemon_new ();

  if (daemon == NULL) {
    goto out;
  }

  loop = g_main_loop_new (NULL, FALSE);

  g_main_loop_run (loop);

  g_object_unref (daemon);
  g_main_loop_unref (loop);
  ret = 0;

 out:
  return ret;
}

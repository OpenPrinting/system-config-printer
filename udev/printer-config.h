/* -*- Mode: C; c-file-style: "gnu" -*-
 * printer-config - a D-Bus service for configuring printers
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

#ifndef PRINTER_CONFIG_H
#define PRINTER_CONFIG_H

#include <glib-object.h>
#include <dbus/dbus-glib.h>

#define PRINTER_CONFIG_TYPE_DAEMON	(printer_config_daemon_get_type ())
#define PRINTER_CONFIG_DAEMON(obj)					\
  (G_TYPE_CHECK_INSTANCE_CAST ((obj),					\
			       PRINTER_CONFIG_TYPE_DAEMON,		\
			       PrinterConfigDaemon))
#define PRINTER_CONFIG_IS_DAEMON_CLASS(klass)				\
  (G_TYPE_CHECK_CLASS_CAST ((klass), PRINTER_CONFIG_TYPE_DAEMON,	\
			    PrinterConfigDaemonClass))
#define PRINTER_CONFIG_DAEMON_GET_CLASS(obj)				\
  (G_TYPE_INSTANCE_GET_CLASS ((obj), PRINTER_CONFIG_TYPE_DAEMON,	\
			      PrinterConfigDaemonClass))

typedef struct _PrinterConfigDaemon	PrinterConfigDaemon;
typedef struct _PrinterConfigDaemonClass PrinterConfigDaemonClass;

struct children;
struct _PrinterConfigDaemon
{
  GObject parent_instance;

  /* instance members */
  struct children *children;
  guint killtimer;
};

struct _PrinterConfigDaemonClass
{
  GObjectClass parent_class;

  /* class members */
  DBusGConnection *connection;
};

/* used by PRINTER_CONFIG_TYPE_DAEMON */
GType printer_config_daemon_get_type (void);

PrinterConfigDaemon *printer_config_daemon_new (void);
gboolean printer_config_daemon_usb_printer_add (PrinterConfigDaemon *d,
						const char *devpath,
						const char *deviceid,
						DBusGMethodInvocation *ctx);

gboolean printer_config_daemon_usb_printer_remove (PrinterConfigDaemon *d,
						   const char *devpath,
						   DBusGMethodInvocation *ctx);

void main_quit (void);

#endif /* PRINTER_CONFIG_H */

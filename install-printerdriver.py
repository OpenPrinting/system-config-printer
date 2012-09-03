#!/usr/bin/python

from gi.repository import GLib, PackageKitGlib
import sys

# progress callback
# http://www.packagekit.org/gtk-doc/PkProgress.html
def progress(progress, type, user_data):
    if (type.value_name == "PK_PROGRESS_TYPE_PERCENTAGE" and
        progress.props.package != None):
        sys.stderr.write ("%d\n" % progress.props.percentage)
        sys.stderr.flush ()

package = sys.argv[1]
repo = sys.argv[2]
try:
    repo_gpg_id = sys.argv[3]
except:
    repo_gpg_id = None

# get PackageKit client
pk = PackageKitGlib.Client()

# check if we already have the package installed or available
try:
    res = pk.resolve(PackageKitGlib.FilterEnum.NONE, [package],
                     None, lambda p, t, d: True, None)
except GLib.GError:
    # cannot resolve, so we need to install the key and repo
    # install repository key
    if repo_gpg_id:
        try:
            res = pk.install_signature(PackageKitGlib.SigTypeEnum.GPG, repo_gpg_id,
                                       '', None, progress, None)
        except GLib.GError:
            sys.exit(1)
        if res.get_exit_code() != PackageKitGlib.ExitEnum.SUCCESS:
            sys.exit(1)

    # add repository; see
    # http://www.packagekit.org/gtk-doc/PackageKit-pk-client-sync.html#pk-client-repo-enable
    try:
        res = pk.repo_enable(repo, True, None, progress, None)
    except GLib.GError:
        sys.exit(1)
    if res.get_exit_code() != PackageKitGlib.ExitEnum.SUCCESS:
        sys.exit(1)

    # download/update the indexes
    try:
        res = pk.refresh_cache(False, None, progress, None)
    except GLib.GError:
        sys.exit(1)
    if res.get_exit_code() != PackageKitGlib.ExitEnum.SUCCESS:
        sys.exit(1)

# map package name to PackageKit ID; do not print progress here, it's fast
try:
    res = pk.resolve(PackageKitGlib.FilterEnum.NONE, [package],
                     None, lambda p, t, d: True, None)
except GLib.GError:
    sys.exit(1)
if res.get_exit_code() != PackageKitGlib.ExitEnum.SUCCESS:
    sys.exit(1)
package_ids = res.get_package_array()
if len(package_ids) <= 0:
    sys.exit(1)
package_id = package_ids[0].get_id()

# install the first match, unless already installed
if package_ids[0].get_info() & PackageKitGlib.InfoEnum.INSTALLED == 0:
    # install package
    try:
        res = pk.install_packages(True, [package_id], None, progress, None)
    except GLib.GError:
        sys.exit(1)
    if res.get_exit_code() != PackageKitGlib.ExitEnum.SUCCESS:
        sys.exit(1)

# If we reach this point, the requested package is on the system, either
# because we have installed it now or because it was already there

# Return the list of files contained in the package
try:
    res = pk.get_files([package_id], None, progress, None)
except GLib.GError:
    pass

files = res.get_files_array()
if files:
    for f in files[0].get_property('files'):
        print f

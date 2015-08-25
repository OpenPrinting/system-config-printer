#!/usr/bin/python3

from gi.repository import GLib, PackageKitGlib
import sys
from debug import *

# progress callback
# http://www.packagekit.org/gtk-doc/PkProgress.html
def progress(progress, type, user_data):
    if (type.value_name == "PK_PROGRESS_TYPE_PERCENTAGE" and
        progress.props.package is not None):
        sys.stdout.write ("P%d\n" % progress.props.percentage)
        sys.stdout.flush ()
    else:
        sys.stdout.write ("P%d\n" % -10)
        sys.stdout.flush ()

set_debugging (True)

package = sys.argv[1]
repo = sys.argv[2]
try:
    repo_gpg_id = sys.argv[3]
except:
    repo_gpg_id = None

# get PackageKit client
pk = PackageKitGlib.Client()

refresh_cache_needed = False

# install repository key
if repo_gpg_id:
    debugprint("Signature key supplied")
    debugprint("pk.install_signature")
    try:
        res = pk.install_signature(PackageKitGlib.SigTypeEnum.GPG, repo_gpg_id,
                                       '', None, progress, None)
        refresh_cache_needed = True
        debugprint("pk.install_signature succeeded")
    except GLib.GError:
        debugprint("pk.install_signature failed")
        sys.exit(1)
    if res.get_exit_code() != PackageKitGlib.ExitEnum.SUCCESS:
        debugprint("pk.install_signature errored")
        sys.exit(1)

# check if we already have the package installed or available
debugprint("pk.resolve")
try:
    res = pk.resolve(PackageKitGlib.FilterEnum.NONE, [package],
                     None, progress, None)
    repo_enable_needed = False
    debugprint("pk.resolve succeeded")
except GLib.GError:
    repo_enable_needed = True
    debugprint("pk.resolve failed")
package_ids = res.get_package_array()
if len(package_ids) <= 0:
    debugprint("res.get_package_array() failed")
    repo_enable_needed = True

if repo_enable_needed:
    # Cannot resolve, so we need to install the repo
    # add repository; see
    # http://www.packagekit.org/gtk-doc/PackageKit-pk-client-sync.html#pk-client-repo-enable
    debugprint("pk.repo_enable")
    try:
        res = pk.repo_enable(repo, True, None, progress, None)
        refresh_cache_needed = True
        debugprint("pk.repo_enable succeeded")
    except GLib.GError:
        debugprint("pk.repo_enable failed")
        sys.exit(1)
    if res.get_exit_code() != PackageKitGlib.ExitEnum.SUCCESS:
        debugprint("pk.repo_enable errored")
        sys.exit(1)

if refresh_cache_needed:
    # download/update the indexes
    debugprint("pk.refresh_cache")
    try:
        res = pk.refresh_cache(False, None, progress, None)
        debugprint("pk.refresh_cache succeeded")
    except GLib.GError:
        debugprint("pk.refresh_cache failed")
    if res.get_exit_code() != PackageKitGlib.ExitEnum.SUCCESS:
        debugprint("pk.refresh_cache errored")

# map package name to PackageKit ID; do not print progress here, it's fast
debugprint("pk.resolve")
try:
    res = pk.resolve(PackageKitGlib.FilterEnum.NONE, [package],
                     None, progress, None)
    debugprint("pk.resolve succeeded")
except GLib.GError:
    debugprint("pk.resolve failed")
    sys.exit(1)
if res.get_exit_code() != PackageKitGlib.ExitEnum.SUCCESS:
    debugprint("pk.resolve errored")
    sys.exit(1)
package_ids = res.get_package_array()
if len(package_ids) <= 0:
    debugprint("res.get_package_array() failed")
    sys.exit(1)
package_id = package_ids[0].get_id()
debugprint("package_id: %s" % package_id)

# install the first match, unless already installed
if package_ids[0].get_info() & PackageKitGlib.InfoEnum.INSTALLED == 0:
    debugprint("package not installed")
    debugprint("pk.install_packages")
    # install package
    if repo_gpg_id:
        debugprint("Signature key supplied")
        repo_gpg_id_supplied = True
    else:
        debugprint("Signature key not supplied")
        repo_gpg_id_supplied = False
    try:
        res = pk.install_packages(repo_gpg_id_supplied, [package_id], None,
                                  progress, None)
        debugprint("pk.install_packages succeeded")
    except GLib.GError:
        debugprint("pk.install_packages failed, retrying with modified package ID")
        # See aptdaemon Ubuntu bug #1397750.
        try:
            # Remove last element of the package ID, after the last ";"
            package_id_mod = package_id[:package_id.rfind(";")+1]
            res = pk.install_packages(repo_gpg_id_supplied, [package_id_mod],
                                      None, progress, None)
            debugprint("pk.install_packages succeeded")
        except GLib.GError:
            debugprint("pk.install_packages failed")
            sys.exit(1)
    if res.get_exit_code() != PackageKitGlib.ExitEnum.SUCCESS:
        debugprint("pk.install_packages errored")
        sys.exit(1)

debugprint("Package successfully installed")
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
        print(f)

# Tell the caller that we are done
print("done")

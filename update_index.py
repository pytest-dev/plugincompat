"""
Updates the plugin index with the latest version and descriptions from
PyPI.

The index file (index.json) contains all plugins found by a search for
"pytest-" in PyPI in order to find all pytest plugins. We then save their
latest version and description into index.json, which will be read by
"run.py" in order to execute compatibility tests between the plugins
and pytest/python versions. See "run.py" for more details.

Usage:

    python update_index.py

If index.json was updated, it should be pushed back to GitHub, which will
trigger a new travis build using the new versions.
"""
import json
import os
import re
import sys
import time
from distutils.version import LooseVersion
from xmlrpc.client import Fault
from xmlrpc.client import ServerProxy

INDEX_FILE_NAME = os.path.join(os.path.dirname(__file__), "index.json")

BLACKLIST = {"pytest-nbsmoke"}


def get_releases_for_package(client, package_name):
    """
    Get all release versions for package 'package_name' and return them to the caller

    :param client: xmlrpclib.ServerProxy
    :param package_name: package name to search for
    """
    versions = None

    fetched_releases = False
    while not fetched_releases:
        try:
            versions = client.package_releases(package_name)
            fetched_releases = True
        except Fault as fault:
            # The message is like:
            #   The action could not be performed because there were too many requests by the client. Limit may reset in 1 seconds.
            #raise ValueError(fault.faultString)
            regex_match = re.search('^.+Limit may reset in (\d+) seconds\.$', fault.faultString)
            if regex_match is None:
                raise fault

            sleep_amt = int(regex_match.group(1))
            time.sleep(sleep_amt)

    return versions


def iter_plugins(client, blacklist, *, consider_classifier=True):
    """
    Returns an iterator of (name, latest version, summary) from PyPI.

    :param client: xmlrpclib.ServerProxy
    :param search: package names to search for
    """
    # previously we used the more efficient "search" XMLRPC method, but
    # that stopped returning all results after a while
    package_names = [x for x in client.list_packages() if x.startswith("pytest-")]
    package_names = package_names[1:50] # TEMP: for testing full set is way too large
    names_and_versions = {}
    print("TEMP: Processing '{}' packages".format(len(package_names)))
    counter = 0
    for name in package_names:
        print("process package '{}'".format(counter))
        counter += 1
        versions = get_releases_for_package(client, name)
        if versions:  # Package can exist without public releases
            names_and_versions[name] = max(versions, key=LooseVersion)

    print("pytest-*: %d packages" % len(names_and_versions))

    # search for the new Pytest classifier
    if consider_classifier:
        found = client.browse(["Framework :: Pytest"])
        valid = 0
        for name, version in found:
            if name and version:
                names_and_versions[name] = version
                valid += 1
        print("classifier: %d packages (%d valid)" % (len(found), valid))
        print("total: %d packages" % len(names_and_versions))
    else:
        print("skipping search by classifier")

    for name, version in names_and_versions.items():
        if name not in blacklist:
            plug_data = client.release_data(name, version)
            yield plug_data["name"], plug_data["version"], plug_data["summary"]


def write_plugins_index(file_name, plugins):
    """
    Writes the list of (name, version, description) of the plugins given
    into the index file in JSON format.
    Returns True if the file was actually updated, or False if it was already
    up-to-date.
    """
    # separators is given to avoid trailing whitespaces; see docs
    plugin_contents = []
    for (name, version, description) in plugins:
        plugin_contents.append({"name": name, "version": version, "description": description})
    contents = json.dumps(plugin_contents, indent=2, separators=(",", ": "), sort_keys=True)
    if os.path.isfile(file_name):
        if sys.version_info < (3,):
            mode = "rU"
        else:
            # universal newlines is enabled by default, and specifying it
            # will cause deprecation warnings
            mode = "r"
        with open(file_name, mode) as f:
            current_contents = f.read()
    else:
        current_contents = ""

    if contents.strip() != current_contents.strip():
        with open(file_name, "w") as f:
            f.write(contents + "\n")
        return True
    else:
        return False


def main():
    client = ServerProxy("https://pypi.org/pypi")
    plugins = sorted(iter_plugins(client, BLACKLIST, consider_classifier=False))

    if write_plugins_index(INDEX_FILE_NAME, plugins):
        print(INDEX_FILE_NAME, "updated, push to GitHub.")
    else:
        print(INDEX_FILE_NAME, "skipped, no changes.")


if __name__ == "__main__":
    main()

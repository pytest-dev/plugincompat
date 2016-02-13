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
from __future__ import print_function, with_statement, division

import itertools
import json
import os
import sys
from distutils.version import LooseVersion

if sys.version_info[0] == 3:
    from xmlrpc.client import ServerProxy
else:
    from xmlrpclib import ServerProxy

INDEX_FILE_NAME = os.path.join(os.path.dirname(__file__), 'index.json')


def iter_plugins(client, search='pytest'):
    '''
    Returns an iterator of (name, version, summary) from PyPI.

    :param client: xmlrpclib.ServerProxy
    :param search: package names to search for
    '''
    for plug_data in client.search({'name': search}):
        if plug_data['name'].startswith('pytest-'):
            yield plug_data['name'], plug_data['version'], plug_data['summary']


def get_latest_versions(plugins):
    '''
    Returns an iterator of (name, version, summary) from the given list of (name,
    version, summary), but returning only the latest version of the package. Uses
    distutils.LooseVersion to ensure compatibility with PEP386.
    '''
    plugins = [(name, LooseVersion(version), desc) for (name, version, desc) in plugins]
    for name, grouped_plugins in itertools.groupby(plugins, key=lambda x: x[0]):
        name, loose_version, desc = list(grouped_plugins)[-1]
        yield name, str(loose_version), desc


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
        plugin_contents.append({
            'name': name,
            'version': version,
            'description': description,
        })
    contents = json.dumps(plugin_contents, indent=2, separators=(',', ': '), 
                          sort_keys=True)
    if os.path.isfile(file_name):
        with open(file_name, 'rU') as f:
            current_contents = f.read()
    else:
        current_contents = ''

    if contents != current_contents:
        with open(file_name, 'w') as f:
            f.write(contents)
        return True
    else:
        return False


def main():
    client = ServerProxy('https://pypi.python.org/pypi')
    plugins = list(iter_plugins(client))
    plugins = sorted(get_latest_versions(plugins))

    if write_plugins_index(INDEX_FILE_NAME, plugins):
        print(INDEX_FILE_NAME, 'updated, push to GitHub.')
    else:
        print(INDEX_FILE_NAME, 'skipped, no changes.')


if __name__ == '__main__':
    main()

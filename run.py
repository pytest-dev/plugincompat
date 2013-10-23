from __future__ import print_function, with_statement, division
from distutils.version import LooseVersion

import os
import sys
import tarfile
from zipfile import ZipFile

#===================================================================================================
# py2x3 compatibility
#===================================================================================================
import itertools

if sys.version_info[0] == 3:
    from xmlrpc.client import ServerProxy
    from urllib.request import urlretrieve
else:
    from xmlrpclib import ServerProxy
    from urllib import urlretrieve


#===================================================================================================
# iter_plugins
#===================================================================================================
def iter_plugins(client, search='pytest-'):
    '''
    Returns an iterator of (name, version) from PyPI.
    
    :param client: xmlrpclib.ServerProxy
    :param search: package names to search for 
    '''
    for plug_data in client.search({'name': search}):
        yield plug_data['name'], plug_data['version']


#===================================================================================================
# get_latest_versions
#===================================================================================================
def get_latest_versions(plugins):
    '''
    Returns an iterator of (name, version) from the given list of (name, version), but returning
    only the latest version of the package. Uses distutils.LooseVersion to ensure compatibility
    with PEP386.
    '''
    plugins = [(name, LooseVersion(version)) for (name, version) in plugins]
    for name, grouped_plugins in itertools.groupby(plugins, key=lambda x: x[0]):
        name, loose_version = list(grouped_plugins)[-1]
        yield name, str(loose_version)


#===================================================================================================
# download_package
#===================================================================================================
def download_package(client, name, version):
    found_dists = []
    for url_data in client.release_urls(name, version):
        basename = os.path.basename(url_data['url'])
        found_dists.append(url_data['packagetype'])
        if url_data['packagetype'] == 'sdist':
            urlretrieve(url_data['url'], basename)
            return basename

    return None


#===================================================================================================
# extract
#===================================================================================================
def extract(basename):
    from contextlib import closing

    extractors = {
        '.zip': ZipFile,
        '.tar.gz': tarfile.open,
        '.tgz': tarfile.open,
    }
    for ext, extractor in extractors.items():
        if basename.endswith(ext):
            with closing(extractor(basename)) as f: # need closing for python 2.6 because of TarFile
                f.extractall('.')
            return basename[:-len(ext)]
    assert False, 'could not extract %s' % basename


#===================================================================================================
# run_tox
#===================================================================================================
def run_tox(directory):
    tox_env = 'py%d%d' % sys.version_info[:2]

    tox_file = os.path.join(directory, 'tox.ini')
    if not os.path.isfile(tox_file):
        f = open(tox_file, 'w')
        try:
            f.write(PLACEHOLDER_TOX)
        finally:
            f.close()

    oldcwd = os.getcwd()
    try:
        os.chdir(directory)
        result = os.system('tox --result-json=result.json -e %s' % tox_env)
        return result
    finally:
        os.chdir(oldcwd)


# tox.ini contents when downloaded package does not have a tox.ini file
# in this case we only display help information
PLACEHOLDER_TOX = '''\
[tox]

[testenv]
deps=pytest
commands=
    py.test --help
'''


#===================================================================================================
# main
#===================================================================================================
def main():
    client = ServerProxy('https://pypi.python.org/pypi')

    plugins = iter_plugins(client)
    plugins = get_latest_versions(plugins)
    #plugins = [
    #    ('pytest-pep8', '1.0.5'),
    #    ('pytest-cache', '1.0'),
    #    ('pytest-xdist', '1.9'),
    #    ('pytest-bugzilla', '0.2'),
    #]

    test_results = {}
    for name, version in plugins:
        print('=' * 60)
        print('%s-%s' % (name, version))
        basename = download_package(client, name, version)
        if basename is None:
            print('-> No sdist found (skipping)')
            continue
        print('-> downloaded', basename)
        directory = extract(basename)
        print('-> extracted to', directory)
        result = run_tox(directory)
        print('-> tox returned %s' % result)
        test_results[(name, version)] = result


    print('\n\n')
    print('=' * 60)
    print('Summary')
    print('=' * 60)
    for (name, version) in sorted(test_results):
        result = test_results[(name, version)]
        if result == 0:
            status = 'OK'
        else:
            status = 'Failed'
        print('%s-%s \t\t\t %s' % (name, version, status))


#===================================================================================================
# main
#===================================================================================================
if __name__ == '__main__':
    main()  

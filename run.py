from __future__ import print_function, with_statement, division
from distutils.version import LooseVersion

import os
import sys
import tarfile
from zipfile import ZipFile
import itertools
import requests
import simplejson
import subprocess


if sys.version_info[0] == 3:
    from xmlrpc.client import ServerProxy
    from urllib.request import urlretrieve
else:
    from xmlrpclib import ServerProxy
    from urllib import urlretrieve


def iter_plugins(client, search='pytest-'):
    '''
    Returns an iterator of (name, version) from PyPI.
    
    :param client: xmlrpclib.ServerProxy
    :param search: package names to search for 
    '''
    for plug_data in client.search({'name': search}):
        yield plug_data['name'], plug_data['version']


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


def download_package(client, name, version):
    found_dists = []
    for url_data in client.release_urls(name, version):
        basename = os.path.basename(url_data['url'])
        found_dists.append(url_data['packagetype'])
        if url_data['packagetype'] == 'sdist':
            urlretrieve(url_data['url'], basename)
            return basename

    return None


def extract(basename):
    """
    Extracts the contents of the given archive into the current directory.

    :param basename: name of the archive related to the current directory
    :type basename: str

    :rtype: str
    :return: the name of the directory where the contents where extracted
    """
    from contextlib import closing


    extractors = {
        '.zip': ZipFile,
        '.tar.gz': tarfile.open,
        '.tgz': tarfile.open,
    }
    for ext, extractor in extractors.items():
        if basename.endswith(ext):
            with closing(extractor(
                    basename)) as f: # need closing for python 2.6 because of TarFile
                f.extractall('.')
            return basename[:-len(ext)]
    assert False, 'could not extract %s' % basename


def run_tox(directory, tox_env, pytest_version):
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
        cmdline = 'tox --result-json=result.json -e %s --force-dep=pytest==%s'
        cmdline %= (tox_env, pytest_version)

        try:
            output = subprocess.check_output(
                cmdline, shell=True, stderr=subprocess.STDOUT)
            result = 0
        except subprocess.CalledProcessError as e:
            result = e.returncode
            output = e.output

        return result, output
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


def main():
    tox_env = 'py%d%d' % sys.version_info[:2]
    pytest_version = os.environ['PYTEST_VERSION']
    client = ServerProxy('https://pypi.python.org/pypi')

    plugins = iter_plugins(client)
    plugins = list(get_latest_versions(plugins))
    #plugins = [
        #('pytest-pep8', '1.0.5'),
        #    ('pytest-cache', '1.0'),
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
        result, output = run_tox(directory, tox_env, pytest_version)
        print('-> tox returned %s' % result)
        test_results[(name, version)] = result, output

    print('\n\n')
    print('=' * 60)
    print('Summary')
    print('=' * 60)
    post_data = []
    for (name, version) in sorted(test_results):
        result, output = test_results[(name, version)]
        if result == 0:
            status = 'ok'
        else:
            status = 'fail'
        package = '%s-%s' % (name, version)
        spaces = (50 - len(package)) * ' '
        print('%s%s%s' % (package, spaces, status))
        post_data.append(
            {'name': name,
             'version': version,
             'env': tox_env,
             'pytest': pytest_version,
             'status': status,
             'output': output,
            }
        )
    post_url = os.environ.get('PLUGS_SITE')
    if post_url:
        headers = {'content-type': 'application/json'}
        response = requests.post(post_url, data=simplejson.dumps(post_data),
                                 headers=headers)
        print('posted to {}; response={}'.format(post_url, response))
    else:
        print('not posting, no $PLUGS_SITE defined: {}'.format(post_data))


#===================================================================================================
# main
#===================================================================================================
if __name__ == '__main__':
    main()  

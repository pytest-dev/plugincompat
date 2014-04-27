"""
Reads index.txt file containing plugins versions and descriptions, and
test them against current python version and pytest version selected by
$PYTEST_VERSION environment variable.

The plugins are tested using tox. If a plugin provides a tox.ini file,
that is used to test the plugin compatibility, otherwise we provide a simple
tox.ini that practically just tests that the plugin was installed successfully
by running `pytest --help`.

The pytest version to use is obtained by $PYTEST_VERSION, which is forced as
a dependency when invoking tox.

Once all results are obtained, they are posted to the pytest-plugs heroku app
which can then be visualized.
"""
from __future__ import print_function, with_statement, division

import os
import sys
import tarfile
from zipfile import ZipFile
import subprocess
import json

import requests

import update_index


if sys.version_info[0] == 3:
    from urllib.request import urlretrieve
    from xmlrpc.client import ServerProxy
else:
    from urllib import urlretrieve
    from xmlrpclib import ServerProxy


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
            with closing(extractor(basename)) as f:
                f.extractall('.')
            return basename[:-len(ext)]
    assert False, 'could not extract %s' % basename


def run_tox(directory, tox_env, pytest_version):
    """
    Runs tox on the given directory and return (exit code, output)
    """
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
            output = e.output.decode()

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


def read_plugins_index(file_name):
    with open(file_name) as f:
        return json.load(f)


def main():
    pytest_version = os.environ['PYTEST_VERSION']
    tox_env = 'py%d%d' % sys.version_info[:2]

    client = ServerProxy('https://pypi.python.org/pypi')

    plugins = read_plugins_index(update_index.INDEX_FILE_NAME)

    test_results = {}
    for name, version, desc in plugins:
        # if name != 'pytest-pep8':
        #     continue
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
        test_results[(name, version)] = result, output, desc

    print('\n\n')
    print('=' * 60)
    print('Summary')
    print('=' * 60)
    post_data = []
    for (name, version) in sorted(test_results):
        result, output, desc = test_results[(name, version)]
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
             'description': desc,
            }
        )
    post_url = os.environ.get('PLUGS_SITE')
    if post_url:
        headers = {'content-type': 'application/json'}
        response = requests.post(post_url, data=json.dumps(post_data),
                                 headers=headers)
        print('posted to {}; response={}'.format(post_url, response))
    else:
        print('not posting, no $PLUGS_SITE defined: {}'.format(post_data))


if __name__ == '__main__':
    main()  

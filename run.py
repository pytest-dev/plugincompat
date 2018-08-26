"""
Reads index.json file containing plugins versions and descriptions, and
test them against current python version and pytest version selected by
$PYTEST_VERSION environment variable.

The plugins are tested using tox. If a plugin provides a tox.ini file,
that is used to test the plugin compatibility, otherwise we provide a simple
tox.ini that practically just tests that the plugin was installed successfully
by running `pytest --help`.

The pytest version to use is obtained by $PYTEST_VERSION, which is forced as
a dependency when invoking tox.

Once all results are obtained, they are posted to the plugincompat heroku app
which can then be visualized.
"""
from __future__ import print_function, with_statement, division

import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import traceback
from collections import namedtuple
from contextlib import contextmanager
from zipfile import ZipFile

import colorama
import requests

import update_index

if sys.version_info[0] == 3:
    from urllib.request import urlretrieve
    from xmlrpc.client import ServerProxy
else:
    from urllib import urlretrieve
    from xmlrpclib import ServerProxy

# oh my, urlretrieve is not thread safe :(
_urlretrieve_lock = threading.Lock()


def download_package(client, name, version):
    for url_data in client.release_urls(name, version):
        basename = os.path.basename(url_data['url'])
        if url_data['packagetype'] == 'sdist':
            with _urlretrieve_lock:
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
        with open(tox_file, 'w') as f:
            f.write(PLACEHOLDER_TOX)

    cmdline = 'tox --result-json=result.json -e %s --force-dep=pytest==%s'
    cmdline %= (tox_env, pytest_version)

    try:
        output = subprocess.check_output(
            cmdline, shell=True, stderr=subprocess.STDOUT, cwd=directory)
        result = 0
    except subprocess.CalledProcessError as e:
        result = e.returncode
        output = e.output

    return result, output.decode()


# tox.ini contents when downloaded package does not have a tox.ini file
# in this case we only display help information
PLACEHOLDER_TOX = '''\
[tox]

[testenv]
deps = pytest
commands = pytest --help
'''


def read_plugins_index(file_name):
    with open(file_name) as f:
        return json.load(f)


class PackageResult(
    namedtuple('PackageResult', 'name version status_code status output description elapsed')):
    pass


def process_package(tox_env, pytest_version, name, version, description):
    def get_elapsed():
        return time.time() - start

    start = time.time()

    # if we already results, skip testing this plugin
    url = os.environ.get('PLUGINCOMPAT_SITE')
    if url:
        params = dict(py=tox_env, pytest=pytest_version)
        response = requests.get('{}/output/{}-{}'.format(url, name, version), params=params)
        if response.status_code == 200:
            return PackageResult(name, version, 0, 'SKIPPED', 'Skipped', description,
                                 get_elapsed())

    client = ServerProxy('https://pypi.python.org/pypi')
    basename = download_package(client, name, version)
    if basename is None:
        status_code, output = 1, 'No sdist found'
        return PackageResult(name, version, status_code, 'NO SOURCE', output, description,
                             get_elapsed())
    directory = extract(basename)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    f = executor.submit(run_tox, directory, tox_env, pytest_version)
    try:
        status_code, output = f.result(timeout=5 * 60)
    except concurrent.futures.TimeoutError:
        f.cancel()
        status_code, output = 1, 'tox run timed out'
    except Exception:
        f.cancel()
        if sys.version_info[0] == 2:
            from StringIO import StringIO
        else:
            from io import StringIO
        stream = StringIO()
        traceback.print_exc(file=stream)
        status_code, output = 'error', 'traceback:\n%s' % stream.getvalue()
    finally:
        executor.shutdown(wait=False)
    output += '\n\nTime: %.1f seconds' % get_elapsed()
    status = 'PASSED' if status_code == 0 else 'FAILED'
    return PackageResult(name, version, status_code, status, output, description, get_elapsed())


@contextmanager
def working_dir(new_cwd):
    if os.path.isdir(new_cwd):
        shutil.rmtree(new_cwd)
    os.makedirs(new_cwd)
    old_cwd = os.getcwd()
    os.chdir(new_cwd)
    yield new_cwd
    os.chdir(old_cwd)


def post_test_results(test_results, tox_env, pytest_version, secret):
    from colorama import Fore
    results = []
    for (name, version) in sorted(test_results):
        result, output, description = test_results[(name, version)]
        if result == 0:
            status = 'ok'
        else:
            status = 'fail'
        results.append(
            {'name': name,
             'version': version,
             'env': tox_env,
             'pytest': pytest_version,
             'status': status,
             'output': output,
             'description': description,
             }
        )
    post_url = os.environ.get('PLUGINCOMPAT_SITE')
    if post_url:
        data = {
            'secret': secret,
            'results': results,
        }
        headers = {'content-type': 'application/json'}
        response = requests.post(post_url, data=json.dumps(data),
                                 headers=headers)
        print(Fore.GREEN + 'Batch of {} posted'.format(len(test_results)))
        response.raise_for_status()
        return True
    else:
        print(Fore.YELLOW + 'NOT posted, $PLUGINCOMPAT_SITE not defined')
        return False


def main(argv):
    from colorama import Fore
    strip = False if 'TRAVIS' in os.environ else None
    colorama.init(autoreset=True, strip=strip)
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None

    pytest_version = os.environ['PYTEST_VERSION']

    # important to remove POST_KEY from environment so others cannot sniff it somehow (#26)
    secret = os.environ.pop('POST_KEY')

    tox_env = 'py%d%d' % sys.version_info[:2]

    plugins = read_plugins_index(update_index.INDEX_FILE_NAME)
    if limit:
        plugins = plugins[:limit]

    test_results = {}

    status_color_map = {
        'SKIPPED': Fore.YELLOW,
        'NO SOURCE': Fore.MAGENTA,
        'PASSED': Fore.GREEN,
        'FAILED': Fore.RED,
    }
    total_plugins = len(plugins)
    processed_plugins = 0
    posted_results = 0

    POST_CHUNKS = 10
    WORKERS = 8

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS)
    with working_dir('.work'), executor:
        fs = []
        for plugin in plugins:
            f = executor.submit(process_package, tox_env,
                                pytest_version, plugin['name'],
                                plugin['version'], plugin['description'])
            fs.append(f)

        print(Fore.CYAN + 'Processing {} packages with {} workers'.format(len(fs), WORKERS))
        for f in concurrent.futures.as_completed(fs):
            processed_plugins += 1
            package_result = f.result()
            package = '%s-%s' % (package_result.name, package_result.version)

            print('{package:<60s} {status_color}{package_result.status:>15s}'
                  '{elapsed_color}{package_result.elapsed:>6.1f}s '
                  '{percent_color}[%{percent:>3d}]'.format(
                package=package,
                status_color=status_color_map[package_result.status],
                package_result=package_result,
                elapsed_color=Fore.CYAN,
                percent_color=Fore.LIGHTCYAN_EX,
                percent=processed_plugins * 100 // total_plugins,
            ))
            if package_result.status != 'SKIPPED':
                test_results[(package_result.name, package_result.version)] = \
                    package_result.status_code, package_result.output, package_result.description

            if len(test_results) >= POST_CHUNKS:
                post_test_results(test_results, tox_env=tox_env,
                                  pytest_version=pytest_version,
                                  secret=secret)
                posted_results += len(test_results)
                test_results.clear()
        if test_results:
            post_test_results(test_results, tox_env=tox_env,
                              pytest_version=pytest_version,
                              secret=secret)
            posted_results += len(test_results)

    print()
    print(Fore.GREEN + 'Posted {} new results'.format(posted_results))
    print(Fore.GREEN + 'All done, congratulations :)')


if __name__ == '__main__':
    sys.exit(main(sys.argv) or 0)

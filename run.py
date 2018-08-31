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
from argparse import ArgumentParser
from collections import defaultdict
from collections import namedtuple
from contextlib import closing
from tempfile import mkdtemp
from zipfile import ZipFile

import colorama
import requests
from colorama import Fore
from wheel.install import WheelFile
from wimpy.util import chunks
from wimpy.util import strip_suffix
from wimpy.util import working_directory

import update_index

if sys.version_info >= (3,):
    from urllib.request import urlretrieve
    from xmlrpc.client import ServerProxy
    from io import StringIO
else:
    from urllib import urlretrieve
    from xmlrpclib import ServerProxy
    from StringIO import StringIO


# oh my, urlretrieve is not thread safe :(
_urlretrieve_lock = threading.Lock()


def download_package(client, name, version):
    urls = client.release_urls(name, version)
    dists = defaultdict(list)
    for data in urls:
        dists[data.get('packagetype')].append(data)
    url = fname = None
    for sdist in dists['sdist']:
        url = sdist['url']
        fname = sdist['filename']
        break
    else:
        for bdist in dists['bdist_wheel']:
            if WheelFile(bdist['filename']).compatible:
                url = bdist['url']
                fname = bdist['filename']
                break
    if fname is not None:
        with _urlretrieve_lock:
            urlretrieve(url, fname)
        return fname


def extract(basename):
    """
    Extracts the contents of the given archive into the current directory.

    :param basename: name of the archive related to the current directory
    :type basename: str

    :rtype: str
    :return: the name of the directory where the contents where extracted
    """

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
    raise Exception('could not extract %s' % basename)


def run_tox(target, tox_env, pytest_version, mode="sdist"):
    """
    Runs tox on the given directory and return (exit code, output)
    """
    if mode == "sdist":
        directory = target
        PLACEHOLDER_TOX = PLACEHOLDER_TOX_SDIST
    elif mode == "bdist_wheel":
        directory = strip_suffix(target, ".whl")
        os.makedirs(directory)
        PLACEHOLDER_TOX = PLACEHOLDER_TOX_BDIST.format(wheel_fname=target)
    else:
        raise NotImplementedError
    tox_file = os.path.join(directory, 'tox.ini')
    if not os.path.isfile(tox_file):
        with open(tox_file, 'w') as f:
            f.write(PLACEHOLDER_TOX)

    cmdline = 'tox --result-json=result.json -e %s --force-dep=pytest==%s'
    cmdline %= (tox_env, pytest_version)
    args = cmdline.split()

    try:
        output = subprocess.check_output(args, stderr=subprocess.STDOUT, cwd=directory)
    except subprocess.CalledProcessError as e:
        result = e.returncode
        output = e.output
    else:
        result = 0

    return result, output.decode()


# tox.ini contents when downloaded package does not have a tox.ini file
# in this case we only display help information
PLACEHOLDER_TOX_SDIST = '''\
[tox]

[testenv]
deps = pytest
commands = pytest --trace-config --help
'''

PLACEHOLDER_TOX_BDIST = '''\
[tox]
skipsdist = True

[testenv]
deps =
    pytest
    pip
commands =
    pip install ../{wheel_fname}
    pytest --trace-config --help
'''


def read_plugins_index(file_name):
    with open(file_name) as f:
        return json.load(f)


PackageResult = namedtuple('PackageResult', 'name version status_code status output description elapsed')


def process_package(tox_env, pytest_version, name, version, description):
    def get_elapsed():
        return time.time() - start

    start = time.time()

    # if we already have results, skip testing this plugin
    url = os.environ.get('PLUGINCOMPAT_SITE')
    if url:
        params = dict(py=tox_env, pytest=pytest_version)
        response = requests.get('{}/output/{}-{}'.format(url, name, version), params=params)
        if response.status_code == 200:
            return PackageResult(name, version, 0, 'SKIPPED', 'Skipped', description,
                                 get_elapsed())

    client = ServerProxy('https://pypi.org/pypi')
    basename = download_package(client, name, version)
    if basename is None:
        status_code, output = 1, 'No source or compatible distribution found'
        return PackageResult(name, version, status_code, 'NO DIST', output, description,
                             get_elapsed())
    if basename.endswith('.whl'):
        target = basename
        mode = "bdist_wheel"
    else:
        target = extract(basename)
        mode = "sdist"
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    f = executor.submit(run_tox, target, tox_env, pytest_version, mode)
    try:
        status_code, output = f.result(timeout=5 * 60)
    except concurrent.futures.TimeoutError:
        f.cancel()
        status_code, output = 1, 'tox run timed out'
    except Exception:
        f.cancel()
        stream = StringIO()
        traceback.print_exc(file=stream)
        status_code, output = 1, 'traceback:\n%s' % stream.getvalue()
    finally:
        executor.shutdown(wait=False)
    output += '\n\nTime: %.1f seconds' % get_elapsed()
    status = 'PASSED' if status_code == 0 else 'FAILED'
    return PackageResult(name, version, status_code, status, output, description, get_elapsed())


def post_test_results(test_results, tox_env, pytest_version, secret):
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
    if secret:
        post_url = os.environ['PLUGINCOMPAT_SITE']
        data = {
            'secret': secret,
            'results': results,
        }
        headers = {'content-type': 'application/json'}
        response = requests.post(post_url, data=json.dumps(data),
                                 headers=headers)
        response.raise_for_status()
        print(Fore.GREEN + 'Batch of {} posted'.format(len(test_results)))
        return len(results)
    else:
        msg = 'Skipping posting batch of {} because secret is not available'
        print(Fore.YELLOW + msg.format(len(test_results)))
        return 0


def printer(result_iterator, n_total):
    status_color_map = {
        'SKIPPED': Fore.YELLOW,
        'NO DIST': Fore.MAGENTA,
        'PASSED': Fore.GREEN,
        'FAILED': Fore.RED,
    }
    for i, package_result in enumerate(result_iterator, 1):
        package = '%s-%s' % (package_result.name, package_result.version)
        print('{package:<60s} {status_color}{package_result.status:>15s}'
              '{elapsed_color}{package_result.elapsed:>6.1f}s '
              '{percent_color}[%{percent:>3d}]'.format(
            package=package,
            status_color=status_color_map[package_result.status],
            package_result=package_result,
            elapsed_color=Fore.CYAN,
            percent_color=Fore.LIGHTCYAN_EX,
            percent=i * 100 // n_total,
        ))
        yield package_result


def main():
    strip = False if 'TRAVIS' in os.environ else None
    colorama.init(autoreset=True, strip=strip)
    parser = ArgumentParser()
    parser.add_argument('--limit', type=int)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--post-chunks', type=int, default=10)

    args = parser.parse_args()
    limit = args.limit
    workers = args.workers
    post_chunks = args.post_chunks

    pytest_version = os.environ['PYTEST_VERSION']

    # important to remove POST_KEY from environment so others cannot sniff it somehow (#26)
    secret = os.environ.pop('POST_KEY', None)
    if secret is None and limit is None:
        # bail out early so CI doesn't take forever for a PR
        limit = args.post_chunks * 3
        print(Fore.CYAN + 'Limit forced to {} since secret is unavail'.format(limit))

    tox_env = 'py%d%d' % sys.version_info[:2]

    plugins = read_plugins_index(update_index.INDEX_FILE_NAME)
    if limit is not None:
        plugins = plugins[:limit]

    n_total = len(plugins)
    n_posted = 0

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    tmp = mkdtemp()
    with working_directory(tmp), executor:
        fs = []
        for plugin in plugins:
            f = executor.submit(process_package, tox_env,
                                pytest_version, plugin['name'],
                                plugin['version'], plugin['description'])
            fs.append(f)

        print(Fore.CYAN + 'Processing {} packages with {} workers'.format(len(fs), workers))

        results = (f.result() for f in concurrent.futures.as_completed(fs))
        results = printer(results, n_total=n_total)  # print them as they complete
        chunked_results = chunks(results, chunk_size=post_chunks)
        for chunk in chunked_results:
            test_results = {}
            for package_result in chunk:
                if package_result.status != 'SKIPPED':
                    test_results[(package_result.name, package_result.version)] = \
                        package_result.status_code, package_result.output, package_result.description
            n_posted += post_test_results(test_results, tox_env=tox_env,
                                          pytest_version=pytest_version,
                                          secret=secret)

    print()
    if n_posted:
        print(Fore.GREEN + 'Posted {} new results'.format(n_posted))
    print(Fore.GREEN + 'All done, congratulations :)')
    shutil.rmtree(tmp)


if __name__ == '__main__':
    main()

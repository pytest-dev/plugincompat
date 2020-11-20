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
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import traceback
from argparse import ArgumentParser
from collections import defaultdict
from collections import namedtuple
from contextlib import closing
from functools import partial
from io import StringIO
from tempfile import mkdtemp
from typing import List
from typing import Optional
from zipfile import ZipFile

import asks
import attr
import colorama
import distlib
import trio
from colorama import Fore
from distlib.wheel import is_compatible
from wimpy.util import strip_suffix
from wimpy.util import working_directory

import update_index
from pypi_rpc_client.proxy import RateLimitedProxy


async def download_package(client, session, name, version):
    urls = client.release_urls(name, version)
    dists = defaultdict(list)
    for data in urls:
        dists[data.get("packagetype")].append(data)
    url = fname = None
    for sdist in dists["sdist"]:
        url = sdist["url"]
        fname = sdist["filename"]
        break
    else:
        for bdist in dists["bdist_wheel"]:
            try:
                if not is_compatible(bdist["filename"]):
                    continue
            except distlib.DistlibException:
                # is_compatible may also raise exceptions with invalid wheel
                # files instead of returning False :/
                continue
            else:
                url = bdist["url"]
                fname = bdist["filename"]
                break
    if fname is not None:
        response = await session.get(url)
        await trio.Path(fname).write_bytes(response.content)
        return fname


def extract(basename):
    """
    Extracts the contents of the given archive into the current directory.

    :param basename: name of the archive related to the current directory
    :type basename: str

    :rtype: str
    :return: the name of the directory where the contents where extracted
    """

    extractors = {".zip": ZipFile, ".tar.gz": tarfile.open, ".tgz": tarfile.open}
    for ext, extractor in extractors.items():
        if basename.endswith(ext):
            with closing(extractor(basename)) as f:
                f.extractall(".")
            return basename[: -len(ext)]
    raise Exception("could not extract %s" % basename)


async def run_tox(target, tox_env, pytest_version, mode="sdist"):
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
    tox_file = os.path.join(directory, "tox.ini")
    if not os.path.isfile(tox_file):
        with open(tox_file, "w") as f:
            f.write(PLACEHOLDER_TOX)

    cmdline = "tox --result-json=result.json -e %s --force-dep=pytest==%s"
    cmdline %= (tox_env, pytest_version)
    args = cmdline.split()

    try:
        output = await trio.to_thread.run_sync(
            partial(
                subprocess.check_output,
                args,
                stderr=subprocess.STDOUT,
                cwd=directory,
                encoding="UTF-8",
            ),
            cancellable=True,
        )
    except subprocess.CalledProcessError as e:
        result = e.returncode
        output = e.output
    else:
        result = 0

    return result, output


# tox.ini contents when downloaded package does not have a tox.ini file
# in this case we only display help information
PLACEHOLDER_TOX_SDIST = """\
[tox]

[testenv]
deps = pytest
commands = pytest --trace-config --help
"""

PLACEHOLDER_TOX_BDIST = """\
[tox]
skipsdist = True

[testenv]
deps =
    pytest
    pip
commands =
    pip install ../{wheel_fname}
    pytest --trace-config --help
"""


def read_plugins_index(file_name):
    with open(file_name) as f:
        return json.load(f)


PackageResult = namedtuple(
    "PackageResult", "name version status_code status output description elapsed"
)


@attr.s
class ProgressCounter:
    """Keeps track of progress during the run process.

    Each task will receive an instance of this class, and should call ``increment_percentage``
    to increment the total percentage and obtain it for printing.
    """

    _total = attr.ib()
    _current = attr.ib(init=False, default=0)

    def increment_percentage(self):
        self._current += 1
        return self._current * 100 // self._total


@attr.s
class ResultsPoster:
    """
    Posts results of running the 'tox' command of a package back to the plugin compat site.

    It will post results in batches of ``post_chunks``.
    """

    session: asks.Session = attr.ib()
    batch_size: int = attr.ib()
    tox_env: str = attr.ib()
    pytest_version: str = attr.ib()
    secret: Optional[str] = attr.ib()
    _package_results: List[PackageResult] = attr.ib(init=False, factory=list)
    _total_posted: int = attr.ib(init=False, default=0)

    @property
    def total_posted(self):
        return self._total_posted

    async def maybe_post_batch(self, package_result):
        if package_result.status == "SKIPPED":
            return
        self._package_results.append(package_result)
        if len(self._package_results) >= self.batch_size:
            await self.post_all()

    async def post_all(self):
        results = [
            {
                "name": package_result.name,
                "version": package_result.version,
                "env": self.tox_env,
                "pytest": self.pytest_version,
                "status": "ok" if package_result.status_code == 0 else "fail",
                "output": package_result.output,
                "description": package_result.description,
            }
            for package_result in sorted(self._package_results)
        ]
        self._package_results.clear()

        if self.secret:
            post_url = os.environ["PLUGINCOMPAT_SITE"]
            data = {"secret": self.secret, "results": results}
            headers = {"content-type": "application/json"}
            response = await self.session.post(post_url, data=json.dumps(data), headers=headers)
            response.raise_for_status()
            self._total_posted += len(results)
            print(Fore.GREEN + "Batch of {} posted".format(len(results)))
        else:
            msg = "Skipping posting batch of {} because secret is not available"
            print(Fore.YELLOW + msg.format(len(results)))


async def run_package(session, tox_env, pytest_version, name, version, description):
    def get_elapsed():
        return time.time() - start

    start = time.time()

    # if we already have results, skip testing this plugin
    url = os.environ.get("PLUGINCOMPAT_SITE")
    if url:
        params = dict(py=tox_env, pytest=pytest_version)
        try:
            response = await session.get(
                "{}/output/{}-{}".format(url, name, version), params=params
            )
            if response.status_code == 200:
                return PackageResult(
                    name, version, 0, "SKIPPED", "Skipped", description, get_elapsed()
                )
        except Exception:
            pass

    client = RateLimitedProxy("https://pypi.org/pypi")
    basename = await download_package(client, session, name, version)
    if basename is None:
        status_code, output = 1, "No source or compatible distribution found"
        return PackageResult(
            name, version, status_code, "NO DIST", output, description, get_elapsed()
        )
    if basename.endswith(".whl"):
        target = basename
        mode = "bdist_wheel"
    else:
        target = extract(basename)
        mode = "sdist"

    with trio.move_on_after(5 * 60) as scope:
        try:
            status_code, output = await run_tox(target, tox_env, pytest_version, mode)
        except Exception:
            stream = StringIO()
            traceback.print_exc(file=stream)
            status_code, output = 1, "traceback:\n%s" % stream.getvalue()

    if scope.cancelled_caught:
        status_code, output = 1, "tox run timed out"

    output += "\n\nTime: %.1f seconds" % get_elapsed()
    status = "PASSED" if status_code == 0 else "FAILED"
    return PackageResult(name, version, status_code, status, output, description, get_elapsed())


def print_package_result(progress_counter: ProgressCounter, package_result):
    status_color_map = {
        "SKIPPED": Fore.YELLOW,
        "NO DIST": Fore.MAGENTA,
        "PASSED": Fore.GREEN,
        "FAILED": Fore.RED,
    }
    package = "{}-{}".format(package_result.name, package_result.version)
    print(
        "{package:<60s} {status_color}{package_result.status:>15s}"
        "{elapsed_color}{package_result.elapsed:>6.1f}s "
        "{percent_color}[%{percent:>3d}]".format(
            package=package,
            status_color=status_color_map[package_result.status],
            package_result=package_result,
            elapsed_color=Fore.CYAN,
            percent_color=Fore.LIGHTCYAN_EX,
            percent=progress_counter.increment_percentage(),
        )
    )


async def process_package(
    semaphore,
    session,
    results_poster: ResultsPoster,
    progress_counter: ProgressCounter,
    tox_env,
    pytest_version,
    name,
    version,
    description,
    *,
    task_status,
):
    async with semaphore:
        task_status.started()
        package_result = await run_package(
            session, tox_env, pytest_version, name, version, description
        )
        print_package_result(progress_counter, package_result)
        await results_poster.maybe_post_batch(package_result)


async def main():
    strip = False if "TRAVIS" in os.environ else None
    colorama.init(autoreset=True, strip=strip)
    parser = ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--post-batches", type=int, default=10)

    args = parser.parse_args()
    limit = args.limit
    post_batches = args.post_batches

    pytest_version = os.environ["PYTEST_VERSION"]

    # important to remove POST_KEY from environment so others cannot sniff it somehow (#26)
    secret = os.environ.pop("POST_KEY", None)
    if secret is None and limit is None:
        # bail out early so CI doesn't take forever for a PR
        limit = args.post_batches * 3
        print(Fore.CYAN + "Limit forced to {} since secret is unavailable".format(limit))

    tox_env = "py%d%d" % sys.version_info[:2]

    plugins = read_plugins_index(update_index.INDEX_FILE_NAME)
    if limit is not None:
        plugins = plugins[:limit]

    n_total = len(plugins)
    print(Fore.CYAN + f"Processing {len(plugins)} packages with {args.workers} workers")

    tmp = mkdtemp()
    async with asks.Session() as session:
        results_poster = ResultsPoster(
            session,
            batch_size=post_batches,
            tox_env=tox_env,
            pytest_version=pytest_version,
            secret=secret,
        )
        progress_counter = ProgressCounter(n_total)
        semaphore = trio.Semaphore(args.workers)
        with working_directory(tmp):
            async with trio.open_nursery() as nursery:
                for plugin in plugins:
                    await nursery.start(
                        process_package,
                        semaphore,
                        session,
                        results_poster,
                        progress_counter,
                        tox_env,
                        pytest_version,
                        plugin["name"],
                        plugin["version"],
                        plugin["description"],
                    )

        await results_poster.post_all()

        print()
        if results_poster.total_posted:
            print(Fore.GREEN + f"Posted {results_poster.total_posted} new results")
        print(Fore.GREEN + "All done, congratulations :)")

    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    trio.run(main)

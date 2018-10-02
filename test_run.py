import json
import os
import sys
import zipfile
from shutil import copy
from textwrap import dedent

import pytest
import responses
from requests.exceptions import HTTPError

from run import download_package
from run import extract
from run import main
from run import PackageResult
from run import post_test_results
from run import process_package
from run import read_plugins_index


canned_data = [
    {"description": "the description 1", "name": "pytest-plugin-a", "version": "0.1.1"},
    {"description": "the description 2", "name": "pytest-plugin-b", "version": "0.2.2"},
    {"description": "the description 3", "name": "pytest-plugin-c", "version": "0.3.3"},
]

canned_results = {
    # (name, version): (result, output, description),
    ("pytest-shmytest", "0.0"): (0, "this one was ok", "a cool plugin"),
    ("pytest-yo-dawg", "6.9"): (1, "this one was a failure", "uncool plugin"),
}

canned_tox_ini = """\
[tox]

[testenv]
commands = python -c "print('hi from tox')"
"""


@pytest.fixture(autouse=True)
def patch_env(monkeypatch):
    monkeypatch.setenv("PYTEST_VERSION", "1.2.3")
    monkeypatch.setenv("PLUGINCOMPAT_SITE", "http://plugincompat.example.com")


@pytest.fixture(autouse=True)
def fake_index_json(monkeypatch):
    monkeypatch.setattr("run.read_plugins_index", lambda file_name: canned_data)


@pytest.fixture(autouse=True)
def freeze_time(monkeypatch):
    monkeypatch.setattr("time.time", lambda: 1535608108.637679)


@pytest.fixture(autouse=True)
def greyorama(monkeypatch):
    class Fore:
        def __getattr__(self, name):
            return ""

    monkeypatch.setattr("run.Fore", Fore())


def fake_process_package(tox_env, pytest_version, name, version, description):
    result = PackageResult(
        name=name,
        version=version,
        status_code=0,
        status="PASSED",
        output="whatever",
        description=description,
        elapsed=0,
    )
    return result


@pytest.fixture
def posted_results(monkeypatch):
    collector = []

    def fake_post_test_results(test_results, tox_env, pytest_version, secret):
        assert pytest_version == "1.2.3"
        assert secret == "my cat's breath smells like cat food"
        collector.append(test_results)
        return len(test_results)

    monkeypatch.setattr("run.post_test_results", fake_post_test_results)
    return collector


def test_main(monkeypatch, capsys, posted_results):
    monkeypatch.setattr("run.process_package", fake_process_package)
    monkeypatch.setattr("sys.argv", ["run.py", "--limit=2", "--workers=1"])
    monkeypatch.setattr("colorama.init", lambda autoreset, strip: None)
    monkeypatch.setenv("POST_KEY", "my cat's breath smells like cat food")
    main()
    out, err = capsys.readouterr()
    assert err == ""
    assert out == dedent(
        """\
        Processing 2 packages with 1 workers
        pytest-plugin-a-0.1.1                                                 PASSED   0.0s [% 50]
        pytest-plugin-b-0.2.2                                                 PASSED   0.0s [%100]
    
        Posted 2 new results
        All done, congratulations :)
        """
    )
    assert posted_results == [
        {
            ("pytest-plugin-a", "0.1.1"): (0, "whatever", "the description 1"),
            ("pytest-plugin-b", "0.2.2"): (0, "whatever", "the description 2"),
        }
    ]


@responses.activate
def test_post_test_results(capsys):
    responses.add(responses.POST, "http://plugincompat.example.com/")
    post_test_results(
        canned_results, tox_env="py10", pytest_version="1.2.3", secret="ILIKETURTLES"
    )
    out, err = capsys.readouterr()
    assert err == ""
    assert "Batch of 2 posted\n" in out
    assert len(responses.calls) == 1
    [call] = responses.calls
    assert call.request.url == "http://plugincompat.example.com/"
    assert json.loads(call.request.body) == {
        "results": [
            {
                "description": "a cool plugin",
                "env": "py10",
                "name": "pytest-shmytest",
                "output": "this one was ok",
                "pytest": "1.2.3",
                "status": "ok",
                "version": "0.0",
            },
            {
                "description": "uncool plugin",
                "env": "py10",
                "name": "pytest-yo-dawg",
                "output": "this one was a failure",
                "pytest": "1.2.3",
                "status": "fail",
                "version": "6.9",
            },
        ],
        "secret": "ILIKETURTLES",
    }


@responses.activate
def test_post_test_results_raises_for_status():
    responses.add(responses.POST, "http://plugincompat.example.com", status=500)
    error_message = "Internal Server Error for url: http://plugincompat.example.com"
    with pytest.raises(HTTPError, match=error_message):
        post_test_results(
            canned_results,
            tox_env="py10",
            pytest_version="1.2.3",
            secret="ILIKETURTLES",
        )


def test_no_post_if_no_secret(capsys):
    responses.add(responses.POST, "http://plugincompat.example.com", status=500)
    post_test_results(
        canned_results, tox_env="py10", pytest_version="1.2.3", secret=None
    )
    out, err = capsys.readouterr()
    assert err == ""
    assert "Skipping posting batch of 2 because secret is not available" in out


@responses.activate
def test_process_package_skips_if_result_already_on_plugincompat_website():
    url = "http://plugincompat.example.com/output/myplugin-1.0?py=py10&pytest=1.2.3"
    responses.add(responses.GET, url)
    result = process_package(
        tox_env="py10",
        pytest_version="1.2.3",
        name="myplugin",
        version="1.0",
        description="'sup",
    )
    assert result == PackageResult(
        name="myplugin",
        version="1.0",
        status_code=0,
        status="SKIPPED",
        output="Skipped",
        description="'sup",
        elapsed=0.0,
    )


@responses.activate
def test_process_package_no_dist_available(monkeypatch):
    url = "http://plugincompat.example.com/output/myplugin-1.0?py=py10&pytest=1.2.3"
    responses.add(responses.GET, url, status=404)
    monkeypatch.setattr("run.download_package", lambda client, name, version: None)
    result = process_package(
        tox_env="py10",
        pytest_version="1.2.3",
        name="myplugin",
        version="1.0",
        description="'sup",
    )
    assert result == PackageResult(
        name="myplugin",
        version="1.0",
        status_code=1,
        status="NO DIST",
        output="No source or compatible distribution found",
        description="'sup",
        elapsed=0.0,
    )


@responses.activate
def test_process_package_tox_errored(tmpdir, monkeypatch):
    url = "http://plugincompat.example.com/output/myplugin-1.0?py=py36&pytest=1.2.3"
    responses.add(responses.GET, url, status=404)
    monkeypatch.setattr(
        "run.download_package", lambda client, name, version: "myplugin.zip"
    )
    monkeypatch.chdir(tmpdir)
    tmpdir.join("myplugin").ensure_dir()
    tmpdir.join("myplugin").join("setup.py").ensure(file=True)
    with zipfile.ZipFile(str(tmpdir/"myplugin.zip"), mode="w") as z:
        z.write("myplugin")
    result = process_package(
        tox_env="py36",
        pytest_version="1.2.3",
        name="myplugin",
        version="1.0",
        description="'sup",
    )
    assert result.name == "myplugin"
    assert result.status_code == 1
    assert result.status == "FAILED"
    assert "ERROR: setup.py is empty" in result.output


@responses.activate
def test_process_package_tox_crash(tmpdir, monkeypatch):
    url = "http://plugincompat.example.com/output/myplugin-1.0?py=py36&pytest=1.2.3"
    responses.add(responses.GET, url, status=404)
    monkeypatch.setattr(
        "run.download_package", lambda client, name, version: "myplugin.zip"
    )
    monkeypatch.chdir(tmpdir)
    empty_zipfile_bytes = b"PK\x05\x06" + b"\x00" * 18
    tmpdir.join("myplugin.zip").write(empty_zipfile_bytes)
    result = process_package(
        tox_env="py36",
        pytest_version="1.2.3",
        name="myplugin",
        version="1.0",
        description="'sup",
    )
    assert result.name == "myplugin"
    assert result.status_code == 1
    assert result.status == "FAILED"
    assert result.output.startswith("traceback:\n")
    fn = os.path.join("myplugin", "tox.ini")
    assert "No such file or directory: {fn!r}".format(fn=fn) in result.output


@responses.activate
def test_process_package_tox_succeeded(tmpdir, monkeypatch):
    py = "py{}{}".format(*sys.version_info[:2])
    url = "http://plugincompat.example.com/output/myplugin-1.0?py={}&pytest=3.7.4".format(
        py
    )
    responses.add(responses.GET, url, status=404)
    monkeypatch.setattr(
        "run.download_package", lambda client, name, version: "myplugin.zip"
    )
    monkeypatch.chdir(tmpdir)
    tmpdir.join("myplugin").ensure_dir()
    tmpdir.join("myplugin").join("setup.py").write(
        "from distutils.core import setup\nsetup(name='myplugin', version='1.0')"
    )
    tmpdir.join("myplugin").join("tox.ini").write(canned_tox_ini)
    with zipfile.ZipFile(str(tmpdir/"myplugin.zip"), mode="w") as z:
        z.write("myplugin")
    result = process_package(
        tox_env=py,
        pytest_version="3.7.4",
        name="myplugin",
        version="1.0",
        description="'sup",
    )
    assert result.name == "myplugin"
    assert result.version == "1.0"
    assert result.status_code == 0
    assert result.status == "PASSED"
    assert result.description == "'sup"
    assert result.elapsed == 0.0
    assert "hi from tox" in result.output
    assert "congratulations :)" in result.output


def test_unsupported_extraction_file_extension():
    with pytest.raises(Exception, match="could not extract myplugin.dat"):
        extract("myplugin.dat")


def test_read_plugins(monkeypatch, tmpdir):
    monkeypatch.chdir(tmpdir)
    tmpdir.join("index.json").write('{"k":"v"}')
    result = read_plugins_index(file_name="index.json")
    assert result == {"k": "v"}


def test_download_package(monkeypatch):
    def fake_urlretrieve(url, basename):
        assert url == "/path/to/whatever.tar.gz"
        assert basename == "whatever.tar.gz"

    monkeypatch.setattr("run.urlretrieve", fake_urlretrieve)

    class FakeClient(object):
        def release_urls(self, name, version):
            return [
                {
                    "filename": "whatever.tar.gz",
                    "url": "/path/to/whatever.tar.gz",
                    "packagetype": "sdist",
                }
            ]

    basename = download_package(client=FakeClient(), name="whatever", version="1.0")
    assert basename == "whatever.tar.gz"


def test_download_package_whl(monkeypatch):
    def fake_urlretrieve(url, basename):
        assert url == "/path/to/myplugin-1.0.0-py2.py3-none-any.whl"
        assert basename == "myplugin-1.0.0-py2.py3-none-any.whl"

    monkeypatch.setattr("run.urlretrieve", fake_urlretrieve)

    class FakeClient(object):
        def release_urls(self, name, version):
            return [
                {
                    "filename": "myplugin-1.0.0-py2.py3-none-any.whl",
                    "url": "/path/to/myplugin-1.0.0-py2.py3-none-any.whl",
                    "packagetype": "bdist_wheel",
                }
            ]

    basename = download_package(client=FakeClient(), name="myplugin", version="1.0")
    assert basename == "myplugin-1.0.0-py2.py3-none-any.whl"


@responses.activate
def test_process_package_tox_succeeded_bdist(tmpdir, monkeypatch):
    py = "py{}{}".format(*sys.version_info[:2])
    url = "http://plugincompat.example.com/output/myplugin-1.0.0?py={}&pytest=3.7.4".format(
        py
    )
    responses.add(responses.GET, url, status=404)
    monkeypatch.setattr(
        "run.download_package", lambda client, name, version: "myplugin-1.0.0-py2.py3-none-any.whl"
    )
    here = os.path.dirname(__file__)
    canned_whl = os.path.join(here, 'test_data', 'myplugin-1.0.0-py2.py3-none-any.whl')
    copy(canned_whl, str(tmpdir))
    monkeypatch.chdir(tmpdir)
    result = process_package(
        tox_env=py,
        pytest_version="3.7.4",
        name="myplugin",
        version="1.0.0",
        description="nope",
    )
    assert result.name == "myplugin"
    assert result.version == "1.0.0"
    assert result.status_code == 0
    assert result.status == "PASSED"
    assert result.description == "nope"
    assert result.elapsed == 0.0
    assert "hi from tox" not in result.output
    assert "hello world from .whl pytest plugin" in result.output
    assert "PLUGIN registered: <module 'myplugin'" in result.output
    assert "congratulations :)" in result.output

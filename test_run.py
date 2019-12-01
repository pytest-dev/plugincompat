import json
import os
import sys
import zipfile
from pathlib import Path
from shutil import copy
from textwrap import dedent

import asynctest
import distlib
import pytest

import run
from run import download_package
from run import extract
from run import main
from run import PackageResult
from run import read_plugins_index


packages_results = {
    "pytest-plugin-a": PackageResult(
        name="pytest-plugin-a",
        version="0.1.1",
        status_code=0,
        status="PASSED",
        output="whatever 1",
        description="the description 1",
        elapsed=0,
    ),
    "pytest-plugin-b": PackageResult(
        name="pytest-plugin-b",
        version="0.2.2",
        status_code=1,
        status="FAILED",
        output="whatever 2",
        description="the description 2",
        elapsed=0,
    ),
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
    canned_data = [
        {"description": "the description 1", "name": "pytest-plugin-a", "version": "0.1.1"},
        {"description": "the description 2", "name": "pytest-plugin-b", "version": "0.2.2"},
        {"description": "the description 3", "name": "pytest-plugin-c", "version": "0.3.3"},
    ]
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


async def fake_run_package(session, tox_env, pytest_version, name, version, description):
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


@pytest.fixture(name="mock_session")
def mock_session_():
    session = asynctest.MagicMock()
    session.post = asynctest.CoroutineMock()
    session.get = asynctest.CoroutineMock()
    return session


async def test_main(monkeypatch, capsys):
    collected = []

    class FakeResultsPoster:
        def __init__(self, *args, **kwargs):
            pass

        async def maybe_post_batch(self, package_result):
            collected.append(package_result)

        async def post_all(self):
            pass

        @property
        def total_posted(self):
            return len(collected)

    monkeypatch.setattr("run.ResultsPoster", FakeResultsPoster)
    monkeypatch.setattr("run.run_package", fake_run_package)
    monkeypatch.setattr("sys.argv", ["run.py", "--limit=2", "--workers=1"])
    monkeypatch.setattr("colorama.init", lambda autoreset, strip: None)
    monkeypatch.setenv("POST_KEY", "my cat's breath smells like cat food")
    await main()
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
    assert collected == [
        PackageResult(
            name="pytest-plugin-a",
            version="0.1.1",
            status_code=0,
            status="PASSED",
            output="whatever",
            description="the description 1",
            elapsed=0,
        ),
        PackageResult(
            name="pytest-plugin-b",
            version="0.2.2",
            status_code=0,
            status="PASSED",
            output="whatever",
            description="the description 2",
            elapsed=0,
        ),
    ]


async def test_post_test_results(capsys, mock_session):

    poster = run.ResultsPoster(
        mock_session, batch_size=2, tox_env="py38", pytest_version="3.5.2", secret="ILIKETURTLES"
    )
    await poster.maybe_post_batch(packages_results["pytest-plugin-a"])
    assert mock_session.post.call_count == 0  # not posted yet

    await poster.maybe_post_batch(packages_results["pytest-plugin-b"])
    assert mock_session.post.call_count == 1
    out, err = capsys.readouterr()
    assert err == ""
    assert "Batch of 2 posted\n" in out
    assert mock_session.post.call_count == 1
    args, kwargs = mock_session.post.call_args
    assert args[0] == "http://plugincompat.example.com"
    assert json.loads(kwargs["data"]) == {
        "results": [
            {
                "description": "the description 1",
                "env": "py38",
                "name": "pytest-plugin-a",
                "output": "whatever 1",
                "pytest": "3.5.2",
                "status": "ok",
                "version": "0.1.1",
            },
            {
                "description": "the description 2",
                "env": "py38",
                "name": "pytest-plugin-b",
                "output": "whatever 2",
                "pytest": "3.5.2",
                "status": "fail",
                "version": "0.2.2",
            },
        ],
        "secret": "ILIKETURTLES",
    }


async def test_no_post_if_no_secret(capsys, mock_session):
    poster = run.ResultsPoster(
        mock_session, batch_size=1, tox_env="py38", pytest_version="3.5.2", secret=None
    )
    await poster.maybe_post_batch(packages_results["pytest-plugin-a"])
    out, err = capsys.readouterr()
    assert err == ""
    assert "Skipping posting batch of 1 because secret is not available" in out


async def test_process_package_skips_if_result_already_on_plugincompat_website(mock_session):
    mock_session.get.return_value.status_code = 200
    result = await run.run_package(
        session=mock_session,
        tox_env="py10",
        pytest_version="1.2.3",
        name="myplugin",
        version="1.0",
        description="'sup",
    )
    assert mock_session.get.call_count == 1
    args, kwargs = mock_session.get.call_args
    assert args[0] == "http://plugincompat.example.com/output/myplugin-1.0"
    assert kwargs["params"] == dict(py="py10", pytest="1.2.3")
    assert result == PackageResult(
        name="myplugin",
        version="1.0",
        status_code=0,
        status="SKIPPED",
        output="Skipped",
        description="'sup",
        elapsed=0.0,
    )


async def test_process_package_no_dist_available(monkeypatch, mock_session):
    mock_session.get.return_value.status_code = 404
    with asynctest.patch("run.download_package", return_value=None, autospec=True):
        result = await run.run_package(
            mock_session,
            tox_env="py10",
            pytest_version="1.2.3",
            name="myplugin",
            version="1.0",
            description="'sup",
        )

    assert mock_session.get.call_count == 1
    args, kwargs = mock_session.get.call_args
    assert args[0] == "http://plugincompat.example.com/output/myplugin-1.0"
    assert kwargs["params"] == dict(py="py10", pytest="1.2.3")
    assert result == PackageResult(
        name="myplugin",
        version="1.0",
        status_code=1,
        status="NO DIST",
        output="No source or compatible distribution found",
        description="'sup",
        elapsed=0.0,
    )


async def test_process_package_tox_errored(tmpdir, monkeypatch, mock_session):
    mock_session.get.return_value.status_code = 404
    monkeypatch.chdir(tmpdir)

    tmpdir.join("myplugin").ensure_dir()
    tmpdir.join("myplugin").join("setup.py").ensure(file=True)
    with zipfile.ZipFile(str(tmpdir / "myplugin.zip"), mode="w") as z:
        z.write("myplugin")

    with asynctest.patch("run.download_package", return_value="myplugin.zip", autospec=True):
        result = await run.run_package(
            mock_session,
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


async def test_process_package_tox_crash(tmpdir, monkeypatch, mock_session):
    mock_session.get.return_value.status_code = 404
    monkeypatch.chdir(tmpdir)

    empty_zipfile_bytes = b"PK\x05\x06" + b"\x00" * 18
    tmpdir.join("myplugin.zip").write(empty_zipfile_bytes)

    with asynctest.patch("run.download_package", return_value="myplugin.zip", autospec=True):
        result = await run.run_package(
            mock_session,
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


async def test_process_package_tox_succeeded(tmpdir, monkeypatch, mock_session):
    py = "py{}{}".format(*sys.version_info[:2])
    mock_session.get.return_value.status_code = 404

    monkeypatch.chdir(tmpdir)
    tmpdir.join("myplugin").ensure_dir()
    tmpdir.join("myplugin").join("setup.py").write(
        "from distutils.core import setup\nsetup(name='myplugin', version='1.0')"
    )
    tmpdir.join("myplugin").join("tox.ini").write(canned_tox_ini)
    with zipfile.ZipFile(str(tmpdir / "myplugin.zip"), mode="w") as z:
        z.write("myplugin")
    with asynctest.patch("run.download_package", return_value="myplugin.zip", autospec=True):
        result = await run.run_package(
            mock_session,
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


async def test_download_package(mock_session):
    mock_session.get.return_value.content = expected_content = b"some contents"

    class FakeClient:
        def release_urls(self, name, version):
            return [
                {
                    "filename": "whatever.tar.gz",
                    "url": "/path/to/whatever.tar.gz",
                    "packagetype": "sdist",
                }
            ]

    basename = await download_package(
        client=FakeClient(), session=mock_session, name="whatever", version="1.0"
    )
    assert mock_session.get.call_args[0][0] == "/path/to/whatever.tar.gz"
    assert basename == "whatever.tar.gz"
    assert Path(basename).read_bytes() == expected_content


async def test_download_package_whl(monkeypatch, mocker, mock_session):
    mock_session.get.return_value.content = b"some contents"

    m = mocker.patch.object(run, "is_compatible", autospec=True, return_value=True)

    class FakeClient:
        def release_urls(self, name, version):
            return [
                {
                    "filename": "myplugin-1.0.0-py2.py3-none-any.whl",
                    "url": "/path/to/myplugin-1.0.0-py2.py3-none-any.whl",
                    "packagetype": "bdist_wheel",
                }
            ]

    basename = await download_package(
        session=mock_session, client=FakeClient(), name="myplugin", version="1.0"
    )
    assert basename == "myplugin-1.0.0-py2.py3-none-any.whl"

    # incompatible wheel
    m.return_value = False
    assert (
        await download_package(
            session=mock_session, client=FakeClient(), name="myplugin", version="1.0"
        )
        is None
    )

    # invalid wheel
    m.side_effect = distlib.DistlibException()
    assert (
        await download_package(
            session=mock_session, client=FakeClient(), name="myplugin", version="1.0"
        )
        is None
    )


async def test_process_package_tox_succeeded_bdist(datadir, monkeypatch, mock_session):
    py = "py{}{}".format(*sys.version_info[:2])
    mock_session.get.return_value.status_code = 404

    monkeypatch.chdir(datadir)

    with asynctest.patch(
        "run.download_package", return_value="myplugin-1.0.0-py2.py3-none-any.whl", autospec=True
    ):
        result = await run.run_package(
            session=mock_session,
            tox_env=py,
            pytest_version="3.7.4",
            name="myplugin",
            version="1.0.0",
            description="nope",
        )
    print(result.output)
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

from textwrap import dedent

import pytest
import responses
from requests.exceptions import HTTPError

from run import main
from run import PackageResult
from run import post_test_results


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


@pytest.fixture(autouse=True)
def patch_env(monkeypatch):
    monkeypatch.setenv("PYTEST_VERSION", "1.2.3")
    monkeypatch.setenv("PLUGINCOMPAT_SITE", "http://plugincompat.example.com/")


@pytest.fixture(autouse=True)
def fake_index_json(monkeypatch):
    monkeypatch.setattr("run.read_plugins_index", lambda file_name: canned_data)


@pytest.fixture
def main_mocks(monkeypatch):
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

    monkeypatch.setattr("run.process_package", fake_process_package)


@pytest.fixture
def posted_results(monkeypatch):
    collector = []

    def fake_post_test_results(test_results, tox_env, pytest_version, secret):
        assert pytest_version == "1.2.3"
        assert secret is None
        collector.append(test_results)

    monkeypatch.setattr("run.post_test_results", fake_post_test_results)
    return collector


def test_main(monkeypatch, capsys, main_mocks, posted_results):
    monkeypatch.setattr("sys.argv", ["run.py", "--limit=2", "--workers=1"])
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


@responses.activate
def test_post_test_results_raises_for_status():
    responses.add(responses.POST, "http://plugincompat.example.com/", status=500)
    error_message = "Internal Server Error for url: http://plugincompat.example.com/"
    with pytest.raises(HTTPError, match=error_message):
        post_test_results(
            canned_results,
            tox_env="py10",
            pytest_version="1.2.3",
            secret="ILIKETURTLES",
        )


def test_no_post_if_no_secret(capsys):
    responses.add(responses.POST, "http://plugincompat.example.com/", status=500)
    post_test_results(
        canned_results, tox_env="py10", pytest_version="1.2.3", secret=None
    )
    out, err = capsys.readouterr()
    assert err == ""
    assert "Skipping posting batch of 2 because secret is not available" in out

import update_index


def test_iter_plugins(mocker):
    client = mocker.MagicMock()
    client.list_packages.return_value = ["pytest-plugin-a", "pytest-plugin-b"]
    client.package_releases.return_value = ["1.0"]
    client.browse.return_value = [("pytest-plugin-c", "2.0")]
    client.release_data = lambda name, version: dict(name=name, version=version, summary="")

    results = update_index.iter_plugins(client, {"pytest-plugin-a"})
    assert list(results) == [("pytest-plugin-b", "1.0", ""), ("pytest-plugin-c", "2.0", "")]

    results = update_index.iter_plugins(client, {"pytest-plugin-a"}, consider_classifier=False)
    assert list(results) == [("pytest-plugin-b", "1.0", "")]

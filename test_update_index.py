import update_index


def test_blacklist(mocker):
    client = mocker.MagicMock()
    client.list_packages.return_value = ['pytest-plugin-a', 'pytest-plugin-b']
    client.package_releases.return_value = ['1.0']
    client.browse.return_value = []
    client.release_data = lambda name, version: dict(name=name, version=version, summary="")

    results = update_index.iter_plugins(client, {'pytest-plugin-a'})
    assert list(results) == [('pytest-plugin-b', '1.0', '')]

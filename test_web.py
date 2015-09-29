import pytest

from flask import json
import mock
from web import PlugsStorage


class MemoryStorage(object):
    """
    Mock class that simulates a PlugsStorage instance. This class simply
    holds the values in memory, and is used by TestView as a mock to the real
    storage class, allowing the view to be tested without a database.
    """

    def __init__(self):
        self._results = []

    def add_test_result(self, result):
        required = {'name', 'version', 'env', 'pytest', 'status'}
        if not required.issubset(result):
            raise TypeError('Invalid keys given: %s' % result.keys())

        for index, existing_result in enumerate(self._results):
            if (existing_result['name'] == result['name'] and
                        existing_result['version'] == result['version'] and
                        existing_result['env'] == result['env'] and
                        existing_result['pytest'] == result['pytest']):
                self._results[index] = result
                break
        else:
            self._results.append(result)

    def get_all_results(self):
        return self._results

    def get_test_results(self, name, version):
        result = []
        for entry in self._results:
            if entry['name'] == name and entry['version'] == version:
                result.append(entry)
        return result

    def drop_all(self):
        self._results[:] = []


@pytest.fixture(params=[PlugsStorage, MemoryStorage])
def storage(request):
    """
    Initializes a Storage for execution in a test environment. This fixture
    will instantiate the storage class given in the parameters. This way we
    ensure both the real implementation and dummy implementation work in the
    same way.

    When initializing the real PlugsStorage(), it will use a test-specific
    data-base to avoid any conflicts between tests and to avoid clashing with
    real databases.
    """
    if request.param is PlugsStorage:
        db_name = 'testing-{}'.format(request.node.name)

        plugs_storage = PlugsStorage(default_db_name=db_name)
        plugs_storage.__TESTING__ = True

        def finalizer():
            plugs_storage.get_connection().drop_database(db_name)

        request.addfinalizer(finalizer)
        return plugs_storage
    elif request.param is MemoryStorage:
        memory_storage = MemoryStorage()
        return memory_storage
    else:
        assert False


def make_result_data(**kwparams):
    result = {
        'name': 'mylib',
        'version': '1.0',
        'env': 'py27',
        'pytest': '2.3',
        'status': 'ok',
        'output': 'all commands:\nok',
        'description': 'a generic library',
    }
    result.update(kwparams)
    return result


#noinspection PyShadowingNames
class TestPlugsStorage(object):
    """
    Tests for PlugsStorage class
    """

    def test_add_test_result(self, storage):
        """
        :type storage: PlugsStorage
        """
        assert list(storage.get_all_results()) == []

        with pytest.raises(TypeError):
            # missing "env" key
            invalid_result = make_result_data()
            del invalid_result['env']
            storage.add_test_result(invalid_result)

        result1 = make_result_data()
        storage.add_test_result(result1)
        assert storage.get_test_results('mylib', '1.0') == [result1]

        result2 = make_result_data(env='py33', status='failed')
        storage.add_test_result(result2)
        assert storage.get_test_results('mylib', '1.0') == [result1, result2]

        result3 = make_result_data(env='py33')
        storage.add_test_result(result3)
        assert storage.get_test_results('mylib', '1.0') == [result1, result3]

        result4 = make_result_data(version='1.1', output='another output')
        storage.add_test_result(result4)
        assert storage.get_test_results('mylib', '1.0') == [result1, result3]
        assert storage.get_test_results('mylib', '1.1') == [result4]

    def test_invalid_lib(self, storage):
        assert storage.get_test_results('foobar', '1.0') == []

    def test_get_all_results(self, storage):
        assert list(storage.get_all_results()) == []

        result1 = make_result_data()
        storage.add_test_result(result1)
        assert list(storage.get_all_results()) == [result1]

        result2 = make_result_data(version='1.1')
        storage.add_test_result(result2)
        assert list(storage.get_all_results()) == [result1, result2]

        result3 = make_result_data(name='myotherlib')
        storage.add_test_result(result3)
        assert list(storage.get_all_results()) == [result1, result2, result3]

    def test_drop_all(self, storage):
        result1 = make_result_data()
        result2 = make_result_data(version='1.1')
        storage.add_test_result(result1)
        storage.add_test_result(result2)
        assert len(storage.get_all_results()) == 2

        storage.drop_all()
        assert len(storage.get_all_results()) == 0


@pytest.fixture
def patched_storage(monkeypatch):
    import web


    result = MemoryStorage()
    monkeypatch.setattr(web, 'get_storage_for_view', lambda: result)
    return result


@pytest.fixture
def client():
    from web import app


    result = app.test_client()
    app.testing = True
    return result


#noinspection PyShadowingNames
class TestView(object):
    """
    Tests web views for plugincompat
    """

    def post_result(self, client, result):
        response = client.post('/', data=json.dumps(result),
                               content_type='application/json')
        assert response.status_code == 200

    def test_index_post(self, client, patched_storage):
        result1 = make_result_data()
        self.post_result(client, result1)
        assert patched_storage.get_all_results() == [result1]

        result2 = make_result_data(env='py33')
        self.post_result(client, result2)
        assert patched_storage.get_all_results() == [result1, result2]

        result3 = make_result_data(name='myotherlib')
        result4 = make_result_data(name='myotherlib', env='py33')
        self.post_result(client, [result3, result4])
        assert patched_storage.get_all_results() == [result1, result2, result3,
                                                     result4]

    def test_index_get_json(self, client, patched_storage):
        self.post_result(client, make_result_data())
        self.post_result(client, make_result_data(env='py33'))
        self.post_result(client, make_result_data(name='myotherlib'))
        self.post_result(client,
                         make_result_data(name='myotherlib', env='py33'))
        assert len(patched_storage.get_all_results()) == 4

        response = client.get('/?json=1')
        results = json.loads(response.data)['data']
        assert set(x['name'] for x in results) == {'mylib', 'myotherlib'}

    def test_get_render_namespace(self):
        from web import get_namespace_for_rendering


        with mock.patch('web.get_python_versions') as mock_python_versions, \
                mock.patch('web.get_pytest_versions') as mock_pytest_versions:
            mock_python_versions.return_value = {'py27', 'py33'}
            mock_pytest_versions.return_value = {'2.4', '2.3'}
            # post results; only the latest lib versions should be rendered
            all_results = [
                make_result_data(),
                make_result_data(env='py26', status='failed'),
                make_result_data(env='py32', status='failed'),
                make_result_data(env='py33', status='failed'),
                make_result_data(name='myotherlib', version='1.8', pytest='2.4'),
                make_result_data(env='py33', pytest='2.4'),
                make_result_data(env='py33', pytest='2.4', version='0.6'),
                make_result_data(env='py33', pytest='2.4', version='0.7'),
                make_result_data(env='py33', pytest='2.4', version='0.8'),
                make_result_data(name='myotherlib', version='2.0', pytest='2.4',
                                 description='my other library',
                                 output='output for myotherlib-2.0'),
            ]

            bad_result = make_result_data(name='badlib')
            del bad_result['output']
            all_results.append(bad_result)

            output_ok = 'all commands:\nok'
            lib_data = {
                ('badlib-1.0', 'py27', '2.3'): (
                    'ok', '<no output available>', 'a generic library'),
                ('mylib-1.0', 'py27', '2.3'): (
                    'ok', output_ok, 'a generic library'),
                ('mylib-1.0', 'py33', '2.3'): (
                    'failed', output_ok, 'a generic library'),
                ('mylib-1.0', 'py33', '2.4'): (
                    'ok', output_ok, 'a generic library'),
                ('myotherlib-2.0', 'py27', '2.4'): (
                    'ok', 'output for myotherlib-2.0', 'my other library'),
            }

            statuses = {k: status for (k, (status, output, desc)) in
                        lib_data.items()}
            outputs = {k: output for (k, (status, output, desc)) in
                       lib_data.items()}
            descriptions = {k[0]: desc for (k, (status, output, desc)) in
                            lib_data.items()}

            assert get_namespace_for_rendering(all_results) == {
                'python_versions': ['py27', 'py33'],
                'lib_names': ['badlib-1.0', 'mylib-1.0', 'myotherlib-2.0'],
                'pytest_versions': ['2.3', '2.4'],
                'latest_pytest_ver': '2.4',
                'statuses': statuses,
                'outputs': outputs,
                'descriptions': descriptions,
            }

    def test_versions(self):
        from web import get_python_versions, get_pytest_versions
        assert get_python_versions() == {'py27', 'py35'}
        assert get_pytest_versions() == {'2.7.3', '2.8.1'}


    def test_get_with_empty_database(self, client, patched_storage):
        assert len(patched_storage.get_all_results()) == 0

        response = client.get('/')
        assert response.data == 'Database is empty'

    @pytest.mark.parametrize('lib_version', ['1.0', '1.2', 'latest'])
    def test_get_output(self, client, lib_version):
        self.post_result(client,
                         make_result_data(version='0.9', output='ver 0.9', pytest='2.3'))
        self.post_result(client,
                         make_result_data(version='1.0', output='ver 1.0', pytest='2.3'))
        self.post_result(client,
                         make_result_data(version='1.2', output='ver 1.2', pytest='2.3'))

        url = '/output/mylib-{0}?py=py27&pytest=2.3'.format(lib_version)
        response = client.get(url)

        if lib_version == 'latest':
            lib_version = '1.2'
        assert response.data == 'ver {}'.format(lib_version)
        assert response.content_type == 'text/plain'

    @pytest.mark.parametrize('lib_version', ['1.0', 'latest'])
    def test_get_output_missing(self, client, patched_storage, lib_version):
        post_data = make_result_data()
        del post_data['output']
        patched_storage.add_test_result(post_data)

        response = client.get('/output/mylib-{}?py=py27&pytest=2.3'
                              .format(lib_version))
        assert response.data == '<no output available>'
        assert response.content_type == 'text/plain'

    @pytest.mark.parametrize('lib_version', ['1.0', 'latest'])
    def test_status_image_help(self, client, lib_version):
        response = client.get('/status/mylib-{}'.format(lib_version))
        assert 'Plugin Status Images' in response.data

    @pytest.mark.parametrize('lib_version', ['1.0', 'latest'])
    def test_status_image(self, client, lib_version):
        self.post_result(client, make_result_data())

        response = client.get('/status/mylib-{}?py=py27&pytest=2.3'
                              .format(lib_version))
        assert response.content_type == 'image/png'

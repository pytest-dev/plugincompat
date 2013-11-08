from flask import json
import pytest
from web import PlugsStorage

class MemoryStorage(object):
    """
    Mock class that simulates a PlugsStorage instance. This class simply holds the values in memory, and is
    used by TestView as a mock to the real storage class, allowing the view to be tested without a database.

    Hmm interfaces would be handy here.
    """
    def __init__(self):
        self._results = []

    def add_test_result(self, result):
        expected = {'name', 'version', 'env', 'pytest', 'status'}
        if not expected.issubset(result):
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
    '''
    Initializes a Storage for execution in a test environment. This fixture will instantiate the storage class
    given in the parameters. This way we ensure both the real implementation and dummy implementation
    work in the same way.

    When initializing the real PlugsStorage(), it will use a test-specific data-base to avoid any conflicts between
    tests and to avoid clashing with real databases.
    '''
    if request.param is PlugsStorage:
        db_name = 'testing-{}'.format(request.node.name)

        result = PlugsStorage(default_db_name=db_name)
        result.__TESTING__ = True

        def finalizer():
            result.get_connection().drop_database(db_name)

        request.addfinalizer(finalizer)
    elif request.param is MemoryStorage:
        result = MemoryStorage()
    else:
        assert False
    return result


def make_result_data(**kwparams):
    result = {
        'name': 'mylib',
        'version': '1.0',
        'env': 'py27',
        'pytest': '2.3',
        'status': 'ok',
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

        result4 = make_result_data(version='1.1')
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
    return result

#noinspection PyShadowingNames
class TestView(object):
    """
    Tests web views for pytest-plugs
    """
    def post_result(self, client, result):
        response = client.post('/', data=json.dumps(result), content_type='application/json')
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
        assert patched_storage.get_all_results() == [result1, result2, result3, result4]

    def test_index_get_json(self, client, patched_storage):
        self.post_result(client, make_result_data())
        self.post_result(client, make_result_data(env='py33'))
        self.post_result(client, make_result_data(name='myotherlib'))
        self.post_result(client, make_result_data(name='myotherlib', env='py33'))
        assert len(patched_storage.get_all_results()) == 4

        response = client.get('/?json=1')
        results = json.loads(response.data)['data']
        assert set(x['name'] for x in results) == {'mylib', 'myotherlib'}

    def test_get_render_namespace(self):
        from web import get_namespace_for_rendering
        result1 = make_result_data()
        result2 = make_result_data(env='py33', status='failed')
        result3 = make_result_data(env='py33', pytest='2.4')
        result4 = make_result_data(name='myotherlib', version='2.0', pytest='2.4')
        all_results = [result1, result2, result3, result4]

        statuses = {
            ('mylib-1.0', 'py27', '2.3'): 'ok',
            ('mylib-1.0', 'py33', '2.3'): 'failed',
            ('mylib-1.0', 'py33', '2.4'): 'ok',
            ('myotherlib-2.0', 'py27', '2.4'): 'ok',
        }
        assert get_namespace_for_rendering(all_results) == {
            'python_versions': ['py27', 'py33'],
            'lib_names': ['mylib-1.0', 'myotherlib-2.0'],
            'pytest_versions': ['2.3', '2.4'],
            'latest_pytest_ver': '2.4',
            'statuses' : statuses,
        }

import pytest
from web import PlugsStorage


@pytest.fixture
def storage(request):
    '''
    Initializes a MongoStorage() using a test-specific data-base, to avoid any conflicts between
    tests and to avoid clashing with real databases.
    '''
    db_name = 'testing-{}'.format(request.node.name)

    result = PlugsStorage(default_db_name=db_name)
    result.__TESTING__ = True

    def finalizer():
        result.get_connection().drop_database(db_name)

    request.addfinalizer(finalizer)
    return result


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
            invalid_result = {
                'name': 'mylib',
                'version': '1.0',
                'pytest': '2.3',
                'status': 'ok',
            }
            storage.add_test_result(invalid_result)

        result1 = {
            'name': 'mylib',
            'version': '1.0',
            'env': 'py27',
            'pytest': '2.3',
            'status': 'ok',
        }
        storage.add_test_result(result1)

        result2 = {
            'name': 'mylib',
            'version': '1.0',
            'env': 'py33',
            'pytest': '2.3',
            'status': 'fail',
        }
        storage.add_test_result(result2)
        assert storage.get_test_results('mylib', '1.0') == [result1, result2]

        result3 = {
            'name': 'mylib',
            'version': '1.0',
            'env': 'py33',
            'pytest': '2.3',
            'status': 'ok',
        }
        storage.add_test_result(result3)
        assert storage.get_test_results('mylib', '1.0') == [result1, result3]

        result4 = {
            'name': 'mylib',
            'version': '1.1',
            'env': 'py27',
            'pytest': '2.3',
            'status': 'ok',
        }
        storage.add_test_result(result4)
        assert storage.get_test_results('mylib', '1.0') == [result1, result3]
        assert storage.get_test_results('mylib', '1.1') == [result4]

    def test_invalid_lib(self, storage):
        assert storage.get_test_results('foobar', '1.0') == []


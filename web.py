import os
from urlparse import urlsplit
from flask import request
import flask
import pymongo


class PlugsStorage(object):
    """
    API around a MongoDatabase used to add and obtain test results for pytest plugins.
    """

    def __init__(self, default_db_name='test-results'):
        mongodb_uri = os.environ.get('MONGOLAB_URI', 'mongodb://localhost:27017/{}'.format(default_db_name))
        db_name = urlsplit(mongodb_uri).path[1:]
        self._connection = pymongo.Connection(mongodb_uri)
        self._db = self._connection[db_name]

        self._db.results.create_index([('name', pymongo.ASCENDING), ('version', pymongo.ASCENDING)])

        self.__TESTING__ = False

    def get_connection(self):
        assert self.__TESTING__
        return self._connection

    def add_test_result(self, result):
        """
        :param result: adds results from a compatibility test for a pytest plugin.

            The results is given as a dict containing the following keys:
            * "name": name of the library;
            * "version": version of the library;
            * "env": python environment of the test. Examples: "py27", "py32", "py33".
            * "pytest": pytest version of the test. Examples: "2.3.5"
            * "status": "ok" or "fail".
        """
        expected = {'name', 'version', 'env', 'pytest', 'status'}
        if not expected.issubset(result):
            raise TypeError('Invalid keys given: %s' % result.keys())

        query = {
            'name': result['name'],
            'version': result['version'],
            'env': result['env'],
            'pytest': result['pytest'],
        }
        entry = self._db.results.find_one(query)
        if entry is None:
            entry = query
        entry['status'] = result['status']
        self._db.results.save(entry)

    def get_all_results(self):
        return self._filter_entry_ids(self._db.results.find())

    def get_test_results(self, name, version):
        return self._filter_entry_ids(self._db.results.find({'name': name, 'version': version}))

    def _filter_entry_ids(self, entries):
        result = []
        for entry in entries:
            del entry['_id']
            result.append(entry)
        return result

app = flask.Flask('pytest-plugs')


def get_storage_for_view():
    """
    Returns a storage instance to be used by the view functions. This exists solely we can mock this function
    during testing.
    """
    return PlugsStorage()


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        results = request.get_json()
        if not isinstance(results, list):
            results = [results]
        storage = get_storage_for_view()
        for result in results:
            storage.add_test_result(result)
        return 'OK'

if __name__ == '__main__':
    app.debug = True
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '5000')))
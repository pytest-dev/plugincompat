from distutils.version import LooseVersion
import os
from urlparse import urlsplit
from flask import request, render_template
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
    storage = get_storage_for_view()
    if request.method == 'POST':
        results = request.get_json()
        if not isinstance(results, list):
            results = [results]
        for result in results:
            storage.add_test_result(result)
        return 'OK'
    else:
        all_results = storage.get_all_results()
        if request.args.get('json', False):
            response = flask.jsonify(data=all_results)
            return response
        else:
            namespace = get_namespace_for_rendering(all_results)
            return render_template('index.html', **namespace)


def get_namespace_for_rendering(all_results):
    # python_versions, lib_names, pytest_versions, statuses, latest_pytest_ver
    python_versions = set()
    lib_names = set()
    pytest_versions = set()
    statuses = {}
    for result in all_results:
        lib_name = '{}-{}'.format(result['name'], result['version'])
        python_versions.add(result['env'])
        lib_names.add(lib_name)
        pytest_versions.add(result['pytest'])
        statuses[(lib_name, result['env'], result['pytest'])] = result['status']

    latest_pytest_ver = str(sorted(LooseVersion(x) for x in pytest_versions)[-1])
    return dict(
        python_versions=sorted(python_versions),
        lib_names=sorted(lib_names),
        pytest_versions=sorted(pytest_versions),
        statuses=statuses,
        latest_pytest_ver=latest_pytest_ver,
    )

if __name__ == '__main__':
    app.debug = True
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '5000')))
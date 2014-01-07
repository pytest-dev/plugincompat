from distutils.version import LooseVersion
import os
from urlparse import urlsplit
import itertools

from flask import request, render_template
import flask
import pymongo


class PlugsStorage(object):
    """
    API around a MongoDatabase used to add and obtain test results for pytest plugins.
    """

    def __init__(self, default_db_name='test-results'):
        mongodb_uri = os.environ.get('MONGOLAB_URI',
                                     'mongodb://localhost:27017/{}'.format(
                                         default_db_name))
        db_name = urlsplit(mongodb_uri).path[1:]
        self._connection = pymongo.Connection(mongodb_uri)
        self._db = self._connection[db_name]

        self._db.results.create_index(
            [('name', pymongo.ASCENDING), ('version', pymongo.ASCENDING)])

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
            * "output": string with output from running tox commands.
        """
        expected = {'name', 'version', 'env', 'pytest', 'status', 'output'}
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
        entry['output'] = result['output']
        self._db.results.save(entry)

    def drop_all(self):
        self._db.drop_collection('results')

    def get_all_results(self):
        return self._filter_entry_ids(self._db.results.find())

    def get_test_results(self, name, version):
        return self._filter_entry_ids(
            self._db.results.find({'name': name, 'version': version}))

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
            if all_results:
                namespace = get_namespace_for_rendering(all_results)
                return render_template('index.html', **namespace)
            else:
                return 'Database is empty'


def get_namespace_for_rendering(all_results):
    # python_versions, lib_names, pytest_versions, statuses, latest_pytest_ver
    python_versions = set()
    lib_names = set()
    pytest_versions = set()
    statuses = {}

    latest_versions = set(get_latest_versions((x['name'], x['version']) for x in all_results))

    for result in all_results:
        if (result['name'], result['version']) not in latest_versions:
            continue
        lib_name = '{}-{}'.format(result['name'], result['version'])
        python_versions.add(result['env'])
        lib_names.add(lib_name)
        pytest_versions.add(result['pytest'])
        statuses[(lib_name, result['env'], result['pytest'])] = result['status']

    latest_pytest_ver = str(
        sorted(LooseVersion(x) for x in pytest_versions)[-1])
    return dict(
        python_versions=sorted(python_versions),
        lib_names=sorted(lib_names),
        pytest_versions=sorted(pytest_versions),
        statuses=statuses,
        latest_pytest_ver=latest_pytest_ver,
    )


def get_latest_versions(names_and_versions):
    """
    Returns an iterator of (name, version) from the given list of (name,
    version), but returning only the latest version of the package. Uses
    distutils.LooseVersion to ensure compatibility with PEP386.
    """
    names_and_versions = sorted((name, LooseVersion(version)) for
                                (name, version) in names_and_versions)
    for name, grouped_versions in itertools.groupby(names_and_versions,
                                                    key=lambda x: x[0]):
        name, loose_version = list(grouped_versions)[-1]
        yield name, str(loose_version)


@app.route('/status')
@app.route('/status/<name>')
def status_image(name=None):
    py = request.args.get('py')
    pytest = request.args.get('pytest')
    if name and py and pytest:
        storage = get_storage_for_view()
        status = get_status_for(storage, name, py, pytest)
        if not status:
            status = 'unknown'
        dirname = os.path.dirname(__file__)
        filename = os.path.join(dirname, 'static', '%s.png' % status)
        response = flask.make_response(open(filename, 'rb').read())
        response.content_type = 'image/png'
        return response
    else:
        if name is None:
            name = 'pytest-pep8-1.0.5'
        return render_template('status_help.html', name=name)


def get_status_for(storage, fullname, env, pytest):
    name, version = fullname.rsplit('-', 1)
    for test_result in storage.get_test_results(name, version):
        if test_result['env'] == env and test_result['pytest'] == pytest:
            return test_result['status']
    return None


if __name__ == '__main__':
    app.debug = True
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '5000')))
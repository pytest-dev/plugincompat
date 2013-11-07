import os
from urlparse import urlsplit

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
        return self._db.results.find()

    def get_test_results(self, name, version):
        result = []
        for entry in self._db.results.find({'name': name, 'version': version}):
            del entry['_id']
            result.append(entry)
        return result
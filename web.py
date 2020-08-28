import itertools
import logging
import os
import sys
from contextlib import closing

import flask
from flask import render_template
from flask import request
from packaging.version import parse
from sqlalchemy import Column
from sqlalchemy import create_engine
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()


class PluginResult(Base):
    """Results of testing a pytest plugin against a pytest and python version."""

    __tablename__ = "results"

    id = Column(Integer, primary_key=True)
    name = Column(String, index=True)
    version = Column(String, index=True)
    env = Column(String)
    pytest = Column(String)
    status = Column(String)
    output = Column(String)
    description = Column(String, default="")

    def as_dict(self):
        return {
            "name": self.name,
            "version": self.version,
            "env": self.env,
            "pytest": self.pytest,
            "status": self.status,
            "output": self.output,
            "description": self.description,
        }

    def __repr__(self):
        attrs = [f"{k}={v!r}" for k, v in self.as_dict().items()]
        return f"PluginResult({', '.join(attrs)})"

    def __eq__(self, other):
        if not isinstance(other, PluginResult):
            return NotImplemented
        return self.as_dict() == other.as_dict()


app = flask.Flask("plugincompat")


def get_python_versions():
    """
    Python versions we are willing to display on the page, in order to ignore
    old and incomplete results.
    """
    return {"py36", "py37", "py38"}


def get_pytest_versions():
    """
    Same as `get_python_versions`, but for pytest versions.
    """
    return {"6.0.1"}


class PlugsStorage:
    """
    API around a MongoDatabase used to add and obtain test results for pytest plugins.
    """

    def __init__(self, url=None):
        url = url or os.environ["DATABASE_URL"]
        self._engine = create_engine(url)
        Base.metadata.create_all(self._engine)
        self._session_maker = sessionmaker(autocommit=False, autoflush=False, bind=self._engine)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._engine.dispose()

    def add_test_result(self, payload):
        """
        :param result: adds results from a compatibility test for a pytest plugin.

            The results is given as a dict containing the following keys:
            * "name": name of the library;
            * "version": version of the library;
            * "env": python environment of the test. Examples: "py27", "py32", "py33".
            * "pytest": pytest version of the test. Examples: "2.3.5"
            * "status": "ok" or "fail".
            * "output": string with output from running tox commands.
            * "description": description of this package (optional).
        """
        expected = {"name", "version", "env", "pytest", "status"}
        if not expected.issubset(payload):
            raise TypeError("Invalid keys given: %s" % payload.keys())

        with closing(self._session_maker()) as session:
            result = (
                session.query(PluginResult)
                .filter(PluginResult.name == payload["name"])
                .filter(PluginResult.version == payload["version"])
                .filter(PluginResult.env == payload["env"])
                .filter(PluginResult.pytest == payload["pytest"])
                .first()
            )
            if result is None:
                result = PluginResult(**payload)
            result.status = payload["status"]
            result.output = payload.get("output", "")
            result.description = payload.get("description", "")
            session.add(result)
            session.commit()

    def drop_all(self):
        Base.metadata.drop_all(self._engine)
        Base.metadata.create_all(self._engine)

    def get_all_results(self):
        session = self._session_maker()
        return [x.as_dict() for x in session.query(PluginResult).all()]

    def get_test_results(self, name, version):
        """
        searches the database for all test results given library name and
        version. If version is LATEST_VERSION, only results for highest
        version number are returned.
        """
        with closing(self._session_maker()) as session:
            q = session.query(PluginResult).filter(PluginResult.name == name)
            if version != LATEST_VERSION:
                q = q.filter(PluginResult.version == version)
            results = [p.as_dict() for p in q.all()]

        if version != LATEST_VERSION:
            return results
        else:
            return filter_latest_results(results)

    def _filter_entry_ids(self, entries):
        """
        removes special "_id" from entries returned from MongoDB
        """
        result = []
        for entry in entries:
            del entry["_id"]
            result.append(entry)
        return result


def get_storage_for_view():
    """
    Returns a storage instance to be used by the view functions. This exists
    solely we can mock this function during testing.
    """
    return PlugsStorage()


def authenticate(json_data):
    """Ensure the posted data contains the correct secret"""
    if json_data.get("secret") != os.environ["POST_KEY"]:
        flask.abort(401)


@app.route("/", methods=["GET", "POST"])
def index():
    storage = get_storage_for_view()
    if request.method == "POST":
        data = request.get_json()
        authenticate(data)
        results = data["results"]
        if not isinstance(results, list):
            results = [results]
        for result in results:
            storage.add_test_result(result)
        return "OK, posted {} entries".format(len(results))
    else:
        all_results = storage.get_all_results()
        if request.args.get("json", False):
            response = flask.jsonify(data=all_results)
            return response
        else:
            if all_results:
                namespace = get_namespace_for_rendering(all_results)
                return render_template("index.html", **namespace)
            else:
                return "Database is empty"


def filter_latest_results(all_results):
    """
    given a list of test results read from the db, filter out only the ones
    for highest library version available in the database.
    """
    latest_versions = set(get_latest_versions((x["name"], x["version"]) for x in all_results))

    for result in all_results:
        if (result["name"], result["version"]) in latest_versions:
            yield result


def get_namespace_for_rendering(all_results):
    # python_versions, lib_names, pytest_versions, statuses, latest_pytest_ver
    python_versions = get_python_versions()
    lib_names = set()
    pytest_versions = get_pytest_versions()
    statuses = {}
    outputs = {}
    descriptions = {}

    latest_results = filter_latest_results(all_results)
    for result in latest_results:
        ignore = result["env"] not in python_versions or result["pytest"] not in pytest_versions
        if ignore:
            continue
        lib_name = "{}-{}".format(result["name"], result["version"])
        lib_names.add(lib_name)
        key = (lib_name, result["env"], result["pytest"])
        statuses[key] = result["status"]
        outputs[key] = result.get("output", NO_OUTPUT_AVAILABLE)
        if not descriptions.get(lib_name):
            descriptions[lib_name] = result.get("description", "")

    latest_pytest_ver = max(pytest_versions, key=parse)
    return dict(
        python_versions=sorted(python_versions),
        lib_names=sorted(lib_names),
        pytest_versions=sorted(pytest_versions),
        statuses=statuses,
        outputs=outputs,
        descriptions=descriptions,
        latest_pytest_ver=latest_pytest_ver,
    )


def get_latest_versions(names_and_versions):
    """
    Returns an iterator of (name, version) from the given list of (name,
    version), but returning only the latest version of the package.
    """
    names_and_versions = sorted((name, parse(version)) for (name, version) in names_and_versions)
    for name, grouped_versions in itertools.groupby(names_and_versions, key=lambda x: x[0]):
        name, loose_version = list(grouped_versions)[-1]
        yield name, str(loose_version)


@app.route("/status")
@app.route("/status/<name>")
def get_status_image(name=None):
    py = request.args.get("py")
    pytest = request.args.get("pytest")
    if name and py and pytest:
        status = get_field_for(name, py, pytest, "status")
        if not status:
            status = "unknown"
        dirname = os.path.dirname(__file__)
        filename = os.path.join(dirname, "static", "%s.png" % status)
        response = flask.make_response(open(filename, "rb").read())
        response.content_type = "image/png"
        return response
    else:
        if name is None:
            name = "pytest-pep8-1.0.5"
        name = name.rsplit("-", 1)[0]
        return render_template("status_help.html", name=name)


@app.route("/output/<name>")
def get_output(name):
    py = request.args.get("py")
    pytest = request.args.get("pytest")
    if name and py and pytest:
        output = get_field_for(name, py, pytest, "output")
        status_code = 200
        if not output:
            output = NO_OUTPUT_AVAILABLE
            status_code = 404
        response = flask.make_response(output)
        response.content_type = "text/plain"
        response.content_type = "text/plain"
        response.status_code = status_code
        return response
    else:
        return 'Specify "py" and "pytest" parameters'


def get_field_for(fullname, env, pytest, field_name):
    storage = get_storage_for_view()
    name, version = fullname.rsplit("-", 1)
    for test_result in storage.get_test_results(name, version):
        if test_result["env"] == env and test_result["pytest"] == pytest:
            return test_result.get(field_name, None)


# text returned when an entry in the database lacks an "output" field
NO_OUTPUT_AVAILABLE = "<no output available>"
LATEST_VERSION = "latest"


def main():
    app.debug = True
    app.logger.addHandler(logging.StreamHandler(sys.stdout))
    app.logger.setLevel(logging.ERROR)
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")))


if __name__ == "__main__":
    main()

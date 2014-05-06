# pytest-plugs #

Compatibility checks for pytest plugins. 

![plug](static/electrical-plug-th.png)

This project tests pytest plugins compatibility across python and pytest
versions, displaing them in a web page for quick consulting.

See test results at http://pytest-plugs.herokuapp.com.

## Updating ##

Right now the process is manual, but should be executed automatically in the
future.

To update, execute `update_index.py` with no parameters:

```
] python update_index.py
index.txt updated (push to GitHub).
```

If `index.txt` is updated as the message above states, that file should be committed
and pushed back to GitHub in order to trigger a new [travis](travis.org) build.
The web page should be updated when the full matrix gets a chance
to run, usually after 10 minutes or so.

If `index.txt` does not change, no further action is needed:

```
] py update_index.py
index.txt skipped, no changes.
```

## How It Works ##

For each each plugin, as identified by a search for `pytest-*` on PyPI, we
download, install and execute its tests using [tox](http://tox.readthedocs.org/en/latest/).
If a plugin doesn't have a `tox.ini` file, we generate a simple
`tox.ini` which just ensures that the plugin was installed successfully.

Once we have tested all plugins, the results are posted to a web application
that can be used to visualize them.

The steps above are executed for some Python and pytest versions,
resulting in a matrix of plugin x python x pytest compatibility.

We use [travis](travis.org) to execute the tests and post the results. The web
page is hosted by [heroku](heroku.com) at http://pytest-plugs.herokuapp.com.

## Details ##

Below there's a more detailed description of the system for those interested.

### update_index.py ###

This script creates/updates the file `index.txt` file using new information
from PyPI and contains the list of plugins to test. It is a `JSON`
formatted file containing a list of `(plugin name, version, description)`,
like this:

```
[
  [
    "pytest-bdd",
    "2.1.0",
    "BDD for pytest"
  ],
  [
    "pytest-bench",
    "0.2.5",
    "Benchmark utility that plugs into pytest."
  ],
  [
    "pytest-blockage",
    "0.1",
    "Disable network requests during a test run."
  ],
...
```

To run the script, just execute it without parameters:

```
] python update_index.py
index.txt updated (push to GitHub).
```

If the script was updated it means either new plugins were posted or some
of the existing plugins were updated, so the file `index.txt` should be
committed and pushed to GitHub as the message says.

If nothing has changed, no further action is needed:

```
] py update_index.py
index.txt skipped, no changes.
```

### run.py ###

This script reads `index.txt` file, executes tests for each package in
the current python interpreter and posts results back to
[heroku](heroku.com).

Then it downloads the source package for each plugin and extracts it into the
current directory. It is assumed that plugins use [tox](http://tox.readthedocs.org/en/latest/)
for testing; if a plugin doesn't have a `tox.ini` file, the script will generate
a simple `tox.ini` that just tries to ensure the plugins installs cleanly.

After all plugins are tested, results are posted to the web page.

The script is configured by two environment variables:

`PYTEST_VERSION`: pytest version that will be passed to `tox` as `--force-dep`
 parameter, ensuring that it is tested against that pytest version and not
 what is installed in the system.

`PLUGS_SITE`: URL to post the results data to. Example of a payload:

```json
[
  {
    "name": "pytest-blockage",
    "version": "0.1",
    "env": "py33",
    "pytest": "2.5.2",
    "status": "ok",
    "output": "GLOB sdist-make: /home/travis/...",
    "description": "Disable network requests during a test run.",
  },
]
```

The above environment variables are configured in the
[.travis.yaml](/.travis.yaml) file and are part of the build matrix.

### web.py ###

This is the webserver that is hosted at [heroku](http://pytest-plugs.herokuapp.com).

It serves an index page containing a table displaying test results for pytest
plugins against different python and pytest versions.

It supports the following URLs:

```
GET /
```
Returns main page, showing the test results table.

```
POST /
```
Posts a new payload that update test results. See above for an
example of a valid payload. Returns

```
GET /status
```
Returns a page explaining on how to obtain status images (badges) for each plugin.

```
GET /status/:name/`
```
Returns an image for a specific plugin indicating its
status when tested against a python and pytest versions. For example:
 `/status/pytest-pep8-1.0.5?py=py33&pytest=2.4.2`

[web.py](/web.py) has test cases to ensure pages are behaving as expected, see
[test_web.py](/test_web.py).

```
GET /output/:name/
```

Receives the same parameter as `/status/:name/`, but returns the output
of the tox run as plain text.

# pytest-plugs #

Compatibility checks for pytest plugins. 

![plug](static/electrical-plug-th.png)

This project tests pytest plugins compatibility across python and pytest
versions, displaing them in a web page for quick consulting.

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
The build matrix page should be updated when the full matrix gets a chance
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
`tox.ini` which just tests that the plugin was installed successfully.

Once we have a tested all plugins, we post the results to a web application
that keeps track and displays them.

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

To execute the script, just execute it without parameters:

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

This script reads `index.txt` file and executes tests for each package in
the current python interpreter and posting the results back to
[heroku](heroku.com).

We download the source package for each plugin and extract it into the
current directory. We assume that plugins use [tox](http://tox.readthedocs.org/en/latest/)
for testing; if a plugin doesn't have a `tox.ini` file, the script will generate
a simple `tox.ini` that just tries to ensure the plugins installs cleanly.

After all plugins are tested, we post the results to the web page.

The script is configured by using two environment variables:

`PYTEST_VERSION`: pytest version that will be passed to `tox` as a `--force-dep`
 parameter, ensuring that we test against the pytest version we want and not
 what is installed in the system.

`PLUGS_SITE`: URL to post the results data to. Example of a payload:

```
[
{"name": "pytest-blockage",
 "version": "0.1",
 "env": "py33",
 "pytest": "2.5.2",
 "status": "ok",
 "output": "GLOB sdist-make: /home/travis/...",
 "description": "Disable network requests during a test run.",
},
...
]
```

The above environment variables are configured in the
[.travis.yaml](/travis.yaml) file and are part of the build matrix.




# pytest-plugs #

Compatibility checks for pytest plugins. 

![plug](static/electrical-plug-th.png)

The purpose of this project is to provide a web page to
check known compatibility between pytest plugins and 
different python and pytest versions.

## How It Works ##

For each each plugin, as identified by a search for `pytest-*` on PyPI, we
download, install and execute its tests using `tox`. If a plugin doesn't
have a `tox.ini` file, we generate a simple `tox.ini` which just tests that the
plugin was installed successfully.

Once we have a set of test results, we post them to a web application
that keeps track and displays the results.

The steps above are executed for some Python and pytest versions,
resulting in a matrix of plugin x python x pytest compatibility.

We use [travis](travis.org) to execute the test and post the results. The web
page is hosted by [heroky](heroku.com) at http://pytest-plugs.herokuapp.com.

### update.py ###

This script creates/updates the file



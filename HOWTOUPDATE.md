
Follow this steps to update Python and pytest versions on the site:

1. Update pytest and/or python versions in `.travis.yml`:

   ```yaml
   python:
     - "2.7"
     - "3.6"
   env:
     matrix:
     - PYTEST_VERSION=3.3.0 PLUGINCOMPAT_SITE=http://plugincompat.herokuapp.com
   ```

2. Update `get_pytest_versions()` and `get_python_versions()` in `web.py` to match the versions in `.travis.yml`.

3. Update `test_versions` in `test_web.py`.

4. Finally push `master` to GitHub and Heroku.

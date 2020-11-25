# script ran periodically by Heroku to update the plugin index file
echo "Cloning..."
git config --global user.name "pytestbot"
git config --global user.email pytestbot@gmail.com
git clone https://github.com/pytest-dev/plugincompat.git

echo "Updating..."
cd plugincompat || exit
pip install -r update-index-requirements.txt
python update_index.py

echo "Push..."
git commit -a -m "Updating index (from heroku)"
# GITHUB_TOKEN is personal access token from the pytestbot account, created in:
#   https://github.com/settings/tokens
# and made available to this script as a config var setting in Heroku:
#   https://dashboard.heroku.com/apps/plugincompat/settings
git push "https://$GITHUB_TOKEN:x-oauth-basic@github.com/pytest-dev/plugincompat.git" master

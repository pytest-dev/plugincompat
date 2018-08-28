# script ran periodically by Heroku to update the plugin index file
echo "Cloning..."
git config --global user.name "Bruno Oliveira"
git config --global user.email nicoddemus@gmail.com
git clone https://github.com/pytest-dev/plugincompat.git

echo "Updating..."
cd plugincompat
python update_index.py

echo "Push..."
git commit -a -m "Updating index (from heroku)"
git push https://$GITHUB_TOKEN:x-oauth-basic@github.com/pytest-dev/plugincompat.git master

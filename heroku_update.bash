echo "Clonning..."
git config --global user.name "Bruno Oliveira"
git config --global user.email nicoddemus@gmail.com
git clone https://github.com/nicoddemus/pytest-plugs.git

echo "Updating..."
cd pytest-plugs
python update_index.py

echo "Push..."
git commit -a -m "Updating index (from heroku)"
git push https://$GITHUB_TOKEN:x-oauth-basic@github.com/nicoddemus/pytest-plugs.git 

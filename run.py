from __future__ import with_statement
import glob
import os
import sys
import tarfile
import urllib
import xmlrpclib
from zipfile import ZipFile

import simplejson


#===================================================================================================
# iter_plugins
#===================================================================================================
def iter_plugins(client, search='pytest-'):
    '''
    Returns an iterator of (name, version) from PyPI.
    
    :param client: xmlrpclib.ServerProxy
    :param search: package names to search for 
    '''
    for plug_data in client.search({'name' : search}):
        yield plug_data['name'], plug_data['version']


#===================================================================================================
# download_plugins
#===================================================================================================
def download_plugins():
    client = xmlrpclib.ServerProxy('https://pypi.python.org/pypi')
    #plugins = iter_plugins(client) # weird, failing for py2.6
    plugins = [('pytest-pep8', '1.0.5')] # only one package so we can quickly test the system
    for name, version in plugins:
        for url_data in client.release_urls(name, version):
            basename = os.path.basename(url_data['url'])
            if url_data['packagetype'] != 'sdist':
                print ' -> skipped ({}, {})'.format(url_data['packagetype'], basename)
            elif os.path.isfile(basename):
                print ' -> {} already downloaded'.format(basename)
            else:
                print ' ...', url_data['url'],
                urllib.urlretrieve(url_data['url'], basename)
                print 'OK'
            
    

#===================================================================================================
# extract_plugins
#===================================================================================================
def extract_plugins():
    
    def extract(extension, file_class):
        
        for filename in glob.glob('*%s' % extension):
            basename = filename[:-len(extension)]
            print basename, extension
            with file_class(filename) as f:
                f.extractall('.')
            
    extract('.zip', ZipFile)
    extract('.tar.gz', tarfile.open)
    
    
#===================================================================================================
# run_tox
#===================================================================================================
def run_tox():
    tox_env = 'py%d%d' % sys.version_info[:2]
    for name in os.listdir('.'):
        if os.path.isdir(name):
            if os.path.isfile(os.path.join(name, 'tox.ini')):
                oldcwd = os.getcwd()
                try:
                    os.chdir(name)
                    print '-> Running tox for', tox_env
                    os.system('tox --result-json=result.json -e %s' % tox_env)
                    contents = file('result.json').read()
                    json = simplejson.loads(contents) 
                    print contents
                finally:
                    os.chdir(oldcwd)
                    
    
#===================================================================================================
# main    
#===================================================================================================
if __name__ == '__main__':    
    download_plugins()
    extract_plugins() 
    run_tox()   

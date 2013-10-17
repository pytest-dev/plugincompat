from __future__ import print_function, with_statement, division

import os
import sys
import tarfile
from zipfile import ZipFile

#===================================================================================================
# py2x3 compatibility
#===================================================================================================
if sys.version_info[0] == 3:
    from xmlrpc.client import ServerProxy
    from urllib.request import urlretrieve
else:
    from xmlrpclib import ServerProxy
    from urllib import urlretrieve


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
# download_package
#===================================================================================================
def download_package(client, name, version):
    found_dists = []
    for url_data in client.release_urls(name, version):
        basename = os.path.basename(url_data['url'])
        found_dists.append(url_data['packagetype'])
        if url_data['packagetype'] == 'sdist':
            urlretrieve(url_data['url'], basename)
            return basename
        
    assert 'could not found a source dist: %r' % found_dists


#===================================================================================================
# extract
#===================================================================================================
def extract(basename):
    from contextlib import closing
    
    extractors = {
        '.zip' :  ZipFile,
        '.tar.gz': tarfile.open,
        '.tgz': tarfile.open,
    }
    for ext, extractor in extractors.items():
        if basename.endswith(ext):
            with closing(extractor(basename)) as f: # need closing for python 2.6 because of TarFile
                f.extractall('.')
            return basename[:-len(ext)]
    assert False, 'could not extract %s' % basename
    
            
#===================================================================================================
# run_tox
#===================================================================================================
def run_tox(directory):
    tox_env = 'py%d%d' % sys.version_info[:2]
    
    tox_file = os.path.join(directory, 'tox.ini')
    if os.path.isfile(tox_file):
        oldcwd = os.getcwd()
        try:
            os.chdir(directory)
            result = os.system('tox --result-json=result.json -e %s' % tox_env)
            return result
        finally:
            os.chdir(oldcwd)
            
    return None
                    
#===================================================================================================
# main
#===================================================================================================
def main():                    
    client = ServerProxy('https://pypi.python.org/pypi')
    
    # only one package so we can quickly test the system
    #plugins = iter_plugins(client) 
    plugins = [
        ('pytest-pep8', '1.0.5'),
        ('pytest-cache', '1.0'),
        ('pytest-xdist', '1.9'),
    ]                 
    
    for name, version in plugins:
        print( '=' * 60)
        basename = download_package(client, name, version)
        print('-> downloaded', basename)
        directory = extract(basename)
        print('-> extracted to', directory)
        result = run_tox(directory)
        print('-> tox returned %s' % result) 
    
#===================================================================================================
# main    
#===================================================================================================
if __name__ == '__main__':    
    main()  

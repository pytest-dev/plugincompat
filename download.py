import glob
import operator
import os
import tarfile
import urllib
import xmlrpclib
from zipfile import ZipFile


#===================================================================================================
# download_plugins
#===================================================================================================
def download_plugins():
    
    client = xmlrpclib.ServerProxy('http://pypi.python.org/pypi')
    for plug_data in sorted(client.search({'name' : 'pytest-'}), key=operator.itemgetter('_pypi_ordering')):
        print plug_data['name'], plug_data['version'], plug_data['summary']
        for url_data in client.release_urls(plug_data['name'], plug_data['version']):
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
# check_tox
#===================================================================================================
def check_tox():
    total = 0
    with_tox = 0
    for name in os.listdir('.'):
        if os.path.isdir(name):
            if os.path.isfile(os.path.join(name, 'tox.ini')):
                print name
                with_tox += 1
            total += 1
            
    print 'total:', total
    print 'tox:', with_tox
    
    
#===================================================================================================
# main    
#===================================================================================================
if __name__ == '__main__':    
    #download_plugins()
    #extract_plugins() 
    check_tox()   
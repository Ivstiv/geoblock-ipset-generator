import csv
import os.path
import sys
import socket, struct
import netaddr
import subprocess
import configparser
import random
import string
import wget
import zipfile
import six
from lxml import html

DEBUG = True

config = configparser.ConfigParser()
config.read('config.ini')

def validateArgs(args):
    if len(args) == 0:
        return False
    ARGUMENTS = ['--countries', '--name', '--update-database']
    for arg in args:
        if arg not in ARGUMENTS:
            print('[ERROR] Unknown argument: '+arg)
            return False
    return True

"""
    "question" is a string that is presented to the user.
    "default" is the presumed answer if the user just hits <Enter>.
    It must be "yes" (the default), "no" or None (meaning an answer
    is required of the user).

    The "answer" return value is True for "yes" or False for "no".
"""
def query_yes_no(question, default="yes"):
    valid = {"yes": True, "y": True, "ye": True,
             "no": False, "n": False}
    if default is None:
        prompt = " [y/n] "
    elif default == "yes":
        prompt = " [Y/n] "
    elif default == "no":
        prompt = " [y/N] "
    else:
        raise ValueError("invalid default answer: '%s'" % default)

    while True:
        sys.stdout.write(question + prompt)
        choice = six.moves.input().lower()
        if default is not None and choice == '':
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            sys.stdout.write("Please respond with 'yes' or 'no' "
                             "(or 'y' or 'n').\n")

def longToIp(long):
    return socket.inet_ntoa(struct.pack('!L', long))

def updateDatabase():
    if(not config['DATABASE']['token']):
        print('[ERROR] You need to specify a download token found in your IP2Location profile https://lite.ip2location.com/file-download')
        exit()

    print('Beginning download of DATABASE.ZIP...')
    url = 'https://www.ip2location.com/download/?token={Token}&file={DatabaseCode}'.format(Token=config['DATABASE']['token'],DatabaseCode=config['DATABASE']['database-code'])
    wget.download(url, 'DATABASE.ZIP')

    print('\nUnzipping %s...' % (config['DATABASE']['file']))
    try:
        with zipfile.ZipFile("DATABASE.ZIP","r") as zip_ref:
            zip_ref.extract(config['DATABASE']['file'])
    except zipfile.BadZipfile:
        print('[ERROR] You have either reached the download limit or the specified token is invalid.')
        f = open("DATABASE.ZIP", "r")
        print('[ERROR MESSAGE] '+f.read())
        f.close()
        os.remove("DATABASE.ZIP")
        exit()

    print('\nDeleting DATABASE.ZIP')
    os.remove("DATABASE.ZIP")

    print('\nThe database was sucessfully updated!')

def checkVersion():
    print('Checking for new database version...\n')
    # downloading the file for scraping
    versionURL = 'https://download.ip2location.com/lite/'
    wget.download(versionURL, 'versionCheck.html')
    versionCheck = open("versionCheck.html", "r")
    pageString = versionCheck.read()
    versionCheck.close()
    os.remove("versionCheck.html")

    # scraping the date of the upload
    pageHTML = html.fromstring(pageString)
    info = pageHTML.xpath('//a[@href="{File}"]/../following-sibling::*[1]/text()'.format(File=config['DATABASE']['database-version-file']))
    newDate = info[0].strip()

    print('\nYour database version is from: %s' % (config['DATABASE']['database-version-date']))
    print('Latest database version is from: %s' % (newDate))

    if(newDate != config['DATABASE']['database-version-date']):
        if query_yes_no('Would you like to download the latest version of the database?'):
            updateDatabase()

            # setting the new date
            config['DATABASE']['database-version-date'] = newDate
            with open('config.ini', 'w') as configfile:
                config.write(configfile)
    else:
        print('Nothing to update.')





##                          ##
# EXECUTION STARTS FROM HERE #
##                          ##

try:
    FNULL = open(os.devnull, 'w')
    subprocess.call(["ipset", 'help'], stdout=FNULL)
except:
    print('[ERROR] The script detected that ipset is not installed on the system!')
    exit()


checkVersion()

mainArgs = list(filter(lambda arg: arg.startswith('--'), sys.argv))
if validateArgs(mainArgs):
    countryCodes = []
    name = ''

    for arg in sys.argv:
        argumentIndex = sys.argv.index(arg)
        
        if arg == '--countries':
            if not os.path.isfile(config['DATABASE']['file']):
                print("[ERROR] Missing database file:"+config['DATABASE']['file'])
                exit()

            if argumentIndex+1 < len(sys.argv):
                countries = sys.argv[argumentIndex+1].upper() 
                countryCodes = countries.split(',')
                print('Countries: '+str(countryCodes))
            else:
                print('[ERROR] No countries specified!')
                exit()
                
        elif arg == '--name':
            if not os.path.isfile(config['DATABASE']['file']):
                print("[ERROR] Missing database file:"+config['DATABASE']['file'])
                exit()

            if argumentIndex+1 < len(sys.argv):
                name = sys.argv[argumentIndex+1]
                print('List name: '+name)
            else:
                print('[ERROR] No name specified!')
                exit()

        elif arg == '--update-database':
            updateDatabase()
            exit()


    # check for invalid country codes
    if any(len(el) != 2 for el in countryCodes) or any(not el.isalpha() for el in countryCodes):
        print('[ERROR] Invalid country code!')
        exit()

    # check if there is a name if not generate a random one 
    if len(name) < 1:
        print('[WARNING] You have not specified a name. A random name will be generated for the list!')
        name = 'geoblock-'+''.join(random.choice(string.ascii_lowercase) for i in range(6))
        print('Generated list name:'+name)
        if query_yes_no('Do you want to start over and define your own list name using --name?'):
            print('Exiting...')
            exit()
    
    ##                             ##
    # ADDING IP RANGES TO THE IPSET #
    ##                             ##

    # filter through the database for country codes
    listCIDRs = []
    listIpCount = 0
    for countryCode in countryCodes:
        reader = csv.reader(open(config['DATABASE']['file'], 'r'),delimiter=',')
        filtered = filter(lambda p: countryCode == p[2], reader)
        for row in filtered:
            startip = longToIp(int(row[0]))
            endip = longToIp(int(row[1]))
            cidr = netaddr.iprange_to_cidrs(startip, endip)[0]
            listIpCount += cidr.size
            print('%s FROM %s TO %s CIDR %s SIZE %d' % (row[2], startip, endip, cidr, cidr.size))
            listCIDRs.append(str(cidr))


    message = 'Do you want to add {count} IPs to {name}?'.format(count=listIpCount, name=name)
    print('\n[IMPORTANT] Very large IPsets can take longer to traverse and lower the performance due to high traffic. Increased RAM usage can also become a problem.\n')
    if query_yes_no(message):
        print('Creating an ipset with name %s...' % (name))
        if not DEBUG:
            # adding 1000 on top just in case people want to add more IPs manually
            subprocess.call(['ipset', 'create', name, 'hash:ip', 'maxelem', str(listIpCount+1000)])
        for range in listCIDRs:
            print('Adding %s to IPSet %s' % (range, name))
            if not DEBUG:
                subprocess.call(['ipset', 'add', name, range])   
    else:
        print('Exiting...')
        exit()

    print('\n%s was created successfully! You can follow the instructions in the README or the Github page if you want to implement the set as whitelist or blacklist.\n\nFor more advanced usage consider checking out the relevant firewall documentation.\n' % (name))
    print('To check your ipset execute: ipset list %s | less' % (name))
    print('To destroy your ipset execute: ipset destroy %s' % (name))
else:
    print("Use --help to see available options!")
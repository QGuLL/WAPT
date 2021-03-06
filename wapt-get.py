#!/usr/bin/python
# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------
#    This file is part of WAPT
#    Copyright (C) 2013  Tranquil IT Systems http://www.tranquil.it
#    WAPT aims to help Windows systems administrators to deploy
#    setup and update applications on users PC.
#
#    WAPT is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    WAPT is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with WAPT.  If not, see <http://www.gnu.org/licenses/>.
#
# -----------------------------------------------------------------------
__version__ = "1.4.1"

import codecs
import getpass
import glob
import json
import logging
import os
import shutil
import sys

from optparse import OptionParser
from waptutils import *

from waptpackage import PackageEntry
from waptpackage import update_packages

import common

from common import Wapt
from common import WaptDB

import setuphelpers

v = (sys.version_info.major, sys.version_info.minor)
if v != (2, 7):
    raise Exception('wapt-get supports only Python 2.7, not %d.%d' % v)


usage = """\
%prog -c configfile action

WAPT install system.

action is either :
  install <package> : install one or several packages by name, directory or wapt file
  update            : update package database
  upgrade           : upgrade installed packages, install host package if not installed.
  remove <package>  : remove installed packages

  download <package>: force download one or several packages
  show <package>    : show attributes of one or more packages

  list [keywords]   : list installed packages containing keywords
  list-upgrade      : list upgradable packages
  download-upgrade  : download available upgradable packages
  search [keywords] : search installable packages whose description contains keywords
  clean             : remove all WAPT cached files from local drive
  upgradedb         : manually upgrade the schema used by the WAPT database. If the database file can't be found, it will be recreated.

  setup-tasks       : creates Windows daily scheduled tasks for update/download-upgrade/upgrade
  enable-tasks
  disable-tasks

  add-upgrade-shutdown    : add a local shutdown policy to launch upgrade
                            of packages at windows shutdown (via waptexit.exe)
  remove-upgrade-shutdown : remove shutdown policy

  register [description] : Add the computer to the WAPT server database,
                                     change the description of the computer.
  inventory         : get json encoded list of host data, installed packages and softwares as supplied to server with register
  update-status     : Send packages and softwares status to the WAPT server,

  setlocalpassword  : Set the local admin password for waptservice access to
                      packages install/remove (for standalone usage)

  reset-uuid        : reset host's UUID to the uuid provided by the BIOS.
  generate-uuid     : regenerate a random host's UUID, stored in wapt-get.ini.

  get-server-certificate : get the public key from waptserver and save it to <waptbasedir>\\ssl\\server
  enable-check-certificate : get the public key from waptserver,save it to <waptbasedir>\\ssl\\server and enable verify in config file.

 For user session setup
  session-setup [packages,ALL] : setup local user environment for specific or all installed packages

 For packages development (Wapt default configuration is taken from user's waptconsole.ini if it exists)
  list-registry [keywords]  : list installed software from Windows Registry
  sources <package>         : checkout or update sources of a package from SVN repository (if attribute Sources was supplied in control file)
  make-template <installer-path> [<packagename> [<source directoryname>]] : initializes a package template with an installer (exe or msi)
  make-host-template <machinename> [[<package>,<package>,...] [directory]] :
                                initializes a package meta template with packages.
                                If no package name is given, use FQDN
  make-group-template <groupname> [[<package>,<package>,...] [directory]] :
                                initializes a meta package template with supplied dependencies.

  build-package <directory> : creates a WAPT package from supplied directory
  sign-package <directory or package>  : add a signature of the manifest using a private SSL key
  build-upload <directory> : creates a WAPT package from supplied directory, sign it and upload it
  duplicate <directory or package> <new-package-name> [<new-version> [<target directory>]] : duplicate an existing package,
                                            changing its name (can be used for duplication of host packages...)
  edit <package> [p1,p2,..]: download and unzip a package. Open in Explorer the target directory. Appends dependencies p1, p2 ...
  edit-host <host fqdn> [p1,p2,..]: download an unzip a host package. Open in Explorer the target directory. Appends dependencies p1, p2 ...

 For repository management
  upload-package  <filenames> : upload package to repository (using winscp for example.)
  update-packages <directory> : rebuild a "Packages" file for http package repository

"""

parser=OptionParser(usage=usage,version='wapt-get.py ' + __version__+' common.py '+common.__version__+' setuphelpers.py '+setuphelpers.__version__)

default_waptservice_ini=os.path.join(os.path.dirname(sys.argv[0]),'wapt-get.ini')
default_waptconsole_ini=setuphelpers.makepath(setuphelpers.user_local_appdata(),'waptconsole','waptconsole.ini')

parser.add_option("-c","--config", dest="config", default=None, help="Config file full path (default: %default)")
parser.add_option("-l","--loglevel", dest="loglevel", default=None, type='choice',  choices=['debug','warning','info','error','critical'], metavar='LOGLEVEL',help="Loglevel (default: warning)")
parser.add_option("-D","--direct",    dest="direct",    default=False, action='store_true', help="Don't use http service for update/upgrade (default: %default)")
parser.add_option("-S","--service",    dest="service",    default=False, action='store_true', help="User http service for update/upgrade/install/remove (default: %default)")
parser.add_option("-d","--dry-run",    dest="dry_run",    default=False, action='store_true', help="Dry run (default: %default)")
parser.add_option("-u","--update-packages",    dest="update_packages",  default=False, action='store_true', help="Update Packages first then action (default: %default)")
parser.add_option("-f","--force",    dest="force",    default=False, action='store_true', help="Force (default: %default)")
parser.add_option("-p","--params", dest="params", default='{}', help="Setup params as a JSon Object (example : {'licence':'AZE-567-34','company':'TIS'}} (default: %default)")
parser.add_option("-r","--repository", dest="wapt_url", default='', help="URL of main wapt repository (override url from ini file, example http://wapt/wapt) (default: %default)")
parser.add_option("-i","--inc-release",    dest="increlease",    default=False, action='store_true', help="Increase release number when building package (default: %default)")
parser.add_option("-s","--sections",    dest="section_filter",    default=None,  help="Add a filter section to search query (default: ALL)")
parser.add_option("-j","--json",    dest="json_output",    default=False, action='store_true', help="Switch to json output for scripts purpose (default: %default)")
parser.add_option("-e","--encoding",    dest="encoding",    default=None, help="Chararacter encoding for the output (default: no change)")
parser.add_option("-x","--excludes",    dest="excludes",    default='.svn,.git*,*.pyc,*.dbg,src', help="Comma separated list of files or directories to exclude for build-package (default: %default)")
parser.add_option("-k","--private-key", dest="private_key",    default='', help="Path to the PEM RSA private key to sign packages. Package are unsigned if not provided (default: %default)")
parser.add_option("-w","--private-key-passwd", dest="private_key_passwd", default='', help="Path to the password of the private key. (default: %default)")
parser.add_option("-U","--user", dest="user", default=None, help="Interactive user (default: no change)")
parser.add_option("-g","--usergroups", dest="usergroups", default='[]', help="Groups of the final user as a JSon array for checking install permission (default: %default)")
parser.add_option("-t","--maxttl", type='int',  dest="max_ttl", default=60, help="Max run time in minutes of wapt-get process before being killed by subsequent wapt-get (default: %default minutes)")
parser.add_option("-L","--language",    dest="language",    default=setuphelpers.get_language(), help="Override language for install (example : fr) (default: %default)")
parser.add_option("--wapt-server-user", dest="wapt_server_user", default=None, help="User to upload packages to waptserver. (default: %default)")
parser.add_option("--wapt-server-passwd", dest="wapt_server_passwd", default=None, help="Password to upload packages to waptserver. (default: %default)")
parser.add_option("--log-to-windows-events",dest="log_to_windows_events",    default=False, action='store_true', help="Log steps to the Windows event log (default: %default)")

(options,args) = parser.parse_args()

encoding = options.encoding
if not encoding:
    encoding = sys.stdout.encoding or 'cp850'

sys.stdout = codecs.getwriter(encoding)(sys.stdout,'replace')
sys.stderr = codecs.getwriter(encoding)(sys.stderr,'replace')

# setup Logger
logger = logging.getLogger()
loglevel = options.loglevel

if len(logger.handlers) < 1:
    hdlr = logging.StreamHandler(sys.stderr)
    hdlr.setFormatter(logging.Formatter(
        u'%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(hdlr)

def setloglevel(loglevel):
    """set loglevel as string"""
    if loglevel in ('debug','warning','info','error','critical'):
        numeric_level = getattr(logging, loglevel.upper(), None)
        if not isinstance(numeric_level, int):
            raise ValueError('Invalid log level: %s' % loglevel)
        logger.setLevel(numeric_level)

if loglevel:
    setloglevel(loglevel)
else:
    setloglevel('warning')

logger.debug(u'Default encoding : %s ' % sys.getdefaultencoding())
logger.debug(u'Setting encoding for stdout and stderr to %s ' % encoding)

key_passwd = None


class JsonOutput(object):
    """file like to print output to json"""
    def __init__(self,output,logger):
        self.output = output
        self.logger = logger

    def write(self,txt):
        txt = ensure_unicode(txt)
        if txt != '\n':
            logger.info(txt)
            self.output.append(txt)

    def __getattrib__(self, name):
        if hasattr(self.output,'__getattrib__'):
            return self.output.__getattrib__(name)
        else:
            return self.output.__getattribute__(name)


def wapt_sources_edit(wapt_sources_dir):
    psproj_filename = os.path.join(wapt_sources_dir,'WAPT','wapt.psproj')
    control_filename = os.path.join(wapt_sources_dir,'WAPT','control')
    setup_filename = os.path.join(wapt_sources_dir,'setup.py')
    pyscripter_filename = os.path.join(setuphelpers.programfiles32,
                                       'PyScripter', 'PyScripter.exe')
    if os.path.isfile(pyscripter_filename) and os.path.isfile(psproj_filename):
        import psutil
        p = psutil.Popen('"%s" --newinstance --project "%s" "%s" "%s"' % (
                         pyscripter_filename,
                         psproj_filename,
                         setup_filename,
                         control_filename),
                         cwd=os.path.join(setuphelpers.programfiles32,
                                          'PyScripter'))
    else:
        os.startfile(wapt_sources_dir)

def guess_package_root_dir(fn):
    """return the root dir of package development dir given
            control fn,
            setup fn or
            package directory
    """
    if os.path.isdir(fn):
        if os.path.isfile(os.path.join(fn,'WAPT','control')):
            return fn
        elif os.path.isfile(os.path.join(fn,'control')):
            return os.path.abspath(os.path.join(fn,'..'))
        else:
            return fn
    elif os.path.isfile(fn):
        if os.path.basename(fn) == 'control':
            return os.path.abspath(os.path.join(os.path.dirname(fn),'..'))
        elif os.path.basename(fn) == 'setup.py':
            return os.path.abspath(os.path.dirname(fn))
        else:
            return fn
    else:
        return fn

def main():
    jsonresult = {'output':[]}
    if options.json_output:
        # redirect output to json list
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stderr = sys.stdout = JsonOutput(
            jsonresult['output'],logger)

    try:
        if len(args) == 0:
            print(u"ERROR : You must provide one action to perform")
            parser.print_usage()
            sys.exit(2)

        action = args[0]
        development_actions = ['sources','make-template',
            'make-host-template','make-group-template','build-package',
            'sign-package','build-upload','duplicate','edit','edit-host',
            'upload-package','update-packages']
        if not options.config:
            if action in development_actions and os.path.isfile(default_waptconsole_ini):
                config_file = default_waptconsole_ini
                logger.info(u'/!\ Development mode, using Waptconsole configuration %s '%config_file)
            else:
                config_file = default_waptservice_ini
                logger.info(u'Using local waptservice configuration %s '%config_file)
        else:
            config_file = options.config
        # Config file
        if not os.path.isfile(config_file):
            logger.error((u"Error : could not find file : %s"
                          ", please check the path") % config_file)

        logger.debug(u'Config file: %s' % config_file)

        mywapt = Wapt(config_filename=config_file)
        if options.wapt_url:
            mywapt.config.set('global','repo_url',options.wapt_url)

        global loglevel
        if not loglevel and mywapt.config.has_option('global','loglevel'):
            loglevel = mywapt.config.get('global','loglevel')
            setloglevel(loglevel)

        mywapt.options = options

        if options.log_to_windows_events:
            try:
                from logging.handlers import NTEventLogHandler
                hdlr = NTEventLogHandler('wapt-get')
                logger.addHandler(hdlr)
            except Exception as e:
                print('Unable to initialize windows log Event handler: %s' % e)



        if options.private_key:
            mywapt.private_key = options.private_key

        # key password management
        def pwd_callback(*args):
            """Password callback for opening private keysin suppli password file"""
            return open(options.private_key_passwd,'r').read().splitlines()[0].strip()

        if options.private_key_passwd:
            mywapt.key_passwd_callback = pwd_callback

        if options.language:
            mywapt.language = options.language

        if options.usergroups:
            mywapt.usergroups = json.loads(options.usergroups.replace("'",'"'))
            logger.info(u'User Groups:%s' % (mywapt.usergroups,))

        if options.user:
            mywapt.user = options.user
            logger.info(u'Interactive user :%s' % (mywapt.user,))

        mywapt.dry_run = options.dry_run

        # development mode, using a memory DB.
        if config_file == default_waptconsole_ini:
            mywapt.dbpath = r':memory:'
            mywapt.use_hostpackages = False
            logger.info('Updating in-memory packages index from repositories...')
            update_result = mywapt.update(register=False,filter_on_host_cap=False)
            logger.info('Configuration file : %s' % config_file)
            logger.info('  waptserver     : %s' % mywapt.waptserver)
            logger.info('  repositories   : %s' % mywapt.repositories)
            logger.info('  packages count : %s' % update_result['count'])

        logger.debug(u'WAPT base directory : %s' % mywapt.wapt_base_dir)
        logger.debug(u'Package cache dir : %s' % mywapt.package_cache_dir)
        logger.debug(u'WAPT DB Structure version;: %s' % mywapt.waptdb.db_version)

        try:
            params_dict = {}
            try:
                params_dict = json.loads(options.params.replace("'",'"'))
            except:
                raise Exception(
                    'Installation Parameters must be in json format')

            # cleanup environement, remove stalled wapt-get, update install_status
            if action in ('install','download','remove','uninstall','update','upgrade'):
                running_install = mywapt.check_install_running(max_ttl=options.max_ttl)
            else:
                running_install = []

            if action == 'install':
                if len(args) < 2:
                    print(u"You must provide at least one package name")
                    sys.exit(1)

                if os.path.isdir(args[1]) or os.path.isfile(args[1]) or '*' in args[1]:
                    all_args = expand_args(args[1:])
                    print(u"Installing WAPT files %s" % ", ".join(all_args))
                    # abort if there is already a running install in progress
                    if running_install:
                        raise Exception(u'Running wapt progresses (%s), please wait...' % (running_install,))
                    result = {u'install':[]}
                    for fn in all_args:
                        fn = guess_package_root_dir(fn)
                        res = mywapt.install_wapt(fn,params_dict = params_dict)
                        result['install'].append((fn,res))
                else:
                    print(u"%sing WAPT packages %s" % (action,','.join(args[1:])))
                    if options.update_packages:
                        print(u"Update package list")
                        mywapt.update()

                    if running_install and action == 'install':
                        raise Exception(u'Running wapt processes (%s) in progress, please wait...' % (running_install,))

                    result = mywapt.install(
                        args[1:],
                        force=options.force,
                        params_dict=params_dict,
                        download_only=(action == 'download'),
                        usecache = not (action == 'download' and options.force)
                    )

                if options.json_output:
                    jsonresult['result'] = result
                else:
                    print(u"\nResults :")
                    if action != 'download':
                        for k in ('install','additional','upgrade','skipped','errors'):
                            if result.get(k,[]):
                                print(u"\n === %s packages ===\n%s" % (k,'\n'.join(["  %-30s | %s (%s)" % (ensure_unicode(s[0]),s[1].package,s[1].version) for s in result[k]]),))
                    else:
                        for k in ('downloaded','skipped','errors'):
                            if result.get('downloads', {'downloaded':[],'skipped':[],'errors':[]})[k]:
                                print(u"\n=== %s packages ===\n%s" % (k,'\n'.join(["  %s" % (s,) for s in result['downloads'][k]]),))
                    if result.get('unavailable',[]):
                        print(u'Critical : ')
                        print(u' === Unavailable packages ===\n%s' % '\n'.join(["  %-30s" % s[0] for s in  result['unavailable']]))
                if mywapt.waptserver:
                    try:
                        mywapt.update_server_status()
                    except Exception as e:
                        logger.critical('Unable to update server with current status : %s' % ensure_unicode(e))

            elif action == 'download':
                if len(args) < 2:
                    print(u"You must provide at least one package name to download")
                    sys.exit(1)
                if options.update_packages:
                    print(u"Update package list")
                    mywapt.update()
                packages = args[1:]
                depends = mywapt.check_downloads(packages)
                print(u"Downloading packages %s" % (','.join([p.asrequirement() for p in depends]),))
                result = mywapt.download_packages(depends, usecache=not options.force)
                if options.json_output:
                    jsonresult['result'] = result
                else:
                    if result['downloaded']:
                        print(u"\nDownloaded packages : \n%s" % u"\n".join(["  %s" % p for p in result['downloaded']]))
                    if result['skipped']:
                        print(u"Skipped packages : \n%s" % u"\n".join([u"  %s" % p for p in result['skipped']]))
                if result['errors']:
                    logger.critical(u'Unable to download some files : %s' % (result['errors'],))
                    sys.exit(1)

            elif action == 'show':
                if len(args) < 2:
                    print(u"You must provide at least one package name to show")
                    sys.exit(1)
                result = []
                if options.update_packages:
                    if not options.json_output:
                        print(u"Update packages list")
                    mywapt.update()

                all_args = expand_args(args[1:])
                if all_args:
                    for arg in all_args:
                        if os.path.isdir(arg) or os.path.isfile(arg):
                            control = PackageEntry().load_control_from_wapt(arg)
                            result.append(control)
                else:
                    for arg in args[1:]:
                        result.extend(mywapt.waptdb.packages_matching(arg))

                if options.json_output:
                    jsonresult['result'] = result
                    for p in result:
                        try:
                            crt = control.check_control_signature(mywapt.authorized_certificates())
                            print('%s OK control signature checked properly by certificate %s (fingerprint: %s )' % (p.filename,crt.cn,crt.fingerprint))
                        except Exception as e:
                            print('%s ERROR control signature can not be validated with certificates %s' % (p.filename,mywapt.authorized_certificates()))
                else:
                    print(u"Display package control data for %s\n" % (','.join(all_args),))
                    for p in result:
                        print(p.ascontrol(with_non_control_attributes=True))
                        print('')
                        try:
                            logger.info(u'Verifying package control signature against certificates %s' % mywapt.authorized_certificates())
                            crt = control.check_control_signature(mywapt.authorized_certificates())
                            print('OK Package control signature checked properly by certificate %s (fingerprint: %s )' % (crt.cn,crt.fingerprint))
                        except:
                            print('WARNING: control data signature can not be validated with certificates %s' %mywapt.authorized_certificates())
                        print('')

            elif action == 'show-params':
                if len(args) < 2:
                    print(u"You must provide at one package name to show params for")
                    sys.exit(1)
                for packagename in args[1:]:
                    params = mywapt.waptdb.params(packagename)
                    print(u"%s : %s" % (packagename,params))

            elif action == 'list-registry':
                result = setuphelpers.installed_softwares(' '.join(args[1:]))
                if options.json_output:
                    jsonresult['result'] = result
                else:
                    print(u"%-39s%-70s%-20s%-70s" % ('UninstallKey','Software','Version','Uninstallstring'))
                    print(u'-' * 39 + '-' * 70 + '-' * 20 + '-' * 70)
                    for p in result:
                        print(u"%-39s%-70s%-20s%-70s" % (p['key'],p['name'],p['version'],p['uninstall_string']))

            elif action in ('showlog','show-log'):
                if len(args) < 2:
                    print(u"You must provide at least one package name")
                    sys.exit(1)
                for packagename in args[1:]:
                    result = mywapt.last_install_log(packagename)
                    print(u"Package : %s\nStatus : %s\n\nInstallation log:\n%s" % (packagename,result['status'],result['log']))

            elif action == 'remove':
                if len(args) < 2:
                    print(u"You must provide at least one package name to remove")
                    sys.exit(1)
                # abort if there is already a running install in progress
                if running_install:
                    raise Exception('Running wapt processes (%s) in progress, please wait...' % (running_install,))
                removed = []
                errors = []
                for packagename in args[1:]:
                    print(u"Removing %s ..." % (packagename,))
                    try:
                        packagename = guess_package_root_dir(packagename)
                        result = mywapt.remove(packagename,force=options.force)
                        errors.extend(result['errors'])
                        removed.extend(result['removed'])
                    except:
                        errors.append(packagename)

                if options.json_output:
                    jsonresult['result'] = {'errors':errors,'removed':removed}
                else:
                    if removed:
                        print(u"=== Removed packages ===\n%s" % u"\n".join([u"  %s" % p for p in removed]))
                    else:
                        print(u"No package removed !")

                    if errors:
                        print(u"=== Error removing packages ===\n%s" % u"\n".join([u"  %s" % p for p in errors]))

                if mywapt.waptserver:
                    try:
                        mywapt.update_server_status()
                    except Exception as e:
                        logger.critical('Unable to update server with current status : %s' % ensure_unicode(e))

            elif action == 'session-setup':
                if len(args) < 2:
                    print(u"You must provide at least one package to be configured in user's session or ALL (in uppercase) for all currently installed packages of this system")
                    sys.exit(1)
                result = []
                if args[1] == 'ALL':
                    packages_list = mywapt.installed().keys()
                else:
                    packages_list = args[1:]
                for packagename in packages_list:
                    try:
                        print(u"Configuring %s ..." % (packagename,))
                        packagename = guess_package_root_dir(packagename)
                        result.append(mywapt.session_setup(packagename,force=options.force))
                        print("Done")
                    except Exception as e:
                        logger.critical(ensure_unicode(e))
                if args[1] == 'ALL':
                    logger.debug('cleanup session db, removed not installed package entries')
                    mywapt.cleanup_session_setup()
                if options.json_output:
                    jsonresult['result'] = result

            elif action == 'uninstall':
                # launch the setup.uninstall() procedure for the given packages
                # can be used when registering in registry a custom install
                # with a python script
                if len(args) < 2:
                    print(u"You must provide at least one package to be uninstalled")
                    sys.exit(1)

                for packagename in args[1:]:
                    print(u"Uninstalling %s ..." % (packagename,))
                    packagename = guess_package_root_dir(packagename)
                    print(mywapt.uninstall(packagename,params_dict=params_dict))
                    print(u"Uninstallation done")

            elif action == 'update':
                # abort if there is already a running install in progress
                if running_install:
                    raise Exception('Running wapt processes (%s) in progress, please wait...' % (running_install,))
                print(u"Update package list")
                result = mywapt.update(force=options.force)
                if options.json_output:
                    jsonresult['result'] = result
                else:
                    print(u"Total packages : %i" % result['count'])
                    print(u"Added packages : \n%s" % "\n".join(["  %s (%s)" % p for p in result['added']]))
                    print(u"Removed packages : \n%s" % "\n".join(["  %s (%s)" % p for p in result['removed']]))
                    print(u"Upgradable packages : \n%s" % "\n".join(["  %s" % p for p in result['upgrades']]))
                    print(u"Repositories URL : \n%s" % "\n".join(["  %s" % p for p in result['repos']]))

            elif action == 'upgradedb':
                # abort if there is already a running install in progress
                if running_install:
                    raise Exception('Running wapt processes (%s) in progress, please wait...' % (running_install,))
                (old,new) = mywapt.waptdb.upgradedb(force=options.force)
                if old == new:
                    print(u"No database upgrade required, current %s, required %s" % (old,mywapt.waptdb.curr_db_version))
                else:
                    print(u"Old version : %s to new : %s" % (old,new))

            elif action == 'upgrade':
                if options.update_packages:
                    print(u"Update packages list")
                    mywapt.update()
                # abort if there is already a running install in progress
                if running_install:
                    raise Exception('Running wapt processes (%s) in progress, please wait...' % (running_install,))
                result = mywapt.upgrade()

                if options.json_output:
                    jsonresult['result'] = result
                else:
                    if not result['install'] and not result['additional'] and not result['upgrade'] and not result['skipped']:
                        print(u"Nothing to upgrade")
                    else:
                        for k in ('install','additional','upgrade','skipped','errors'):
                            if result[k]:
                                print(u"\n=== %s packages ===\n%s" % (k,'\n'.join( ["  %-30s | %s (%s)" % (s[0],s[1].package,s[1].version) for s in  result[k]]),))
                if mywapt.waptserver:
                    try:
                        mywapt.update_server_status()
                    except Exception as e:
                        logger.critical('Unable to update server with current status : %s' % ensure_unicode(e))
                sys.exit(0)

            elif action == 'list-upgrade':
                if options.update_packages:
                    print(u"Update package list")
                    mywapt.update()
                result = mywapt.list_upgrade()
                if not result:
                    print(u"Nothing to upgrade")
                if options.json_output:
                    jsonresult['result'] = result
                else:
                    for l in ('install','additional','upgrade'):
                        if result[l]:
                            print(u"\n=== %s packages ===\n%s" % (l,'\n'.join( ["  %-30s " % (p) for p in  result[l]]),))

            elif action == 'download-upgrade':
                # abort if there is already a running install in progress
                if options.update_packages:
                    print(u"Update packages list")
                    mywapt.update()
                result = mywapt.download_upgrades()
                if options.json_output:
                    jsonresult['result'] = result
                else:
                    for l in ('downloaded','skipped','errors'):
                        if result[l]:
                            print(u"\n=== %s packages ===\n%s" % (l,'\n'.join( ["  %-30s " % (p) for p in  result[l]]),))
                    if result['errors']:
                        logger.critical(u'Unable to download some files : %s' % (result['errors'],))
                        sys.exit(1)

            elif action == 'forget':
                if len(args) < 2:
                    print(u"You must provide the package names to forget")
                    sys.exit(1)
                result = mywapt.forget_packages(args[1:])
                if options.json_output:
                    jsonresult['result'] = result
                else:
                    print(u"\n=== Packages removed from status ===\n%s" % ('\n'.join( ["  %-30s " % (p) for p in  result]),))

            elif action == 'update-packages':
                if len(args) < 2:
                    print(u"You must provide the directory")
                    sys.exit(1)
                result = update_packages(args[1],force=options.force)

                if options.json_output:
                    jsonresult['result'] = result
                else:
                    print(u"Packages filename : %s" % result['packages_filename'])
                    print(u"Processed packages :\n%s" % "\n".join(["  %s" % p for p in result['processed']]))
                    print(u"Skipped packages :\n%s" % "\n".join(["  %s" % p for p in result['kept']]))
                    if result['errors']:
                        logger.critical(u'Unable to process some files :\n%s' % "\n".join(["  %s" % p for p in result['kept']]))
                        sys.exit(1)

            elif action == 'sources':
                if len(args) < 2:
                    print(u"You must provide the package name")
                    sys.exit(1)
                result = mywapt.get_sources(args[1])
                os.startfile(result)
                wapt_sources_edit(result)

            elif action == 'make-template':
                if len(args) < 2:
                    print(u"You must provide the installer path")
                    sys.exit(1)
                result = mywapt.make_package_template(*args[1:])
                if options.json_output:
                    jsonresult['result'] = result
                else:
                    print(u"Template created. You can build the WAPT package by launching\n  %s build-package %s" % (sys.argv[0],result))
                    if mywapt.upload_cmd or mywapt.waptserver:
                        print(u"You can build and upload the WAPT package by launching\n  %s build-upload %s" % (sys.argv[0],result))
                    wapt_sources_edit(result)

            elif action in ('make-host-template','make-group-template'):
                if action == 'make-host-template':
                    result = mywapt.make_host_template(*args[1:])
                else:
                    result = mywapt.make_group_template(*args[1:])
                if options.json_output:
                    jsonresult['result'] = result
                else:
                    print(u"Template created. You can build the WAPT package by launching\n  %s build-package %s" % (sys.argv[0],result['source_dir']))
                    if mywapt.upload_cmd or mywapt.waptserver:
                        print(u"You can build and upload the WAPT package by launching\n  %s build-upload %s" % (sys.argv[0],result['source_dir']))
                    wapt_sources_edit(result['source_dir'])

            elif action == 'duplicate':
                if len(args) < 3:
                    print(u"You must provide the source package and the new name")
                    sys.exit(1)
                result = mywapt.duplicate_package(*args[1:4],target_directory='',
                    build=False)
                if options.json_output:
                    jsonresult['result'] = result
                else:
                    if os.path.isdir(result['target']):
                        print(u"Package duplicated. You can build the new WAPT package by launching\n  %s build-package %s" % (sys.argv[0],result['source_dir']))
                        if mywapt.upload_cmd or mywapt.waptserver:
                            print(u"You can build and upload the new WAPT package by launching\n  %s build-upload %s" % (sys.argv[0],result['source_dir']))
                        wapt_sources_edit(result['source_dir'])
                    else:
                        print(u"Package duplicated. You can upload the new WAPT package to repository by launching\n  %s upload-package %s" % (sys.argv[0],result['target']))
                        print(u"You can rebuild and upload the new WAPT package by launching\n  %s build-upload %s" % (sys.argv[0],result['source_dir']))

            elif action == 'edit':
                if len(args) < 2:
                    print(u"You must provide the package to edit")
                    sys.exit(1)
                if len(args) >= 3:
                    result = mywapt.edit_package(packagerequest=args[1],
                                                 append_depends=args[2])
                else:
                    result = mywapt.edit_package(packagerequest=args[1])
                if options.json_output:
                    jsonresult['result'] = result
                else:
                    if os.path.isdir(result['target']):
                        wapt_sources_edit(result['target'])
                        if mywapt.upload_cmd or mywapt.waptserver:
                            print(u"Package edited. You can build and upload the new WAPT package by launching\n  %s -i build-upload %s" % (sys.argv[0],result['target']))
                        else:
                            print(u"Package edited. You can build the new WAPT package by launching\n  %s -i build-package %s" % (sys.argv[0],result['target']))

            elif action == 'edit-host':
                if len(args) == 1:
                    print(u"Using current host fqdn %s" % setuphelpers.get_hostname())
                    result = mywapt.edit_host(hostname=setuphelpers.get_hostname(),
                                              use_local_sources=True)
                elif len(args) >= 3:
                    result = mywapt.edit_host(hostname=args[1],
                                              append_depends=args[2],
                                              use_local_sources=True)
                else:
                    result = mywapt.edit_host(hostname=args[1],
                                              use_local_sources=True)
                if options.json_output:
                    jsonresult['result'] = result
                else:
                    if os.path.isdir(result['target']):
                        wapt_sources_edit(result['target'])
                        if mywapt.upload_cmd or mywapt.waptserver:
                            print(u"Package edited. You can build and upload the new WAPT package by launching\n  %s -i build-upload %s" % (sys.argv[0],result['target']))
                        else:
                            print(u"Package edited. You can build the new WAPT package by launching\n  %s -i build-package %s" % (sys.argv[0],result['target']))

            elif action in ('build-package','build-upload'):
                if len(args) < 2:
                    print(u"You must provide at least one source directory for package building")
                    sys.exit(1)
                if not mywapt.private_key or not os.path.isfile(mywapt.private_key):
                    print(u"You must provide the filepath to a private key in the [global]->private_key key of configuration %s" %config_file)
                    sys.exit(1)

                packages = []
                errors = []

                all_args = expand_args(args[1:])
                print("Building packages %s packages" % len(all_args))

                for source_dir in all_args:
                    try:
                        source_dir = guess_package_root_dir(source_dir)
                        if os.path.isdir(source_dir):
                            print('Building  %s' % source_dir)
                            result = mywapt.build_package(
                                source_dir,
                                inc_package_release=options.increlease,
                                excludes=ensure_list(options.excludes))
                            package_fn = result['filename']
                            if package_fn:
                                packages.append(result)
                                if not options.json_output:
                                    print(u"Package %s content:" % (result['package'].asrequirement(),))
                                    for f in result['files']:
                                        print(u" %s" % f)
                                print('...done. Package filename %s' % (package_fn,))

                                if mywapt.private_key:
                                    print('Signing %s with key %s' % (package_fn,mywapt.private_key))
                                    signature = mywapt.sign_package(
                                        package_fn,
                                        excludes=common.ensure_list(options.excludes)
                                        )
                                    print(u"Package %s signed : signature :\n%s" % (package_fn,signature))
                                else:
                                    logger.warning(u'No private key provided, package %s is unsigned !' % package_fn)

                            else:
                                logger.critical(u'package %s not created' % package_fn)

                        else:
                            logger.critical(u'Directory %s not found' % source_dir)
                    except Exception as e:
                        errors.append(source_dir)
                        print(u'  ERROR building %s: %s' % (source_dir,e))

                print(u'%s packages successfully built'%len(packages))
                print(u'%s packages failed '%len(errors))

                if errors:
                    print(u'List of errors :\n%s'%('\n '.join(errors)))

                # continue with upload
                if action == 'build-upload':
                    print('Uploading files...')
                    # groups by www target : wapt or wapt-host
                    hosts = ('wapt-host',[])
                    others = ('wapt',[])
                    # split by destination
                    for p in packages:
                        if p['package'].section == 'host':
                            hosts[1].append(p['filename'])
                        else:
                            others[1].append(p['filename'])
                    for package_group in (hosts,others):
                        if package_group[1]:
                            # add quotes for command line
                            files_list = ['"%s"' % f for f in package_group[1]]
                            cmd_dict = {
                                'waptfile': files_list,
                                'waptdir':package_group[0],
                            }
                            res = mywapt.upload_package(cmd_dict,
                                wapt_server_user = options.wapt_server_user,
                                wapt_server_passwd=options.wapt_server_passwd)
                            print('Status : %s, %s' % (
                                res['status'], res['message']))

                            if package_group != hosts:
                                if mywapt.after_upload:
                                    print('Run after upload script...')
                                    print(setuphelpers.run(mywapt.after_upload % cmd_dict))

                else:
                    print(u'\nYou can upload to repository with')
                    print(u'  %s upload-package %s ' % (
                        sys.argv[0],'"%s"' % (
                            ' '.join([p['filename'] for p in packages]),
                        )
                    ))

            elif action == 'sign-package':
                if len(args) < 2:
                    print(u"You must provide at least one source directory or package to sign")
                    sys.exit(1)
                if not mywapt.private_key or not os.path.isfile(mywapt.private_key):
                    print(u"You must provide the filepath to a private key in the [global]->private_key key of configuration %s" %config_file)
                    sys.exit(1)

                all_args = expand_args(args[1:])
                print("Signing packages %s" % ", ".join(all_args))
                for waptfile in all_args:
                    try:
                        waptfile = guess_package_root_dir(waptfile)
                        if os.path.isdir(waptfile) or os.path.isfile(waptfile):
                            print('Signing %s with key %s' % (waptfile,mywapt.private_key))
                            signature = mywapt.sign_package(
                                waptfile,
                                excludes=common.ensure_list(options.excludes)
                                )
                            print(u"   OK: Package %s signed : signature :\n%s" % (
                                waptfile, signature))
                        else:
                            logger.critical(u'Package %s not found' % waptfile)
                    except Exception as e:
                        print(u'   ERROR: %s: %s'% (waptfile,e))
                sys.exit(0)

            elif action == 'upload-package':
                if len(args) < 2:
                    print(u"You must provide a package to upload")
                    sys.exit(1)
                waptfiles = []
                for a in args[1:]:
                    waptfiles += glob.glob(a)

                # groups by www target : wapt or wapt-host
                hosts = ('wapt-host',[])
                others = ('wapt',[])
                # split by destination
                for w in waptfiles:
                    p = PackageEntry()
                    p.load_control_from_wapt(w)
                    if p.section == 'host':
                        hosts[1].append(w)
                    else:
                        others[1].append(w)

                for package_group in (hosts,others):
                    if package_group[1]:
                        # add quotes for command line
                        files_list = ['"%s"' % f for f in package_group[1]]
                        cmd_dict = {
                            'waptfile': files_list,
                            'waptdir':package_group[0],
                        }

                        print(mywapt.upload_package(cmd_dict,
                            wapt_server_user = options.wapt_server_user,
                            wapt_server_passwd=options.wapt_server_passwd))
                        if package_group != hosts:
                            if mywapt.after_upload:
                                print('Run after upload script...')
                                print(setuphelpers.run(mywapt.after_upload % cmd_dict))

            elif action == 'search':
                if options.update_packages:
                    print(u"Update package list")
                    mywapt.update()
                result = mywapt.search([ensure_unicode(w) for w in args[1:]],
                                       section_filter=options.section_filter)
                if options.json_output:
                    jsonresult['result'] = result
                else:
                    print(ppdicttable(result, (
                        (('status','Stat'),10),
                        (('package','Package'),30),
                        ('version',10),
                        (('architecture','Arc'),3),
                        (('maturity','Val'),3),
                        (('locale','Loc'),3),
                        ('description',80),
                        ('repo',10))))

            elif action in ('clean','cleanup'):
                result = mywapt.cleanup(obsolete_only=not options.force)
                if options.json_output:
                    jsonresult['result'] = result
                else:
                    print(u"Removed files : \n%s" % "\n".join(["  %s" % p for p in result]))

            elif action == 'register':
                if mywapt.waptserver:
                    result = mywapt.register_computer(
                        description=(" ".join(args[1:])).decode(sys.getfilesystemencoding()),
                        )
                    if options.json_output:
                        jsonresult['result'] = result
                    else:
                        logger.debug(u"Registering host info against server: %s", result)
                        print(u"Host correctly registered against server %s." % (mywapt.waptserver.server_url,))
                else:
                    print(u"No waptserver defined. Register unavailable")
                    sys.exit(1)

            elif action == 'setlocalpassword':
                if len(args)>=2:
                    pwd = ' '.join(args[1:])
                else:
                    pwd1 = getpass.getpass('Local password: ')
                    pwd = getpass.getpass('Confirm password: ')
                    if pwd1 != pwd:
                        print('ERROR: Passwords not matching')
                        sys.exit(1)
                result = mywapt.set_local_password(
                    user='admin',
                    pwd=pwd.decode(sys.getfilesystemencoding()))
                if options.json_output:
                    jsonresult['result'] = result
                else:
                    print(u"Local auth password set successfully")

            elif action == 'generate-uuid':
                if len(args)>=2:
                    uuid = args[1]
                else:
                    uuid = None
                result = mywapt.generate_host_uuid(forced_uuid=uuid)

                if mywapt.waptserver:
                    mywapt.update_server_status()
                if options.json_output:
                    jsonresult['result'] = result
                else:
                    logger.debug(u"Registering host info against server: %s", result)
                    print(u"New UUID: %s" % (mywapt.host_uuid,))

            elif action == 'reset-uuid':
                result = mywapt.reset_host_uuid()

                if mywapt.waptserver:
                    mywapt.update_server_status()
                if options.json_output:
                    jsonresult['result'] = result
                else:
                    print(u"New UUID: %s" % (mywapt.host_uuid,))

            elif action == 'update-status':
                if mywapt.waptserver:
                    result = mywapt.update_server_status()
                    if result:
                        if options.json_output:
                            jsonresult['result'] = result
                        else:
                            logger.debug(u"Inventory sent to server: %s", result)
                            print(u"Inventory correctly sent to server %s." % (mywapt.waptserver.server_url,))
                    else:
                        print(u"waptserver is not available. Update of status not sent")
                        sys.exit(3)
                else:
                    print(u"No waptserver defined. Update of status unavailable")
                    sys.exit(3)

            elif action == 'inventory':
                if options.json_output:
                    jsonresult['result'] = result
                else:
                    print(jsondump(mywapt.inventory(),indent=True))

            elif action == 'setup-tasks':
                result = mywapt.setup_tasks()
                if options.json_output:
                    jsonresult['result'] = result
                else:
                    print(result)

            elif action == 'add-upgrade-shutdown':
                result = mywapt.add_upgrade_shutdown_policy()
                if options.json_output:
                    jsonresult['result'] = result
                else:
                    print(result)

            elif action == 'remove-upgrade-shutdown':
                result = mywapt.remove_upgrade_shutdown_policy()
                if options.json_output:
                    jsonresult['result'] = result
                else:
                    print(result)

            elif action == 'enable-tasks':
                result = mywapt.enable_tasks()
                if options.json_output:
                    jsonresult['result'] = result
                else:
                    print(result)

            elif action == 'disable-tasks':
                result = mywapt.disable_tasks()
                if options.json_output:
                    jsonresult['result'] = result
                else:
                    print(result)

            elif action == 'list':
                def cb(fieldname,value):
                    if value and fieldname == 'install_date':
                        return value[0:16]
                    else:
                        return value
                result = mywapt.list(args[1:])
                if options.json_output:
                    jsonresult['result'] = result
                else:
                    print(ppdicttable(result,(
                        ('package',20),
                        ('version',15),
                        ('install_status',10),
                        ('install_date',16),
                        ('description',80)),
                        callback=cb))

            elif action == 'get-server-certificate':
                if mywapt.waptserver and mywapt.waptserver_available():
                    result = mywapt.waptserver.save_server_certificate(os.path.join(mywapt.wapt_base_dir,'ssl','server'))
                if options.json_output:
                    jsonresult['result'] = result
                else:
                    print('Server certificate written to %s' % result)

            elif action == 'enable-check-certificate':
                if mywapt.waptserver and mywapt.waptserver_available():
                    result = mywapt.waptserver.save_server_certificate(os.path.join(mywapt.wapt_base_dir,'ssl','server'))
                    setuphelpers.inifile_writestring(mywapt.config_filename,'global','verify_cert',result)
                else:
                    result = ''
                if options.json_output:
                    jsonresult['result'] = result
                else:
                    print('Server certificate written to %s' % result)
                    print('wapt config file updated')

            elif action == 'add-icon':
                if len(args) < 2:
                    print(u"You must provide the package to edit")
                    sys.exit(1)
                if len(args) >= 3:
                    raise NotImplementedError
                    ##result = mywapt.add_iconpng_wapt(
                    ##    package=args[1],
                    ##    iconpath=args[2])
                else:
                    raise NotImplementedError
                    ##result = mywapt.add_iconpng_wapt(package=args[1])
                mywapt.upload_package({
                    'waptfile':result['filename'],
                    'waptdir':'wapt',
                    },
                    wapt_server_user = options.wapt_server_user,
                    wapt_server_passwd=options.wapt_server_passwd)
                if options.json_output:
                    jsonresult['result'] = result
            else:
                print(u'Unknown action %s' % action)
                sys.exit(1)

        except Exception as e:
            print(u"FATAL ERROR : %s" % (ensure_unicode(e),))
            if logger.level == logging.DEBUG:
                raise
            sys.exit(3)

    except SystemExit as e:
        # catch exit code for json output
        if options.json_output:
            jsonresult['exit_code'] = e.code
        raise

    except Exception as e:
        # catch exceptions for json output
        if options.json_output:
            jsonresult['error'] = ensure_unicode(e)
        raise

    finally:
        if options.json_output:
            # restore stdin/stdout
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            # print final result
            print(jsondump(jsonresult,indent=True))

if __name__ == "__main__":
    logger.debug(u'Python path %s' % sys.path)
    main()

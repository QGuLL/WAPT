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

import os
import sys
try:
    wapt_root_dir = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            '..'))
except:
    wapt_root_dir = 'c:/tranquilit/wapt'

sys.path.insert(0, os.path.join(wapt_root_dir))
sys.path.insert(0, os.path.join(wapt_root_dir, 'lib'))
sys.path.insert(0, os.path.join(wapt_root_dir, 'lib', 'site-packages'))

from flask import request, Flask, Response, send_from_directory, session, g, redirect, url_for, abort, render_template, flash
import time
import json
import hashlib
from passlib.hash import sha512_crypt, bcrypt

from peewee import *
from playhouse.postgres_ext import *

from waptserver_model import Hosts,HostSoftwares,HostPackagesStatus,init_db,wapt_db,model_to_dict,dict_to_model

from werkzeug.utils import secure_filename
from functools import wraps
import logging
import ConfigParser
import codecs
import zipfile
import platform
import socket
import requests
import shutil
import subprocess
import tempfile
import traceback
import datetime
import uuid
import email.utils
import collections
import urlparse
import stat
import pefile
import itsdangerous
from rocket import Rocket
import thread
import threading
import Queue
import re

from waptpackage import *
from waptcrypto import *

from waptserver_utils import *
import waptserver_config

import wakeonlan.wol

# i18n
from flask_babel import Babel
try:
    from flask_babel import gettext
except ImportError:
    gettext = (lambda s: s)
_ = gettext


from optparse import OptionParser

# Ensure that any created files have sane permissions.
# uWSGI implicitely sets umask(0).
try:
    os.umask(0o022)
except Exception:
    pass

DEFAULT_CONFIG_FILE = os.path.join(wapt_root_dir, 'conf', 'waptserver.ini')
config_file = DEFAULT_CONFIG_FILE

# If we run under uWSGI, retrieve the config from the same ini file
try:
    import uwsgi
    if uwsgi.magic_table['P']:
        config_file = uwsgi.magic_table['P']
except Exception:
    pass

app = Flask(__name__, static_folder='./templates/static')
app.config['CONFIG_FILE'] = config_file

babel = Babel(app)

conf = waptserver_config.load_config(config_file)

ALLOWED_EXTENSIONS = set(['wapt'])

# setup logging
logger = logging.getLogger()

try:
    import wsus
    app.register_blueprint(wsus.wsus)
except Exception as e:
    logger.info(str(e))
    wsus = False


def get_wapt_exe_version(exe):
    present = False
    version = None
    if os.path.exists(exe):
        present = True
        pe = None
        try:
            pe = pefile.PE(exe)
            version = pe.FileInfo[0].StringTable[
                0].entries['FileVersion'].strip()
            if not version:
                version = pe.FileInfo[0].StringTable[
                    0].entries['ProductVersion'].strip()
        except:
            pass
        if pe is not None:
            pe.close()
    return (present, version)


@app.teardown_appcontext
def close_db(error):
    """Closes the database again at the end of the request."""
    try:
        wapt_db.commit()
    except:
        wapt_db.rollback()

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization

        if not auth:
            logger.info('no credential given')
            return authenticate()

        logging.debug("authenticating : %s" % auth.username)
        if not check_auth(auth.username, auth.password):
            return authenticate()
        logger.info("user %s authenticated" % auth.username)
        return f(*args, **kwargs)
    return decorated


def check_auth(username, password):
    """This function is called to check if a username /
    password combination is valid.
    """

    def any_(l):
        """Check if any element in the list is true, in constant time.
        """
        ret = False
        for e in l:
            if e:
                ret = True
        return ret

    user_ok = False
    pass_sha1_ok = pass_sha512_ok = pass_sha512_crypt_ok = pass_bcrypt_crypt_ok = False

    user_ok = conf['wapt_user'] == username

    pass_sha1_ok = conf['wapt_password'] == hashlib.sha1(
        password.encode('utf8')).hexdigest()
    pass_sha512_ok = conf['wapt_password'] == hashlib.sha512(
        password.encode('utf8')).hexdigest()

    if sha512_crypt.identify(conf['wapt_password']):
        pass_sha512_crypt_ok = sha512_crypt.verify(
            password,
            conf['wapt_password'])
    else:
        try:
            if bcrypt.identify(conf['wapt_password']):
                pass_bcrypt_crypt_ok = bcrypt.verify(
                    password,
                    conf['wapt_password'])
        except Exception:
            pass

    return any_([pass_sha1_ok, pass_sha512_ok,
                 pass_sha512_crypt_ok, pass_bcrypt_crypt_ok]) and user_ok


def authenticate():
    """Sends a 401 response that enables basic auth"""
    return Response(
        _('You have to login with proper credentials'), 401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'})


@babel.localeselector
def get_locale():
    browser_lang = request.accept_languages.best_match(['en', 'fr'])
    user_lang = session.get('lang', browser_lang)
    return user_lang


@app.route('/lang/<language>')
def lang(language=None):
    session['lang'] = language
    return redirect('/')


@babel.timezoneselector
def get_timezone():
    user = getattr(g, 'user', None)
    if user is not None:
        return user.timezone


@app.route('/')
def index():
    waptagent = os.path.join(conf['wapt_folder'], 'waptagent.exe')
    waptsetup = os.path.join(conf['wapt_folder'], 'waptsetup-tis.exe')
    waptdeploy = os.path.join(conf['wapt_folder'], 'waptdeploy.exe')

    agent_status = setup_status = deploy_status = db_status = 'N/A'
    agent_style = setup_style = deploy_style = disk_space_style = 'style="color: red;"'

    setup_present, setup_version = get_wapt_exe_version(waptsetup)
    if setup_present:
        setup_style = ''
        if setup_version is not None:
            setup_status = setup_version
        else:
            setup_status = 'ERROR'

    agent_present, agent_version = get_wapt_exe_version(waptagent)
    agent_sha256 = None
    if agent_present:
        if agent_version is not None:
            agent_status = agent_version
            agent_sha256 = sha256_for_file(waptagent)
            if Version(agent_version) >= Version(setup_version):
                agent_style = ''
        else:
            agent_status = 'ERROR'

    deploy_present, deploy_version = get_wapt_exe_version(waptdeploy)
    if deploy_present:
        deploy_style = ''
        if deploy_version is not None:
            deploy_status = deploy_version
        else:
            deploy_status = 'ERROR'

    try:
        cnt = 'hosts' in wapt_db.get_tables()
        db_status = 'OK (%s hosts)'%cnt
    except Exception as e:
        db_status = 'ERROR'

    try:
        space = get_disk_space(conf['wapt_folder'])
        if not space:
            raise Exception('Disk info not found')
        percent_free = (space[0] * 100) / space[1]
        if percent_free >= 20:
            disk_space_style = ''
        disk_space_str = str(percent_free) + '% free'
    except Exception as e:
        disk_space_str = 'error, %s' % str(e)

    data = {
        'wapt': {
            'server': {'status': __version__},
            'agent': {'status': agent_status, 'style': agent_style, 'sha256': agent_sha256},
            'setup': {'status': setup_status, 'style': setup_style},
            'deploy': {'status': deploy_status, 'style': deploy_style},
            'db': {'status': db_status},
            'disk_space': {'status': disk_space_str, 'style': disk_space_style},
        }
    }

    return render_template("index.html", data=data)


def update_host_data(data):
    """Helper function to insert or update host data in db

    Args :
        data (dict) : data to push in DB with at least 'uuid' key
                        if uuid key already exists, update the data
                        eld insert
                      only keys in data are pushed to DB.
                        Other data (fields) are left untouched
    Returns:
        dict : host data from db after update
    """
    uuid = data['uuid']
    try:
        # simulates an upsert statement based on uuid PK
        try:
            # wapt update_status packages softwares host
            newhost = Hosts()
            for k in data.keys():
                if hasattr(newhost,k):
                    setattr(newhost,k,data[k])

            newhost.save(force_insert=True)
        except IntegrityError as e:
            wapt_db.rollback()
            updhost = Hosts.get(uuid=uuid)
            for k in data.keys():
                if hasattr(updhost,k):
                    setattr(updhost,k,data[k])
            updhost.save()
    except Exception as e:
        logger.critical(u'Error updating data for %s : %s'%(uuid,ensure_unicode(e)))
        wapt_db.rollback()

    result_query = Hosts.select(Hosts.uuid,Hosts.computer_fqdn,Hosts.host_info)
    return result_query.where(Hosts.uuid == uuid).dicts().first(1)


def get_reachable_ip(ips=[], waptservice_port=conf[
                     'waptservice_port'], timeout=conf['clients_connect_timeout']):
    """Try to establish a TCP connection to each IP of ips list on waptservice_port
        return first successful IP

    Args:
        ips (list of str, or str) :
            list of IP to try
            ips is either a single IP, or a list of IP, or a CSV list of IP
        waptservice_port : tcp port to try to connect to
        timeout: connection timeout

    Returns:
        str : first IP which is successful with or empty string if no ip is is successful
    """
    ips = ensure_list(ips)
    for ip in ips:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect((ip, conf['waptservice_port']))
            s.close()
            return ip
        except:
            pass
    return None


@app.route('/add_host', methods=['POST'])
@app.route('/update_host', methods=['POST'])
def update_host():
    """Update localstatus of computer, and return known registration info"""
    try:
        data = json.loads(request.data)
        if data:
            uuid = data["uuid"]
            if uuid:
                logger.info('Update host %s status' % (uuid,))
                data['last_seen_on'] = datetime2isodate()
                db_data = update_host_data(data)
                result = dict(
                    status='OK',
                    message="update_host",
                    result=db_data)

                # check if client is reachable
                if not 'check_hosts_thread' in g or not g.check_hosts_thread.is_alive():
                    logger.info('Creates check hosts thread for %s' % (uuid,))
                    g.check_hosts_thread = CheckHostsWaptService(
                        timeout=conf['clients_connect_timeout'],
                        uuids=[uuid])
                    g.check_hosts_thread.start()
                else:
                    logger.info(
                        'Reuses current check hosts thread for %s' %
                        (uuid,))
                    g.check_hosts_thread.queue.put(data)

            else:
                result = dict(
                    status='ERROR',
                    message="update_host: No uuid supplied")
        else:
            result = dict(
                status='ERROR',
                message="update_host: No data supplied")

    except Exception as e:
        result = dict(
            status='ERROR', message='%s: %s' %
            ('update_host', e), result=None)

    # backward... to fix !
    if result['status'] == 'OK':
        return Response(response=json.dumps(result['result']),
                        status=200,
                        mimetype="application/json")
    else:
        return Response(response=json.dumps(result),
                        status=200,
                        mimetype="application/json")


@app.route('/upload_package/<string:filename>', methods=['POST'])
@requires_auth
def upload_package(filename=""):
    try:
        tmp_target = ''
        if request.method == 'POST':
            if filename and allowed_file(filename):
                tmp_target = os.path.join(
                    conf['wapt_folder'],
                    secure_filename(
                        filename +
                        '.tmp'))
                with open(tmp_target, 'wb') as f:
                    data = request.stream.read(65535)
                    try:
                        while len(data) > 0:
                            f.write(data)
                            data = request.stream.read(65535)
                    except:
                        logger.debug('End of stream')
                        raise

                if not os.path.isfile(tmp_target):
                    result = dict(
                        status='ERROR',
                        message=_('Problem during upload'))
                else:
                    if PackageEntry().load_control_from_wapt(tmp_target):
                        target = os.path.join(
                            conf['wapt_folder'],
                            secure_filename(filename))
                        if os.path.isfile(target):
                            os.unlink(target)
                        os.rename(tmp_target, target)
                        data = update_packages(conf['wapt_folder'])
                        result = dict(
                            status='OK', message='%s uploaded, %i packages analysed' %
                            (filename, len(
                                data['processed'])), result=data)
                    else:
                        result = dict(
                            status='ERROR',
                            message=_('Not a valid wapt package'))
                        os.unlink(tmp_target)
            else:
                result = dict(status='ERROR', message=_('Wrong file type'))
        else:
            result = dict(status='ERROR', message=_('Unsupported method'))
    except:
        # remove temporary
        if os.path.isfile(tmp_target):
            os.unlink(tmp_target)
        e = sys.exc_info()
        logger.critical(repr(traceback.format_exc()))
        result = dict(status='ERROR', message=_('unexpected: {}').format((e,)))
    return Response(response=json.dumps(result),
                    status=200,
                    mimetype="application/json")


@app.route('/upload_host', methods=['POST'])
@requires_auth
def upload_host():
    try:
        file = request.files['file']
        if file:
            logger.debug('uploading host file : %s' % file)
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                wapt_host_folder = os.path.join(conf['wapt_folder'] + '-host')
                tmp_target = os.path.join(wapt_host_folder, filename + '.tmp')
                target = os.path.join(wapt_host_folder, filename)
                file.save(tmp_target)
                if os.path.isfile(tmp_target):
                    try:
                        # try to read attributes...
                        entry = PackageEntry().load_control_from_wapt(
                            tmp_target)
                        if os.path.isfile(target):
                            os.unlink(target)
                        os.rename(tmp_target, target)
                        data = update_packages(wapt_host_folder)
                        result = dict(
                            status='OK',
                            message=_('File {} uploaded to {}').format(
                                file.filename,
                                target))
                    except:
                        if os.path.isfile(tmp_target):
                            os.unlink(tmp_target)
                        raise
                else:
                    result = dict(
                        status='ERROR',
                        message=_('No data received'))
            else:
                result = dict(status='ERROR', message=_('Wrong file type'))
        else:
            result = dict(
                status='ERROR',
                message=_('No package file provided in request'))
    except:
        # remove temporary
        if os.path.isfile(tmp_target):
            os.unlink(tmp_target)
        e = sys.exc_info()
        logger.critical(repr(traceback.format_exc()))
        result = dict(status='ERROR', message='upload_host: %s' % (e,))
    return Response(response=json.dumps(result),
                    status=200,
                    mimetype="application/json")


@app.route('/upload_waptsetup', methods=['POST'])
@requires_auth
def upload_waptsetup():
    waptagent = os.path.join(conf['wapt_folder'], 'waptagent.exe')
    waptsetup = os.path.join(conf['wapt_folder'], 'waptsetup-tis.exe')

    logger.debug("Entering upload_waptsetup")
    tmp_target = None
    try:
        if request.method == 'POST':
            file = request.files['file']
            if file and "waptagent.exe" in file.filename:
                filename = secure_filename(file.filename)
                tmp_target = os.path.join(
                    conf['wapt_folder'],
                    secure_filename(
                        '.' +
                        filename))
                target = os.path.join(
                    conf['wapt_folder'],
                    secure_filename(filename))
                file.save(tmp_target)
                if not os.path.isfile(tmp_target):
                    result = dict(
                        status='ERROR',
                        message=_('Problem during upload'))
                else:
                    os.rename(tmp_target, target)
                    result = dict(
                        status='OK', message=_('{} uploaded').format(
                            (filename,)))

                # Compat with older clients: provide a waptsetup.exe ->
                # waptagent.exe alias
                if os.path.exists(waptsetup):
                    if not os.path.exists(waptsetup + '.old'):
                        try:
                            os.rename(waptsetup, waptsetup + '.old')
                        except:
                            pass
                    try:
                        os.unlink(waptsetup)
                    except:
                        pass
                try:
                    os.symlink(waptagent, waptsetup)
                except:
                    shutil.copyfile(waptagent, waptsetup)

            else:
                result = dict(
                    status='ERROR',
                    message=_('Wrong file name (version conflict?)'))
        else:
            result = dict(status='ERROR', message=_('Unsupported method'))
    except:
        e = sys.exc_info()
        if tmp_target and os.path.isfile(tmp_target):
            os.unlink(tmp_target)
        result = dict(status='ERROR', message=_('unexpected: {}').format((e,)))
    return Response(response=json.dumps(result),
                    status=200,
                    mimetype="application/json")


def install_wapt(computer_name, authentication_file):
    cmd = '/usr/bin/smbclient -G -E -A %s  //%s/IPC$ -c listconnect ' % (
        authentication_file, computer_name)
    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True)
    except subprocess.CalledProcessError as e:
        if "NT_STATUS_LOGON_FAILURE" in e.output:
            raise Exception(_("Incorrect credentials."))
        if "NT_STATUS_CONNECTION_REFUSED" in e.output:
            raise Exception(_("Couldn't access IPC$ share."))

        raise Exception(u"%s" % e.output)

    cmd = '/usr/bin/smbclient -A "%s" //%s/c\\$ -c "put waptagent.exe" ' % (
        authentication_file, computer_name)
    print(subprocess.check_output(cmd, shell=True))

    cmd = '/usr/bin/winexe -A "%s"  //%s  "c:\\waptagent.exe  /MERGETASKS=""useWaptServer"" /VERYSILENT"  ' % (
        authentication_file, computer_name)
    print(subprocess.check_output(cmd, shell=True))

    cmd = '/usr/bin/winexe -A "%s"  //%s  "c:\\wapt\\wapt-get.exe register"' % (
        authentication_file, computer_name)
    print(subprocess.check_output(cmd, shell=True))

    cmd = '/usr/bin/winexe -A "%s"  //%s  "c:\\wapt\\wapt-get.exe --version"' % (
        authentication_file, computer_name)
    return subprocess.check_output(cmd, shell=True)


@app.route('/deploy_wapt', methods=['POST'])
@requires_auth
def deploy_wapt():
    try:
        result = {}
        if platform.system() != 'Linux':
            raise Exception(_('WAPT server must be run on Linux.'))
        if subprocess.call('which smbclient', shell=True) != 0:
            raise Exception(_("smbclient installed on WAPT server."))
        if subprocess.call('which winexe', shell=True) != 0:
            raise Exception(_("winexe is not installed on WAPT server."))

        if request.method == 'POST':
            d = json.loads(request.data)
            if 'auth' not in d:
                raise Exception(_("Credentials are missing."))
            if 'computer_fqdn' not in d:
                raise Exception(_("There are no registered computers."))

            auth_file = tempfile.mkstemp("wapt")[1]
            try:
                with open(auth_file, 'w') as f:
                    f.write('username = %s\npassword = %s\ndomain = %s\n' % (
                        d['auth']['username'],
                        d['auth']['password'],
                        d['auth']['domain']))

                os.chdir(conf['wapt_folder'])

                message = install_wapt(d['computer_fqdn'], auth_file)

                result = {'status': 'OK', 'message': message}
            finally:
                os.unlink(auth_file)

        else:
            raise Exception(_("Unsupported HTTP method."))

    except Exception as e:
        result = {'status': 'ERROR', 'message': u"%s" % e}

    return Response(response=json.dumps(result),
                    status=200,
                    mimetype="application/json")


def rewrite_config_item(cfg_file, *args):
    config = ConfigParser.RawConfigParser()
    config.read(cfg_file)
    config.set(*args)
    with open(cfg_file, 'wb') as cfg:
        config.write(cfg)

# Reload config file.
# On Rocket we rely on inter-threads synchronization,
# thus the variable you want to sync MUST be declared as a *global*
# On Unix we ask uwsgi to perform a graceful restart.


def reload_config():
    if os.name == "posix":
        try:
            import uwsgi
            uwsgi.reload()
        except ImportError:
            pass


@app.route('/login', methods=['POST'])
def login():
    config_file = app.config['CONFIG_FILE']

    try:
        if request.method == 'POST':
            d = json.loads(request.data)
            if "username" in d and "password" in d:
                if check_auth(d["username"], d["password"]):
                    if "newPass" in d:
                        new_hash = hashlib.sha1(
                            d["newPass"].encode('utf8')).hexdigest()
                        rewrite_config_item(
                            config_file,
                            'options',
                            'wapt_password',
                            new_hash)
                        conf['wapt_password'] = new_hash
                        reload_config()
                    return "True"
            return "False"
        else:
            return "Unsupported method"
    except:
        e = sys.exc_info()
        return str(e)


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1] in ALLOWED_EXTENSIONS


@app.route('/delete_package/<string:filename>')
@requires_auth
def delete_package(filename=""):
    fullpath = os.path.join(conf['wapt_folder'], filename)
    try:
        if os.path.isfile(fullpath):
            os.unlink(fullpath)
            data = update_packages(conf['wapt_folder'])
            if os.path.isfile("%s.zsync" % (fullpath,)):
                os.unlink("%s.zsync" % (fullpath,))
            result = dict(
                status='OK', message="Package deleted %s" %
                (fullpath,), result=data)
        else:
            result = dict(
                status='ERROR', message="The file %s doesn't exist in wapt folder (%s)" %
                (filename, conf['wapt_folder']))

    except Exception as e:
        result = {'status': 'ERROR', 'message': u"%s" % e}

    return Response(response=json.dumps(result),
                    status=200,
                    mimetype="application/json")


@app.route('/wapt/')
def wapt_listing():
    return render_template(
        'listing.html', dir_listing=os.listdir(conf['wapt_folder']))


@app.route('/waptwua/')
def waptwua():
    return render_template(
        'listingwua.html', dir_listing=os.listdir(waptwua_folder))


@app.route('/wapt/<string:input_package_name>')
def get_wapt_package(input_package_name):
    package_name = secure_filename(input_package_name)
    r = send_from_directory(conf['wapt_folder'], package_name)
    if 'content-length' not in r.headers:
        r.headers.add_header(
            'content-length', int(os.path.getsize(os.path.join(conf['wapt_folder'], package_name))))
    return r


@app.route('/wapt/icons/<string:iconfilename>')
def serve_icons(iconfilename):
    """Serves a png icon file from /wapt/icons/ test waptserver"""
    iconfilename = secure_filename(iconfilename)
    icons_folder = os.path.join(conf['wapt_folder'], 'icons')
    r = send_from_directory(icons_folder, iconfilename)
    if 'content-length' not in r.headers:
        r.headers.add_header(
            'content-length', int(os.path.getsize(os.path.join(icons_folder, iconfilename))))
    return r

@app.route('/css/<string:fn>')
@app.route('/fonts/<string:fn>')
@app.route('/img/<string:fn>')
@app.route('/js/<string:fn>')
def serve_static(fn):
    """Serve"""
    rootdir = os.path.join(app.template_folder,request.path.split('/')[1])
    if fn is not None:
        fn = secure_filename(fn)
        r = send_from_directory(rootdir, fn)
        if 'content-length' not in r.headers:
            r.headers.add_header(
                'content-length', int(os.path.getsize(os.path.join(rootdir, fn))))
        return r


@app.route('/wapt-host/<string:input_package_name>')
def get_host_package(input_package_name):
    """Returns a host package (in case there is no apache static files server)"""
    # TODO straighten this -host stuff
    host_folder = conf['wapt_folder'] + '-host'
    package_name = secure_filename(input_package_name)
    r = send_from_directory(host_folder, package_name)
    if 'Content-Length' not in r.headers:
        r.headers.add_header(
            'Content-Length', int(os.path.getsize(os.path.join(host_folder, package_name))))
    return r


@app.route('/wapt-group/<string:input_package_name>')
def get_group_package(input_package_name):
    """Returns a group package (in case there is no apache static files server)"""
    # TODO straighten this -group stuff
    group_folder = conf['wapt_folder'] + '-group'
    package_name = secure_filename(input_package_name)
    r = send_from_directory(group_folder, package_name)
    # on line content-length is not added to the header.
    if 'content-length' not in r.headers:
        r.headers.add_header(
            'content-length',
            os.path.getsize(
                os.path.join(
                    group_folder +
                    '-group',
                    package_name)))
    return r


def get_ip_port(host_data, recheck=False, timeout=None, check_ping=False):
    """Return a dict protocol,address,port,timestamp for the supplied registered host
        - first check if wapt.listening_address is ok and recheck is False
        - if not present or recheck is True, check each of host.check connected_ips list with timeout

    Args:
        host_data (dict):  host registration data with at least
            wapt.listening_address.address
            wapt.waptservice_port
            host.connected_ips

        recheck: force recheck even if listening_address
        timeout (int) : http timeout, or socket connection timeout
        check_ping (bool) : if True, check using http://host/ping else just check socket connection

    Returns;
        dict with keys:
            protocol
            address
            port
            timestamp


    """
    if not timeout:
        timeout = conf['clients_connect_timeout']
    if not host_data or not 'uuid' in host_data:
        raise EWaptUnknownHost(_('Unknown uuid'))

    if not recheck and host_data.get('listening_address',None):
        # use data stored in DB
        return dict(
            protocol=host_data.get('listening_protocol', 'http'),
            address=host_data.get('listening_address',None),
            port=host_data.get('listening_port',8088),
            timestamp=host_data.get('listening_timestamp',None),
            )
    elif host_data.get('wapt_status',None) and host_data.get('host_info',{}).get('connected_ips',''):
        # check using http
        ips = ensure_list(host_data.get('host_info',{}).get('connected_ips',''))
        protocol = host_data['wapt_status'].get('waptservice_protocol', 'http')
        port = host_data['wapt_status'].get('waptservice_port',conf['waptservice_port'])
        address = None

        if check_ping:
            for ip in ips:
                try:
                    req = requests.head('%s://%s:%s/ping?uuid=%s'%(protocol,ip,port,host_data.get('uuid',None)),
                            proxies = {'http':None,'https':None},
                            verify=False,
                            timeout=timeout,
                            )
                    req.raise_for_status()
                    address = ip
                    break
                except:
                    pass
        # optionnally try socket
        else:
            address = get_reachable_ip(
                    ips,
                    waptservice_port=port,
                    timeout=timeout)

        return dict(
            protocol=protocol,
            address=address,
            port=port,
            timestamp=datetime2isodate(),
            )
    else:
        raise EWaptHostUnreachable(
            _('No reachable IP for {}').format(
                host_data['uuid']))


@app.route('/ping')
def ping():
    config_file = app.config['CONFIG_FILE']

    if conf['server_uuid'] == '':
        server_uuid = str(uuid.uuid1())
        rewrite_config_item(config_file, 'options', 'server_uuid', server_uuid)
        conf['server_uuid'] = server_uuid
        reload_config()
    return make_response(
        msg=_('WAPT Server running'), result=dict(
            version=__version__,
            api_root='/api/',
            api_version='v1',
            uuid=conf['server_uuid'],
            date=datetime2isodate(),
        )
    )


@app.route('/api/v1/trigger_reachable_discovery',methods=['GET','POST'])
@requires_auth
def trigger_reachable_discovery():
    """Launch a separate thread to check all reachable IP and update database with results.
    """
    try:
        # check if client is reachable
        if 'check_hosts_thread' in g:
            if not g.check_hosts_thread.is_alive():
                del(g.check_hosts_thread)
        g.check_hosts_thread = CheckHostsWaptService(
            timeout=conf['clients_connect_timeout'])
        # in case a POST is issued with a selection of uuids to scan.
        g.check_hosts_thread.uuids = request.json.get('uuids',None) or None

        g.check_hosts_thread.start()
        message = _(u'Hosts scan launched')
        result = dict(thread_ident=g.check_hosts_thread.ident)

    except Exception as e:
        return make_response_from_exception(e)
    return make_response(result, msg=message)


@app.route('/api/v1/host_reachable_ip')
@requires_auth
def host_reachable_ip():
    """Check if supplied host's waptservice can be reached
            param uuid : host uuid
    """
    try:
        try:
            uuid = request.args['uuid']
            host_data = Hosts\
                        .select(Hosts.uuid,Hosts.computer_fqdn,Hosts.wapt,
                                Hosts.listening_address,
                                Hosts.listening_port,
                                Hosts.listening_protocol,
                                Hosts.listening_timestamp,
                                 )\
                        .where(Hosts.uuid==uuid)\
                        .dicts()\
                        .first(1)
            result = get_ip_port(host_data)
            Hosts.update(
                    listening_protocol=result['protocol'],
                    listening_address=result['address'],
                    listening_port=int(result['port']),
                    listening_timestamp=result['timestamp'],
                ).where(Hosts.uuid == uuid).execute()
        except Exception as e:
            raise EWaptHostUnreachable(
                _("Couldn't connect to web service : {}.").format(e))

    except Exception as e:
        return make_response_from_exception(e)
    return make_response(result)


def proxy_host_request(request, action):
    """Proxy the wapt forget action to the client
            uuid
            packages
            notify_user
            notify_server
    """
    try:
        all_args = {k: v for k, v in request.args.iteritems()}
        if request.json:
            all_args.update(request.json)

        uuids = ensure_list(all_args['uuid'])
        del(all_args['uuid'])

        result = dict(success=[], errors=[])
        for uuid in uuids:
            try:
                host_data = Hosts\
                        .select(Hosts.uuid,Hosts.computer_fqdn,Hosts.wapt,
                                Hosts.listening_address,
                                Hosts.listening_port,
                                Hosts.listening_protocol,
                                Hosts.listening_timestamp,
                                 )\
                        .where(Hosts.uuid==uuid)\
                        .dicts()\
                        .first(1)
                listening_address = get_ip_port(host_data)
                msg = u''
                if listening_address and listening_address['address'] and listening_address['port']:
                    logger.info(
                        "Launching %s with args %s for %s at address %s..." %
                        (action, all_args, uuid, listening_address['address']))
                    args = dict(all_args)
                    args.update(listening_address)
                    args['uuid'] = uuid
                    args['action'] = action
                    args_url = []
                    for (key, value) in args.iteritems():
                        if isinstance(value, list):
                            args_url.append('%s=%s' % (key, ','.join(value)))
                        else:
                            args_url.append('%s=%s' % (key, value))
                    args['args_url'] = '&'.join(args_url)

                    client_result = requests.get(
                        "%(protocol)s://%(address)s:%(port)d/%(action)s?%(args_url)s" %
                        args,
                        proxies={
                            'http': None,
                            'https': None},
                        verify=False,
                        timeout=conf['clients_read_timeout'],
                        ).text
                    try:
                        client_result = json.loads(client_result)
                        if not isinstance(client_result, list):
                            client_result = [client_result]
                        msg = _(u"Triggered tasks: {}").format(
                            ','.join(
                                t['description'] for t in client_result))
                        result['success'].append(
                            dict(
                                uuid=uuid,
                                msg=msg,
                                computer_fqdn=host_data['computer_fqdn']))
                    except ValueError:
                        if 'Restricted access' in client_result:
                            raise EWaptForbiddden(client_result)
                        else:
                            raise Exception(client_result)
            except Exception as e:
                result['errors'].append(
                    dict(
                        uuid=uuid,
                        msg='%s' %
                        e,
                        computer_fqdn=host_data['computer_fqdn'],
                        )
                    )

        msg = [
            'Success : %s, Errors: %s' %
            (len(
                result['success']), len(
                result['errors']))]
        if result['errors']:
            msg.extend(['%s: %s' % (e['computer_fqdn'], e['msg'])
                        for e in result['errors']])

        return make_response(result,
                             msg='\n- '.join(msg),
                             success=True)
    except Exception as e:
        return make_response_from_exception(e)


@app.route('/api/v1/trigger_upgrade')
@requires_auth
def trigger_upgrade():
    """Proxy the wapt upgrade action to the client"""
    try:
        uuid = request.args['uuid']
        notify_user = request.args.get('notify_user', 0)
        notify_server = request.args.get('notify_server', 1)
        host_data = Hosts\
                        .select(Hosts.uuid,Hosts.computer_fqdn,Hosts.wapt,
                                Hosts.listening_address,
                                Hosts.listening_port,
                                Hosts.listening_protocol,
                                Hosts.listening_timestamp,
                                 )\
                        .where(Hosts.uuid==uuid)\
                        .dicts()\
                        .first(1)
        listening_address = get_ip_port(host_data)
        msg = u''
        if listening_address and listening_address[
                'address'] and listening_address['port']:
            logger.info(
                "Triggering upgrade for %s at address %s..." %
                (uuid, listening_address['address']))
            args = {}
            args.update(listening_address)
            args['uuid'] = uuid
            args['notify_user'] = notify_user
            args['notify_server'] = notify_server
            client_result = requests.get(
                "%(protocol)s://%(address)s:%(port)d/upgrade.json?notify_user=%(notify_user)s&notify_server=%(notify_server)s&uuid=%(uuid)s" %
                args,
                proxies={
                    'http': None,
                    'https': None},
                verify=False,
                timeout=conf['clients_read_timeout']).text
            try:
                client_result = json.loads(client_result)
                result = client_result['content']
                if len(result) <= 1:
                    msg = _(u"Nothing to upgrade.")
                else:
                    packages = [t['description']
                                for t in result if t['classname'] != 'WaptUpgrade']
                    msg = _(u"Triggered {} task(s):\n{}").format(
                        len(packages),
                        '\n'.join(packages))
            except ValueError:
                if 'Restricted access' in client_result:
                    raise EWaptForbiddden(client_result)
                else:
                    raise Exception(client_result)
        else:
            raise EWaptMissingHostData(_("The WAPT service is unreachable."))
        return make_response(result,
                             msg=msg,
                             success=client_result['result'] == 'OK',)
    except Exception as e:
        return make_response_from_exception(e)


@app.route('/api/v1/trigger_update')
@requires_auth
def trigger_update():
    """Proxy the wapt update action to the client"""
    try:
        uuid = request.args['uuid']
        notify_user = request.args.get('notify_user', 0)
        notify_server = request.args.get('notify_server', 1)

        host_data = Hosts\
                        .select(Hosts.uuid,Hosts.computer_fqdn,Hosts.wapt,
                                Hosts.listening_address,
                                Hosts.listening_port,
                                Hosts.listening_protocol,
                                Hosts.listening_timestamp,
                                 )\
                        .where(Hosts.uuid==uuid)\
                        .dicts()\
                        .first(1)
        listening_address = get_ip_port(host_data)
        msg = u''
        if listening_address and listening_address[
                'address'] and listening_address['port']:
            logger.info(
                "Triggering update for %s at address %s..." %
                (uuid, listening_address['address']))
            args = {}
            args.update(listening_address)
            args['notify_user'] = notify_user
            args['notify_server'] = notify_server
            args['uuid'] = uuid
            client_result = requests.get(
                "%(protocol)s://%(address)s:%(port)d/update.json?notify_user=%(notify_user)s&notify_server=%(notify_server)s&uuid=%(uuid)s" %
                args,
                proxies={
                    'http': None,
                    'https': None},
                verify=False,
                timeout=conf['clients_read_timeout']).text
            try:
                client_result = json.loads(client_result)
                msg = _(u"Triggered task: {}").format(
                    client_result['description'])
            except ValueError:
                if 'Restricted access' in client_result:
                    raise EWaptForbiddden(client_result)
                else:
                    raise Exception(client_result)
        else:
            raise EWaptMissingHostData(_("The WAPT service is unreachable."))
        return make_response(client_result,
                             msg=msg,
                             success=True)
    except Exception as e:
        return make_response_from_exception(e)


@app.route('/api/v2/trigger_wakeonlan')
@requires_auth
def trigger_wakeonlan():
    try:
        uuid = request.args['uuid']
        host_data = Hosts\
                        .select(Hosts.uuid,Hosts.computer_fqdn,Hosts.wapt,Hosts.host_info)\
                        .where(Hosts.uuid==uuid)\
                        .first(1)
        macs = host_data['host_info']['mac']
        msg = u''
        if macs:
            logger.info(
                _("Sending magic wakeonlan packets to {} for machine {}").format(
                    macs,
                    host_data.computer_fqdn))
            wakeonlan.wol.send_magic_packet(*macs)
            for line in host_data['host_info']['networking']:
                if 'broadcast' in line:
                    broadcast = line['broadcast']
                    wakeonlan.wol.send_magic_packet(
                        *
                        macs,
                        ip_address='%s' %
                        broadcast)
            msg = _(u"Wakeonlan packets sent to {} for machine {}").format(
                macs,
                host_data.computer_fqdn)
            result = dict(
                macs=macs,
                host=host_data.computer_fqdn,
                uuid=uuid)
        else:
            raise EWaptMissingHostData(
                _("No MAC address found for this host in database"))
        return make_response(result,
                             msg=msg,
                             success=True)
    except Exception as e:
        return make_response_from_exception(e)


@app.route('/api/v2/trigger_host_inventory', methods=['GET', 'POST'])
@requires_auth
def trigger_host_inventory():
    """Proxy the wapt update action to the client"""
    return proxy_host_request(request, 'register.json')


@app.route('/api/v2/trigger_waptwua_scan', methods=['GET', 'POST'])
@requires_auth
def trigger_waptwua_scan():
    """Proxy the wapt update action to the client"""
    return proxy_host_request(request, 'waptwua_scan.json')


@app.route('/api/v2/trigger_waptwua_download', methods=['GET', 'POST'])
@requires_auth
def trigger_waptwua_download():
    """Proxy the wapt download action to the client"""
    return proxy_host_request(request, 'waptwua_download.json')


@app.route('/api/v2/trigger_waptwua_install', methods=['GET', 'POST'])
@requires_auth
def trigger_waptwua_install():
    """Proxy the wapt scan action to the client"""
    return proxy_host_request(request, 'waptwua_install.json')


@app.route('/api/v2/waptagent_version')
@requires_auth
def waptagent_version():
    try:
        start = time.time()
        waptagent = os.path.join(conf['wapt_folder'], 'waptagent.exe')
        agent_present, agent_version = get_wapt_exe_version(waptagent)
        waptagent_timestamp = None
        agent_sha256 = None
        if agent_present and agent_version is not None:
            agent_sha256 = sha256_for_file(waptagent)
            waptagent_timestamp = datetime2isodate(
                datetime.datetime.fromtimestamp(
                    os.path.getmtime(waptagent)))

        waptsetup = os.path.join(conf['wapt_folder'], 'waptsetup-tis.exe')
        setup_present, setup_version = get_wapt_exe_version(waptsetup)
        waptsetup_timestamp = None
        if setup_present and setup_version is not None:
            waptsetup_timestamp = datetime2isodate(
                datetime.datetime.fromtimestamp(
                    os.path.getmtime(waptsetup)))

        if agent_present and setup_present and Version(
                agent_version) >= Version(setup_version):
            msg = 'OK : waptagent.exe %s >= waptsetup %s' % (
                agent_version, setup_version)
        elif agent_present and setup_present and Version(agent_version) < Version(setup_version):
            msg = 'Problem : waptagent.exe %s is older than waptsetup %s, and must be regenerated.' % (
                agent_version, setup_version)
        elif not agent_present and setup_present:
            msg = 'Problem : waptagent.exe not found. It should be compiled from waptconsole.'
        elif not setup_present:
            msg = 'Problem : waptsetup-tis.exe not found on repository.'

        result = dict(
            waptagent_version=agent_version,
            waptagent_sha256=agent_sha256,
            waptagent_timestamp=waptagent_timestamp,
            waptsetup_version=setup_version,
            waptsetup_timestamp=waptsetup_timestamp,
            request_time=time.time() - start,
        )
    except Exception as e:
        return make_response_from_exception(e)

    return make_response(result=result, msg=msg, status=200)


@app.route('/api/v1/host_forget_packages', methods=['GET', 'POST'])
@requires_auth
def host_forget_packages():
    """Proxy the wapt forget action to the client
            uuid
            packages
            notify_user
            notify_server
    """
    return proxy_host_request(request, 'forget.json')


@app.route('/api/v1/host_remove_packages', methods=['GET', 'POST'])
@requires_auth
def host_remove_packages():
    """Proxy the wapt remove action to the client
            uuid
            packages
            notify_user
            notify_server
            force
    """
    return proxy_host_request(request, 'remove.json')


@app.route('/api/v1/host_install_packages', methods=['GET', 'POST'])
@requires_auth
def host_install_packages():
    """Proxy the wapt install action to the client
            uuid
            packages
            notify_user
            notify_server
    """
    return proxy_host_request(request, 'install.json')


@app.route('/api/v1/host_tasks_status')
@requires_auth
def host_tasks_status():
    """Proxy the get tasks status action to the client"""
    try:
        uuid = request.args['uuid']
        host_data = Hosts\
                    .select(Hosts.uuid,Hosts.computer_fqdn,Hosts.wapt,
                            Hosts.listening_address,
                            Hosts.listening_port,
                            Hosts.listening_protocol,
                            Hosts.listening_timestamp,
                             )\
                    .where(Hosts.uuid==uuid)\
                    .dicts()\
                    .first(1)
        listening_address = get_ip_port(host_data)
        if listening_address and listening_address[
                'address'] and listening_address['port']:
            logger.info(
                "Get tasks status for %s at address %s..." %
                (uuid, listening_address['address']))
            args = {}
            args.update(listening_address)
            args['uuid'] = uuid
            client_result = requests.get(
                "%(protocol)s://%(address)s:%(port)d/tasks.json?uuid=%(uuid)s" %
                args,
                proxies={
                    'http': None,
                    'https': None},
                verify=False,
                timeout=conf['client_tasks_timeout']).text
            try:
                client_result = json.loads(client_result)
            except ValueError:
                if 'Restricted access' in client_result:
                    raise EWaptForbiddden(client_result)
                else:
                    raise Exception(client_result)
        else:
            raise EWaptMissingHostData(
                _("The host reachability is not defined."))
        return make_response(client_result,
                             msg="Tasks status retrieved properly",
                             success=isinstance(client_result, dict),)
    except Exception as e:
        return make_response_from_exception(e)


@app.route('/api/v1/groups')
@requires_auth
def get_groups():
    """List of packages having section == group
    """
    try:
        packages = WaptLocalRepo(conf['wapt_folder'])
        groups = [p.as_dict()
                  for p in packages.packages if p.section == 'group']
        msg = '{} Packages for section group'.format(len(groups))

    except Exception as e:
        return make_response_from_exception(e)

    return make_response(result=groups, msg=msg, status=200)

def build_hosts_filter(model,filter_expr):
    """Legacy helper function to translate waptconsole <=1.3.11 hosts filter
        into peewee model where clause.
    Args:
        filter_dict (str) : field1,field4,field5:search_regexp
    """
    (search_fields, search_expr) = filter_expr.split(':', 1)
    if search_expr.startswith('not ') or search_expr.startswith('!'):
        not_filter = 1
        if search_expr.startswith('not '):
            search_expr = search_expr.split(' ', 1)[1]
        else:
            search_expr = search_expr[1:]
    else:
        not_filter = 0

    if search_fields.strip() and search_expr.strip():
        result = None
        for fn in ensure_list(search_fields):
            members = fn.split('.')
            rootfield = members[0]
            if rootfield in model._meta.fields:
                if isinstance(model._meta.fields[rootfield],(JSONField,BinaryJSONField)):
                    if len(members)==1:
                        clause =  SQL("%s::text ~* '%s'" % (fn,search_expr))
                    else:
                        # (wapt->'waptserver'->'dnsdomain')::text ~* 'asfrance.lan'
                        clause = SQL("(%s->%s)::text ~* '%s'" % (rootfield,'->'.join(["'%s'" % f for f in members[1:]]),search_expr))
                        # model._meta.fields[members[0]].path(members[1:]).regexp(ur'(?i)%s' % search_expr)
                elif isinstance(model._meta.fields[rootfield],ArrayField):
                    clause = SQL("%s::text ~* '%s'" % (fn,search_expr))
                else:
                    clause = model._meta.fields[fn].regexp(ur'(?i)%s' % search_expr)
            # else ignored...

            if result is None:
                result = clause
            else:
                result = result | clause
        if not_filter:
            result = ~result
        return result
    else:
        raise Exception('Invalid filter provided in query. Should be f1,f2,f3:regexp ')


@app.route('/api/v1/hosts', methods=['DELETE'])
@app.route('/api/v1/hosts_delete', methods=['GET', 'POST'])
@requires_auth
def hosts_delete():
    """Remove one or several hosts from Server DB and optionnally the host packages

    Args:
        delete_packages: [0,1]: delete host's packages too
        uuid (csvlist of uuid): <uuid1[,uuid2,...]>): filter based on uuid
        filter (csvlist of field:regular expression): filter based on attributes

    Returns:
        result (dict): {'records':[],'files':[]}

    """
    try:
        # build filter
        if 'uuid' in request.args:
            query = Hosts.uuid.in_(ensure_list(request.args['uuid']))
        elif 'filter' in request.args:
            query = build_hosts_filter(request.args['filter'])
        else:
            raise Exception('Neither uuid nor filter provided in query')

        msg = []
        result = dict(files=[], records=[])

        hosts_packages_repo = WaptLocalRepo(conf['wapt_folder'] + '-host')
        packages_repo = WaptLocalRepo(conf['wapt_folder'])

        if 'delete_packages' in request.args and request.args[
                'delete_packages'] == '1':
            selected = Hosts.select(Hosts.uuid,Hosts.computer_fqdn).where(query)
            for host in selected:
                result['records'].append(
                    dict(
                        uuid=host.uuid,
                        computer_fqdn=host.computer_fqdn))
                if host.computer_fqdn in hosts_packages_repo:
                    fn = hosts_packages_repo[host.computer_fqdn].wapt_fullpath()
                    logger.debug('Trying to remove %s' % fn)
                    if os.path.isfile(fn):
                        result['files'].append(fn)
                        os.remove(fn)
            msg.append(
                '{} files removed from host repository'.format(len(result['files'])))

        remove_result = Hosts.delete().where(query).execute()
        msg.append('{} hosts removed from DB'.format(remove_result))

    except Exception as e:
        wapt_db.rollback()
        return make_response_from_exception(e)

    return make_response(result=result, msg='\n'.join(msg), status=200)


def build_fields_list(model,mongoproj):
    """Returns a list of peewee fields based on a mongo style projection
            For compatibility with waptconsole <= 1.3.11
    """
    result =[]
    for fn in mongoproj.keys():
        if fn in model._meta.fields:
            result.append(model._meta.fields[fn])
        else:
            # jsonb sub fields.
            parts = fn.split('.')
            root = parts[0]
            if root in model._meta.fields:
                path = ','.join(parts[1:])
                result.append(SQL("%s #>>'{%s}' as \"%s\" "%(root,path,fn.replace('.','-'))))
    return result


@app.route('/api/v1/hosts', methods=['GET'])
@requires_auth
def get_hosts():
    """Get registration data of one or several hosts

    Args:
        has_errors (0/1): filter out hosts with packages errors
        need_upgrade (0/1): filter out hosts with outdated packages
        groups (csvlist of packages) : hosts with packages
        columns (csvlist of columns) :
        uuid (csvlist of uuid): <uuid1[,uuid2,...]>): filter based on uuid
        filter (csvlist of field):regular expression: filter based on attributes
        not_filter (0,1):
        limit (int) : 1000

    Returns:
        result (dict): {'records':[],'files':[]}

        query:
          uuid=<uuid>
        or
          filter=<csvlist of fields>:regular expression
    """
    try:
        start_time = time.time()
        default_columns = ['host_status',
                           'last_update_status',
                           'reachable',
                           'computer_fqdn',
                           'dnsdomain',
                           'description',
                           'connected_users',
                           'listening_protocol',
                           'listening_address',
                           'listening_port',
                           'listening_timestamp',
                           'manufacturer',
                           'productname',
                           'serialnr',
                           'last_seen_on',
                           'mac_addresses',
                           'connected_ips',
                           'wapt_status',
                           'uuid',
                           'md5sum',
                           'purchase_order',
                           'purchase_date',
                           'groups',
                           'attributes',
                           'host.domain_controller',
                           'host.domain_name',
                           'host.domain_controller_address',
                           'depends',
                           'computer_type',
                           'os_name',
                           'os_version',]

        # keep only top tree nodes (mongo doesn't want fields like {'wapt':1,'wapt.listening_address':1} !
        # minimum columns
        columns = ['uuid',
                       'host_status',
                       'last_seen_on',
                       'last_update_status',
                       'computer_fqdn',
                       'computer_name',
                       'description',
                       'wapt_status',
                       'dnsdomain',
                       'listening_protocol',
                       'listening_address',
                       'listening_port',
                       'listening_timestamp',
                       'connected_users']
        other_columns = ensure_list(
            request.args.get(
                'columns',
                default_columns))

        # add request columns
        for fn in other_columns:
            if not fn in columns:
                columns.append(fn)

        # remove children
        columns_tree = sorted([c.split('.') for c in columns])
        last = None
        new_tree = []
        for col in columns_tree:
            if last is None or col[:len(last)] != last:
                new_tree.append(col)
                last = col

        columns = ['.'.join(c) for c in new_tree]

        not_filter = request.args.get('not_filter', 0)

        query = None

        # build filter
        if 'uuid' in request.args:
            query = Hosts.uuid.in_(ensure_list(request.args['uuid']))
        elif 'filter' in request.args:
            query = build_hosts_filter(Hosts,request.args['filter'])
        else:
            query = ~(Hosts.uuid.is_null())

        if 'has_errors' in request.args and request.args['has_errors']:
            query = query & (Hosts.host_status == 'ERROR')
        if "need_upgrade" in request.args and request.args['need_upgrade']:
            query = query & (Hosts.host_status.in_(['ERROR','TO_UPGRADE']))

        if not_filter:
            query = ~ query

        limit = int(request.args.get('limit',1000))

        hosts_packages_repo = WaptLocalRepo(conf['wapt_folder'] + '-host')
        packages_repo = WaptLocalRepo(conf['wapt_folder'])

        groups = ensure_list(request.args.get('groups', ''))

        result = []
        req = Hosts.select(*build_fields_list(Hosts,{col: 1 for col in columns})).limit(limit).order_by(-Hosts.last_seen_on).dicts().dicts()
        if query:
            req = req.where(query)

        for host in req:

            if (('depends' in columns) or len(groups) >
                    0) and host.get('computer_fqdn',None):
                host_package = hosts_packages_repo.get(
                    host.get('computer_fqdn',None),
                    None)
                if host_package:
                    depends = ensure_list(host_package.depends.split(','))
                    host['depends'] = [d for d in depends
                                       if (d in packages_repo and packages_repo[d].section == 'group')]
                else:
                    depends = []
            else:
                depends = []

            if not groups or list(set(groups) & set(depends)):
                result.append(host)
            else:
                continue

            try:
                if host['listening_address'] and host['listening_timestamp']:
                    reachable = 'OK'
                elif not host['listening_address'] and host['listening_timestamp']:
                    reachable = 'UNREACHABLE'
                else:
                    reachable = 'UNKNOWN'
                host['reachable'] = reachable
            except (KeyError, TypeError):
                host['reachable'] = 'UNKNOWN'

            """try:
                us = host['last_update_status']
                if us.get('errors', []):
                    host['host_status'] = 'ERROR'
                elif us.get('upgrades', []):
                    host['host_status'] = 'TO-UPGRADE'
                else:
                    host['host_status'] = 'OK'
            except:
                host['host_status'] = '?'
            """ # updated by model listener or DB trigger

        if 'uuid' in request.args:
            if len(result) == 0:
                msg = 'No data found for uuid {}'.format(request.args['uuid'])
            else:
                msg = 'host data fields {} returned for uuid {}'.format(
                    ','.join(columns),
                    request.args['uuid'])
        elif 'filter' in request.args:
            if len(result) == 0:
                msg = 'No data found for filter {}'.format(
                    request.args['filter'])
            else:
                msg = '{} hosts returned for filter {}'.format(
                    len(result),
                    request.args['filter'])
        else:
            if len(result) == 0:
                msg = 'No data found'
            else:
                msg = '{} hosts returned'.format(len(result))

    except Exception as e:
        return make_response_from_exception(e)

    return make_response(
        result=result, msg=msg, status=200, request_time=time.time() - start_time)


@app.route('/api/v1/host_data')
@requires_auth
def host_data():
    """
        Get additional data for a host
        query:
          uuid=<uuid>
          field=packages, dmi or softwares
    """
    try:
        start_time = time.time()
        # build filter
        if 'uuid' in request.args:
            uuid = request.args['uuid']
        else:
            raise EWaptMissingParameter('Parameter uuid is missing')

        if 'field' in request.args:
            field = request.args['field']
            if not field in Hosts._meta.fields:
                raise EWaptMissingParameter('Parameter field %s is unknown'%field)

        else:
            raise EWaptMissingParameter('Parameter field is missing')

        data = Hosts\
                        .select(Hosts.uuid,Hosts.computer_fqdn,Hosts.fieldbyname(field))\
                        .where(Hosts.uuid==uuid)\
                        .dicts()\
                        .first(1)
        if data is None:
            raise EWaptUnknownHost(
                'Host {} not found in database'.format(uuid))
        else:
            msg = '{} data for host {}'.format(field, uuid)

    except Exception as e:
        return make_response_from_exception(e)

    result = data.get(field,None)
    if result is None:
        msg = 'No {} data for host {}'.format(field, uuid)
        success = False
        error_code = 'empty_data'
    else:
        success = True
        error_code = None

    return make_response(result=result, msg=msg, success=success,
                         error_code=error_code, status=200, request_time=time.time() - start_time)


@app.route('/api/v1/hosts', methods=['POST'])
@requires_auth
def update_hosts():
    """update one or several hosts
        post data is a json list of host data
        for each host, the key is the uuid
    """
    start_time = time.time()

    post_data = ensure_list(json.loads(request.data))
    msg = []
    result = []

    try:
        for data in post_data:
            # build filter
            if not 'uuid' in data:
                raise Exception('No uuid provided in post host data')
            uuid = data["uuid"]
            result.append(update_host_data(data))

            # check if client is reachable
            if not 'check_hosts_thread' in g or not g.check_hosts_thread.is_alive():
                logger.info('Creates check hosts thread for %s' % (uuid,))
                g.check_hosts_thread = CheckHostsWaptService(
                    timeout=conf['clients_connect_timeout'],
                    uuids=[uuid])
                g.check_hosts_thread.start()
            else:
                logger.info(
                    'Reuses current check hosts thread for %s' %
                    (uuid,))
                g.check_hosts_thread.queue.put(data)

            msg.append('host {} updated in DB'.format(uuid))

    except Exception as e:
        return make_response_from_exception(e)

    return make_response(result=result, msg='\n'.join(
        msg), status=200, request_time=time.time() - start_time)


@app.route('/api/v1/host_cancel_task')
@requires_auth
def host_cancel_task():
    try:
        uuid = request.args['uuid']
        host_data = Hosts\
                        .select(Hosts.uuid,Hosts.computer_fqdn,Hosts.wapt,
                                Hosts.listening_address,
                                Hosts.listening_port,
                                Hosts.listening_protocol,
                                Hosts.listening_timestamp,
                                 )\
                        .where(Hosts.uuid==uuid)\
                        .dicts()\
                        .first(1)
        listening_address = get_ip_port(host_data)
        if listening_address and listening_address[
                'address'] and listening_address['port']:
            logger.info(
                "Get tasks status for %s at address %s..." %
                (uuid, listening_address['address']))
            args = {}
            args.update(listening_address)
            args['uuid'] = uuid
            client_result = requests.get(
                "%(protocol)s://%(address)s:%(port)d/cancel_running_task.json?uuid=%(uuid)s" %
                args,
                proxies={
                    'http': None,
                    'https': None},
                verify=False,
                timeout=conf['client_tasks_timeout']).text
            try:
                client_result = json.loads(client_result)
            except ValueError:
                if 'Restricted access' in client_result:
                    raise EWaptForbiddden(client_result)
                else:
                    raise Exception(client_result)
        else:
            raise EWaptMissingHostData(
                _("The host reachability is not defined."))
        return make_response(client_result,
                             msg="Task canceled",
                             success=isinstance(client_result, dict),)
    except Exception as e:
        return make_response_from_exception(e)


@app.route('/api/v1/usage_statistics')
def usage_statistics():
    """returns some anonymous usage statistics to give an idea of depth of use"""
    hosts = get_db().hosts
    try:
        stats = hosts.aggregate([
            {'$unwind': '$packages'},
            {'$group':
                {'_id': '$uuid',
                    'last_query_date': {'$first': {'$substr': ['$last_query_date', 0, 10]}},
                    'count': {'$sum': 1},
                    'ok': {'$sum': {'$cond': [{'$eq': ['$packages.install_status', 'OK']}, 1, 0]}},
                    'has_error': {'$first': {'$cond': [{'$ne': ['$update_status.errors', []]}, 1, 0]}},
                    'need_upgrade': {'$first': {'$cond': [{'$ne': ['$update_status.upgrades', []]}, 1, 0]}},
                 }},
            {'$group':
                {'_id': 1,
                    'hosts_count': {'$sum': 1},
                    'oldest_query': {'$min': '$last_query_date'},
                    'newest_query': {'$max': '$last_query_date'},
                    'packages_count_max': {'$max': '$count'},
                    'packages_count_avg': {'$avg': '$count'},
                    'packages_count_ok': {'$sum': '$ok'},
                    'hosts_count_has_error': {'$sum': '$has_error'},
                    'hosts_count_need_upgrade': {'$sum': '$need_upgrade'},
                 }},
        ])
        del(stats['result'][0]['_id'])
    except:
        # fallback for old mongo without aggregate framework
        stats = {}
        stats['result'] = [
            {
                'hosts_count': hosts.count(),
            }]

    result = dict(
        uuid=conf['server_uuid'],
        platform=platform.system(),
        architecture=platform.architecture(),
        version=__version__,
        date=datetime2isodate(),
    )
    result.update(stats['result'][0])
    return make_response(msg=_('Anomnymous usage statistics'), result=result)


##################################################################
class CheckHostWorker(threading.Thread):

    """Worker which pulls a host data from queue, checks reachability, and stores result in db
    """

    def __init__(self, queue, timeout):
        threading.Thread.__init__(self)
        self.queue = queue
        self.timeout = timeout
        self.daemon = True
        self.start()

    def check_host(self, host_data):
        try:
            listening_info = get_ip_port(
                host_data,
                recheck=True,
                timeout=self.timeout)
            # update timestamp
            listening_info['timestamp'] = datetime2isodate()
            return listening_info
        except Exception as e:
            # return "not reachable" information
            return dict(protocol='', address='', port=conf[
                        'waptservice_port'], timestamp=datetime2isodate())

    def run(self):
        logger.debug('worker %s running' % self.ident)
        while True:
            try:
                host_data = self.queue.get(timeout=2)
                listening_infos = self.check_host(host_data)
                Hosts.update(
                    listening_protocol=listening_infos['protocol'],
                    listening_address=listening_infos['address'],
                    listening_port=listening_infos['port'],
                    listening_timestamp=listening_infos['timestamp'],
                    )\
                    .where(Hosts.uuid == host_data['uuid'])\
                    .execute()
                logger.debug(
                        "Client check %s finished with %s" %
                        (self.ident, listening_infos))
                self.queue.task_done()
                wapt_db.commit()
            except Queue.Empty:
                break
        logger.debug('worker %s finished' % self.ident)


class CheckHostsWaptService(threading.Thread):

    """Thread which check which IP is reachable for all registered hosts
        The result is stored in MongoDB database as wapt.listening_address
        {protocol
         address
         port}
       if poll_interval is not None, the thread runs indefinetely/
       if poll_interval is None, one check of all hosts is performed.
    """

    def __init__(self, timeout=2, uuids=[]):
        threading.Thread.__init__(self)
        self.daemon = True
        self.timeout = timeout
        self.uuids = uuids
        if self.uuids:
            self.workers_count = min(len(uuids), 30)
        else:
            self.workers_count = 30

        self.queue = Queue.Queue()


    def run(self):
        logger.debug(
            'Client-listening %s address checker thread started' %
            self.ident)

        fields = [Hosts.uuid,
                  Hosts.computer_fqdn,
                  Hosts.listening_timestamp,
                  Hosts.listening_protocol,
                  Hosts.listening_address,
                  Hosts.listening_port,
                  Hosts.wapt_status,
                  Hosts.host_info,
                  ]
        if self.uuids:
            where_clause = Hosts.uuid.in_(self.uuids)
        else:
            # slect only computer with connected ips or all ?
            where_clause = None

        query = Hosts.select(*fields)
        if where_clause:
            query = query.where(where_clause)

        logger.debug('Reset listening status timestamps of hosts')
        Hosts.update(listening_timestamp=None).where(where_clause).execute()

        for data in query.dicts():
            logger.debug(
                'Hosts %s pushed in check IP queue' %
                data['uuid'])
            self.queue.put(data)

        logger.debug('Create %i workers' % self.workers_count)
        for i in range(self.workers_count):
            CheckHostWorker(self.queue, self.timeout)

        logger.debug(
            '%s CheckHostsWaptService waiting for check queue to be empty' %
            (self.ident))
        self.queue.join()
        logger.debug(
            '%s CheckHostsWaptService workers all terminated' %
            (self.ident))


#################################################
# Helpers for installer
##

def install_windows_nssm_service(
        service_name, service_binary, service_parameters, service_logfile, service_dependencies=None):
    """Setup a program as a windows Service managed by nssm
    >>> install_windows_nssm_service("WAPTServer",
        os.path.abspath(os.path.join(wapt_root_dir,'waptpython.exe')),
        os.path.abspath(__file__),
        os.path.join(log_directory,'nssm_waptserver.log'),
        service_logfile,
        'WAPTMongodb WAPTApache')
    """
    import setuphelpers
    from setuphelpers import registry_set, REG_DWORD, REG_EXPAND_SZ, REG_MULTI_SZ, REG_SZ
    datatypes = {
        'dword': REG_DWORD,
        'sz': REG_SZ,
        'expand_sz': REG_EXPAND_SZ,
        'multi_sz': REG_MULTI_SZ,
    }

    if setuphelpers.service_installed(service_name):
        if not setuphelpers.service_is_stopped(service_name):
            logger.info('Stop running "%s"' % service_name)
            setuphelpers.run('net stop "%s" /yes' % service_name)
            while not setuphelpers.service_is_stopped(service_name):
                logger.debug('Waiting for "%s" to terminate' % service_name)
                time.sleep(2)
        logger.info('Unregister existing "%s"' % service_name)
        setuphelpers.run('sc delete "%s"' % service_name)

    if setuphelpers.iswin64():
        nssm = os.path.join(wapt_root_dir, 'waptservice', 'win64', 'nssm.exe')
    else:
        nssm = os.path.join(wapt_root_dir, 'waptservice', 'win32', 'nssm.exe')

    logger.info('Register service "%s" with nssm' % service_name)
    cmd = '"{nssm}" install "{service_name}" "{service_binary}" {service_parameters}'.format(
        nssm=nssm,
        service_name=service_name,
        service_binary=service_binary,
        service_parameters=service_parameters
    )
    logger.info("running command : %s" % cmd)
    setuphelpers.run(cmd)

    # fix some parameters (quotes for path with spaces...
    params = {
        "Description": "sz:%s" % service_name,
        "DelayedAutostart": 1,
        "DisplayName": "sz:%s" % service_name,
        "AppStdout": r"expand_sz:{}".format(service_logfile),
        "Parameters\\AppStderr": r"expand_sz:{}".format(service_logfile),
        "Parameters\\AppParameters": r'expand_sz:{}'.format(service_parameters),
    }

    root = setuphelpers.HKEY_LOCAL_MACHINE
    base = r'SYSTEM\CurrentControlSet\services\%s' % service_name
    for key in params:
        if isinstance(params[key], int):
            (valuetype, value) = ('dword', params[key])
        elif ':' in params[key]:
            (valuetype, value) = params[key].split(':', 1)
            if valuetype == 'dword':
                value = int(value)
        else:
            (valuetype, value) = ('sz', params[key])
        fullpath = base + '\\' + key
        (path, keyname) = fullpath.rsplit('\\', 1)
        if keyname == '@' or keyname == '':
            keyname = None
        registry_set(root, path, keyname, value, type=datatypes[valuetype])

    if service_dependencies is not None:
        logger.info(
            'Register dependencies for service "%s" with nssm : %s ' %
            (service_name, service_dependencies))
        cmd = '"{nssm}" set "{service_name}" DependOnService {service_dependencies}'.format(
            nssm=nssm,
            service_name=service_name,
            service_dependencies=service_dependencies
        )
        logger.info("running command : %s" % cmd)
        setuphelpers.run(cmd)

        #fullpath = base+'\\' + 'DependOnService'
        #(path,keyname) = fullpath.rsplit('\\',1)
        # registry_set(root,path,keyname,service_dependencies,REG_MULTI_SZ)


def make_httpd_config(wapt_root_dir, wapt_folder):
    import jinja2

    if conf['wapt_folder'].endswith('\\') or conf['wapt_folder'].endswith('/'):
        conf['wapt_folder'] = conf['wapt_folder'][:-1]

    ap_conf_dir = os.path.join(
        wapt_root_dir,
        'waptserver',
        'apache-win32',
        'conf')
    ap_file_name = 'httpd.conf'
    ap_conf_file = os.path.join(ap_conf_dir, ap_file_name)
    ap_ssl_dir = os.path.join(
        wapt_root_dir,
        'waptserver',
        'apache-win32',
        'ssl')

    # generate ssl keys
    openssl = os.path.join(
        wapt_root_dir,
        'waptserver',
        'apache-win32',
        'bin',
        'openssl.exe')
    openssl_config = os.path.join(
        wapt_root_dir,
        'waptserver',
        'apache-win32',
        'conf',
        'openssl.cnf')
    fqdn = None
    try:
        import socket
        fqdn = socket.getfqdn()
    except:
        pass
    if not fqdn:
        fqdn = 'wapt'
    if '.' not in fqdn:
        fqdn += '.local'
    void = subprocess.check_output([
        openssl,
        'req',
        '-new',
        '-x509',
        '-newkey', 'rsa:2048',
        '-nodes',
        '-days', '3650',
        '-out', os.path.join(ap_ssl_dir, 'cert.pem'),
        '-keyout', os.path.join(ap_ssl_dir, 'key.pem'),
        '-config', openssl_config,
        '-subj', '/C=/ST=/L=/O=/CN=' + fqdn + '/'
    ], stderr=subprocess.STDOUT)

    # write config file
    jinja_env = jinja2.Environment(loader=jinja2.FileSystemLoader(ap_conf_dir))
    template = jinja_env.get_template(ap_file_name + '.j2')
    template_variables = {
        'wapt_repository_path': os.path.dirname(conf['wapt_folder']),
        'apache_root_folder': os.path.dirname(ap_conf_dir),
        'windows': True,
        'ssl': True,
        'wapt_ssl_key_file': os.path.join(ap_ssl_dir, 'key.pem'),
        'wapt_ssl_cert_file': os.path.join(ap_ssl_dir, 'cert.pem')
    }
    config_string = template.render(template_variables)
    dst_file = file(ap_conf_file, 'wt')
    dst_file.write(config_string)
    dst_file.close()


def make_mongod_config(wapt_root_dir):
    import jinja2

    conf_dir = os.path.join(wapt_root_dir, 'waptserver', 'mongodb')
    file_name = 'mongod.cfg'
    conf_file = os.path.join(conf_dir, file_name)
    jinja_env = jinja2.Environment(loader=jinja2.FileSystemLoader(conf_dir))
    template = jinja_env.get_template(file_name + '.j2')
    template_variables = {
        'dbpath': os.path.join(conf_dir, 'data'),
        'logpath': os.path.join(conf_dir, 'log', 'mongodb.log'),
        'mongodb_port': int(conf['mongodb_port']),
    }
    config_string = template.render(template_variables)
    dst_file = file(conf_file, 'wt')
    dst_file.write(config_string)
    dst_file.close()


def install_windows_service():
    """Setup waptserver, waptmongodb et waptapache as a windows Service managed by nssm
    >>> install_windows_service([])
    """
    install_apache_service = not options.without_apache  # '--without-apache' not in options

    # register mongodb server
    make_mongod_config(wapt_root_dir)

    service_binary = os.path.abspath(
        os.path.join(
            wapt_root_dir,
            'waptpython.exe'))
    service_parameters = '"%s" "%s" "%s"' % (
        os.path.join(wapt_root_dir, 'waptserver', 'mongodb', 'mongod.py'),
        os.path.join(wapt_root_dir, 'waptserver', 'mongodb', 'mongod.exe'),
        os.path.join(wapt_root_dir, 'waptserver', 'mongodb', 'mongod.cfg')
    )
    service_logfile = os.path.join(log_directory, 'nssm_waptmongodb.log')
    install_windows_nssm_service(
        "WAPTMongodb",
        service_binary,
        service_parameters,
        service_logfile)

    # register apache frontend
    if install_apache_service:
        make_httpd_config(wapt_root_dir, conf['wapt_folder'])
        service_binary = os.path.abspath(
            os.path.join(
                wapt_root_dir,
                'waptserver',
                'apache-win32',
                'bin',
                'httpd.exe'))
        service_parameters = ""
        service_logfile = os.path.join(log_directory, 'nssm_apache.log')
        install_windows_nssm_service(
            "WAPTApache",
            service_binary,
            service_parameters,
            service_logfile)

    # register waptserver
    service_binary = os.path.abspath(
        os.path.join(
            wapt_root_dir,
            'waptpython.exe'))
    service_parameters = '"%s"' % os.path.abspath(__file__)
    service_logfile = os.path.join(log_directory, 'nssm_waptserver.log')
    service_dependencies = 'WAPTMongodb'
    if install_apache_service:
        service_dependencies += ' WAPTApache'
    install_windows_nssm_service(
        "WAPTServer",
        service_binary,
        service_parameters,
        service_logfile,
        service_dependencies)


##############
if __name__ == "__main__":
    usage = """\
    %prog [-c configfile] [--devel] [action]

    WAPT Server daemon.

    action is either :
      <nothing> : run service in foreground
      install   : install as a Windows service managed by nssm

    """

    parser = OptionParser(usage=usage, version='waptserver.py ' + __version__)
    parser.add_option(
        "-c",
        "--config",
        dest="configfile",
        default=DEFAULT_CONFIG_FILE,
        help="Config file full path (default: %default)")
    parser.add_option(
        "-l",
        "--loglevel",
        dest="loglevel",
        default=None,
        type='choice',
        choices=[
            'debug',
            'warning',
            'info',
            'error',
            'critical'],
        metavar='LOGLEVEL',
        help="Loglevel (default: warning)")
    parser.add_option(
        "-d",
        "--devel",
        dest="devel",
        default=False,
        action='store_true',
        help="Enable debug mode (for development only)")
    parser.add_option(
        "-w",
        "--without-apache",
        dest="without_apache",
        default=False,
        action='store_true',
        help="Don't install Apache http server for wapt (service WAPTApache)")

    (options, args) = parser.parse_args()
    app.config['CONFIG_FILE'] = options.configfile

    utils_set_devel_mode(options.devel)

    if options.loglevel is not None:
        setloglevel(logger, options.loglevel)
    else:
        setloglevel(logger, conf['loglevel'])

    log_directory = os.path.join(wapt_root_dir, 'log')
    if not os.path.exists(log_directory):
        os.mkdir(log_directory)

    hdlr = logging.FileHandler(os.path.join(log_directory, 'waptserver.log'))
    hdlr.setFormatter(
        logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(hdlr)

    # Setup initial directories
    if os.path.exists(conf['wapt_folder']) == False:
        try:
            os.makedirs(conf['wapt_folder'])
        except:
            raise Exception(
                _("Folder missing : {}.").format(
                    conf['wapt_folder']))
    if os.path.exists(conf['wapt_folder'] + '-host') == False:
        try:
            os.makedirs(conf['wapt_folder'] + '-host')
        except:
            raise Exception(
                _("Folder missing : {}-host.").format(conf['wapt_folder']))
    if os.path.exists(conf['wapt_folder'] + '-group') == False:
        try:
            os.makedirs(conf['wapt_folder'] + '-group')
        except:
            raise Exception(
                _("Folder missing : {}-group.").format(conf['wapt_folder']))

    if args and args[0] == 'doctest':
        import doctest
        sys.exit(doctest.testmod())

    if args and args[0] == 'install':
        # pass optional parameters along with the command
        install_windows_service()
        sys.exit(0)

    if args and args[0] == 'test':
        # pass optional parameters along with the command
        test()
        sys.exit(0)

    if options.devel:
        app.run(host='0.0.0.0', port=8080, debug=False)
    else:
        port = conf['waptserver_port']
        server = Rocket(('0.0.0.0', port), 'wsgi', {"wsgi_app": app})
        try:
            logger.info("starting waptserver %s" % __version__)
            server.start()
        except KeyboardInterrupt:
            logger.info("stopping waptserver")
            server.stop()

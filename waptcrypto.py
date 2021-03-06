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

import os,sys
import codecs
import hashlib
import glob

from M2Crypto import EVP, X509, SSL, BIO
from M2Crypto.EVP import EVPError
from M2Crypto import BIO,RSA

from waptutils import *

import datetime

def check_key_password(key_filename,password=""):
    """Check if provided password is valid to read the PEM private key
    >>> if not os.path.isfile('c:/private/test.pem'):
    ...     create_self_signed_key('test',organization='Tranquil IT',locality=u'St Sebastien sur Loire',commonname='wapt.tranquil.it',email='...@tranquil.it')
    >>> check_key_password('c:/private/test.pem','')
    True
    >>> check_key_password('c:/private/ko.pem','')
    False
    """
    def callback(*args):
        return password
    try:
        EVP.load_key(key_filename, callback)
    except EVPError:
        return False
    return True


def read_in_chunks(f, chunk_size=1024*128):
    """Lazy function (generator) to read a file piece by piece.
    Default chunk size: 128k."""
    while True:
        data = f.read(chunk_size)
        if not data:
            break
        yield data


def sha1_for_file(fname, block_size=2**20):
    f = open(fname,'rb')
    sha1 = hashlib.sha1()
    while True:
        data = f.read(block_size)
        if not data:
            break
        sha1.update(data)
    return sha1.hexdigest()


def sha1_for_data(data):
    assert(isinstance(data,str))
    sha1 = hashlib.sha1()
    sha1.update(data)
    return sha1.hexdigest()


def sha256_for_file(fname, block_size=2**20):
    f = open(fname,'rb')
    sha256 = hashlib.sha256()
    while True:
        data = f.read(block_size)
        if not data:
            break
        sha256.update(data)
    return sha256.hexdigest()


def sha256_for_data(data):
    assert(isinstance(data,str))
    sha256 = hashlib.sha256()
    sha256.update(data)
    return sha256.hexdigest()


def default_pwd_callback(*args):
    """Default password callback for opening private keys.
    """
    import getpass
    return getpass.getpass().encode('ascii')


class SSLCAChain(object):
    BEGIN_KEY = '-----BEGIN ENCRYPTED PRIVATE KEY-----'
    END_KEY = '-----END ENCRYPTED PRIVATE KEY-----'
    BEGIN_CERTIFICATE = '-----BEGIN CERTIFICATE-----'
    END_CERTIFICATE = '-----END CERTIFICATE-----'

    def __init__(self,callback=None):
        self._keys = {}
        self._certificates = {}
        if callback is None:
            callback = default_pwd_callback
        self.callback = callback

    def add_pems(self,cert_pattern_or_dir='*.crt',load_keys=False):
        if os.path.isdir(cert_pattern_or_dir):
            # load pems from provided directory
            for fn in glob.glob(os.path.join(cert_pattern_or_dir,'*.crt'))+glob.glob(os.path.join(cert_pattern_or_dir,'*.pem')):
                self.add_pem(fn,load_keys=load_keys)
        else:
            # load pems based on file wildcards
            for fn in glob.glob(cert_pattern_or_dir):
                self.add_pem(fn,load_keys=load_keys)

    def add_pem(self,filename,load_keys=False):
        # parse a bundle PEM with multiple key / certificates
        lines = open(filename,'r').read().splitlines()
        inkey = False
        incert = False
        tmplines = []
        for line in lines:
            if line == self.BEGIN_CERTIFICATE:
                tmplines = [line]
                incert = True
            elif line == self.END_CERTIFICATE:
                tmplines.append(line)
                crt =  X509.load_cert_string('\n'.join(tmplines))
                self._certificates[crt.get_fingerprint(md='sha1')] = SSLCertificate(filename,crt=crt)
                incert = False
                tmplines = []
            elif line == self.BEGIN_KEY:
                tmplines = [line]
                inkey = True
            elif line == self.END_KEY:
                tmplines.append(line)
                if load_keys:
                    key = EVP.load_key_string('\n'.join(tmplines),callback=self.callback)
                    self._keys[key.get_modulus()] = SSLPrivateKey(filename,key=key,callback=self.callback)
                inkey = False
                tmplines = []
            else:
                if inkey or incert:
                    tmplines.append(line)

    def key(self,modulus):
        return self._keys.get(modulus,None)

    def certificate(self,sha1_fingerprint=None,subject_hash=None):
        if subject_hash:
            certs = [crt for crt in self.certificates() if crt.subject_hash == subject_hash]
            if certs:
                return certs[0]
            else:
                return None
        else:
            return self._certificates.get(sha1_fingerprint,None)

    def keys(self):
        return self._keys.values()

    def certificates(self):
        return self._certificates.values()

    def matching_certs(self,key):
        return [crt for crt in self.certificates() if crt.is_valid() and crt.match_key(key)]

    def certificate_chain(self,crt):
        result = [crt]
        issuer = self.certificate(subject_hash=crt.crt.get_issuer().as_hash())
        while issuer:
            result.append(issuer)
            issuer_subject_hash = issuer.crt.get_issuer().as_hash()
            new_issuer = self.certificate(subject_hash=issuer_subject_hash)
            if new_issuer == issuer:
                break
            else:
                issuer = new_issuer
        return result

class SSLVerifyException(Exception):
    pass

class SSLPrivateKey(object):
    def __init__(self,private_key=None,key=None,callback=None):
        """Args:
            private_key (str) : Filename Path to PEM encoded Private Key
            key (PKey) : Public/[private]  PKey structure
            callback (func) : Called to provide password for the key if needed
        """
        self.private_key_filename = private_key
        if key:
            self.key = key
        else:
            if not os.path.isfile(private_key):
                raise Exception('Private key %s not found' % private_key)
        if callback is None:
            callback = default_pwd_callback
        self.pwd_callback = callback
        self._rsa = None
        self._key = None

    @property
    def rsa(self):
        """access to RSA keys"""
        if not self._rsa:
            self._rsa = RSA.load_key(self.private_key_filename,callback=self.pwd_callback)
        return self._rsa

    @property
    def key(self):
        if not self._key:
            self._key = EVP.PKey()
            self._key.assign_rsa(self.rsa)
        return self._key

    def sign_content(self,content):
        """ Sign content with the private_key, return the signature"""
        if isinstance(content,unicode):
            content = content.encode('utf8')
        if not isinstance(content,str):
            content = jsondump(content)
        self.key.sign_init()
        self.key.sign_update(content)
        signature = self.key.sign_final()
        return signature

    def match_cert(self,crt):
        """Check if provided public certificate matches the current private key"""
        if not isinstance(crt,SSLCertificate):
            crt = SSLCertificate(crt)
        return crt.crt.get_pubkey().get_modulus() == self.key.get_modulus()

    def matching_certs(self,cert_dir):
        result = []
        for fn in glob.glob(os.path.join(cert_dir,'*.crt')):
            crt = SSLCertificate(fn)
            if crt.match_key(self):
                result.append(crt)
        return result

    def encrypt(self,content):
        """Encrypt a message will can be decrypted with the public key"""
        return self.rsa.private_encrypt(content,RSA.pkcs1_padding)

    def decrypt(self,content):
        """Decrypt a message encrypted with the public key"""
        return self.rsa.private_decrypt(content,RSA.pkcs1_oaep_padding)

    @property
    def modulus(self):
        return self.key.get_modulus()

    def __cmp__(self,key):
        return cmp(self.modulus,key.modulus)


class SSLCertificate(object):
    """Hold a X509 public certificate"""
    def __init__(self,public_cert=None,crt=None,ignore_validity_checks=True):
        """
            public_cert (str): Path to X509 encoded certificate
            crt (
        """
        self._public_cert_filename = None
        self._crt = None
        self._rsa = None
        self._key = None
        self.public_cert_filename = public_cert
        if crt:
            self._crt = crt
        self.ignore_validity_checks = ignore_validity_checks

    @property
    def public_cert_filename(self):
        return self._public_cert_filename

    @public_cert_filename.setter
    def public_cert_filename(self,value):
        if value != self._public_cert_filename:
            self._public_cert_filename = value
            self._crt = None
            self._rsa = None
            self._key = None
            self._crt = None
            if not os.path.isfile(value):
                raise Exception('Public certificate %s not found' % value)

    @property
    def crt(self):
        if self._crt is None:
            self._crt = X509.load_cert(self._public_cert_filename)
        return self._crt

    @property
    def rsa(self):
        """Return public RSA keys"""
        if not self._rsa:
            self._rsa = self.crt.get_pubkey().get_rsa()
        return self._rsa

    @property
    def key(self):
        """Return public key"""
        if not self._key:
            self._key = EVP.PKey()
            self._key.assign_rsa(self.rsa)
        return self._key

    @property
    def organisation(self):
        return self.crt.get_subject().O

    @property
    def cn(self):
        return self.crt.get_subject().CN

    @property
    def subject(self):
        subject = self.crt.get_subject()
        result = {}
        for key in subject.nid.keys():
            result[key] = getattr(subject,key)
        return result

    @property
    def subject_hash(self):
        return self.crt.get_subject().as_hash()

    @property
    def subject_dn(self):
        return self.crt.get_subject().as_text()

    @property
    def fingerprint(self,md='sha1'):
        return self.crt.get_fingerprint(md=md)

    @property
    def issuer(self):
        data = self.crt.get_issuer()
        result = {}
        for key in data.nid.keys():
            result[key] = getattr(data,key)
        return result

    @property
    def issuer_dn(self):
        return self.crt.get_issuer().as_text()

    def verify_content(self,content,signature):
        u"""Check that the signature matches the content

        Args:
            content (str) : content to check. if not str, the structure will be converted to json first
            signature (str) : ssl signature of the content

        Return
            str: subject (CN) of current certificate or raise an exception if no match
        """
        if isinstance(content,unicode):
            content = content.encode('utf8')
        if not isinstance(content,str):
            content = jsondump(content)
        self.key.verify_init()
        self.key.verify_update(content)
        if self.key.verify_final(signature):
            return self.subject_dn
        raise SSLVerifyException('SSL signature verification failed for certificate %s'%self.subject_dn)

    def match_key(self,key):
        """Check if certificate matches the given private key"""
        if not isinstance(key,SSLPrivateKey):
            key = SSLPrivateKey(key)
        return self.crt.get_pubkey().get_modulus() == key.key.get_modulus()

    @property
    def not_before(self):
        result = self.crt.get_not_before().get_datetime()
        return result

    @property
    def not_after(self):
        result = self.crt.get_not_after().get_datetime()
        return result

    def is_valid(self,issuer_cert=None,cn=None,purpose=None,ca_bundle=None):
        """Check validity of certificate
                not before / not after
            if ca_bundle is provided, check that the certificate is issued by a known ca
            if issuer_cert is provided, check that the certificate is issued by this issuer
        """
        if self.ignore_validity_checks:
            return True
        nb,na = self.not_before,self.not_after
        now = datetime.datetime.now(nb.tzinfo)
        return \
            (cn is None or cn == self.cn) and \
            now >= nb and now <= na and \
            (issuer_cert is None or issuer_cert == self.issuer) and \
            (ca_bundle is None or ca_bundle.check_is_known_issuer(self))

    def __iter__(self):
        for k in ['issuer_dn','fingerprint','subject_dn','cn']:
            yield k,getattr(self,k)

    def __str__(self):
        return u'SSLCertificate cn=%s'%self.cn

    def __repr__(self):
        return u'<SSLCertificate cn=%s / issuer=%s / validity=%s - %s>'%(self.cn,self.issuer.get('CN','?'),self.not_before.strftime('%Y-%m-%d'),self.not_after.strftime('%Y-%m-%d'))

    def __cmp__(self,crt):
        if isinstance(crt,SSLCertificate):
            return cmp(self.fingerprint,crt.fingerprint)
        elif isinstance(crt,dict):
            return cmp(self.subject,crt)
        else:
            raise ValueError('Can not compare SSLCertificate with %s'%(type(crt)))

    def encrypt(self,content):
        """Encrypt a message will can be decrypted with the private key"""
        rsa = self.crt.get_pubkey().get_rsa()
        return rsa.public_encrypt(content, RSA.pkcs1_oaep_padding)

    def decrypt(self,content):
        """Decrypt a message encrypted with the private key"""
        rsa = self.crt.get_pubkey().get_rsa()
        return rsa.public_decrypt(content, RSA.pkcs1_padding)


def ssl_verify_content(content,signature,public_certs):
    u"""Check that the signature matches the content, using the provided list of public keys
        Content, signature are String
        public_certs is either a filename or a list of filenames
    >>> if not os.path.isfile('c:/private/test.pem'):
    ...     key = create_self_signed_key('test',organization='Tranquil IT',locality=u'St Sebastien sur Loire',commonname='wapt.tranquil.it',email='...@tranquil.it')
    >>> my_content = 'Un test de contenu'
    >>> my_signature = SSLPrivateKey('c:/private/test.pem').sign_content(my_content)
    >>> SSLCertificate('c:/private/test.crt').verify_content(my_content,my_signature)
    'C=FR, L=St Sebastien sur Loire, O=Tranquil IT, CN=wapt.tranquil.it/emailAddress=...@tranquil.it'
    """
    assert isinstance(signature,str)
    assert isinstance(public_certs,str) or isinstance(public_certs,unicode) or isinstance(public_certs,list)
    if not isinstance(public_certs,list):
        public_certs = [public_certs]
    for public_cert in public_certs:
        crt = SSLCertificate(public_cert)
        if crt.is_valid():
            try:
                return crt.verify_content(content,signature)
            except SSLVerifyException :
                pass
        else:
            logger.warning('Certificate %s is not valid'%public_cert)
    # no certificate can verify the content
    raise SSLVerifyException('SSL signature verification failed, either none public certificates match signature or signed content has been changed')


def private_key_has_password(key):
    r"""Return True if key can not be loaded without password
    >>> private_key_has_password(r'c:/tranquilit/wapt/tests/ssl/test.pem')
    False
    >>> private_key_has_password(r'c:/tmp/ko.pem')
    True
    """
    def callback(*args):
        return ""
    try:
        EVP.load_key(key, callback)
    except Exception as e:
        if "bad password" in str(e):
            return True
        else:
            print(str(e))
            return True
    return False


if __name__ == '__main__':
    import doctest
    import sys
    reload(sys)
    sys.setdefaultencoding("UTF-8")
    import doctest
    doctest.ELLIPSIS_MARKER = '???'
    doctest.testmod(optionflags=doctest.ELLIPSIS)
    sys.exit(0)

# Copyright (c) 2012, Hui Peng Hu
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# 1. Redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
# 3. All advertising materials mentioning features or use of this software
# must display the following acknowledgement:
# This product includes software developed by Hui Peng Hu.
#
# THIS SOFTWARE IS PROVIDED BY Hui Peng Hu ''AS IS'' AND ANY
# EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL Hui Peng Hu BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import uuid
import os
import tarfile
import zipfile
import tempfile
import datetime
import socket
import cherrypy
from cherrypy.lib.static import serve_file
import upnp

try:
    import pyminizip
    support_passworded_zip = True
except ImportError:
    support_passworded_zip = False


def get_internal_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('google.com', 80))
        return s.getsockname()[0]
    except:
        return None


def log_finish_request():
    print('sent to {}'.format(cherrypy.request.remote.ip))


cherrypy.tools.log_finish_request = cherrypy.Tool('on_end_request', log_finish_request, 'log_finish_request')


class SendF(object):
    def __init__(self, filenames, allow_external=False, output_fname=None, compression="gz", password=None):
        self.filenames = filenames
        self.allow_external = allow_external
        self.output_fname = output_fname
        self.compression = compression
        self.password = password

        self.internal_ip = None
        self.external_ip = None
        self.port = None
        self.uuid = str(uuid.uuid4())
        self.igd_device = None
        self.port_forwarded = False
        self.compressed = None

        self.start_time = None
        self.download_count = 0

    def initialize(self):
        # first, check that all files exists
        if not all(map(os.path.exists, self.filenames)):
            return False
        self.filepaths = [os.path.abspath(f) for f in self.filenames]

        # try getting the internal IP
        self.internal_ip = get_internal_ip()
        if self.internal_ip is None:
            return False

        self.port = self._get_unused_port()

        # first, do UPnP discovery
        # skip if we don't want external ips
        if self.allow_external:
            self.igd_device = upnp.discover()
            if self.igd_device:
                self.external_ip = upnp.get_external_ip_address(self.igd_device)
                upnp.add_port_mapping(self.igd_device, self.internal_ip, self.port, self.port)
                self.port_forwarded = True
            else:
                print('UPnP not found. If you are behind a router, link will probably not work.')

        # if UPnP did not work, then use the internal IP as the external IP
        if not self.port_forwarded:
            self.external_ip = self.internal_ip

        self.start_time = datetime.datetime.now()
        return True

    def finalize(self):
        if self.port_forwarded:
            upnp.delete_port_mapping(self.igd_device, self.port)
            self.port_forwarded = False
        if self.compressed:
            os.remove(self.compressed)
            self.compressed = None

    def quit(self):
        self.finalize()
        cherrypy.engine.exit()

    def _create_archive(self, archive_filename):
        if self.compression == 'zip':
            output_extension = 'zip'
            if support_passworded_zip and self.password:
                pyminizip.compress_multiple(self.filepaths, archive_filename, self.password, 1)
            else:
                with zipfile.ZipFile(archive_filename, 'w') as zFile:
                    for path in self.filepaths:
                        basename = os.path.basename(path)
                        zFile.write(path, basename)
            return output_extension

        if self.compression == 'gz':
            output_extension = 'tgz'
            f = tarfile.open(archive_filename, 'w:gz')
        elif self.compression == 'bz2':
            output_extension = 'tar.bz2'
            f = tarfile.open(archive_filename, 'w:bz2')
        elif self.compression in ('tar', 'none'):
            output_extension = 'tar'
            f = tarfile.open(archive_filename, 'w')

        for path in self.filepaths:
            basename = os.path.basename(path)
            f.add(path, basename)

        f.close()

        return output_extension

    @cherrypy.expose
    @cherrypy.tools.log_finish_request()
    def default(self, uuid):
        if uuid != self.uuid:
            return
        if not all(map(os.path.exists, self.filepaths)):
            self.quit()

        if len(self.filepaths) > 1 or os.path.isdir(self.filepaths[0]):
            file_to_send = os.path.join(tempfile.gettempdir(), self.uuid)
            output_extension = self._create_archive(file_to_send)
            self.compressed = file_to_send
            name, _ = os.path.splitext(self.output_fname if self.output_fname else "archive")
            name += '.' + output_extension
        else:
            file_to_send = self.filepaths[0]
            name = self.output_fname

        self.download_count += 1
        return serve_file(
            file_to_send,
            content_type="application/x-download",
            disposition="attachment",
            name=name)

    def _get_unused_port(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('localhost', 0))
        addr, port = s.getsockname()
        s.close()
        return port

    @property
    def link(self):
        return "http://{}:{}/{}".format(self.external_ip, self.port, self.uuid)

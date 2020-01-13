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
import tempfile
import datetime
import socket
import cherrypy
from cherrypy.lib.static import serve_file
import upnp
from typing import Sequence, Optional


def get_internal_ip() -> Optional[str]:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('google.com', 80))
        return s.getsockname()[0]
    except Exception:
        return None


def log_finish_request():
    print(f'sent to {cherrypy.request.remote.ip}')


cherrypy.tools.log_finish_request = cherrypy.Tool('on_end_request', log_finish_request, 'log_finish_request')


class SendF(object):
    def __init__(
        self,
        filenames: Sequence[str],
        allow_external: bool = False,
        output_fname: Optional[str] = None,
    ):
        self.filenames = filenames
        self.allow_external = allow_external
        self.output_fname = output_fname

        self.uuid = str(uuid.uuid4())[:8]
        self.igd_device: Optional[str] = None
        self.port_forwarded = False

    def initialize(self) -> bool:
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
            if self.igd_device is not None:
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

    def finalize(self) -> None:
        if self.port_forwarded and self.igd_device is not None:
            upnp.delete_port_mapping(self.igd_device, self.port)
            self.port_forwarded = False

    def quit(self) -> None:
        self.finalize()
        cherrypy.engine.exit()

    def _create_archive(self, archive_filename: str):
        f = tarfile.open(archive_filename, 'w')

        for path in self.filepaths:
            basename = os.path.basename(path)
            f.add(path, basename)

        f.close()

    @cherrypy.expose
    @cherrypy.tools.log_finish_request()
    def default(self, uuid: str):
        if uuid != self.uuid:
            return
        if not all(map(os.path.exists, self.filepaths)):
            self.quit()

        name: Optional[str] = None  # will use the file name
        if len(self.filepaths) > 1 or os.path.isdir(self.filepaths[0]):
            file_to_send = os.path.join(tempfile.gettempdir(), self.uuid)
            self._create_archive(file_to_send)
            name = os.path.splitext(self.output_fname if self.output_fname else "archive")[0] + '.tar'
        else:
            file_to_send = self.filepaths[0]

        return serve_file(file_to_send, content_type="application/x-download", disposition="attachment", name=name)

    def _get_unused_port(self) -> int:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('localhost', 0))
        addr, port = s.getsockname()
        s.close()
        return port

    @property
    def link(self) -> str:
        return f"http://{self.external_ip}:{self.port}/{self.uuid}"

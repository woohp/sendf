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

import sys
import signal
import uuid
import os
import getpass
import tarfile
import zipfile
import argparse
import tempfile
import datetime
import cherrypy
import socket
from cherrypy.lib.static import serve_file
from upnp import *

try:
    import pyminizip
    support_passworded_zip = True
except ImportError:
    support_passworded_zip = False


def check_files_exist(filenames):
    for filename in filenames:
        if os.path.exists(filename) == False:
            return False
    return True

def get_internal_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('google.com', 80))
        return s.getsockname()[0]
    except:
        return None

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
        self.upnp = None
        self.port_forwarded = False
        self.compressed = None

        self.start_time = None
        self.download_count = 0

    def initialize(self):
        # first, check that all files exists
        if check_files_exist(self.filenames) == False:
            return False
        self.filepaths = [os.path.abspath(f) for f in self.filenames]

        # try getting the internal IP
        self.internal_ip = get_internal_ip()
        if self.internal_ip == None:
            return False

        self.port = self._get_unused_port()

        # first, do UPnP discovery
        # skip if we don't want external ips
        if self.allow_external:
            upnp = UPnPPlatformIndependent()
            self.upnp = upnp
            upnp.discover()
            if upnp.found_wanted_services():
                self.external_ip = upnp.get_ext_ip()
                for i in xrange(10):
                    upnp.add_port_map(self.internal_ip, self.port)
                    self.port_forwarded = True
                    break
            else:
                print 'UPnP not found. If you are behind a router, link will probably not work.'

        # if UPnP did not work, then use the internal IP as the external IP
        if not self.port_forwarded:
            self.external_ip = self.internal_ip

        self.start_time = datetime.datetime.now()
        return True

    def finalize(self):
        if self.port_forwarded:
            self.upnp.del_port_map(self.port)
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
        elif self.compression == 'tar' or self.compression == 'none':
            output_extension = 'tar'
            f = tarfile.open(archive_filename, 'w')

        for path in self.filepaths:
            basename = os.path.basename(path)
            f.add(path, basename)

        f.close()

        return output_extension

    def default(self, uuid):
        if uuid != uuid:
            return
        if check_files_exist(self.filepaths) == False:
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

    default.exposed = True

    def _get_unused_port(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('localhost', 0))
        addr, port = s.getsockname()
        s.close()
        return port
    
    def __repr__(self):
        return "http://%s:%d/%s" % (self.external_ip, self.port, self.uuid)


def main():
    parser = argparse.ArgumentParser(prog="sendf")
#    parser.add_argument("-c", "--count", type=int, default=2,
#            help="maximum download count before the link expires")
    parser.add_argument("-d", "--duration", type=int, default=30,
            help="time before the link expires, in minutes")
    parser.add_argument("-o", "--output", type=str, default=None,
            help="name of the file the user will receive it as")
    parser.add_argument("-E", "--external", action="store_true", default=False,
            help="whether or not to use an external ip via uPnP")
    parser.add_argument("-c", "--compression", type=str, default="gz", choices=["gz", "bz2", "zip", "none"],
            help="compression method to use")
    parser.add_argument("-P", "--passworded", action='store_true', default=False,
            help="whether or not to password protect the file. compression method must be zip")
    parser.add_argument("files", type=str, nargs="+",
            help="files to send")
    args = vars(parser.parse_args())

    # stop cherrypy from printing stuff to the screen
    cherrypy.log.screen = False
    cherrypy.checker.on = False

    # initialize
    password = None
    if args['passworded']:
        if not support_passworded_zip:
            print 'WARNING: System does not support creating passworded zip. Install zlib and pyminizip. Skipping password...'
        elif args['compression'] != 'zip':
            print 'WARNING: You can only password protect zip files. Skipping password...'
        else:
            password = getpass.getpass('Password:')
    sendf = SendF(args['files'], args['external'], args['output'], args['compression'], password)
    sendf.initialize()
    print sendf

    # setup signal handlers
    def signal_handler(signal, frame):
        sendf.finalize()
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGQUIT, signal_handler)

    # set function to check whether the duration has passed
    duration = datetime.timedelta(minutes=args['duration'])
    check_frequency = args['duration'] * 10 # check every 10 seconds
    def check_duration():
        if datetime.datetime.now() - sendf.start_time >= duration:
            sendf.quit()
    cherrypy.process.plugins.Monitor(
            cherrypy.engine,
            check_duration,
            check_frequency).subscribe()

    # config server and start it up
    cherrypy.config.update({'server.socket_host': '0.0.0.0',
                            'server.socket_port': sendf.port})
    cherrypy.quickstart(sendf)

if __name__ == '__main__':
    main()


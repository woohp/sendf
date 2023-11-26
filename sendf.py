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

import argparse
import os
import signal
import socket
import sys
import tarfile
import types
import uuid
from collections.abc import Sequence
from io import BytesIO
from typing import AsyncGenerator

import uvicorn
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, Response, StreamingResponse
from starlette.routing import Route

import upnp


def get_internal_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("google.com", 80))
        internal_ip = s.getsockname()[0]
        s.close()
        return internal_ip
    except Exception:
        raise RuntimeError("Failed to get internal ip address :(")


class SendF:
    def __init__(
        self,
        filenames: Sequence[str],
        allow_external: bool = False,
        output_fname: str | None = None,
    ):
        # first, check that all files exists
        if not all(map(os.path.exists, filenames)):
            raise RuntimeError("File does not exists.")
        self.filepaths = [os.path.abspath(f) for f in filenames]

        self.internal_ip = get_internal_ip()
        self.port = self._get_unused_port()

        # do UPnP discovery and port mapping of external access is needed
        if allow_external:
            igd_device = upnp.discover()
            if igd_device is not None:
                self.igd_device = igd_device
                self.external_ip: str = upnp.get_external_ip_address(self.igd_device)
                upnp.add_port_mapping(igd_device, self.internal_ip, self.port, self.port)
            else:
                raise RuntimeError("UPnP IGD not found.")

        else:
            self.external_ip = self.internal_ip

        self.allow_external = allow_external
        self.output_fname = output_fname

        self.uuid = str(uuid.uuid4())[:8]

    def finalize(self) -> None:
        if self.allow_external:
            print("deleting port mapping...")
            upnp.delete_port_mapping(self.igd_device, self.port)
            self.allow_external = False

    async def _stream_tar_file(self) -> AsyncGenerator[bytes, None]:
        io = BytesIO()
        f = tarfile.open(fileobj=io, mode="w")

        for path in self.filepaths:
            basename = os.path.basename(path)
            f.add(path, basename)
            yield io.getvalue()
            io.truncate(0)
            io.seek(0)

        f.close()
        yield io.getvalue()

    async def call(self, request: Request) -> Response:
        uuid: str = request.path_params["uuid"]
        if uuid != self.uuid:
            raise HTTPException(404)

        # make sure all our files exists
        if not all(map(os.path.exists, self.filepaths)):
            raise RuntimeError

        # if it is a single file, then just return that as a FileResponse
        if len(self.filepaths) == 1 and os.path.isfile(self.filepaths[0]):
            filename = self.output_fname or os.path.basename(self.filepaths[0])
            return FileResponse(self.filepaths[0], filename=filename)

        # stream the tar file back
        filename = self.output_fname or "Archive.tar"
        return StreamingResponse(
            self._stream_tar_file(),
            headers={"content-disposition": f'attachment; filename="{filename}"'},
            media_type="application/x-tar",
        )

    def _get_unused_port(self) -> int:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("localhost", 0))
        addr, port = s.getsockname()
        s.close()
        return port

    @property
    def link(self) -> str:
        return f"http://{self.external_ip}:{self.port}/{self.uuid}"


def main() -> None:
    parser = argparse.ArgumentParser(prog="sendf")
    parser.add_argument("-o", "--output", type=str, default=None, help="name of the file the user will receive it as")
    parser.add_argument(
        "-e", "--external", action="store_true", default=False, help="whether or not to use an external ip via uPnP"
    )
    parser.add_argument("files", type=str, nargs="+", help="files to send")
    args = parser.parse_args()

    # initialize
    sendf = SendF(args.files, args.external, args.output)
    print(sendf.link)

    routes = [
        Route("/{uuid}", sendf.call),
    ]

    app = Starlette(debug=False, routes=routes)

    # setup signal handlers
    def signal_handler(signal: int, frame: types.FrameType | None) -> None:
        nonlocal sendf
        sendf.finalize()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGQUIT, signal_handler)

    uvicorn.run(app, host="0.0.0.0", port=sendf.port, loop="asyncio")
    sendf.finalize()


if __name__ == "__main__":
    main()

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
import asyncio
import os
import signal
import socket
import sys
import tarfile
import threading
import types
import uuid
from collections.abc import AsyncGenerator, Sequence
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, cast
from urllib.parse import quote

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, Response, StreamingResponse
from starlette.routing import Route

import upnp


class StreamCancelled(Exception):
    pass


def get_internal_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 80))
            return sock.getsockname()[0]
    except OSError:
        raise RuntimeError("Failed to get internal ip address :(") from None


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

        archive_names = [os.path.basename(path) for path in self.filepaths]
        if len(archive_names) != len(set(archive_names)):
            raise RuntimeError("Files must have unique names.")

        self.internal_ip = get_internal_ip()
        self.server_socket = self._create_server_socket()
        self.port = self.server_socket.getsockname()[1]

        # do UPnP discovery and port mapping if external access is needed
        try:
            if allow_external:
                igd_device = upnp.discover()
                if igd_device is None:
                    raise RuntimeError("UPnP IGD not found.")
                self.igd_device = igd_device
                self.external_ip: str = upnp.get_external_ip_address(self.igd_device)
                upnp.add_port_mapping(igd_device, self.internal_ip, self.port, self.port)
            else:
                self.external_ip = self.internal_ip
        except Exception:
            self.server_socket.close()
            raise

        self.allow_external = allow_external
        self.output_fname = output_fname

        self.uuid = str(uuid.uuid4())

    def finalize(self) -> None:
        try:
            if self.allow_external:
                print("deleting port mapping...")
                try:
                    upnp.delete_port_mapping(self.igd_device, self.port)
                except Exception as error:
                    print(f"warning: failed to delete port mapping: {error}", file=sys.stderr)
                self.allow_external = False
        finally:
            self.server_socket.close()

    async def _stream_tar_file(self) -> AsyncGenerator[bytes, None]:
        loop = asyncio.get_running_loop()
        chunks: asyncio.Queue[bytes | Exception | None] = asyncio.Queue(maxsize=4)
        cancelled = threading.Event()

        class TarWriter:
            def write(self, data: bytes) -> int:
                if cancelled.is_set():
                    raise StreamCancelled

                chunk = bytes(data)
                future = asyncio.run_coroutine_threadsafe(chunks.put(chunk), loop)
                while True:
                    try:
                        future.result(timeout=0.1)
                        return len(chunk)
                    except FutureTimeoutError:
                        if cancelled.is_set():
                            future.cancel()
                            raise StreamCancelled from None

        def create_archive() -> None:
            try:
                with tarfile.open(fileobj=cast(Any, TarWriter()), mode="w|") as archive:
                    for filepath in self.filepaths:
                        archive.add(filepath, os.path.basename(filepath))
            except StreamCancelled:
                return
            except Exception as error:
                asyncio.run_coroutine_threadsafe(chunks.put(error), loop).result()
            finally:
                if not cancelled.is_set():
                    asyncio.run_coroutine_threadsafe(chunks.put(None), loop).result()

        producer = asyncio.create_task(asyncio.to_thread(create_archive))
        try:
            while (chunk := await chunks.get()) is not None:
                if isinstance(chunk, Exception):
                    raise chunk
                yield chunk
        finally:
            cancelled.set()
            await producer

    async def call(self, request: Request) -> Response:
        # make sure all our files exists
        if not all(map(os.path.exists, self.filepaths)):
            raise RuntimeError

        # if it is a single file, then just return that as a FileResponse
        if len(self.filepaths) == 1 and os.path.isfile(self.filepaths[0]):
            filename = self.output_fname or os.path.basename(self.filepaths[0])
            return FileResponse(self.filepaths[0], filename=filename)

        filename = self.output_fname or "Archive.tar"
        encoded_filename = quote(filename, safe="")
        return StreamingResponse(
            self._stream_tar_file(),
            headers={"content-disposition": f"attachment; filename*=utf-8''{encoded_filename}"},
            media_type="application/x-tar",
        )

    def _create_server_socket(self) -> socket.socket:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(("0.0.0.0", 0))
        server_socket.listen()
        return server_socket

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
        Route(f"/{sendf.uuid}", sendf.call),
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

    config = uvicorn.Config(app, loop="asyncio", log_level="critical", access_log=False)
    uvicorn.Server(config).run(sockets=[sendf.server_socket])
    sendf.finalize()


if __name__ == "__main__":
    main()

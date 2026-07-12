import select
import subprocess
import sys
import tarfile
from io import BytesIO
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit, urlunsplit
from urllib.request import urlopen

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import upnp
from sendf import SendF


def test_basic() -> None:
    sendf = SendF([__file__])
    app = Starlette(debug=True, routes=[Route("/{uuid}", sendf.call)])
    client = TestClient(app)
    response = client.get(f"/{sendf.uuid}")
    assert response.status_code == 200
    assert response.content == Path(__file__).read_bytes()
    assert response.headers["content-disposition"] == 'attachment; filename="tests.py"'
    assert response.headers["content-type"] == "text/x-python; charset=utf-8"


def test_check_file_exists_on_startup() -> None:
    with pytest.raises(RuntimeError, match="not exist"):
        SendF(["nonexistant_file"])


def test_rejects_duplicate_archive_names(tmp_path: Path) -> None:
    first = tmp_path / "first" / "file.txt"
    second = tmp_path / "second" / "file.txt"
    first.parent.mkdir()
    second.parent.mkdir()
    first.touch()
    second.touch()

    with pytest.raises(RuntimeError, match="unique names"):
        SendF([str(first), str(second)])


def test_raises_error_when_upnp_device_not_found() -> None:
    with mock.patch("upnp.discover", return_value=None), pytest.raises(RuntimeError, match="IGD not found"):
        SendF([__file__], allow_external=True)


def test_returns_gone_when_file_disappears(tmp_path: Path) -> None:
    path = tmp_path / "file.txt"
    path.touch()
    sendf = SendF([str(path)])
    path.unlink()
    app = Starlette(routes=[Route(f"/{sendf.uuid}", sendf.call)])

    with TestClient(app) as client:
        response = client.get(f"/{sendf.uuid}")

    sendf.finalize()
    assert response.status_code == 410
    assert response.text == "A requested file is no longer available."


def test_error_when_uuid_is_wrong() -> None:
    sendf = SendF([__file__])
    app = Starlette(debug=True, routes=[Route(f"/{sendf.uuid}", sendf.call)])
    client = TestClient(app)
    response = client.get("/bad-uuid")
    assert response.status_code == 404
    assert response.content == b"Not Found"


def test_single_file_with_custom_name() -> None:
    sendf = SendF([__file__], output_fname="customname.py")
    app = Starlette(debug=True, routes=[Route("/{uuid}", sendf.call)])
    client = TestClient(app)
    response = client.get(f"/{sendf.uuid}")
    assert response.status_code == 200
    assert response.content == Path(__file__).read_bytes()
    assert response.headers["content-disposition"] == 'attachment; filename="customname.py"'
    assert response.headers["content-type"] == "text/x-python; charset=utf-8"


def test_multiple_files() -> None:
    sendf = SendF(["tests.py", "sendf.py"])
    app = Starlette(debug=True, routes=[Route("/{uuid}", sendf.call)])
    client = TestClient(app)
    response = client.get(f"/{sendf.uuid}")
    assert response.status_code == 200
    assert response.headers["content-disposition"] == "attachment; filename*=utf-8''Archive.tar"
    assert response.headers["content-type"] == "application/x-tar"

    # make sure we have a valid tar, and that the tar contains our 2 files
    with tarfile.open(fileobj=BytesIO(response.content)) as f:
        assert isinstance(f, tarfile.TarFile)
        assert set(f.getnames()) == {"tests.py", "sendf.py"}


def test_multiple_files_with_custom_name() -> None:
    sendf = SendF(["tests.py", "sendf.py"], output_fname="customname.tar")
    app = Starlette(debug=True, routes=[Route("/{uuid}", sendf.call)])
    client = TestClient(app)
    response = client.get(f"/{sendf.uuid}")
    assert response.status_code == 200
    assert response.headers["content-disposition"] == "attachment; filename*=utf-8''customname.tar"
    assert response.headers["content-type"] == "application/x-tar"

    # make sure we have a valid tar, and that the tar contains our 2 files
    with tarfile.open(fileobj=BytesIO(response.content)) as f:
        assert isinstance(f, tarfile.TarFile)
        assert set(f.getnames()) == {"tests.py", "sendf.py"}


def test_discovery_skips_unrelated_upnp_devices() -> None:
    unrelated_response = b"HTTP/1.1 200 OK\r\nLOCATION: http://speaker/device.xml\r\n\r\n"
    router_response = b"HTTP/1.1 200 OK\r\nLOCATION: http://router/device.xml\r\n\r\n"
    discovered_device = upnp.Device(
        "http://router/control",
        "urn:schemas-upnp-org:service:WANIPConnection:1",
    )
    sock = mock.MagicMock()
    sock.__enter__.return_value = sock
    sock.recvfrom.side_effect = [
        (unrelated_response, ("192.168.1.2", 1900)),
        (router_response, ("192.168.1.1", 1900)),
    ]

    with (
        mock.patch("upnp.socket.socket", return_value=sock),
        mock.patch("upnp._find_services", side_effect=[None, discovered_device]) as find_services,
    ):
        assert upnp.discover() == discovered_device

    assert find_services.call_args_list == [
        mock.call("http://speaker/device.xml"),
        mock.call("http://router/device.xml"),
    ]


@pytest.mark.parametrize(
    "service_type",
    [
        "urn:schemas-upnp-org:service:WANIPConnection:1",
        "urn:schemas-upnp-org:service:WANIPConnection:2",
        "urn:schemas-upnp-org:service:WANPPPConnection:1",
    ],
)
def test_soap_request_uses_discovered_service_type(service_type: str) -> None:
    device = upnp.Device("http://router/control", service_type)
    response = mock.MagicMock(status=200)
    response.__enter__.return_value = response

    with mock.patch("upnp.urlopen", return_value=response) as urlopen:
        upnp.add_port_mapping(device, "192.168.1.2", 1234, 1234)

    request = urlopen.call_args.args[0]
    assert request.full_url == device.control_url
    assert request.get_header("Soapaction") == f"{service_type}#AddPortMapping"
    assert request.data.startswith(b'<?xml version="1.0"?>')
    assert f'xmlns:m="{service_type}"'.encode() in request.data


def test_cli_serves_file_and_prints_only_link(tmp_path: Path) -> None:
    path = tmp_path / "file.txt"
    path.write_text("file contents")
    process = subprocess.Popen(
        [sys.executable, "sendf.py", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None

    try:
        readable, _, _ = select.select([process.stdout], [], [], 5)
        assert readable, "sendf did not print a link"
        link = process.stdout.readline().strip()
        parsed_link = urlsplit(link)
        local_link = urlunsplit((parsed_link.scheme, f"127.0.0.1:{parsed_link.port}", parsed_link.path, "", ""))
        with urlopen(local_link, timeout=5) as response:
            assert response.read() == b"file contents"
    finally:
        process.terminate()
        _stdout, stderr = process.communicate(timeout=5)

    assert stderr == ""


def test_send_folder() -> None:
    sendf = SendF(["tests/stuff"])
    app = Starlette(debug=True, routes=[Route("/{uuid}", sendf.call)])
    client = TestClient(app)
    response = client.get(f"/{sendf.uuid}")
    assert response.status_code == 200
    assert response.headers["content-disposition"] == "attachment; filename*=utf-8''Archive.tar"
    assert response.headers["content-type"] == "application/x-tar"

    # make sure we have a valid tar, and that the tar contains our 2 files
    with tarfile.open(fileobj=BytesIO(response.content)) as f:
        assert isinstance(f, tarfile.TarFile)
        assert f.getnames() == ["stuff", "stuff/a", "stuff/b.dump", "stuff/c.txt"]

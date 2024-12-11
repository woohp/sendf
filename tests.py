import tarfile
from io import BytesIO
from pathlib import Path
from unittest import mock

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

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


def test_raises_error_when_upnp_device_not_found() -> None:
    with mock.patch("upnp.discover", return_value=None), pytest.raises(RuntimeError, match="IGD not found"):
        SendF([__file__], allow_external=True)


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
    assert response.headers["content-disposition"] == 'attachment; filename="Archive.tar"'
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
    assert response.headers["content-disposition"] == 'attachment; filename="customname.tar"'
    assert response.headers["content-type"] == "application/x-tar"

    # make sure we have a valid tar, and that the tar contains our 2 files
    with tarfile.open(fileobj=BytesIO(response.content)) as f:
        assert isinstance(f, tarfile.TarFile)
        assert set(f.getnames()) == {"tests.py", "sendf.py"}


def test_send_folder() -> None:
    sendf = SendF(["tests/stuff"])
    app = Starlette(debug=True, routes=[Route("/{uuid}", sendf.call)])
    client = TestClient(app)
    response = client.get(f"/{sendf.uuid}")
    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="Archive.tar"'
    assert response.headers["content-type"] == "application/x-tar"

    # make sure we have a valid tar, and that the tar contains our 2 files
    with tarfile.open(fileobj=BytesIO(response.content)) as f:
        assert isinstance(f, tarfile.TarFile)
        assert f.getnames() == ["stuff", "stuff/a", "stuff/b.dump", "stuff/c.txt"]

import tarfile
from io import BytesIO
from unittest import TestCase, mock

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from sendf import SendF


class SendFTestCase(TestCase):
    _file_content: bytes

    @classmethod
    def setUpClass(cls: type[SendFTestCase]) -> None:
        super().setUpClass()
        with open(__file__, "rb") as f:
            cls._file_content = f.read()

    def test_basic(self) -> None:
        sendf = SendF([__file__])
        app = Starlette(debug=True, routes=[Route("/{uuid}", sendf.call)])
        client = TestClient(app)
        response = client.get(f"/{sendf.uuid}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, self._file_content)
        self.assertEqual(response.headers["content-disposition"], 'attachment; filename="tests.py"')
        self.assertEqual(response.headers["content-type"], "text/x-python; charset=utf-8")

    def test_check_file_exists_on_startup(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "not exist"):
            SendF(["nonexistant_file"])

    def test_raises_error_when_upnp_device_not_found(self) -> None:
        with mock.patch("upnp.discover", return_value=None), self.assertRaisesRegex(RuntimeError, "IGD not found"):
            SendF([__file__], allow_external=True)

    def test_error_when_uuid_is_wrong(self) -> None:
        sendf = SendF([__file__])
        app = Starlette(debug=True, routes=[Route("/{uuid}", sendf.call)])
        client = TestClient(app)
        response = client.get("/bad-uuid")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"Not Found")

    def test_single_file_with_custom_name(self) -> None:
        sendf = SendF([__file__], output_fname="customname.py")
        app = Starlette(debug=True, routes=[Route("/{uuid}", sendf.call)])
        client = TestClient(app)
        response = client.get(f"/{sendf.uuid}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, self._file_content)
        self.assertEqual(
            response.headers["content-disposition"],
            'attachment; filename="customname.py"',
        )
        self.assertEqual(response.headers["content-type"], "text/x-python; charset=utf-8")

    def test_multiple_files(self) -> None:
        sendf = SendF(["tests.py", "sendf.py"])
        app = Starlette(debug=True, routes=[Route("/{uuid}", sendf.call)])
        client = TestClient(app)
        response = client.get(f"/{sendf.uuid}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["content-disposition"],
            'attachment; filename="Archive.tar"',
        )
        self.assertEqual(response.headers["content-type"], "application/x-tar")

        # make sure we have a valid tar, and that the tar contains our 2 files
        f = tarfile.open(fileobj=BytesIO(response.content))
        self.assertIsInstance(f, tarfile.TarFile)
        self.assertEqual(set(f.getnames()), {"tests.py", "sendf.py"})

    def test_multiple_files_with_custom_name(self) -> None:
        sendf = SendF(["tests.py", "sendf.py"], output_fname="customname.tar")
        app = Starlette(debug=True, routes=[Route("/{uuid}", sendf.call)])
        client = TestClient(app)
        response = client.get(f"/{sendf.uuid}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["content-disposition"],
            'attachment; filename="customname.tar"',
        )
        self.assertEqual(response.headers["content-type"], "application/x-tar")

        # make sure we have a valid tar, and that the tar contains our 2 files
        f = tarfile.open(fileobj=BytesIO(response.content))
        self.assertIsInstance(f, tarfile.TarFile)
        self.assertEqual(set(f.getnames()), {"tests.py", "sendf.py"})

    def test_send_folder(self) -> None:
        sendf = SendF(["scripts"])
        app = Starlette(debug=True, routes=[Route("/{uuid}", sendf.call)])
        client = TestClient(app)
        response = client.get(f"/{sendf.uuid}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["content-disposition"],
            'attachment; filename="Archive.tar"',
        )
        self.assertEqual(response.headers["content-type"], "application/x-tar")

        # make sure we have a valid tar, and that the tar contains our 2 files
        f = tarfile.open(fileobj=BytesIO(response.content))
        self.assertIsInstance(f, tarfile.TarFile)
        self.assertEqual(f.getnames(), ["scripts", "scripts/sendf"])

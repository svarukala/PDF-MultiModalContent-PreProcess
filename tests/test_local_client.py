import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import test_local


class LocalClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_settings_preserve_environment_overrides(self):
        (self.root / "local.settings.json").write_text(
            json.dumps({"Values": {"EXISTING": "file", "NEW": "local"}}),
            encoding="utf-8-sig",
        )
        with patch.object(test_local, "PROJECT_DIR", self.root):
            with patch.dict(os.environ, {"EXISTING": "environment"}, clear=True):
                test_local.load_local_settings()
                self.assertEqual(os.environ["EXISTING"], "environment")
                self.assertEqual(os.environ["NEW"], "local")

    def test_missing_settings_allow_environment_only_configuration(self):
        with patch.object(test_local, "PROJECT_DIR", self.root):
            test_local.load_local_settings()

    def test_download_uses_emulator_url_and_selected_output(self):
        service = Mock()
        blob = service.get_container_client.return_value.get_blob_client.return_value
        blob.download_blob.return_value.readall.return_value = b"# Converted PDF"
        output = self.root / "output"
        with patch.dict(os.environ, {
            "AZURE_STORAGE_CONNECTION_STRING": "UseDevelopmentStorage=true",
            "PDF_OUTPUT_CONTAINER": "pdf-output",
        }, clear=True):
            with patch.object(test_local.BlobServiceClient, "from_connection_string",
                              return_value=service) as factory:
                test_local.download_md(
                    "http://127.0.0.1:10000/devstoreaccount1/pdf-output/report%20one.md",
                    output,
                )
        factory.assert_called_once_with("UseDevelopmentStorage=true")
        service.get_container_client.assert_called_once_with("pdf-output")
        service.get_container_client.return_value.get_blob_client.assert_called_once_with(
            "report one.md"
        )
        self.assertEqual((output / "report one.md").read_bytes(), b"# Converted PDF")

    def test_download_requires_storage_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "AZURE_STORAGE_CONNECTION_STRING"):
                test_local.download_md("http://localhost/pdf-output/report.md")

    def test_download_rejects_wrong_container(self):
        with patch.dict(os.environ, {
            "AZURE_STORAGE_CONNECTION_STRING": "UseDevelopmentStorage=true",
            "PDF_OUTPUT_CONTAINER": "pdf-output",
        }, clear=True):
            with self.assertRaisesRegex(ValueError, "configured container"):
                test_local.download_md("http://localhost/other/report.md")

    def run_client(self, response, status=None):
        pdf = self.root / "document.pdf"
        pdf.write_bytes(b"%PDF-1.7\n")
        with patch("sys.argv", ["test_local.py", str(pdf)]):
            with patch.object(test_local, "load_local_settings"):
                with patch.object(test_local.requests, "post", return_value=response):
                    with patch.object(test_local.requests, "get", return_value=status):
                        with patch.object(test_local, "download_md") as download:
                            return test_local.main(), download

    def test_rejected_upload_exits_nonzero(self):
        result, download = self.run_client(Mock(status_code=400, text="Invalid PDF"))
        self.assertEqual(result, 1)
        download.assert_not_called()

    def test_failed_orchestration_exits_nonzero(self):
        response = Mock(status_code=202)
        response.json.return_value = {"statusQueryGetUri": "http://localhost/status"}
        status = Mock()
        status.json.return_value = {"runtimeStatus": "Failed", "output": "AI not configured"}
        result, download = self.run_client(response, status)
        self.assertEqual(result, 1)
        download.assert_not_called()
        status.raise_for_status.assert_called_once()

    def test_completed_orchestration_downloads_markdown(self):
        response = Mock(status_code=202)
        response.json.return_value = {"statusQueryGetUri": "http://localhost/status"}
        status = Mock()
        status.json.return_value = {
            "runtimeStatus": "Completed",
            "output": {"status": "completed", "blob_url": "http://localhost/pdf-output/report.md"},
        }
        result, download = self.run_client(response, status)
        self.assertEqual(result, 0)
        download.assert_called_once_with(
            "http://localhost/pdf-output/report.md", test_local.OUTPUT_DIR
        )


if __name__ == "__main__":
    unittest.main()

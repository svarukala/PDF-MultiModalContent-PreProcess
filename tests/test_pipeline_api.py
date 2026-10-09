import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import azure.functions as func
from azure.core.exceptions import ResourceNotFoundError

import function_app


FUNCTIONS = {
    name: getattr(function_app, name).build().get_user_function()
    for name in ("job_status", "job_file", "parse_pdf")
}
FUNCTIONS["job_status"] = FUNCTIONS["job_status"].client_function
JOB_ID = "a" * 32


class PipelineApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_job_status_decodes_input_and_exposes_only_summary(self):
        client = Mock()
        client.get_status = AsyncMock(return_value=SimpleNamespace(
            name="pdf_processing_orchestrator",
            input_=json.dumps({"job_id": JOB_ID, "original_filename": "sample.pdf"}),
            runtime_status=SimpleNamespace(name="Running"), output=None,
            custom_status={"interim_ready": True, "completed": 2, "total": 3},
        ))
        req = func.HttpRequest("GET", "http://localhost/api/jobs/" + JOB_ID,
                               body=b"", route_params={"job_id": JOB_ID})
        response = await FUNCTIONS["job_status"](req, client)
        body = json.loads(response.get_body())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["filename"], "sample.pdf")
        self.assertEqual(body["files"]["interim"], f"/api/jobs/{JOB_ID}/files/interim")
        self.assertIsNone(body["files"]["final"])
        self.assertNotIn("input", body)
        client.get_status.assert_awaited_once_with(JOB_ID, show_input=True)

    async def test_invalid_job_rejected_before_storage_or_status_lookup(self):
        client = Mock()
        req = func.HttpRequest("GET", "http://localhost/api/jobs/invalid",
                               body=b"", route_params={"job_id": "../secret"})
        response = await FUNCTIONS["job_status"](req, client)
        self.assertEqual(response.status_code, 400)
        client.get_status.assert_not_called()

    async def test_unknown_job(self):
        client = Mock()
        client.get_status = AsyncMock(return_value=None)
        req = func.HttpRequest("GET", "http://localhost/api/jobs/" + JOB_ID,
                               body=b"", route_params={"job_id": JOB_ID})
        self.assertEqual((await FUNCTIONS["job_status"](req, client)).status_code, 404)

    def test_artifacts_are_plain_text_and_do_not_accept_arbitrary_paths(self):
        blob_service = Mock()
        blob_service.get_blob_client.return_value.download_blob.return_value.readall.return_value = b"<script>alert(1)</script>"
        req = func.HttpRequest("GET", "http://localhost/file", body=b"",
                               route_params={"job_id": JOB_ID, "kind": "interim"})
        with patch.object(function_app, "_get_blob_service", return_value=blob_service):
            response = FUNCTIONS["job_file"](req)
        self.assertEqual(response.mimetype, "text/plain")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        req = func.HttpRequest("GET", "http://localhost/file", body=b"",
                               route_params={"job_id": JOB_ID, "kind": "../../private"})
        self.assertEqual(FUNCTIONS["job_file"](req).status_code, 400)

    def test_missing_artifact_returns_not_found(self):
        blob_service = Mock()
        blob_service.get_blob_client.return_value.download_blob.side_effect = ResourceNotFoundError("not found")
        req = func.HttpRequest("GET", "http://localhost/file", body=b"",
                               route_params={"job_id": JOB_ID, "kind": "final"})
        with patch.object(function_app, "_get_blob_service", return_value=blob_service):
            self.assertEqual(FUNCTIONS["job_file"](req).status_code, 404)

    def test_parse_keeps_exact_raw_markdown_and_unicode_spans(self):
        blob_service = Mock()
        blob_service.get_container_client.return_value.get_blob_client.return_value.download_blob.return_value.readall.return_value = b"%PDF-"
        di = Mock()
        poller = di.begin_analyze_document.return_value
        poller.details = {"operation_id": "operation"}
        poller.result.return_value = SimpleNamespace(
            content="Text \U0001f600 <figure>Chart</figure>",
            figures=[SimpleNamespace(id="1.1", caption=None,
                                     spans=[SimpleNamespace(offset=7, length=22)])],
        )
        di.get_analyze_result_figure.return_value = [b"png"]
        with patch.object(function_app, "_get_blob_service", return_value=blob_service), \
                patch.object(function_app, "_get_di_client", return_value=di), \
                patch.object(function_app, "_save_markdown") as save:
            result = FUNCTIONS["parse_pdf"]({"container": "pdf-input", "blob_name": "file", "job_id": JOB_ID})
        self.assertEqual(di.begin_analyze_document.call_args.kwargs["string_index_type"], "unicodeCodePoint")
        save.assert_called_once_with(poller.result.return_value.content, f"{JOB_ID}/interim.md")
        self.assertEqual(result["markdown"], poller.result.return_value.content)
        self.assertEqual(result["figures"][0]["spans"], [{"offset": 7, "length": 22}])


if __name__ == "__main__":
    unittest.main()

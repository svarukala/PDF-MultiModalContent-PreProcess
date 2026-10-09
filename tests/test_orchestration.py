import json
import unittest
from pathlib import Path
from unittest.mock import Mock

import function_app


class OrchestrationTests(unittest.TestCase):
    def test_activity_concurrency_is_bounded(self):
        host_path = Path(function_app.__file__).with_name("host.json")
        host = json.loads(host_path.read_text(encoding="utf-8"))
        self.assertEqual(host["extensions"]["durableTask"]["maxConcurrentActivityFunctions"], 2)

    def test_figure_retries_wait_longer_without_changing_storage_retries(self):
        orchestrator = function_app.pdf_processing_orchestrator.build().get_user_function().orchestrator_function
        context = Mock()
        context.get_input.return_value = {
            "blob_name": "sample.pdf",
            "original_filename": "sample.pdf",
            "container": "pdf-input",
        }
        generator = orchestrator(context)
        next(generator)
        generator.send({
            "markdown": "![](figures/1.1)",
            "figures": [{"id": "1.1", "base64_png": "image"}],
        })
        figure_call = context.call_activity_with_retry.call_args
        self.assertEqual(figure_call.args[0], "describe_figure")
        figure_retry = figure_call.kwargs["retry_options"]
        self.assertEqual(figure_retry.first_retry_interval_in_milliseconds, 60000)
        self.assertEqual(figure_retry.max_number_of_attempts, 3)

        generator.send([{"figure_id": "1.1", "description": "Chart description"}])
        generator.send("Final Markdown")
        storage_call = context.call_activity_with_retry.call_args
        self.assertEqual(storage_call.args[0], "save_to_blob")
        storage_retry = storage_call.kwargs["retry_options"]
        self.assertEqual(storage_retry.first_retry_interval_in_milliseconds, 5000)
        self.assertEqual(storage_retry.max_number_of_attempts, 3)
        with self.assertRaises(StopIteration) as completed:
            generator.send("http://localhost/pdf-output/sample.md")
        self.assertEqual(completed.exception.value["figures_processed"], 1)
        self.assertEqual(completed.exception.value["figures_described"], 1)

    def test_batches_preserve_all_figures_and_report_progress(self):
        orchestrator = function_app.pdf_processing_orchestrator.build().get_user_function().orchestrator_function
        context = Mock()
        context.get_input.return_value = {
            "blob_name": "sample.pdf", "original_filename": "sample.pdf",
            "container": "pdf-input", "job_id": "b" * 32,
        }
        generator = orchestrator(context)
        next(generator)
        generator.send({"markdown": "text", "figures": [
            {"id": str(i), "spans": []} for i in range(3)
        ]})
        self.assertEqual(context.call_activity_with_retry.call_count, 2)
        generator.send([
            {"figure_id": "0", "description": "First", "status": "described"},
            {"figure_id": "1", "description": "Unavailable", "status": "fallback"},
        ])
        self.assertEqual(context.call_activity_with_retry.call_count, 3)
        generator.send([{"figure_id": "2", "description": "Last", "status": "described"}])
        assemble_payload = context.call_activity.call_args.args[1]
        self.assertEqual(len(assemble_payload["figures"]), 3)
        self.assertEqual(len(assemble_payload["descriptions"]), 3)
        generator.send("assembled")
        with self.assertRaises(StopIteration) as completed:
            generator.send("blob-url")
        self.assertEqual(completed.exception.value["figures_described"], 2)
        self.assertEqual(completed.exception.value["figures_with_fallback"], 1)
        final_progress = context.set_custom_status.call_args.args[0]
        self.assertEqual(final_progress["stage"], "completed")
        self.assertEqual(final_progress["completed"], 3)
        self.assertLessEqual(len(final_progress["events"]), 12)


if __name__ == "__main__":
    unittest.main()

import unittest

from figure_markdown import assemble_figures, surrounding_text


class FigureMarkdownTests(unittest.TestCase):
    def test_actual_figure_markup_and_unicode_offsets(self):
        raw = "# Start \U0001f600\n\n<figure>\nChart OCR\n<figcaption>Caption</figcaption>\n</figure>\n\nKeep this table."
        offset = raw.index("Chart OCR")
        figures = [{"id": "1.1", "spans": [{"offset": offset, "length": len("Chart OCR")}]}]
        descriptions = [{"figure_id": "1.1", "description": "Revenue increased 20%."}]
        result = assemble_figures(raw, figures, descriptions)
        self.assertIn("# Start \U0001f600", result)
        self.assertIn("Revenue increased 20%.", result)
        self.assertIn("Keep this table.", result)
        self.assertNotIn("<figure>", result)
        self.assertNotEqual(raw, result)
        self.assertIn("Chart OCR", surrounding_text(raw, figures[0]))

    def test_shared_block_inserts_all_figures_once(self):
        raw = "Before\n<figure>ABCD</figure>\nAfter"
        start = raw.index("ABCD")
        figures = [
            {"id": "1.1", "spans": [{"offset": start, "length": 2}]},
            {"id": "1.2", "spans": [{"offset": start + 2, "length": 2}]},
        ]
        result = assemble_figures(raw, figures, [
            {"figure_id": "1.1", "description": "First image."},
            {"figure_id": "1.2", "description": "Second image."},
        ])
        self.assertEqual(result.count("First image."), 1)
        self.assertEqual(result.count("Second image."), 1)
        self.assertTrue(result.startswith("Before"))
        self.assertTrue(result.endswith("After"))

    def test_unpositioned_figures_are_not_lost_or_assigned_by_order(self):
        raw = "<figure>Unrelated content</figure>"
        result = assemble_figures(raw, [{"id": "2.1", "spans": []}], [
            {"figure_id": "2.1", "description": "Unpositioned image description."},
        ])
        self.assertTrue(result.startswith(raw))
        self.assertIn("## Additional figure descriptions", result)
        self.assertIn("Unpositioned image description.", result)

    def test_legacy_placeholders(self):
        for raw in ("Before ![](figures/1.1) After",
                    "Before <figure>![](figures/1.1)</figure> After"):
            with self.subTest(raw=raw):
                result = assemble_figures(raw, [], [{"figure_id": "1.1", "description": "Description"}])
                self.assertIn("Description", result)
                self.assertNotIn("figures/1.1", result)

    def test_multiple_spans_do_not_duplicate_description(self):
        result = assemble_figures("A middle B", [{
            "id": "1.1", "spans": [{"offset": 0, "length": 1}, {"offset": 9, "length": 1}],
        }], [{"figure_id": "1.1", "description": "Unique description."}])
        self.assertEqual(result.count("Unique description."), 1)
        self.assertIn(" middle ", result)

    def test_missing_or_duplicate_descriptions_fail_explicitly(self):
        with self.assertRaises(ValueError):
            assemble_figures("text", [{"id": "1.1"}], [])
        with self.assertRaises(ValueError):
            assemble_figures("text", [], [{"figure_id": "1", "description": "A"}] * 2)

    def test_invalid_span_fails_explicitly(self):
        for span in ({"offset": -1, "length": 2}, {"offset": 0, "length": 99}):
            with self.subTest(span=span), self.assertRaises(ValueError):
                assemble_figures("text", [{"id": "1", "spans": [span]}],
                                 [{"figure_id": "1", "description": "A"}])

    def test_text_only_document_unchanged(self):
        self.assertEqual(assemble_figures("# Text only", [], []), "# Text only")


if __name__ == "__main__":
    unittest.main()

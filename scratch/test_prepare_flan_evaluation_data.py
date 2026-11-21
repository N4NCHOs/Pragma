"""Offline tests for auditable FLAN preprocessing snapshot preparation.

Only temporary fixtures are written. No model, database, scraper, or network
service is loaded or called. Fixtures exercise boundaries, not evaluation data.
"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import prepare_flan_evaluation_data as preparation
from article_preprocessing import EMPTY_FOOTER_HEADING, KNOWN_PROMOTIONAL_FOOTER


FOOTER = KNOWN_PROMOTIONAL_FOOTER + "\n" + EMPTY_FOOTER_HEADING


def article(article_id: str, **updates):
    value = {
        "dataset_article_id": article_id,
        "title": "Ethereum’s technical update",
        "full_body": "Ethereum published a technical update involving $4 million.",
        "url": f"https://example.invalid/{article_id}",
        "qualification_status": "qualified",
        "is_redundant": False,
        "metadata": {"tags": ["ETH", "東京"], "source": {"attempts": 2}},
    }
    value.update(updates)
    return value


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class PrepareArticlesTests(unittest.TestCase):
    def test_preserves_ids_order_nested_metadata_and_does_not_mutate_source(self):
        articles = [article("z", full_body="Original.\n" + FOOTER), article("a")]
        before = deepcopy(articles)
        cleaned, report, changes = preparation.prepare_articles(articles)
        self.assertEqual(articles, before)
        self.assertEqual([item["dataset_article_id"] for item in cleaned], ["z", "a"])
        self.assertEqual(len(cleaned), len(articles))
        self.assertEqual(cleaned[0]["full_body"], "Original.")
        for original, result in zip(articles, cleaned):
            self.assertIsNot(original, result)
            self.assertEqual(set(original), set(result))
            self.assertEqual(
                {key: value for key, value in original.items() if key != "full_body"},
                {key: value for key, value in result.items() if key != "full_body"},
            )
        self.assertEqual(report["changed_count"], 1)
        self.assertEqual(report["unchanged_count"], 1)
        self.assertEqual(len(changes), 1)

    def test_unmatched_article_body_is_byte_identical_including_whitespace(self):
        body = "\t São Paulo: BTC $131; Ethereum’s update.\r\n\n  "
        cleaned, report, changes = preparation.prepare_articles([article("a", full_body=body)])
        self.assertEqual(cleaned[0]["full_body"].encode("utf-8"), body.encode("utf-8"))
        self.assertEqual(report["changed_count"], 0)
        self.assertEqual(report["unchanged_count"], 1)
        self.assertEqual(changes, [])

    def test_audit_hashes_counts_and_removed_suffix_reconstruct_source(self):
        body = "\n  Bitcoin at $131.  \n" + FOOTER + "\n" + FOOTER + "\n"
        articles = [article("one", full_body=body), article("two", full_body="Unchanged.")]
        cleaned, report, changes = preparation.prepare_articles(articles)
        audit, unchanged_audit = report["articles"]
        change = changes[0]
        self.assertEqual(cleaned[0]["full_body"] + change["removed_text"], body)
        self.assertEqual(audit["article_index"], 1)
        self.assertEqual(audit["dataset_article_id"], "one")
        self.assertTrue(audit["changed"])
        self.assertEqual(audit["removed_blocks"], 2)
        self.assertEqual(audit["removed_characters"], len(change["removed_text"]))
        self.assertEqual(audit["original_body_characters"], len(body))
        self.assertEqual(audit["cleaned_body_characters"], len(cleaned[0]["full_body"]))
        self.assertEqual(audit["original_body_sha256"], text_hash(body))
        self.assertEqual(audit["cleaned_body_sha256"], text_hash(cleaned[0]["full_body"]))
        self.assertEqual(unchanged_audit["article_index"], 2)
        self.assertFalse(unchanged_audit["changed"])
        self.assertEqual(unchanged_audit["removed_blocks"], 0)
        self.assertEqual(report["removed_footer_blocks"], 2)
        self.assertEqual(report["removed_characters"], audit["removed_characters"])
        self.assertEqual(report["article_count"], 2)
        self.assertEqual(report["original_dataset_hash"], preparation.compute_dataset_hash(articles))
        self.assertEqual(report["cleaned_dataset_hash"], preparation.compute_dataset_hash(cleaned))
        self.assertNotEqual(report["original_dataset_hash"], report["cleaned_dataset_hash"])

    def test_change_examples_use_real_before_and_after_tails(self):
        body = ("Long body with names and numbers. " * 30) + "\n" + FOOTER
        cleaned, _report, changes = preparation.prepare_articles([article("a", full_body=body)])
        self.assertEqual(changes[0]["before_tail"], body[-500:])
        self.assertEqual(changes[0]["after_tail"], cleaned[0]["full_body"][-500:])
        self.assertEqual(changes[0]["dataset_article_id"], "a")

    def test_empty_cleaned_body_is_flagged_but_not_silently_dropped(self):
        cleaned, report, changes = preparation.prepare_articles([article("empty", full_body=FOOTER)])
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0]["full_body"], "")
        self.assertEqual(report["empty_after_cleaning_ids"], ["empty"])
        self.assertEqual(report["changed_count"], 1)
        self.assertEqual(len(changes), 1)

    def test_stored_qualification_flags_are_not_recomputed(self):
        _cleaned, report, _changes = preparation.prepare_articles([article("a")])
        self.assertTrue(report["article_order_and_ids_preserved"])
        self.assertFalse(report["asset_filter_recomputed"])
        self.assertFalse(report["novelty_recomputed"])
        self.assertFalse(report["cohort_selected"])
        self.assertTrue(report["limitations"])

    def test_optional_missing_qualification_metadata_is_preserved_as_missing(self):
        item = article("a")
        del item["qualification_status"]
        del item["is_redundant"]
        cleaned, _report, _changes = preparation.prepare_articles([item])
        self.assertNotIn("qualification_status", cleaned[0])
        self.assertNotIn("is_redundant", cleaned[0])

    def test_non_list_empty_list_or_non_object_records_fail(self):
        for invalid in (None, {}, "not a list", [], [None], ["article"], [[article("a")]]):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    preparation.prepare_articles(invalid)

    def test_missing_empty_or_non_string_ids_fail(self):
        for invalid in (None, "", "  ", 3, False, [], {}):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    preparation.prepare_articles([article(invalid)])
        item = article("a")
        del item["dataset_article_id"]
        with self.assertRaises(ValueError):
            preparation.prepare_articles([item])

    def test_duplicate_ids_fail_even_if_article_contents_differ(self):
        with self.assertRaisesRegex(ValueError, "duplicate dataset_article_id"):
            preparation.prepare_articles([article("same"), article("same", title="Different story")])

    def test_missing_empty_or_non_string_title_and_body_fail(self):
        for field in ("title", "full_body"):
            for invalid in (None, "", " \t\r\n", 5, False, [], {}):
                with self.subTest(field=field, invalid=invalid):
                    with self.assertRaises(ValueError):
                        preparation.prepare_articles([article("a", **{field: invalid})])
            missing = article("a")
            del missing[field]
            with self.assertRaises(ValueError):
                preparation.prepare_articles([missing])

    def test_non_qualified_status_and_any_non_false_redundancy_fail(self):
        for invalid in (None, "redundant", "rejected_asset_filter", "Qualified", True, 0):
            with self.subTest(status=invalid):
                with self.assertRaises(ValueError):
                    preparation.prepare_articles([article("a", qualification_status=invalid)])
        for invalid in (None, True, 0, "false", "False", []):
            with self.subTest(redundant=invalid):
                with self.assertRaises(ValueError):
                    preparation.prepare_articles([article("a", is_redundant=invalid)])


class ExportSnapshotTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "live" / "qualified_news.json"
        self.source.parent.mkdir()
        self.items = [article("z", full_body="Ethereum’s update.\n" + FOOTER), article("a")]
        self.raw_bytes = (json.dumps(self.items, ensure_ascii=False, indent=3) + "\r\n").encode("utf-8")
        self.source.write_bytes(self.raw_bytes)
        self.destination = self.root / "snapshots" / "first"

    def test_export_preserves_raw_bytes_and_source_and_outputs_match_hashes(self):
        outcome = preparation.export_snapshot(self.source, self.destination)
        self.assertEqual(self.source.read_bytes(), self.raw_bytes)
        self.assertEqual((self.destination / "qualified_news_raw.json").read_bytes(), self.raw_bytes)
        cleaned = json.loads((self.destination / "qualified_news_cleaned.json").read_bytes())
        changes = json.loads((self.destination / "changes.json").read_bytes())
        report = json.loads((self.destination / "preprocessing_report.json").read_bytes())
        self.assertEqual(report, outcome["report"])
        self.assertEqual(changes, outcome["changes"])
        self.assertEqual(outcome["output_dir"], str(self.destination.resolve()))
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["source_file_sha256"], hashlib.sha256(self.raw_bytes).hexdigest())
        self.assertEqual(report["original_dataset_hash"], preparation.compute_dataset_hash(self.items))
        self.assertEqual(report["cleaned_dataset_hash"], preparation.compute_dataset_hash(cleaned))
        self.assertEqual(report["source_path"], str(self.source.resolve()))
        self.assertEqual([item["dataset_article_id"] for item in cleaned], ["z", "a"])
        self.assertEqual(cleaned[0]["full_body"] + changes[0]["removed_text"], self.items[0]["full_body"])
        self.assertEqual(set(path.name for path in self.destination.iterdir()), {
            "qualified_news_raw.json", "qualified_news_cleaned.json", "changes.json",
            "preprocessing_report.json",
        })

    def test_preview_does_not_create_destination_or_parent(self):
        outcome = preparation.export_snapshot(self.source, self.destination, preview=True)
        self.assertEqual(outcome["report"]["status"], "preview")
        self.assertIsNone(outcome["output_dir"])
        self.assertFalse(self.destination.parent.exists())
        self.assertEqual(self.source.read_bytes(), self.raw_bytes)

    def test_preview_does_not_touch_existing_destination(self):
        self.destination.mkdir(parents=True)
        marker = self.destination / "untouched.txt"
        marker.write_text("Keep me.", encoding="utf-8")
        preparation.export_snapshot(self.source, self.destination, preview=True)
        self.assertEqual(marker.read_text(encoding="utf-8"), "Keep me.")
        self.assertEqual(list(self.destination.iterdir()), [marker])

    def test_repeat_export_refuses_overwrite_and_keeps_first_snapshot(self):
        preparation.export_snapshot(self.source, self.destination)
        before = {path.name: path.read_bytes() for path in self.destination.iterdir()}
        with self.assertRaises(FileExistsError):
            preparation.export_snapshot(self.source, self.destination)
        after = {path.name: path.read_bytes() for path in self.destination.iterdir()}
        self.assertEqual(after, before)
        self.assertEqual(self.source.read_bytes(), self.raw_bytes)

    def test_destination_cannot_equal_source_or_be_its_ancestor(self):
        for destination in (self.source, self.source.parent, self.root):
            with self.subTest(destination=destination):
                with self.assertRaisesRegex(ValueError, "source file or an ancestor"):
                    preparation.export_snapshot(self.source, destination)
                self.assertEqual(self.source.read_bytes(), self.raw_bytes)

    def test_invalid_json_or_schema_fails_before_any_destination_write(self):
        invalid_sources = (b"{not json", b"[]", b"{}", b"[null]", b'[{"dataset_article_id":"a"}]')
        for raw_bytes in invalid_sources:
            with self.subTest(raw_bytes=raw_bytes):
                self.source.write_bytes(raw_bytes)
                with self.assertRaises(ValueError):
                    preparation.export_snapshot(self.source, self.destination)
                self.assertFalse(self.destination.parent.exists())
                self.assertEqual(self.source.read_bytes(), raw_bytes)

    def test_nonfinite_metadata_fails_before_destination_creation(self):
        invalid = [article("a", score=float("nan"))]
        raw_bytes = json.dumps(invalid).encode("utf-8")
        self.source.write_bytes(raw_bytes)
        with self.assertRaises(ValueError):
            preparation.export_snapshot(self.source, self.destination)
        self.assertFalse(self.destination.parent.exists())
        self.assertEqual(self.source.read_bytes(), raw_bytes)

    def test_missing_source_does_not_create_destination(self):
        with self.assertRaises(FileNotFoundError):
            preparation.export_snapshot(self.root / "missing.json", self.destination)
        self.assertFalse(self.destination.parent.exists())

    def test_default_output_creates_distinct_snapshots_under_configured_root(self):
        output_root = self.root / "evaluation"
        with patch.object(preparation, "DEFAULT_OUTPUT_ROOT", output_root):
            first = preparation.export_snapshot(self.source)
            second = preparation.export_snapshot(self.source)
        first_path = Path(first["output_dir"])
        second_path = Path(second["output_dir"])
        self.assertNotEqual(first_path, second_path)
        self.assertEqual(first_path.parent, output_root.resolve())
        self.assertEqual(second_path.parent, output_root.resolve())
        self.assertTrue((first_path / "preprocessing_report.json").is_file())
        self.assertTrue((second_path / "preprocessing_report.json").is_file())

    def test_no_completion_report_when_intermediate_export_fails(self):
        original_writer = preparation.atomic_write_json

        def fail_on_changes(path, payload, **kwargs):
            if Path(path).name == "changes.json":
                raise OSError("simulated disk write failure")
            return original_writer(path, payload, **kwargs)

        with patch.object(preparation, "atomic_write_json", side_effect=fail_on_changes):
            with self.assertRaisesRegex(OSError, "simulated disk write failure"):
                preparation.export_snapshot(self.source, self.destination)
        self.assertTrue((self.destination / "qualified_news_raw.json").exists())
        self.assertTrue((self.destination / "qualified_news_cleaned.json").exists())
        self.assertFalse((self.destination / "preprocessing_report.json").exists())
        self.assertEqual(self.source.read_bytes(), self.raw_bytes)

    def test_cli_preview_prints_example_and_writes_nothing(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = preparation.main([
                "--source", str(self.source), "--output-dir", str(self.destination), "--preview",
            ])
        self.assertEqual(code, 0)
        self.assertIn("Preview only: no files written.", stdout.getvalue())
        self.assertIn("BEFORE", stdout.getvalue())
        self.assertIn("AFTER", stdout.getvalue())
        self.assertFalse(self.destination.parent.exists())

    def test_cli_export_creates_snapshot_and_prints_destination(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = preparation.main(["--source", str(self.source), "--output-dir", str(self.destination)])
        self.assertEqual(code, 0)
        self.assertIn(str(self.destination.resolve()), stdout.getvalue())
        self.assertTrue((self.destination / "preprocessing_report.json").is_file())

    def test_cli_invalid_source_exits_cleanly_without_writes(self):
        self.source.write_bytes(b"[]")
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                preparation.main(["--source", str(self.source), "--output-dir", str(self.destination)])
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("Preprocessing stopped: ValueError", stderr.getvalue())
        self.assertFalse(self.destination.parent.exists())


if __name__ == "__main__":
    unittest.main()

"""Offline tests: no production scraper, model, or database module is imported.

Run from the repository root:
    python -m unittest discover -s scratch -p test_main_pipeline2.py
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main_pipeline2 as experimental


EXPECTED_FIELDS = (
    "run_id", "article_index", "exported_at", "inference_mode", "title", "url",
    "image_url", "article_body", "text_source", "model_input_text", "is_redundant",
    "novelty_label", "extracted_assets", "summary", "flan_input_tokens",
    "flan_output_tokens", "flan_input_truncated", "flan_inference_seconds",
    "category", "category_confidence", "impact", "impact_confidence", "sentiment",
    "sentiment_confidence", "target_investor", "deberta_inference_seconds",
    "total_inference_seconds", "model_errors", "database_id", "database_created_at",
    "database_status", "database_error",
    "experiment_id", "dataset_sha256", "flan_max_input_tokens", "flan_original_input_tokens",
)


def article(title="Bitcoin news", **changes):
    value = {
        "title": title, "url": "https://example.invalid/bitcoin", "image_url": None,
        "full_body": 'Bitcoin rose, according to "Company A".\nInvestor: café.',
        "rss_summary": "RSS fallback", "description": "Description fallback",
    }
    value.update(changes)
    return value


def record_for(item, *, redundant=False):
    return SimpleNamespace(
        title=item["title"], url=item["url"], image_url=item.get("image_url"),
        description=item.get("full_body") or item.get("rss_summary")
        or item.get("description") or "",
        is_redundant=redundant, novelty_label="Low" if redundant else "High",
        extracted_assets=None, summary=None, category=None, impact=None,
        sentiment=None, target_investor=None, id=None, created_at=None,
        embedding=[0.5] * 384,
    )


def inference_outcome():
    return SimpleNamespace(
        entities=[{"matched_text": "Bitcoin", "name": "Bítcoin", "asset_id": 1}],
        summary_result=SimpleNamespace(
            summary="Bitcoin news, explained simply.", inference_seconds=1.25,
            input_token_count=100, original_input_token_count=125,
            output_token_count=20, input_was_truncated=True,
        ),
        classification_result=SimpleNamespace(
            category="Market", category_confidence=0.9, impact="Low",
            impact_confidence=0.8, sentiment="Neutral", sentiment_confidence=0.7,
            target_investor=["Beginner", "Long-term"],
            target_investor_scores={"Beginner": 0.95}, inference_seconds=2.5,
        ),
        elapsed_seconds=3.75, errors={},
    )


def aggregate(record, outcome):
    record.extracted_assets = outcome.entities
    if outcome.summary_result is not None:
        record.summary = outcome.summary_result.summary
    if outcome.classification_result is not None:
        for name in ("category", "impact", "sentiment", "target_investor"):
            setattr(record, name, getattr(outcome.classification_result, name))


def csv_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class CsvRunExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.export = experimental.CsvRunExport(self.directory)
        self.article = article()
        self.record = record_for(self.article)
        self.outcome = inference_outcome()
        aggregate(self.record, self.outcome)

    def capture(self, **kwargs):
        return self.export.capture(
            kwargs.get("article_index", 1), kwargs.get("article", self.article),
            kwargs.get("record", self.record), kwargs.get("outcome", self.outcome),
            kwargs.get("mode", "sequential"),
        )

    def test_exact_columns_unicode_quotes_and_multiline_roundtrip(self):
        self.capture()
        self.assertEqual(tuple(experimental.FIELDNAMES), EXPECTED_FIELDS)
        self.assertTrue(self.export.path.read_bytes().startswith(b"\xef\xbb\xbf"))
        rows = csv_rows(self.export.path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["article_body"], self.article["full_body"])
        self.assertEqual(rows[0]["summary"], self.record.summary)
        self.assertEqual(rows[0]["model_input_text"], f'{self.article["title"]}. {self.article["full_body"]}')
        self.assertEqual(rows[0]["text_source"], "full_body")
        self.assertNotIn("embedding", rows[0])

    def test_structured_fields_json_and_missing_scalars_blank(self):
        self.outcome.errors = {"ner": ValueError("example error")}
        self.capture()
        row = csv_rows(self.export.path)[0]
        self.assertEqual(json.loads(row["extracted_assets"]), self.outcome.entities)
        self.assertEqual(json.loads(row["target_investor"]), self.record.target_investor)
        self.assertIn("example error", json.loads(row["model_errors"])["ner"])
        self.assertEqual(row["image_url"], "")
        self.assertEqual(row["database_id"], "")
        self.assertEqual(row["database_status"], "pending")
        self.assertEqual(row["flan_input_tokens"], "100")

    def test_fallback_body_source_matches_pipeline(self):
        for overrides, expected in (
            ({"full_body": ""}, "rss_summary"),
            ({"full_body": None, "rss_summary": None}, "description"),
        ):
            with self.subTest(source=expected):
                item = article(**overrides)
                record = record_for(item)
                index = self.capture(article=item, record=record)
                row = csv_rows(self.export.path)[index]
                self.assertEqual(row["text_source"], expected)
                self.assertEqual(row["article_body"], item[expected])

    def test_redundant_row_has_no_stale_metrics(self):
        self.capture()
        item = article("Redundant article")
        record = record_for(item, redundant=True)
        self.capture(article_index=2, article=item, record=record, outcome=None)
        row = csv_rows(self.export.path)[1]
        for key in ("summary", "flan_input_tokens", "category_confidence",
                    "flan_inference_seconds", "total_inference_seconds", "model_input_text"):
            self.assertEqual(row[key], "", key)
        self.assertEqual(row["article_body"], item["full_body"])

    def test_saved_updates_same_row_and_database_metadata(self):
        index = self.capture()
        self.record.id = 123
        self.record.created_at = datetime(2026, 10, 18, tzinfo=timezone.utc)
        self.export.mark_saved(index, self.record)
        rows = csv_rows(self.export.path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["database_status"], "saved")
        self.assertEqual(rows[0]["database_id"], "123")
        self.assertEqual(rows[0]["database_created_at"], self.record.created_at.isoformat())

    def test_failed_save_retains_generated_results(self):
        index = self.capture()
        self.export.mark_failed(index, RuntimeError("commit unavailable"))
        row = csv_rows(self.export.path)[0]
        self.assertEqual(row["database_status"], "failed")
        self.assertIn("commit unavailable", row["database_error"])
        self.assertEqual(row["summary"], self.record.summary)

    def test_unique_filenames_and_run_ids(self):
        other = experimental.CsvRunExport(self.directory)
        self.assertNotEqual(self.export.path, other.path)
        self.assertNotEqual(self.export.run_id, other.run_id)

    def test_atomic_write_failure_keeps_previous_file_and_memory_row(self):
        self.capture()
        previous_bytes = self.export.path.read_bytes()
        with patch.object(experimental.os, "replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.capture(article_index=2)
        self.assertEqual(self.export.path.read_bytes(), previous_bytes)
        self.assertEqual(len(self.export.rows), 2)
        self.export.write()
        self.assertEqual(len(csv_rows(self.export.path)), 2)

    def test_safe_csv_wrapper_does_not_propagate_failure(self):
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            result = experimental._try_csv(Mock(side_effect=OSError("disk unavailable")))
        self.assertIsNone(result)


class PipelineIntegrationTests(unittest.TestCase):
    def run_offline(self, articles, *, mode="sequential", commit_failure=False,
                    refresh_failure=False, csv_failure=False, outcomes=None,
                    fail_write_calls=(), fail_first_commit=False, before_save=None):
        """Inject a fake main_pipeline; all I/O remains inside a temp directory."""
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "output").mkdir()
            (folder / "output" / "scraped_news.json").write_text(
                json.dumps(articles), encoding="utf-8",
            )
            records = []
            added = []
            db = Mock()

            def process(item, session):
                self.assertIs(session, db)
                record = record_for(item, redundant=item.get("redundant", False))
                records.append(record)
                return record

            def commit():
                if before_save is not None:
                    before_save("commit", csv_rows(next((folder / "csv").glob("*.csv"))))
                if commit_failure or (fail_first_commit and len(added) == 1):
                    raise RuntimeError("simulated commit failure")
                added[-1].id = 100 + len(added)
                added[-1].created_at = datetime(2026, 10, 18, tzinfo=timezone.utc)

            def add(record):
                if before_save is not None:
                    before_save("add", csv_rows(next((folder / "csv").glob("*.csv"))))
                added.append(record)

            db.add.side_effect = add
            db.commit.side_effect = commit
            if refresh_failure:
                db.refresh.side_effect = RuntimeError("simulated refresh failure")
            fake = ModuleType("main_pipeline")
            fake.SessionLocal = Mock(return_value=db)
            fake.run_scheduler = Mock(return_value={
                "rss_items": len(articles), "new_items": len(articles),
                "scrape_success": len(articles), "scrape_failed": 0,
            })
            fake.is_top_10_news = Mock(side_effect=lambda item: not item.get("filtered", False))
            fake.process_incoming_news = Mock(side_effect=process)
            fake.run_ai_inference = AsyncMock(
                side_effect=outcomes if outcomes is not None
                else lambda *_args, **_kwargs: inference_outcome(),
            )
            original_write = experimental.CsvRunExport.write
            write_count = 0

            def intermittent_write(export):
                nonlocal write_count
                write_count += 1
                if write_count in fail_write_calls:
                    raise OSError(f"simulated CSV write failure {write_count}")
                return original_write(export)

            previous_cwd = Path.cwd()
            try:
                os.chdir(folder)
                with contextlib.ExitStack() as stack:
                    stack.enter_context(patch.dict(sys.modules, {"main_pipeline": fake}))
                    stack.enter_context(patch.object(experimental, "DEFAULT_CSV_OUTPUT_DIR", folder / "csv"))
                    stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                    stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
                    if csv_failure:
                        stack.enter_context(patch.object(experimental.CsvRunExport, "write", side_effect=OSError("disk unavailable")))
                    elif fail_write_calls:
                        stack.enter_context(patch.object(experimental.CsvRunExport, "write", intermittent_write))
                    asyncio.run(experimental.run_pipeline(mode))
                files = list((folder / "csv").glob("*.csv"))
                rows = csv_rows(files[0]) if files and not csv_failure else []
            finally:
                os.chdir(previous_cwd)
            return rows, fake, db, records

    def test_unique_redundant_and_filtered_article_flow(self):
        rows, fake, db, records = self.run_offline([
            article("Unique"), article("Duplicate", redundant=True),
            article("Unrelated", filtered=True),
        ])
        self.assertEqual(len(rows), 2)
        self.assertEqual([row["title"] for row in rows], ["Unique", "Duplicate"])
        self.assertEqual([row["database_status"] for row in rows], ["saved", "saved"])
        self.assertEqual(rows[0]["summary"], records[0].summary)
        self.assertEqual(rows[1]["summary"], "")
        self.assertEqual(rows[1]["flan_inference_seconds"], "")
        self.assertEqual(fake.run_ai_inference.await_count, 1)
        self.assertEqual(db.commit.call_count, 2)
        db.close.assert_called_once()

    def test_existing_inference_modes_are_forwarded(self):
        for mode in ("sequential", "concurrent"):
            with self.subTest(mode=mode):
                rows, fake, _, _ = self.run_offline([article()], mode=mode)
                self.assertEqual(rows[0]["inference_mode"], mode)
                self.assertEqual(fake.run_ai_inference.await_args.kwargs, {"concurrent": mode == "concurrent"})

    def test_commit_failure_exported_without_losing_summary(self):
        rows, _, db, records = self.run_offline([article()], commit_failure=True)
        self.assertEqual(rows[0]["database_status"], "failed")
        self.assertIn("simulated commit failure", rows[0]["database_error"])
        self.assertEqual(rows[0]["summary"], records[0].summary)
        db.rollback.assert_called_once()

    def test_refresh_failure_after_commit_is_still_saved(self):
        rows, _, db, _ = self.run_offline([article()], refresh_failure=True)
        self.assertEqual(rows[0]["database_status"], "saved")
        self.assertIn("simulated refresh failure", rows[0]["database_error"])
        db.commit.assert_called_once()

    def test_csv_failure_does_not_prevent_database_commit(self):
        _, _, db, records = self.run_offline([article()], csv_failure=True)
        db.commit.assert_called_once()
        self.assertIsNotNone(records[0].id)
        self.assertIsNotNone(records[0].summary)
        db.close.assert_called_once()

    def test_capture_write_failure_is_recovered_after_database_save(self):
        # Writes: 1 header, 2 pending capture (fails), 3 saved status, 4 final retry.
        rows, _, db, records = self.run_offline([article()], fail_write_calls=(2,))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["database_status"], "saved")
        self.assertEqual(rows[0]["database_id"], str(records[0].id))
        self.assertEqual(rows[0]["summary"], records[0].summary)
        db.commit.assert_called_once()
        db.rollback.assert_not_called()

    def test_status_write_failure_is_recovered_without_database_rollback(self):
        # The DB commit succeeds; only the following status snapshot fails.
        rows, _, db, records = self.run_offline([article()], fail_write_calls=(3,))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["database_status"], "saved")
        self.assertEqual(rows[0]["database_id"], str(records[0].id))
        db.commit.assert_called_once()
        db.rollback.assert_not_called()

    def test_partial_model_failure_preserves_successful_classification(self):
        partial = inference_outcome()
        partial.summary_result = None
        partial.errors = {"flan_t5": RuntimeError("simulated FLAN failure")}
        rows, _, db, records = self.run_offline([article()], outcomes=[partial])
        row = rows[0]
        self.assertEqual(row["database_status"], "saved")
        self.assertEqual(row["summary"], "")
        self.assertEqual(row["flan_input_tokens"], "")
        self.assertEqual(row["flan_inference_seconds"], "")
        self.assertIsNone(records[0].summary)
        self.assertEqual(row["category"], partial.classification_result.category)
        self.assertEqual(records[0].category, partial.classification_result.category)
        self.assertEqual(row["category_confidence"], "0.9")
        self.assertIn("simulated FLAN failure", json.loads(row["model_errors"])["flan_t5"])
        db.commit.assert_called_once()
        db.rollback.assert_not_called()

    def test_pending_result_is_durable_before_add_and_commit(self):
        stages = []

        def assert_pending(stage, rows):
            stages.append(stage)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["database_status"], "pending")
            self.assertEqual(rows[0]["database_id"], "")
            self.assertEqual(rows[0]["summary"], "Bitcoin news, explained simply.")

        rows, _, _, _ = self.run_offline([article()], before_save=assert_pending)
        self.assertEqual(stages, ["add", "commit"])
        self.assertEqual(rows[0]["database_status"], "saved")

    def test_commit_failure_then_success_has_no_stale_results(self):
        first = inference_outcome()
        second = inference_outcome()
        second.summary_result = None
        second.errors = {"flan_t5": RuntimeError("second article FLAN unavailable")}
        second.elapsed_seconds = 9.25
        second.classification_result.category = "Regulation"
        second.classification_result.category_confidence = 0.42
        rows, fake, db, records = self.run_offline(
            [article("First"), article("Second")], outcomes=[first, second],
            fail_first_commit=True,
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["database_status"], "failed")
        self.assertEqual(rows[1]["database_status"], "saved")
        self.assertEqual(rows[0]["summary"], first.summary_result.summary)
        self.assertEqual(rows[0]["flan_input_tokens"], "100")
        self.assertEqual(rows[1]["summary"], "")
        self.assertEqual(rows[1]["flan_input_tokens"], "")
        self.assertEqual(rows[1]["flan_inference_seconds"], "")
        self.assertEqual(rows[1]["total_inference_seconds"], "9.25")
        self.assertEqual(rows[1]["category"], "Regulation")
        self.assertEqual(rows[1]["category_confidence"], "0.42")
        self.assertEqual(rows[1]["database_error"], "")
        self.assertEqual(rows[1]["database_id"], str(records[1].id))
        self.assertEqual(fake.run_ai_inference.await_count, 2)
        self.assertEqual(db.commit.call_count, 2)
        db.rollback.assert_called_once()
        db.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()

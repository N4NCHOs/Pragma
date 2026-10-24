"""Offline validation of fixed-batch experiments; never calls a live service."""

from __future__ import annotations

import asyncio
import csv
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from contextlib import ExitStack

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main_pipeline2 as experimental
import pipeline_experiment_data as data
from scratch.test_main_pipeline2 import csv_rows, inference_outcome, record_for


def article(index, **changes):
    value = {
        "title": f"Bitcoin story {index}",
        "url": f"https://example.invalid/article/{index}",
        "guid": f"article-{index}",
        "full_body": f"Verified full article body {index}.",
    }
    value.update(changes)
    return value


def unique_vector(text):
    index = int(text.split("story ", 1)[1].split(".", 1)[0])
    return [float(position == index) for position in range(110)]


class FixedBatchTests(unittest.TestCase):
    def prepare(self, articles, **changes):
        options = {
            "target_count": len(articles), "asset_filter": lambda item: True,
            "encode_text": unique_vector, "distance_threshold": 0.15,
        }
        options.update(changes)
        return data.prepare_fixed_batch(articles, **options)

    def test_selects_exactly_100_without_padding_or_mutating_input(self):
        articles = [article(index) for index in range(105)]
        before = json.dumps(articles, sort_keys=True)
        batch, report = self.prepare(articles, target_count=100)
        self.assertEqual(len(batch), 100)
        self.assertEqual(len({item["experiment_article_id"] for item in batch}), 100)
        self.assertEqual(report["accepted"], 100)
        self.assertEqual(report["scanned_articles"], 100)
        self.assertEqual(report["remaining_articles"], 5)
        self.assertEqual(json.dumps(articles, sort_keys=True), before)
        self.assertEqual([item["url"] for item in batch], [item["url"] for item in articles[:100]])

    def test_shortfall_raises_report_instead_of_repeating_articles(self):
        with self.assertRaises(data.DatasetShortfallError) as raised:
            self.prepare([article(0), article(1)], target_count=100)
        self.assertEqual(raised.exception.report["accepted"], 2)
        self.assertEqual(raised.exception.report["target_count"], 100)

    def test_missing_body_and_filtered_articles_are_not_accepted(self):
        articles = [
            article(0, full_body="", rss_summary="Do not substitute this RSS excerpt"),
            article(1, full_body="   "), article(2, allowed=False), article(3),
        ]
        batch, report = self.prepare(
            articles, target_count=1, asset_filter=lambda item: item.get("allowed", True),
        )
        self.assertEqual(batch[0]["url"], article(3)["url"])
        self.assertEqual(report["rejected_no_full_body"], 2)
        self.assertEqual(report["rejected_asset_filter"], 1)

    def test_identity_and_semantic_duplicates_are_rejected(self):
        same_url = article(1, url=article(0)["url"])
        semantic_duplicate = article(2)

        def encode(text):
            return [0.0, 1.0] if "story 3." in text else [1.0, 0.0]

        batch, report = self.prepare(
            [article(0), same_url, semantic_duplicate, article(3)],
            target_count=2, encode_text=encode,
        )
        self.assertEqual([item["title"] for item in batch], [article(0)["title"], article(3)["title"]])
        self.assertEqual(report["rejected_duplicate"], 1)
        self.assertEqual(report["rejected_redundant"], 1)

    def test_encoder_errors_and_invalid_vectors_are_reported(self):
        invalid = [RuntimeError("encoder unavailable"), [float("nan"), 1.0], [0.0, 0.0], [1.0, 0.0]]

        def encode(_text):
            value = invalid.pop(0)
            if isinstance(value, Exception):
                raise value
            return value

        batch, report = self.prepare([article(i) for i in range(4)], target_count=1, encode_text=encode)
        self.assertEqual(batch[0]["title"], article(3)["title"])
        self.assertEqual(report["embedding_errors"], 3)
        self.assertEqual(len(report["reasons"]), 3)

    def test_encoder_receives_same_title_plus_full_body_as_pipeline(self):
        encode = Mock(return_value=[1.0, 0.0])
        item = article(0)
        self.prepare([item], encode_text=encode)
        encode.assert_called_once_with(f'{item["title"]}. {item["full_body"]}')

    def test_hash_is_repeatable_but_sensitive_to_text_and_order(self):
        items = [article(0), article(1)]
        fingerprint = data.compute_dataset_hash(items)
        self.assertEqual(fingerprint, data.compute_dataset_hash(json.loads(json.dumps(items))))
        self.assertNotEqual(fingerprint, data.compute_dataset_hash(list(reversed(items))))
        changed = [dict(items[0], full_body="Different article text"), items[1]]
        self.assertNotEqual(fingerprint, data.compute_dataset_hash(changed))

    def test_json_snapshot_roundtrips_unicode(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "dataset.json"
            payload = [article(0, full_body="Bitcoin, café\nquoted: \"news\"")]
            data.atomic_write_json(target, payload)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), payload)

    def test_pretty_and_compact_json_preserve_identical_data_and_dataset_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            payload = [article(0, full_body='Bítcoin café, "unchanged".\nNext paragraph.')]
            compact = folder / "compact.json"
            pretty = folder / "pretty.json"
            data.atomic_write_json(compact, payload)
            data.atomic_write_json(pretty, payload, indent=2)
            compact_text = compact.read_text(encoding="utf-8")
            pretty_text = pretty.read_text(encoding="utf-8")
            self.assertNotEqual(compact_text, pretty_text)
            self.assertEqual(len(compact_text.splitlines()), 1)
            self.assertGreater(len(pretty_text.splitlines()), 2)
            self.assertEqual(pretty_text.splitlines()[1], "  {")
            self.assertIn("Bítcoin café", pretty_text)
            compact_data, pretty_data = json.loads(compact_text), json.loads(pretty_text)
            self.assertEqual(compact_data, payload)
            self.assertEqual(pretty_data, payload)
            self.assertEqual(data.compute_dataset_hash(compact_data), data.compute_dataset_hash(pretty_data))


class ExperimentCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.dataset_path = self.directory / "source.json"
        self.articles = [article(0), article(1)]
        self.dataset_path.write_text(json.dumps(self.articles), encoding="utf-8")

        self.pipeline = ModuleType("main_pipeline")
        self.pipeline.flan_service = SimpleNamespace(max_input_tokens=777, model_name="fake/flan")
        self.pipeline.is_top_10_news = Mock(return_value=True)
        self.scheduler = ModuleType("rss_scrape_scheduler")
        self.scheduler.RSS_LIMIT = 100
        self.scheduler.RSS_URL = "https://example.invalid/rss"
        self.scheduler.RSS_TEMP_FILE = self.directory / "rss_temp.json"
        self.scheduler.RSS_HISTORY_FILE = self.directory / "rss_history.json"
        self.scheduler.SCRAPED_NEWS_FILE = self.directory / "scraped_news.json"
        self.scheduler.SCRAPED_NEWS_FILE.write_text(json.dumps(self.articles), encoding="utf-8")
        self.scheduler.run_scheduler = Mock(return_value={})
        self.scheduler.article_keys = lambda item: [item["url"]]
        self.novelty = ModuleType("ai_models.novelty_detection")
        self.novelty.embedding_model = SimpleNamespace(encode=unique_vector)
        self.novelty.SIMILARITY_THRESHOLD_DISTANCE = 0.2
        self.models = ModuleType("ai_models")
        self.models.__path__ = []
        self.models.novelty_detection = self.novelty

    def run_experiment(self, *, target_count=2, max_input_limits=(512, 1024),
                       confirm_db_reset=True, dataset_path=True,
                       prepare_only=False, run_side_effect=None,
                       verification_error=None, mutate_batch=False):
        self.order = []

        async def run(mode, **kwargs):
            self.order.append(("run", self.pipeline.flan_service.max_input_tokens))
            if run_side_effect is not None:
                raise run_side_effect
            if mutate_batch:
                kwargs["news_batch"][0]["full_body"] = "Unexpected mutation"
            return Mock()

        self.run_mock = AsyncMock(side_effect=run)
        self.reset_db = Mock(side_effect=lambda *_args, **_kwargs: self.order.append(("reset", self.pipeline.flan_service.max_input_tokens)))
        with ExitStack() as stack:
            stack.enter_context(patch.dict(sys.modules, {
                "main_pipeline": self.pipeline, "rss_scrape_scheduler": self.scheduler,
                "ai_models": self.models, "ai_models.novelty_detection": self.novelty,
            }))
            stack.enter_context(patch.object(experimental, "DEFAULT_EXPERIMENT_OUTPUT_DIR", self.directory / "results"))
            stack.enter_context(patch.object(experimental, "reset_news_articles", self.reset_db))
            self.reset_rss = stack.enter_context(patch.object(experimental, "reset_rss_files"))
            self.collect = stack.enter_context(patch.object(
                experimental, "_collect_source_articles", return_value=(self.articles, {}),
            ))
            stack.enter_context(patch.object(experimental, "run_pipeline", self.run_mock))
            stack.enter_context(patch.object(experimental, "verify_iteration_export", side_effect=verification_error))
            stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(redirect_stderr(io.StringIO()))
            asyncio.run(experimental.run_experiments(
                "sequential", max_input_limits=max_input_limits,
                target_count=target_count,
                dataset_path=self.dataset_path if dataset_path else None,
                confirm_db_reset=confirm_db_reset, prepare_only=prepare_only,
            ))

    def test_without_confirmation_never_resets_database(self):
        with self.assertRaises((ValueError, RuntimeError)):
            self.run_experiment(confirm_db_reset=False)
        self.reset_db.assert_not_called()
        self.run_mock.assert_not_awaited()

    def test_same_frozen_batch_and_hash_used_for_every_limit(self):
        limits = (512, 1024, 2048, 3072)
        self.run_experiment(max_input_limits=limits)
        calls = self.run_mock.await_args_list
        self.assertEqual(len(calls), len(limits))
        batch = calls[0].kwargs["news_batch"]
        fingerprint = data.compute_dataset_hash(batch)
        for call, limit in zip(calls, limits):
            self.assertEqual(call.kwargs["news_batch"], batch)
            self.assertEqual(call.kwargs["dataset_sha256"], fingerprint)
            self.assertEqual(call.kwargs["flan_max_input_tokens"], limit)
            self.assertTrue(call.kwargs["strict"])
        self.assertEqual([event[0] for event in self.order], ["reset", "run"] * 4)
        self.assertEqual([limit for kind, limit in self.order if kind == "run"], list(limits))
        self.assertEqual(self.pipeline.flan_service.max_input_tokens, 777)
        self.scheduler.run_scheduler.assert_not_called()
        self.assertEqual(self.reset_rss.call_count, 4)

    def test_inference_failure_stops_iterations_and_restores_original_limit(self):
        with self.assertRaisesRegex(RuntimeError, "inference failed"):
            self.run_experiment(run_side_effect=RuntimeError("inference failed"))
        self.assertEqual(self.run_mock.await_count, 1)
        self.assertEqual(self.reset_db.call_count, 1)
        self.assertEqual(self.pipeline.flan_service.max_input_tokens, 777)

    def test_shortfall_does_not_reset_database_or_pad_dataset(self):
        with self.assertRaises(data.DatasetShortfallError):
            self.run_experiment(target_count=100)
        self.reset_db.assert_not_called()
        self.run_mock.assert_not_awaited()
        self.assertEqual(self.pipeline.flan_service.max_input_tokens, 777)

    def test_fresh_collection_shortfall_never_truncates_database(self):
        with self.assertRaises(data.DatasetShortfallError):
            self.run_experiment(target_count=100, dataset_path=False)
        self.reset_rss.assert_called_once()
        self.collect.assert_called_once_with(self.scheduler, 1000)
        self.scheduler.run_scheduler.assert_not_called()
        self.reset_db.assert_not_called()
        self.run_mock.assert_not_awaited()

    def test_prepare_only_does_not_require_database_reset_confirmation(self):
        self.run_experiment(confirm_db_reset=False, prepare_only=True)
        self.reset_db.assert_not_called()
        self.run_mock.assert_not_awaited()
        self.assertEqual(self.pipeline.flan_service.max_input_tokens, 777)

    def test_csv_verification_failure_prevents_next_database_reset(self):
        with self.assertRaisesRegex(experimental.ExperimentIncompleteError, "incomplete CSV"):
            self.run_experiment(
                verification_error=experimental.ExperimentIncompleteError("incomplete CSV"),
            )
        self.assertEqual(self.reset_db.call_count, 1)
        self.assertEqual(self.run_mock.await_count, 1)
        self.assertEqual(self.pipeline.flan_service.max_input_tokens, 777)

    def test_fixed_batch_mutation_prevents_next_database_reset(self):
        with self.assertRaisesRegex(experimental.ExperimentIncompleteError, "changed"):
            self.run_experiment(mutate_batch=True)
        self.assertEqual(self.reset_db.call_count, 1)
        self.assertEqual(self.run_mock.await_count, 1)
        self.assertEqual(self.pipeline.flan_service.max_input_tokens, 777)


class StrictPipelineTests(unittest.TestCase):
    def run_strict(self, *, redundant=False, outcome=None, csv_failure=False):
        item = article(0)
        fake = ModuleType("main_pipeline")
        record = record_for(item, redundant=redundant)
        db = Mock()

        def commit():
            record.id = 1

        db.commit.side_effect = commit
        fake.SessionLocal = Mock(return_value=db)
        fake.run_scheduler = Mock()
        fake.is_top_10_news = Mock(return_value=True)
        fake.process_incoming_news = Mock(return_value=record)
        fake.run_ai_inference = AsyncMock(return_value=outcome or inference_outcome())
        fake.flan_service = SimpleNamespace(max_input_tokens=512)
        error = None
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            stack.enter_context(patch.dict(sys.modules, {"main_pipeline": fake}))
            stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(redirect_stderr(io.StringIO()))
            if csv_failure:
                stack.enter_context(patch.object(experimental, "CsvRunExport", side_effect=OSError("CSV unavailable")))
            try:
                asyncio.run(experimental.run_pipeline(
                    "sequential", news_batch=[item], csv_output_dir=Path(temporary),
                    strict=True, flan_max_input_tokens=512,
                    experiment_id="offline-test", dataset_sha256="fixed-hash",
                ))
            except Exception as exc:
                error = exc
            files = list(Path(temporary).glob("*.csv"))
            rows = csv_rows(files[0]) if files else []
        return rows, fake, db, record, error

    def test_fixed_batch_skips_scraper_and_exports_experiment_metadata(self):
        rows, fake, db, _, error = self.run_strict()
        self.assertIsNone(error)
        fake.run_scheduler.assert_not_called()
        self.assertEqual(rows[0]["experiment_id"], "offline-test")
        self.assertEqual(rows[0]["dataset_sha256"], "fixed-hash")
        self.assertEqual(rows[0]["flan_max_input_tokens"], "512")
        self.assertEqual(rows[0]["flan_original_input_tokens"], "125")
        self.assertEqual(rows[0]["database_status"], "saved")
        db.commit.assert_called_once()

    def test_partial_model_failure_is_saved_but_experiment_cannot_advance(self):
        partial = inference_outcome()
        partial.summary_result = None
        partial.errors = {"flan_t5": RuntimeError("model unavailable")}
        rows, fake, db, record, error = self.run_strict(outcome=partial)
        self.assertIsInstance(error, experimental.ExperimentIncompleteError)
        self.assertEqual(rows[0]["database_status"], "saved")
        self.assertEqual(rows[0]["summary"], "")
        self.assertEqual(record.category, partial.classification_result.category)
        self.assertIn("model unavailable", rows[0]["model_errors"])
        db.commit.assert_called_once()

    def test_unexpected_redundancy_cannot_count_as_completed_experiment(self):
        rows, fake, db, _, error = self.run_strict(redundant=True)
        self.assertIsInstance(error, experimental.ExperimentIncompleteError)
        fake.run_ai_inference.assert_not_awaited()
        self.assertEqual(rows[0]["summary"], "")
        self.assertEqual(rows[0]["database_status"], "saved")

    def test_export_initialization_failure_stops_strict_run_before_database_work(self):
        _, fake, db, _, error = self.run_strict(csv_failure=True)
        self.assertIsInstance(error, experimental.ExperimentIncompleteError)
        fake.process_incoming_news.assert_not_called()
        db.commit.assert_not_called()


class ResetAndVerificationTests(unittest.TestCase):
    def test_candidate_collector_uses_explicit_pool_limit_and_preserves_failed_scrapes(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            candidates = [article(index) for index in range(5)]
            scraped = [dict(item, scrape_status="success", scrape_error=None) for item in candidates]
            scraped[2].update(full_body=None, scrape_status="failed", scrape_error="rate limited")
            scheduler = SimpleNamespace(
                RSS_TEMP_FILE=folder / "rss_temp.json",
                RSS_HISTORY_FILE=folder / "rss_history.json",
                SCRAPED_NEWS_FILE=folder / "scraped_news.json",
                BROWSER_HEADERS={"User-Agent": "offline-test"},
                DELAY_BETWEEN_REQUESTS=0.01,
                fetch_latest_rss=Mock(return_value=candidates),
                scrape_article=Mock(side_effect=scraped),
                write_json_atomic=Mock(side_effect=data.atomic_write_json),
            )
            session = Mock()
            session.headers = {}
            session_context = MagicMock()
            session_context.__enter__.return_value = session
            requests = ModuleType("requests")
            requests.Session = Mock(return_value=session_context)
            scheduler.requests = requests
            with patch.dict(sys.modules, {"requests": requests}), \
                    patch.object(experimental.time, "sleep") as sleep, \
                    redirect_stdout(io.StringIO()):
                batch, stats = experimental._collect_source_articles(scheduler, candidate_limit=1000)
            scheduler.fetch_latest_rss.assert_called_once_with(session, limit=1000)
            self.assertEqual(scheduler.scrape_article.call_count, 5)
            self.assertEqual(sleep.call_count, 4)
            self.assertEqual(session.headers["User-Agent"], "offline-test")
            self.assertEqual(batch, scraped)
            self.assertEqual(stats["scrape_success"], 4)
            self.assertEqual(stats["scrape_failed"], 1)
            disk = json.loads(scheduler.SCRAPED_NEWS_FILE.read_text())
            self.assertEqual(disk[2]["scrape_status"], "failed")
            self.assertEqual(disk[2]["scrape_error"], "rate limited")
            self.assertEqual(len(disk), 5)

    def test_rss_reset_backs_up_all_three_files_before_clearing(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            names = ("rss_temp.json", "rss_history.json", "scraped_news.json")
            paths = [folder / name for name in names]
            originals = {}
            for index, path in enumerate(paths):
                originals[path.name] = json.dumps([{"id": index}]).encode()
                path.write_bytes(originals[path.name])
            untouched = folder / "unrelated.json"
            untouched.write_text('["keep"]', encoding="utf-8")
            scheduler = SimpleNamespace(**dict(zip(
                ("RSS_TEMP_FILE", "RSS_HISTORY_FILE", "SCRAPED_NEWS_FILE"), paths,
            )))
            backup = folder / "backup"
            original_atomic = experimental.atomic_write_json

            def check_backups_then_clear(path, value):
                for name in names:
                    self.assertEqual((backup / name).read_bytes(), originals[name])
                return original_atomic(path, value)

            with patch.object(experimental, "atomic_write_json", side_effect=check_backups_then_clear):
                experimental.reset_rss_files(scheduler, backup)
            for path in paths:
                self.assertEqual(json.loads(path.read_text()), [])
            self.assertEqual(untouched.read_text(), '["keep"]')

    def test_rss_backup_failure_does_not_clear_working_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            paths = [folder / name for name in ("rss_temp.json", "rss_history.json", "scraped_news.json")]
            for path in paths:
                path.write_text('["original"]', encoding="utf-8")
            scheduler = SimpleNamespace(**dict(zip(
                ("RSS_TEMP_FILE", "RSS_HISTORY_FILE", "SCRAPED_NEWS_FILE"), paths,
            )))
            with patch.object(experimental.shutil, "copy2", side_effect=OSError("backup unavailable")):
                with self.assertRaises(OSError):
                    experimental.reset_rss_files(scheduler, folder / "backup")
            self.assertTrue(all(path.read_text() == '["original"]' for path in paths))

    def reset_database_offline(self, backup_path, *, backup_failure=False):
        statements = []
        connection = Mock()

        def execute(statement):
            statements.append(statement)
            if statement == "SELECT current_database()":
                return Mock(scalar_one=Mock(return_value="offline_test_database"))
            if statement.startswith("SELECT row_to_json"):
                return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [{"id": 10, "summary": "retained"}]))
            if statement.startswith("TRUNCATE"):
                self.assertTrue(backup_path.is_file(), "Backup must precede TRUNCATE")
            return Mock()

        connection.execute.side_effect = execute
        transaction = MagicMock()
        transaction.__enter__.return_value = connection
        engine = SimpleNamespace(
            url=SimpleNamespace(render_as_string=lambda **_kwargs: "postgresql://offline.invalid/test"),
            begin=lambda: transaction,
        )
        session = Mock()
        session.get_bind.return_value = engine
        pipeline = SimpleNamespace(SessionLocal=Mock(return_value=session))
        sqlalchemy = ModuleType("sqlalchemy")
        sqlalchemy.text = lambda sql: sql
        with ExitStack() as stack:
            stack.enter_context(patch.dict(sys.modules, {"sqlalchemy": sqlalchemy}))
            stack.enter_context(redirect_stdout(io.StringIO()))
            if backup_failure:
                stack.enter_context(patch.object(experimental, "atomic_write_json", side_effect=OSError("backup disk failed")))
                with self.assertRaises(OSError):
                    experimental.reset_news_articles(pipeline, backup_path)
            else:
                experimental.reset_news_articles(pipeline, backup_path)
        session.close.assert_called_once()
        return statements, transaction

    def test_database_reset_uses_exact_table_no_cascade_and_backup_first(self):
        with tempfile.TemporaryDirectory() as temporary:
            backup_path = Path(temporary) / "database_backup.json"
            statements, transaction = self.reset_database_offline(backup_path)
            backup = json.loads(backup_path.read_text())
            self.assertEqual(backup["table"], "public.news_articles")
            self.assertEqual(backup["rows"], [{"id": 10, "summary": "retained"}])
            self.assertIn("LOCK TABLE public.news_articles IN ACCESS EXCLUSIVE MODE", statements)
            self.assertEqual(statements[-1], "TRUNCATE TABLE public.news_articles RESTART IDENTITY")
            self.assertFalse(any("CASCADE" in sql or "DROP" in sql for sql in statements))
            self.assertIsNone(transaction.__exit__.call_args.args[0])

    def test_database_backup_failure_prevents_truncate_and_exits_transaction_with_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            statements, transaction = self.reset_database_offline(
                Path(temporary) / "backup.json", backup_failure=True,
            )
            self.assertFalse(any("TRUNCATE" in sql for sql in statements))
            self.assertIs(transaction.__exit__.call_args.args[0], OSError)

    def test_disk_csv_must_be_complete_before_next_iteration(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "results.csv"
            valid = dict.fromkeys(experimental.FIELDNAMES, "")
            valid.update(
                article_index="1", database_status="saved", summary="A factual summary.",
                category="Market", model_errors="{}", is_redundant="False",
                dataset_sha256="hash", flan_max_input_tokens="1024",
            )

            def write(row):
                with path.open("w", encoding="utf-8-sig", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=experimental.FIELDNAMES)
                    writer.writeheader()
                    writer.writerow(row)

            write(valid)
            experimental.verify_iteration_export(SimpleNamespace(path=path), 1, "hash", 1024)
            for changes in (
                {"summary": ""}, {"database_status": "pending"},
                {"model_errors": '{"flan_t5":"failed"}'}, {"is_redundant": "True"},
                {"dataset_sha256": "other"}, {"flan_max_input_tokens": "512"},
                {"database_error": "refresh failed"}, {"article_index": "2"},
            ):
                with self.subTest(changes=changes):
                    write(dict(valid, **changes))
                    with self.assertRaises(experimental.ExperimentIncompleteError):
                        experimental.verify_iteration_export(SimpleNamespace(path=path), 1, "hash", 1024)

    def test_large_csv_field_is_verified_and_global_field_limit_is_restored(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "large_results.csv"
            valid = dict.fromkeys(experimental.FIELDNAMES, "")
            valid.update(
                article_index="1", database_status="saved", summary="A factual summary.",
                category="Market", model_errors="{}", is_redundant="False",
                dataset_sha256="hash", flan_max_input_tokens="1024",
                article_body="x" * 150_001,
            )
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=experimental.FIELDNAMES)
                writer.writeheader()
                writer.writerow(valid)
            old_limit = csv.field_size_limit(131_072)
            try:
                experimental.verify_iteration_export(SimpleNamespace(path=path), 1, "hash", 1024)
                self.assertEqual(csv.field_size_limit(), 131_072)
            finally:
                csv.field_size_limit(old_limit)


if __name__ == "__main__":
    unittest.main()

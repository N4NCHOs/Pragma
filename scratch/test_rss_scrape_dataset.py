"""Offline tests for the separate resumable RSS dataset collector.

No production scraper, transformer model, or database is imported or executed.
"""

from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import rss_scrape_dataset as dataset


def article(index, **changes):
    item = {
        "title": f"Bitcoin article {index}",
        "url": f"https://example.invalid/news/{index}", "guid": f"news-{index}",
        "full_body": f"The complete source article {index}, with an exact figure of 42.",
        "rss_summary": "A shorter RSS excerpt", "scrape_status": "success",
        "scrape_error": None,
    }
    item.update(changes)
    return item


def keys(item):
    return {f"url:{item['url']}", f"guid:{item.get('guid', item['url'])}"}


def encode(text):
    index = int(text.split("article ", 1)[1].split(".", 1)[0])
    return [float(position == index) for position in range(205)]


class DatasetCollectorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def collector(self, **changes):
        options = {
            "target_count": 2, "asset_filter": lambda item: item.get("allowed", True),
            "encode_text": encode, "model_name": "offline/test-encoder",
            "distance_threshold": 0.2, "key_function": keys,
        }
        options.update(changes)
        return dataset.DatasetCollector(self.directory, **options)

    def test_source_fields_preserved_with_qualification_annotations(self):
        original = article(0)
        collector = self.collector()
        self.assertTrue(collector.add_article(original))
        row = collector.articles[0]
        self.assertEqual({key: row[key] for key in original}, original)
        self.assertNotIn("dataset_article_id", original)
        self.assertEqual(row["qualification_status"], "qualified")
        self.assertTrue(row["asset_filter_passed"])
        self.assertTrue(row["novelty_checked"])
        self.assertIs(row["is_redundant"], False)
        self.assertEqual(row["novelty_label"], "High")
        self.assertEqual(len(collector.qualified), 1)
        self.assertFalse(collector.complete)

    def test_resume_pool_grows_and_reuses_saved_vectors_without_old_inference(self):
        first_encode = Mock(side_effect=encode)
        collector = self.collector(encode_text=first_encode)
        collector.add_article(article(0))
        collector.save()
        next_encode = Mock(side_effect=encode)
        resumed = self.collector(encode_text=next_encode)
        next_encode.assert_not_called()
        self.assertEqual(len(resumed.qualified), 1)
        self.assertTrue(resumed.add_article(article(1)))
        next_encode.assert_called_once_with(f'{article(1)["title"]}. {article(1)["full_body"]}')
        self.assertEqual(len(resumed.qualified), 2)
        self.assertTrue(resumed.complete)
        resumed.save()
        self.assertEqual(len(self.collector().qualified), 2)

    def test_duplicate_identity_is_not_stored_or_embedded_twice(self):
        encoder = Mock(side_effect=encode)
        collector = self.collector(encode_text=encoder)
        collector.add_article(article(0))
        self.assertTrue(collector.contains(article(0)))
        self.assertFalse(collector.add_article(article(0, full_body="Changed RSS observation")))
        self.assertEqual(len(collector.articles), 1)
        encoder.assert_called_once()
        self.assertEqual(collector.articles[0]["full_body"], article(0)["full_body"])

    def test_semantic_redundancy_is_flagged_and_retained_across_resume(self):
        collector = self.collector(encode_text=lambda _text: [1.0, 0.0])
        collector.add_article(article(0))
        collector.save()
        resumed = self.collector(encode_text=lambda _text: [1.0, 0.0])
        self.assertTrue(resumed.add_article(article(1)))
        row = resumed.articles[1]
        self.assertEqual(row["qualification_status"], "redundant")
        self.assertTrue(row["novelty_checked"])
        self.assertIs(row["is_redundant"], True)
        self.assertEqual(row["novelty_label"], "Low")
        self.assertEqual(row["matched_article_id"], resumed.articles[0]["dataset_article_id"])
        self.assertEqual(len(resumed.qualified), 1)
        self.assertEqual(len(resumed.articles), 2)

    def test_filter_and_missing_full_body_rejections_are_kept_without_embeddings(self):
        encoder = Mock(side_effect=encode)
        collector = self.collector(encode_text=encoder)
        collector.add_article(article(0, allowed=False))
        collector.add_article(article(1, full_body=None, scrape_status="failed", scrape_error="rate limited"))
        self.assertEqual([row["qualification_status"] for row in collector.articles], [
            "rejected_asset_filter", "rejected_no_full_body",
        ])
        for row in collector.articles:
            self.assertFalse(row["novelty_checked"])
            self.assertIsNone(row["is_redundant"])
            self.assertTrue(row["exclusion_reason"])
        self.assertEqual(collector.articles[1]["scrape_error"], "rate limited")
        encoder.assert_not_called()
        self.assertEqual(len(collector.qualified), 0)

    def test_embedding_failure_is_recorded_not_marked_unique(self):
        collector = self.collector(encode_text=Mock(side_effect=RuntimeError("model unavailable")))
        self.assertTrue(collector.add_article(article(0)))
        row = collector.articles[0]
        self.assertEqual(row["qualification_status"], "qualification_error")
        self.assertIn("model unavailable", row["exclusion_reason"])
        self.assertIsNone(row["is_redundant"])
        self.assertFalse(collector.complete)

    def test_transient_encoder_failure_can_recover_without_refetching(self):
        encoder = Mock(side_effect=[RuntimeError("temporary model failure"), encode(f'{article(0)["title"]}. {article(0)["full_body"]}')])
        collector = self.collector(encode_text=encoder)
        collector.add_article(article(0))
        identity = collector.articles[0]["dataset_article_id"]
        collector.retry_pending()
        self.assertEqual(encoder.call_count, 2)
        self.assertEqual(len(collector.articles), 1)
        self.assertEqual(len(collector.qualified), 1)
        self.assertEqual(collector.qualified[0]["dataset_article_id"], identity)
        self.assertEqual(collector.qualified[0]["qualification_status"], "qualified")
        collector.retry_pending()
        self.assertEqual(encoder.call_count, 2)

    def test_persistent_encoder_failures_stop_after_three_attempts(self):
        encoder = Mock(side_effect=RuntimeError("persistent encoder failure"))
        collector = self.collector(encode_text=encoder)
        collector.add_article(article(0))
        for _ in range(5):
            collector.retry_pending()
        self.assertEqual(encoder.call_count, 3)
        self.assertEqual(collector.articles[0]["qualification_status"], "qualification_error")
        self.assertEqual(len(collector.qualified), 0)

    def test_empty_body_never_uses_rss_summary_as_full_text(self):
        collector = self.collector()
        collector.add_article(article(0, full_body="   ", rss_summary="A usable-looking excerpt"))
        self.assertEqual(collector.articles[0]["qualification_status"], "rejected_no_full_body")
        self.assertEqual(len(collector.qualified), 0)

    def test_target_200_is_exact_and_completion_is_frozen(self):
        collector = self.collector(target_count=200)
        for index in range(200):
            self.assertTrue(collector.add_article(article(index)))
        self.assertTrue(collector.complete)
        self.assertEqual(len(collector.qualified), 200)
        frozen = json.dumps(collector.articles, sort_keys=True)
        self.assertFalse(collector.add_article(article(200)))
        self.assertFalse(collector.add_article(article(0)))
        self.assertEqual(json.dumps(collector.articles, sort_keys=True), frozen)
        self.assertEqual(collector.report()["qualified_count"], 200)
        self.assertEqual(collector.report()["collected_count"], 200)

    def test_saved_projections_are_consistent_with_authoritative_state(self):
        collector = self.collector()
        collector.add_article(article(0))
        collector.add_article(article(1, allowed=False))
        collector.save()
        all_rows = json.loads((self.directory / "all_collected_news.json").read_text())
        qualified = json.loads((self.directory / "qualified_news.json").read_text())
        report = json.loads((self.directory / "collection_report.json").read_text())
        self.assertEqual(len(all_rows), 2)
        self.assertEqual(len(qualified), 1)
        self.assertEqual(qualified[0]["url"], article(0)["url"])
        self.assertEqual(report["qualified_count"], 1)
        self.assertEqual(report["collected_count"], 2)
        self.assertTrue((self.directory / "collection_state.json").is_file())

    def test_outputs_use_two_space_pretty_json_without_changing_text_or_frozen_hash(self):
        source = article(0, full_body='Bítcoin café: "exact wording".\nSecond paragraph.')
        original = dict(source)
        collector = self.collector(target_count=1)
        collector.add_article(source)
        collector.save()
        frozen_hash = collector.report()["dataset_sha256"]
        for name in (
            "collection_state.json", "all_collected_news.json",
            "qualified_news.json", "collection_report.json",
        ):
            with self.subTest(filename=name):
                text = (self.directory / name).read_text(encoding="utf-8")
                lines = text.splitlines()
                self.assertGreater(len(lines), 2)
                self.assertTrue(lines[1].startswith("  "))
                self.assertFalse(lines[1].startswith("   "))
        for name in ("all_collected_news.json", "qualified_news.json"):
            text = (self.directory / name).read_text(encoding="utf-8")
            self.assertIn("Bítcoin café", text)
            self.assertEqual(json.loads(text)[0]["full_body"], source["full_body"])
        self.assertEqual(source, original)
        resumed = self.collector(target_count=1)
        self.assertEqual(resumed.report()["dataset_sha256"], frozen_hash)
        self.assertEqual(resumed.qualified[0]["full_body"], source["full_body"])

    def test_resume_repairs_interrupted_projection_from_authoritative_state(self):
        collector = self.collector()
        collector.add_article(article(0))
        collector.save()
        projection = self.directory / "qualified_news.json"
        projection.write_text("{interrupted projection", encoding="utf-8")
        resumed = self.collector(encode_text=Mock(side_effect=AssertionError("must reuse cached vector")))
        self.assertEqual(len(resumed.qualified), 1)
        self.assertEqual(json.loads(projection.read_text()), resumed.qualified)

    def test_corrupt_state_is_refused_and_never_overwritten(self):
        state = self.directory / "collection_state.json"
        state.write_text("{broken JSON", encoding="utf-8")
        with self.assertRaises((ValueError, RuntimeError)):
            self.collector()
        self.assertEqual(state.read_text(), "{broken JSON")

    def test_configuration_change_is_refused_without_overwriting_state(self):
        collector = self.collector()
        collector.add_article(article(0))
        collector.save()
        state = self.directory / "collection_state.json"
        original = state.read_bytes()
        for changes in ({"target_count": 3}, {"model_name": "different/model"}, {"distance_threshold": 0.3}):
            with self.subTest(changes=changes):
                with self.assertRaises((ValueError, RuntimeError)):
                    self.collector(**changes)
                self.assertEqual(state.read_bytes(), original)

    def test_resume_refuses_inconsistent_embedding_cache(self):
        collector = self.collector()
        collector.add_article(article(0))
        collector.save()
        state = self.directory / "collection_state.json"
        original = json.loads(state.read_text())
        for corrupt_vectors in ({}, {collector.articles[0]["dataset_article_id"]: [0.0, 0.0]}):
            with self.subTest(vectors=corrupt_vectors):
                damaged = dict(original, vectors=corrupt_vectors)
                state.write_text(json.dumps(damaged), encoding="utf-8")
                before = state.read_bytes()
                with self.assertRaises((ValueError, RuntimeError)):
                    self.collector()
                self.assertEqual(state.read_bytes(), before)

    def test_resume_refuses_text_changed_after_embedding_was_cached(self):
        collector = self.collector()
        collector.add_article(article(0))
        collector.save()
        state = self.directory / "collection_state.json"
        damaged = json.loads(state.read_text())
        damaged["articles"][0]["full_body"] = "Changed text no longer matches stored vector"
        state.write_text(json.dumps(damaged), encoding="utf-8")
        before = state.read_bytes()
        with self.assertRaises((ValueError, RuntimeError)):
            self.collector()
        self.assertEqual(state.read_bytes(), before)

    def test_checkpoint_failure_is_fatal_and_does_not_replace_saved_state(self):
        collector = self.collector()
        before = collector.state_path.read_bytes()
        with patch.object(dataset, "atomic_write_json", side_effect=OSError("disk unavailable")):
            with self.assertRaises(dataset.DatasetPersistenceError):
                collector.add_article(article(0))
        self.assertEqual(collector.state_path.read_bytes(), before)


class DatasetCollectorLockTests(unittest.TestCase):
    def test_competing_process_lock_is_refused_then_released(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            with dataset.collection_lock(folder):
                with self.assertRaises((RuntimeError, BlockingIOError)):
                    with dataset.collection_lock(folder):
                        self.fail("Second writer unexpectedly acquired collection lock")
            with dataset.collection_lock(folder):
                pass

    def test_loading_production_novelty_constants_does_not_import_model_or_database(self):
        before = set(sys.modules)
        model_name, threshold = dataset.load_novelty_config()
        added = set(sys.modules) - before
        self.assertIsInstance(model_name, str)
        self.assertTrue(model_name)
        self.assertGreaterEqual(threshold, 0)
        self.assertLessEqual(threshold, 2)
        self.assertNotIn("database", added)
        self.assertNotIn("ai_models.novelty_detection", added)
        self.assertNotIn("sentence_transformers", added)


class CollectOnceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def collector(self, target=3):
        return dataset.DatasetCollector(
            self.directory, target_count=target, asset_filter=lambda _item: True,
            encode_text=encode, model_name="offline/test-encoder",
            distance_threshold=0.2, key_function=keys,
        )

    def scheduler(self, candidates, scraped):
        session = Mock()
        session.headers = {}
        context = MagicMock()
        context.__enter__.return_value = session
        requests = ModuleType("requests")
        requests.Session = Mock(return_value=context)
        return SimpleNamespace(
            requests=requests, BROWSER_HEADERS={"User-Agent": "offline-dataset-test"},
            DELAY_BETWEEN_REQUESTS=0.01,
            fetch_latest_rss=Mock(return_value=candidates),
            scrape_article=Mock(side_effect=scraped),
            write_json_atomic=Mock(), run_scheduler=Mock(),
        ), session

    def poll(self, collector, scheduler):
        with patch.object(dataset.time, "sleep") as sleep, redirect_stdout(io.StringIO()):
            result = dataset.collect_once(collector, scheduler, candidate_limit=1000)
        scheduler.write_json_atomic.assert_not_called()
        scheduler.run_scheduler.assert_not_called()
        return result, sleep

    def test_known_urls_skipped_before_scrape_and_failed_bodies_retained(self):
        collector = self.collector()
        collector.add_article(article(0))
        collector.save()
        failed = article(2, full_body=None, scrape_status="failed", scrape_error="rate limited")
        scheduler, session = self.scheduler(
            [article(0), article(1), article(2)], [article(1), failed, failed, failed],
        )
        self.poll(collector, scheduler)
        scheduler.fetch_latest_rss.assert_called_once_with(session, limit=1000)
        self.assertEqual(scheduler.scrape_article.call_count, 2)
        self.assertEqual(session.headers["User-Agent"], "offline-dataset-test")
        self.assertEqual(len(collector.articles), 3)
        self.assertEqual(len(collector.qualified), 2)
        self.assertEqual(collector.articles[-1]["qualification_status"], "rejected_no_full_body")
        self.assertEqual(collector.articles[-1]["scrape_error"], "rate limited")
        self.assertTrue((self.directory / "collection_state.json").is_file())
        scheduler.scrape_article.reset_mock()
        self.poll(collector, scheduler)
        scheduler.scrape_article.assert_called_once()
        scheduler.scrape_article.reset_mock()
        self.poll(collector, scheduler)
        scheduler.scrape_article.assert_called_once()
        self.assertEqual(collector.articles[-1]["collection_scrape_attempts"], 3)
        scheduler.scrape_article.reset_mock()
        self.poll(collector, scheduler)
        scheduler.scrape_article.assert_not_called()
        self.assertEqual(len(collector.articles), 3)

    def test_failed_full_body_recovers_on_later_poll_without_duplicate_row(self):
        collector = self.collector()
        collector.add_article(article(0, full_body=None, scrape_status="failed", scrape_error="rate limited"))
        identity = collector.articles[0]["dataset_article_id"]
        scheduler, _ = self.scheduler([article(0)], [article(0)])
        self.poll(collector, scheduler)
        scheduler.scrape_article.assert_called_once()
        self.assertEqual(len(collector.articles), 1)
        self.assertEqual(len(collector.qualified), 1)
        self.assertEqual(collector.articles[0]["dataset_article_id"], identity)
        self.assertEqual(collector.articles[0]["qualification_status"], "qualified")
        self.assertIn("rate limited", collector.articles[0]["collection_attempt_errors"])

    def test_already_complete_dataset_does_not_fetch_or_scrape_again(self):
        collector = self.collector(target=1)
        collector.add_article(article(0))
        scheduler, _ = self.scheduler([article(1)], [article(1)])
        self.poll(collector, scheduler)
        scheduler.fetch_latest_rss.assert_not_called()
        scheduler.scrape_article.assert_not_called()
        self.assertEqual(len(collector.qualified), 1)

    def test_poll_stops_downloading_when_target_is_reached(self):
        collector = self.collector(target=2)
        collector.add_article(article(0))
        scheduler, _ = self.scheduler([article(1), article(2)], [article(1), article(2)])
        self.poll(collector, scheduler)
        self.assertTrue(collector.complete)
        self.assertEqual(scheduler.scrape_article.call_count, 1)
        self.assertEqual(len(collector.articles), 2)

    def test_repeated_failed_feed_entry_is_attempted_only_once_per_poll(self):
        collector = self.collector()
        failed = article(0, full_body=None, scrape_status="failed", scrape_error="rate limited")
        scheduler, _ = self.scheduler([article(0), article(0), article(0)], [failed])
        self.poll(collector, scheduler)
        scheduler.scrape_article.assert_called_once()
        self.assertEqual(len(collector.articles), 1)
        self.assertEqual(collector.articles[0]["collection_scrape_attempts"], 1)

    def test_unexpected_extraction_failure_is_retained_and_next_article_continues(self):
        collector = self.collector()
        scheduler, _ = self.scheduler(
            [article(0), article(1)], [RuntimeError("unexpected extraction error"), article(1)],
        )
        self.poll(collector, scheduler)
        self.assertEqual(scheduler.scrape_article.call_count, 2)
        self.assertEqual(len(collector.articles), 2)
        self.assertEqual(len(collector.qualified), 1)
        self.assertEqual(collector.articles[0]["qualification_status"], "rejected_no_full_body")
        self.assertIn("unexpected extraction error", collector.articles[0]["scrape_error"])
        resumed = self.collector()
        self.assertEqual(len(resumed.articles), 2)

    def test_keyboard_interrupt_retains_encountered_article_for_resume(self):
        collector = self.collector()
        scheduler, _ = self.scheduler([article(0)], [KeyboardInterrupt()])
        with self.assertRaises(KeyboardInterrupt):
            self.poll(collector, scheduler)
        resumed = self.collector()
        self.assertEqual(len(resumed.articles), 1)
        self.assertEqual(resumed.articles[0]["url"], article(0)["url"])
        self.assertEqual(resumed.articles[0]["qualification_status"], "rejected_no_full_body")
        self.assertIn("interrupted", resumed.articles[0]["scrape_error"].lower())
        self.assertTrue(resumed.needs_scrape(article(0)))


if __name__ == "__main__":
    unittest.main()

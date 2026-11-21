"""Offline request-flow and real saved-HTML checks for the pruned scraper copy."""

from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from lxml import html
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import compare_prune_xpath as comparison
import rss_scrape_scheduler as original
import rss_scrape_scheduler_pruned as scraper
from scratch.test_prune_xpath_comparison import FIRST, LAST, READ_MORE, SUBSCRIPTION, TRENDING, page
from test_article_body_scraper import FIELDS, html_filename


def rss_article(index: int = 1):
    return {
        "source": "CoinDesk", "guid": f"guid-{index}",
        "title": f"RSS headline {index} stays unchanged",
        "rss_summary": "Saved RSS description",
        "url": f"https://www.coindesk.com/business/2026/10/18/story-{index}",
        "image_url": "https://example.org/article.jpg",
        "published_at": "Sun, 18 Oct 2026 00:00:00 GMT", "categories": ["Finance"],
        "rss_fetched_at": "2026-10-18T00:00:00+00:00",
    }


def response(payload: bytes, url: str, status: int = 200):
    value = requests.Response()
    value.status_code = status
    value.url = url
    value.headers["Content-Type"] = "text/html; charset=utf-8"
    value._content = payload
    return value


class PrunedArticleTests(unittest.TestCase):
    def test_approved_removals_preserve_rss_metadata_schema_and_article_sections(self):
        source = rss_article()
        before = deepcopy(source)
        client = Mock()
        client.get.return_value = response(page(), source["url"])
        result = scraper.scrape_article(client, source)
        self.assertEqual(source, before)
        self.assertEqual(set(result), set(FIELDS))
        self.assertEqual(result["scrape_status"], "success")
        self.assertIsNone(result["scrape_error"])
        for name, value in source.items():
            self.assertEqual(result[name], value)
        for text in (FIRST, LAST, READ_MORE, SUBSCRIPTION, "Today’s signal"):
            self.assertIn(text, result["full_body"])
        for text in (TRENDING, "What’s trending", "RECOMMENDATION:", "SITE FOOTER:"):
            self.assertNotIn(text, result["full_body"])
        client.get.assert_called_once_with(source["url"], timeout=30)

    def test_extraction_options_are_explicit_and_no_strict_body_selector_is_required(self):
        source = rss_article()
        client = Mock()
        client.get.return_value = response(page(live=True), source["url"])
        with patch.object(scraper.trafilatura, "extract", return_value="Live update news.") as extract:
            result = scraper.scrape_article(client, source)
        self.assertEqual(result["full_body"], "Live update news.")
        kwargs = extract.call_args.kwargs
        self.assertEqual(kwargs, {
            "include_comments": False, "include_tables": False,
            "favor_precision": False, "prune_xpath": scraper.PRUNE_XPATH,
        })

    def test_boundary_marking_matches_approved_experiment_including_ambiguous_cases(self):
        contents = [
            f'<p>{FIRST}</p><h2>What’s trending</h2><p>{TRENDING}</p><h2>Keep section</h2><p>{LAST}</p>',
            f'<p>{FIRST}</p><h2>WHAT\'S TRENDING</h2><p>{TRENDING}</p>',
            f'<p>{FIRST}</p><h3>What’s trending</h3><h4>Subsection</h4><p>{TRENDING}</p><h2>Keep</h2><p>{LAST}</p>',
            f'<p>{FIRST}</p><h2>What’s trending</h2><div><h2>Nested boundary</h2><p>{LAST}</p></div>',
            f'<p>{FIRST}</p><h2>What’s trending</h2>Ambiguous direct text<p>{TRENDING}</p>',
            f'<p>{FIRST}</p><p>What’s trending is discussed in this news paragraph.</p><p>{LAST}</p>',
        ]
        for content in contents:
            raw = page(content=content)
            expected = html.fromstring(raw)
            comparison.plan_pruning(expected)
            with self.subTest(content=content), patch.object(scraper.LOGGER, "warning"):
                actual = scraper.prepare_pruned_html(raw)
                self.assertEqual(html.tostring(actual), html.tostring(expected))

    def test_http_connection_empty_and_malformed_html_failures_remain_records(self):
        source = rss_article()
        cases = [
            response(b"Denied", source["url"], 403),
            response(b"", source["url"]),
            response(b"<html><body>Empty extraction fixture</body></html>", source["url"]),
        ]
        for item in cases:
            client = Mock()
            client.get.return_value = item
            with self.subTest(status=item.status_code, content=item.content[:10]):
                with patch.object(scraper.trafilatura, "extract", return_value=None):
                    result = scraper.scrape_article(client, source)
                self.assertEqual(result["scrape_status"], "failed")
                self.assertIsNone(result["full_body"])
                self.assertTrue(result["scrape_error"])
                self.assertEqual(result["title"], source["title"])
        client = Mock()
        client.get.side_effect = requests.ConnectionError("offline fixture")
        result = scraper.scrape_article(client, source)
        self.assertEqual(result["scrape_status"], "failed")
        self.assertIn("offline fixture", result["scrape_error"])

    def test_saved_rendered_pages_match_the_completed_pruning_experiment(self):
        run = ROOT / "output/article_body_scrape_test/full_20261031_01"
        expected_run = ROOT / "output/article_body_scrape_test/prune_xpath_20261031_01"
        if not (run / "source_snapshot.json").exists() or not (expected_run / "pruned_scraped_news.json").exists():
            self.skipTest("Local research HTML/result snapshots are not present")
        source = json.loads((run / "source_snapshot.json").read_text())
        expected = json.loads((expected_run / "pruned_scraped_news.json").read_text())
        checked = 0
        for index, (saved, reference) in enumerate(zip(source, expected), 1):
            if reference["scrape_status"] != "success":
                continue
            article = {name: saved[name] for name in rss_article()}
            client = Mock()
            path = run / "html" / html_filename(index, saved["url"])
            client.get.return_value = response(path.read_bytes(), saved["url"])
            with self.subTest(source_index=index):
                result = scraper.scrape_article(client, article)
                self.assertEqual(result["scrape_status"], "success")
                self.assertEqual(result["full_body"], reference["full_body"])
                self.assertEqual(set(result), set(FIELDS))
            checked += 1
        self.assertEqual(checked, 29)


class SchedulerFlowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.paths = {
            "RSS_TEMP_FILE": self.directory / "rss_pruned/rss_temp.json",
            "RSS_HISTORY_FILE": self.directory / "rss_pruned/rss_history.json",
            "SCRAPED_NEWS_FILE": self.directory / "rss_pruned/scraped_news.json",
        }
        for name, value in self.paths.items():
            patched = patch.object(scraper, name, value)
            patched.start()
            self.addCleanup(patched.stop)
        silence = redirect_stdout(io.StringIO())
        silence.__enter__()
        self.addCleanup(silence.__exit__, None, None, None)

    def test_one_session_rss_first_known_history_skipped_delay_and_checkpoints(self):
        scraper.write_json_atomic(self.paths["RSS_HISTORY_FILE"], [rss_article(1)])
        items = ''.join(
            f'<item><title>RSS title {i}</title><link>{rss_article(i)["url"]}</link>'
            f'<guid>guid-{i}</guid><description>RSS description</description></item>'
            for i in (1, 2, 3)
        )
        feed = f'<rss version="2.0"><channel><title>Fixture feed</title>{items}</channel></rss>'.encode()
        client = Mock()
        client.headers = {}
        client.get.side_effect = [response(feed, scraper.RSS_URL),
                                  response(page(2), rss_article(2)["url"]),
                                  response(page(3), rss_article(3)["url"])]
        manager = Mock()
        manager.__enter__ = Mock(return_value=client)
        manager.__exit__ = Mock(return_value=False)
        writes = []
        original_write = scraper.write_json_atomic

        def save(path, data):
            writes.append((path, deepcopy(data)))
            original_write(path, data)

        with patch.object(scraper.requests, "Session", return_value=manager) as session_factory, \
             patch.object(scraper.time, "sleep") as sleep, \
             patch.object(scraper, "write_json_atomic", side_effect=save):
            stats = scraper.run_scheduler()
        session_factory.assert_called_once_with()
        self.assertEqual(client.headers, scraper.BROWSER_HEADERS)
        self.assertEqual(client.get.call_args_list[0].args, (scraper.RSS_URL,))
        self.assertEqual(client.get.call_args_list[0].kwargs, {"timeout": 20})
        self.assertEqual([call.args[0] for call in client.get.call_args_list[1:]],
                         [rss_article(2)["url"], rss_article(3)["url"]])
        self.assertTrue(all(call.kwargs == {"timeout": 30} for call in client.get.call_args_list[1:]))
        sleep.assert_called_once_with(5.0)
        self.assertEqual(stats, {"rss_items": 3, "new_items": 2, "scrape_success": 2, "scrape_failed": 0})
        body_writes = [data for path, data in writes if path == self.paths["SCRAPED_NEWS_FILE"]]
        self.assertEqual([len(data) for data in body_writes], [0, 1, 2])
        self.assertEqual(writes[-1][0], self.paths["RSS_HISTORY_FILE"])
        self.assertEqual(len(scraper.read_json_list(self.paths["RSS_HISTORY_FILE"])), 3)

    def test_direct_reset_touches_only_the_copy_files_and_preserves_other_files(self):
        original_folder = self.directory / "original_output"
        original_folder.mkdir()
        for name in ("rss_temp.json", "rss_history.json", "scraped_news.json"):
            (original_folder / name).write_text("ORIGINAL DATA")
        for path in self.paths.values():
            scraper.write_json_atomic(path, [rss_article()])
        marker = self.directory / "rss_pruned/keep.txt"
        marker.write_text("Do not delete")
        with patch.object(scraper.requests, "Session") as network:
            scraper.main()
        network.assert_not_called()
        for path in self.paths.values():
            self.assertEqual(json.loads(path.read_text()), [])
        self.assertEqual(marker.read_text(), "Do not delete")
        self.assertTrue(all(path.read_text() == "ORIGINAL DATA" for path in original_folder.iterdir()))

    def test_feed_error_does_not_advance_history(self):
        known = [rss_article()]
        scraper.write_json_atomic(self.paths["RSS_HISTORY_FILE"], known)
        client = Mock()
        client.headers = {}
        client.get.side_effect = requests.ConnectionError("offline feed")
        manager = Mock()
        manager.__enter__ = Mock(return_value=client)
        manager.__exit__ = Mock(return_value=False)
        with patch.object(scraper.requests, "Session", return_value=manager):
            with self.assertRaises(requests.ConnectionError):
                scraper.run_scheduler()
        self.assertEqual(scraper.read_json_list(self.paths["RSS_HISTORY_FILE"]), known)
        self.assertEqual(scraper.read_json_list(self.paths["SCRAPED_NEWS_FILE"]), [])


class OriginalBehaviorParityTests(unittest.TestCase):
    def test_pure_functions_and_request_constants_match_original(self):
        self.assertEqual(scraper.RSS_URL, original.RSS_URL)
        self.assertEqual(scraper.RSS_LIMIT, original.RSS_LIMIT)
        self.assertEqual(scraper.BROWSER_HEADERS, original.BROWSER_HEADERS)
        self.assertEqual(scraper.DELAY_BETWEEN_REQUESTS, original.DELAY_BETWEEN_REQUESTS)
        for value in ("", "https://WWW.coindesk.com/story/?utm_source=test&x=1#part", "https://coindesk.com/story?fbclid=abc"):
            self.assertEqual(scraper.normalize_url(value), original.normalize_url(value))
        for value in ("", "News.\nNews.\nOther.", "News.\n- 1 - 2\nFooter", "\n  Article.  \n"):
            self.assertEqual(scraper.clean_full_body(value), original.clean_full_body(value))
        for value in (rss_article(), {"url": "https://coindesk.com/story?utm_source=test"}, {}):
            self.assertEqual(scraper.article_keys(value), original.article_keys(value))
        for value in ({}, {"media_content": [{"url": "https://example.org/a.jpg"}]}):
            self.assertEqual(scraper.extract_rss_image_url(value), original.extract_rss_image_url(value))
        self.assertNotEqual(scraper.SCRAPED_NEWS_FILE.resolve(), original.SCRAPED_NEWS_FILE.resolve())


if __name__ == "__main__":
    unittest.main()

"""Offline boundary and persistence tests for the separate extraction experiment."""

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

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import test_article_body_scraper as scraper


FIRST = (
    "Deutsche Bank plans a cryptocurrency safekeeping service for institutional clients "
    "in Asia in 2027, according to the bank's announcement."
)
LAST = (
    "The German launch remains subject to regulatory approval, and the bank will manage "
    "clients' wallets and private keys rather than asking clients to manage them."
)
TITLE = "Deutsche Bank announces a cryptocurrency custody expansion"


def article(index: int = 1, **changes):
    result = {
        "source": "CoinDesk", "guid": f"guid-{index}",
        "title": "OLD RSS HEADLINE MUST NOT BE REUSED",
        "url": f"https://www.coindesk.com/business/2026/10/18/story-{index}",
        "rss_summary": "Saved RSS excerpt", "rss_fetched_at": "2026-10-18T02:00:00+00:00",
        "image_url": "https://cdn.coindesk.com/old.jpg",
        "published_at": "Sun, 18 Oct 2026 02:00:00 GMT", "categories": ["Old category"],
        "full_body": "OLD BODY MUST NOT BE REUSED", "dataset_article_id": f"dataset-{index}",
        "is_redundant": False, "qualification_status": "qualified",
    }
    result.update(changes)
    return result


def page(*, guid="guid-1", title=TITLE, metadata=True, narrative=None):
    ld = {
        "@type": "NewsArticle", "identifier": guid, "headline": title,
        "datePublished": "2026-10-19T02:00:00.000Z", "articleSection": "Finance",
        "keywords": ["Stablecoins", "stablecoins", "Bitcoin"],
        "image": {"@type": "ImageObject", "url": "https://cdn.coindesk.com/fresh.jpg"},
    }
    head = '<meta charset="utf-8">'
    if metadata:
        head += f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    blocks = narrative if narrative is not None else (
        '<div class="article-content-wrapper" data-article-body-start>'
        '<div id="se-summary-widget"><div><button aria-label="Expand summary">Summary</button>'
        '<div class="document-body"><ul><li>SUMMARY WIDGET MUST BE EXCLUDED</li></ul></div>'
        '</div></div>'
        f'<div class="font-body document-body"><p>{FIRST}</p></div></div>'
        '<div class="advertisement">ADVERTISEMENT MUST BE EXCLUDED</div>'
        f'<div class="article-content-wrapper"><div class="document-body font-body"><p>{LAST}</p></div></div>'
    )
    return (
        f'<!doctype html><html><head>{head}</head><body>'
        '<header><h1>WEBSITE HEADER MUST BE EXCLUDED</h1></header>'
        f'<main><h1>{title}</h1>{blocks}'
        '<div class="article-content-wrapper"><div data-module-name="article-bottom-news">'
        '<h1>RECOMMENDATION HEADLINE MUST BE EXCLUDED</h1>'
        '<div class="article-content-wrapper"><div class="document-body">'
        '<p>RECOMMENDATION BODY MUST BE EXCLUDED</p></div></div></div></div></main>'
        '<footer><div class="article-content-wrapper"><div class="document-body">'
        '<p>FOOTER DISCLOSURE MUST BE EXCLUDED</p></div></div></footer></body></html>'
    )


class ExtractPageTests(unittest.TestCase):
    def test_fresh_headline_and_all_narrative_chunks_without_surrounding_regions(self):
        record = article()
        before = deepcopy(record)
        fields, audit = scraper.extract_page(page(), record)
        self.assertEqual(record, before)
        self.assertEqual(fields["title"], TITLE)
        self.assertIn(FIRST, fields["full_body"])
        self.assertIn(LAST, fields["full_body"])
        self.assertLess(fields["full_body"].index(FIRST), fields["full_body"].index(LAST))
        for unwanted in ("OLD RSS", "OLD BODY", "SUMMARY WIDGET", "RECOMMENDATION", "FOOTER", "ADVERTISEMENT", TITLE):
            self.assertNotIn(unwanted, fields["full_body"])
        self.assertEqual(audit["selected_body_blocks"], 2)
        self.assertEqual(audit["excluded_bottom_modules"], 1)
        self.assertEqual(audit["source_segments_not_found_verbatim"], [])
        reasons = {r["reason"] for r in audit["excluded_regions"]}
        self.assertIn("article_bottom_news", reasons)
        self.assertIn("non_narrative_document_body", reasons)

    def test_real_article_lists_and_inline_names_are_preserved(self):
        content = (
            '<div class="article-content-wrapper"><div class="document-body">'
            f'<p>{FIRST}</p><ul><li>Bitcoin will be supported by the service at launch.</li>'
            '<li>Ether and USDC will also be supported by the bank.</li></ul>'
            f'<p>{LAST}</p></div></div>'
        )
        fields, audit = scraper.extract_page(page(narrative=content), article())
        self.assertIn("Bitcoin will be supported by the service at launch.", fields["full_body"])
        self.assertIn("Ether and USDC will also be supported by the bank.", fields["full_body"])
        self.assertFalse(audit["source_segments_not_found_verbatim"])

    def test_sidebar_with_matching_class_does_not_become_article_content(self):
        content = (
            f'<div class="article-content-wrapper"><div class="document-body"><p>{FIRST}</p><p>{LAST}</p></div></div>'
            '<aside><div class="article-content-wrapper"><div class="document-body">'
            '<p>SIDEBAR TEXT MUST BE EXCLUDED</p></div></div></aside>'
        )
        fields, audit = scraper.extract_page(page(narrative=content), article())
        self.assertNotIn("SIDEBAR TEXT", fields["full_body"])
        self.assertEqual(audit["selected_body_blocks"], 1)

    def test_missing_or_ambiguous_main_h1_is_failure_without_old_title_fallback(self):
        for document in (page().replace(f'<h1>{TITLE}</h1>', ''), page().replace(f'<h1>{TITLE}</h1>', f'<h1>{TITLE}</h1><h1>Another headline</h1>')):
            with self.subTest(document=document[:60]), self.assertRaises(scraper.ExtractionError):
                scraper.extract_page(document, article())

    def test_missing_main_body_or_wrong_structure_never_uses_whole_page(self):
        documents = [
            '<html><body><h1>Vercel Security Checkpoint</h1></body></html>',
            f'<html><body><main><h1>{TITLE}</h1><p>{FIRST}</p><p>{LAST}</p></main></body></html>',
            f'<html><body><main><h1>{TITLE}</h1><div class="document-body"><p>{FIRST}</p></div></main></body></html>',
            page(narrative='<div class="article-content-wrapper"><div><div class="document-body">Unverified nested body</div></div></div>'),
        ]
        for document in documents:
            with self.subTest(document=document[:90]), self.assertRaises(scraper.ExtractionError):
                scraper.extract_page(document, article())

    def test_mismatching_page_guid_is_failure(self):
        with self.assertRaisesRegex(scraper.ExtractionError, "identifier differs"):
            scraper.extract_page(page(guid="other-story"), article())

    def test_fresh_metadata_preferred_over_old_values_and_origin_is_logged(self):
        fields, audit = scraper.extract_page(page(), article())
        self.assertEqual(fields["image_url"], "https://cdn.coindesk.com/fresh.jpg")
        self.assertEqual(fields["published_at"], "Mon, 19 Oct 2026 02:00:00 GMT")
        self.assertEqual(fields["categories"], ["Finance", "Stablecoins", "Bitcoin"])
        self.assertTrue(all(v.startswith("page:") for v in audit["metadata_origins"].values()))

    def test_missing_optional_metadata_falls_back_explicitly_not_title_or_body(self):
        record = article()
        fields, audit = scraper.extract_page(page(metadata=False), record)
        for name in ("image_url", "published_at", "categories"):
            self.assertEqual(fields[name], record[name])
            self.assertEqual(audit["metadata_origins"][name], "saved_rss_fallback")
        self.assertEqual(fields["title"], TITLE)
        self.assertNotEqual(fields["full_body"], record["full_body"])

    def test_empty_extraction_fails_closed(self):
        with patch.object(scraper.trafilatura, "extract", return_value=None):
            with self.assertRaisesRegex(scraper.ExtractionError, "returned no text"):
                scraper.extract_page(page(), article())

    def test_content_dropped_by_existing_cleanup_is_exposed_in_audit(self):
        with patch.object(scraper, "clean_full_body", return_value=FIRST):
            fields, audit = scraper.extract_page(page(), article())
        self.assertEqual(fields["full_body"], FIRST)
        self.assertIn(LAST, audit["source_segments_not_found_verbatim"])
        self.assertIn("existing_pagination_or_duplicate_line_cleanup_changed_text", audit["warnings"])


class RunScrapeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.source = self.directory / "source.json"
        self.output = self.directory / "run"
        self.records = [article(), article(2)]
        self.source.write_text(json.dumps(self.records, indent=2) + '\n', encoding="utf-8")
        self.source_bytes = self.source.read_bytes()
        self.client = Mock()
        self.client.headers = {}
        self.silent = redirect_stdout(io.StringIO())
        self.silent.__enter__()
        self.addCleanup(self.silent.__exit__, None, None, None)
        # Avoid any dependency on the production batch during isolated tests.
        self.root_patch = patch.object(scraper, "ROOT", self.directory)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def response(self, index=1, *, status=200, document=None):
        response = requests.Response()
        response.status_code = status
        response.url = self.records[index - 1]["url"]
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        response._content = (document or page(guid=f"guid-{index}")).encode("utf-8")
        return response

    def read(self, name):
        return json.loads((self.output / name).read_text(encoding="utf-8"))

    def test_fresh_download_exact_schema_snapshot_identity_and_no_source_mutation(self):
        self.client.get.side_effect = [self.response(), self.response(2)]
        report = scraper.run_scrape(self.source, self.output, delay=0, session=self.client)
        rows = self.read("scraped_news.json")
        self.assertEqual(self.source.read_bytes(), self.source_bytes)
        self.assertEqual((self.output / "source_snapshot.json").read_bytes(), self.source_bytes)
        self.assertEqual(report["status"], "complete")
        self.assertEqual((report["success"], report["failed"], report["downloaded"], report["replayed"]), (2, 0, 2, 0))
        for i, row in enumerate(rows):
            self.assertEqual(set(row), set(scraper.FIELDS))
            self.assertEqual(len(row), 13)
            self.assertEqual(row["guid"], self.records[i]["guid"])
            self.assertEqual(row["title"], TITLE)
            self.assertEqual(row["rss_fetched_at"], self.records[i]["rss_fetched_at"])
            self.assertEqual(row["rss_summary"], self.records[i]["rss_summary"])
            self.assertNotIn("dataset_article_id", row)
            self.assertNotIn("is_redundant", row)
        comparisons = self.read("comparison.json")
        self.assertEqual([r["dataset_article_id"] for r in comparisons], ["dataset-1", "dataset-2"])
        self.assertEqual(comparisons[0]["old_title"], self.records[0]["title"])
        self.assertEqual(comparisons[0]["new_title"], TITLE)
        self.assertEqual(len(list((self.output / "html").glob("*.selected.html"))), 2)
        self.client.get.assert_any_call(self.records[0]["url"], timeout=30.0)

    def test_replay_uses_exact_source_index_url_key_without_network(self):
        cache = self.directory / "cached"
        cache.mkdir()
        filename = scraper.html_filename(2, self.records[1]["url"])
        (cache / filename).write_text(page(guid="guid-2"), encoding="utf-8")
        report = scraper.run_scrape(self.source, self.output, indices=[2], html_dir=cache, delay=0, session=self.client)
        self.client.get.assert_not_called()
        self.assertEqual((report["success"], report["downloaded"], report["replayed"]), (1, 0, 1))
        comparison = self.read("comparison.json")[0]
        self.assertEqual(comparison["source_index"], 2)
        self.assertEqual(comparison["transport"]["origin"], "saved_html_replay")

    def test_failed_download_retains_record_without_old_title_or_body(self):
        self.client.get.side_effect = [requests.ConnectionError("Offline test"), self.response(2)]
        report = scraper.run_scrape(self.source, self.output, delay=0, session=self.client)
        failed, successful = self.read("scraped_news.json")
        self.assertEqual((report["attempted"], report["success"], report["failed"]), (2, 1, 1))
        self.assertEqual(failed["scrape_status"], "failed")
        self.assertEqual(failed["title"], "")
        self.assertIsNone(failed["full_body"])
        self.assertIn("Offline test", failed["scrape_error"])
        self.assertEqual(successful["scrape_status"], "success")

    def test_http_error_html_is_saved_for_diagnosis_without_extraction(self):
        self.client.get.return_value = self.response(status=429, document="<html>Security checkpoint</html>")
        report = scraper.run_scrape(self.source, self.output, indices=[1], delay=0, session=self.client)
        self.assertEqual(report["failed"], 1)
        row = self.read("scraped_news.json")[0]
        self.assertEqual(row["title"], "")
        self.assertIsNone(row["full_body"])
        filename = scraper.html_filename(1, self.records[0]["url"])
        self.assertIn("Security checkpoint", (self.output / "html" / filename).read_text())

    def test_output_overwrite_refused_without_touching_previous_results(self):
        self.output.mkdir()
        marker = self.output / "marker.txt"
        marker.write_text("existing results")
        with self.assertRaises(FileExistsError):
            scraper.run_scrape(self.source, self.output, delay=0, session=self.client)
        self.assertEqual(marker.read_text(), "existing results")
        self.client.get.assert_not_called()

    def test_keyboard_interrupt_checkpoints_completed_attempts(self):
        self.client.get.side_effect = [self.response(), KeyboardInterrupt()]
        with self.assertRaises(KeyboardInterrupt):
            scraper.run_scrape(self.source, self.output, delay=0, session=self.client)
        self.assertEqual(len(self.read("scraped_news.json")), 1)
        report = self.read("report.json")
        self.assertEqual(report["status"], "interrupted")
        self.assertEqual(report["attempted"], 1)

    def test_invalid_selection_refused_before_output_or_download(self):
        for indices in ([0], [3], [1, 1], []):
            with self.subTest(indices=indices), self.assertRaises(ValueError):
                scraper.run_scrape(self.source, self.output, indices=indices, delay=0, session=self.client)
        self.assertFalse(self.output.exists())
        self.client.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""Offline checks of bounded HTML pruning, content retention and experiment output."""

from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from lxml import html

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import compare_prune_xpath as comparison


TITLE = "Deutsche Bank prepares a cryptocurrency safekeeping service"
FIRST = (
    "Deutsche Bank plans to offer cryptocurrency safekeeping to institutional clients "
    "in Asia in 2027, according to an announcement from the German bank."
)
LAST = (
    "The bank will manage clients' wallets and private keys, and the German launch "
    "remains subject to regulatory approval before customers can use the service."
)
READ_MORE = "Read more: The bank previously explained how its proposed cryptocurrency service will work."
SUBSCRIPTION = "Sign up here to receive the publisher's weekly newsletter about digital assets and banking."
TRENDING = "An unrelated exchange introduced a new trading competition for its retail customers this week."


def article(index: int = 1):
    return {
        "source": "CoinDesk", "guid": f"guid-{index}", "dataset_article_id": f"dataset-{index}",
        "url": f"https://www.coindesk.com/business/2026/10/18/example-{index}",
        "title": "OLD RSS TITLE", "full_body": "OLD ARTICLE BODY",
        "rss_summary": "Saved RSS description", "rss_fetched_at": "2026-10-18T00:00:00+00:00",
        "image_url": "https://example.org/old.jpg", "categories": ["Old category"],
        "published_at": "Sun, 18 Oct 2026 00:00:00 GMT", "is_redundant": False,
    }


def page(index: int = 1, *, content: str | None = None, title: str = TITLE, live: bool = False):
    metadata = {
        "@type": "LiveBlogPosting" if live else "NewsArticle", "identifier": f"guid-{index}",
        "headline": title, "datePublished": "2026-10-19T02:00:00.000Z", "articleSection": "Finance",
        "keywords": ["Bitcoin"], "image": {"url": "https://example.org/fresh.jpg"},
    }
    if content is None:
        content = (
            f"<p>{FIRST}</p><p>{READ_MORE}</p><p>{SUBSCRIPTION}</p>"
            f"<h2>What’s trending</h2><ul><li>{TRENDING}</li></ul>"
            f"<h2>Today’s signal</h2><p>{LAST}</p>"
            "<ul><li>Bitcoin and ether will be supported by the service at launch.</li></ul>"
        )
    if live:
        narrative = f'<div class="live-news-article"><article><h2>Update headline</h2><div class="font-body-lg text-xl text-default">{content}</div></article></div>'
    else:
        narrative = f'<div class="article-content-wrapper"><div class="document-body font-body-lg">{content}</div></div>'
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<script type="application/ld+json">{json.dumps(metadata)}</script></head><body>'
        '<header><p>Website navigation outside the article.</p></header>'
        f'<main><h1>{title}</h1>{narrative}'
        '<div data-module-name="article-bottom-news"><p>'
        'RECOMMENDATION: Another company announced unrelated news about its cryptocurrency exchange.'
        '</p></div></main>'
        '<footer data-module-name="footer"><p>SITE FOOTER: Publisher disclosure and unrelated website details.</p></footer>'
        '</body></html>'
    ).encode()


def narrative_document(content: str):
    return html.fromstring(page(content=content))


class PruningPlanTests(unittest.TestCase):
    def test_exact_section_is_bounded_by_next_equal_heading_and_preserves_requested_text(self):
        tree = html.fromstring(page())
        removals, warnings = comparison.plan_pruning(tree)
        result = comparison.pruned_copy(tree)
        text = result.text_content()
        for keep in (FIRST, LAST, READ_MORE, SUBSCRIPTION, "Today’s signal", "Bitcoin and ether will be supported"):
            self.assertIn(keep, text)
        for remove in ("What’s trending", TRENDING, "RECOMMENDATION:", "SITE FOOTER:"):
            self.assertNotIn(remove, text)
        self.assertFalse(warnings)
        self.assertEqual([r["tag"] for r in removals if r["rule"] == "whats_trending"], ["h2", "ul"])

    def test_higher_heading_and_parent_end_boundaries_preserve_following_blocks(self):
        for content in (
            f'<p>{FIRST}</p><h3>What’s trending</h3><p>{TRENDING}</p><h2>Another section</h2><p>{LAST}</p>',
            f'<p>{FIRST}</p><h2>What’s trending</h2><p>{TRENDING}</p>',
        ):
            tree = narrative_document(content)
            parent = tree.xpath('//main')[0]
            parent.append(html.fromstring(f'<div><h2>Following body block</h2><p>{LAST}</p></div>'))
            comparison.plan_pruning(tree)
            retained = comparison.pruned_copy(tree).text_content()
            self.assertNotIn(TRENDING, retained)
            self.assertIn(LAST, retained)
            self.assertIn("Following body block", retained)

    def test_lower_headings_belong_to_section_until_next_equal_heading(self):
        tree = narrative_document(
            f'<p>{FIRST}</p><h2>What’s trending</h2><h3>Subtopic</h3><p>{TRENDING}</p>'
            f'<h2>Return to the article</h2><p>{LAST}</p>'
        )
        comparison.plan_pruning(tree)
        retained = comparison.pruned_copy(tree).text_content()
        self.assertNotIn("Subtopic", retained)
        self.assertNotIn(TRENDING, retained)
        self.assertIn(LAST, retained)

    def test_heading_normalizes_apostrophe_case_and_whitespace_but_not_paragraph_mentions(self):
        for heading in ("What’s trending", "WHAT'S TRENDING", "  What's\n  trending "):
            tree = narrative_document(f'<p>{FIRST}</p><h2>{heading}</h2><p>{TRENDING}</p>')
            removals, _ = comparison.plan_pruning(tree)
            self.assertEqual(sum(r["rule"] == "whats_trending" for r in removals), 2)
        tree = narrative_document(
            f'<p>{FIRST}</p><p>What’s trending is a phrase mentioned in this actual article.</p>'
            f'<h2>What’s trending in banking today?</h2><p>{LAST}</p>'
        )
        removals, _ = comparison.plan_pruning(tree)
        self.assertFalse(any(r["rule"] == "whats_trending" for r in removals))
        self.assertIn(LAST, comparison.pruned_copy(tree).text_content())

    def test_nested_equal_heading_boundary_is_retained_for_review(self):
        tree = narrative_document(
            f'<p>{FIRST}</p><h2>What’s trending</h2><p>{TRENDING}</p>'
            f'<div><h2>Separate article section</h2><p>{LAST}</p></div>'
        )
        removals, warnings = comparison.plan_pruning(tree)
        self.assertIn("ambiguous_trending_section_retained_for_review", warnings)
        self.assertFalse(any(r["rule"] == "whats_trending" for r in removals))
        self.assertIn(TRENDING, comparison.pruned_copy(tree).text_content())
        self.assertIn(LAST, comparison.pruned_copy(tree).text_content())

    def test_nonempty_tail_is_retained_instead_of_ambiguous_section_deletion(self):
        tree = narrative_document(
            f'<p>{FIRST}</p><h2>What’s trending</h2>Ambiguous direct text outside a block.'
            f'<p>{TRENDING}</p><h2>Another section</h2><p>{LAST}</p>'
        )
        removals, warnings = comparison.plan_pruning(tree)
        self.assertIn("ambiguous_trending_section_retained_for_review", warnings)
        self.assertFalse(any(r["rule"] == "whats_trending" for r in removals))

    def test_site_footer_rule_does_not_remove_article_footer_or_summary_widget(self):
        tree = narrative_document(
            f'<p>{FIRST}</p><div id="se-summary"><p>Publisher summary remains untouched.</p></div>'
            f'<footer>Article-specific footer remains untouched.</footer><p>{LAST}</p>'
        )
        comparison.plan_pruning(tree)
        retained = comparison.pruned_copy(tree).text_content()
        self.assertIn("Publisher summary remains untouched.", retained)
        self.assertIn("Article-specific footer remains untouched.", retained)
        self.assertNotIn("SITE FOOTER:", retained)

    def test_existing_private_attribute_is_refused(self):
        tree = narrative_document(f'<p {comparison.TRENDING_ATTRIBUTE}="true">{FIRST}</p>')
        with self.assertRaises(ValueError):
            comparison.plan_pruning(tree)


class ExtractionComparisonTests(unittest.TestCase):
    def test_actual_trafilatura_preserves_news_readmore_subscription_and_later_section(self):
        record = article()
        original = deepcopy(record)
        result = comparison.compare_page(page(), record)
        self.assertEqual(record, original)
        body = result["pruned"]["full_body"]
        self.assertTrue(result["rendered_content_available"])
        for text in (FIRST, LAST, READ_MORE, SUBSCRIPTION, "Today’s signal", "Bitcoin and ether will be supported"):
            self.assertIn(text, body)
        for text in (TRENDING, "What’s trending", "SITE FOOTER:", "RECOMMENDATION:"):
            self.assertNotIn(text, body)
        self.assertFalse(result["retained_segments_missing_after_pruning"])
        self.assertEqual(result["pruned"]["title"], TITLE)
        self.assertEqual(result["pruned"]["image_url"], "https://example.org/fresh.jpg")
        self.assertEqual(result["pruned"]["published_at"], "Mon, 19 Oct 2026 02:00:00 GMT")
        for method in ("baseline", "pruned"):
            self.assertEqual(set(result[method]), set(comparison.FIELDS))
            self.assertEqual(len(result[method]), 13)

    def test_both_conditions_have_identical_options_except_prune_xpath(self):
        with patch.object(comparison.trafilatura, "extract", side_effect=[FIRST + '\n' + LAST, FIRST + '\n' + LAST]) as extract:
            result = comparison.compare_page(page(content=f'<p>{FIRST}</p><p>{LAST}</p>'), article())
        before_options = extract.call_args_list[0].kwargs
        after_options = extract.call_args_list[1].kwargs
        self.assertEqual(before_options, {"include_comments": False, "include_tables": False, "favor_precision": False})
        self.assertEqual(after_options, {**before_options, "prune_xpath": comparison.PRUNE_XPATH})
        self.assertTrue(result["rendered_content_available"])

    def test_actual_live_blog_is_eligible_without_document_body(self):
        result = comparison.compare_page(page(live=True, content=f'<p>{FIRST}</p><p>{LAST}</p>'), article())
        self.assertTrue(result["rendered_content_available"])
        self.assertEqual(result["pruned"]["scrape_status"], "success")
        self.assertIn(FIRST, result["pruned"]["full_body"])
        self.assertIn(LAST, result["pruned"]["full_body"])

    def test_header_only_response_never_turns_nonempty_navigation_into_success(self):
        document = f'<html><body><main><h1>{TITLE}</h1><div>Navigation only</div></main></body></html>'.encode()
        with patch.object(comparison.trafilatura, "extract", return_value="Navigation is nonempty but is not news."):
            result = comparison.compare_page(document, article())
        self.assertFalse(result["rendered_content_available"])
        for method in ("baseline", "pruned"):
            self.assertIsNone(result[method]["full_body"])
            self.assertEqual(result[method]["scrape_status"], "failed")
            self.assertNotEqual(result[method]["title"], "OLD RSS TITLE")
        self.assertIn("Navigation", result["baseline_extracted_text"])
        self.assertIn("Navigation", result["pruned_extracted_text"])

    def test_retention_audit_reports_fact_dropped_by_extractor(self):
        document = page(content=f'<p>{FIRST}</p><p>{LAST}</p>')
        with patch.object(comparison.trafilatura, "extract", side_effect=[FIRST + '\n' + LAST, FIRST]):
            result = comparison.compare_page(document, article())
        self.assertIn(LAST, result["retained_segments_missing_after_pruning"])
        self.assertIn("retained_article_segments_lost_from_extraction", result["warnings"])


class SavedRunTests(unittest.TestCase):
    def test_offline_outputs_are_separate_exact_schema_and_provenance_preserving(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source = folder / "saved_run"
            source.mkdir()
            (source / "html").mkdir()
            records = [article(), article(2)]
            raw_source = (json.dumps(records, ensure_ascii=False, indent=2) + '\n').encode()
            (source / "source_snapshot.json").write_bytes(raw_source)
            pages = [page(), f'<html><body><main><h1>{TITLE}</h1></main></body></html>'.encode()]
            html_paths = []
            for i, record in enumerate(records, 1):
                path = source / "html" / comparison.html_filename(i, record["url"])
                path.write_bytes(pages[i-1])
                html_paths.append(path)
            destination = folder / "new_output"
            with patch("requests.sessions.Session.request", side_effect=AssertionError("Network is forbidden")) as request:
                with redirect_stdout(io.StringIO()):
                    report = comparison.run_comparison(source, destination)
                request.assert_not_called()
            self.assertEqual((source / "source_snapshot.json").read_bytes(), raw_source)
            self.assertEqual((destination / "source_snapshot.json").read_bytes(), raw_source)
            self.assertEqual([p.read_bytes() for p in html_paths], pages)
            self.assertEqual(report["source_sha256"], hashlib.sha256(raw_source).hexdigest())
            self.assertEqual(report["network_requests"], 0)
            self.assertEqual((report["articles"], report["rendered_content_available"], report["unavailable_rendered_content"]), (2, 1, 1))
            for name in ("baseline_scraped_news.json", "pruned_scraped_news.json"):
                output = json.loads((destination / name).read_text())
                self.assertEqual(len(output), 2)
                self.assertTrue(all(set(row) == set(comparison.FIELDS) for row in output))
                self.assertEqual([row["guid"] for row in output], ["guid-1", "guid-2"])
            audit = json.loads((destination / "comparison.json").read_text())
            self.assertEqual([row["source_index"] for row in audit], [1, 2])
            self.assertEqual([row["dataset_article_id"] for row in audit], ["dataset-1", "dataset-2"])
            self.assertEqual([row["saved_html_sha256"] for row in audit], [hashlib.sha256(p).hexdigest() for p in pages])
            marker = destination / "report.json"
            previous = marker.read_bytes()
            with self.assertRaises(FileExistsError):
                comparison.run_comparison(source, destination)
            self.assertEqual(marker.read_bytes(), previous)


if __name__ == "__main__":
    unittest.main()

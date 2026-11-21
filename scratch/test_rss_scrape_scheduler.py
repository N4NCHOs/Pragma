"""Offline checks for the HTML pruning in rss_scrape_scheduler.py.

Self-contained: no network, no output files. Run from the project root:
    python -m unittest scratch.test_rss_scrape_scheduler
"""

from __future__ import annotations

import unittest
from unittest.mock import Mock

import trafilatura

import rss_scrape_scheduler as scheduler

ARTICLE = " ".join(
    f"Paragraph {i}: the exchange reported that customer withdrawals resumed after a "
    f"short pause, and regulators said they were reviewing the incident in detail."
    for i in range(1, 7)
)


def page(trending: str = "", extra_body: str = "") -> str:
    paragraphs = "".join(f"<p>{part}.</p>" for part in ARTICLE.split(". ") if part)
    return f"""<html><head><title>Test</title></head><body>
    <main><article><h1>Exchange resumes withdrawals</h1>
      <div class="document-body">{paragraphs}{trending}{extra_body}
        <div data-module-name="article-bottom-news"><p>LATEST NEWS: an unrelated headline
          about a memecoin listing that is not part of this story at all.</p></div>
        <footer data-module-name="footer"><p>FOOTER: About us, careers, advertising,
          and terms of use for the publisher's website and newsletters.</p></footer>
      </div>
    </article></main>
    </body></html>"""


def extract(html_text: str) -> str:
    return trafilatura.extract(
        scheduler.prepare_pruned_html(html_text), include_comments=False,
        include_tables=False, favor_precision=False, prune_xpath=scheduler.PRUNE_XPATH,
    ) or ""


class PruningTests(unittest.TestCase):
    def test_footer_and_bottom_news_removed_article_kept(self):
        text = extract(page())
        self.assertIn("Paragraph 1", text)
        self.assertIn("Paragraph 6", text)
        self.assertNotIn("FOOTER", text)
        self.assertNotIn("LATEST NEWS", text)

    def test_bounded_trending_section_removed(self):
        trending = "<h2>What’s trending</h2><ul><li>TRENDING: dog token soars</li></ul>"
        after = "<h2>Background</h2><p>BACKGROUND: the pause lasted two hours.</p>"
        text = extract(page(trending, after))
        self.assertNotIn("TRENDING", text)
        self.assertIn("BACKGROUND", text)

    def test_ambiguous_trending_section_retained(self):
        # A nested heading of the same level makes the boundary ambiguous.
        trending = ("<h2>What's trending</h2><div><p>TRENDING: item</p>"
                    "<h2>Inner heading</h2><p>INNER: real article text.</p></div>")
        with self.assertLogs(scheduler.LOGGER, level="WARNING"):
            tree = scheduler.prepare_pruned_html(page(trending))
        self.assertEqual(tree.xpath(f'//*[@{scheduler.TRENDING_ATTRIBUTE}]'), [])

    def test_private_attribute_in_input_is_rejected(self):
        html_text = page(f'<p {scheduler.TRENDING_ATTRIBUTE}="true">x</p>')
        with self.assertRaises(ValueError):
            scheduler.prepare_pruned_html(html_text)

    def test_scrape_article_uses_pruning_and_keeps_rss_title(self):
        response = Mock(content=page().encode("utf-8"))
        response.raise_for_status = Mock()
        session = Mock(get=Mock(return_value=response))
        article = {"url": "https://example.com/a", "title": "RSS title"}
        result = scheduler.scrape_article(session, article)
        self.assertEqual(result["scrape_status"], "success")
        self.assertEqual(result["title"], "RSS title")
        self.assertNotIn("FOOTER", result["full_body"])

    def test_scrape_article_records_failure(self):
        session = Mock(get=Mock(side_effect=scheduler.requests.ConnectionError("offline")))
        result = scheduler.scrape_article(session, {"url": "https://example.com/a"})
        self.assertEqual(result["scrape_status"], "failed")
        self.assertIsNone(result["full_body"])


if __name__ == "__main__":
    unittest.main()

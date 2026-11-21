"""Offline tests for conservative, auditable article-footer preprocessing.

Run with: python -m unittest scratch.test_article_preprocessing -v
These tests do not load NLP models, connect to PostgreSQL, or fetch articles.
"""

from __future__ import annotations

from dataclasses import is_dataclass
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from article_preprocessing import (
    EMPTY_FOOTER_HEADING,
    KNOWN_PROMOTIONAL_FOOTER,
    PREPROCESSING_VERSION,
    clean_article_footer,
    clean_article_footer_with_audit,
)


OBSERVED_PARAGRAPH = (
    "Diversified RWA stablecoins sustain 5-7% yield from real credit as crypto "
    "funding compresses to ~4%. GENIUS pushes yield off-chain; TAM grows to "
    "$4B in 3 years."
)


def footer(newline: str = "\n") -> str:
    return OBSERVED_PARAGRAPH + newline + "Why it matters:"


class ArticleFooterPreprocessingTests(unittest.TestCase):
    def assert_unchanged(self, original: str) -> None:
        result = clean_article_footer_with_audit(original)
        self.assertEqual(result.text, original)
        self.assertEqual(result.removed_text, "")
        self.assertEqual(result.removed_blocks, 0)
        self.assertFalse(result.changed)
        self.assertEqual(clean_article_footer(original), original)

    def test_rule_constants_match_observed_footer(self):
        self.assertEqual(KNOWN_PROMOTIONAL_FOOTER, OBSERVED_PARAGRAPH)
        self.assertEqual(EMPTY_FOOTER_HEADING, "Why it matters:")
        self.assertIsInstance(PREPROCESSING_VERSION, str)
        self.assertTrue(PREPROCESSING_VERSION.strip())

    def test_removes_exact_tail_block_and_preceding_newline(self):
        original = "Bitcoin article body." + "\n" + footer()
        result = clean_article_footer_with_audit(original)
        self.assertEqual(result.text, "Bitcoin article body.")
        self.assertEqual(result.removed_text, "\n" + footer())
        self.assertEqual(result.removed_blocks, 1)
        self.assertTrue(result.changed)
        self.assertEqual(clean_article_footer(original), result.text)

    def test_crlf_tail_and_preceding_crlf_are_supported(self):
        original = "First paragraph.\r\nSecond paragraph.\r\n" + footer("\r\n")
        result = clean_article_footer_with_audit(original)
        self.assertEqual(result.text, "First paragraph.\r\nSecond paragraph.")
        self.assertEqual(result.removed_text, "\r\n" + footer("\r\n"))
        self.assertEqual(result.text + result.removed_text, original)

    def test_footer_only_becomes_empty_text(self):
        for newline in ("\n", "\r\n"):
            with self.subTest(newline=repr(newline)):
                original = footer(newline)
                result = clean_article_footer_with_audit(original)
                self.assertEqual(result.text, "")
                self.assertEqual(result.removed_text, original)
                self.assertEqual(result.removed_blocks, 1)

    def test_optional_trailing_horizontal_whitespace_and_newlines(self):
        suffixes = (" ", "\t", " \t\n", "\n\n", "\r\n\t \r\n")
        for suffix in suffixes:
            with self.subTest(suffix=repr(suffix)):
                original = "Article." + "\n" + footer() + suffix
                result = clean_article_footer_with_audit(original)
                self.assertEqual(result.text, "Article.")
                self.assertEqual(result.text + result.removed_text, original)
                self.assertEqual(result.removed_blocks, 1)

    def test_prefix_whitespace_unicode_names_and_numbers_are_byte_identical(self):
        prefix = (
            "\t  Ethereum’s upgrade involves São Paulo and 東京.\r\n"
            "USDC: $4.25 million; BTC: 6.4 million; yield 5–7%.  \n\n"
        )
        original = prefix + "\n" + footer()
        result = clean_article_footer_with_audit(original)
        self.assertEqual(result.text.encode("utf-8"), prefix.encode("utf-8"))
        self.assertEqual(result.text + result.removed_text, original)

    def test_unmatched_text_is_not_generally_stripped(self):
        for original in ("", " ", "\t\r\n  ", "  Article body.\n\n", "\nBTC $131.  "):
            with self.subTest(original=repr(original)):
                self.assert_unchanged(original)

    def test_footer_paragraph_without_heading_is_preserved(self):
        self.assert_unchanged("Article.\n" + OBSERVED_PARAGRAPH)

    def test_heading_without_footer_paragraph_is_preserved(self):
        self.assert_unchanged("Article.\nWhy it matters:")

    def test_heading_with_substantive_explanation_is_preserved(self):
        self.assert_unchanged("Article.\n" + footer() + " Costs may decrease.")
        self.assert_unchanged("Article.\n" + footer() + "\nCosts may decrease.")

    def test_footer_followed_by_any_substantive_content_is_preserved(self):
        for content in ("More article text.", "End", "0", "."):
            with self.subTest(content=content):
                self.assert_unchanged("Article.\n" + footer() + "\n\n" + content)

    def test_modified_numbers_punctuation_or_case_do_not_match(self):
        variants = (
            OBSERVED_PARAGRAPH.replace("5-7%", "5-8%"),
            OBSERVED_PARAGRAPH.replace("$4B", "$5B"),
            OBSERVED_PARAGRAPH.replace("~4%", "4%"),
            OBSERVED_PARAGRAPH.replace("3 years.", "3 years!"),
            OBSERVED_PARAGRAPH.replace("Diversified", "diversified"),
            OBSERVED_PARAGRAPH.replace("off-chain", "off chain"),
        )
        for paragraph in variants:
            with self.subTest(paragraph=paragraph):
                self.assert_unchanged("Article.\n" + paragraph + "\nWhy it matters:")

    def test_modified_heading_does_not_match(self):
        for heading in ("why it matters:", "Why it matters", "Why it Matters:", " Why it matters:"):
            with self.subTest(heading=heading):
                self.assert_unchanged("Article.\n" + OBSERVED_PARAGRAPH + "\n" + heading)

    def test_quoted_or_indented_paragraph_does_not_match(self):
        for marker in ('"', "> ", " ", "\t", "- "):
            with self.subTest(marker=repr(marker)):
                self.assert_unchanged("Article.\n" + marker + footer())

    def test_paragraph_embedded_on_same_line_does_not_match(self):
        self.assert_unchanged("Article explains: " + footer())

    def test_heading_on_same_line_as_paragraph_does_not_match(self):
        self.assert_unchanged("Article.\n" + OBSERVED_PARAGRAPH + " Why it matters:")

    def test_extra_blank_line_between_paragraph_and_heading_does_not_match(self):
        self.assert_unchanged("Article.\n" + OBSERVED_PARAGRAPH + "\n\nWhy it matters:")

    def test_paragraph_trailing_space_does_not_match_exact_line_rule(self):
        self.assert_unchanged("Article.\n" + OBSERVED_PARAGRAPH + " \nWhy it matters:")

    def test_internal_identical_block_is_preserved_when_only_tail_is_removed(self):
        prefix = "Opening.\n" + footer() + "\nAdditional factual article content."
        original = prefix + "\n" + footer()
        result = clean_article_footer_with_audit(original)
        self.assertEqual(result.text, prefix)
        self.assertEqual(result.removed_blocks, 1)
        self.assertEqual(result.text + result.removed_text, original)

    def test_multiple_consecutive_tail_blocks_are_all_removed(self):
        for newline in ("\n", "\r\n"):
            with self.subTest(newline=repr(newline)):
                original = "Article." + newline + newline.join([footer(newline)] * 3)
                result = clean_article_footer_with_audit(original)
                self.assertEqual(result.text, "Article.")
                self.assertEqual(result.removed_blocks, 3)
                self.assertTrue(result.changed)
                self.assertEqual(result.text + result.removed_text, original)

    def test_multiple_footer_only_blocks_leave_empty_text(self):
        original = footer() + "\n" + footer()
        result = clean_article_footer_with_audit(original)
        self.assertEqual(result.text, "")
        self.assertEqual(result.removed_blocks, 2)
        self.assertEqual(result.removed_text, original)

    def test_cleanup_is_idempotent(self):
        original = "Article body." + "\n" + footer() + "\n" + footer() + "\n"
        once = clean_article_footer(original)
        self.assertEqual(clean_article_footer(once), once)
        self.assert_unchanged(once)

    def test_audit_result_is_dataclass_and_reconstructs_original(self):
        for original in ("", "Unchanged article.", footer(), "Text.\n" + footer()):
            with self.subTest(original=original):
                result = clean_article_footer_with_audit(original)
                self.assertTrue(is_dataclass(result))
                self.assertEqual(result.text + result.removed_text, original)
                self.assertEqual(result.changed, result.removed_blocks > 0)

    def test_non_string_values_raise_type_error(self):
        for invalid in (None, 7, 1.5, b"article", [], {}, True):
            for cleaner in (clean_article_footer, clean_article_footer_with_audit):
                with self.subTest(invalid=repr(invalid), cleaner=cleaner.__name__):
                    with self.assertRaises(TypeError):
                        cleaner(invalid)


if __name__ == "__main__":
    unittest.main()

"""Narrow, dependency-free removal of an observed trailing web footer.

This is NOT a general article extractor or a replacement for the scheduler's
trafilatura/pagination/duplicate-line preprocessing. Unmatched text and every
character before a matching suffix are preserved. Safe to import without
loading models, starting a scraper, or connecting to PostgreSQL.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


PREPROCESSING_VERSION = "coindesk_exact_trailing_footer_v1"
KNOWN_PROMOTIONAL_FOOTER = (
    "Diversified RWA stablecoins sustain 5-7% yield from real credit as crypto "
    "funding compresses to ~4%. GENIUS pushes yield off-chain; TAM grows to "
    "$4B in 3 years."
)
EMPTY_FOOTER_HEADING = "Why it matters:"

# Require the entire known paragraph on its own line and the immediately
# following empty heading at the absolute end. A standalone heading/paragraph,
# paraphrase, quotation, or heading with substantive content is not enough.
# LF/CRLF and terminal whitespace after the heading are supported formatting
# variants; only the LF/no-terminal-whitespace variant was initially observed.
_KNOWN_TRAILING_BLOCK = re.compile(
    r"(?:\r?\n|\A)"
    + re.escape(KNOWN_PROMOTIONAL_FOOTER)
    + r"\r?\n"
    + re.escape(EMPTY_FOOTER_HEADING)
    + r"[ \t]*(?:\r?\n[ \t]*)*\Z"
)


@dataclass(frozen=True, slots=True)
class FooterCleanupResult:
    """Exact retained prefix and removed suffix, suitable for an audit log."""

    text: str
    removed_text: str
    removed_blocks: int

    @property
    def changed(self) -> bool:
        return self.removed_blocks > 0


def clean_article_footer_with_audit(text: str) -> FooterCleanupResult:
    """Remove only consecutive exact known footer blocks at the end of text.

    No general whitespace normalization or ``strip`` is performed. If a suffix
    matches, its immediately preceding line separator belongs to the removed
    suffix; all preceding characters remain identical. Repeated applications
    are idempotent, including for consecutive duplicate footer blocks.
    """
    if not isinstance(text, str):
        raise TypeError("article text must be a string")

    cleaned = text
    removed_blocks = 0
    while (match := _KNOWN_TRAILING_BLOCK.search(cleaned)) is not None:
        cleaned = cleaned[:match.start()]
        removed_blocks += 1

    return FooterCleanupResult(
        text=cleaned,
        removed_text=text[len(cleaned):],
        removed_blocks=removed_blocks,
    )


def clean_article_footer(text: str) -> str:
    """Return cleaned text; use the audit variant to inspect removals."""
    return clean_article_footer_with_audit(text).text

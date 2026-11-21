"""Offline audit of saved RSS text and earlier captured HTTP response HTML.

No network requests, cookie changes, account access, or production writes.
Text-only flags are review candidates, never proof of a meter lock.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from lxml import html
import trafilatura

import rss_scrape_scheduler_pruned as scraper


ROOT = Path(__file__).resolve().parent
STATE_PATTERN = re.compile(r'\{[^{}]{0,300}"remaining":[^{}]{0,1000}\}')
BODY_CLASS = 'contains(concat(" ", normalize-space(@class), " "), " document-body ")'
WRAPPER_CLASS = 'contains(concat(" ", normalize-space(@class), " "), " article-content-wrapper ")'
LIVE_CLASS = 'contains(concat(" ", normalize-space(@class), " "), " live-news-article ")'
LIVE_BODY_CLASS = 'contains(concat(" ", normalize-space(@class), " "), " font-body-lg ")'


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def meter_states(tree: Any, url: str) -> list[dict[str, Any]]:
    """Decode captured Next payload strings as data, without executing scripts."""
    chunks: list[str] = []
    marker = "self.__next_f.push("
    for script in tree.xpath("//script"):
        text = script.text or ""
        cursor = 0
        while (position := text.find(marker, cursor)) >= 0:
            position += len(marker)
            try:
                value, consumed = json.JSONDecoder().raw_decode(text[position:])
            except ValueError:
                cursor = position
                continue
            cursor = position + consumed
            if isinstance(value, list) and len(value) > 1 and isinstance(value[1], str):
                chunks.append(value[1])
    path = urlsplit(url).path.rstrip("/")
    found: list[dict[str, Any]] = []
    for match in STATE_PATTERN.finditer("".join(chunks)):
        try:
            state = json.loads(match.group())
        except ValueError:
            continue
        if not {"remaining", "limit", "allowed", "metered", "public"} <= state.keys():
            continue
        if str(state.get("pathname", "")).rstrip("/") != path:
            continue
        if state not in found:
            found.append(state)
    return found


def is_locked(states: list[dict[str, Any]]) -> bool:
    return any(
        state.get("type") == "lock" and state.get("metered") is True
        and state.get("public") is False and state.get("allowed") is False
        for state in states
    )


def inspect_response(page: bytes, url: str) -> dict[str, Any]:
    tree = html.fromstring(page)
    states = meter_states(tree, url)
    narrative = tree.xpath(f"//main//*[{WRAPPER_CLASS}]/*[{BODY_CLASS}]")
    live = tree.xpath(f"//main//*[{LIVE_CLASS}]//article/div[{LIVE_BODY_CLASS}]")
    blocks = [node for node in narrative + live if node.text_content().strip()]
    prepared = scraper.prepare_pruned_html(page)
    options = dict(include_comments=False, include_tables=False, favor_precision=False)
    baseline = trafilatura.extract(deepcopy(prepared), **options) or ""
    pruned = trafilatura.extract(deepcopy(prepared), prune_xpath=scraper.PRUNE_XPATH,
                                 **options) or ""
    cleaned = scraper.clean_full_body(pruned)
    locked = is_locked(states)
    availability = (
        "meter_locked" if locked else
        "rendered_body_present" if blocks and cleaned else "unverified_or_missing_body"
    )
    return {
        "meter_states": states, "availability": availability,
        "regular_narrative_blocks": len(narrative), "live_update_blocks": len(live),
        "narrative_chars": sum(len(node.text_content().strip()) for node in blocks),
        "main_paragraphs": len(tree.xpath("//main//p")),
        "baseline_extracted_chars": len(baseline), "pruned_extracted_chars": len(pruned),
        "cleaned_chars": len(cleaned), "full_body": cleaned,
        "html_sha256": sha256(page),
    }


def text_flags(text: str) -> list[str]:
    """Conservative diagnostic flags; no automatic dataset exclusion or rewrite."""
    flags: list[str] = []
    if not text.strip():
        flags.append("empty_body")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) <= 6 and any(
        phrase in text.casefold()
        for phrase in ("share this article", "condividi questo articolo", "bu makaleyi paylaş")
    ):
        flags.append("header_and_share_controls_only_candidate")
    if text.startswith("Skip to main content\nNews\nLatest Crypto News"):
        flags.append("navigation_heavy_candidate")
    return flags


def run_audit(source: Path, captured_report: Path, output: Path) -> dict[str, Any]:
    source_bytes = source.read_bytes()
    articles = json.loads(source_bytes)
    captures = json.loads(captured_report.read_text(encoding="utf-8"))
    by_url = {item["url"]: item for item in captures}
    rows: list[dict[str, Any]] = []
    for index, article in enumerate(articles, 1):
        body = article.get("full_body") or ""
        row: dict[str, Any] = {
            "index": index, "url": article["url"], "title": article.get("title"),
            "scraped_at": article.get("scraped_at"),
            "saved_status": article.get("scrape_status"), "saved_chars": len(body),
            "text_flags": text_flags(body), "captured_response_available": False,
        }
        capture = by_url.get(article["url"])
        if capture:
            path = captured_report.parent / f"{capture['index']:02d}.html"
            evidence = inspect_response(path.read_bytes(), article["url"])
            row.update(captured_response_available=True,
                       captured_response_file=str(path.resolve()),
                       replay_body_matches_saved=evidence["full_body"] == body,
                       replay_evidence=evidence)
        rows.append(row)
    report = {
        "audited_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": str(source.resolve()), "source_sha256": sha256(source_bytes),
        "captured_report": str(captured_report.resolve()),
        "captured_report_sha256": sha256(captured_report.read_bytes()),
        "network_requests": 0, "cookie_changes": 0,
        "live_cookie_reset_test": "not_run_automatic_approval_review_rejected",
        "article_count": len(rows),
        "header_only_candidates": [r["index"] for r in rows if
                                   "header_and_share_controls_only_candidate" in r["text_flags"]],
        "navigation_candidates": [r["index"] for r in rows if
                                  "navigation_heavy_candidate" in r["text_flags"]],
        "articles": rows,
        "limitations": [
            "Captured HTML is from the earlier diagnostic replay, not the original RSS run.",
            "Text flags alone do not establish a lock or prove article completeness.",
            "No cookie reset method or reset interval has been verified.",
        ],
    }
    output.mkdir(parents=True, exist_ok=False)
    (output / "source_snapshot.json").write_bytes(source_bytes)
    report["source_unchanged"] = source.read_bytes() == source_bytes
    (output / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False)
                                        + "\n", encoding="utf-8")
    lines = ["# Offline RSS body availability audit", "",
             "The live session/cookie-reset test was rejected by automatic approval review "
             "and was not run. This report makes zero network requests and changes no cookies. "
             "It re-examines previously captured responses and the current saved dataset.", "",
             f"Articles: {len(rows)}. Header-only candidates: {report['header_only_candidates']}. "
             f"Navigation-heavy candidates: {report['navigation_candidates']}.", "",
             "| Article | Saved status | Characters | Text flags | Replay evidence |",
             "|---:|---|---:|---|---|"]
    for row in rows:
        evidence = row.get("replay_evidence", {})
        lines.append(f"| {row['index']} | {row['saved_status']} | {row['saved_chars']} | "
                     f"{', '.join(row['text_flags'])} | "
                     f"{evidence.get('availability', 'No raw response available')} |")
    lines.extend(["", *[f"- {item}" for item in report["limitations"]], "",
                  f"Source unchanged: {report['source_unchanged']}", ""])
    (output / "README.md").write_text("\n".join(lines), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path,
                        default=ROOT / "output/rss_pruned/scraped_news.json")
    parser.add_argument("--captured-report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    output = args.output_dir or ROOT / "output/rss_meter_audit" / f"run_{stamp}_utc"
    report = run_audit(args.source, args.captured_report, output)
    print(json.dumps({"output_dir": str(output), "articles": report["article_count"],
                      "header_only_candidates": report["header_only_candidates"],
                      "navigation_candidates": report["navigation_candidates"],
                      "source_unchanged": report["source_unchanged"]}, indent=2))


if __name__ == "__main__":
    main()

"""Separate, fail-closed CoinDesk article-body extraction experiment.

Uses saved URLs, never polls RSS, and never imports NLP/database modules.
Run ``python test_article_body_scraper.py --help`` for examples/options.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from lxml import etree, html
import requests
import trafilatura

from pipeline_experiment_data import atomic_write_json
from rss_scrape_scheduler import BROWSER_HEADERS, DELAY_BETWEEN_REQUESTS, clean_full_body


ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = ROOT / "output/rss_dataset_recovered/qualified_news.json"
VERSION = "coindesk_scoped_narrative_v1"
FIELDS = (
    "source", "guid", "title", "rss_summary", "url", "image_url",
    "published_at", "categories", "rss_fetched_at", "scraped_at",
    "full_body", "scrape_status", "scrape_error",
)
CLASS_BODY = 'contains(concat(" ", normalize-space(@class), " "), " document-body ")'
CLASS_WRAPPER = 'contains(concat(" ", normalize-space(@class), " "), " article-content-wrapper ")'
BODY_XPATH = f".//*[{CLASS_WRAPPER}]/*[{CLASS_BODY}]"
BOTTOM_XPATH = './/*[@data-module-name="article-bottom-news"]'


class ExtractionError(RuntimeError):
    """Expected article content could not be identified with confidence."""

    def __init__(self, message: str, audit: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.audit = audit or {}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalized(text: str) -> str:
    return " ".join(text.split())


def valid_url(url: Any, *, coindesk_only: bool = False) -> bool:
    if not isinstance(url, str):
        return False
    parts = urlsplit(url)
    return bool(
        parts.scheme in {"http", "https"} and parts.hostname
        and not parts.username and not parts.password
        and (not coindesk_only or parts.hostname.lower() in {"www.coindesk.com", "coindesk.com"})
    )


def html_filename(index: int, url: str) -> str:
    return f"{index:03d}_{digest(url.encode())[:16]}.html"


def meta_values(tree: Any, name: str) -> list[str]:
    return [
        value.strip() for value in tree.xpath(
            '//meta[@property=$name or @name=$name]/@content', name=name,
        ) if value.strip()
    ]


def news_metadata(tree: Any, article: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Use only article-level JSON-LD, without treating related items as the story."""
    objects: list[dict[str, Any]] = []
    warnings: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            kinds = value.get("@type", [])
            if isinstance(kinds, str):
                kinds = [kinds]
            if not isinstance(kinds, list):
                kinds = []
            if any(kind in {"NewsArticle", "Article", "ReportageNewsArticle"} for kind in kinds):
                objects.append(value)
            if "@graph" in value:
                visit(value["@graph"])

    for script in tree.xpath('//script[@type="application/ld+json"]'):
        try:
            visit(json.loads(script.text or ""))
        except (TypeError, ValueError):
            warnings.append("malformed_json_ld")
    guid = article.get("guid")
    matching = [obj for obj in objects if guid and obj.get("identifier") == guid]
    if len(matching) == 1:
        return matching[0], warnings
    if len(objects) == 1:
        identifier = objects[0].get("identifier")
        if guid and isinstance(identifier, str) and identifier != guid:
            raise ExtractionError("Webpage article identifier differs from the saved RSS GUID")
        return objects[0], warnings
    if objects:
        warnings.append("ambiguous_article_json_ld_metadata_not_used")
    # If GUID validation was unavailable, check any canonical page identity.
    canonical = tree.xpath('//link[@rel="canonical"]/@href')
    if canonical:
        saved = urlsplit(article.get("url") or "")
        page = urlsplit(canonical[0])
        if saved.path.rstrip("/") != page.path.rstrip("/"):
            raise ExtractionError("Webpage canonical URL differs from the saved article URL")
    warnings.append("page_guid_not_verified")
    return {}, warnings


def publication_date(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            stamp = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None
    if stamp.tzinfo is None:
        return None
    return format_datetime(stamp.astimezone(timezone.utc), usegmt=True)


def extract_page(page_html: bytes | str, article: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Extract fresh title/body and available metadata; never use old title/body."""
    try:
        tree = html.fromstring(page_html)
    except (etree.ParserError, ValueError) as exc:
        raise ExtractionError(f"Unreadable HTML: {exc}") from exc
    mains = tree.xpath("//main")
    if len(mains) != 1:
        raise ExtractionError(f"Expected one main content region, found {len(mains)}")
    main = mains[0]
    headings = main.xpath(".//h1[not(ancestor::*[@data-module-name='article-bottom-news'])]")
    if len(headings) != 1 or not normalized(headings[0].text_content()):
        raise ExtractionError(f"Expected one nonempty article H1, found {len(headings)}")
    title = normalized(headings[0].text_content())
    metadata, warnings = news_metadata(tree, article)
    headline = metadata.get("headline")
    if isinstance(headline, str) and normalized(headline) != title:
        warnings.append("page_h1_differs_from_json_ld_headline")

    removed: list[dict[str, Any]] = []
    # Exclude identified bottom modules before selecting any body candidates.
    bottom_nodes = main.xpath(BOTTOM_XPATH)
    for node in bottom_nodes:
        removed.append({"reason": "article_bottom_news", "text": node.text_content()})
        node.drop_tree()
    candidates = main.xpath(f".//*[{CLASS_BODY}]")
    selected = main.xpath(BODY_XPATH)
    selected = [
        node for node in selected if not any(
            ancestor.tag in {"aside", "nav", "footer"}
            or (ancestor.get("id") or "").startswith("se-")
            for ancestor in node.iterancestors()
        )
    ]
    # Direct children distinguish narrative from the nested summary widget.
    for node in candidates:
        if node not in selected:
            removed.append({
                "reason": "non_narrative_document_body",
                "path": tree.getroottree().getpath(node), "text": node.text_content(),
            })
    if not selected:
        live_blog = bool(main.xpath('.//*[contains(concat(" ", normalize-space(@class), " "), " live-news-article ")]'))
        reason = "live_blog_layout_not_supported" if live_blog else "narrative_body_absent_from_expected_containers"
        raise ExtractionError(
            f"No verified narrative document-body blocks ({reason}); whole-page fallback disabled",
            {"page_title": title, "document_body_candidates_in_main": len(candidates),
             "selected_body_blocks": 0, "excluded_bottom_modules": len(bottom_nodes),
             "excluded_regions": removed, "warnings": [reason] + warnings},
        )

    shell = html.fromstring("<html><body><article></article></body></html>")
    target = shell.xpath("//article")[0]
    for node in selected:
        copied = deepcopy(node)
        for excluded in copied.xpath(".//script | .//style | .//noscript | .//nav | .//aside | .//footer"):
            removed.append({"reason": "nonarticle_element_inside_body", "text": excluded.text_content()})
            excluded.drop_tree()
        target.append(copied)
    selected_html = html.tostring(shell, encoding="unicode")
    extracted = trafilatura.extract(
        selected_html, include_comments=False, include_tables=False,
    ) or ""
    if not extracted.strip():
        raise ExtractionError("Trafilatura returned no text from the selected article blocks")
    body = clean_full_body(extracted)
    if not body:
        raise ExtractionError("Existing text cleanup produced an empty article body")

    # Audit content loss; do not silently label structural extraction as a quality verdict.
    segments: list[str] = []
    for node in target.xpath(".//p | .//li | .//h2 | .//h3 | .//h4 | .//h5 | .//h6"):
        if node.xpath("ancestor::table") or len(node):
            # Inline spans/links are valid; skip only elements containing other block segments.
            if node.xpath("ancestor::table") or node.xpath(".//p | .//li"):
                continue
        text = normalized(node.text_content())
        if text:
            segments.append(text)
    absent = [text for text in segments if text not in normalized(body)]
    if absent:
        warnings.append("selected_source_segments_not_found_verbatim_after_extraction_or_cleanup")
    if body != extracted.strip():
        warnings.append("existing_pagination_or_duplicate_line_cleanup_changed_text")
    origins: dict[str, str] = {"title": "page:main_h1", "full_body": "page:scoped_narrative_blocks"}
    fresh: dict[str, Any] = {"title": title, "full_body": body}

    image_candidates = meta_values(tree, "og:image") + meta_values(tree, "parsely-image-url")
    image = metadata.get("image")
    if isinstance(image, dict):
        image_candidates.append(image.get("url"))
    elif isinstance(image, str):
        image_candidates.append(image)
    fresh["image_url"] = next((v for v in image_candidates if valid_url(v)), None)
    origins["image_url"] = "page:article_image_metadata"
    if fresh["image_url"] is None:
        fresh["image_url"] = article.get("image_url") if valid_url(article.get("image_url")) else None
        origins["image_url"] = "saved_rss_fallback" if fresh["image_url"] else "unavailable"

    dates = [metadata.get("datePublished")] + meta_values(tree, "article:published_time") + meta_values(tree, "parsely-pub-date")
    fresh["published_at"] = next((v for raw in dates if (v := publication_date(raw))), None)
    origins["published_at"] = "page:publication_metadata"
    if fresh["published_at"] is None:
        fresh["published_at"] = article.get("published_at") or ""
        origins["published_at"] = "saved_rss_fallback" if fresh["published_at"] else "unavailable"

    categories: list[str] = []
    section = metadata.get("articleSection")
    sections = section if isinstance(section, list) else [section]
    sections += meta_values(tree, "parsely-section")
    keywords = metadata.get("keywords", [])
    if isinstance(keywords, str):
        keywords = keywords.split(",")
    if not isinstance(keywords, list):
        keywords = []
    tags = [tag for value in meta_values(tree, "parsely-tags") for tag in value.split(",")]
    for value in sections + keywords + tags:
        if isinstance(value, str) and value.strip() and value.strip().casefold() not in {v.casefold() for v in categories}:
            categories.append(value.strip())
    fresh["categories"] = categories or deepcopy(article.get("categories") or [])
    origins["categories"] = "page:article_section_and_tags" if categories else "saved_rss_fallback"
    audit = {
        "version": VERSION, "title_xpath": "//main//h1", "body_xpath": "//main/" + BODY_XPATH[2:],
        "document_body_candidates_in_main": len(candidates), "selected_body_blocks": len(selected),
        "excluded_bottom_modules": len(bottom_nodes), "excluded_regions": removed,
        "selected_html": selected_html, "selected_source_segments": segments,
        "source_segments_not_found_verbatim": absent,
        "text_before_existing_cleanup": extracted,
        "metadata_origins": origins, "warnings": sorted(set(warnings)),
        "selected_body_paths": [tree.getroottree().getpath(node) for node in selected],
    }
    return fresh, audit


def base_record(article: dict[str, Any]) -> dict[str, Any]:
    """Exactly the existing scraper schema; failure never reuses old title/body."""
    return {
        "source": article.get("source") or "CoinDesk", "guid": article.get("guid") or "",
        "title": "", "rss_summary": article.get("rss_summary") or "", "url": article.get("url") or "",
        "image_url": article.get("image_url"), "published_at": article.get("published_at") or "",
        "categories": deepcopy(article.get("categories") or []),
        "rss_fetched_at": article.get("rss_fetched_at") or "", "scraped_at": now(),
        "full_body": None, "scrape_status": "failed", "scrape_error": None,
    }


def write_report(folder: Path, report: dict[str, Any], comparisons: list[dict[str, Any]]) -> None:
    lines = [
        "# CoinDesk article-body extraction experiment", "",
        f"Status: **{report['status']}**. Source articles: {report['source_count']}; "
        f"selected: {report['selected_count']}; attempted: {report['attempted']}; "
        f"success: {report['success']}; failed: {report['failed']}.", "",
        "`scraped_news.json` has exactly the existing 13-field scraper schema. "
        "Source dataset IDs and extraction audits are in `comparison.json` only.", "",
        "The title is freshly extracted from main H1. Body text comes only from direct "
        "document-body children of article-content-wrapper under main, excluding bottom-news "
        "modules and nested summary widgets. No old-title/body or whole-page fallback.", "",
        "Metadata origins/fallbacks are recorded per field. RSS summary/fetch time and GUID "
        "retain their original meaning. Dates from the page are formatted as RFC 2822 GMT.", "",
        "Structural success is not a human quality verdict. Review missing source segments, "
        "newsletter introductions inside narrative, and genuine article lists. Original and "
        "new text may differ because the publisher edited the page after collection.", "",
        "No filtering, novelty detection, NLP inference, reference editing, or database writes "
        "were performed. Previous eligibility flags were not transferred to the new output.", "",
        "| Source # | Fresh title / failure | Status | Blocks | Review flags |", "|---|---|---|---:|---|",
    ]
    for row in comparisons:
        title = row["new_title"] or row["error"] or "Missing title"
        title = title.replace("|", "\\|").replace("\n", " ")
        flags = ", ".join(row.get("audit", {}).get("warnings", [])) or "—"
        lines.append(f"| {row['source_index']} | {title} | {row['status']} | "
                     f"{row.get('audit', {}).get('selected_body_blocks', 0)} | {flags} |")
    lines += ["", "Full before/after text and excluded regions: `comparison.json`. "
              "Downloaded pages and selected HTML fragments: `html/`. "
              "Failure rows remain in the output; do not assume all records are ready for evaluation.", ""]
    (folder / "report.md").write_text("\n".join(lines), encoding="utf-8")


def run_scrape(
    source: Path, output_dir: Path, *, indices: list[int] | None = None,
    limit: int | None = None, delay: float = DELAY_BETWEEN_REQUESTS,
    timeout: float = 30.0, html_dir: Path | None = None,
    session: Any = None,
) -> dict[str, Any]:
    """Checkpoint every attempt into a NEW folder; optional exact-URL HTML replay."""
    if delay < 0 or timeout <= 0 or (limit is not None and limit < 1):
        raise ValueError("Delay must be nonnegative; timeout and limit must be positive")
    source_bytes = Path(source).read_bytes()
    articles = json.loads(source_bytes)
    if not isinstance(articles, list) or not articles or not all(isinstance(v, dict) for v in articles):
        raise ValueError("Source must be a nonempty JSON list of article objects")
    chosen = list(range(1, len(articles) + 1)) if indices is None else list(indices)
    if len(chosen) != len(set(chosen)) or not chosen or any(i < 1 or i > len(articles) for i in chosen):
        raise ValueError("Indices must be distinct 1-based positions in the source dataset")
    if limit is not None:
        chosen = chosen[:limit]
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "html").mkdir()
    (folder / "source_snapshot.json").write_bytes(source_bytes)
    schema = json.loads((ROOT / "output/scraped_news.json").read_text()) if (ROOT / "output/scraped_news.json").exists() else []
    if schema:
        if set(schema[0]) != set(FIELDS):
            raise ValueError("Existing scraped_news.json schema changed; inspect before running")
    report: dict[str, Any] = {
        "version": VERSION, "status": "running", "started_at": now(),
        "source_path": str(Path(source).resolve()), "source_sha256": digest(source_bytes),
        "source_count": len(articles), "selected_indices": chosen, "selected_count": len(chosen),
        "output_fields": list(FIELDS), "delay_seconds": delay, "timeout_seconds": timeout,
        "replay_html_dir": str(html_dir.resolve()) if html_dir else None,
        "trafilatura_version": trafilatura.__version__, "attempted": 0, "success": 0, "failed": 0,
        "downloaded": 0, "replayed": 0,
        "script_sha256": digest(Path(__file__).read_bytes()),
    }
    results: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []

    def checkpoint() -> None:
        report.update(attempted=len(results), success=sum(r["scrape_status"] == "success" for r in results),
                      failed=sum(r["scrape_status"] != "success" for r in results))
        report["warning_counts"] = dict(Counter(
            warning for row in comparisons for warning in row.get("audit", {}).get("warnings", [])
        ))
        atomic_write_json(folder / "scraped_news.json", results, indent=2)
        atomic_write_json(folder / "comparison.json", comparisons, indent=2)
        atomic_write_json(folder / "report.json", report, indent=2)
        write_report(folder, report, comparisons)

    client = session or requests.Session()
    client.headers.update(BROWSER_HEADERS)
    checkpoint()
    last_request: float | None = None
    try:
        for index in chosen:
            article = articles[index - 1]
            row = base_record(article)
            audit: dict[str, Any] = {}
            transport: dict[str, Any] = {}
            filename = html_filename(index, str(row["url"]))
            try:
                if not valid_url(row["url"], coindesk_only=True):
                    raise ExtractionError("Expected a public CoinDesk article URL")
                cached = Path(html_dir) / filename if html_dir else None
                if cached and cached.exists():
                    payload = cached.read_bytes()
                    transport = {"origin": "saved_html_replay", "path": str(cached.resolve())}
                    report["replayed"] += 1
                else:
                    if last_request is not None:
                        remaining = delay - (time.monotonic() - last_request)
                        if remaining > 0:
                            time.sleep(remaining)
                    last_request = time.monotonic()
                    response = client.get(row["url"], timeout=timeout)
                    report["downloaded"] += 1
                    payload = response.content
                    # Preserve even HTTP error/challenge responses for diagnosis.
                    (folder / "html" / filename).write_bytes(payload)
                    transport = {"origin": "fresh_http", "http_status": response.status_code,
                                 "final_url": response.url, "downloaded_at": now()}
                    response.raise_for_status()
                    if not valid_url(response.url, coindesk_only=True):
                        raise ExtractionError("Redirect destination is not CoinDesk")
                    content_type = response.headers.get("Content-Type", "")
                    if content_type and "html" not in content_type.lower():
                        raise ExtractionError(f"Expected HTML response, received {content_type}")
                (folder / "html" / filename).write_bytes(payload)
                transport["html_sha256"] = digest(payload)
                fields, audit = extract_page(payload, article)
                fragment = audit.pop("selected_html")
                (folder / "html" / filename.replace(".html", ".selected.html")).write_text(fragment, encoding="utf-8")
                row.update(fields, scrape_status="success", scrape_error=None)
            except (requests.RequestException, ExtractionError, etree.LxmlError, ValueError, TypeError) as exc:
                row["scrape_error"] = f"{type(exc).__name__}: {exc}"
                if isinstance(exc, ExtractionError):
                    audit = exc.audit
            comparisons.append({
                "source_index": index, "dataset_article_id": article.get("dataset_article_id"),
                "guid": row["guid"], "url": row["url"], "status": row["scrape_status"],
                "old_title": article.get("title"), "new_title": row["title"],
                "old_full_body": article.get("full_body"), "new_full_body": row["full_body"],
                "old_metadata": {k: article.get(k) for k in ("image_url", "published_at", "categories")},
                "new_metadata": {k: row[k] for k in ("image_url", "published_at", "categories")},
                "old_body_characters": len(article.get("full_body") or ""),
                "new_body_characters": len(row["full_body"] or ""),
                "error": row["scrape_error"], "transport": transport, "audit": audit,
            })
            results.append(row)
            checkpoint()
            print(f"[{len(results)}/{len(chosen)}] source #{index}: {row['scrape_status']} — "
                  f"{row['title'] or row['scrape_error']}", flush=True)
    except BaseException:
        report.update(status="interrupted", finished_at=now())
        checkpoint()
        raise
    finally:
        if session is None:
            client.close()
    report.update(status="complete", finished_at=now())
    checkpoint()
    print(f"Results: {folder.resolve()}\nSuccess {report['success']}; failed {report['failed']}", flush=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--indices", nargs="+", type=int, help="1-based source positions, e.g. 1 10 15 20 50 61")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--delay", type=float, default=DELAY_BETWEEN_REQUESTS)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--html-dir", type=Path, help="Replay saved HTML for matching source index/URL filenames; download cache misses")
    args = parser.parse_args()
    stamp = datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%Y%m%d_%H%M%S_%f")
    destination = args.output_dir or ROOT / "output/article_body_scrape_test" / f"run_{stamp}"
    try:
        report = run_scrape(args.source, destination, indices=args.indices, limit=args.limit,
                            delay=args.delay, timeout=args.timeout, html_dir=args.html_dir)
    except KeyboardInterrupt:
        print("Stopped; completed attempts are retained in the experiment folder.", file=sys.stderr)
        return 130
    except (OSError, ValueError) as exc:
        print(f"Scraping experiment stopped: {exc}", file=sys.stderr)
        return 1
    return 0 if report["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

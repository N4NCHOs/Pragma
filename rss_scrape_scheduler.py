"""Incremental CoinDesk RSS scraper for scheduled notebook/script runs.

Each run creates these files:
  * rss_temp.json: the latest 25 RSS records
  * rss_history.json: the previous successful run's RSS snapshot
  * scraped_news.json: only articles that were new in the current run
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import requests
import trafilatura


RSS_URL = "https://www.coindesk.com/arc/outboundfeeds/rss/"
RSS_LIMIT = 25
RSS_TEMP_FILE = Path("output/rss_temp.json")
RSS_HISTORY_FILE = Path("output/rss_history.json")
SCRAPED_NEWS_FILE = Path("output/scraped_news.json")
DELAY_BETWEEN_REQUESTS = 5.0

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

PAGINATION_RUN = re.compile(r"(?:\s*[-*\u2022]\s*\d+\b){2,}")
TRACKING_PARAMETERS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json_atomic(path: Path, data: list[dict[str, Any]]) -> None:
    """Replace a JSON file atomically, avoiding partially written files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def read_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read valid JSON from {path}: {exc}") from exc
    if not isinstance(data, list):
        raise RuntimeError(f"Expected a JSON list in {path}")
    return data


def normalize_url(url: str) -> str:
    """Normalize URLs so tracking parameters do not create false new items."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMETERS
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def article_keys(article: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    guid = str(article.get("guid") or "").strip()
    url = normalize_url(str(article.get("url") or ""))
    if guid:
        keys.add(f"guid:{guid}")
    if url:
        keys.add(f"url:{url}")
    return keys


def fetch_latest_rss(session: requests.Session, limit: int = RSS_LIMIT) -> list[dict[str, Any]]:
    response = session.get(RSS_URL, timeout=20)
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    if getattr(feed, "bozo", False) and not feed.entries:
        raise RuntimeError(f"RSS parsing failed: {feed.get('bozo_exception')}")

    fetched_at = utc_now()
    articles: list[dict[str, Any]] = []
    for entry in feed.entries[:limit]:
        url = entry.get("link", "").strip()
        guid = str(entry.get("id") or url).strip()
        if not guid and not url:
            continue
        articles.append(
            {
                "source": "CoinDesk",
                "guid": guid,
                "title": entry.get("title", "").strip(),
                "rss_summary": entry.get("summary", "").strip(),
                "url": url,
                "published_at": entry.get("published", ""),
                "categories": [tag.get("term", "") for tag in entry.get("tags", [])],
                "rss_fetched_at": fetched_at,
            }
        )
    if not articles:
        raise RuntimeError("The RSS request succeeded but returned no usable articles")
    return articles


def find_new_articles(
    current_articles: list[dict[str, Any]], history: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    historical_keys = set().union(*(article_keys(item) for item in history)) if history else set()
    return [item for item in current_articles if article_keys(item).isdisjoint(historical_keys)]


def clean_full_body(text: str) -> str:
    if not text:
        return text
    match = PAGINATION_RUN.search(text)
    if match:
        text = text[: match.start()]

    unique_lines: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        key = line.strip()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        unique_lines.append(line)
    return "\n".join(unique_lines).strip()


def scrape_article(session: requests.Session, article: dict[str, Any]) -> dict[str, Any]:
    result = dict(article)
    result["scraped_at"] = utc_now()
    try:
        response = session.get(article["url"], timeout=30)
        response.raise_for_status()
        extracted = trafilatura.extract(
            response.text, include_comments=False, include_tables=False
        )
        full_body = clean_full_body(extracted or "")
        if not full_body:
            raise RuntimeError("no main article content was extracted")
        result.update(full_body=full_body, scrape_status="success", scrape_error=None)
    except (requests.RequestException, RuntimeError, KeyError) as exc:
        result.update(full_body=None, scrape_status="failed", scrape_error=str(exc))
    return result


def run_scheduler(delay: float = DELAY_BETWEEN_REQUESTS) -> dict[str, int]:
    """Run one incremental batch. Suitable for cron/APScheduler invocation."""
    # The batch output represents this run only, as requested.
    write_json_atomic(SCRAPED_NEWS_FILE, [])

    with requests.Session() as session:
        session.headers.update(BROWSER_HEADERS)
        current_articles = fetch_latest_rss(session)
        write_json_atomic(RSS_TEMP_FILE, current_articles)

        history = read_json_list(RSS_HISTORY_FILE)
        new_articles = find_new_articles(current_articles, history)

        scraped: list[dict[str, Any]] = []
        for index, article in enumerate(new_articles, start=1):
            print(f"[{index}/{len(new_articles)}] {article['title']}")
            scraped.append(scrape_article(session, article))
            # Checkpoint after every article so a stopped run keeps completed work.
            write_json_atomic(SCRAPED_NEWS_FILE, scraped)
            if delay and index < len(new_articles):
                time.sleep(delay)

    # Advance history only after the entire scrape loop completes.
    write_json_atomic(RSS_HISTORY_FILE, current_articles)
    return {
        "rss_items": len(current_articles),
        "new_items": len(new_articles),
        "scrape_success": sum(item["scrape_status"] == "success" for item in scraped),
        "scrape_failed": sum(item["scrape_status"] == "failed" for item in scraped),
    }


if __name__ == "__main__":
    print(json.dumps(run_scheduler(), indent=2))

"""Copy of the CoinDesk RSS scraper with the tested HTML pruning rules.

Output: output/rss_pruned/{rss_temp,rss_history,scraped_news}.json.
Direct execution mirrors the original script's startup reset, in this folder
only. Imported run_scheduler() processes one incremental batch without resetting
history. No model/database imports or changes to HTTP/session behavior.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
from lxml import etree, html
import requests
import trafilatura


RSS_URL = "https://www.coindesk.com/arc/outboundfeeds/rss/"
RSS_LIMIT = 100
OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "rss_pruned"
RSS_TEMP_FILE = OUTPUT_DIR / "rss_temp.json"
RSS_HISTORY_FILE = OUTPUT_DIR / "rss_history.json"
SCRAPED_NEWS_FILE = OUTPUT_DIR / "scraped_news.json"
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
FOOTER_XPATH = '//footer[@data-module-name="footer"]'
BOTTOM_XPATH = '//*[@data-module-name="article-bottom-news"]'
TRENDING_ATTRIBUTE = "data-pragma-prune-trending"
PRUNE_XPATH = " | ".join([
    FOOTER_XPATH, BOTTOM_XPATH, f'//*[@{TRENDING_ATTRIBUTE}="true"]',
])
LOGGER = logging.getLogger(__name__)


def main() -> None:
    """Mirror the original direct-run reset, restricted to this copy's files."""
    for path in (RSS_TEMP_FILE, RSS_HISTORY_FILE, SCRAPED_NEWS_FILE):
        write_json_atomic(path, [])
        print(f"Reset {path}")


def prepare_pruned_html(page_html: bytes | str) -> Any:
    """Mark an exact bounded trending section for Trafilatura's prune_xpath.

    Footer and recommendation containers are matched directly by PRUNE_XPATH.
    No new rules target Read more, subscriptions, publisher summaries, headers,
    price chips, or unrelated lists. Ambiguous section boundaries are retained.
    """
    tree = html.fromstring(page_html)
    if tree.xpath(f'//*[@{TRENDING_ATTRIBUTE}]'):
        raise ValueError("Input already uses the private HTML pruning attribute")
    body_class = 'contains(concat(" ", normalize-space(@class), " "), " document-body ")'
    headings = tree.xpath(
        f'//main//*[{body_class}]//*[self::h2 or self::h3 or self::h4 or self::h5 or self::h6]'
    )

    def level(node: Any) -> int | None:
        return int(node.tag[1]) if isinstance(node.tag, str) and node.tag in {
            "h1", "h2", "h3", "h4", "h5", "h6",
        } else None

    for heading in headings:
        label = " ".join(heading.text_content().split()).casefold().replace("’", "'")
        if label != "what's trending":
            continue
        rank = level(heading)
        section = [heading]
        ambiguous = False
        for sibling in heading.itersiblings():
            if not isinstance(sibling.tag, str):
                continue
            sibling_rank = level(sibling)
            if sibling_rank is not None and sibling_rank <= rank:
                break
            if any((level(child) or 99) <= rank for child in sibling.iterdescendants()):
                ambiguous = True
                break
            section.append(sibling)
        if ambiguous or any((node.tail or "").strip() for node in section):
            LOGGER.warning("Ambiguous What's trending boundary; section retained for review")
            continue
        for node in section:
            node.set(TRENDING_ATTRIBUTE, "true")
    return tree


def extract_rss_image_url(entry: dict[str, Any]) -> str | None:
    """Return the first valid image URL provided by the RSS entry."""
    for media_item in entry.get("media_content", []):
        image_url = str(media_item.get("url") or "").strip()
        parsed_url = urlsplit(image_url)
        if parsed_url.scheme in {"http", "https"} and parsed_url.netloc:
            return image_url
    return None


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
        image_url = extract_rss_image_url(entry)
        if not guid and not url:
            continue
        articles.append({
            "source": "CoinDesk", "guid": guid,
            "title": entry.get("title", "").strip(),
            "rss_summary": entry.get("summary", "").strip(),
            "url": url, "image_url": image_url,
            "published_at": entry.get("published", ""),
            "categories": [tag.get("term", "") for tag in entry.get("tags", [])],
            "rss_fetched_at": fetched_at,
        })
    if not articles:
        raise RuntimeError("The RSS request succeeded but returned no usable articles")
    return articles


def find_new_articles(
    current_articles: list[dict[str, Any]], history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    historical_keys = set().union(*(article_keys(item) for item in history)) if history else set()
    return [item for item in current_articles if article_keys(item).isdisjoint(historical_keys)]


def clean_full_body(text: str) -> str:
    if not text:
        return text
    match = PAGINATION_RUN.search(text)
    if match:
        text = text[:match.start()]
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
        prepared = prepare_pruned_html(response.content)
        extracted = trafilatura.extract(
            prepared, include_comments=False, include_tables=False,
            favor_precision=False, prune_xpath=PRUNE_XPATH,
        )
        full_body = clean_full_body(extracted or "")
        if not full_body:
            raise RuntimeError("no main article content was extracted")
        result.update(full_body=full_body, scrape_status="success", scrape_error=None)
    except (requests.RequestException, RuntimeError, KeyError, ValueError, etree.LxmlError) as exc:
        result.update(full_body=None, scrape_status="failed", scrape_error=str(exc))
    return result


def run_scheduler(delay: float = DELAY_BETWEEN_REQUESTS) -> dict[str, int]:
    """Run one incremental batch. Suitable for cron/APScheduler invocation."""
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
            write_json_atomic(SCRAPED_NEWS_FILE, scraped)
            if delay and index < len(new_articles):
                time.sleep(delay)
    write_json_atomic(RSS_HISTORY_FILE, current_articles)
    return {
        "rss_items": len(current_articles), "new_items": len(new_articles),
        "scrape_success": sum(item["scrape_status"] == "success" for item in scraped),
        "scrape_failed": sum(item["scrape_status"] == "failed" for item in scraped),
    }


if __name__ == "__main__":
    main()
    print(json.dumps(run_scheduler(), indent=2))

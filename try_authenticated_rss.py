"""Try one RSS-discovered article using a user-provided authenticated cookie file.

This diagnostic never reads browser cookie stores, signs into an account, resets
cookies, or changes the scheduler. It preserves the scraper's RSS metadata,
approved extraction/pruning rules, and 13-field article representation.
"""

from __future__ import annotations

import argparse
from contextlib import redirect_stderr
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from http.cookiejar import LoadError, MozillaCookieJar
from io import StringIO
import json
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit
import warnings

import requests

from audit_rss_body_availability import inspect_response, is_locked
import rss_scrape_scheduler_pruned as scraper


ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = ROOT / "output/rss_pruned/scraped_news.json"
DEFAULT_URL = (
    "https://www.coindesk.com/markets/2026/10/30/"
    "wall-street-analysts-urge-investors-to-buy-crypto-stocks-on-weakness-"
    "after-usd6-3-billion-binance-hack"
)
RSS_FIELDS = (
    "source", "guid", "title", "rss_summary", "url", "image_url",
    "published_at", "categories", "rss_fetched_at",
)
STATE_FIELDS = (
    "limit", "remaining", "allowed", "public", "metered", "authorized",
    "premium", "type", "pathname",
)
EVIDENCE_FIELDS = (
    "availability", "regular_narrative_blocks", "live_update_blocks",
    "narrative_chars", "main_paragraphs", "baseline_extracted_chars",
    "pruned_extracted_chars", "cleaned_chars", "html_sha256",
)


class AuthenticatedTrialError(RuntimeError):
    """An input/setup problem whose message contains no credential contents."""


@dataclass
class LoadedCookies:
    cookies: MozillaCookieJar = field(repr=False)
    accepted_count: int
    ignored_count: int


def validate_article_url(url: str) -> str:
    """Accept only HTTPS article URLs on the two supported CoinDesk hosts."""
    try:
        parts = urlsplit(url)
        valid = (
            isinstance(url, str) and url == url.strip()
            and not any(ord(char) < 32 for char in url)
            and parts.scheme == "https"
            and parts.hostname in {"coindesk.com", "www.coindesk.com"}
            and parts.port in {None, 443}
            and parts.username is None and parts.password is None
            and bool(parts.path.strip("/")) and not parts.fragment
        )
    except (TypeError, ValueError, AttributeError):
        valid = False
    if not valid:
        raise AuthenticatedTrialError(
            "The article must be an HTTPS URL on coindesk.com or www.coindesk.com "
            "without credentials, a fragment, or a nonstandard port."
        )
    return url


def load_cookie_file(path: Path) -> LoadedCookies:
    """Load supplied Netscape cookies; discard foreign domains and real expiry.

    Netscape/curl exports commonly use expiry 0 for session cookies. Those are
    normalized to session cookies before checking expiry; actual expired dated
    cookies are rejected. No cookie value or parser diagnostic is displayed.
    """
    loaded = MozillaCookieJar(str(path))
    try:
        # CookieJar's malformed-file warnings can include a raw credential line.
        with warnings.catch_warnings(), redirect_stderr(StringIO()):
            warnings.simplefilter("ignore")
            loaded.load(ignore_discard=True, ignore_expires=True)
    except (OSError, LoadError, ValueError, UnicodeError):
        raise AuthenticatedTrialError(
            "Cannot load the cookie file. Supply a readable, valid Netscape-format "
            "file containing your authorized CoinDesk session cookies."
        ) from None

    accepted = MozillaCookieJar()
    ignored = 0
    for cookie in loaded:
        domain = cookie.domain.lstrip(".").lower()
        if cookie.expires == 0:
            cookie.expires = None
            cookie.discard = True
        if not (domain == "coindesk.com" or domain.endswith(".coindesk.com")):
            ignored += 1
            continue
        if cookie.is_expired():
            ignored += 1
            continue
        accepted.set_cookie(cookie)
    if not len(accepted):
        raise AuthenticatedTrialError(
            "The cookie file contains no unexpired CoinDesk cookies. "
            "Supply cookies from your currently authorized session."
        )
    return LoadedCookies(accepted, len(accepted), ignored)


def evaluate_response(page: bytes, url: str) -> dict[str, Any]:
    """Require account authorization and genuine narrative, not just HTTP 200."""
    validate_article_url(url)
    inspected = inspect_response(page, url)
    states = inspected["meter_states"]
    evidence = {key: inspected[key] for key in EVIDENCE_FIELDS if key in inspected}
    evidence["meter_states"] = [
        {key: state[key] for key in STATE_FIELDS if key in state}
        for state in states
    ]
    state = states[0] if len(states) == 1 else {}
    authenticated = state.get("authorized") is True
    body_available = bool(
        inspected.get("regular_narrative_blocks", 0)
        + inspected.get("live_update_blocks", 0)
    ) and inspected.get("narrative_chars", 0) > 0 and bool(
        (inspected.get("full_body") or "").strip()
    )
    if len(states) != 1:
        outcome = "authentication_unverified"
    elif is_locked(states):
        outcome = "meter_locked"
    elif not authenticated:
        outcome = "authentication_unverified"
    elif not body_available:
        outcome = "authenticated_but_body_missing"
    else:
        outcome = "authenticated_body_extracted"
    return {
        "outcome": outcome,
        "authenticated": authenticated,
        "body_available": body_available,
        "full_body": inspected["full_body"]
        if outcome == "authenticated_body_extracted" else None,
        "evidence": evidence,
    }


def _source_article(source: Path, url: str) -> tuple[bytes, dict[str, Any]]:
    try:
        source_bytes = source.read_bytes()
        articles = json.loads(source_bytes)
    except (OSError, ValueError, UnicodeError):
        raise AuthenticatedTrialError(
            "Cannot read the source article JSON. Supply a readable JSON list."
        ) from None
    if not isinstance(articles, list):
        raise AuthenticatedTrialError("The source JSON must contain a list of articles.")
    matches = [item for item in articles if isinstance(item, dict) and item.get("url") == url]
    if len(matches) != 1:
        raise AuthenticatedTrialError(
            "The source must contain exactly one article matching the requested URL."
        )
    missing = [key for key in RSS_FIELDS if key not in matches[0]]
    if missing:
        raise AuthenticatedTrialError(
            "The matching article is missing required RSS metadata fields: "
            + ", ".join(missing)
        )
    return source_bytes, matches[0]


def run_trial(
    *, source: Path, cookie_file: Path, url: str = DEFAULT_URL,
    output_dir: Path | None = None,
    session_factory: Callable[[], requests.Session] = requests.Session,
) -> dict[str, Any]:
    """Make one article request and write isolated, credential-free diagnostics."""
    validate_article_url(url)
    source_bytes, article = _source_article(source, url)
    loaded = load_cookie_file(cookie_file)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    destination = output_dir or ROOT / "output/rss_authenticated_test" / f"run_{stamp}_utc"
    try:
        destination.mkdir(parents=True, exist_ok=False)
    except OSError:
        raise AuthenticatedTrialError(
            "Cannot create the output folder. Choose a new, writable folder; "
            "existing results will not be overwritten."
        ) from None

    record = {key: article[key] for key in RSS_FIELDS}
    record.update(
        scraped_at=datetime.now(timezone.utc).isoformat(),
        full_body=None, scrape_status="failed", scrape_error=None,
    )
    report: dict[str, Any] = {
        "started_at_utc": record["scraped_at"],
        "article_url": url,
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "accepted_cookie_count": loaded.accepted_count,
        "ignored_cookie_count": loaded.ignored_count,
        "cookie_reset_count": 0,
        "request_attempted": False,
        "redirects_followed": False,
        "outcome": "request_not_completed",
        "authenticated": False,
        "body_available": False,
        "limitations": [
            "A full body without explicit account authorization is not proof of authenticated access.",
            "This tests one saved RSS article, not the scheduler or a complete article batch.",
            "No cookie values, response cookie headers, authorization headers, or raw HTML are saved.",
        ],
    }
    try:
        with session_factory() as session:
            session.headers.update(scraper.BROWSER_HEADERS)
            session.cookies.update(loaded.cookies)
            report["request_attempted"] = True
            response = session.get(url, timeout=30, allow_redirects=False)
            report["http_status"] = response.status_code
            if 300 <= response.status_code < 400:
                report["outcome"] = "redirect_not_followed"
                record["scrape_error"] = "The article returned a redirect; no redirect was followed."
            else:
                response.raise_for_status()
                evaluation = evaluate_response(response.content, url)
                report.update({key: evaluation[key] for key in (
                    "outcome", "authenticated", "body_available", "evidence",
                )})
                if evaluation["outcome"] == "authenticated_body_extracted":
                    record.update(
                        full_body=evaluation["full_body"],
                        scrape_status="success", scrape_error=None,
                    )
                else:
                    record["scrape_error"] = {
                        "meter_locked": "The response still reports a meter lock.",
                        "authentication_unverified": (
                            "Account authorization could not be verified; "
                            "article text was not accepted as an authenticated result."
                        ),
                        "authenticated_but_body_missing": (
                            "Account authorization was reported, but no usable article narrative was extracted."
                        ),
                    }[evaluation["outcome"]]
    except requests.RequestException:
        report["outcome"] = "request_failed"
        record.update(
            full_body=None, scrape_status="failed",
            scrape_error="The HTTPS request failed; credential-bearing diagnostics were suppressed.",
        )
    except Exception:
        report["outcome"] = "inspection_failed"
        record.update(
            full_body=None, scrape_status="failed",
            scrape_error="The response could not be inspected safely; no article body was accepted.",
        )

    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    try:
        report["source_unchanged"] = source.read_bytes() == source_bytes
    except OSError:
        report["source_unchanged"] = False
    report["output_dir"] = str(destination.resolve())
    for name, value in (("scraped_news.json", [record]), ("report.json", report)):
        (destination / name).write_text(
            json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cookie-file", type=Path, required=True,
        help="Local Netscape-format cookies from your authorized CoinDesk account; never paste them into chat.",
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE,
                        help="Existing RSS article JSON supplying the matching article metadata.")
    parser.add_argument("--url", default=DEFAULT_URL,
                        help="Exact article URL already present in the source JSON.")
    parser.add_argument("--output-dir", type=Path,
                        help="New isolated folder; defaults to output/rss_authenticated_test/run_<UTC timestamp>.")
    args = parser.parse_args()
    try:
        report = run_trial(
            source=args.source, cookie_file=args.cookie_file, url=args.url,
            output_dir=args.output_dir,
        )
    except AuthenticatedTrialError as exc:
        parser.exit(2, f"Authenticated trial stopped: {exc}\n")
    print(json.dumps({key: report[key] for key in (
        "outcome", "authenticated", "body_available", "source_unchanged", "output_dir",
    )}, indent=2))
    return 0 if report["outcome"] == "authenticated_body_extracted" else 1


if __name__ == "__main__":
    raise SystemExit(main())

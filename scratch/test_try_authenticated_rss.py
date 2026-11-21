"""Offline checks for the isolated, user-supplied authenticated-session trial.

All credentials, HTML and HTTP responses below are synthetic fixtures. No browser,
real account, or network access is used by these tests.
"""

from __future__ import annotations

from contextlib import redirect_stderr
from http.cookiejar import Cookie, MozillaCookieJar
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import try_authenticated_rss as trial
from test_article_body_scraper import FIELDS


BODY = (
    "A cryptocurrency exchange said it had restored customer withdrawals after "
    "completing a security review. The company said customer balances were "
    "unchanged, while investigators continued checking how the incident happened. "
    "The exchange attributed the disruption to an internal configuration issue "
    "and said it would publish a detailed report after the investigation."
)
SENSITIVE_FIXTURE = "not-a-real-auth-cookie-value-should-never-be-logged"


def rss_article() -> dict:
    return {
        "source": "CoinDesk", "guid": "offline-fixture-005", "title": "RSS title retained",
        "rss_summary": "RSS description retained", "url": trial.DEFAULT_URL,
        "image_url": "https://example.org/image.jpg", "published_at": "2026-10-30",
        "categories": ["Markets"], "rss_fetched_at": "2026-10-31T00:00:00+00:00",
    }


def cookie(name: str, domain: str, *, expires: int | None = None) -> Cookie:
    return Cookie(
        version=0, name=name, value=SENSITIVE_FIXTURE, port=None, port_specified=False,
        domain=domain, domain_specified=domain.startswith("."),
        domain_initial_dot=domain.startswith("."), path="/", path_specified=True,
        secure=True, expires=expires, discard=expires is None, comment=None,
        comment_url=None, rest={}, rfc2109=False,
    )


def state(**changes) -> dict:
    from urllib.parse import urlsplit
    value = {
        "remaining": 0, "limit": 3, "allowed": True, "public": False,
        "metered": True, "authorized": True, "premium": False,
        "type": "meter", "pathname": urlsplit(trial.DEFAULT_URL).path,
    }
    value.update(changes)
    return value


def page(*, states: list[dict] | None = None, body: bool = True) -> bytes:
    payload = json.dumps({"states": states if states is not None else [state()]})
    next_chunk = json.dumps([1, payload])
    narrative = (
        '<div class="article-content-wrapper"><div class="document-body">'
        f"<p>{BODY}</p></div></div>" if body else ""
    )
    return (
        '<html><head><title>Offline article</title></head><body><main>'
        '<h1>Offline article</h1><p>Share this article</p>' + narrative +
        '</main><footer data-module-name="footer">Unrelated footer.</footer>'
        f'<script>self.__next_f.push({next_chunk});</script></body></html>'
    ).encode()


def response(payload: bytes, status: int = 200) -> requests.Response:
    value = requests.Response()
    value.status_code = status
    value.url = trial.DEFAULT_URL
    value._content = payload
    value.headers["Content-Type"] = "text/html; charset=utf-8"
    value.headers["Set-Cookie"] = "session=" + SENSITIVE_FIXTURE
    return value


class CookieFileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def save_jar(self, cookies: list[Cookie]) -> Path:
        path = self.directory / "local-session.txt"
        jar = MozillaCookieJar(str(path))
        for value in cookies:
            jar.set_cookie(value)
        jar.save(ignore_discard=True, ignore_expires=True)
        return path

    def test_only_coindesk_domain_boundary_is_accepted(self):
        path = self.save_jar([
            cookie("root", ".coindesk.com"), cookie("www", "www.coindesk.com"),
            cookie("auth", "auth.coindesk.com"), cookie("unrelated", ".example.org"),
            cookie("suffix", ".coindesk.com.evil.example"),
            cookie("prefix", ".evilcoindesk.com"),
        ])
        loaded = trial.load_cookie_file(path)
        self.assertEqual({c.name for c in loaded.cookies}, {"root", "www", "auth"})
        self.assertEqual(loaded.accepted_count, 3)
        self.assertNotIn(SENSITIVE_FIXTURE, repr(loaded))

    def test_session_cookies_retained_but_expired_cookies_excluded(self):
        now = int(time.time())
        path = self.save_jar([
            cookie("session", ".coindesk.com"),
            cookie("expired", ".coindesk.com", expires=now - 1000),
            cookie("future", ".coindesk.com", expires=now + 1000),
        ])
        loaded = trial.load_cookie_file(path)
        self.assertEqual({c.name for c in loaded.cookies}, {"session", "future"})

    def test_malformed_cookie_file_does_not_disclose_a_cookie_line(self):
        path = self.directory / "invalid.txt"
        path.write_text("# Netscape HTTP Cookie File\n" + SENSITIVE_FIXTURE + "\n")
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            with self.assertRaises(trial.AuthenticatedTrialError) as caught:
                trial.load_cookie_file(path)
        self.assertNotIn(SENSITIVE_FIXTURE, str(caught.exception))
        self.assertNotIn(SENSITIVE_FIXTURE, stderr.getvalue())

    def test_common_browser_export_zero_expiry_means_session_cookie(self):
        path = self.save_jar([cookie("browser_session", ".coindesk.com", expires=0)])
        loaded = trial.load_cookie_file(path)
        self.assertEqual([c.name for c in loaded.cookies], ["browser_session"])
        self.assertIsNone(next(iter(loaded.cookies)).expires)

    def test_empty_or_unrelated_jar_is_not_a_valid_account_session(self):
        for cookies in ([], [cookie("unrelated", ".example.org")]):
            with self.subTest(cookies=len(cookies)):
                path = self.save_jar(cookies)
                with self.assertRaises(trial.AuthenticatedTrialError):
                    trial.load_cookie_file(path)


class AccessEvidenceTests(unittest.TestCase):
    def test_verified_authorization_and_body_are_both_required(self):
        result = trial.evaluate_response(page(), trial.DEFAULT_URL)
        self.assertTrue(result["authenticated"])
        self.assertTrue(result["body_available"])
        self.assertIn(BODY, result["full_body"])

    def test_visible_body_without_authorization_is_not_authenticated_success(self):
        for values in (
            [state(authorized=False, remaining=2)],
            [state(authorized=False, public=True, metered=False, type="disabled")],
            [],
        ):
            with self.subTest(states=values):
                result = trial.evaluate_response(page(states=values), trial.DEFAULT_URL)
                self.assertFalse(result["authenticated"])

    def test_locked_header_and_no_narrative_cannot_pass(self):
        result = trial.evaluate_response(
            page(states=[state(authorized=False, allowed=False, type="lock")], body=False),
            trial.DEFAULT_URL,
        )
        self.assertFalse(result["authenticated"])
        self.assertFalse(result["body_available"])

    def test_authorized_but_body_missing_does_not_produce_success(self):
        result = trial.evaluate_response(page(body=False), trial.DEFAULT_URL)
        self.assertFalse(result["body_available"])
        self.assertIsNone(result["full_body"])

    def test_conflicting_or_wrong_article_access_states_are_unverified(self):
        cases = [
            [state(), state(authorized=False, allowed=False, type="lock")],
            [state(pathname="/markets/other-article")],
        ]
        for states in cases:
            with self.subTest(states=states):
                result = trial.evaluate_response(page(states=states), trial.DEFAULT_URL)
                self.assertFalse(result["authenticated"])

    def test_unknown_access_properties_cannot_leak_into_saved_evidence(self):
        result = trial.evaluate_response(
            page(states=[state(refresh_token=SENSITIVE_FIXTURE)]), trial.DEFAULT_URL,
        )
        self.assertNotIn(SENSITIVE_FIXTURE, json.dumps(result["evidence"]))

    def test_only_expected_https_article_hosts_are_accepted(self):
        self.assertEqual(trial.validate_article_url(trial.DEFAULT_URL), trial.DEFAULT_URL)
        for url in (
            "http://www.coindesk.com/markets/story", "https://example.org/story",
            "https://www.coindesk.com.evil.example/story", "https://auth.coindesk.com/story",
            "https://user:password@www.coindesk.com/story", "https://www.coindesk.com:444/story",
        ):
            with self.subTest(url=url), self.assertRaises(trial.AuthenticatedTrialError):
                trial.validate_article_url(url)


class AuthenticatedTrialTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.source = self.directory / "source.json"
        self.article = rss_article()
        saved = {**self.article, "scraped_at": "old", "full_body": "Old headline only",
                 "scrape_status": "success", "scrape_error": None}
        self.source.write_text(json.dumps([saved]))
        self.source_bytes = self.source.read_bytes()
        self.cookie_file = self.directory / "session.txt"
        jar = MozillaCookieJar(str(self.cookie_file))
        jar.set_cookie(cookie("session", ".coindesk.com"))
        jar.save(ignore_discard=True)
        self.cookie_bytes = self.cookie_file.read_bytes()
        # Even a faulty test implementation cannot reach the live network.
        network_guard = patch("requests.sessions.Session.send", side_effect=AssertionError(
            "Live network access is forbidden in the authenticated-trial tests"
        ))
        network_guard.start()
        self.addCleanup(network_guard.stop)

    def run_fixture(self, fixture: requests.Response) -> tuple[dict, dict, requests.Session]:
        client = requests.Session()
        client.get = Mock(return_value=fixture)
        self.output = self.directory / "run"
        report = trial.run_trial(source=self.source, cookie_file=self.cookie_file,
                                 output_dir=self.output, session_factory=lambda: client)
        records = json.loads((self.output / "scraped_news.json").read_text())
        self.assertEqual(len(records), 1)
        self.assertEqual(set(records[0]), set(FIELDS))
        self.assertEqual(self.source.read_bytes(), self.source_bytes)
        self.assertEqual(self.cookie_file.read_bytes(), self.cookie_bytes)
        return report, records[0], client

    def test_one_authorized_request_keeps_exact_schema_and_rss_metadata(self):
        _, record, client = self.run_fixture(response(page()))
        self.assertEqual(record["scrape_status"], "success")
        self.assertIsNone(record["scrape_error"])
        self.assertIn(BODY, record["full_body"])
        for name, value in self.article.items():
            self.assertEqual(record[name], value)
        client.get.assert_called_once_with(trial.DEFAULT_URL, timeout=30, allow_redirects=False)
        serialized = "\n".join(p.read_text() for p in self.output.iterdir() if p.is_file())
        self.assertNotIn(SENSITIVE_FIXTURE, serialized)
        self.assertFalse(list(self.output.glob("*.html")))

    def test_body_available_from_anonymous_quota_is_saved_as_failed_authentication(self):
        _, record, client = self.run_fixture(response(page(states=[state(authorized=False)])))
        self.assertEqual(record["scrape_status"], "failed")
        self.assertIsNone(record["full_body"])
        self.assertTrue(record["scrape_error"])
        self.assertEqual(client.get.call_count, 1)

    def test_redirect_is_not_followed_or_treated_as_a_success(self):
        fixture = response(page(), 302)
        fixture.headers["Location"] = "https://unrelated.example/login"
        _, record, client = self.run_fixture(fixture)
        self.assertEqual(record["scrape_status"], "failed")
        self.assertIsNone(record["full_body"])
        client.get.assert_called_once_with(trial.DEFAULT_URL, timeout=30, allow_redirects=False)

    def test_request_exception_does_not_echo_credentials(self):
        client = requests.Session()
        client.get = Mock(side_effect=requests.ConnectionError(SENSITIVE_FIXTURE))
        output = self.directory / "request-error"
        report = trial.run_trial(source=self.source, cookie_file=self.cookie_file,
                                 output_dir=output, session_factory=lambda: client)
        self.assertEqual(report["outcome"], "request_failed")
        record = json.loads((output / "scraped_news.json").read_text())[0]
        self.assertEqual(record["scrape_status"], "failed")
        self.assertIsNone(record["full_body"])
        saved = "\n".join(p.read_text() for p in output.iterdir())
        self.assertNotIn(SENSITIVE_FIXTURE, saved)

    def test_existing_results_are_refused_before_any_request(self):
        output = self.directory / "existing"
        output.mkdir()
        marker = output / "saved-result.json"
        marker.write_text('{"keep": true}\n')
        factory = Mock()
        with self.assertRaises(trial.AuthenticatedTrialError):
            trial.run_trial(source=self.source, cookie_file=self.cookie_file,
                            output_dir=output, session_factory=factory)
        factory.assert_not_called()
        self.assertEqual(marker.read_text(), '{"keep": true}\n')


if __name__ == "__main__":
    unittest.main()

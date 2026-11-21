# CoinDesk authenticated RSS article test

**Status: stopped at the user's request on 2026-10-31.** The selected method is
the existing RSS/request flow with the approved pruning in
`rss_scrape_scheduler_pruned.py`; see `RSS_SCRAPER_PRUNED_README.md`.

No login-cookie file was provided or exported, and no live authenticated Python
request was performed. This runner and its offline tests are retained only as
unused experimental work. The setup instructions below are historical, not the
next step in the selected workflow. Do not resume cookie collection or account
integration unless the user explicitly requests it again.

This is a separate, one-article experiment. It tests whether a locally supplied
CoinDesk login session lets Python download the affected article and extract its
body with the existing Trafilatura/prune_xpath method.

It does not change `rss_scrape_scheduler.py`, `rss_scrape_scheduler_pruned.py`,
`rss_scrape_dataset.py`, `main_pipeline.py`, the database, or existing datasets.
No login endpoint is invented and no password is hardcoded. The test does not
clear cookies, rotate identities, or change the reading allowance.

## What is verified so far

- The affected article's narrative, including its closing paragraph, is visible
  in the existing Safari context.
- That observation alone does not prove that Python is authenticated, or isolate
  login from other browser/session differences.
- Safari's Save button was disabled during the attempted local source export;
  no authenticated HTML sample was exported by that attempt.
- An authenticated Python request still needs a local login-cookie file provided
  by the user. The runner has not been tested against a live authenticated account
  until that file is supplied and the response confirms authorization.

## Why RSS remains part of the method

The current scraper already reads URLs and metadata from RSS, then downloads each
article's webpage. This test reuses a saved RSS record from
`output/rss_pruned/scraped_news.json`. Only the webpage request receives the
supplied login cookies. For this one-article test, the RSS snapshot stays fixed;
there is no new RSS fetch, scheduler run, history reset, or database write.

## Historical local account setup

1. Sign in to your own free CoinDesk account in your browser.
2. Confirm the affected article is readable and that the account menu shows you
   signed in.
3. Supply an existing, locally exported **Netscape-format cookie file** containing
   the relevant CoinDesk session cookies. Keep it outside the repository, for
   example `~/.config/pragma/coindesk-cookies.txt`. Do not paste cookie values into
   chat or commit the file: those values can authorize account access.

If you do not already have an export, Safari's Web Inspector lets you inspect the
Cookie rows for the signed-in CoinDesk page. Enable developer features through
Safari > Settings > Advanced > Show features for web developers, then open
Develop > Show Web Inspector and locate the page's Cookies storage. If copying
rows manually, preserve their exact names, values, domain, path, Secure flag and
expiration, including relevant HttpOnly cookie rows. There is no assumption that
Safari offers a built-in Netscape export button.

A Netscape cookie file starts with `# Netscape HTTP Cookie File`. Each cookie row
has these seven **TAB-separated** fields, followed by a newline:

```text
domain    include_subdomains    path    secure    expires_unix    name    value
```

The line above describes the fields; it is not a usable cookie row. Use the
cookie's actual browser values. Domain cookies normally have a leading dot and
`TRUE` for `include_subdomains`; host-only cookies use `FALSE`. Expiration is a
Unix timestamp in seconds; `0` or an empty expiration field represents a session
cookie in this runner. The `#HttpOnly_` domain prefix is accepted. Do not alter
cookie contents or extend real expiration times.

The runner loads only unexpired cookies scoped to `coindesk.com` or its
subdomains. It does not access Safari's cookie database or export credentials
from any browser. The local cookie file is read without being rewritten.

## Run the single-article test

From the repository root with the project's virtual environment active:

```bash
python try_authenticated_rss.py \
  --cookie-file "$HOME/.config/pragma/coindesk-cookies.txt"
```

The default URL is the article that previously produced only 271 characters:

```text
https://www.coindesk.com/markets/2026/10/30/wall-street-analysts-urge-investors-to-buy-crypto-stocks-on-weakness-after-usd6-3-billion-binance-hack
```

For another saved RSS article, use `--url` and, if necessary, `--source`:

```bash
python try_authenticated_rss.py \
  --cookie-file "$HOME/.config/pragma/coindesk-cookies.txt" \
  --source output/rss_pruned/scraped_news.json \
  --url "https://www.coindesk.com/your-saved-article-path"
```

The selected URL must match exactly one record in the source snapshot. Only HTTPS
article URLs on `coindesk.com` or `www.coindesk.com` are accepted. Redirects are
not followed in this trial. If the request redirects to login, refresh your
account session through the normal browser sign-in flow; the runner does not
automate login or ask for passwords.

## Outputs and interpretation

Each run creates a new folder under `output/rss_authenticated_test/`:

- `report.json`: authorization/body evidence and the trial outcome.
- `scraped_news.json`: one record using the existing 13-field structure.

The result is successful only when the selected article's response contains an
unambiguous, path-matched access state with `authorized: true`, no meter lock,
and actual narrative content that the existing extraction method can extract.
HTTP 200 or a long text string alone is not sufficient. A fresh anonymous visitor
can receive a full body using an unused reading allowance, so an accessible body
without authorization evidence is reported as unverified.

An unsuccessful record has `full_body: null`, `scrape_status: "failed"`, and an
explanation in `scrape_error`. Such output must not be fed to NLP as a complete
article. Successful extraction verifies body availability, not perfect article
completeness or access to every other article.

The runner does not save raw authenticated HTML, cookie values, cookie headers,
or login credentials. It uses the existing browser headers, a 30-second request
timeout, and the existing pruning/cleanup functions. No new dependencies are
required beyond the project's existing scraper dependencies.

## Offline verification

```bash
python -m unittest scratch.test_try_authenticated_rss -v
python try_authenticated_rss.py --help
```

These checks use fabricated cookie fixtures and mocked HTTP responses, without
opening an account or contacting CoinDesk. They validate the runner's behavior;
they do not establish that a real account session works in Python.

## References

- [CoinDesk free registration announcement](https://www.coindesk.com/coindesk-news/2025/01/22/coindesk-launches-free-registration-wall)
- [Requests session and cookie behavior](https://requests.readthedocs.io/en/latest/user/advanced/#session-objects)
- [Python cookie jars](https://docs.python.org/3/library/http.cookiejar.html)
- [Apple: enabling Safari developer features](https://developer.apple.com/documentation/safari-developer-tools/enabling-developer-features)
- [curl: Netscape cookie file fields](https://curl.se/docs/http-cookies.html)

The separate high-priority integration of `article_preprocessing.py` into
`main_pipeline.py` remains pending. This authentication experiment does not
complete or change that work.

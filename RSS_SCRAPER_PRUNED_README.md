# RSS scraper copy with approved HTML pruning

`rss_scrape_scheduler_pruned.py` remains a separate experimental copy with its
own output directory. The original `rss_scrape_scheduler.py` now uses the same
approved body-pruning rules. The dataset collector and main pipeline continue
to import the original scheduler and receive pruned article bodies through it.

## Selected approach: 2026-10-31

The user chose to continue the existing RSS and anonymous webpage-request method
with the approved `prune_xpath` additions. Account authentication and cookie-file
setup are no longer being pursued. The separate authenticated test runner is
retained as an unused experiment; it is not imported by this scraper or the
production pipeline.

Use this pruned copy for the experiment. The RSS source, metadata, request headers,
session lifecycle, delay, and JSON schema remain as described below. This choice
does not add a cookie reset, login flow, or automatic reading-meter workaround.
It also does not add completeness filtering: withheld or incomplete article
bodies remain a limitation of the inherited extraction-success check.

## Run and output

From the project root with the existing virtual environment:

```bash
python rss_scrape_scheduler_pruned.py
```

This runs one RSS batch, like the original script. It does not install a timer or
start an automatic 15-minute loop. Results are written separately to:

```text
output/rss_pruned/
  rss_temp.json
  rss_history.json
  scraped_news.json
```

**Startup behaviour is intentionally copied:** direct execution resets these
three copy-specific files, including the copy's history, before fetching RSS.
It never resets the original `output/rss_temp.json`, `output/rss_history.json`
or `output/scraped_news.json`. Running the file again therefore starts that
copy's CLI batch from empty history, just as the existing original CLI does.

For an incremental scheduled/notebook call that retains the copy's history:

```python
from rss_scrape_scheduler_pruned import run_scheduler

stats = run_scheduler()
```

Importing the module does not reset data or fetch anything. Each call to
`run_scheduler()` opens one session, fetches RSS first, scrapes new records only,
checkpoints each completed article, and advances history after the whole batch.

## Body extraction in both schedulers

After downloading each article, `prepare_pruned_html()` marks bounded What's
trending sections, then Trafilatura receives the approved `prune_xpath` rules:

- `//footer[@data-module-name="footer"]`: the website footer.
- `//*[@data-module-name="article-bottom-news"]`: latest-news and research modules.
- An experimental attribute on the exact What's trending heading and its bounded
  following sibling content. The section stops at an equal/higher-level heading
  in the same parent, or that parent's end. Ambiguous nested boundaries or
  meaningful unwrapped tail text are retained with a log warning.

Read more, subscriptions, newsletter introductions, publisher summary widgets,
article headers and market-price chips have no new removal rules. Genuine
article lists outside the targeted section remain. The following Today’s signal
section is retained in the observed Daybook example.

`favor_precision=False`, `include_comments=False` and `include_tables=False`
are explicit. The existing pagination and duplicate-line cleanup follows.
There is no strict document-body-only extraction gate and no new JSON-LD body
fallback; Trafilatura still identifies the main text from the remaining HTML.
The new helper is self-contained, with no dependency on the experiment runner
or model/database modules.

The request URL, RSS limit setting, headers, article timeout, five-second delay
and one-session-per-batch lifecycle are copied. `RSS_LIMIT=100` caps available
RSS entries; it cannot force the feed to return 100 articles.

## Metadata and schema

The existing 13-field structure is preserved:

```text
source, guid, title, rss_summary, url, image_url, published_at, categories,
rss_fetched_at, scraped_at, full_body, scrape_status, scrape_error
```

As in the original scheduler, title and metadata come from RSS. Only the article
body extraction gains the pruning rules. This is distinct from the earlier
separate experiment that re-extracted the page H1/metadata. No fields, database
tables or NLP results are added.

## Access and completeness limitations

Pruning does not retrieve withheld text or guarantee avoidance of a reading-meter
lock. Request/session behaviour is not changed to circumvent access restrictions.
The original nonempty-text success criterion is retained: a nonempty extraction
can still be incomplete. This copy does not silently introduce access validation
or treat metadata as proof of a full article. Parser errors and empty extraction
are reported through the existing failure fields.

The earlier offline comparison established the approved removals on matching
captured pages. It did not establish complete extraction for every future layout.
See `PRUNE_XPATH_EXPERIMENT_README.md` for the controlled comparison and its limits.

## Verification

```bash
python -m unittest scratch.test_rss_scrape_scheduler_pruned scratch.test_prune_xpath_comparison -q
```

The copy was also replayed against all 29 available rendered article responses
from `output/article_body_scrape_test/full_20261031_01/`, using mocked HTTP
responses. Every resulting body matched the previously approved pruned output,
including the five live blogs and the Deutsche Bank endpoint. This replay made
no network requests and did not populate the copy's live output folder.

The requested realtime integration of `article_preprocessing.py` with the original
`main_pipeline.py` remains pending. Creating this separate copy does not complete
or replace that high-priority integration.

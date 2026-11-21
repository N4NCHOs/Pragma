# Separate CoinDesk article-body scraping experiment

This experiment re-downloads saved CoinDesk article URLs and extracts a fresh
headline and a more narrowly selected article body. It does not collect a new RSS
feed or change the production scraper, collector, pipeline, models, or database.

## Files

- `test_article_body_scraper.py`: standalone command and reusable extraction function.
- `scratch/test_article_body_scraper.py`: offline boundary/persistence tests.
- `ARTICLE_BODY_SCRAPER_TEST_README.md`: method, commands, and limitations.

Existing dependencies (`requests`, `lxml`, `trafilatura`) and the existing request
headers and `clean_full_body()` function are reused. No new packages are needed.

## Input and extraction method

The default source is `output/rss_dataset_recovered/qualified_news.json`.
The source is snapshotted before collection. Source positions, GUIDs, URLs, and
dataset IDs remain available for joining old and new results. The old headline
and body are used only for comparisons, never as extraction fallbacks.

1. Download each source URL with the existing scraper's headers and request delay.
2. Require one main content region and one nonempty article H1 within it.
3. Check the article-level JSON-LD identifier against the saved GUID when available.
4. Remove `data-module-name="article-bottom-news"` regions from the main tree.
5. Select **direct** `document-body` children of `article-content-wrapper` inside
   main, preserving all matched blocks in document order. Do not select only the
   first block, or every `document-body` on the entire page.
6. Exclude nested summary widgets and sidebar/navigation/footer regions. Preserve
   lists and headings genuinely inside the selected narrative blocks.
7. Give only the selected HTML to Trafilatura, with comments and tables excluded.
8. Apply the existing pagination and duplicate-line cleanup. Record source text
   segments that cannot be found verbatim afterward, for manual inspection.

The title is read from the page's H1 and stays in `title`; it is not prepended to
`full_body`. The current class/attribute rules are specific to inspected CoinDesk
HTML. Missing expected structure is a failure, not permission to extract the whole
webpage, reconstruct prose from unrelated scripts, or reuse the previous body.

## Output schema

`scraped_news.json` is a pretty-printed JSON list with exactly the same 13 fields
as the existing `output/scraped_news.json`:

| Fields | Provenance |
|---|---|
| `title`, `full_body` | Fresh page H1 and selected narrative; no old-text fallback. |
| `image_url` | Article image metadata, preferring `og:image`; stored image only if unavailable. |
| `published_at` | Page publication metadata, formatted as RFC 2822 GMT; stored date only if unavailable. |
| `categories` | Page article section and keywords/tags; stored categories only if unavailable. |
| `source`, `guid`, `url` | Preserved identity from the source record. |
| `rss_summary`, `rss_fetched_at` | Original RSS provenance; a webpage request is not a fresh RSS fetch. |
| `scraped_at` | Timestamp of the current attempt, including saved-HTML reprocessing. |
| `scrape_status`, `scrape_error` | Structural extraction success/failure and reason. |

Per-field metadata origins and fallbacks are in the audit. Categories freshly
extracted from a page need not exactly match RSS category spelling or membership.
For example, an RSS `News` category may not exist in the page metadata.

Failed rows remain in the result with empty `title`, `full_body: null`, and a
failure reason. A successfully parsed H1 may still be visible as `page_title` in
the failure audit if body selection failed; it is not reused to claim success.
Qualification/novelty fields are not copied into this scraper-shaped output, and
the new text is not automatically declared eligible for downstream evaluation.

## Run

From the project root, using the project virtual environment:

```bash
# Six layouts, including the Deutsche Bank witness and known newsletter cases.
python test_article_body_scraper.py --indices 20 1 10 15 50 61

# Every URL in the current source snapshot; default delay is 5 seconds.
python test_article_body_scraper.py

# Another source, or a small initial sample.
python test_article_body_scraper.py --source path/to/articles.json --limit 5

# Replay downloaded HTML for matching source position + URL filenames.
# Cache misses are downloaded; the new output folder must not already exist.
python test_article_body_scraper.py \
  --source output/article_body_scrape_test/pilot_20261031_01/source_snapshot.json \
  --html-dir output/article_body_scrape_test/pilot_20261031_01/html

# Offline checks, with no live requests or model loads.
python -m unittest scratch.test_article_body_scraper -q
```

Without `--output-dir`, each command creates a unique timestamped folder under
`output/article_body_scrape_test/`; folder names use Asia/Jakarta time and stored
timestamps are UTC. Existing output folders are refused to prevent overwrites.

```text
run_<timestamp>/
  source_snapshot.json      original input bytes
  scraped_news.json         scraper-shaped records, including failures
  comparison.json           complete old/new text, IDs, excluded regions, provenance
  report.json               configuration, counts, source/script hashes, warnings
  report.md                 readable results and limitations
  html/
    <source-index>_<url-hash>.html           received HTTP response or replay
    <source-index>_<url-hash>.selected.html  selected article HTML on success
```

Results are checkpointed after each completed attempt. Ctrl+C retains completed
records and marks the run interrupted. There is no in-place resume/overwrite;
use a new run folder and `--html-dir` to reuse the downloaded responses. HTTP error
responses are also retained; replaying one can fail again. Exit codes: 0 means
every selected article extracted, 2 means the run finished with article failures,
1 means a setup/file error, and 130 means interrupted.

## How to judge whether it works

Inspect `comparison.json` and the corresponding saved HTML. For each page, verify:

- The fresh headline belongs to the requested article.
- Story paragraphs, genuine lists, and continuation blocks are retained in order.
- Summary widgets, recommendations, navigation, and footer text are excluded.
- Each missing source segment is explained. A verbatim mismatch may be markup or
  whitespace around inline tickers, but may also indicate useful text was lost.
- Metadata origins and any saved-RSS fallbacks are understood.

`scrape_status: success` means the expected structure produced nonempty text.
It is **not** a factuality/cleanliness/completeness guarantee. The report does not
pretend to automatically label every remaining paragraph as relevant news.

## Known limitations

- Some live blogs use `live-news-article` and per-update body containers rather
  than `document-body`. This experiment flags them as unsupported; it does not
  silently change extraction methods or return a partial live blog.
- Some downloaded pages contain headline/metadata but no narrative body in the
  expected HTML. They are flagged. This alone does not establish whether the
  cause is client rendering, access restrictions, or a temporary server response.
- Publisher edits can change the article at the same URL. Old-vs-new differences
  cannot all be attributed to extraction cleanup.
- A newsletter introduction embedded inside a genuine narrative block can remain.
  No new semantic filtering or broad newsletter-deletion rules are introduced.
- Existing pagination cleanup can cut meaningful numbered content. Missing source
  segments and cleanup changes are audited, not assumed harmless.
- No new GPT references or FLAN summaries/scores are created. Review changed source
  text and references before any later evaluation.

This is a refinement of the outline's HTML parsing followed by existing text
cleanup. It is not yet a production preprocessing change. In particular,
`article_preprocessing.py`'s exact-footer cleaner remains independent and its
requested realtime integration is still pending; this experiment does not mark
that high-priority integration complete.

## First full experiment — 31 October 2026

Results: `output/article_body_scrape_test/full_20261031_01/`.
The source snapshot contains 73 articles. Six responses were reused from the
same-session pilot; the remaining 67 URLs were freshly downloaded.

| Outcome | Count |
|---|---:|
| Structural extraction succeeded | 24 |
| Narrative blocks absent from the returned expected main markup | 43 |
| Different live-blog layout, unsupported by this selector | 5 |
| Main headline absent | 1 |
| Total retained records | 73 |

All HTTP requests that returned responses in this run had status 200; an HTTP
success did not establish that usable narrative HTML was present. The underlying
cause of missing narrative has not been established. No access mechanism or new
content-fetching service was introduced to compensate.

The Deutsche Bank article (source #20) has a fresh H1, all eight narrative
paragraphs, and ends exactly at `BBVA in offering crypto custody.` Its summary
widget and research recommendation are excluded. The White House article
(source #15) now yields narrative content rather than the previously collected
navigation-dominated text.

Six successful extractions have source-segment verbatim mismatch warnings. These
are review flags, not six proven cases of paragraph loss. Inspected examples
involve inline ticker/price widgets, whitespace/zero-width characters and list
prefixes. `Read more` and `What's trending` remain in source #5 because they are
inside the selected narrative container. Further conservative cleaning would be
a separate method change and has not been applied here.

`verification.json` records schema, identity, source-hash and selected-HTML checks.
The experiment supports structural removal of external recommendations on
matching pages; it does not establish universal extraction across all CoinDesk
layouts or a completely noise-free evaluation dataset.

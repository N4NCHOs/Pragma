# Controlled offline prune_xpath experiment

This separate experiment tests the user's approved HTML removals against the
same saved webpage responses. It does not download anything, rotate sessions,
change access parameters, run NLP models, or write to the database.

## Approved scope

Remove only:

1. The website footer: `//footer[@data-module-name="footer"]`.
2. Latest-news and research modules:
   `//*[@data-module-name="article-bottom-news"]`.
3. The exact **What's trending** section within narrative content, including its
   heading and following siblings until the next equal/higher-level heading in
   the same parent, or that parent's end.

Do not introduce removal rules for Read more, subscription text, newsletter
introductions, site-generated summary widgets, article headers, inline price
chips, or arbitrary lists. All extraction settings are held fixed, including
`favor_precision=False`, `include_comments=False`, and `include_tables=False`.
The existing pagination/duplicate-line cleanup is applied identically afterward.

## Why a bounded section needs a marker

The observed What's trending section has no dedicated container attribute. On
source #5 it is an H2 followed by a UL inside a narrative document-body block.
The preceding Read more paragraph must remain, and Today's signal follows in
another article block and must remain.

The experiment finds an exact normalized heading (case/whitespace and curly
apostrophe variants), marks only the bounded heading/sibling nodes using a
private attribute, then removes those nodes through `prune_xpath`. It does not
delete all following elements on the page. If a sibling contains a nested
equal/higher-level heading, or meaningful unwrapped tail text makes the boundary
ambiguous, the section is retained and flagged for review.

Both control and experimental conditions receive identical copies of the marked
DOM; the control ignores the markers. Only the experimental condition passes the
prune_xpath argument. This keeps the comparison independent of request/session
behavior and of raw-string-versus-DOM parser differences.

## Files and command

- `compare_prune_xpath.py`: offline runner and pruning-plan helpers.
- `scratch/test_prune_xpath_comparison.py`: boundary, preservation and output tests.
- `PRUNE_XPATH_EXPERIMENT_README.md`: protocol and results.

Existing dependencies and pure project helpers are reused. No requirements file
or existing scraper/preprocessing module was changed.

```bash
python compare_prune_xpath.py

# Another directory containing source_snapshot.json and the saved html/ files:
python compare_prune_xpath.py --input-run output/article_body_scrape_test/full_20261031_01

# Explicit NEW destination; an existing directory is refused:
python compare_prune_xpath.py --output-dir output/article_body_scrape_test/prune_xpath_next

python -m unittest scratch.test_prune_xpath_comparison -q
```

Without an explicit destination, a unique Asia/Jakarta timestamped folder is
created beneath `output/article_body_scrape_test/`. The source snapshot and raw
HTML are never overwritten. No automatic retries or network fallback exist.

## Outputs

```text
prune_xpath_<timestamp>/
  source_snapshot.json          byte-identical source snapshot
  baseline_scraped_news.json    original extraction condition
  pruned_scraped_news.json      experimental extraction condition
  comparison.json              exact removals, full text, diffs and retention checks
  report.json                  settings, hashes, counts and limitations
  report.md                    readable results
```

Both scraper-shaped exports have exactly the existing 13 fields. The title is
read from the saved response's main H1, independently of extraction, and shared
between both conditions. Image/date/categories are read from article page
metadata when available; any saved-RSS metadata fallback is recorded. The old
title and old full_body are not used as extraction fallbacks. RSS metadata keeps
its original meaning, and scraped_at identifies the current offline processing
attempt; original HTTP capture provenance remains in the source run.

Raw diagnostic text for unavailable pages is retained only in comparison.json.
Nonempty navigation is not called an article: rendered-content availability is
validated against the known narrative/live-update containers and headline.
There is no new JSON-LD body fallback in this pruning-only test. Source #37 has
structured live-blog content, but no supported rendered headline/body; it remains
unavailable in these exports. This does not mean its structured text was lost.

No original asset/novelty decisions are transferred as new decisions. These
outputs are candidates for inspection, not an automatically qualified replacement
for the evaluation cohort or production pipeline input.

## Results — 31 October 2026

Source: `output/article_body_scrape_test/full_20261031_01/`.
Results: `output/article_body_scrape_test/prune_xpath_20261031_01/`.

| Measurement | Result |
|---|---:|
| Saved HTML responses examined | 73 |
| Available rendered article pages | 29 |
| Unavailable rendered pages | 44 |
| Available article outputs changed | 24 |
| Available live-blog outputs unchanged | 5 |
| Retained baseline-present article segments lost | 0 observed |
| Site footer nodes matched | 73 |
| Latest-news/research nodes matched | 58 across 29 pages |
| What's trending sections matched | 1, represented by 2 nodes |
| New HTTP requests | 0 |

The retention check covered 598 distinct per-article source segments that were
present verbatim in the control and outside the approved removals. Independent
line-diff review of all 29 available pages found only the approved research-teaser
deletions and source #5's trending section; no additional news-paragraph loss was
observed. The paired DOM-based control is not a byte-for-byte reproduction of
production raw-response parsing: the 24 standard pages show a one-character
raw-vs-DOM variation (the colon in the research heading on source #20). This
precedes both experimental conditions; the five live blogs have no such variation.

The unavailable set is 43 locked regular-article responses plus source #37's
unrendered live blog. Pruning did not recover withheld narratives, and these
records remain with full_body=null and a failure reason in both exports.

On source #5, What's trending is removed while Read more, Sign up here and the
later Today's signal section remain. On source #20, the Deutsche Bank research
teaser is removed and the article still ends at the BBVA custody sentence.
The five rendered live blogs retain the same extracted text as the control.

## How to interpret the evidence

Each removed node is logged with its rule, XPath, text and HTML. The full
before/after extraction and a line diff are retained per source article.
Retention checks look for narrative source segments present in the control but
absent from the experimental extraction, after excluding the specifically
approved removals. Existing cleanup changes are reported separately.

Zero observed retention losses is not proof of factuality or complete extraction.
Trafilatura may already omit source material in both conditions, and inline
widgets can make verbatim source comparisons imperfect. A shorter output alone
does not establish quality. Check all remaining text against the saved HTML
before replacing any evaluation inputs or reviewing GPT-reference compatibility.

Removing HTML containers refines the outline's existing HTML-parsing stage.
Document the final rules and inspection procedure before adopting them. Production
scraping, FLAN, and database integration are unchanged. The previously requested
realtime integration of `article_preprocessing.py` remains pending; this
experiment does not complete it.

# FLAN input-length experiments

`main_pipeline2.py` compares input ceilings on the same **100 full articles**.
The original `main_pipeline.py`, RSS module, models, database schema, and Docker
configuration are not modified. Existing services are reused.

## Run from the repository root

First check whether the source can provide a sufficient dataset:

```bash
python main_pipeline2.py --prepare-only
```

This fetches/scrapes and checks article eligibility, including the existing
embedding-based novelty criterion. It does **not** truncate PostgreSQL or run
FLAN/DeBERTa inference. The original services still require their normal Python,
model, and database environment. RSS working files are backed up and cleared.

Run all four default input ceilings:

```bash
python main_pipeline2.py --confirm-db-reset --max-input-tokens 512 1024 2048 3072
```

**Warning:** after dataset validation, this command backs up and truncates
**`public.news_articles` in the database configured by `database.py` before every
iteration, including the first**. It restarts that table's IDs. The program
prints the destination without the database password. It does not use `CASCADE`
or delete any other table. If backup creation, table locking, or truncation fails,
the experiment stops. Stop other writers to the same table while experimenting.

After a successful preparation, reuse its printed `fixed_articles.json` path so
the full run does not fetch another dataset:

```bash
python main_pipeline2.py --confirm-db-reset --dataset "/absolute/path/to/fixed_articles.json" --max-input-tokens 512 1024 2048 3072
```

`--mode sequential` is the default; `--mode concurrent` retains the original
pipeline's inference mode. Keep the mode fixed within comparisons. The checkpoint,
prompt, generation settings, asset filter, and novelty threshold remain unchanged.
Only the in-memory FLAN input ceiling changes; it is restored on exit. Tokenizer
and model instances are reused instead of reloaded for each article or iteration.

## How the fixed batch is obtained

The experiment reads up to **1,000 candidate entries** from the existing CoinDesk
RSS feed, using the existing `fetch_latest_rss` and `scrape_article` functions.
The existing request delay and extraction logic are preserved. This wider slice
does not make the feed return additional history and introduces no new source,
pagination, or scraping technique. Override it with `--candidate-limit N`.

Candidates must have a title, HTTP(S) URL, nonempty `full_body`, and pass the
existing asset filter. RSS summary fallbacks are intentionally excluded from this
controlled full-article comparison. URL/GUID duplicates and semantic duplicates
are rejected using the existing embedding model and novelty distance threshold.
The first 100 qualifying articles, in stable source order, become the fixed batch.
Normal database novelty detection still runs in each iteration; an unexpected
redundant article makes that iteration incomplete rather than bypassing detection.

If fewer than 100 qualify, **no database truncation occurs**. The terminal and
`collection_report.json` explain the shortfall: source count, missing bodies and
scrape errors, asset-filter rejection, duplicates, semantic redundancy, or
embedding failures. No articles are repeated or synthesized to reach 100.
The collector does not poll indefinitely for future articles. A sufficiently
large existing JSON list of normalized scraped articles can be supplied with
`--dataset`; the same validation still applies.

## Outputs

The terminal prints a unique experiment directory under
`output/pipeline_results/experiments/`. It contains:

- `source_articles.json`: the source snapshot, before experiment selection.
- `collection_report.json`: selection counts and reasons for rejection.
- `fixed_articles.json`: the immutable, ordered 100-article dataset.
- `experiment.json`: overall/iteration status, dataset hash, limits, actual FLAN
  checkpoint, prompt, literal generation options, device, and novelty threshold.
- `collection_rss_backup/`: pre-collection RSS working files (for fresh collection).
- One `flan_<limit>/` directory per attempted iteration, containing its CSV,
  `database_before_reset.json`, and RSS working-file backups.

RSS files are cleared before each iteration, but inference reads the preserved
fixed batch directly instead of fetching fresh news. Previous CSVs are not cleared.
Each successful iteration must have exactly 100 saved rows and complete NLP
results. A partial model result, database error, missing/invalid CSV, altered
dataset, or unexpected redundancy stops advancement to the next input ceiling.
Incomplete CSVs and diagnostics are retained for inspection, not counted as
completed evaluations. Database snapshots are recovery data, not an automatic
restore feature or a full PostgreSQL backup.

CSVs retain the original results columns, plus `experiment_id`, `dataset_sha256`,
`flan_max_input_tokens`, and `flan_original_input_tokens`. `flan_input_tokens`
records the actual encoder input **including the prompt**, after truncation.
`model_input_text` is title plus full body, before the FLAN instruction prompt.
Join configurations by the dataset hash and `article_index`, not database IDs
across unrelated experiments. Human references and ROUGE/BERTScore evaluation
are not generated automatically by this runner.

The database retains the **last attempted iteration's records**. Earlier iterations
remain in CSVs and pre-reset snapshots. Runtime measurements are observational:
first-call loading/cache effects and device synchronization can affect comparisons.

## Offline verification

```bash
python -m unittest discover -s scratch -p 'test_*pipeline*.py' -v
```

Tests use temporary files and mocked services. They do not fetch news, load
production models, or connect to/truncate the real database.

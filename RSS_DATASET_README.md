# Collect a fixed RSS news dataset

`rss_scrape_dataset.py` builds a separate, resumable dataset of 200 qualified
articles by default. It does not run the news pipeline or write to PostgreSQL.
The existing RSS scraper, scheduler, and pipeline commands keep their existing
behavior.

Run from the repository root with the project's Python environment active:

```sh
python rss_scrape_dataset.py
```

The collector checks the feed immediately, then polls every 900 seconds until
it has 200 qualified articles. Keep the terminal and process running and the Mac
awake between polls. This command does not create a Codex automation or a
background service. Use Ctrl+C to pause; completed checkpoints remain on disk.
Run the same command with the same settings again to resume. Articles checkpointed
before an interrupted qualification step are recovered on the next run.

The source feed is finite. A candidate limit of 1,000 does not make the feed
contain 1,000 stories: the current feed may expose only about 25. Reaching 200
qualified articles will require future feed updates and may take substantial
time. Asset filtering, failed scraping, duplicates, and semantic redundancy
reduce the eligible count further. The collector cannot guarantee when the
target will be reached.

## Commands

Poll once and save progress, without waiting for another feed update:

```sh
python rss_scrape_dataset.py --once
```

Use a separate collection directory and explicit settings:

```sh
python rss_scrape_dataset.py --target 200 --candidate-limit 1000 --poll-seconds 900 --output-dir output/rss_dataset_200
```

Optionally merge an existing JSON list of scraped articles into the collection:

```sh
python rss_scrape_dataset.py --seed output/scraped_news.json --once
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--target` | `200` | Required number of qualified articles. |
| `--output-dir` | `output/rss_dataset` | Dedicated collection directory; reused to resume. |
| `--candidate-limit` | `1000` | Maximum feed candidates considered per poll, subject to what the feed supplies. |
| `--poll-seconds` | `900` | Delay between polls while collecting; minimum 60 seconds. |
| `--once` | Disabled | Perform one poll, checkpoint, and exit. |
| `--seed` | None | Merge a local JSON list of known scraped articles. |

Use a new `--output-dir` when changing the collection configuration. Existing
state protects the selected dataset and its qualification settings from being
silently replaced.

## Qualification

An article qualifies only if it has a valid title and HTTP(S) URL, a nonempty
scraped full body, and passes the existing production asset filter. RSS summaries
and descriptions do not substitute for missing full bodies in this controlled
dataset.

The collector removes repeated URLs/GUIDs using the scheduler's normalized
article identities. It then uses the production `all-MiniLM-L6-v2` embedding
model and unchanged cosine-distance novelty threshold to check each candidate
against the growing selected dataset. Novelty is local to this collection; it
does not depend on the contents of the live news database. Embeddings are cached
in the collection state so resuming can reuse completed work.

MiniLM encoding is necessary for this qualification step. The collector does
not import or run FLAN-T5, DeBERTa, or the database module. Failed scraping and
embedding errors do not count toward the target.

Missing-body or extraction failures are retried when that story appears in a
later feed poll, up to three scraping attempts in total and at most once per
story per poll. Previous scrape errors remain in the article's
`collection_attempt_errors`; reaching the attempt limit leaves the failed story
recorded for inspection. Interrupted pending qualification and temporary
qualification errors, including encoder failures, are also retried, up to three
qualification attempts using the saved body without fetching it again.

## Saved files

The collector writes these files under the chosen output directory:

| File | Contents |
| --- | --- |
| `all_collected_news.json` | Distinct collected stories, including rejected or failed ones, with normalized RSS fields and qualification annotations. |
| `qualified_news.json` | The selected articles in stable order. This is a partial subset while collection is in progress. |
| `collection_state.json` | Authoritative resumable state, including configuration and cached vectors. |
| `collection_report.json` | Progress counts, rejection reasons, errors, dataset hash, and completion status. |
| `.collector.lock` | An OS file lock preventing two collectors from writing the same directory simultaneously. |

A collection is complete only when the report's `complete` flag is true and
`qualified_news.json` contains exactly the configured target. The mere existence
of that JSON file does not mean the target has been reached. Once complete, the
selected dataset and its `dataset_sha256` hash are frozen; rerunning the collector
in that directory preserves them instead of adding later stories.

While collecting, inspect `qualified_count` and `remaining_needed` for progress.
The report's `last_feed_count` shows how many candidates the latest successful
feed check actually supplied. `status_counts` summarizes qualification outcomes,
`rejections` gives article-level reasons, and `poll_errors` records feed or poll
failures. These explain why collected stories may outnumber qualified articles;
failed or rejected stories never fill the target.

The lock uses Unix `flock` and is released when the process exits. A lock file
may remain afterward; the operating-system lock, rather than the file's presence,
determines whether another writer is active. Do not edit the state files while
the collector is running. Retain the entire output directory when moving or
backing up a resumable collection.

## Using the dataset for an experiment

This command prepares data only. It does not reset a database, run FLAN/DeBERTa
inference, or claim that 200 live articles have already been collected. MiniLM
encoding is still performed for novelty qualification.

`qualified_news.json` uses a JSON article-list structure accepted by
`main_pipeline2.py --dataset`. However, that experimental runner currently
selects **100** articles. It can read the completed 200-article JSON file, but
will select/process only 100, not all 200. Updating the experimental runner for
a full 200-article experiment is a separate step.

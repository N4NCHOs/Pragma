# FLAN input-limit comparison — all 73 as-is

Run completed on 25 October 2026 (Asia/Jakarta): **292/292 trials, zero errors**.
All four CSVs passed schema, ID, reference, and integrity-hash validation. Total
execution time was 878.83 seconds (about 14 minutes 39 seconds), including setup
and output work; recorded generation calls totaled 871.61 seconds.

The user explicitly chose all 73 frozen candidates, including six output-pilot
articles and ten description/navigation-limited sources. Existing extraction
flags remain. Inclusion is an experimental cohort decision, not certification
of source completeness or human factual review.

The user's existing GPT silver references are used byte-for-byte unchanged in
the master CSV, SHA-256:
`071492b220b2f0a394300a101a4b549b58f24cae27594f4760e177ceaae9ba06`.
Known review findings for articles 16, 18, 48 and 58 were accepted as-is rather
than corrected. ROUGE/BERTScore therefore measure agreement with references
that retain those limitations, not establish factual accuracy. Exact GPT model,
reference-generation date, and human reviewer remain unrecorded.

## Fixed settings

- Pretrained `google/flan-t5-base`, locally cached revision
  `7bcac572ce56db69c1ea7c8af255c5d7c9672fc2`.
- CPU, float32, four CPU threads; generation seed 0.
- `do_sample=False`, `num_beams=4`, `max_new_tokens=64`,
  `early_stopping=True`, `no_repeat_ngram_size=3`.
- Same frozen source text, approved prompt, article order, and reference at every
  input limit. The six pilot articles are included, not independent holdouts.
- Total prompt input ceilings: **512, 1024, 2048, 3072**. Right truncation matches
  the current service and can remove the trailing `Summary:` cue.

The cached model loader emitted the same tied-weights/config warning seen during
the prior output pilot: both `shared.weight` and `lm_head.weight` are present with
different values and were not tied. No configuration or weights were changed to
silence it. This warning is a reproducibility observation, not by itself a
diagnosis of output correctness.

## Files

- `flan_512.csv`, `flan_1024.csv`, `flan_2048.csv`, `flan_3072.csv`: published only
  after all 292 trials succeed, each with 73 rows and exactly
  `id,title,summary,reference_summary`.
- `selected_articles.json`: the run's exact full sources, references, IDs, pilot
  markers, and source flags. Use this frozen copy for interpretation.
- `prompt_template.txt`: exact task prompt.
- `generation_metrics.json`: per-trial consumed/original input tokens,
  truncation, selected output/EOS audit, generation time, raw summary, and errors.
- `run_manifest.json`: checkpoint status, configuration, expected/completed
  trials, source/reference provenance, and completed CSV integrity hashes.
- `execution_context.json`: written when the execution finishes or raises;
  runtime versions, CPU thread count, seed, source/reference/audit hashes,
  cached generation config, and elapsed time.
- `generation_overview.json`: derived execution/truncation/stop statistics and
  the previous six-article pilot reproduction check; not similarity scores.

## Observed results

Each input limit produced 73 nonempty summaries with the same IDs, titles,
references, and order. All six pilot summaries **and selected token sequences**
match their previous 3072-input/64-output results exactly.

| Total input ceiling | Articles with input truncation | Outputs at 64 without EOS | Mean generation seconds |
| --- | ---: | ---: | ---: |
| 512 | 66/73 | 4/73 | 2.03 |
| 1024 | 28/73 | 2/73 | 3.14 |
| 2048 | 3/73 | 3/73 | 3.42 |
| 3072 | 0/73 | 3/73 | 3.35 |

Across all 292 trials, 280 ended with EOS before the limit and 12 reached 64
without EOS, spanning five distinct articles. Some capped texts visibly end in
unfinished fragments; all raw outputs were retained unchanged. Thus the old
six-pilot result still reproduces, but cannot justify saying 64 always suffices
for this larger cohort. No output setting was changed mid-comparison.

For 31 articles, all four summary strings are identical; for 42, at least one
input limit gives a different string. Neither a difference nor an unchanged
summary establishes which result is better. ROUGE/BERTScore were subsequently
computed in the separate evaluation folder linked below. No manual factuality
or readability rating has been computed.

No warmup was performed. Timing values are single serial observations and
exclude model loading/tokenization, with cold-execution overhead in the first
trial; they are not a controlled latency benchmark. An output reaching the cap
is not automatically proof of an incomplete sentence; inspect the EOS audit and
actual text.

Original pending source audit and manifest are backed up under
`notebook/evaluation_data/flan_reference_package_v1/as_is_decisions/20261025_all73/`
at project root. Master references and frozen article inputs were not rewritten.
No scraper, PostgreSQL, cryptoNER, DeBERTa, or production configuration is part
of this isolated run. ROUGE and BERTScore have now completed as a separate
checkpoint, without rerunning generation, in
[`evaluation_results/scores_20261025_023043_e19f4b6b/`](evaluation_results/scores_20261025_023043_e19f4b6b/README.md).
That folder contains eight separate per-article metric CSVs, a combined means
CSV, and protocol/provenance details. The highest observed ROUGE-1/L and
BERTScore F1 means occur at 2048, with ROUGE-2 tied with 3072; differences are
small and only one summary differs between those two limits. This is descriptive
reference agreement, not proof of statistical significance or factual quality.

`notebook/flan_evaluation.ipynb` now defaults `EXISTING_RUN_DIR` to this completed
folder, with `RUN_GENERATION=False` and `RUN_SCORING=False`. Default execution
only loads/validates/previews the results. Scoring requires
its separate `RUN_SCORING=True` opt-in and the separate ROUGE/BERTScore cells.
Do not manually edit a comparison CSV: integrity checks will detect changes.

To reproduce the CPU runtime choice in a new run, set `DEVICE_NAME="cpu"` and
`torch.set_num_threads(4)` before generation. The module sets seed 0 internally.
Retain the same pinned revision, prompt, source/reference hashes, and versions.

## Validation and changed files

Two independent read-only checks confirmed all four CSVs, 292 metric pairs,
source/prompt/reference hashes, settings, six retained pilots, and exact pilot
reproduction. All 175 relevant offline tests passed. The updated notebook's
seven code cells compile and were executed from both project root and notebook
folder with model/scoring/database imports blocked; all four saved datasets
loaded, and generation/scoring remained off. CSV previews were also inspected.

Created files are the eleven run files listed above (including this README and
the derived overview). Outside this run, the only changes for this execution are:

- Package `source_audit.csv`: 73 authorized `include` decisions and explicit
  as-is notes, with original identities/flags preserved.
- Package `manifest.json`: as-is decision and provenance limitations; unknown
  GPT model/date/reviewer fields remain blank.
- Package `as_is_decisions/20261025_all73/`: original audit/manifest backups
  plus `decision.json` documenting the authorization and hashes.
- `notebook/flan_evaluation.ipynb`: select this completed run by default;
  generation/scoring switches stay off and notebook outputs stay cleared.
- `FLAN_EVALUATION_PLAN.md`, `FLAN_REFERENCE_WORKFLOW_README.md`, and
  `FLAN_64_TOKEN_JUSTIFICATION_README.md`: record the completed checkpoint and
  larger-cohort output-cap limitation.
- Graphify's AST outputs were refreshed; no LLM/API was used. SQL extraction
  remained skipped because `tree_sitter_sql` is absent; no dependency installed.

The GPT reference CSV, frozen article text/prompt, FLAN module, production
pipeline, scraper, database, and existing unrelated outputs were not changed.
Realtime integration of `article_preprocessing.py` remains high-priority pending.

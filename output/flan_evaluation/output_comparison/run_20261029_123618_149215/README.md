# FLAN output-budget comparison: fixed input 3072

Completed **29 October 2026 (Asia/Jakarta)**. All 73 frozen articles were compared
at output ceilings 64, 96, and 128. The 96/128 conditions comprise **146 fresh
generations**, all successful. The 73 output-64 results are reused from the
preserved input-3072 baseline, with two additional exact 64-token canary replays
before the fresh trials. The canaries are checks, not additional evaluation rows.

## Observed output-limit counts

| Maximum new output tokens | Articles | EOS before ceiling | Ceiling reached without EOS | Rate | Input truncation | Errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 64 (historical baseline) | 73 | 70 | 3 | 4.11% | 0 | 0 |
| 96 (new) | 73 | 72 | 1 | 1.37% | 0 | 0 |
| 128 (new) | 73 | 73 | 0 | 0.00% | 0 | 0 |

There were no EOS-at-ceiling, forced-EOS-at-ceiling, or unexpected-stop cases.
The earlier 12/292 count pooled four **input** limits; it is not the correct
64-token comparison here. At input 3072, that original count is 3/73.

Here, “ceiling reached without EOS” means the **selected generated sequence**
reached its budget without the model's end-of-sequence token. It is the measured
output-limit indicator, not an automatic factuality or sentence-quality judgment.
Decoder-start and beam padding are excluded; EOS consumes one new-token slot.
Global beam-search iteration counts are retained separately and do not determine
the selected-output limit count.

## The three previously capped articles

| Article | 64 | 96 | 128 |
| --- | --- | --- | --- |
| CME’s bitcoin cash, uniswap futures, global PMIs: Crypto Week Ahead | 64 tokens, no EOS | 88 tokens including EOS | 88 tokens including EOS |
| Strategy's price chart is about to flash a major bullish signal weeks after bitcoin did | 64 tokens, no EOS | 93 tokens including EOS | 93 tokens including EOS |
| Live updates: Bitcoin’s round trip to $85,000 burns traders on both sides | 64 tokens, no EOS | 96 tokens, no EOS | 96 tokens including EOS |

The remaining 96-token case is article
`01631d1ddee666a7e3cde6b2de96807309b487dae11a154020adc7bf0b3decff`.
Its 96-token output ends with the unfinished word sequence **“About”** after
three sentences. The 128-budget output ends after the preceding complete sentence
with EOS. The selected output has 95 content tokens plus EOS, despite a ceiling
of 128. A ceiling is not a target length. Different ceilings can change beam
finalization/selection; this is not simply appending tokens to the old text.

All **72 other summary strings are identical between 96 and 128**. Each new
configuration changes three summary strings relative to 64: the three articles
listed above. Maximum selected new-token counts, including EOS when present,
are 64, 96, and 96 respectively. Mean content-token counts are approximately
33.95, 35.08, and 35.07 respectively.

## Interpretation limits

Within these 73 cases, 128 is the only tested output ceiling with **zero
limit-without-EOS cases**. This does not establish a universal minimum, optimal
budget, factual correctness, or compliance with the 1–2-sentence goal.

In particular, the Bitcoin live-updates output at 128 contains three sentences.
The Strategy output at both 96 and 128 still includes newsletter text and an
ellipsis-ending explanation. Thus, allowing EOS resolves the measured ceiling
condition but does not resolve all source selection, clarity, or task-adherence
problems. No formal rubric, ROUGE, BERTScore, or training was added to this run.
No production output setting has been selected or changed from these observations.

## Fixed protocol and preserved data

- Pretrained `google/flan-t5-base`, revision
  `7bcac572ce56db69c1ea7c8af255c5d7c9672fc2`, local cache only, offline.
- Same approved prompt, frozen article text/IDs/order, references, and six pilot
  membership flags as the original 73-article run. All accepted source/reference
  limitations are retained, including the limited-source cases.
- Total input ceiling **3072**. Actual complete input tokens match the original
  baseline for every article; the largest input is 2278. None was truncated.
- `do_sample=False`, `num_beams=4`, `early_stopping=True`,
  `no_repeat_ngram_size=3`; only `max_new_tokens` changes.
- CPU float32, four CPU threads, seed 0, Torch 2.13.0, Transformers 5.14.1.
  Model and tokenizer were each loaded once. No forced EOS was configured.
- Both an earlier-EOS and an earlier-capped 64-token case were regenerated;
  selected token IDs and decoded text match their historical baseline exactly.
- Existing `inspect_selected_sequence` performs the EOS/beam-ancestry audit.
  All trial results are checkpointed as readable JSON.

The loader emitted the same shared/lm-head tied-weight warning as the original
baseline. Configuration and weights were retained; the exact canary reproduction
checks passed. Recorded elapsed execution was 500.34 seconds (about 8m20s),
including setup, canaries, generation, and checkpoints. Historical 64 timings
are not comparable as a controlled latency benchmark.

## Files and reproduction

- `run_report.json`: runtime configuration, provenance, source hashes, progress,
  per-budget stop counts, and summary-change counts.
- `generation_metrics.json`: 219 article-condition records, with raw summaries,
  references, selected token IDs, EOS flags, input/output counts, and provenance.
- `summaries_output_64.json`: 73 historical baseline records.
- `summaries_output_96.json`, `summaries_output_128.json`: 73 fresh records each.
- `previously_capped_cases.json`: full 64/96/128 outputs for the three old cases.
- `canary_64_replays.json`: two matching 64-token control regenerations.
- `selected_articles.json`, `prompt_template.txt`: frozen input/reference/prompt copy.
- `verification_report.json`: independently reconstructed stop categories,
  identity/reference checks, exact old-row reproduction, and artifact hashes.

From project root, using the project environment:

```bash
python run_flan_output_comparison.py
```

The default creates a new timestamped directory. `--output-dir <new_folder>`
can select a fresh location; an existing destination is refused. An interrupted
run keeps its checkpoints, but automatic resume is not implemented. Importing
the runner does not load model weights or execute inference.

Model-free tests:

```bash
python -m unittest scratch.test_flan_output_comparison scratch.test_flan_output_pilot scratch.test_flan_reference_workflow -q
```

The eight new integrity/aggregation tests and 96 existing helper/workflow tests
passed. Completed-result checks confirm exact IDs/order/references, selected
token/EOS categories, zero input truncation, two matching canaries, and unchanged
checksums of original baseline run files and the model source. The original
baseline and its archived snapshot remain intact.

This experiment adds a standalone runner and tests, its result directory, and a
checkpoint note in `FLAN_EVALUATION_PLAN.md`. It does not execute the database,
scraper, main pipeline, cryptoNER, or DeBERTa. **High-priority pending:** realtime
integration of `article_preprocessing.py` remains a separate unfinished task.

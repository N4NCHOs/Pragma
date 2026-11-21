# Agreed FLAN evaluation checkpoints

Updated: 2026-10-30 (Asia/Jakarta).

## Paket bukti pemilihan input dan output — 2026-10-30

Pengguna meminta bukti sebelum menerapkan kandidat output 128, termasuk teks
input dan keluaran tiap artikel untuk mendukung penjelasan di outline.
Paket selesai di
[`laporan bukti 3072 dan 128`](output/flan_evaluation/token_selection_evidence_20261030/README.md),
dengan indeks dan lampiran seluruh 73 artikel, prompt mentah, rekonstruksi
input 512/1024/2048/3072, keluaran historis pada keempat input (output 64), dan
keluaran 64/96/128 pada input 3072. Arsip lengkap:
[`token_selection_evidence_20261030.zip`](output/flan_evaluation/token_selection_evidence_20261030.zip).

Seluruh teks sumber/prompt/rujukan dan keluaran dicocokkan dengan file beku;
292 kondisi token input dan 219 tampilan kondisi output terverifikasi (73
kondisi input3072/output64 muncul pada kedua perbandingan). Teks/token encoder
diberi label sebagai rekonstruksi tokenizer, bukan tensor yang direkam saat
inferensi lama. Tidak ada inferensi baru atau perubahan sumber/run baseline.

Dasar keputusan tetap dibatasi pada bukti: 3072 menjaga seluruh input yang
tersimpan pada cohort ini; 128 merupakan batas output terkecil di antara yang
diuji dengan nol kasus mencapai batas tanpa EOS. Skor 2048 sedikit lebih tinggi,
sementara 128 belum dinilai ulang dengan ROUGE/BERTScore dan belum memenuhi
seluruh sasaran 1–2 kalimat. Paragraf untuk diadaptasi ke outline tersedia dalam
laporan. Input3072 sudah disepakati; output128 masih kandidat yang sedang
ditinjau berdasarkan bukti, dan default service belum diubah.


## Keputusan input tetap untuk eksperimen berikutnya — 2026-10-29

Pengguna mengonfirmasi **`max_input_tokens = 3072`** sebagai batas input tetap
untuk eksperimen FLAN berikutnya, sebelum menentukan batas output. Tujuannya
adalah menyediakan seluruh input pada cohort saat ini agar pengujian batas
output tidak disertai pemotongan input.

Bukti dari baseline: 3072 memuat seluruh 73 input tanpa truncation; input penuh
terpanjang adalah **2278 token**, termasuk prompt dan token khusus. Pada 2048,
tiga input terpotong. Rata-rata skor 2048 sedikit lebih tinggi, tetapi 72/73 teks
ringkasan identik dengan 3072. Pemilihan 3072 didasarkan pada kelengkapan input
untuk pengujian output, bukan klaim bahwa skor atau kualitasnya selalu terbaik.

Batas ini adalah maksimum, bukan panjang wajib setiap artikel. Kecukupannya
perlu diukur kembali jika artikel, prompt, atau tokenizer berubah. Tetapkan
sumber, prompt, dan pengaturan lain selama membandingkan batas output.

Keputusan ini berlaku untuk rancangan eksperimen selanjutnya. Batas output
96/128 kini telah diuji pada cohort penuh sebagaimana checkpoint di bawah;
konfigurasi output final belum dipilih. Catatan ini tidak mengubah default service,
notebook perbandingan empat input, paket beku, maupun hasil/snapshot baseline.

## Pengujian output 96/128 selesai — 2026-10-29

Dengan input tetap 3072, seluruh 73 artikel dari baseline diuji pada output 96
dan 128: **146 generation baru, tanpa error atau input terpotong**. Hasil output
64 diambil dari 73 baris baseline input 3072, bukan menggabungkan empat input.
Dua canary 64 (satu kasus EOS dan satu kasus mencapai batas) menghasilkan teks
serta urutan token yang persis sama sebelum percobaan baru dimulai.

| Batas output | Artikel | Mencapai batas tanpa EOS | EOS sebelum batas |
| --- | ---: | ---: | ---: |
| 64, baseline lama | 73 | 3 | 70 |
| 96, generation baru | 73 | 1 | 72 |
| 128, generation baru | 73 | 0 | 73 |

Kasus yang masih mencapai batas 96 adalah “Live updates: Bitcoin’s round trip
to $85,000 burns traders on both sides”; keluarannya berhenti pada kata “About”.
Pada batas 128, model memilih keluaran yang berakhir dengan EOS (96 token baru
termasuk EOS). Ringkasan 96 dan 128 sama pada 72 artikel lainnya. Kedua batas
mengubah tiga ringkasan dibandingkan baseline 64.

128 menghilangkan kondisi mencapai batas tanpa EOS pada cohort ini, tetapi
belum membuktikan seluruh ringkasan sesuai tujuan. Keluaran Bitcoin tersebut
masih tiga kalimat; kasus Strategy masih memuat pengantar newsletter/ellipsis.
EOS bukan jaminan kelengkapan makna, faktualitas, atau kepatuhan 1–2 kalimat.
Tidak ada scoring ROUGE/BERTScore baru atau fine-tuning pada tahap ini.

Runner: `run_flan_output_comparison.py`; delapan tes baru pada
`scratch/test_flan_output_comparison.py` dan 96 tes helper/workflow lulus.
Hasil lengkap dan protokol:
[`README perbandingan output`](output/flan_evaluation/output_comparison/run_20261029_123618_149215/README.md).
Seluruh hasil/rujukan/prompt lama dan snapshot baseline dipertahankan; default
produksi belum diubah. Pilihan budget final menunggu pembahasan hasil.


## Baseline dipertahankan sebelum perbaikan — 2026-10-27

Pengguna meminta hasil eksperimen ini disimpan sebagai temuan sebelum mengubah
kode FLAN. Catatan utama: [`FLAN_BASELINE_DISCOVERY_001.md`](FLAN_BASELINE_DISCOVERY_001.md).
Pertahankan hasil 73 artikel/292 generation, empat batas input, output 64,
seluruh referensi GPT, dan skor sebagai baseline. Simpan eksperimen perbaikan
berikutnya dalam run baru, bukan menimpa atau memperbaiki keluaran baseline.
Temuan output yang wajib ikut dilaporkan: **12/292 kondisi mencapai 64 token
tanpa EOS, mencakup lima artikel**, distribusi 4/2/3/3; sebagian teks terlihat
belum selesai, tetapi status tanpa EOS bukan audit kelengkapan kalimat untuk
semua kasus. Snapshot dan checksum dirujuk dari catatan discovery tersebut.

## Status checkpoint

Current status: baseline inspection, frozen footer-cleaned snapshot, tokenizer
preflight, six-article output-budget pilot, manual GPT-reference preparation,
four-limit generation, and **ROUGE/BERTScore scoring are complete**. The user
approved all **73 articles including the six pilots** and all existing GPT silver
references as-is. All 29 source-review flags remain; none caused automatic exclusion.
Generation used the same deterministic **64-new-token baseline** at every input limit.

The notebook joins fixed references by ID and has separate, opt-in generation,
ROUGE, and BERTScore stages. Both notebook execution switches default to False.
The user has supplied all 73 GPT silver references and explicitly requests using
them as-is, without the suggested corrections. The user also confirmed retaining
all 73 articles, including the ten description/navigation-limited sources. That
inclusion decision is recorded; it is not a claim of completed human source-
quality review. Exact reference-generation model/date/reviewer are unrecorded.
The four-limit comparison has completed independently on CPU, with four threads
as in the pilot: **292/292 trials, zero errors**, and four verified CSVs with
73 records each. Scoring produced eight per-article metric CSVs plus one comparison
CSV, with separate ROUGE and BERTScore results. Production code/settings are unchanged.

## 2026-10-25 — keep user references as-is

The user chose to continue with the existing reference summaries rather than
revise the audit findings for articles 16, 18, 48 and 58. Do not silently edit,
replace or regenerate those summaries. The accepted current CSV SHA-256 is
`071492b220b2f0a394300a101a4b549b58f24cae27594f4760e177ceaae9ba06`.
Similarity scores will measure agreement with these references, including their
known limitations, not establish factual accuracy or human-gold quality.

Read-only preflight confirms all 73 references have unique matching IDs and
unchanged titles/source text. The current model source, prompt, pinned revision,
and deterministic 64-token generation settings match the frozen package. A
full 73-article input comparison was planned as 292 generations at
512/1024/2048/3072 input tokens. This preflight preceded the completed run below.

The user subsequently explicitly chose "Gunakan seluruh 73 artikel apa adanya."
All source decisions are now `include`, with notes identifying this as the
user's experimental cohort decision rather than certified human source-quality
approval. Original pending audit and manifest were backed up under
`notebook/evaluation_data/flan_reference_package_v1/as_is_decisions/20261025_all73/`.
Extraction flags and the reference CSV remain unchanged. The existing readiness
check passes normally for all 73; no validation gate was removed or bypassed.
Do not invent missing GPT provenance metadata.

The real input-comparison run completed in
`output/flan_evaluation/input_comparison/run_20261025_012611_as_is_39b89baf/`.
It used one locally cached model/tokenizer, CPU float32, four CPU threads, and
seed 0. All 292 trials succeeded and four 73-row comparison CSVs were published
and checked against the exact frozen IDs, titles, order, and GPT references.
Total execution time was 878.83 seconds. No warmup was performed; timings are
single observations, not a latency benchmark. Generation checkpoints are retained,
but the current runner does not automatically resume interrupted trials.

Input truncation counts at 512/1024/2048/3072 are **66/28/3/0 out of 73**.
Twelve outputs reached the 64-token ceiling without EOS (4/2/3/3 by input limit),
spanning five articles. Some are visibly unfinished. All raw outputs are kept;
the output budget was not changed mid-experiment. All six prior pilot64 summaries
and token sequences reproduce exactly at input 3072, so the larger-cohort ceiling
findings do not contradict the earlier six-case observation, but limit its
generalization. Thirty-one articles have identical summary strings at all four
limits; 42 differ at least once. No quality ranking follows from this alone.

The notebook selects this completed run by default with generation and scoring
still disabled. Both metrics were subsequently computed from the saved CSVs;
FLAN was not regenerated and the GPT references were not changed.

## Completed scoring — 2026-10-25

Results are inside the completed generation run at
`evaluation_results/scores_20261025_023043_e19f4b6b/`.
Each of the four input-limit folders contains separate 73-row ROUGE and
BERTScore CSVs; `input_limit_comparison.csv` contains their means. The result
README documents interpretation, and `scoring_report.json` records settings,
versions, checkpoint revision, input hashes, and output hashes.

| Input ceiling | ROUGE-1 F1 | ROUGE-2 F1 | ROUGE-L F1 | BERTScore F1 |
| --- | ---: | ---: | ---: | ---: |
| 512 | 0.3212 | 0.1326 | 0.2517 | 0.8832 |
| 1024 | 0.3344 | 0.1464 | 0.2600 | 0.8831 |
| 2048 | 0.3442 | 0.1472 | 0.2677 | 0.8852 |
| 3072 | 0.3428 | 0.1472 | 0.2672 | 0.8847 |

ROUGE uses stemming. BERTScore uses cached `roberta-large`, layer 17, English,
CPU, batch 4, no IDF, and no baseline rescaling; no scorer input was truncated.
The 2048 configuration has the highest observed ROUGE-1/L and BERTScore F1;
ROUGE-2 ties 3072. Only one summary changes between 2048 and 3072. These small,
descriptive differences do not establish statistical significance or universal
optimality. BERTScore 0.8852 does **not** mean 88.52% factual accuracy.

All nine CSVs passed exact-value/schema/ID checks and independent verification.
All 175 offline tests passed; default notebook execution was verified from root
and notebook folders without importing generation/scoring/database models.
The next research checkpoint is source-based review of factuality, beginner
readability, and output-ceiling failures before choosing a production setting.
Do not silently alter the prompt, references, cohort, or output budget.

## Confirmed decision — include the six pilot articles

The user explicitly accepts including the six pilot articles in the subsequent
evaluation. Audit the entire frozen pool of **73 candidate articles**, including
those six; do NOT automatically exclude them or start from only 67 candidates.
Apply the same content-quality criteria to every article. No article was removed
by this decision. The later package adds review observations only; final include/
exclude decisions remain with the user.

Retain a pilot-membership marker in future evaluation audit/results metadata
for transparency. A separate held-out set or separate pilot/nonpilot score
reporting is not required by this decision. Combined exploratory comparisons
are allowed on the same eligible articles and fixed references across all input
limits. Disclose that six cases also informed output-budget selection; do not
describe the combined set as fully independent held-out validation.

Dataset JSON and existing experiment artifacts remain unchanged. Final article
count depends on the quality audit and the user's review, not on pilot status.

## HIGH PRIORITY — pending realtime integration

The user explicitly marked this follow-up as high priority: reuse the existing
`article_preprocessing.py` footer-cleaning function in the realtime flow used by
`main_pipeline.py`. It is currently implemented/tested for the evaluation copy
only and is **NOT integrated into production**. Integration guidance is in
`FLAN_PREPROCESSING_README.md`. Keep this item pending until the user asks to
implement it and the production integration is verified; this note does not
authorize changing the pipeline now.

## Scope

- Use the qualified article JSON in `output/rss_dataset_recovered/`.
- The last user-reported count was 66 qualified articles; verify the actual count
  before freezing an experiment snapshot. Do not silently change the cohort.
- Preserve article IDs, text, and order. Continued RSS collection must not alter
  an existing experiment snapshot.
- Use the exact current FLAN prompt and checkpoint; inspect and record them at
  execution time rather than assume an earlier chat version is implemented.
- This is pretrained inference evaluation, not model fine-tuning.
- Do not run scraping, PostgreSQL resets, cryptoNER, or DeBERTa for this study.

## 1. Prepare and run an output-budget pilot FIRST

Before running models, agree on the pilot size and article IDs. Include examples
with different lengths and technical complexity, important names, and numbers.
The initial suggestion of a separate development subset was optional. The user
subsequently chose to include the six pilot articles in the evaluation pool;
see the confirmed decision above.

Keep the prompt, checkpoint, input ceiling, and other generation settings fixed.
Verify that the complete prompt plus source article fits the chosen pilot input
ceiling so input truncation cannot confound the output-budget test. Do not assume
3,072 tokens will fit every article without measuring.

Proposed output ceilings: 64, 96, and 128 new tokens. These are ceilings, not
requested summary lengths. Record normal end-of-sequence stopping versus the
generation ceiling, token counts, and sentence completeness. Hitting a ceiling
alone does not establish that a sentence is incomplete. Also inspect factuality,
preservation of key details, and the 1–2-concise-sentence requirement.

## 2. Lock one output configuration

Choose an output ceiling based on the pilot, then keep it and all other generation
settings identical for every input-length configuration. The prepared workflow
uses the current 64-new-token baseline supported by the pilot; this is not a
claim of universal optimality. Do not vary input and output limits together.

## 3. Prepare fixed ChatGPT silver references

Prepare a CSV matching each frozen article ID to its exact model-input text.
Generate references manually, independently of FLAN outputs, with the same prompt
and complete source text. Use the same 1–2-sentence task requirement, but do not
claim identical output lengths or enforced token budgets across tokenizers.

Record the reference model, generation date, and factual-review status. Check
names, numbers, uncertainty, and unsupported claims. These remain AI-generated
silver references, even if reviewed by a human. Use one fixed reference per
article for every input-length configuration.

## 4. Compare FLAN input ceilings

Compare 512, 1,024, 2,048, and 3,072 input tokens on the same frozen evaluation
articles using the locked output settings. Record original and consumed input
tokens (including the prompt), input truncation, output tokens, summary lengths,
and inference time. Preserve separate outputs per configuration.

## 5. Score and interpret

Report ROUGE-1, ROUGE-2, and ROUGE-L separately from BERTScore precision, recall,
and F1. Keep per-article scores and configuration averages, matched by article ID.
Similarity to a silver reference is not proof of factual accuracy or beginner
readability; include source-based review and state the silver-reference limitation.

## Decisions still open

- Source-based factuality/readability review of the completed outputs. The
  current cohort is already fixed at all 73 as-is; do not reopen inclusion or
  silently exclude flagged articles for the reported comparison.
- Whether broader source-based review reveals output truncation or quality
  failures beyond the six pilot cases; 64 is the prepared comparison baseline,
  not a universal guarantee.
- Whether to keep the current prompt as the baseline despite observed
  extractive copying and incomplete beginner-language/context adherence. Do not
  change the approach or prompt without the user's approval.
- Exact GPT model/version and manual reference-generation dates/reviewer,
  recorded in the package's reference_provenance metadata.

Next manual checkpoint: inspect the generated outputs against their frozen
sources, especially the 12 output-ceiling cases and the one summary that changes
between 2048 and 3072. Existing source decisions and GPT references are accepted
as-is for this experiment. Workflow details are in `FLAN_REFERENCE_WORKFLOW_README.md`.

## Point 1 findings — 2026-10-24

Source: `output/rss_dataset_recovered/qualified_news.json`.

- Current inspected qualified count: **73**, increased from the previously
  reported 66. The collection report shows 113 total collected and target 200;
  collection is still incomplete and may continue updating the source file.
- All 73 inspected records have a nonempty title, full body, and article ID.
  No repeated article IDs or URLs were found. All are marked qualified and
  `is_redundant=false`. This checks stored flags, not a fresh novelty evaluation.
- No evaluation cohort has been selected or frozen yet.

Current code in `ai_models/flan_t5.py`:

| Setting | Observed value |
| --- | --- |
| Checkpoint | `google/flan-t5-base` |
| Default maximum input tokens | `512` |
| Maximum new output tokens | `64` |
| Sampling | `do_sample=False` |
| Beams | `num_beams=4` |
| Early stopping | `True` |
| No-repeat n-gram size | `3` |

**Prompt decision resolved:** the user said to use the current prompt, which they
edited. A fresh read confirms beginner-friendly jargon rephrasing, preservation
of uncertainty and attribution, explicitly stated consequences only, and no
investment advice or price predictions. Use this current on-disk prompt exactly;
do not replace it with an earlier chat version. The user's edit to
`ai_models/flan_t5.py` is preserved.

Point 1 changed this planning note only; no model or data files were modified.

## Point 2 — proposed output-budget pilot

The source still contains 73 records at this inspection. This is a purposeful
six-article stress-test proposal, not a random or statistically representative
sample. No subset or evaluation snapshot has been written. Selection uses stable
`dataset_article_id` values, not row positions, so collection can continue.

Pre-cleaning word counts below are whitespace counts of `title + ". " + full_body`, matching
the current pipeline's source-text construction. They include repeated source
headings and scraper text, exclude the FLAN instruction prompt, and are **not
token counts**. Exact tokenizer counts belong to the next point.

| Article | Words | Why include it |
| --- | ---: | --- |
| Bitcoin ETFs just saw their biggest day in a month thanks entirely to BlackRock | 266 | Short financial report; distinguish total inflows from one fund's inflows and retain the correct names/numbers. |
| Tether leads $15 million funding round for AI-focused payment startup Mural | 344 | Short corporate event; distinguish this funding round from total funding and explain agentic finance simply. |
| Ethereum delays Glamsterdam test after security devs flag risk to existing contracts | 578 | Technical security report; simplify gas/smart-contract jargon without claiming an exploit is already happening. |
| Ethereum's four-minute settlement plan could lower the cost of moving crypto | 629 | Technical proposal with stated consequences; retain proposed versus implemented status and important timing figures. |
| Satoshi-era bitcoin faces a bigger quantum threat after Google's new Willow breakthrough | 1,075 | Long technical report; test concise explanation of cryptography and future-risk uncertainty. |
| OCC's final rule to start fresh in weighing stablecoin rewards against GENIUS Act ban | 1,403 | Long regulatory report; test accurate attribution and distinctions between proposals, restrictions, and settled rules. |

Stable IDs in the same order:

1. `d88ecdbfd283769b367268dc7b7c14f411851af8ea5ea97875a08925af8bf1d4`
2. `5c5fbb2ad4e363114002acb9a7ece8d2de59b94151909d7e1cbd82c0b33d90ac`
3. `269a4ac2559e1cc75c9fa61e579a0f0daa4e465ae57413d703fa7e90f07cae76`
4. `544307a0609c50dd807ec9a6888fdce4ccfa2b63d79499f6e5fed5ce82b47fdf`
5. `78adaf032c25de397f75d390ed0ebe2299a8c3ba73b16f54633d6d2d19c94817`
6. `8b38d00ac6012f9c741d1e711f04aea939463019d0f2ea72ad3e9d4774c5c331`

### Source-quality issues to resolve before freezing

- Five records contain fewer than 100 whitespace words of constructed source
  text (46–60 words), consisting mainly of a title, short description, and
  sharing controls rather than a full narrative. They are not proposed for this
  core pilot; a nonempty `full_body` is not proof of a complete article.
- 62 of 73 records, including these six candidates, contain the same unrelated
  promotional footer beginning `Diversified RWA stablecoins sustain 5-7% yield`
  and end with a dangling `Why it matters:` heading. Some other records also
  contain clipped sentences. These are source extraction issues, not FLAN output
  truncation. The six candidates have substantive narratives, but are not being
  certified as complete or perfectly clean scrapes.
- The longest entry (the Crypto for Advisors newsletter) is not proposed: it
  combines multiple sections, a Q&A, subscription material, and a roundup rather
  than one focused news event.
- At the initial point 2 inspection, no source text had been cleaned or changed.
  The user subsequently authorized removal of only this identified repeated
  footer in a separate evaluation copy; the completed follow-up is recorded
  below. Preserve the original JSON and use the same cleaned source for FLAN
  inputs and silver-reference inputs.
- Pilot membership was initially undecided; the user later confirmed including
  these six in the full 73-article candidate pool. No automatic 67-article-only
  cohort is used; the final eligible cohort still requires quality audit.

After approval: freeze the chosen source text and current prompt, count complete
prompt-plus-article inputs with the actual FLAN tokenizer, and choose an input
ceiling that fits the pilot before testing 64/96/128 output ceilings. Do not
assume 3,072 tokens is sufficient without measuring.

Point 2 changed this planning note only. No pipeline/model code or dataset files
were modified, and no tokenization, generation, or scoring was run.

## Point 2 follow-up — authorized footer cleanup completed

The user approved a separate evaluation copy plus reusable preprocessing and
documentation. This is a refinement of the thesis's residual-web-noise Regex
stage, not a replacement for trafilatura, pagination cleanup, or line deduplication.

Implementation:

- `article_preprocessing.py`: dependency-free, reusable text function and audit
  result. Requires the entire exact promotional paragraph plus empty following
  heading at the end; removes only that suffix and its line separator. No broad
  `yield`/number matching, text rewriting, or generic whitespace stripping.
- `prepare_flan_evaluation_data.py`: optional no-write preview, single-read raw
  snapshot, cleaned copies, provenance hashes and removal audit. Existing output
  directories are refused. No models, network, database, filtering, or novelty
  evaluation is invoked.
- `scratch/test_article_preprocessing.py` and
  `scratch/test_prepare_flan_evaluation_data.py`: 49 offline unit tests.
- `FLAN_PREPROCESSING_README.md`: rules, commands, output format, limitations,
  and proposed upstream realtime integration, which is NOT applied yet.

Created snapshot:

`output/flan_evaluation/preprocessed_v1_20261024/`

1. `qualified_news_raw.json` — byte-identical source snapshot.
2. `qualified_news_cleaned.json` — all records retained; only matching
   `full_body` values changed.
3. `preprocessing_report.json` — completed report, rule version, counts, hashes,
   and per-article audit metadata.
4. `changes.json` — exact removed suffixes and before/after tail previews.

Actual run: **73 retained, 62 changed, 11 unchanged, 0 empty after cleaning**.
Source file SHA-256:
`4f53b991ba282954b9b94379269bd2cf9986c0f949ff550f4da41cac077bbc88`.
The live source was verified unchanged at the post-run check. Article order,
stable IDs, and every other field were verified preserved, including original
qualification/novelty decisions. Those decisions were NOT recomputed on cleaned
text. No article was excluded or automatically repaired.

Validation: **123 offline tests passed** across the 49 new tests plus existing
collector/experimental-pipeline tests. Snapshot hashes, exact removal
reconstruction, retained field equality, and idempotence were also checked
against the real dataset.

No changes were made to the FLAN prompt/model, production pipeline, RSS
scheduler/collector, or database by this work. The user's existing edit to
`ai_models/flan_t5.py` was left untouched. Other scrape-quality limitations
remain; this snapshot is not certification that all 73 are complete articles.
The proposed pilot and final evaluation cohort still require confirmation.

## Point 3 — actual FLAN tokenizer preflight completed

User authorized the next checkpoint. Measured the six pilot candidates from the
existing frozen cleaned snapshot, not the live collector. The saved prompt is
the exact current `SUMMARY_PROMPT` read from `ai_models/flan_t5.py`; no rewrite
was made. Used the actual cached tokenizer for `google/flan-t5-base`, pinned to
revision `7bcac572ce56db69c1ea7c8af255c5d7c9672fc2`, with local-only loading.

Each count tokenizes the complete formatted input in one call:

`SUMMARY_PROMPT.format(article_text=(title + ". " + full_body).strip())`

Special tokens are included. Counts are not word estimates and do not assume
separate prompt/title/body token counts are additive.

| Pilot article | Complete input tokens |
| --- | ---: |
| BlackRock / Bitcoin ETF inflows | 597 |
| Tether / Mural funding | 627 |
| Ethereum Glamsterdam test delay | 931 |
| Ethereum four-minute settlement proposal | 987 |
| Bitcoin / Google quantum research | 1,508 |
| OCC / stablecoin rewards rule | 2,071 |

Actual capped tokenization was also measured at all four desired limits:

| Input ceiling | Complete inputs without truncation | Truncated inputs |
| --- | ---: | ---: |
| 512 | 0/6 | 6/6 |
| 1,024 | 4/6 | 2/6 |
| 2,048 | 5/6 | 1/6 |
| 3,072 | 6/6 | 0/6 |

Recommendation: **3,072 for the output-budget pilot only**, the smallest of the
four planned ceilings that fits all six. The longest input exceeds 2,048 by 23
tokens. Setting a ceiling does not pad every article to that length; individual
unpadded consumed lengths remain as measured. Other/current/future articles
are not guaranteed to fit this ceiling.

Important limits and findings:

- Tokenizer metadata reports `model_max_length=512`, with right truncation.
  This measurement does not establish long-input model feasibility, memory use,
  or summary quality. Those require the next inference checkpoint.
- The current service truncates the entire formatted prompt from the right.
  All measured truncated cases also lose the final `Summary:` cue. This is
  preserved and documented as current behavior, NOT silently corrected. Decide
  how to handle this potential comparison confound before the later input-limit
  study; it does not arise in an untruncated output-budget pilot.
- No weights were loaded and no inference, reference generation, model scoring,
  database operation, or RSS collection was run. The default production input
  limit remains 512 and generation remains max_new_tokens=64.
- Realtime preprocessing integration remains **HIGH PRIORITY / PENDING**.

Files added in this checkpoint:

- `measure_flan_pilot_tokens.py`: reproducible token-only script, AST-based
  literal prompt/config reading without executing the production module, frozen
  snapshot hash validation, stable-ID selection, pinned local tokenizer, and
  exclusive output directories. This is not the later inference runner or a
  decision between notebook/script for the full evaluation.
- `scratch/test_flan_pilot_tokens.py`: 30 offline tests with a fake tokenizer for
  software boundaries only; the reported real article counts use the real
  cached FLAN tokenizer, not the fake tokenizer.

Output: `output/flan_evaluation/pilot_tokens_v1_20261024/`

1. `token_report.json` — per-article complete/capped counts, truncation, decoded
   tails, baseline generation settings, tokenizer versions/revision, and hashes.
2. `pilot_inputs.json` — the six exact cleaned articles and actual source/input
   strings, preserving stable IDs for the later pilot.
3. `prompt_template.txt` — the unchanged current prompt as measured.

Rerun in the project environment with a NEW output directory (existing output
directories are refused):

```bash
.venv/bin/python measure_flan_pilot_tokens.py --output-dir output/flan_evaluation/pilot_tokens_v2
```

Report/input hashes, exact formatting, preserved IDs, actual truncated lengths,
and final-cue behavior were independently checked against the saved artifacts.
Validation: **153 offline tests passed**, including the 30 new token-preflight
tests and the existing preprocessing/collector/experimental-pipeline tests.

## Point 4 — output-budget pilot completed

User authorized continuation. Ran the six frozen inputs at output ceilings
64/96/128, holding input limit 3,072, prompt, checkpoint/revision, and the other
generation settings fixed. Actual input lengths matched preflight in every
trial, with no truncation. Local cached model/tokenizer loaded once; CPU,
float32, torch.inference_mode(), deterministic four-beam search, and no sampling.
No fallback to another checkpoint/device/dtype or production modification.

Output directory: `output/flan_evaluation/output_pilot_v1_20261024/`.

- `results.json`: 18 model outputs with times, original/consumed input counts,
  content/new-token counts, EOS position, beam-derived selected token IDs,
  search iterations, stop reason, and error status.
- `run_report.json`: completed run, pinned revision/environment/config/hash and
  aggregate results. Includes separate load/warmup timing.
- `pilot_inputs.json`, `prompt_template.txt`, `preflight_report.json`: unchanged
  input/prompt/provenance copies.
- `review.md`: AI-assisted qualitative source-based review, not a human gold
  evaluation, factual verification of news, or ROUGE/BERTScore.

| Output ceiling | Successful trials | EOS before ceiling | Selected output at ceiling | Mean content tokens |
| --- | ---: | ---: | ---: | ---: |
| 64 | 6/6 | 6/6 | 0/6 | 31.5 |
| 96 | 6/6 | 6/6 | 0/6 | 31.5 |
| 128 | 6/6 | 6/6 | 0/6 | 31.5 |

Per article, all three summaries are exactly identical. Content-token counts
are 35, 30, 27, 25, 42, 30; selected new-token counts including EOS are one more.
Global search iterations also remain below 64 (29–59). No selected-output
ceiling clipping was observed. All are grammatical one-sentence outputs,
without advice or price predictions in the returned text.

Important qualitative finding: all six are exact contiguous sentence copies
from their own full_body. Jargon remains unexplained, and some summaries omit
essential standalone context (e.g. Ethereum/four-minute proposal; OCC output
says “the act” without identifying the act or stablecoin rewards). Thus the
pilot does NOT establish successful abstraction or beginner readability.

Provisional recommendation: **64 as output baseline for these pilot cases**,
since increasing the ceiling changes no text. Not a globally optimal budget,
not evidence that future articles cannot hit 64, and NOT automatically locked.
Prompt remains unchanged. Any later approved prompt change requires explicit
new-condition labeling and a repeated pilot before the main comparison.

Single-observation mean generation times are approximately 3.92/3.88/3.69 seconds
for 64/96/128. Excludes model loading/tokenization; one 1-token warmup was
excluded from the 18 trials. Not a latency benchmark or evidence that a higher
ceiling is faster. A Transformers tied-weight loading warning was observed and
documented without config changes; its impact was not determined here.

Files added: `run_flan_output_pilot.py`, `scratch/test_flan_output_pilot.py`,
`FLAN_OUTPUT_PILOT_README.md`, and the run artifacts above. This independent
pilot runner never imports main_pipeline or the database. Updated this plan
and the preprocessing README for checkpoint status only.

Validation: **199 offline tests passed**, including 46 new output-pilot helper
tests. Real run hashes, exact inputs, unchanged source baseline, all 18 trial
records, EOS/token counts, and six identical-summary groups were also checked.
Production preprocessing integration remains **HIGH PRIORITY / PENDING**.

### Dedicated 64-token justification requested

Added `FLAN_64_TOKEN_JUSTIFICATION_README.md` at the user's request, documenting
the six paired pilot cases, 64/96/128 comparison, exact token/EOS evidence,
baseline-selection rationale, and ready-to-adapt Indonesian thesis/oral-answer
wording. Explicitly distinguishes the smallest tested ceiling from a minimum
or universally optimal ceiling, and output-cap sufficiency from summary quality.
No additional inference, configuration change, reference generation, or input
comparison was performed to create this documentation.

## Point 5 preparation — manual references and four-limit notebook

Prepared `notebook/evaluation_data/flan_reference_package_v1/` from the frozen
cleaned snapshot, not the live collector file. It contains all 73 candidates,
all six pilot markers, a blank four-column GPT reference CSV, a source-review
CSV, and 73 exact full-source prompts ready to copy manually. Observations flag
29 articles: five navigation/ticker extracts, five description/share-control
extracts, and 19 possible clipped-prose cases. These are review aids, not
automatic exclusions or repaired text. Unflagged articles are not certified
complete. All 73 source decisions remain pending.

Added independent `flan_reference_workflow.py` with strict ID matching, source/
prompt hashes, explicit inclusion decisions, reference-readiness checks, and
four-limit generation/export functions. Updated `notebook/flan_evaluation.ipynb`
for the package, generation, four comparison CSVs, and separate ROUGE/BERTScore
cells. Both generation/scoring switches default to False. Comparison CSVs will
contain exactly `id,title,summary,reference_summary`, with the same frozen
references/cohort at every limit. Each run uses a fresh folder and keeps partial
errors instead of silently dropping articles.

Output baseline remains 64 with the current prompt/checkpoint/decoding settings;
the only varied generation setting will be total input ceiling
512/1024/2048/3072. The current service's whole-prompt right-truncation behavior
is retained, including the possibility of losing the trailing `Summary:` cue.
This caveat must be disclosed when attributing differences to input length.

GPT references are blank for the user to fill independently of FLAN outputs.
They use the same prompt and complete source, but not an equal numeric GPT-token
budget. Record the actual GPT model/date/reviewer and source-check the result;
these remain silver rather than human gold references. See
`FLAN_REFERENCE_WORKFLOW_README.md` for the step-by-step procedure.

No production pipeline, database, ingestion, current FLAN source, or original
dataset was modified. Realtime preprocessing integration remains
**HIGH PRIORITY / PENDING**. No new real model inference or metric scoring was
performed for this preparation stage.

Validation: **175 offline tests passed**, including 50 reference-workflow tests
with fake-runtime successful/failing generation. Both project-root and notebook-
directory default execution passed with all heavy model/scoring imports blocked.
All 73 CSV sources/prompts round-trip exactly; source/model hashes are unchanged.

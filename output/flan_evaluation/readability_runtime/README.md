# Isolated RS readability runtime

This environment scores the two frozen FLAN prompt runs and the supplied GPT/Gemini references with English Flesch–Kincaid Grade Level (FKGL). It does not modify the main `.venv`, the source articles, generated summaries, or downloaded reference CSV.

The recorded runtime is Python 3.12.10 with exact package versions in `requirements.txt`. The metric is `textstat==0.7.10`, language `en_US`, and `set_rounding_points(None)`. The required CMU pronunciation dictionary is stored locally under `nltk_data/corpora/`. Dictionary and implementation file SHA-256 hashes are recorded in the evaluation run's `readability_report.json`.

Run from the project root:

```sh
output/flan_evaluation/readability_runtime/venv/bin/python measure_rs_fkgl.py \
  --inputs output/flan_evaluation/dual_reference_evaluation/run_20261101T153358_903997Z/evaluation_inputs.json \
  --output-dir output/flan_evaluation/dual_reference_evaluation/run_20261101T153358_903997Z
```

To recreate the environment, create a Python 3.12 virtual environment and install the pinned `requirements.txt`. Download the official CMUdict archive from `https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/cmudict.zip`, place it at `nltk_data/corpora/cmudict.zip`, and extract it in `nltk_data/corpora/`. Check its recorded SHA-256 before rescoring. The initial Python NLTK downloader could not validate this computer's certificate chain, so the dictionary was downloaded successfully with curl using normal TLS certificate validation.

The scoring script explicitly requires the installed local dictionary, then replaces only NLTK's resource downloader with a local-resource check during scoring. This prevents textstat's unconditional installer call from attempting a network request. Metric functions, dictionary contents, pronunciation selection, syllable fallback, and raw input strings are unchanged.

For each raw string, textstat counts words after its own default punctuation removal; contractions remain one word and hyphens are removed without splitting. It splits sentences with `\b[^.!?]+[.!?]*`, ignores segments of at most two words, and returns at least one sentence for nonempty text. Syllables use the first CMUdict pronunciation, falling back to Pyphen en_US hyphenation positions plus one. Abbreviations, decimal numbers, proper names, and unfamiliar cryptocurrency terms can distort these counts. Every reported FKGL is checked against the unrounded formula from the same recorded word, sentence, and syllable counts:

```text
0.39 * words/sentences + 11.8 * syllables/words - 15.59
```

No score is clamped or repaired. Exact duplicate raw strings reuse the same deterministic descriptors. All 55 identical candidate pairs were separately verified to have equal counts, scores, hashes, and descriptive flags. All 292 candidate/reference records were scored; the maximum formula reconstruction error was 0.0.

FKGL estimates surface reading difficulty, not factual accuracy, completeness, coherence, or actual novice comprehension. The algorithmic 2–3 sentence flag is not a grammatical judgment. Ellipsis, initial `Output:`/`Summary:` label, and missing terminal punctuation flags are string checks; they do not establish an error or prove token-limit truncation. AI reference scores are descriptive baselines rather than validated readability targets.

Library sources: [textstat](https://github.com/textstat/textstat), [pinned release](https://pypi.org/project/textstat/0.7.10/). An exact snapshot of the relevant installed metric functions is saved with the evaluation results.

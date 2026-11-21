# Audit of identical summaries across the two FLAN prompts

No evidence of reference leakage or reuse of previous outputs was found in the inspected generation code. The 55/73identical-output count was reproduced from saved texts and selected token IDs.

## Fresh independent replay

A separate process loaded the cached model again and directly called Transformers `model.generate`, without importing the project generation runners or reading prior summaries/references. It read only the rawRS articles and saved prompts, running detailed before short to reverse historical order.

All 12 fresh generations matched the saved summary strings and selected token IDs exactly. The model inputs differed between prompts in all six cases.

| Article position | Historical relationship | Fresh replay |
|---:|---|---|
| 1 | Identical across prompts | Both prompt outputs reproduced exactly |
| 2 | Identical across prompts | Both prompt outputs reproduced exactly |
| 4 | Identical across prompts | Both prompt outputs reproduced exactly |
| 28 | Identical across prompts | Both prompt outputs reproduced exactly |
| 3 | Different across prompts | Both prompt outputs reproduced exactly |
| 37 | Different across prompts | Both prompt outputs reproduced exactly |

## Why matching outputs are plausible

Of the 55 matching summaries, 48 are exact contiguous passages of their own source articles; 49 match when whitespace is normalized. Article 1 copies a key-point bullet, and article 2 copies the publisher’s introductory deck. Both instruction variants often lead the model to select the same existing concise text.

Both experiments use deterministic four-beam decoding with sampling disabled. Different instruction strings can produce the same selected output sequence; a change of prompt does not require changed wording. This result is evidence of strongly extractive behavior and limited response to some instruction changes, rather than evidence that a reference summary was supplied to FLAN.

## Code-path checks

- Current RS title and full_body form the article input. The recovered dataset supplies stable IDs only.
- Each prompt is formatted and tokenized separately.
- Each article invokes model.generate; the helper returns newly generated tokens.
- The RS runner does not invoke the separate historical-baseline reuse function.
- Local cached model weights are reused model parameters, not cached generated answers.

## Limits and experimental interpretation

The fresh replay covers six selected articles, while the saved-artifact and code audit covers all 73 pairs. This cannot establish whether the pretrained model’s original training corpus contained related text.

Prompt experimentation has repeatedly used these same 73 articles. Treat results as a development/comparison experiment; an unseen held-out set would be needed for a stronger generalization claim.

No production configuration, original article dataset, reference CSV, or previous generation result was modified.

Files: verification_report.json, fresh_outputs.json, replay_report.json, per_article_source_copy_audit.json, and replay_script.py.

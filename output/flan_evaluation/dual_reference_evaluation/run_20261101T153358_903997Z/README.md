# Paired evaluation of the two RS FLAN prompts

Both saved prompt runs were evaluated on the same 73 articles, against separate GPT and Gemini AI-generated references. 55 summary pairs are exactly identical and 18 differ. No summaries, article bodies, or references were edited for evaluation.

## Main results

Scores are macro means over all 73 articles. ROUGE, BERTScore, and AlignScore use their raw scale; FKGL uses estimated US school grade. Arrows show the preferred metric direction. Wins/ties/losses describe the detailed prompt relative to the short prompt; for FKGL a lower value counts as a metric win.

| Metric | Short | Detailed | Detailed − short | Paired 95% CI | Wins / ties / losses |
| --- | ---: | ---: | ---: | --- | ---: |
| ROUGE-1 F1 / GPT ↑ | 0.3267 | 0.3239 | -0.0028 | [-0.0172, +0.0130] | 6 / 55 / 12 |
| ROUGE-2 F1 / GPT ↑ | 0.1454 | 0.1430 | -0.0024 | [-0.0171, +0.0117] | 7 / 55 / 11 |
| ROUGE-L F1 / GPT ↑ | 0.2479 | 0.2481 | +0.0002 | [-0.0130, +0.0146] | 7 / 55 / 11 |
| BERTScore F1 / GPT ↑ | 0.8819 | 0.8821 | +0.0002 | [-0.0026, +0.0039] | 7 / 55 / 11 |
| ROUGE-1 F1 / GEMINI ↑ | 0.2681 | 0.2618 | -0.0063 | [-0.0177, +0.0051] | 5 / 56 / 12 |
| ROUGE-2 F1 / GEMINI ↑ | 0.1055 | 0.1018 | -0.0037 | [-0.0120, +0.0049] | 7 / 55 / 11 |
| ROUGE-L F1 / GEMINI ↑ | 0.1937 | 0.1905 | -0.0031 | [-0.0130, +0.0068] | 7 / 56 / 10 |
| BERTScore F1 / GEMINI ↑ | 0.8727 | 0.8727 | -1.05e-06 | [-0.0021, +0.0029] | 8 / 55 / 10 |
| AlignScore ↑ | 0.9726 | 0.9755 | +0.0029 | [-0.0004, +0.0072] | 12 / 55 / 6 |
| FKGL ↓ | 11.2663 | 10.9216 | -0.3447 | [-0.6373, -0.0767] | 14 / 55 / 4 |

The reference-agreement changes are small and mixed: all eight F1 confidence intervals include zero. The detailed prompt has a slightly higher mean AlignScore, but its change interval also includes zero. Its mean FKGL is about 0.34 grades lower, with a paired interval below zero. This supports a small reduction in estimated surface difficulty on these articles, while the evaluation does not establish an overall winning prompt. The 72-article sensitivity analysis gives the same interpretation.

The confidence intervals describe the mean paired change, not uncertainty for individual summaries. A small favorable change in an automatic metric does not establish overall summary quality or beginner understanding. Table means are rounded; CSV and JSON values retain full precision.

## Sensitivity to input truncation

Articles with any generation-input truncation: #29. The detailed prompt made article #29 exceed the 3072-token input limit (3266 original tokens; 194 removed). Both conditions produced the same summary for this article. The following table removes this paired article from both conditions (72 articles). AlignScore still uses the full frozen article as the source in the main and sensitivity analyses.

| Metric | Short | Detailed | Detailed − short | Paired 95% CI | Wins / ties / losses |
| --- | ---: | ---: | ---: | --- | ---: |
| ROUGE-1 F1 / GPT ↑ | 0.3282 | 0.3253 | -0.0029 | [-0.0175, +0.0132] | 6 / 54 / 12 |
| ROUGE-2 F1 / GPT ↑ | 0.1463 | 0.1438 | -0.0024 | [-0.0169, +0.0118] | 7 / 54 / 11 |
| ROUGE-L F1 / GPT ↑ | 0.2486 | 0.2488 | +0.0002 | [-0.0128, +0.0148] | 7 / 54 / 11 |
| BERTScore F1 / GPT ↑ | 0.8820 | 0.8823 | +0.0002 | [-0.0026, +0.0039] | 7 / 54 / 11 |
| ROUGE-1 F1 / GEMINI ↑ | 0.2697 | 0.2633 | -0.0064 | [-0.0177, +0.0049] | 5 / 55 / 12 |
| ROUGE-2 F1 / GEMINI ↑ | 0.1063 | 0.1025 | -0.0037 | [-0.0120, +0.0048] | 7 / 54 / 11 |
| ROUGE-L F1 / GEMINI ↑ | 0.1949 | 0.1918 | -0.0032 | [-0.0132, +0.0070] | 7 / 55 / 10 |
| BERTScore F1 / GEMINI ↑ | 0.8729 | 0.8729 | -1.07e-06 | [-0.0022, +0.0028] | 8 / 54 / 10 |
| AlignScore ↑ | 0.9723 | 0.9752 | +0.0030 | [-0.0004, +0.0072] | 12 / 54 / 6 |
| FKGL ↓ | 11.3558 | 11.0063 | -0.3495 | [-0.6487, -0.0747] | 14 / 54 / 4 |

## Readability components and output length

| Descriptive measure | Short mean | Detailed mean |
| --- | ---: | ---: |
| word_count | 26.8219 | 25.5479 |
| sentence_count | 1.6027 | 1.5205 |
| words_per_sentence | 19.7390 | 19.3379 |
| syllables_per_word | 1.6236 | 1.6076 |
| generated_tokens_including_eos | 40.4521 | 38.5205 |

The textstat sentence heuristic counted 2–3 sentences for 26/73 short-prompt and 24/73 detailed-prompt summaries. Abbreviations and decimal numbers can split sentences; this is an algorithmic count rather than a grammatical compliance assessment.

Both generation runs used max_new_tokens=192, and neither hit that output ceiling. Natural model termination does not guarantee complete or useful prose; existing ellipses, output labels, and incomplete fragments remain in the scored strings.

| AI reference baseline | Mean word count | Mean FKGL |
| --- | ---: | ---: |
| GPT | 66.4247 | 11.9282 |
| GEMINI | 100.3562 | 14.8195 |

These reference readability values are descriptive baselines. They are not validated readability targets; the two references differ in length and style.

## Methods and interpretation

- **Reference agreement:** ROUGE-1/2/L and BERTScore precision, recall, and F1 are computed independently against GPT and Gemini. The primary table reports F1; all components are in the CSV/JSON files. A secondary per-article equal-weight mean of the two reference scores is explicitly labeled. References are never concatenated or selected by whichever gives the better score. Neither reference is human gold.
- **ROUGE:** rouge-score 0.1.2, stemming enabled; macro average of per-article scores.
- **BERTScore:** bert-score 0.3.13; roberta-large layer 17, no IDF, no baseline rescaling, slow tokenizer, CPU. Configuration hash: `roberta-large_L17_no-idf_version=0.3.12(hug_trans=5.14.1)`. No evaluator text was truncated (maximum 178 tokens; evaluator limit 512).
- **Source consistency:** AlignScore compares each unchanged candidate to the full frozen article, independently of the GPT/Gemini references. Its 0–1 output estimates source alignment; it is not a percentage of correct facts and cannot verify whether the article itself is true. A copied passage can score well while omitting essential context or retaining difficult terminology.
- **AlignScore runtime and internal limit:** AlignScore-large uses the official `nli_sp` method from commit `a0936d5afee642a46b22f6c02a163478447aa493`: source chunks based on 350 whitespace words, summary sentence splitting, maximum entailment over source chunks per summary sentence, then a mean over summary sentences. Full documents enter this pipeline without a manual cutoff. The official tokenizer internally truncated 24 of 367 sentence/chunk pairs at 512 tokens, affecting 13 of 91 unique article/summary pairs. This evaluator-internal limit is distinct from the one FLAN generation-input truncation at article #29. A compatibility adapter bypasses training-only dependencies and unused computation; all 404 state tensors (403 parameter tensors) were verified against the checkpoint, and the classification outputs matched the original full forward bitwise in the recorded parity check. Exact provenance is in alignscore_report.json.
- **Surface readability:** unrounded English FKGL is computed on the exact saved summary using textstat 0.7.10. Formula: `0.39 × words/sentences + 11.8 × syllables/words − 15.59`. Lower values indicate lower estimated surface reading difficulty. FKGL does not measure factuality, completeness, coherence, jargon explanation, or actual beginner comprehension. Word, sentence, and syllable counts are retained because short texts, names, abbreviations, and numbers affect the result.
- **Pairing and uncertainty:** 10,000 article-level bootstrap resamples, seed 20261101, percentile 95% intervals (NumPy linear quantiles). Each resample keeps both prompt outputs and both reference scores together. The same bootstrap draws are used across metrics within each subset. All 55 identical pairs retain exact score ties. Intervals are pointwise, with no multiplicity adjustment or p-values; no combined quality score is calculated.
- **Scope:** these articles were used during prompt development, so this is a development-set comparison rather than a held-out test. Intervals describe variation across the sampled articles only. They do not account for reference-generation choices, model-training uncertainty, repeated events, or topic/source clustering. The 18 changed outputs are also summarized separately for description only, because selecting changes after generation cannot support a general prompt-effect claim.

## Relationship to existing studies

This separates reference agreement, readability, and source consistency in the same broad manner as the [BioLaySumm 2024 evaluation](https://aclanthology.org/2024.bionlp-1.10.pdf), which uses ROUGE/BERTScore, readability measures including FKGL, and factuality measures including AlignScore. Its biomedical task differs from cryptocurrency news, so its usage supports the method choice rather than validating these scores for this domain. The paper also notes that highly extractive outputs can be favored by factuality metrics.

[AlignScore (Zha et al., 2023)](https://aclanthology.org/2023.acl-long.634/) introduces the learned information-alignment metric. [Tanprasert and Kauchak (2021)](https://aclanthology.org/2021.gem-1.1/) demonstrate that FKGL can be manipulated and recommend examining component statistics. Accordingly FKGL is used here as a diagnostic surface measure. [Dror et al. (2018)](https://aclanthology.org/P18-1128/) discuss choosing statistical comparisons that match the NLP experimental design; the paired article bootstrap here preserves the shared inputs.

## Reproducibility and files

Generation checkpoint: `google/flan-t5-base` at `7bcac572ce56db69c1ea7c8af255c5d7c9672fc2`; input limit 3072, output limit 192, deterministic beam search with 4 beams. Prompt strings and generation settings are recorded in evaluation_manifest.json.

- `per_article_evaluation.csv`: 146 candidate rows, exact summary/reference text, all primary metric components, input truncation flags, and readability diagnostics.
- `paired_differences.csv`: one row per article/metric/reference with both scores and the detailed-minus-short change.
- `evaluation_summary.csv`: all metric components by condition, reference, and subset, including descriptive 18-changed-output results.
- `paired_statistics.json`: paired changes, bootstrap intervals, wins/ties/losses, baseline reference readability, and validation/provenance hashes.
- `reference_metric_scores.json`, `alignscore_scores.json`, `readability_scores.json`, `reference_readability.json`: unchanged phase results.
- `reference_metrics_report.json`, `alignscore_report.json`, `readability_report.json`: exact scorer configurations, model/resource versions, and runtime compatibility details.
- `reference_summaries_frozen.csv`, `evaluation_inputs.json`, `evaluation_manifest.json`: frozen input and source provenance.

Aggregation command (from the project root):

```bash
.venv/bin/python summarize_rs_dual_evaluation.py --run-dir output/flan_evaluation/dual_reference_evaluation/run_20261101T153358_903997Z
```

The aggregation validates all phase statuses, candidate/reference coverage, protected source hashes, and score equality for identical outputs before writing derived reports.

AlignScore runtime note: consult `alignscore_report.json` for the official checkpoint, inference adapter, parameter-loading audit, and forward-parity checks. The original training runtime is not required for inference.

# Proposed dual-reference evaluation of the two FLAN prompts

Status: proposed protocol, not completed scoring. The reference file and existing generation runs were inspected read-only. This document does not contain metric results or human/LLM judgments.

## Verified inputs

- Supplied file: `/Users/mumu/Downloads/flan_dual_reference_summaries_20261101.csv`.
- SHA256: `75dcb6f52e5d51e0f0b1989900975c1b170d32ed964c3d9c610e37a17130ceac`.
- Exactly 73 unique IDs; every `title` and `article_text` exactly matches both frozen RS experiment datasets.
- Columns: `id`, `title`, `article_text`, `gpt_reference_summary`, `gemini_reference_summary`. Both reference columns contain 73 nonempty summaries.
- GPT references average 66.42 whitespace-delimited words; Gemini references average 100.37. Report separate reference scores and precision/recall, because the references differ in length and wording.
- Short-prompt run: `output/flan_evaluation/rs_output_lengths/run_20261101T125023_557980Z/`.
- Detailed-prompt run: `output/flan_evaluation/rs_output_lengths/run_20261101T130452_832310Z/`.
- Both use 73 articles, the same model revision, deterministic beam settings, a 3,072-token input limit and initial 192-token output ceiling. No output reruns were required.
- There are 55 identical within-article output pairs and 18 changed pairs: 146 output records but 91 distinct article-summary pairs for content-based annotation.
- Only article #29 is input-truncated in the detailed-prompt run: 3,266 complete input tokens become 3,072, removing 194. Its output remains identical across the two runs.

## Evaluation questions

Keep four outcomes separate:

1. Reference agreement: how similar is the FLAN summary to each supplied GPT/Gemini reference?
2. Source consistency: are the summary's event claims supported by its source article?
3. Beginner readability: can the intended reader follow the wording and essential concepts?
4. Coverage/relevance: does the summary communicate the main event and necessary supporting facts?

The supplied summaries are AI-generated silver references. Agreement between them is not a gold factual label. Factual consistency here means faithfulness to the supplied article, not independent verification of the article's real-world truth.

## A. Reference-based automatic evaluation

Score each FLAN output against each reference separately: 2 prompt conditions × 73 articles × 2 references = 292 candidate-reference comparisons.

- ROUGE-1, ROUGE-2 and ROUGE-L: preserve the project's stemming setting; retain precision, recall and F1. F1 maintains continuity with earlier result tables.
- BERTScore: preserve the existing English `roberta-large`, layer 17, `idf=False`, `rescale_with_baseline=False`, slow tokenizer and pinned cached revision. Retain precision, recall, F1 and the configuration hash.
- Preserve full candidate/reference text; verify the evaluator itself does not truncate either.
- Report four explicit combinations: short/GPT, short/Gemini, detailed/GPT and detailed/Gemini. Do not concatenate the two references.
- If a combined reference-agreement result is useful, predeclare an equal-weight mean of the two per-reference scores for each article, then macro-average across the 73 articles. This is a transparent aggregation choice for this experiment, not a claim about a universally preferred multi-reference metric.
- Inspect whether the prompt comparison has the same direction under both references. Do not choose the reference giving the preferred result after scoring.

ROUGE and BERTScore measure lexical/semantic agreement. Do not rename either score factual accuracy or beginner understanding.

## B. Source-grounded factual consistency

Use the full frozen `article_text` as the evidence document for both conditions. Record the input-truncation flag separately.

For each distinct article-summary pair, split clear factual assertions using fixed segmentation rules. Label each assertion:

- Supported by the source.
- Contradicted by the source.
- Not verifiable from the supplied source.

Retain a source evidence span or a concise explanation of the missing evidence. Tag wrong entities/actions, numbers/dates, attribution, uncertainty, causal links and unsupported additions. Flag uninterpretable fragments separately instead of silently awarding full factual credit.

Suggested outcomes are the per-summary supported-claim proportion and the proportion of summaries with at least one contradicted or unsupported event claim. Retain the underlying labels and denominators. These are an adapted annotation procedure inspired by factuality research; they are not the published FRANK or FActScore metric implementation.

Keep omissions under coverage/relevance unless they change a claim's meaning. A short true headline can be factually supported while failing to communicate the main event adequately.

Predefine treatment of technical definitions. The prompts request simple explanations: distinguish a neutral explanatory gloss from a new claim about the news event. Check explanatory accuracy separately against a documented, fixed glossary where external definitions are allowed. If strict article-only support is required, mark definitions absent from the article as not source-verifiable, rather than automatically calling them false. Do not silently change this policy after seeing outputs.

## C. Beginner readability and coverage

Use an explicit, calibrated rubric. The following is a proposed adaptation, not a validated cryptocurrency readability scale.

| Dimension | 1 | 3 | 5 |
|---|---|---|---|
| Beginner accessibility | Essential unexplained jargon blocks understanding | Main point recognizable, but some concepts unclear | Main event understandable in everyday language with necessary explanations |
| Fluency/coherence | Fragments or disconnected/promotional material | Generally readable with some unclear links/referents | Complete, connected sentences with clear relationships |
| Main-event coverage | Central event missing or misleadingly incomplete | Main event present, with an important gap | Main event and essential supporting facts sufficiently conveyed |

Record essential explanation adequacy separately as adequate/partial/missing/not applicable. Avoid rewarding unnecessary definitions just for making a summary longer.

Record format compliance separately: 2–3 sentences, no headings/bullets, no copied newsletter/signup text, and no unfinished fragments/ellipses. Sentence splitting must account for abbreviations and decimals; manually review ambiguous cases.

For accessibility judgments, first show only the candidate summary and intended audience. Do not let the source or reference fill gaps for the reader. Coverage and factuality are assessed in a separate pass with the article available.

Flesch Reading Ease, Flesch–Kincaid grade, word count and sentence length can be supplementary descriptors. They are not sufficient evidence of cryptocurrency beginner understanding, particularly for short texts and specialist terms.

If actual novice comprehension is a thesis outcome, add source-validated comprehension questions on a feasible subset with novice participants. Counterbalance conditions so a reader does not first learn the same article from the other condition. Without this component, describe the result as rater-assessed readability, not demonstrated comprehension.

## D. Raters and optional GPT/Gemini judging

Prefer two independent blinded human raters for the adapted factuality/readability rubric where feasible. Calibrate on a small fixed pilot, document rubric changes, then freeze instructions before the main annotation. Report agreement before adjudication and retain disagreements and final decisions. For example, nominal agreement statistics apply to claim labels; an ordinal agreement statistic can be used for the 1–5 scales.

If GPT and Gemini are also used as judges, that is a new role, separate from supplying their reference summaries:

- Give each judge the same criteria and anonymous candidate labels; hide which FLAN prompt produced the candidate.
- For factuality, supply the article and candidate and require source evidence. Do not ask a judge to infer truth solely from its own reference.
- For readability, use the audience definition and candidate-only first pass; require a concise rationale.
- Prefer independent candidate scoring. If using pairwise preferences, evaluate both A/B and B/A order and retain order-sensitive disagreements.
- Record exact judge model/version, date, evaluation prompt and settings. Preserve GPT and Gemini scores separately before any declared aggregation.
- Require human review of disagreements and a predefined sample of agreements. Clearly label unvalidated model ratings as LLM-assisted judgments.
- Agreement between the two judges is corroborating evidence, not proof. Hiding labels or using two models does not eliminate all model/style biases.

For content-based ratings, annotate each of the 91 distinct article-summary pairs once per rater and map the score back to identical outputs in both prompt conditions. Identical within-article texts must not receive different prompt-attributed scores merely because a judge is stochastic.

## E. Paired comparison and reporting

- Keep all 73 article pairs in the main comparison. The experimental unit is the article; references and judge ratings within it are not independent extra articles.
- Report prompt-level means, paired differences, and article-level win/tie/loss counts where meaningful.
- Obtain 95% bootstrap confidence intervals by resampling article IDs and keeping both conditions and both references together. Predeclare primary outcomes if formal significance claims are planned.
- Retain the 55 identical output pairs as ties. Report the 18 changed pairs as a descriptive subset, not the entire evaluation cohort.
- Add a sensitivity comparison on the 72 articles untruncated in both runs. Explain article #29's changed input availability even though its summary happened to be unchanged.
- Report reference-specific agreement, factual consistency, readability, coverage and format compliance separately. Do not mix them into an arbitrary overall accuracy percentage.
- Label the study a paired evaluation on this 73-article thesis dataset, not evidence of general superiority across unseen news.

## Research basis

The proposed protocol adapts these studies; it does not reproduce every paper's dataset, annotation scheme or implementation.

- Lin (2004), [ROUGE: A Package for Automatic Evaluation of Summaries](https://aclanthology.org/W04-1013/): lexical reference-overlap evaluation.
- Zhang et al. (2020), [BERTScore: Evaluating Text Generation with BERT](https://arxiv.org/abs/1904.09675): contextual token-based reference agreement.
- Fabbri et al. (2021), [SummEval: Re-evaluating Summarization Evaluation](https://aclanthology.org/2021.tacl-1.24/): separate consistency, relevance, fluency and coherence judgments alongside automatic metrics; reference quality can itself be imperfect.
- Pagnoni et al. (2021), [Understanding Factuality in Abstractive Summarization with FRANK](https://aclanthology.org/2021.naacl-main.383/): source article as factual ground truth and fine-grained error categories.
- Alva-Manchego et al. (2021), [The (Un)Suitability of Automatic Evaluation Metrics for Text Simplification](https://aclanthology.org/2021.cl-4.28/): limitations of automatic simplicity proxies, including weak Flesch-based performance in sentence-level evaluation.
- Agrawal and Carpuat (2024), [Do Text Simplification Systems Preserve Meaning? A Human Evaluation via Reading Comprehension](https://aclanthology.org/2024.tacl-1.24/): comprehension-based human evaluation as evidence beyond perceived simplicity.
- Liu et al. (2023), [G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment](https://aclanthology.org/2023.emnlp-main.153/): structured LLM evaluation with limitations and potential bias.
- Wang et al. (2024), [Large Language Models are not Fair Evaluators](https://aclanthology.org/2024.acl-long.511/): candidate-order bias in LLM judgments and the need for calibration/counterbalancing.
- Dror et al. (2018), [The Hitchhiker's Guide to Testing Statistical Significance in Natural Language Processing](https://aclanthology.org/P18-1128/): choose comparative inference methods appropriate to task, metric and experimental design.

## Suggested next deliverables

1. A frozen copy of the supplied references and validated candidate/source manifest.
2. Separate ROUGE and BERTScore per-article/reference results plus a paired comparison table.
3. A blinded, deduplicated annotation sheet with article evidence fields and rubric anchors.
4. Optional fixed GPT/Gemini judge prompts and a separate human-review sheet.
5. A final report preserving automatic scores, ratings, disagreements, input flags and uncertainty separately.

No scoring, judge calls or reference edits have been performed by preparing this protocol.

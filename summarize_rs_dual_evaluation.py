"""Validate and aggregate the frozen paired RS summary evaluation.

Only this run's derived reports are written. Source text, references, generation
outputs, and phase scores are read without alteration. Every bootstrap sample
resamples article IDs, preserving the short/detailed pair and both references.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent
DEFAULT_RUN = ROOT / 'output/flan_evaluation/dual_reference_evaluation/run_20261101T153358_903997Z'
CONDITIONS = ('short', 'detailed')
REFERENCES = ('gpt', 'gemini')
REFERENCE_METRICS = tuple(f'{name}_{part}' for name in ('rouge1', 'rouge2', 'rougeL', 'bertscore')
                          for part in ('precision', 'recall', 'f1'))
READABILITY_METRICS = ('fkgl', 'word_count', 'sentence_count', 'syllable_count',
                       'words_per_sentence', 'syllables_per_word', 'two_to_three_sentences')
GENERATION_METRICS = ('generated_tokens_including_eos', 'input_token_count', 'original_input_token_count')
PHASE_FILES = {
    'reference': ('reference_metric_scores.json', 'reference_metrics_report.json'),
    'alignscore': ('alignscore_scores.json', 'alignscore_report.json'),
    'readability': ('readability_scores.json', 'readability_report.json'),
}
PRIMARY_METRICS = tuple((metric, ref) for ref in REFERENCES
                        for metric in ('rouge1_f1', 'rouge2_f1', 'rougeL_f1', 'bertscore_f1')) + (
                            ('alignscore', 'source'), ('fkgl', 'none'))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f'No rows for {path.name}')
    fields = list(dict.fromkeys(key for row in rows for key in row))
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def keyed(rows: list[dict], fields: tuple[str, ...], expected: set[tuple], label: str) -> dict:
    result = {}
    for row in rows:
        key = tuple(row[field] for field in fields)
        if key in result:
            raise ValueError(f'Duplicate {label} key: {key}')
        result[key] = row
    if set(result) != expected:
        raise ValueError(f'{label} keys mismatch: missing={len(expected-set(result))}, extra={len(set(result)-expected)}')
    return result


def finite_number(value: Any, label: str) -> float:
    if not isinstance(value, (float, int, bool)) or not math.isfinite(value):
        raise ValueError(f'Non-finite or non-numeric {label}: {value!r}')
    return float(value)


def validate_inputs(run: Path, require_all_phases: bool = True) -> dict:
    manifest = read_json(run / 'evaluation_manifest.json')
    if digest(run / 'evaluation_inputs.json') != manifest['input_manifest_sha256']:
        raise ValueError('Frozen evaluation input hash changed')
    if digest(run / 'reference_summaries_frozen.csv') != manifest['reference_sha256']:
        raise ValueError('Frozen reference CSV hash changed')
    for filename, expected_hash in manifest['source_hashes'].items():
        if digest(Path(filename)) != expected_hash:
            raise ValueError(f'Protected source changed: {filename}')
    inputs = read_json(run / 'evaluation_inputs.json')
    ids = [row['id'] for row in inputs if row['prompt_condition'] == 'short']
    n = manifest['article_count']
    if len(ids) != n or len(set(ids)) != n or len(inputs) != 2*n:
        raise ValueError('Unexpected number of unique paired inputs')
    expected = {(article_id, condition) for article_id in ids for condition in CONDITIONS}
    by_input = keyed(inputs, ('id', 'prompt_condition'), expected, 'candidate')
    by_index = {}
    for article_id in ids:
        short, detailed = [by_input[article_id, condition] for condition in CONDITIONS]
        for field in ('source_index', 'title', 'url', 'article_text', 'gpt_reference_summary', 'gemini_reference_summary'):
            if short[field] != detailed[field]:
                raise ValueError(f'Unpaired {field}: {article_id}')
        if not all(row['summary'].strip() for row in (short, detailed)):
            raise ValueError(f'Empty candidate: {article_id}')
        if short['source_index'] in by_index:
            raise ValueError('Duplicate source index')
        by_index[short['source_index']] = article_id
    reports, scores, hashes, missing = {}, {}, {}, []
    for phase, (scorefile, reportfile) in PHASE_FILES.items():
        if not all((run / name).is_file() for name in (scorefile, reportfile)):
            missing.append(phase)
            continue
        report = read_json(run / reportfile)
        if report.get('status') != 'complete':
            raise ValueError(f'{phase} is not complete')
        if 'input_sha256' in report and report['input_sha256'] != manifest['input_manifest_sha256']:
            raise ValueError(f'{phase} used different inputs')
        reports[phase] = report
        phase_expected = {(a, c, r) for a, c in expected for r in REFERENCES} if phase == 'reference' else expected
        keys = ('id', 'prompt_condition', 'reference_model') if phase == 'reference' else ('id', 'prompt_condition')
        scores[phase] = keyed(read_json(run / scorefile), keys, phase_expected, phase)
        metric_names = REFERENCE_METRICS if phase == 'reference' else ('alignscore',) if phase == 'alignscore' else READABILITY_METRICS
        for key, row in scores[phase].items():
            for metric in metric_names:
                value = finite_number(row[metric], f'{phase}/{key}/{metric}')
                if (metric.startswith('rouge') or metric == 'alignscore') and not 0 <= value <= 1:
                    raise ValueError(f'{metric} outside [0, 1]')
            if 'source_index' in row and row['source_index'] != by_input[key[:2]]['source_index']:
                raise ValueError(f'{phase} source index mismatch')
            if 'title' in row and row['title'] != by_input[key[:2]]['title']:
                raise ValueError(f'{phase} title mismatch')
            if phase == 'readability' and row.get('text_sha256') != hashlib.sha256(
                    by_input[key[:2]]['summary'].encode('utf-8')).hexdigest():
                raise ValueError(f'{phase} summary fingerprint mismatch')
        for name in (scorefile, reportfile):
            hashes[name] = digest(run / name)
    if require_all_phases and missing:
        raise ValueError(f'Metric phases not ready: {", ".join(missing)}')
    identical = [a for a in ids if by_input[a, 'short']['summary'] == by_input[a, 'detailed']['summary']]
    for phase, phase_scores in scores.items():
        metric_names = REFERENCE_METRICS if phase == 'reference' else ('alignscore',) if phase == 'alignscore' else READABILITY_METRICS
        for article_id in identical:
            for ref in REFERENCES if phase == 'reference' else (None,):
                suffix = (ref,) if ref is not None else ()
                short, detailed = [phase_scores[(article_id, condition) + suffix] for condition in CONDITIONS]
                for metric in metric_names:
                    if short[metric] != detailed[metric]:
                        raise ValueError(f'Identical candidate has unequal {phase}/{metric} scores: {article_id}')
    reference_readability = None
    if 'readability' in scores:
        name = 'reference_readability.json'
        reference_readability = keyed(read_json(run / name), ('id', 'reference_model'),
                                      {(a, r) for a in ids for r in REFERENCES}, 'reference readability')
        for key, row in reference_readability.items():
            article_id, reference = key
            expected_text = by_input[article_id, 'short'][f'{reference}_reference_summary']
            if row.get('text_sha256') != hashlib.sha256(expected_text.encode('utf-8')).hexdigest():
                raise ValueError('Reference readability text fingerprint mismatch')
            for metric in READABILITY_METRICS:
                finite_number(row[metric], f'reference readability/{key}/{metric}')
        hashes[name] = digest(run / name)
    return dict(manifest=manifest, inputs=inputs, ids=ids, by_input=by_input, reports=reports, scores=scores,
                hashes=hashes, identical=identical, reference_readability=reference_readability, missing_phases=missing)


def metric_specs() -> list[dict]:
    specs = []
    for ref in (*REFERENCES, 'mean_of_two_references'):
        for metric in REFERENCE_METRICS:
            specs.append(dict(metric=metric, reference=ref, direction='higher',
                              role='secondary' if ref == 'mean_of_two_references' else 'primary_reference_metric'))
    specs.extend([dict(metric='alignscore', reference='source', direction='higher', role='source_consistency_proxy'),
                  dict(metric='fkgl', reference='none', direction='lower', role='surface_readability_proxy')])
    for metric in READABILITY_METRICS[1:] + GENERATION_METRICS:
        specs.append(dict(metric=metric, reference='none', direction='descriptive', role='descriptive'))
    return specs


def score_value(data: dict, article_id: str, condition: str, spec: dict) -> float:
    metric, ref = spec['metric'], spec['reference']
    if metric in REFERENCE_METRICS:
        if ref == 'mean_of_two_references':
            return sum(data['scores']['reference'][article_id, condition, r][metric] for r in REFERENCES) / 2
        return float(data['scores']['reference'][article_id, condition, ref][metric])
    if metric == 'alignscore':
        return float(data['scores']['alignscore'][article_id, condition][metric])
    if metric in READABILITY_METRICS:
        return float(data['scores']['readability'][article_id, condition][metric])
    return float(data['by_input'][article_id, condition][metric])


def bootstrap_interval(differences: np.ndarray, indices: np.ndarray) -> list[float]:
    means = differences[indices].mean(axis=1)
    return [float(value) for value in np.quantile(means, [0.025, 0.975], method='linear')]


def descriptive(values: np.ndarray) -> dict:
    return dict(mean=float(values.mean()), median=float(np.median(values)),
                standard_deviation=float(values.std(ddof=1)) if len(values) > 1 else 0.0,
                minimum=float(values.min()), maximum=float(values.max()))


def aggregate(data: dict, resamples: int, seed: int) -> tuple[dict, list, list, list]:
    ids, by_input = data['ids'], data['by_input']
    truncated = [a for a in ids if any(by_input[a, c]['input_was_truncated'] for c in CONDITIONS)]
    changed = [a for a in ids if a not in data['identical']]
    subsets = [('all_articles', ids), ('no_input_truncation', [a for a in ids if a not in truncated]),
               ('changed_outputs_descriptive', changed)]
    specs = metric_specs()
    records, summaries, differences = [], [], []
    rng = np.random.default_rng(seed)
    for subset_name, selected in subsets:
        if not selected:
            continue
        bootstrap = subset_name != 'changed_outputs_descriptive'
        # Shared draws across all metrics preserve article pairing and reference dependence.
        indices = rng.integers(0, len(selected), size=(resamples, len(selected))) if bootstrap else None
        for spec in specs:
            short = np.array([score_value(data, a, 'short', spec) for a in selected], dtype=np.float64)
            detailed = np.array([score_value(data, a, 'detailed', spec) for a in selected], dtype=np.float64)
            delta = detailed - short
            row = dict(subset=subset_name, n=len(selected), **spec, short_mean=float(short.mean()),
                       detailed_mean=float(detailed.mean()), mean_delta=float(delta.mean()),
                       delta_definition='detailed_minus_short', median_delta=float(np.median(delta)),
                       exact_ties=int((delta == 0).sum()), positive_deltas=int((delta > 0).sum()),
                       negative_deltas=int((delta < 0).sum()), bootstrap_resamples=resamples if bootstrap else 0,
                       bootstrap_95_percent_ci=bootstrap_interval(delta, indices) if bootstrap else None)
            if spec['direction'] != 'descriptive':
                improvement = delta * (1 if spec['direction'] == 'higher' else -1)
                row.update(detailed_wins=int((improvement > 0).sum()), detailed_losses=int((improvement < 0).sum()))
            else:
                row.update(detailed_wins=None, detailed_losses=None)
            records.append(row)
            for condition, values in [('short', short), ('detailed', detailed)]:
                summaries.append(dict(subset=subset_name, n=len(selected), prompt_condition=condition, **spec,
                                      **descriptive(values)))
            if subset_name == 'all_articles':
                for article_id, short_value, detailed_value, delta_value in zip(selected, short, detailed, delta, strict=True):
                    outcome = 'tie' if delta_value == 0 else (
                        'increase' if delta_value > 0 else 'decrease') if spec['direction'] == 'descriptive' else (
                        'detailed_win' if (delta_value > 0) == (spec['direction'] == 'higher') else 'detailed_loss')
                    differences.append(dict(id=article_id, source_index=by_input[article_id, 'short']['source_index'],
                        title=by_input[article_id, 'short']['title'], **spec,
                        short_value=float(short_value), detailed_value=float(detailed_value), delta=float(delta_value),
                        delta_definition='detailed_minus_short', outcome=outcome,
                        summaries_identical=article_id in data['identical'],
                        included_no_input_truncation=article_id not in truncated))
    merged = []
    for article_id in ids:
        for condition in CONDITIONS:
            source = by_input[article_id, condition]
            row = {key: source[key] for key in ('id', 'source_index', 'prompt_condition', 'title', 'url', 'summary',
                'gpt_reference_summary', 'gemini_reference_summary', 'input_was_truncated', *GENERATION_METRICS)}
            row['summaries_identical'] = article_id in data['identical']
            for ref in REFERENCES:
                for metric in REFERENCE_METRICS:
                    row[f'{ref}_{metric}'] = data['scores']['reference'][article_id, condition, ref][metric]
            row.update({key: value for key, value in data['scores']['readability'][article_id, condition].items()
                        if key not in ('id', 'prompt_condition', 'source_index')})
            row['alignscore'] = data['scores']['alignscore'][article_id, condition]['alignscore']
            merged.append(row)
    baseline = []
    for ref in REFERENCES:
        for metric in READABILITY_METRICS:
            values = np.array([data['reference_readability'][a, ref][metric] for a in ids], dtype=float)
            baseline.append(dict(reference_model=ref, metric=metric, n=len(ids), **descriptive(values)))
    report = dict(status='complete', created_at_utc=datetime.now(timezone.utc).isoformat(),
        article_count=len(ids), candidate_count=2*len(ids), identical_summary_pairs=len(data['identical']),
        changed_summary_pairs=len(changed), truncated_article_ids=truncated,
        truncated_source_indices=[by_input[a, 'short']['source_index'] for a in truncated],
        validation=dict(complete_phase_names=list(data['reports']), protected_sources_unchanged=True,
                        paired_ids_valid=True, identical_output_metric_equality_valid=True),
        method=dict(delta='detailed minus short', aggregate='macro mean of per-article scores',
                    bootstrap='paired article-level nonparametric percentile bootstrap; 95% pointwise CIs',
                    bootstrap_resamples=resamples, seed=seed, random_generator='numpy.default_rng PCG64',
                    quantile_method='linear', draws_shared_across_metrics=True, tie_definition='exact numerical equality',
                    changed_subset='Post-selection descriptive view only; no inferential CI.',
                    references='GPT and Gemini separate; per-article equal-weight mean is secondary; no best-reference selection.',
                    inference_scope='Empirical article variation only; not model training, references, topics, or run randomness.',
                    multiplicity='CIs are pointwise, without multiplicity correction; no p-values or overall quality claim.'),
        input_sha256=data['manifest']['input_manifest_sha256'],
        phase_artifact_sha256=data['hashes'], script_sha256=digest(Path(__file__)),
        evaluator_limits=dict(
            bertscore_truncated_texts=data['reports']['reference']['evaluator_input_truncations'],
            alignscore_internal_chunk_pairs=data['reports']['alignscore']['sentence_chunk_pairs_total'],
            alignscore_internal_chunk_pairs_truncated=data['reports']['alignscore']['sentence_chunk_pairs_over_model_limit_total'],
            alignscore_unique_pairs_with_internal_truncation=data['reports']['alignscore']['pairs_with_official_chunk_token_truncation']),
        numpy_version=np.__version__, records=records, reference_readability_baselines=baseline)
    return report, summaries, differences, merged


def metric_label(metric: str, ref: str) -> str:
    labels = {'rouge1_f1': 'ROUGE-1 F1', 'rouge2_f1': 'ROUGE-2 F1', 'rougeL_f1': 'ROUGE-L F1',
              'bertscore_f1': 'BERTScore F1', 'alignscore': 'AlignScore', 'fkgl': 'FKGL'}
    return labels.get(metric, metric) + (f' / {ref.upper()}' if ref in REFERENCES else '')


def result_table(records: list, subset: str) -> list[str]:
    lines = ['| Metric | Short | Detailed | Detailed − short | Paired 95% CI | Wins / ties / losses |',
             '| --- | ---: | ---: | ---: | --- | ---: |']
    for metric, ref in PRIMARY_METRICS:
        row = next(r for r in records if r['subset'] == subset and r['metric'] == metric and r['reference'] == ref)
        low, high = row['bootstrap_95_percent_ci']
        arrow = '↓' if metric == 'fkgl' else '↑'
        delta_display = (f"{row['mean_delta']:+.2e}" if 0 < abs(row['mean_delta']) < .00005
                         else f"{row['mean_delta']:+.4f}")
        lines.append(f"| {metric_label(metric, ref)} {arrow} | {row['short_mean']:.4f} | {row['detailed_mean']:.4f} | "
            f"{delta_display} | [{low:+.4f}, {high:+.4f}] | "
            f"{row['detailed_wins']} / {row['exact_ties']} / {row['detailed_losses']} |")
    return lines


def make_readme(run: Path, data: dict, report: dict) -> None:
    records = report['records']
    truncated_indices = ', '.join(f'#{i}' for i in report['truncated_source_indices']) or 'none'
    settings = data['manifest']['generation_settings']
    reference_config = data['reports']['reference']
    align_config = data['reports']['alignscore']
    lines = [
        '# Paired evaluation of the two RS FLAN prompts', '',
        f"Both saved prompt runs were evaluated on the same {report['article_count']} articles, against separate GPT and Gemini AI-generated references. "
        f"{report['identical_summary_pairs']} summary pairs are exactly identical and {report['changed_summary_pairs']} differ. "
        'No summaries, article bodies, or references were edited for evaluation.', '',
        '## Main results', '',
        'Scores are macro means over all 73 articles. ROUGE, BERTScore, and AlignScore use their raw scale; FKGL uses estimated US school grade. '
        'Arrows show the preferred metric direction. Wins/ties/losses describe the detailed prompt relative to the short prompt; for FKGL a lower value counts as a metric win.', '',
        *result_table(records, 'all_articles'), '',
        'The reference-agreement changes are small and mixed: all eight F1 confidence intervals include zero. '
        'The detailed prompt has a slightly higher mean AlignScore, but its change interval also includes zero. '
        'Its mean FKGL is about 0.34 grades lower, with a paired interval below zero. '
        'This supports a small reduction in estimated surface difficulty on these articles, while the evaluation does not establish an overall winning prompt. '
        'The 72-article sensitivity analysis gives the same interpretation.', '',
        'The confidence intervals describe the mean paired change, not uncertainty for individual summaries. '
        'A small favorable change in an automatic metric does not establish overall summary quality or beginner understanding. '
        'Table means are rounded; CSV and JSON values retain full precision.', '',
        '## Sensitivity to input truncation', '',
        f'Articles with any generation-input truncation: {truncated_indices}. '
        'The detailed prompt made article #29 exceed the 3072-token input limit (3266 original tokens; 194 removed). '
        'Both conditions produced the same summary for this article. The following table removes this paired article from both conditions (72 articles). '
        'AlignScore still uses the full frozen article as the source in the main and sensitivity analyses.', '',
        *result_table(records, 'no_input_truncation'), '',
        '## Readability components and output length', '',
        '| Descriptive measure | Short mean | Detailed mean |', '| --- | ---: | ---: |',
    ]
    for metric in ('word_count', 'sentence_count', 'words_per_sentence', 'syllables_per_word', 'generated_tokens_including_eos'):
        row = next(r for r in records if r['subset'] == 'all_articles' and r['metric'] == metric)
        lines.append(f"| {metric} | {row['short_mean']:.4f} | {row['detailed_mean']:.4f} |")
    counts = {}
    for condition in CONDITIONS:
        rows = [data['scores']['readability'][a, condition] for a in data['ids']]
        counts[condition] = sum(row['two_to_three_sentences'] for row in rows)
    lines.extend(['', f"The textstat sentence heuristic counted 2–3 sentences for {counts['short']}/73 short-prompt and "
        f"{counts['detailed']}/73 detailed-prompt summaries. Abbreviations and decimal numbers can split sentences; "
        'this is an algorithmic count rather than a grammatical compliance assessment.', '',
        'Both generation runs used max_new_tokens=192, and neither hit that output ceiling. '
        'Natural model termination does not guarantee complete or useful prose; existing ellipses, output labels, and incomplete fragments remain in the scored strings.', '',
        '| AI reference baseline | Mean word count | Mean FKGL |', '| --- | ---: | ---: |'])
    for ref in REFERENCES:
        means = {r['metric']: r['mean'] for r in report['reference_readability_baselines'] if r['reference_model'] == ref}
        lines.append(f"| {ref.upper()} | {means['word_count']:.4f} | {means['fkgl']:.4f} |")
    lines.extend(['',
        'These reference readability values are descriptive baselines. They are not validated readability targets; the two references differ in length and style.', '',
        '## Methods and interpretation', '',
        '- **Reference agreement:** ROUGE-1/2/L and BERTScore precision, recall, and F1 are computed independently against GPT and Gemini. '
        'The primary table reports F1; all components are in the CSV/JSON files. A secondary per-article equal-weight mean of the two reference scores is explicitly labeled. '
        'References are never concatenated or selected by whichever gives the better score. Neither reference is human gold.',
        f"- **ROUGE:** rouge-score {reference_config['versions']['rouge-score']}, stemming enabled; macro average of per-article scores.",
        f"- **BERTScore:** bert-score {reference_config['versions']['bert-score']}; roberta-large layer 17, no IDF, no baseline rescaling, slow tokenizer, CPU. "
        f"Configuration hash: `{reference_config['bertscore']['configuration_hash']}`. No evaluator text was truncated "
        f"(maximum {reference_config['evaluator_max_text_tokens']} tokens; evaluator limit 512).",
        '- **Source consistency:** AlignScore compares each unchanged candidate to the full frozen article, independently of the GPT/Gemini references. '
        'Its 0–1 output estimates source alignment; it is not a percentage of correct facts and cannot verify whether the article itself is true. '
        'A copied passage can score well while omitting essential context or retaining difficult terminology.',
        f"- **AlignScore runtime and internal limit:** AlignScore-large uses the official `nli_sp` method from commit `{align_config['official_commit']}`: "
        'source chunks based on 350 whitespace words, summary sentence splitting, maximum entailment over source chunks per summary sentence, '
        'then a mean over summary sentences. Full documents enter this pipeline without a manual cutoff. '
        f"The official tokenizer internally truncated {align_config['sentence_chunk_pairs_over_model_limit_total']} of "
        f"{align_config['sentence_chunk_pairs_total']} sentence/chunk pairs at 512 tokens, affecting "
        f"{align_config['pairs_with_official_chunk_token_truncation']} of 91 unique article/summary pairs. "
        'This evaluator-internal limit is distinct from the one FLAN generation-input truncation at article #29. '
        'A compatibility adapter bypasses training-only dependencies and unused computation; all 404 state tensors (403 parameter tensors) were verified against the checkpoint, '
        'and the classification outputs matched the original full forward bitwise in the recorded parity check. Exact provenance is in alignscore_report.json.',
        '- **Surface readability:** unrounded English FKGL is computed on the exact saved summary using textstat 0.7.10. '
        'Formula: `0.39 × words/sentences + 11.8 × syllables/words − 15.59`. Lower values indicate lower estimated surface reading difficulty. '
        'FKGL does not measure factuality, completeness, coherence, jargon explanation, or actual beginner comprehension. '
        'Word, sentence, and syllable counts are retained because short texts, names, abbreviations, and numbers affect the result.',
        f"- **Pairing and uncertainty:** {report['method']['bootstrap_resamples']:,} article-level bootstrap resamples, seed {report['method']['seed']}, "
        'percentile 95% intervals (NumPy linear quantiles). Each resample keeps both prompt outputs and both reference scores together. '
        'The same bootstrap draws are used across metrics within each subset. All 55 identical pairs retain exact score ties. '
        'Intervals are pointwise, with no multiplicity adjustment or p-values; no combined quality score is calculated.',
        '- **Scope:** these articles were used during prompt development, so this is a development-set comparison rather than a held-out test. '
        'Intervals describe variation across the sampled articles only. They do not account for reference-generation choices, model-training uncertainty, repeated events, or topic/source clustering. '
        'The 18 changed outputs are also summarized separately for description only, because selecting changes after generation cannot support a general prompt-effect claim.', '',
        '## Relationship to existing studies', '',
        'This separates reference agreement, readability, and source consistency in the same broad manner as the '
        '[BioLaySumm 2024 evaluation](https://aclanthology.org/2024.bionlp-1.10.pdf), which uses ROUGE/BERTScore, readability measures including FKGL, '
        'and factuality measures including AlignScore. Its biomedical task differs from cryptocurrency news, so its usage supports the method choice rather than validating these scores for this domain. '
        'The paper also notes that highly extractive outputs can be favored by factuality metrics.', '',
        '[AlignScore (Zha et al., 2023)](https://aclanthology.org/2023.acl-long.634/) introduces the learned information-alignment metric. '
        '[Tanprasert and Kauchak (2021)](https://aclanthology.org/2021.gem-1.1/) demonstrate that FKGL can be manipulated and recommend examining component statistics. '
        'Accordingly FKGL is used here as a diagnostic surface measure. '
        '[Dror et al. (2018)](https://aclanthology.org/P18-1128/) discuss choosing statistical comparisons that match the NLP experimental design; '
        'the paired article bootstrap here preserves the shared inputs.', '',
        '## Reproducibility and files', '',
        f"Generation checkpoint: `{settings['model_checkpoint']}` at `{settings['cached_revision']}`; input limit {settings['max_input_tokens']}, "
        f"output limit {settings['initial_max_new_tokens']}, deterministic beam search with {settings['fixed_generation_kwargs']['num_beams']} beams. "
        'Prompt strings and generation settings are recorded in evaluation_manifest.json.', '',
        '- `per_article_evaluation.csv`: 146 candidate rows, exact summary/reference text, all primary metric components, input truncation flags, and readability diagnostics.',
        '- `paired_differences.csv`: one row per article/metric/reference with both scores and the detailed-minus-short change.',
        '- `evaluation_summary.csv`: all metric components by condition, reference, and subset, including descriptive 18-changed-output results.',
        '- `paired_statistics.json`: paired changes, bootstrap intervals, wins/ties/losses, baseline reference readability, and validation/provenance hashes.',
        '- `reference_metric_scores.json`, `alignscore_scores.json`, `readability_scores.json`, `reference_readability.json`: unchanged phase results.',
        '- `reference_metrics_report.json`, `alignscore_report.json`, `readability_report.json`: exact scorer configurations, model/resource versions, and runtime compatibility details.',
        '- `reference_summaries_frozen.csv`, `evaluation_inputs.json`, `evaluation_manifest.json`: frozen input and source provenance.', '',
        'Aggregation command (from the project root):', '',
        '```bash', f'.venv/bin/python summarize_rs_dual_evaluation.py --run-dir {run.relative_to(ROOT)}', '```', '',
        'The aggregation validates all phase statuses, candidate/reference coverage, protected source hashes, and score equality for identical outputs before writing derived reports.',
    ])
    # Keep the full adaptation report accessible instead of silently implying the historical runtime was used unchanged.
    lines.extend(['', 'AlignScore runtime note: consult `alignscore_report.json` for the official checkpoint, inference adapter, '
                  'parameter-loading audit, and forward-parity checks. The original training runtime is not required for inference.'])
    (run / 'README.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def make_chart(run: Path, report: dict) -> None:
    os.environ.setdefault('MPLCONFIGDIR', str(ROOT / 'output/flan_evaluation/runtime_caches/matplotlib'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator
    rows = [next(r for r in report['records'] if r['subset'] == 'all_articles' and r['metric'] == metric
                 and r['reference'] == ref) for metric, ref in PRIMARY_METRICS]
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 6.8), gridspec_kw={'width_ratios': [2.6, 1]}, constrained_layout=True)
    fig.patch.set_facecolor('#faf9f6')
    fig.suptitle('Change from the short prompt to the detailed prompt', fontsize=17, fontweight='bold', x=.04, ha='left')
    for ax, group in zip(axes, (rows[:-1], rows[-1:]), strict=True):
        ax.set_facecolor('#faf9f6')
        for i, row in enumerate(group):
            low, high = row['bootstrap_95_percent_ci']
            mean = row['mean_delta']
            ax.errorbar(mean, i, xerr=np.array([[mean-low], [high-mean]]), fmt='o', color='#246b81',
                        ecolor='#246b81', capsize=4, markersize=6, linewidth=1.8)
        ax.set_yticks(range(len(group)), [metric_label(r['metric'], r['reference']) for r in group])
        ax.invert_yaxis()
        ax.axvline(0, color='#8d8d8d', linestyle='--', linewidth=1)
        ax.grid(axis='x', alpha=.17)
        ax.spines[['top', 'right', 'left']].set_visible(False)
        ax.tick_params(axis='y', length=0, labelsize=10)
        ax.xaxis.set_major_locator(MaxNLocator(5))
    axes[0].set_title('Reference agreement and source alignment\nHigher values are favorable', fontsize=11, loc='left', pad=18)
    axes[1].set_title('Surface reading difficulty\nLower values are favorable', fontsize=11, loc='left', pad=18)
    axes[0].set_xlabel('Detailed − short (raw score units)')
    axes[1].set_xlabel('Detailed − short (FKGL grades)')
    axes[1].set_ylim(1, -1)
    fig.supxlabel(f"{report['article_count']} paired articles · 95% article-bootstrap intervals · {report['method']['bootstrap_resamples']:,} resamples · {report['identical_summary_pairs']} identical summaries\n"
                  'Automatic proxies; these values do not establish factual accuracy or beginner comprehension.', fontsize=9)
    fig.savefig(run / 'metric_comparison.png', dpi=180, bbox_inches='tight', facecolor=fig.get_facecolor())
    fig.savefig(run / 'metric_comparison.svg', bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, default=DEFAULT_RUN)
    parser.add_argument('--resamples', type=int, default=10000)
    parser.add_argument('--seed', type=int, default=20261101)
    parser.add_argument('--validate-available', action='store_true', help='Validate existing phases without writing aggregation outputs.')
    parser.add_argument('--no-chart', action='store_true')
    args = parser.parse_args()
    if args.resamples < 1000:
        parser.error('--resamples must be at least 1000')
    run = args.run_dir.resolve()
    data = validate_inputs(run, require_all_phases=not args.validate_available)
    if args.validate_available:
        print(json.dumps(dict(status='validated_available', article_count=len(data['ids']),
                              complete_phases=list(data['reports']), missing_phases=data['missing_phases'],
                              identical_output_pairs=len(data['identical']))))
        return
    report, summaries, differences, merged = aggregate(data, args.resamples, args.seed)
    write_csv(run / 'evaluation_summary.csv', summaries)
    write_csv(run / 'paired_differences.csv', differences)
    write_csv(run / 'per_article_evaluation.csv', merged)
    write_json(run / 'paired_statistics.json', report)
    make_readme(run, data, report)
    if not args.no_chart:
        make_chart(run, report)
    print(json.dumps(dict(status='complete', article_count=report['article_count'],
                          paired_metric_records=len(report['records']), output_dir=str(run))))


if __name__ == '__main__':
    main()

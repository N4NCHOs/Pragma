"""Freeze and score the two saved RS FLAN runs against both supplied references.

This runner never generates summaries or changes the source/reference files.
AlignScore and FKGL are separate workers so their dependencies stay isolated.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
from time import perf_counter
from typing import Any

from pipeline_experiment_data import atomic_write_json, compute_dataset_hash

ROOT = Path(__file__).resolve().parent
REFERENCE = Path('/Users/mumu/Downloads/flan_dual_reference_summaries_20261101.csv')
RUNS = {
    'short': ROOT / 'output/flan_evaluation/rs_output_lengths/run_20261101T125023_557980Z',
    'detailed': ROOT / 'output/flan_evaluation/rs_output_lengths/run_20261101T130452_832310Z',
}
FIELDS = ['id', 'title', 'article_text', 'gpt_reference_summary', 'gemini_reference_summary']
MODEL = 'roberta-large'
REVISION = '722cf37b1afa9454edce342e7895e588b6ff1d59'


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def prepare(destination: Path) -> dict[str, Any]:
    protected = {str(REFERENCE): sha(REFERENCE.read_bytes())}
    with REFERENCE.open(encoding='utf-8-sig', newline='') as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != FIELDS:
            raise ValueError(f'unexpected reference columns: {reader.fieldnames}')
        references = list(reader)
    if len(references) != 73 or len({r['id'] for r in references}) != 73:
        raise ValueError('expected 73 unique reference IDs')
    if not all(all(isinstance(r[field], str) and r[field].strip() for field in FIELDS) for r in references):
        raise ValueError('empty reference field')
    reference_by_id = {r['id']: r for r in references}
    inputs = []
    settings = None
    ordered_ids = None
    run_info = {}
    for condition, directory in RUNS.items():
        report = json.loads((directory / 'run_report.json').read_bytes())
        articles = json.loads((directory / 'selected_articles.json').read_bytes())
        summaries = json.loads((directory / 'summaries.json').read_bytes())
        if report['status'] != 'complete' or len(articles) != len(summaries) or len(articles) != 73:
            raise ValueError(f'incomplete generation run: {condition}')
        if compute_dataset_hash(articles) != report['frozen_articles_sha256']:
            raise ValueError(f'frozen source hash mismatch: {condition}')
        if sha((directory / 'prompt_template.txt').read_bytes()) != report['prompt_sha256']:
            raise ValueError(f'prompt hash mismatch: {condition}')
        current_settings = {key: report[key] for key in ('model_checkpoint', 'cached_revision', 'max_input_tokens',
                            'initial_max_new_tokens', 'fixed_generation_kwargs', 'seed', 'cpu_threads', 'device', 'dtype')}
        if settings is not None and current_settings != settings:
            raise ValueError('generation settings differ between conditions')
        settings = current_settings
        ids = [a['id'] for a in articles]
        if ordered_ids is not None and ids != ordered_ids:
            raise ValueError('generation ID order differs')
        ordered_ids = ids
        if ids != [s['id'] for s in summaries] or set(ids) != set(reference_by_id):
            raise ValueError('candidate/reference ID mismatch')
        for article, summary in zip(articles, summaries, strict=True):
            reference = reference_by_id[article['id']]
            if reference['title'] != article['title'] or reference['article_text'] != article['article_text']:
                raise ValueError(f'reference/source text mismatch for {article["id"]}')
            if summary.get('error') or not summary['summary'].strip() or summary['max_new_tokens'] != 192:
                raise ValueError(f'invalid candidate for {article["id"]}')
            inputs.append({
                'id': article['id'], 'source_index': article['source_index'], 'prompt_condition': condition,
                'title': article['title'], 'url': article['url'], 'article_text': article['article_text'],
                'summary': summary['summary'], 'gpt_reference_summary': reference['gpt_reference_summary'],
                'gemini_reference_summary': reference['gemini_reference_summary'],
                'input_token_count': summary['input_token_count'],
                'original_input_token_count': summary['original_input_token_count'],
                'input_was_truncated': summary['input_was_truncated'],
                'generated_tokens_including_eos': summary['generated_new_tokens_including_eos'],
            })
        for name in ('run_report.json', 'selected_articles.json', 'summaries.json', 'prompt_template.txt'):
            path = directory / name
            protected[str(path)] = sha(path.read_bytes())
        run_info[condition] = {'path': str(directory), 'prompt_sha256': report['prompt_sha256']}
    destination.mkdir(parents=True, exist_ok=False)
    (destination / 'reference_summaries_frozen.csv').write_bytes(REFERENCE.read_bytes())
    atomic_write_json(destination / 'evaluation_inputs.json', inputs, indent=2)
    manifest = {
        'status': 'prepared', 'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'output_dir': str(destination), 'reference_source': str(REFERENCE),
        'reference_sha256': protected[str(REFERENCE)], 'source_hashes': protected,
        'generation_runs': run_info, 'generation_settings': settings,
        'article_count': 73, 'candidate_count': len(inputs), 'reference_comparisons': len(inputs) * 2,
        'unique_article_summary_pairs': len({(r['id'], r['summary']) for r in inputs}),
        'input_manifest_sha256': sha((destination / 'evaluation_inputs.json').read_bytes()),
        'notes': ['Two AI-generated silver references, not human gold.',
                  'All articles are scored against full frozen source; truncated generation inputs remain flagged.',
                  'Same-text per-article candidates share deterministic metric values.',
                  'This is automatic evaluation without human comprehension or factuality validation.'],
    }
    atomic_write_json(destination / 'evaluation_manifest.json', manifest, indent=2)
    print(f'EVALUATION_DIR={destination}', flush=True)
    return manifest


def score_reference_metrics(destination: Path) -> dict[str, Any]:
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ.setdefault('MPLCONFIGDIR', str(ROOT / 'output/flan_evaluation/runtime_caches/matplotlib'))
    import torch
    from bert_score import BERTScorer
    from huggingface_hub import try_to_load_from_cache
    from rouge_score.rouge_scorer import RougeScorer

    inputs = json.loads((destination / 'evaluation_inputs.json').read_bytes())
    manifest = json.loads((destination / 'evaluation_manifest.json').read_bytes())
    if sha((destination / 'evaluation_inputs.json').read_bytes()) != manifest['input_manifest_sha256']:
        raise ValueError('frozen evaluation inputs changed')
    cached = try_to_load_from_cache(MODEL, 'config.json')
    if not isinstance(cached, str) or Path(cached).parent.name != REVISION:
        raise ValueError('unexpected cached BERTScore model revision')
    torch.set_num_threads(4)
    torch.manual_seed(0)
    unique = {}
    for row in inputs:
        for reference in ('gpt', 'gemini'):
            key = (row['id'], row['summary'], row[f'{reference}_reference_summary'])
            unique.setdefault(key, {'summary': row['summary'], 'reference': row[f'{reference}_reference_summary']})
    tasks = list(unique.values())
    print(f'ROUGE/BERTScore: {len(tasks)} unique comparisons mapped to {len(inputs)*2} rows.', flush=True)
    rouge = RougeScorer(['rouge1', 'rouge2', 'rougeL'], use_stemmer=True)
    scored = []
    for task in tasks:
        values = {}
        for metric, score in rouge.score(task['reference'], task['summary']).items():
            for suffix, value in (('precision', score.precision), ('recall', score.recall), ('f1', score.fmeasure)):
                values[f'{metric}_{suffix}'] = float(value)
        scored.append(values)
    started = perf_counter()
    scorer = BERTScorer(model_type=MODEL, num_layers=17, batch_size=4, nthreads=4, device='cpu',
                        lang='en', idf=False, rescale_with_baseline=False, use_fast_tokenizer=False)
    candidates = [task['summary'] for task in tasks]
    references = [task['reference'] for task in tasks]
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=REVISION, local_files_only=True, use_fast=False)
    lengths = [len(tokenizer(text, truncation=False, verbose=False)['input_ids']) for text in candidates + references]
    if max(lengths) > tokenizer.model_max_length:
        raise ValueError('BERTScore evaluator would truncate candidate/reference')
    (p, r, f), configuration_hash = scorer.score(candidates, references, batch_size=4, verbose=True, return_hash=True)
    for values, precision, recall, f1 in zip(scored, p.tolist(), r.tolist(), f.tolist(), strict=True):
        values.update(bertscore_precision=precision, bertscore_recall=recall, bertscore_f1=f1)
    lookup = dict(zip(unique, scored, strict=True))
    results = []
    for row in inputs:
        for reference in ('gpt', 'gemini'):
            key = (row['id'], row['summary'], row[f'{reference}_reference_summary'])
            results.append({'id': row['id'], 'source_index': row['source_index'], 'title': row['title'],
                            'prompt_condition': row['prompt_condition'], 'reference_model': reference,
                            **lookup[key]})
    atomic_write_json(destination / 'reference_metric_scores.json', results, indent=2)
    with (destination / 'reference_metric_scores.csv').open('w', encoding='utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=list(results[0]))
        writer.writeheader(); writer.writerows(results)
    report = {
        'status': 'complete', 'row_count': len(results), 'unique_scored_pairs': len(tasks),
        'bertscore': {'model_type': MODEL, 'cached_revision': REVISION, 'num_layers': 17, 'idf': False,
                      'rescale_with_baseline': False, 'use_fast_tokenizer': False, 'device': 'cpu',
                      'batch_size': 4, 'configuration_hash': configuration_hash},
        'rouge': {'metrics': ['rouge1', 'rouge2', 'rougeL'], 'use_stemmer': True},
        'evaluator_max_text_tokens': max(lengths), 'evaluator_input_truncations': 0,
        'versions': {name: version(name) for name in ('bert-score', 'rouge-score', 'torch', 'transformers')},
        'elapsed_seconds': perf_counter() - started,
    }
    atomic_write_json(destination / 'reference_metrics_report.json', report, indent=2)
    for path, digest in manifest['source_hashes'].items():
        if sha(Path(path).read_bytes()) != digest:
            raise ValueError(f'protected source changed: {path}')
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--prepared-dir', type=Path, help='score a previously frozen evaluation directory')
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    if args.prepared_dir:
        destination = args.prepared_dir.resolve(strict=True)
    else:
        destination = (args.output_dir or ROOT / 'output/flan_evaluation/dual_reference_evaluation' /
                       f'run_{datetime.now(timezone.utc):%Y%m%dT%H%M%S_%fZ}').resolve()
        prepare(destination)
    if not args.prepare_only:
        score_reference_metrics(destination)


if __name__ == '__main__':
    main()

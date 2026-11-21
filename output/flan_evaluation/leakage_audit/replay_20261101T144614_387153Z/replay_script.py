"""Independent replay: raw RS JSON and saved prompts only enter the model.

Does not import project runners/helpers, load references, or read saved outputs.
Comparison with prior results is performed separately after this process ends.
"""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

ROOT = Path('/Users/mumu/Thesis Folder/Thesis Test/Pragma')
BASE = ROOT / 'output/flan_evaluation/rs_output_lengths'
RUNS = {
    'short': BASE / 'run_20261101T125023_557980Z',
    'detailed': BASE / 'run_20261101T130452_832310Z',
}
DATASET = ROOT / 'output/rss_meter_audit/url_lists_20261031_175332_160464_utc/output/rss_pruned_RS/scraped_news.json'
REVISION = '7bcac572ce56db69c1ea7c8af255c5d7c9672fc2'
POSITIONS = (1, 2, 4, 28, 3, 37)

started = perf_counter()
destination = ROOT / 'output/flan_evaluation/leakage_audit' / f'replay_{datetime.now(timezone.utc):%Y%m%dT%H%M%S_%fZ}'
destination.mkdir(parents=True, exist_ok=False)
articles = json.loads(DATASET.read_bytes())
prompts = {key: (directory / 'prompt_template.txt').read_text() for key, directory in RUNS.items()}
report = {
    'status': 'running', 'created_at_utc': datetime.now(timezone.utc).isoformat(),
    'output_dir': str(destination), 'positions': list(POSITIONS),
    'prompt_order': ['detailed', 'short'], 'model': 'google/flan-t5-base',
    'revision': REVISION, 'input_limit': 3072, 'max_new_tokens': 192,
    'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'dataset_sha256': hashlib.sha256(DATASET.read_bytes()).hexdigest(),
    'notes': [
        'Fresh process and model load; direct Transformers generation, no project generation helpers.',
        'Only raw article title/body plus its saved instruction prompt enters the model.',
        'No previous outputs or GPT/Gemini reference files read during generation.',
        'Detailed prompt is run before short prompt, reversing historical run order.',
        'Positions1,2,4,28 test identical cases;3,37 are changed-output controls.',
    ],
}
rows = []

def save():
    report['elapsed_seconds'] = perf_counter() - started
    (destination / 'replay_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    (destination / 'fresh_outputs.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n')

save()
print(f'AUDIT_DIR={destination}', flush=True)
torch.set_num_threads(4)
torch.manual_seed(0)
tokenizer = AutoTokenizer.from_pretrained('google/flan-t5-base', revision=REVISION, local_files_only=True)
model = AutoModelForSeq2SeqLM.from_pretrained('google/flan-t5-base', revision=REVISION, local_files_only=True)
model.to('cpu').eval()

for position in POSITIONS:
    article = articles[position - 1]
    for name in ('detailed', 'short'):
        formatted = prompts[name].format(article_text=f"{article['title']}. {article['full_body']}".strip())
        encoded = tokenizer(formatted, max_length=3072, truncation=True, return_tensors='pt', verbose=False)
        generation_start = perf_counter()
        with torch.inference_mode():
            result = model.generate(
                **encoded, do_sample=False, num_beams=4, max_new_tokens=192,
                early_stopping=True, no_repeat_ngram_size=3,
                return_dict_in_generate=True, output_scores=True,
            )
        sequence = result.sequences[0].tolist()
        assert sequence[0] == model.generation_config.decoder_start_token_id
        selected = sequence[1:]
        eos_id = model.generation_config.eos_token_id
        assert eos_id in selected
        selected = selected[:selected.index(eos_id) + 1]
        summary = tokenizer.decode(selected, skip_special_tokens=True, clean_up_tokenization_spaces=True).strip()
        row = {
            'position': position, 'url': article['url'], 'title': article['title'], 'prompt': name,
            'prompt_sha256': hashlib.sha256(prompts[name].encode()).hexdigest(),
            'formatted_input_sha256': hashlib.sha256(formatted.encode()).hexdigest(),
            'input_token_ids_sha256': hashlib.sha256(json.dumps(encoded['input_ids'][0].tolist()).encode()).hexdigest(),
            'input_tokens': int(encoded['attention_mask'].sum().item()),
            'summary': summary, 'selected_token_ids': selected,
            'generated_tokens_including_eos': len(selected),
            'inference_seconds': perf_counter() - generation_start,
        }
        rows.append(row)
        save()
        print(f"[{len(rows)}/12] article={position} prompt={name} tokens={len(selected)}", flush=True)

report['status'] = 'complete'
report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
save()
print(json.dumps({'output_dir': str(destination), 'status': report['status'], 'fresh_generations': len(rows)}), flush=True)

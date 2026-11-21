"""Measure natural FLAN summary lengths on the frozen current RS articles.

Uses the user's new prompt, a 3072-token input ceiling, and an initial 192-token
output ceiling. Only capped/ambiguous outputs are retried at higher ceilings.
No scraping, database access, reference generation, or production changes.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import csv
import hashlib
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from typing import Any

from pipeline_experiment_data import atomic_write_json, compute_dataset_hash
from run_flan_output_comparison import _generate


ROOT = Path(__file__).resolve().parent
DATASET = ROOT / "output/rss_meter_audit/url_lists_20261031_175332_160464_utc/output/rss_pruned_RS/scraped_news.json"
ID_SOURCE = ROOT / "output/rss_dataset_recovered/qualified_news.json"
MODEL = "google/flan-t5-base"
REVISION = "7bcac572ce56db69c1ea7c8af255c5d7c9672fc2"
INPUT_LIMIT = 3072
OUTPUT_LIMITS = (192, 256, 384, 512)
CPU_THREADS = 4
PROMPT = """Summarize the following cryptocurrency news for readers with no knowledge of cryptocurrency, blockchain, or finance.
Write 2–3 short sentences that clearly explain what happened, who was involved, and the most important facts.
Use simple everyday language. Briefly explain unfamiliar technical concepts when necessary for understanding.
Preserve important names, numbers, and facts. Distinguish confirmed information from claims or possibilities.
Only include information supported by the article. Do not invent explanations, speculate about consequences, or provide investment advice.
Output only the summary.
Article:
{article_text}
Summary:"""


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def distribution(values: list[int]) -> dict[str, Any]:
    if not values:
        return {}
    ordered = sorted(values)
    return {
        "minimum": ordered[0], "mean": mean(values), "median": median(values),
        "p90_nearest_rank": ordered[math.ceil(.90 * len(values)) - 1],
        "p95_nearest_rank": ordered[math.ceil(.95 * len(values)) - 1],
        "maximum": ordered[-1], "total": sum(values),
    }


def summarize(rows: list[dict[str, Any]], articles: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [row for row in rows if row.get("error") is None]
    initial = [row for row in successful if row["max_new_tokens"] == OUTPUT_LIMITS[0]]
    latest = {row["id"]: row for row in successful}
    completed = [row for row in latest.values() if row["stop_reason"] == "eos_before_limit"]
    return {
        "article_count": len(articles), "completed_initial_trials": len(initial),
        "generation_attempts": len(rows), "errors": sum(row.get("error") is not None for row in rows),
        "initial_stop_reasons": dict(Counter(row["stop_reason"] for row in initial)),
        "initial_content_tokens": distribution([row["output_token_count"] for row in initial]),
        "initial_generated_tokens_including_eos": distribution([row["generated_new_tokens_including_eos"] for row in initial]),
        "natural_completion_count": len(completed),
        "unresolved_article_ids": [article["id"] for article in articles if article["id"] not in {row["id"] for row in completed}],
        "natural_content_tokens": distribution([row["output_token_count"] for row in completed]),
        "natural_generated_tokens_including_eos": distribution([row["generated_new_tokens_including_eos"] for row in completed]),
        "observed_natural_lengths_within_ceiling": {
            str(limit): sum(row["generated_new_tokens_including_eos"] <= limit for row in completed)
            for limit in (64, 96, 128, 160, 192)
        },
        "longest_naturally_completed": sorted(completed, key=lambda row: row["generated_new_tokens_including_eos"], reverse=True)[:10],
    }


def run(destination: Path, *, prompt: str = PROMPT, prompt_path: Path | None = None) -> dict[str, Any]:
    if prompt.count("{article_text}") != 1:
        raise ValueError("prompt must contain exactly one {article_text} placeholder")
    prompt.format(article_text="")
    sources = {DATASET: DATASET.read_bytes(), ID_SOURCE: ID_SOURCE.read_bytes(),
               ROOT / "ai_models/flan_t5.py": (ROOT / "ai_models/flan_t5.py").read_bytes(),
               ROOT / "run_flan_output_comparison.py": (ROOT / "run_flan_output_comparison.py").read_bytes(),
               ROOT / "run_flan_output_pilot.py": (ROOT / "run_flan_output_pilot.py").read_bytes()}
    if prompt_path is not None:
        sources[prompt_path] = prompt_path.read_bytes()
        if sources[prompt_path].decode("utf-8") != prompt:
            raise ValueError("prompt text differs from its source file")
    current = json.loads(sources[DATASET])
    recovered = json.loads(sources[ID_SOURCE])
    by_url = {article["url"]: article for article in recovered}
    if len(current) != 73 or len({article["url"] for article in current}) != 73:
        raise ValueError("expected the current 73 unique RS articles")
    if len(by_url) != 73 or set(by_url) != {article["url"] for article in current}:
        raise ValueError("RS URLs and original dataset identity mapping differ")
    articles = []
    for index, article in enumerate(current, 1):
        if not all(isinstance(article.get(key), str) and article[key].strip() for key in ("title", "full_body")):
            raise ValueError(f"missing title/body at RS record {index}")
        identity = by_url[article["url"]]["dataset_article_id"]
        article_text = f"{article['title']}. {article['full_body']}".strip()
        articles.append({"id": identity, "source_index": index, **article,
                         "article_text": article_text, "article_text_sha256": digest(article_text.encode())})
    if len({article["id"] for article in articles}) != 73:
        raise ValueError("missing or duplicate stable article IDs")
    destination.mkdir(parents=True, exist_ok=False)
    report: dict[str, Any] = {
        "status": "preparing", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_dir": str(destination), "dataset_path": str(DATASET), "article_count": len(articles),
        "source_sha256": {str(path): digest(raw) for path, raw in sources.items()},
        "frozen_articles_sha256": compute_dataset_hash(articles),
        "prompt_sha256": digest(prompt.encode()), "prompt_source": str(prompt_path) if prompt_path else "runner default",
        "runner_sha256": digest(Path(__file__).read_bytes()),
        "model_checkpoint": MODEL, "cached_revision": REVISION, "max_input_tokens": INPUT_LIMIT,
        "initial_max_new_tokens": OUTPUT_LIMITS[0], "adaptive_output_ceilings": list(OUTPUT_LIMITS),
        "fixed_generation_kwargs": {"do_sample": False, "num_beams": 4, "early_stopping": True, "no_repeat_ngram_size": 3},
        "seed": 0, "cpu_threads": CPU_THREADS,
        "notes": [
            "Exact user prompt; current RS title plus period plus unmodified full_body.",
            "The 3072-token input limit is fixed; longer prompts may right-truncate inputs, as in the current service.",
            "Only capped/ambiguous outputs are retried; latest naturally completed trial is the final result.",
            "Generated-token budgets include EOS and exclude decoder start; content counts exclude special tokens.",
            "Observed lengths at these ceilings do not prove identical summaries or no truncation at lower ceilings.",
            "EOS completion is not a factuality or sentence-completeness evaluation. No ROUGE/BERTScore is calculated.",
            "All source articles, GPT references, and production model settings remain unchanged.",
        ],
    }
    rows: list[dict[str, Any]] = []
    started = perf_counter()

    def checkpoint() -> None:
        report["elapsed_seconds"] = perf_counter() - started
        report["aggregate"] = summarize(rows, articles)
        atomic_write_json(destination / "generation_metrics.json", rows, indent=2)
        atomic_write_json(destination / "run_report.json", report, indent=2)

    atomic_write_json(destination / "selected_articles.json", articles, indent=2)
    (destination / "prompt_template.txt").write_text(prompt, encoding="utf-8")
    checkpoint()
    print(f"RUN_DIR={destination}", flush=True)
    try:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        torch.set_num_threads(CPU_THREADS)
        torch.manual_seed(0)
        report["torch_version"] = version("torch")
        report["transformers_version"] = version("transformers")
        print("Loading cached FLAN-T5 once; CPU float32, four threads, offline.", flush=True)
        tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=REVISION, local_files_only=True)
        model = AutoModelForSeq2SeqLM.from_pretrained(MODEL, revision=REVISION, local_files_only=True)
        model.to("cpu")
        model.eval()
        report["device"] = str(model.device)
        report["dtype"] = str(next(model.parameters()).dtype)
        report["model_generation_config"] = model.generation_config.to_dict()
        if model.generation_config.forced_eos_token_id is not None:
            raise ValueError("forced EOS would confound natural stopping")
        encodings = []
        for article in articles:
            formatted = prompt.format(article_text=article["article_text"])
            ids = tokenizer(formatted, truncation=False, add_special_tokens=True,
                            return_attention_mask=False, verbose=False)["input_ids"]
            encoded = tokenizer(formatted, max_length=INPUT_LIMIT, truncation=True,
                                return_tensors="pt", verbose=False)
            article["complete_input_tokens"] = len(ids)
            article["consumed_input_tokens"] = int(encoded["attention_mask"].sum().item())
            article["input_was_truncated"] = len(ids) > article["consumed_input_tokens"]
            article["removed_input_tokens"] = len(ids) - article["consumed_input_tokens"]
            if article["consumed_input_tokens"] != min(len(ids), INPUT_LIMIT):
                raise ValueError(f"unexpected encoded input length for {article['id']}")
            if not article["input_was_truncated"] and encoded["input_ids"][0].tolist() != ids:
                raise ValueError(f"unexpected token change for {article['id']}")
            encodings.append(encoded)
        report["input_token_counts"] = distribution([article["complete_input_tokens"] for article in articles])
        report["input_truncated_count"] = sum(article["input_was_truncated"] for article in articles)
        report["input_truncated_articles"] = [
            {key: article[key] for key in ("id", "source_index", "title", "complete_input_tokens", "consumed_input_tokens", "removed_input_tokens")}
            for article in articles if article["input_was_truncated"]
        ]
        report["frozen_articles_sha256"] = compute_dataset_hash(articles)
        atomic_write_json(destination / "selected_articles.json", articles, indent=2)
        report["status"] = "running"
        checkpoint()
        for article, encoded in zip(articles, encodings, strict=True):
            for limit in OUTPUT_LIMITS:
                row = {"id": article["id"], "source_index": article["source_index"],
                       "guid": article["guid"], "url": article["url"], "title": article["title"],
                       "max_input_tokens": INPUT_LIMIT, "input_token_count": article["consumed_input_tokens"],
                       "original_input_token_count": article["complete_input_tokens"], "input_was_truncated": article["input_was_truncated"],
                       "max_new_tokens": limit, "error": None}
                try:
                    row.update(_generate(model, tokenizer, encoded, limit))
                except (RuntimeError, ValueError) as exc:
                    row["error"] = f"{type(exc).__name__}: {exc}"
                rows.append(row)
                checkpoint()
                print(f"[{article['source_index']}/73] cap={limit} tokens={row.get('generated_new_tokens_including_eos')} stop={row.get('stop_reason', row.get('error'))} | {article['title']}", flush=True)
                if row.get("error") or row["stop_reason"] == "eos_before_limit":
                    break
                if row["stop_reason"] == "unexpected_stop":
                    raise RuntimeError(f"unexpected model stopping condition for {article['id']}")
        for path, raw in sources.items():
            if path.read_bytes() != raw:
                raise RuntimeError(f"source changed during generation: {path}")
        report["source_integrity_verified"] = True
        aggregate = summarize(rows, articles)
        report["status"] = "complete" if not aggregate["errors"] and not aggregate["unresolved_article_ids"] else "completed_with_unresolved_cases"
        latest = {row["id"]: row for row in rows}
        final = [latest[article["id"]] for article in articles]
        atomic_write_json(destination / "summaries.json", final, indent=2)
        fields = ["id", "source_index", "title", "summary", "input_token_count", "original_input_token_count", "input_was_truncated", "max_new_tokens", "output_token_count",
                  "generated_new_tokens_including_eos", "eos_found", "stop_reason", "inference_seconds", "error"]
        with (destination / "summaries_and_lengths.csv").open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(final)
    except BaseException as exc:
        report["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        checkpoint()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--prompt-file", type=Path, help="UTF-8 prompt containing exactly one {article_text} placeholder")
    args = parser.parse_args()
    destination = args.output_dir or ROOT / "output/flan_evaluation/rs_output_lengths" / f"run_{datetime.now(timezone.utc):%Y%m%dT%H%M%S_%fZ}"
    prompt_path = args.prompt_file.resolve(strict=True) if args.prompt_file else None
    prompt = prompt_path.read_text(encoding="utf-8") if prompt_path else PROMPT
    report = run(destination.resolve(), prompt=prompt, prompt_path=prompt_path)
    print(json.dumps({"status": report["status"], "output_dir": report["output_dir"],
                      "aggregate": {key: value for key, value in report["aggregate"].items() if key != "longest_naturally_completed"}}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()

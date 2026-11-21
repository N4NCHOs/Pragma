"""Compare output 96/128 against saved output 64 on the same frozen articles.

Input stays 3072. Uses the existing pinned, offline CPU baseline and selected-
sequence EOS audit. Never invokes scraping, a database, or the main pipeline.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any
from zoneinfo import ZoneInfo

from measure_flan_pilot_tokens import read_flan_baseline
from pipeline_experiment_data import atomic_write_json, compute_dataset_hash
from run_flan_output_pilot import _ids, inspect_selected_sequence


ROOT = Path(__file__).resolve().parent
DEFAULT_BASELINE = ROOT / "output/flan_evaluation/input_comparison/run_20261025_012611_as_is_39b89baf"
MAX_INPUT_TOKENS = 3072
NEW_OUTPUT_LIMITS = (96, 128)
ALL_OUTPUT_LIMITS = (64, *NEW_OUTPUT_LIMITS)
CPU_THREADS = 4


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_baseline(directory: Path, source: Path | None = None) -> dict[str, Any]:
    """Validate frozen identities, configuration, source, and original results."""
    folder = directory.resolve(strict=True)
    read = lambda name: json.loads((folder / name).read_text(encoding="utf-8"))
    manifest, context = read("run_manifest.json"), read("execution_context.json")
    articles, metrics = read("selected_articles.json"), read("generation_metrics.json")
    prompt = (folder / "prompt_template.txt").read_text(encoding="utf-8")
    if manifest.get("status") != "complete" or context.get("status") != "complete":
        raise ValueError("baseline generation must be complete")
    count = manifest["article_count"]
    if not articles or len(articles) != count or compute_dataset_hash(articles) != manifest["selected_rows_hash"]:
        raise ValueError("frozen article/reference snapshot hash or count mismatch")
    if len({row["id"] for row in articles}) != count:
        raise ValueError("duplicate frozen article IDs")
    if hashlib.sha256(prompt.encode()).hexdigest() != manifest["prompt_sha256"]:
        raise ValueError("frozen prompt hash mismatch")
    settings = read_flan_baseline(source or ROOT / "ai_models/flan_t5.py")
    expected = {"do_sample": False, "num_beams": 4, "max_new_tokens": 64,
                "early_stopping": True, "no_repeat_ngram_size": 3}
    if (manifest["generation_kwargs"] != expected or settings["generation_settings"] != expected
            or settings["source_sha256"] != context["model_source_sha256"]
            or settings["SUMMARY_PROMPT"] != prompt
            or settings["DEFAULT_MODEL_NAME"] != manifest["model_checkpoint"]):
        raise ValueError("FLAN source/prompt/settings differ from the preserved baseline")
    if context["cpu_threads"] != CPU_THREADS or context["generation_seed"] != 0 or manifest["device"] != "cpu":
        raise ValueError("expected the preserved four-thread CPU, seed-zero baseline")
    expected_trials = count * len(manifest["input_limits"])
    if len(metrics) != expected_trials or manifest["completed_trials"] != expected_trials:
        raise ValueError("incomplete baseline metric cohort")
    previous = [row for row in metrics if row["max_input_tokens"] == MAX_INPUT_TOKENS]
    if [row["id"] for row in previous] != [row["id"] for row in articles]:
        raise ValueError("baseline 3072 IDs/order do not match frozen articles")
    for article, row in zip(articles, previous, strict=True):
        if (row.get("error") is not None or row["input_was_truncated"]
                or row["max_new_tokens"] != 64 or not row["summary"].strip()
                or row["title"] != article["title"]
                or row["input_token_count"] != row["original_input_token_count"]
                or row["original_input_token_count"] > MAX_INPUT_TOKENS
                or hashlib.sha256(article["article_text"].encode()).hexdigest() != article["article_text_sha256"]):
            raise ValueError("invalid or input-truncated baseline row")
    protected = {folder / name for name in (
        "run_manifest.json", "execution_context.json", "selected_articles.json",
        "generation_metrics.json", "prompt_template.txt")}
    for limit, digest in manifest["comparison_csv_hashes"].items():
        path = folder / f"flan_{limit}.csv"
        if file_hash(path) != digest:
            raise ValueError("baseline comparison CSV integrity failure")
        protected.add(path)
    protected.add(source or ROOT / "ai_models/flan_t5.py")
    return {"folder": folder, "manifest": manifest, "context": context,
            "articles": articles, "prompt": prompt, "baseline_rows": previous,
            "protected_hashes": {str(path): file_hash(path) for path in protected}}


def aggregate(rows: list[dict[str, Any]], article_count: int) -> dict[str, Any]:
    """Report limit-without-EOS separately from EOS at the limit and errors."""
    groups = {}
    for limit in ALL_OUTPUT_LIMITS:
        trials = [row for row in rows if row["max_new_tokens"] == limit]
        good = [row for row in trials if row.get("error") is None]
        stops = Counter(row["stop_reason"] for row in good)
        groups[str(limit)] = {
            "expected_articles": article_count, "completed_trials": len(trials),
            "successful_trials": len(good), "errors": len(trials) - len(good),
            "input_truncated_count": sum(row["input_was_truncated"] for row in good),
            "output_limit_without_eos_count": stops["length_limit_without_eos"],
            "eos_at_limit_count": stops["eos_at_limit"],
            "forced_eos_at_limit_count": stops["forced_eos_at_limit"],
            "unexpected_stop_count": stops["unexpected_stop"], "stop_reasons": dict(stops),
            "mean_content_output_tokens": mean(row["output_token_count"] for row in good) if good else None,
            "max_new_tokens_observed": max((row["generated_new_tokens_including_eos"] for row in good), default=None),
            "affected_articles": [{"id": row["id"], "title": row["title"]} for row in good
                                  if row["stop_reason"] == "length_limit_without_eos"],
        }
    return groups


def _generate(model: Any, tokenizer: Any, encoded: Any, limit: int) -> dict[str, Any]:
    import torch

    started = perf_counter()
    with torch.inference_mode():
        output = model.generate(
            **encoded, do_sample=False, num_beams=4, max_new_tokens=limit,
            early_stopping=True, no_repeat_ngram_size=3,
            return_dict_in_generate=True, output_scores=True,
        )
    seconds = perf_counter() - started
    if output.beam_indices is None:
        raise RuntimeError("missing beam ancestry; selected output length cannot be audited")
    audit = inspect_selected_sequence(
        output.sequences[0].tolist(), output.beam_indices[0].tolist(),
        decoder_start_id=model.generation_config.decoder_start_token_id,
        eos_ids=_ids(model.generation_config.eos_token_id),
        special_ids=set(tokenizer.all_special_ids), max_new_tokens=limit,
        forced_eos_ids=_ids(model.generation_config.forced_eos_token_id),
    )
    summary = tokenizer.decode(audit["selected_token_ids"], skip_special_tokens=True,
                               clean_up_tokenization_spaces=True).strip()
    if not summary:
        raise RuntimeError("empty generated summary")
    return {**audit, "summary": summary, "inference_seconds": seconds,
            "search_iterations": len(output.scores)}


def run_comparison(baseline_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Generate all 73 at both new budgets, with durable per-trial checkpoints."""
    baseline = load_baseline(baseline_dir)
    destination = output_dir.resolve()
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite {destination}")
    if destination == baseline["folder"] or destination in baseline["folder"].parents:
        raise ValueError("output cannot replace the baseline or its ancestors")
    destination.mkdir(parents=True, exist_ok=False)
    articles = baseline["articles"]
    rows = [{**row, "reference_summary": article["reference_summary"],
             "origin": "reused_historical_baseline"}
            for article, row in zip(articles, baseline["baseline_rows"], strict=True)]
    report = {
        "status": "preparing", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_run": str(baseline["folder"]), "output_dir": str(destination),
        "article_count": len(articles), "max_input_tokens": MAX_INPUT_TOKENS,
        "new_output_limits": list(NEW_OUTPUT_LIMITS), "compared_output_limits": list(ALL_OUTPUT_LIMITS),
        "reused_baseline_trials": len(rows), "expected_new_trials": len(articles)*2,
        "completed_new_trials": 0, "seed": 0, "cpu_threads": CPU_THREADS,
        "runner_sha256": file_hash(Path(__file__)),
        "model_checkpoint": baseline["manifest"]["model_checkpoint"],
        "cached_revision": baseline["manifest"]["cached_revision"],
        "prompt_sha256": baseline["manifest"]["prompt_sha256"],
        "selected_rows_hash": baseline["manifest"]["selected_rows_hash"],
        "reference_csv_sha256": baseline["context"]["reference_csv_sha256"],
        "fixed_generation_kwargs": {k:v for k,v in baseline["manifest"]["generation_kwargs"].items()
                                    if k != "max_new_tokens"},
        "baseline_source_hashes": baseline["protected_hashes"],
        "network_policy": "offline local cached pinned checkpoint only",
        "count_definition": "Selected sequence reaches max_new_tokens without EOS; not a manual sentence-completeness judgment",
        "timing_note": "64 timings are historical; canaries precede new trials; timings are not a controlled latency benchmark",
        "quality_note": "All 73 accepted as-is, including 6 pilots and limited sources; references unchanged; no factuality or ROUGE/BERTScore evaluation in this run",
    }
    controls: list[dict[str, Any]] = []
    started = perf_counter()
    atomic_write_json(destination / "selected_articles.json", articles, indent=2)
    (destination / "prompt_template.txt").write_text(baseline["prompt"], encoding="utf-8")
    try:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        torch.set_num_threads(CPU_THREADS)
        for package in ("torch", "transformers"):
            actual = version(package)
            if actual != baseline["context"][f"{package}_version"]:
                raise RuntimeError(f"{package} version changed; review before reusing historical baseline")
            report[f"{package}_version"] = actual
        print(f"Loading {report['model_checkpoint']} once; CPU, {CPU_THREADS} threads, offline.", flush=True)
        tokenizer = AutoTokenizer.from_pretrained(report["model_checkpoint"], revision=report["cached_revision"], local_files_only=True)
        model = AutoModelForSeq2SeqLM.from_pretrained(report["model_checkpoint"], revision=report["cached_revision"], local_files_only=True)
        model.to("cpu")
        model.eval()
        torch.manual_seed(0)
        report["device"], report["dtype"] = str(model.device), str(next(model.parameters()).dtype)
        if report["dtype"] != baseline["manifest"]["dtype"] or model.generation_config.forced_eos_token_id is not None:
            raise RuntimeError("unexpected dtype or forced-EOS setting")
        report["model_generation_config"] = model.generation_config.to_dict()
        encodings = []
        for article, old in zip(articles, baseline["baseline_rows"], strict=True):
            formatted = baseline["prompt"].format(article_text=article["article_text"])
            full = tokenizer(formatted, truncation=False, add_special_tokens=True,
                             return_attention_mask=False, verbose=False)["input_ids"]
            encoded = tokenizer(formatted, max_length=MAX_INPUT_TOKENS, truncation=True, return_tensors="pt")
            if len(full) != old["original_input_token_count"] or encoded["input_ids"][0].tolist() != full:
                raise ValueError("input differs from baseline or would be truncated")
            encodings.append(encoded)
        # Verify one old EOS case and one old capped case before reusing 64.
        indices = list(dict.fromkeys(next(i for i,row in enumerate(baseline["baseline_rows"])
                       if row["stop_reason"] == reason)
                       for reason in ("eos_before_limit", "length_limit_without_eos")))
        for index in indices:
            old = baseline["baseline_rows"][index]
            control = _generate(model, tokenizer, encodings[index], 64)
            controls.append({"id":old["id"], "max_new_tokens":64, **control})
            atomic_write_json(destination / "canary_64_replays.json", controls, indent=2)
            if control["selected_token_ids"] != old["selected_token_ids"] or control["summary"] != old["summary"]:
                raise RuntimeError("64-token canary differs from preserved baseline; comparison stopped")
        report["canary_replays_match"] = len(controls)
        report["status"] = "running"
        for index, (article, encoded, old) in enumerate(zip(articles, encodings, baseline["baseline_rows"], strict=True),1):
            for limit in NEW_OUTPUT_LIMITS:
                row = {"id":article["id"], "title":article["title"], "is_pilot":article["is_pilot"],
                       "reference_summary":article["reference_summary"], "max_input_tokens":MAX_INPUT_TOKENS,
                       "input_token_count":old["input_token_count"],
                       "original_input_token_count":old["original_input_token_count"],
                       "input_was_truncated":False, "max_new_tokens":limit, "origin":"new_generation", "error":None}
                try:
                    row.update(_generate(model,tokenizer,encoded,limit))
                    print(f"[{report['completed_new_trials']+1}/{report['expected_new_trials']}] article {index}/{len(articles)} output={limit} | {row['stop_reason']} | {row['output_token_count']} tokens",flush=True)
                except (RuntimeError, ValueError) as exc:
                    row["error"] = f"{type(exc).__name__}: {exc}"
                    print(f"ERROR article {index} output={limit}: {row['error']}",flush=True)
                rows.append(row)
                report["completed_new_trials"] += 1
                report["aggregate"] = aggregate(rows,len(articles))
                atomic_write_json(destination / "generation_metrics.json",rows,indent=2)
                atomic_write_json(destination / "run_report.json",report,indent=2)
        for path, digest in baseline["protected_hashes"].items():
            if file_hash(Path(path)) != digest:
                raise RuntimeError(f"baseline changed during execution: {path}")
        report["baseline_integrity_verified"] = True
        report["status"] = "completed_with_errors" if any(row.get("error") for row in rows) else "complete"
        for limit in ALL_OUTPUT_LIMITS:
            selected = [row for row in rows if row["max_new_tokens"] == limit]
            atomic_write_json(destination / f"summaries_output_{limit}.json",selected,indent=2)
        report["summary_changes_from_64"] = {
            str(limit):sum(row["summary"] != old["summary"] for row,old in zip(
                [r for r in rows if r["max_new_tokens"]==limit],baseline["baseline_rows"],strict=True)
                if row.get("error") is None) for limit in NEW_OUTPUT_LIMITS}
    except BaseException as exc:
        report["status"] = "interrupted" if isinstance(exc,KeyboardInterrupt) else "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report["elapsed_seconds"] = perf_counter()-started
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        report["aggregate"] = aggregate(rows,len(articles))
        atomic_write_json(destination / "generation_metrics.json",rows,indent=2)
        atomic_write_json(destination / "run_report.json",report,indent=2)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-run",type=Path,default=DEFAULT_BASELINE)
    parser.add_argument("--output-dir",type=Path,default=None)
    args = parser.parse_args()
    destination = args.output_dir or ROOT / "output/flan_evaluation/output_comparison" / datetime.now(ZoneInfo("Asia/Jakarta")).strftime("run_%Y%m%d_%H%M%S_%f")
    report = run_comparison(args.baseline_run,destination)
    print(json.dumps({"status":report["status"],"output_dir":str(destination),"aggregate":report["aggregate"]},indent=2),flush=True)
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())

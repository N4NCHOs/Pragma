"""Independent 6-article FLAN output-budget pilot; never imports the pipeline.

Uses the exact frozen preflight inputs/prompt and cached model revision. Only
max_new_tokens varies (64/96/128); no database, scraping, or production changes.
Results are checkpointed after each generation in a new output directory.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

from measure_flan_pilot_tokens import read_flan_baseline
from pipeline_experiment_data import atomic_write_json, compute_dataset_hash


DEFAULT_PREFLIGHT = Path("output/flan_evaluation/pilot_tokens_v1_20261024")
OUTPUT_LIMITS = (64, 96, 128)
PILOT_INPUT_LIMIT = 3072


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_frozen_pilot(
    directory: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    """Verify input/prompt hashes, IDs, and unchanged production baseline."""
    folder = Path(directory).resolve(strict=True)
    report = json.loads((folder / "token_report.json").read_bytes())
    inputs = json.loads((folder / "pilot_inputs.json").read_bytes())
    prompt = (folder / "prompt_template.txt").read_text(encoding="utf-8")
    if report.get("status") != "complete" or report.get("article_count") != 6:
        raise ValueError("expected a complete six-article token preflight")
    if not isinstance(inputs, list) or len(inputs) != 6:
        raise ValueError("expected six frozen input records")
    if _sha256(prompt.encode("utf-8")) != report.get("prompt_sha256"):
        raise ValueError("frozen prompt hash mismatch")
    if compute_dataset_hash([item["article"] for item in inputs]) != report.get("pilot_article_dataset_hash"):
        raise ValueError("frozen pilot article dataset hash mismatch")
    rows = report.get("articles", [])
    if len(rows) != 6:
        raise ValueError("token preflight needs six measurement rows")
    seen: set[str] = set()
    for item, row in zip(inputs, rows):
        article = item["article"]
        article_id = article["dataset_article_id"]
        if article_id in seen or article_id != row["dataset_article_id"]:
            raise ValueError("pilot IDs/order mismatch")
        seen.add(article_id)
        text = f"{article['title']}. {article['full_body']}".strip()
        if item["article_text"] != text or item["formatted_input"] != prompt.format(article_text=text):
            raise ValueError("frozen input no longer matches exact service formatting")
        if _sha256(text.encode("utf-8")) != row["article_text_sha256"]:
            raise ValueError("article text hash mismatch")
        if _sha256(item["formatted_input"].encode("utf-8")) != row["formatted_input_sha256"]:
            raise ValueError("formatted input hash mismatch")
        if row["complete_input_tokens"] > PILOT_INPUT_LIMIT:
            raise ValueError("pilot input ceiling would truncate a frozen article")
    baseline = read_flan_baseline(Path(report["flan_source"]))
    if (baseline["source_sha256"] != report["flan_source_sha256"]
            or baseline["SUMMARY_PROMPT"] != prompt
            or baseline["DEFAULT_MODEL_NAME"] != report["model_checkpoint"]
            or baseline["generation_settings"] != report["production_generation_settings"]):
        raise ValueError("production FLAN baseline changed since preflight; review before running")
    return report, inputs, prompt


def inspect_selected_sequence(
    sequence: list[int], beam_indices: list[int], *, decoder_start_id: int,
    eos_ids: set[int], special_ids: set[int], max_new_tokens: int,
    forced_eos_ids: set[int] | None = None,
) -> dict[str, Any]:
    """Extract valid selected tokens, excluding start and beam-buffer filler.

    This pilot uses one input/one returned sequence and records beam ancestry.
    EOS exactly at the ceiling is ambiguous with respect to the length limit;
    neither EOS nor reaching the ceiling proves sentence completeness.
    """
    if not sequence or sequence[0] != decoder_start_id:
        raise ValueError("unexpected decoder-start token")
    valid_count = sum(index >= 0 for index in beam_indices)
    if not 0 < valid_count <= max_new_tokens or valid_count > len(sequence) - 1:
        raise ValueError("invalid selected-sequence beam length")
    if any(index >= 0 for index in beam_indices[valid_count:]):
        raise ValueError("noncontiguous valid beam indices")
    ids = sequence[1:1 + valid_count]
    eos_positions = [index + 1 for index, token in enumerate(ids) if token in eos_ids]
    if eos_positions and eos_positions[0] != valid_count:
        raise ValueError("valid selected tokens unexpectedly continue after EOS")
    eos_position = eos_positions[0] if eos_positions else None
    at_limit = valid_count == max_new_tokens
    if eos_position is not None:
        if at_limit and forced_eos_ids and ids[-1] in forced_eos_ids:
            reason = "forced_eos_at_limit"
        else:
            reason = "eos_at_limit" if at_limit else "eos_before_limit"
    else:
        reason = "length_limit_without_eos" if at_limit else "unexpected_stop"
    return {
        "selected_token_ids": ids,
        "generated_new_tokens_including_eos": valid_count,
        "output_token_count": sum(token not in special_ids for token in ids),
        "eos_found": eos_position is not None,
        "eos_position_new_tokens": eos_position,
        "selected_output_reached_limit": at_limit,
        "stop_reason": reason,
    }


def aggregate_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, Any] = {}
    for limit in OUTPUT_LIMITS:
        rows = [row for row in results if row["max_new_tokens"] == limit]
        successful = [row for row in rows if row.get("error") is None]
        groups[str(limit)] = {
            "completed_trials": len(rows),
            "successful_trials": len(successful),
            "errors": len(rows) - len(successful),
            "stop_reasons": dict(Counter(row["stop_reason"] for row in successful)),
            "mean_output_tokens": mean(row["output_token_count"] for row in successful) if successful else None,
            "mean_inference_seconds": mean(row["inference_seconds"] for row in successful) if successful else None,
        }
    identities = list(dict.fromkeys(row["dataset_article_id"] for row in results))
    comparisons = []
    for article_id in identities:
        rows = [row for row in results if row["dataset_article_id"] == article_id and row.get("error") is None]
        if len(rows) == len(OUTPUT_LIMITS):
            comparisons.append({
                "dataset_article_id": article_id,
                "identical_summary_across_all_limits": len({row["summary"] for row in rows}) == 1,
            })
    return {"by_output_limit": groups, "within_article_comparisons": comparisons}


def _ids(value: Any) -> set[int]:
    if value is None:
        return set()
    return {value} if isinstance(value, int) else set(value)


def _device(torch: Any, requested: str) -> Any:
    if requested == "auto":
        requested = "cuda" if torch.cuda.is_available() else (
            "mps" if torch.backends.mps.is_available() else "cpu"
        )
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable; no silent device fallback")
    if requested == "mps" and not torch.backends.mps.is_available():
        raise RuntimeError("MPS unavailable; no silent device fallback")
    return torch.device(requested)


def _synchronize(torch: Any, device: Any) -> None:
    if device.type == "cuda":
        torch.cuda.synchronize(device)
    elif device.type == "mps":
        torch.mps.synchronize()


def run_pilot(preflight_dir: Path, output_dir: Path, *, device_name: str = "auto") -> dict[str, Any]:
    """Run each frozen article at all three output ceilings; checkpoint trials."""
    preflight = Path(preflight_dir).resolve(strict=True)
    destination = Path(output_dir).resolve()
    if destination.exists():
        raise FileExistsError(f"output directory already exists: {destination}")
    if destination == preflight or destination in preflight.parents:
        raise ValueError("output cannot replace the preflight or its ancestors")
    baseline, inputs, prompt = load_frozen_pilot(preflight)

    import torch
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    device = _device(torch, device_name)
    revision = baseline["tokenizer"]["cached_revision"]
    checkpoint = baseline["model_checkpoint"]
    print(f"Loading cached {checkpoint}@{revision} once on {device}...", flush=True)
    load_started = perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(checkpoint, revision=revision, local_files_only=True)
    model = AutoModelForSeq2SeqLM.from_pretrained(checkpoint, revision=revision, local_files_only=True)
    model.to(device)
    model.eval()
    _synchronize(torch, device)
    load_seconds = perf_counter() - load_started
    torch.manual_seed(0)
    fixed = {key: value for key, value in baseline["production_generation_settings"].items() if key != "max_new_tokens"}
    if fixed.get("do_sample") is not False or fixed.get("num_beams") != 4:
        raise ValueError("pilot expects the agreed deterministic four-beam baseline")
    config = model.generation_config
    start_id = config.decoder_start_token_id
    eos_ids = _ids(config.eos_token_id)
    forced_eos_ids = _ids(config.forced_eos_token_id)
    if start_id is None or not eos_ids:
        raise ValueError("model generation config lacks decoder-start/EOS metadata")
    if forced_eos_ids:
        raise ValueError("forced EOS would confound this pilot; review configuration first")

    # Validate every real tokenizer length against the frozen preflight before
    # any trial. No source article or prompt is truncated for this experiment.
    encodings = []
    for item, measured in zip(inputs, baseline["articles"]):
        encoded = tokenizer(item["formatted_input"], max_length=PILOT_INPUT_LIMIT, truncation=True, return_tensors="pt")
        consumed = int(encoded["attention_mask"].sum().item())
        if consumed != measured["complete_input_tokens"]:
            raise ValueError("actual consumed tokens differ from frozen full-input count")
        encodings.append({key: value.to(device) for key, value in encoded.items()})

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(exist_ok=False)
    atomic_write_json(destination / "pilot_inputs.json", inputs, indent=2)
    (destination / "prompt_template.txt").write_text(prompt, encoding="utf-8")
    atomic_write_json(destination / "preflight_report.json", baseline, indent=2)
    report: dict[str, Any] = {
        "status": "running",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "preflight_dir": str(preflight), "output_dir": str(destination),
        "model_checkpoint": checkpoint, "cached_revision": revision,
        "local_files_only": True, "model_load_seconds": load_seconds,
        "device": str(device), "model_dtype": str(next(model.parameters()).dtype),
        "torch_version": torch.__version__, "transformers_version": version("transformers"),
        "cpu_threads": torch.get_num_threads(), "seed": 0,
        "runner_sha256": _sha256(Path(__file__).read_bytes()),
        "prompt_sha256": baseline["prompt_sha256"],
        "pilot_article_dataset_hash": baseline["pilot_article_dataset_hash"],
        "max_input_tokens": PILOT_INPUT_LIMIT, "output_limits": list(OUTPUT_LIMITS),
        "fixed_generation_kwargs": fixed,
        "model_generation_config": config.to_dict(),
        "article_count": len(inputs), "expected_trials": len(inputs) * len(OUTPUT_LIMITS),
        "completed_trials": 0,
        "timing_note": "Single serial observation per article/limit; generation only, excludes loading/tokenization; one 1-token warmup; not a latency benchmark.",
        "quality_note": "EOS, terminal punctuation, and reaching a token ceiling do not establish factuality or sentence completeness. Source-based review is separate.",
        "realtime_preprocessing_integration": "HIGH PRIORITY / PENDING; production unchanged",
    }
    results: list[dict[str, Any]] = []
    atomic_write_json(destination / "results.json", results, indent=2)
    atomic_write_json(destination / "run_report.json", report, indent=2)
    try:
        # Prime execution once; this deliberately incomplete 1-token output is
        # not a pilot summary or a quality/latency measurement.
        warmup_started = perf_counter()
        with torch.inference_mode():
            model.generate(**encodings[0], **fixed, max_new_tokens=1)
        _synchronize(torch, device)
        report["warmup_seconds"] = perf_counter() - warmup_started
        for article_index, (item, encoded) in enumerate(zip(inputs, encodings)):
            article = item["article"]
            for limit in OUTPUT_LIMITS:
                trial = len(results) + 1
                print(f"[{trial}/{report['expected_trials']}] output={limit} | {article['title']}", flush=True)
                row: dict[str, Any] = {
                    "trial_index": trial, "dataset_article_id": article["dataset_article_id"],
                    "title": article["title"], "max_input_tokens": PILOT_INPUT_LIMIT,
                    "input_token_count": baseline["articles"][article_index]["complete_input_tokens"],
                    "original_input_token_count": baseline["articles"][article_index]["complete_input_tokens"],
                    "input_was_truncated": False, "max_new_tokens": limit, "error": None,
                }
                try:
                    _synchronize(torch, device)
                    started = perf_counter()
                    with torch.inference_mode():
                        generated = model.generate(
                            **encoded, **fixed, max_new_tokens=limit,
                            return_dict_in_generate=True, output_scores=True,
                        )
                    _synchronize(torch, device)
                    row["inference_seconds"] = perf_counter() - started
                    if generated.beam_indices is None:
                        raise RuntimeError("beam ancestry missing; do not guess generated length")
                    row.update(inspect_selected_sequence(
                        generated.sequences[0].tolist(), generated.beam_indices[0].tolist(),
                        decoder_start_id=start_id, eos_ids=eos_ids,
                        special_ids=set(tokenizer.all_special_ids), max_new_tokens=limit,
                        forced_eos_ids=forced_eos_ids,
                    ))
                    row["search_iterations"] = len(generated.scores)
                    row["summary"] = tokenizer.decode(
                        row["selected_token_ids"], skip_special_tokens=True,
                        clean_up_tokenization_spaces=True,
                    ).strip()
                    row["ends_with_sentence_punctuation"] = row["summary"].rstrip('"\u201d\u2019)').endswith((".", "!", "?"))
                    if not row["summary"]:
                        raise RuntimeError("model generated an empty summary")
                    print(f"  {row['inference_seconds']:.2f}s | content={row['output_token_count']} | {row['stop_reason']} | {row['summary']}", flush=True)
                    del generated
                except (RuntimeError, ValueError) as exc:
                    row["error"] = f"{type(exc).__name__}: {exc}"
                    print(f"  ERROR: {row['error']}", flush=True)
                results.append(row)
                report["completed_trials"] = len(results)
                report["aggregate"] = aggregate_results(results)
                atomic_write_json(destination / "results.json", results, indent=2)
                atomic_write_json(destination / "run_report.json", report, indent=2)
        report["status"] = "complete" if all(row["error"] is None for row in results) else "completed_with_errors"
    except BaseException as exc:
        report["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        report["fatal_error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        atomic_write_json(destination / "run_report.json", report, indent=2)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-dir", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--device", choices=("auto", "cpu", "mps", "cuda"), default="auto")
    args = parser.parse_args(argv)
    output = args.output_dir or Path("output/flan_evaluation") / f"output_pilot_{datetime.now(timezone.utc):%Y%m%dT%H%M%S_%fZ}"
    try:
        report = run_pilot(args.preflight_dir, output, device_name=args.device)
    except (OSError, ValueError, TypeError, RuntimeError, ImportError, KeyError) as exc:
        parser.exit(1, f"Output pilot stopped: {type(exc).__name__}: {exc}\n")
    print(f"Pilot status: {report['status']} | results: {output.resolve()}")
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())

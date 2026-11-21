"""Frozen manual-reference package and independent four-limit FLAN evaluation.

Importing this module never loads a model, accesses PostgreSQL, or scrapes news.
The CSV writer uses Python's standard library so the user's notebook needs no
spreadsheet-authoring runtime. No reference summaries are generated here.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from time import perf_counter
from typing import Any

from measure_flan_pilot_tokens import PILOT_ARTICLE_IDS, read_flan_baseline
from pipeline_experiment_data import atomic_write_json, compute_dataset_hash


ROOT = Path(__file__).resolve().parent
DEFAULT_PACKAGE = ROOT / "notebook/evaluation_data/flan_reference_package_v1"
SNAPSHOT = ROOT / "output/flan_evaluation/preprocessed_v1_20261024"
PREFLIGHT = ROOT / "output/flan_evaluation/pilot_tokens_v1_20261024/token_report.json"
INPUT_LIMITS = (512, 1024, 2048, 3072)
REFERENCE_FIELDS = ("id", "title", "article_text", "reference_summary")
AUDIT_FIELDS = ("id", "title", "is_pilot", "body_word_count", "quality_flags", "review_decision", "review_notes")
RESULT_FIELDS = ("id", "title", "summary", "reference_summary")

# Manual observations against the frozen source, not a general punctuation
# classifier: legitimate headings and short complete articles must survive.
_CLIPPED_OBSERVATIONS = {
    "923fe1c36412": "The industry leaders today are Ethereum ",
    "c363c3c5ac2c": "Stripe, meanwhile, is working with Plasma ",
    "f67883101220": "\nBitcoin \n",
    "3ec1254da217": "whether a borrowe",
    "cfa0d75bb9ee": "\nA bitcoin \n",
    "f886c9cb6965": "the layer-2 blockchain built by Coinbase Global ",
    "d3e9bcc0baa5": "price chart flashed a major bullish signal, Strategy ",
    "faf611d55873": "Technology giant Microsoft ",
    "8bad769c26ea": "with companies including Coinbase Global ",
    "dc8a1489ef87": "Investment banking behemoth JPMorgan (JPM) expects bitcoin ",
    "ae5cb9a01e3c": "While bitcoin ",
    "dbbbcc3ddb05": "\nSpaceX \n",
    "29c51a72228a": "\nBitcoin \n",
    "1c3b1c08c9ac": "The teams behind a Dogecoin ",
    "ae469261bfa1": "\nBitcoin \n",
    "91734cb69777": "artificial intelligence investment. Tesla ",
    "544307a0609c": "Stablecoin providers such as Circle ",
    "06daa206c651": "Other cryptocurrencies, such as ether ",
    "8502097f256e": "and with Nvidia ",
}


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    """UTF-8/BOM, quoted multiline text and string IDs; never overwrite."""
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path, fields: tuple[str, ...]) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(fields):
            raise ValueError(f"{path.name}: expected columns {list(fields)}")
        rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError(f"{path.name}: malformed CSV row")
    return rows


def _by_id(rows: list[dict[str, Any]], expected: list[str], label: str) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = row.get("id")
        if not isinstance(identity, str) or not identity or identity in mapped:
            raise ValueError(f"{label}: missing or duplicate ID")
        mapped[identity] = row
    if set(mapped) != set(expected):
        raise ValueError(f"{label}: IDs differ from frozen articles (missing or extra records)")
    return mapped


def source_observations(article: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Review flags only; no automatic include/exclude decision or rewriting."""
    body = article["full_body"]
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    flags: list[str] = []
    notes: list[str] = []
    if body.startswith("Skip to main content"):
        flags.append("navigation_ticker_extract")
        notes.append("Extraction starts with site navigation; inspect whether article prose is present.")
    if len(lines) == 4 and lines[2].startswith("Make") and "preferred on" in lines[2]:
        flags.append("description_with_share_controls")
        notes.append("Four-line extraction: title, short description, preference/share controls.")
    for prefix, evidence in _CLIPPED_OBSERVATIONS.items():
        if article["dataset_article_id"].startswith(prefix) and evidence in body:
            flags.append("possible_clipped_prose")
            notes.append(f"Observed excerpt for review: {evidence.strip()!r}; not automatically repaired.")
    return flags, notes


def prepare_reference_package(
    package_dir: Path = DEFAULT_PACKAGE, *, snapshot_dir: Path = SNAPSHOT,
    flan_source: Path = ROOT / "ai_models/flan_t5.py", preflight_file: Path = PREFLIGHT,
    write_templates: bool = True,
) -> dict[str, Any]:
    """Freeze all candidates, blank references, pending audit, and exact prompts.

    ``write_templates=False`` stages JSON matrices for an external spreadsheet
    author; it leaves status pending until that author finishes both CSVs.
    Normal local use writes portable CSV files directly with the stdlib.
    """
    destination = Path(package_dir).resolve()
    if destination.exists():
        raise FileExistsError(f"package already exists; refusing to overwrite references: {destination}")
    folder = Path(snapshot_dir).resolve(strict=True)
    source = json.loads((folder / "qualified_news_cleaned.json").read_bytes())
    preprocessing = json.loads((folder / "preprocessing_report.json").read_bytes())
    if preprocessing.get("status") != "complete" or compute_dataset_hash(source) != preprocessing.get("cleaned_dataset_hash"):
        raise ValueError("cleaned source no longer matches completed preprocessing report")
    baseline = read_flan_baseline(flan_source)
    preflight = json.loads(Path(preflight_file).read_bytes())
    prompt = baseline["SUMMARY_PROMPT"]
    if (preflight.get("status") != "complete" or preflight["model_checkpoint"] != baseline["DEFAULT_MODEL_NAME"]
            or preflight["prompt_sha256"] != _hash(prompt)):
        raise ValueError("current prompt/checkpoint differs from pilot; review before preparing references")
    if baseline["generation_settings"].get("max_new_tokens") != 64:
        raise ValueError("expected the agreed 64-token output baseline")
    articles = []
    references = []
    audits = []
    seen: set[str] = set()
    for item in source:
        identity = item.get("dataset_article_id")
        if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{64}", identity) or identity in seen:
            raise ValueError("source article IDs must be unique stable SHA-256 strings")
        seen.add(identity)
        if any(not isinstance(item.get(key), str) or not item[key].strip() for key in ("title", "full_body")):
            raise ValueError(f"missing title/full_body for {identity}")
        text = f"{item['title']}. {item['full_body']}".strip()
        flags, notes = source_observations(item)
        article = {
            "id": identity, "title": item["title"], "full_body": item["full_body"],
            "article_text": text, "article_text_sha256": _hash(text),
            "url": item.get("url", ""), "is_pilot": identity in PILOT_ARTICLE_IDS,
            "quality_flags": flags,
        }
        articles.append(article)
        references.append({"id": identity, "title": item["title"], "article_text": text, "reference_summary": ""})
        audits.append({
            "id": identity, "title": item["title"], "is_pilot": str(article["is_pilot"]).lower(),
            "body_word_count": str(len(item["full_body"].split())), "quality_flags": ";".join(flags),
            "review_decision": "pending", "review_notes": " ".join(notes),
        })
    if not source or not set(PILOT_ARTICLE_IDS).issubset(seen):
        raise ValueError("source must retain all six pilot candidates")
    manifest = {
        "status": "complete" if write_templates else "awaiting_csv_templates",
        "schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_snapshot": str(folder), "source_dataset_hash": preprocessing["cleaned_dataset_hash"],
        "flan_source": str(Path(flan_source).resolve()), "flan_source_sha256": baseline["source_sha256"],
        "frozen_articles_hash": compute_dataset_hash(articles), "prompt_sha256": _hash(prompt),
        "model_checkpoint": baseline["DEFAULT_MODEL_NAME"],
        "cached_revision": preflight["tokenizer"]["cached_revision"],
        "generation_kwargs": baseline["generation_settings"], "input_limits": list(INPUT_LIMITS),
        "article_count": len(articles), "pilot_count": sum(row["is_pilot"] for row in articles),
        "flagged_article_count": sum(bool(row["quality_flags"]) for row in articles),
        "reference_file": "gpt_reference_summaries.csv", "audit_file": "source_audit.csv",
        "reference_provenance": {"model": "", "generated_at": "", "reviewer": "", "notes": ""},
        "reference_note": "Manual AI-generated silver references; same full source/prompt, independent of FLAN outputs; not human gold.",
        "quality_note": "Review observations only; no auto exclusions; no flagged issue does not establish completeness.",
        "realtime_preprocessing_integration": "HIGH PRIORITY / PENDING",
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(exist_ok=False)
    (destination / "prompts").mkdir()
    atomic_write_json(destination / "frozen_articles.json", articles, indent=2)
    (destination / "prompt_template.txt").write_text(prompt, encoding="utf-8")
    for index, article in enumerate(articles, 1):
        (destination / "prompts" / f"{index:03d}_{article['id']}.txt").write_text(
            prompt.format(article_text=article["article_text"]), encoding="utf-8",
        )
    atomic_write_json(destination / "template_data.json", {
        "references": references, "audit": audits,
        "reference_fields": list(REFERENCE_FIELDS), "audit_fields": list(AUDIT_FIELDS),
    }, indent=2)
    if write_templates:
        _write_csv(destination / manifest["reference_file"], REFERENCE_FIELDS, references)
        _write_csv(destination / manifest["audit_file"], AUDIT_FIELDS, audits)
    atomic_write_json(destination / "manifest.json", manifest, indent=2)
    return manifest


def load_package(package_dir: Path = DEFAULT_PACKAGE) -> dict[str, Any]:
    folder = Path(package_dir).resolve(strict=True)
    manifest = json.loads((folder / "manifest.json").read_bytes())
    articles = json.loads((folder / "frozen_articles.json").read_bytes())
    prompt = (folder / "prompt_template.txt").read_text(encoding="utf-8")
    if manifest.get("status") != "complete":
        raise ValueError("reference package export is not complete")
    if (compute_dataset_hash(articles) != manifest.get("frozen_articles_hash")
            or _hash(prompt) != manifest.get("prompt_sha256")):
        raise ValueError("frozen source/prompt hash mismatch; do not mix versions")
    if len(articles) != manifest["article_count"]:
        raise ValueError("frozen article count mismatch")
    _by_id(articles, [row["id"] for row in articles], "frozen articles")
    return {"manifest": manifest, "articles": articles, "prompt": prompt, "package_dir": folder}


def validate_ready(
    package_dir: Path = DEFAULT_PACKAGE, reference_csv: Path | None = None,
    audit_csv: Path | None = None,
) -> list[dict[str, Any]]:
    """Strict ID join with manual include/exclude decisions; never silently drop."""
    package = load_package(package_dir)
    manifest, articles, folder = package["manifest"], package["articles"], package["package_dir"]
    identities = [row["id"] for row in articles]
    references = _by_id(_read_csv(reference_csv or folder / manifest["reference_file"], REFERENCE_FIELDS), identities, "references")
    audits = _by_id(_read_csv(audit_csv or folder / manifest["audit_file"], AUDIT_FIELDS), identities, "source audit")
    selected = []
    pending = []
    missing_references = []
    for article in articles:
        identity = article["id"]
        reference, audit = references[identity], audits[identity]
        if reference["title"] != article["title"] or reference["article_text"] != article["article_text"]:
            raise ValueError(f"reference title/source text changed for {identity}")
        if audit["title"] != article["title"] or audit["is_pilot"] != str(article["is_pilot"]).lower():
            raise ValueError(f"audit title/pilot identity changed for {identity}")
        decision = audit["review_decision"].strip().lower()
        if decision not in {"include", "exclude"}:
            pending.append(identity)
            continue
        if decision == "exclude":
            if not audit["review_notes"].strip():
                raise ValueError(f"exclusion requires a reason for {identity}")
            continue
        if not reference["reference_summary"].strip():
            missing_references.append(identity)
        selected.append({**article, "reference_summary": reference["reference_summary"].strip()})
    if pending or missing_references:
        raise ValueError(
            f"Not ready: {len(pending)} source decisions pending; "
            f"{len(missing_references)} included references empty. "
            "Review source_audit.csv (include/exclude) and fill gpt_reference_summaries.csv."
        )
    if not selected:
        raise ValueError("no articles explicitly included for evaluation")
    return selected


def generate_comparison_csvs(
    package_dir: Path, output_dir: Path, *, reference_csv: Path | None = None,
    audit_csv: Path | None = None, device_name: str = "auto",
) -> dict[str, Any]:
    """Generate only after references/review are complete; one model, four limits.

    Comparison CSVs are published only if every expected generation succeeds.
    Partial results/errors are preserved in generation_metrics.json, never
    silently removed from an apparently complete four-way comparison.
    """
    destination = Path(output_dir).resolve()
    if destination.exists():
        raise FileExistsError(f"run folder already exists: {destination}")
    selected = validate_ready(package_dir, reference_csv, audit_csv)
    package = load_package(package_dir)
    manifest, prompt = package["manifest"], package["prompt"]
    baseline = read_flan_baseline(Path(manifest["flan_source"]))
    if baseline["source_sha256"] != manifest["flan_source_sha256"]:
        raise ValueError("FLAN source changed since references were prepared; review/refreeze first")
    generation = manifest["generation_kwargs"]
    if (generation != baseline["generation_settings"]
            or generation.get("max_new_tokens") != 64 or generation.get("do_sample") is not False
            or manifest["model_checkpoint"] != baseline["DEFAULT_MODEL_NAME"]
            or prompt != baseline["SUMMARY_PROMPT"] or manifest["input_limits"] != list(INPUT_LIMITS)):
        raise ValueError("expected the frozen checkpoint/prompt and fixed deterministic 64-token configuration")

    import torch
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    from run_flan_output_pilot import _device, _ids, _synchronize, inspect_selected_sequence

    device = _device(torch, device_name)
    tokenizer = AutoTokenizer.from_pretrained(manifest["model_checkpoint"], revision=manifest["cached_revision"], local_files_only=True)
    model = AutoModelForSeq2SeqLM.from_pretrained(manifest["model_checkpoint"], revision=manifest["cached_revision"], local_files_only=True)
    model.to(device)
    model.eval()
    torch.manual_seed(0)
    if model.generation_config.forced_eos_token_id is not None:
        raise ValueError("unexpected forced EOS; review model config")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(exist_ok=False)
    atomic_write_json(destination / "selected_articles.json", selected, indent=2)
    (destination / "prompt_template.txt").write_text(prompt, encoding="utf-8")
    report = {
        "status": "running", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "package_hash": manifest["frozen_articles_hash"], "prompt_sha256": manifest["prompt_sha256"],
        "selected_rows_hash": compute_dataset_hash(selected), "article_count": len(selected),
        "expected_trials": len(selected) * len(INPUT_LIMITS), "completed_trials": 0,
        "input_limits": list(INPUT_LIMITS), "generation_kwargs": generation,
        "model_checkpoint": manifest["model_checkpoint"], "cached_revision": manifest["cached_revision"],
        "device": str(device), "dtype": str(next(model.parameters()).dtype),
        "reference_provenance": manifest["reference_provenance"],
        "input_truncation_note": "Matches current service: right truncation of whole prompt may remove final Summary: cue.",
    }
    metrics: list[dict[str, Any]] = []
    comparisons: dict[int, list[dict[str, Any]]] = {limit: [] for limit in INPUT_LIMITS}
    atomic_write_json(destination / "run_manifest.json", report, indent=2)
    try:
        for index, article in enumerate(selected, 1):
            formatted = prompt.format(article_text=article["article_text"])
            original_count = len(tokenizer(formatted, truncation=False, add_special_tokens=True, return_attention_mask=False, verbose=False)["input_ids"])
            for limit in INPUT_LIMITS:
                print(f"[{index}/{len(selected)}] input={limit} | {article['title']}", flush=True)
                row: dict[str, Any] = {
                    "id": article["id"], "title": article["title"], "is_pilot": article["is_pilot"],
                    "max_input_tokens": limit, "original_input_token_count": original_count,
                    "max_new_tokens": 64, "error": None,
                }
                try:
                    encoded = tokenizer(formatted, max_length=limit, truncation=True, return_tensors="pt")
                    consumed = int(encoded["attention_mask"].sum().item())
                    row.update(input_token_count=consumed, input_was_truncated=original_count > consumed)
                    encoded = {key: value.to(device) for key, value in encoded.items()}
                    _synchronize(torch, device)
                    started = perf_counter()
                    with torch.inference_mode():
                        output = model.generate(**encoded, **generation, return_dict_in_generate=True, output_scores=True)
                    _synchronize(torch, device)
                    row["inference_seconds"] = perf_counter() - started
                    if output.beam_indices is None:
                        raise RuntimeError("missing beam indices; output length cannot be audited")
                    row.update(inspect_selected_sequence(
                        output.sequences[0].tolist(), output.beam_indices[0].tolist(),
                        decoder_start_id=model.generation_config.decoder_start_token_id,
                        eos_ids=_ids(model.generation_config.eos_token_id), special_ids=set(tokenizer.all_special_ids),
                        max_new_tokens=64,
                    ))
                    row["search_iterations"] = len(output.scores)
                    summary = tokenizer.decode(row["selected_token_ids"], skip_special_tokens=True, clean_up_tokenization_spaces=True).strip()
                    if not summary:
                        raise RuntimeError("empty FLAN summary")
                    comparisons[limit].append({"id": article["id"], "title": article["title"], "summary": summary, "reference_summary": article["reference_summary"]})
                    row["summary"] = summary
                    del output
                except (RuntimeError, ValueError) as exc:
                    row["error"] = f"{type(exc).__name__}: {exc}"
                metrics.append(row)
                report["completed_trials"] = len(metrics)
                atomic_write_json(destination / "generation_metrics.json", metrics, indent=2)
                atomic_write_json(destination / "run_manifest.json", report, indent=2)
        if any(row["error"] for row in metrics):
            raise RuntimeError("generation errors retained; no incomplete comparison CSVs published")
        paths = {}
        hashes = {}
        for limit, rows in comparisons.items():
            path = destination / f"flan_{limit}.csv"
            _write_csv(path, RESULT_FIELDS, rows)
            paths[limit] = path
            hashes[str(limit)] = hashlib.sha256(path.read_bytes()).hexdigest()
        report.update(status="complete", comparison_csv_hashes=hashes)
    except BaseException as exc:
        report.update(status="interrupted" if isinstance(exc, KeyboardInterrupt) else "failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        atomic_write_json(destination / "run_manifest.json", report, indent=2)
    return {"csv_paths": paths, "run_dir": destination, "report": report}


def load_comparison_csvs(package_dir: Path, run_dir: Path) -> dict[int, list[dict[str, str]]]:
    """Score only a complete, consistent four-way run and its frozen references."""
    package = load_package(package_dir)
    folder = Path(run_dir).resolve(strict=True)
    report = json.loads((folder / "run_manifest.json").read_bytes())
    selected = json.loads((folder / "selected_articles.json").read_bytes())
    expected_trials = len(selected) * len(INPUT_LIMITS) if isinstance(selected, list) else 0
    if (not selected or not isinstance(selected, list) or report.get("status") != "complete"
            or report.get("article_count") != len(selected)
            or report.get("expected_trials") != expected_trials
            or report.get("completed_trials") != expected_trials
            or report.get("input_limits") != list(INPUT_LIMITS)
            or report["package_hash"] != package["manifest"]["frozen_articles_hash"]
            or report["prompt_sha256"] != package["manifest"]["prompt_sha256"]
            or compute_dataset_hash(selected) != report["selected_rows_hash"]):
        raise ValueError("run is incomplete or source/reference provenance differs")
    identities = [row["id"] for row in selected]
    original = _by_id(selected, identities, "selected frozen articles")
    candidates = {row["id"]: row for row in package["articles"]}
    for article in selected:
        if article["id"] not in candidates or any(article[key] != candidates[article["id"]][key] for key in ("title", "article_text", "is_pilot")):
            raise ValueError("selected article differs from package")
    output = {}
    for limit in INPUT_LIMITS:
        path = folder / f"flan_{limit}.csv"
        if hashlib.sha256(path.read_bytes()).hexdigest() != report["comparison_csv_hashes"][str(limit)]:
            raise ValueError(f"comparison CSV modified: {path.name}")
        rows = _read_csv(path, RESULT_FIELDS)
        mapped = _by_id(rows, identities, path.name)
        for identity in identities:
            row, frozen = mapped[identity], original[identity]
            if row["title"] != frozen["title"] or row["reference_summary"] != frozen["reference_summary"] or not row["summary"].strip():
                raise ValueError(f"mismatched/empty summary or reference in {path.name}")
        output[limit] = [mapped[identity] for identity in identities]
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--check", action="store_true", help="validate manual references/review; no models")
    args = parser.parse_args()
    try:
        if args.check:
            print(f"Ready: {len(validate_ready(args.package_dir))} included articles")
        else:
            manifest = prepare_reference_package(args.package_dir)
            print(f"Prepared {manifest['article_count']} candidates, including {manifest['pilot_count']} pilot articles")
            print(args.package_dir.resolve())
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(1, f"Reference workflow stopped: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    main()

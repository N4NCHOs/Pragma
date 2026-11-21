"""Token-only preflight for the six agreed FLAN pilot candidates.

Reads the frozen cleaned dataset and the current FLAN prompt as literals, then
loads ONLY a locally cached tokenizer. No model weights, inference, scraping,
novelty detection, or database access. Outputs are written to a new directory.
"""

from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
from typing import Any

from pipeline_experiment_data import atomic_write_json, compute_dataset_hash


DEFAULT_SNAPSHOT = Path("output/flan_evaluation/preprocessed_v1_20261024")
DEFAULT_FLAN_SOURCE = Path("ai_models/flan_t5.py")
INPUT_LIMITS = (512, 1024, 2048, 3072)
PILOT_ARTICLE_IDS = (
    "d88ecdbfd283769b367268dc7b7c14f411851af8ea5ea97875a08925af8bf1d4",
    "5c5fbb2ad4e363114002acb9a7ece8d2de59b94151909d7e1cbd82c0b33d90ac",
    "269a4ac2559e1cc75c9fa61e579a0f0daa4e465ae57413d703fa7e90f07cae76",
    "544307a0609c50dd807ec9a6888fdce4ccfa2b63d79499f6e5fed5ce82b47fdf",
    "78adaf032c25de397f75d390ed0ebe2299a8c3ba73b16f54633d6d2d19c94817",
    "8b38d00ac6012f9c741d1e711f04aea939463019d0f2ea72ad3e9d4774c5c331",
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_flan_baseline(source_path: Path) -> dict[str, Any]:
    """Read literal settings without importing FLAN/torch or executing source."""
    source_bytes = Path(source_path).read_bytes()
    tree = ast.parse(source_bytes)
    names = {"DEFAULT_MODEL_NAME", "DEFAULT_MAX_INPUT_TOKENS", "SUMMARY_PROMPT"}
    settings: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in names:
                    settings[target.id] = ast.literal_eval(node.value)
    if set(settings) != names:
        raise ValueError("FLAN source must define the three expected literal settings")
    if not isinstance(settings["DEFAULT_MODEL_NAME"], str) or not settings["DEFAULT_MODEL_NAME"].strip():
        raise ValueError("FLAN checkpoint must be a nonempty literal string")
    prompt = settings["SUMMARY_PROMPT"]
    if not isinstance(prompt, str) or prompt.count("{article_text}") != 1:
        raise ValueError("FLAN prompt must contain exactly one {article_text} placeholder")
    # Fail rather than guess if source changes introduce nonliteral settings.
    generate_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "generate"
    ]
    if len(generate_calls) != 1:
        raise ValueError("expected exactly one FLAN generate call for baseline settings")
    settings["generation_settings"] = {
        item.arg: ast.literal_eval(item.value)
        for item in generate_calls[0].keywords if item.arg is not None
    }
    settings["source_sha256"] = _sha256(source_bytes)
    return settings


def load_pilot_articles(snapshot_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Verify the frozen cleaned snapshot, then select by stable ID, not row."""
    folder = Path(snapshot_dir).resolve(strict=True)
    report = json.loads((folder / "preprocessing_report.json").read_bytes())
    articles = json.loads((folder / "qualified_news_cleaned.json").read_bytes())
    if report.get("status") != "complete":
        raise ValueError("preprocessing snapshot is not marked complete")
    if not isinstance(articles, list) or compute_dataset_hash(articles) != report.get("cleaned_dataset_hash"):
        raise ValueError("cleaned dataset no longer matches its preprocessing report")
    by_id: dict[str, dict[str, Any]] = {}
    for article in articles:
        if not isinstance(article, dict):
            raise ValueError("cleaned dataset contains a non-object record")
        article_id = article.get("dataset_article_id")
        if not isinstance(article_id, str) or not article_id or article_id in by_id:
            raise ValueError("cleaned dataset contains missing or duplicate article IDs")
        by_id[article_id] = article
    missing = [article_id for article_id in PILOT_ARTICLE_IDS if article_id not in by_id]
    if missing:
        raise ValueError(f"pilot IDs missing from the frozen snapshot: {missing}")
    return [by_id[article_id] for article_id in PILOT_ARTICLE_IDS], report


def measure_inputs(
    articles: list[dict[str, Any]], prompt_template: str, tokenizer: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Mimic service formatting and measure actual complete/truncated encodings.

    No addition of separately counted title/body/prompt lengths: tokenization is
    performed on the complete formatted input including special tokens.
    """
    rows: list[dict[str, Any]] = []
    inputs: list[dict[str, Any]] = []
    special_ids = set(tokenizer.all_special_ids)
    for article in articles:
        for key in ("dataset_article_id", "title", "full_body"):
            if not isinstance(article.get(key), str) or not article[key].strip():
                raise ValueError(f"pilot article requires nonempty string {key}")
        article_text = f"{article['title']}. {article['full_body']}".strip()
        formatted_input = prompt_template.format(article_text=article_text)
        complete_ids = tokenizer(
            formatted_input, add_special_tokens=True, truncation=False,
            return_attention_mask=False, verbose=False,
        )["input_ids"]
        limits: list[dict[str, Any]] = []
        for limit in INPUT_LIMITS:
            encoded = tokenizer(
                formatted_input, max_length=limit, truncation=True,
                add_special_tokens=True, return_attention_mask=True, verbose=False,
            )
            consumed = sum(encoded["attention_mask"])
            if consumed != len(encoded["input_ids"]):
                raise ValueError("unexpected padding in a single unpadded input")
            limits.append({
                "max_input_tokens": limit,
                "consumed_input_tokens": consumed,
                "input_was_truncated": len(complete_ids) > consumed,
                "removed_token_count": len(complete_ids) - consumed,
                "decoded_final_tokens": tokenizer.decode(
                    encoded["input_ids"][-12:], skip_special_tokens=True,
                ),
            })
        rows.append({
            "dataset_article_id": article["dataset_article_id"],
            "title": article["title"],
            "article_text_sha256": _sha256(article_text.encode("utf-8")),
            "formatted_input_sha256": _sha256(formatted_input.encode("utf-8")),
            "complete_input_tokens": len(complete_ids),
            "special_tokens_in_complete_input": sum(
                token in special_ids for token in complete_ids
            ),
            "limits": limits,
        })
        inputs.append({
            "article": article,
            "article_text": article_text,
            "formatted_input": formatted_input,
        })
    return rows, inputs


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def run_preflight(snapshot_dir: Path, flan_source: Path, output_dir: Path) -> dict[str, Any]:
    """Load one pinned cached tokenizer and export one exclusive pilot preflight."""
    snapshot = Path(snapshot_dir).resolve(strict=True)
    source = Path(flan_source).resolve(strict=True)
    destination = Path(output_dir).resolve()
    if destination.exists():
        raise FileExistsError(f"output directory already exists: {destination}")
    if destination in snapshot.parents or destination == snapshot:
        raise ValueError("output cannot replace the input snapshot or its ancestors")
    articles, preprocessing = load_pilot_articles(snapshot)
    baseline = read_flan_baseline(source)

    # Heavy dependencies are imported only here; unit tests can use a fake
    # tokenizer and importing this script never initializes FLAN/torch/service.
    from huggingface_hub import try_to_load_from_cache
    from transformers import AutoTokenizer

    cached_config = try_to_load_from_cache(baseline["DEFAULT_MODEL_NAME"], "tokenizer_config.json")
    if not isinstance(cached_config, str):
        raise RuntimeError("tokenizer is not cached locally; no download was attempted")
    cached_revision = Path(cached_config).parent.name
    tokenizer = AutoTokenizer.from_pretrained(
        baseline["DEFAULT_MODEL_NAME"], revision=cached_revision, local_files_only=True,
    )
    rows, inputs = measure_inputs(articles, baseline["SUMMARY_PROMPT"], tokenizer)
    longest = max(row["complete_input_tokens"] for row in rows)
    fitting = [limit for limit in INPUT_LIMITS if limit >= longest]
    report = {
        "status": "complete",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "token-only preflight; no generation; final evaluation split undecided",
        "snapshot_dir": str(snapshot),
        "output_dir": str(destination),
        "source_dataset_hash": preprocessing["cleaned_dataset_hash"],
        "pilot_article_dataset_hash": compute_dataset_hash(articles),
        "flan_source": str(source),
        "flan_source_sha256": baseline["source_sha256"],
        "prompt_sha256": _sha256(baseline["SUMMARY_PROMPT"].encode("utf-8")),
        "model_checkpoint": baseline["DEFAULT_MODEL_NAME"],
        "production_default_max_input_tokens": baseline["DEFAULT_MAX_INPUT_TOKENS"],
        "production_generation_settings": baseline["generation_settings"],
        "tokenizer": {
            "class": type(tokenizer).__name__,
            "cached_revision": cached_revision,
            "local_files_only": True,
            "model_max_length_metadata": tokenizer.model_max_length,
            "truncation_side": tokenizer.truncation_side,
            "special_tokens_added": tokenizer.num_special_tokens_to_add(pair=False),
            "cached_tokenizer_config_sha256": _sha256(Path(cached_config).read_bytes()),
            "transformers_version": _package_version("transformers"),
            "tokenizers_version": _package_version("tokenizers"),
            "sentencepiece_version": _package_version("sentencepiece"),
        },
        "article_count": len(rows),
        "largest_complete_input_tokens": longest,
        "recommended_pilot_max_input_tokens": min(fitting) if fitting else None,
        "untruncated_articles_per_limit": {
            str(limit): sum(row["complete_input_tokens"] <= limit for row in rows)
            for limit in INPUT_LIMITS
        },
        "notes": [
            "Counts include the full current prompt, title, body, and special tokens.",
            "Prompt-only and article-only token counts are not assumed additive.",
            "The recommended pilot ceiling prevents input truncation for these six inputs only.",
            "Tokenization does not validate long-input inference feasibility, memory, or summary quality.",
            "When input exceeds its limit, the current service right-truncates the whole prompt and loses the trailing Summary: cue.",
            "No production configuration or realtime preprocessing integration was changed.",
        ],
        "articles": rows,
    }
    # Recheck for a race using exclusive creation; never overwrite a prior run.
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(exist_ok=False)
    atomic_write_json(destination / "pilot_inputs.json", inputs, indent=2)
    (destination / "prompt_template.txt").write_text(baseline["SUMMARY_PROMPT"], encoding="utf-8")
    atomic_write_json(destination / "token_report.json", report, indent=2)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--flan-source", type=Path, default=DEFAULT_FLAN_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    output = args.output_dir or Path("output/flan_evaluation") / (
        f"pilot_tokens_{datetime.now(timezone.utc):%Y%m%dT%H%M%S_%fZ}"
    )
    try:
        report = run_preflight(args.snapshot_dir, args.flan_source, output)
    except (OSError, ValueError, TypeError, RuntimeError, ImportError) as exc:
        parser.exit(1, f"Token preflight stopped: {type(exc).__name__}: {exc}\n")
    for row in report["articles"]:
        print(f"{row['complete_input_tokens']:>5} tokens | {row['title']}")
    print(f"Recommended fixed pilot input ceiling: {report['recommended_pilot_max_input_tokens']}")
    print("No model weights loaded; no inference performed; production unchanged.")
    print(f"Report: {output.resolve() / 'token_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

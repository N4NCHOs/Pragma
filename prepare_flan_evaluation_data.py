"""Create an auditable, separate footer-cleaned FLAN evaluation snapshot.

No network, model, database, asset filtering, or novelty evaluation is invoked.
The live collector file is read once and never written. See
FLAN_PREPROCESSING_README.md for scope and future realtime integration.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from article_preprocessing import (
    EMPTY_FOOTER_HEADING,
    KNOWN_PROMOTIONAL_FOOTER,
    PREPROCESSING_VERSION,
    clean_article_footer_with_audit,
)
from pipeline_experiment_data import atomic_write_json, compute_dataset_hash


DEFAULT_SOURCE = Path("output/rss_dataset_recovered/qualified_news.json")
DEFAULT_OUTPUT_ROOT = Path("output/flan_evaluation")


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prepare_articles(
    articles: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Return cleaned copies, an audit report, and inspectable change examples.

    Article IDs/order and all fields other than ``full_body`` are preserved.
    No record is dropped or requalified. Stored qualification/novelty fields
    describe the original collector decision, not a recomputed decision on the
    cleaned text. Malformed inputs fail before any export is attempted.
    """
    if not isinstance(articles, list) or not articles:
        raise ValueError("source must be a nonempty JSON list of qualified articles")

    cleaned_articles: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    empty_after_cleaning: list[str] = []

    for index, article in enumerate(articles, 1):
        if not isinstance(article, dict):
            raise ValueError(f"article {index} must be a JSON object")
        article_id = article.get("dataset_article_id")
        if not isinstance(article_id, str) or not article_id.strip():
            raise ValueError(f"article {index} has no nonempty dataset_article_id")
        if article_id in seen_ids:
            raise ValueError(f"duplicate dataset_article_id at article {index}: {article_id}")
        seen_ids.add(article_id)
        for key in ("title", "full_body"):
            if not isinstance(article.get(key), str) or not article[key].strip():
                raise ValueError(f"article {index} needs a nonempty string {key}")
        if "qualification_status" in article and article["qualification_status"] != "qualified":
            raise ValueError(f"article {index} is not marked qualified")
        if "is_redundant" in article and article["is_redundant"] is not False:
            raise ValueError(f"article {index} is not marked is_redundant=false")

        body = article["full_body"]
        result = clean_article_footer_with_audit(body)
        # A shallow copy suffices: no other field or nested object is modified.
        cleaned_articles.append({**article, "full_body": result.text})
        if not result.text.strip():
            empty_after_cleaning.append(article_id)
        audit = {
            "article_index": index,
            "dataset_article_id": article_id,
            "title": article["title"],
            "changed": result.changed,
            "removed_blocks": result.removed_blocks,
            "removed_characters": len(result.removed_text),
            "original_body_characters": len(body),
            "cleaned_body_characters": len(result.text),
            "original_body_sha256": _text_hash(body),
            "cleaned_body_sha256": _text_hash(result.text),
        }
        audits.append(audit)
        if result.changed:
            changes.append({
                "dataset_article_id": article_id,
                "title": article["title"],
                "removed_text": result.removed_text,
                "before_tail": body[-500:],
                "after_tail": result.text[-500:],
            })

    report = {
        "schema_version": 1,
        "preprocessing_version": PREPROCESSING_VERSION,
        "rule": {
            "exact_paragraph": KNOWN_PROMOTIONAL_FOOTER,
            "required_empty_heading": EMPTY_FOOTER_HEADING,
            "position": "consecutive whole-line blocks at end of full_body only",
            "supports": ["LF", "CRLF", "terminal whitespace after empty heading"],
        },
        "article_count": len(articles),
        "changed_count": len(changes),
        "unchanged_count": len(articles) - len(changes),
        "removed_footer_blocks": sum(item["removed_blocks"] for item in audits),
        "removed_characters": sum(item["removed_characters"] for item in audits),
        "empty_after_cleaning_ids": empty_after_cleaning,
        "original_dataset_hash": compute_dataset_hash(articles),
        "cleaned_dataset_hash": compute_dataset_hash(cleaned_articles),
        "article_order_and_ids_preserved": True,
        "asset_filter_recomputed": False,
        "novelty_recomputed": False,
        "cohort_selected": False,
        "limitations": [
            "Only the exact known trailing footer is removed; unmatched text is unchanged.",
            "Nonempty full_body and stored qualified flags do not prove a complete, clean scrape.",
            "Snippets, navigation text, inline links, and newsletter sections are not repaired.",
            "Stored qualification and novelty metadata describe the original collection text.",
            "This is a preprocessing snapshot, not a final evaluation cohort or a model run.",
        ],
        "articles": audits,
    }
    return cleaned_articles, report, changes


def export_snapshot(
    source_path: Path, output_dir: Path | None = None, *, preview: bool = False,
) -> dict[str, Any]:
    """Read one consistent source snapshot and preview/export without overwrites.

    The source is read once as bytes. The raw snapshot preserves these exact
    bytes, even if the collector replaces its live file later. A destination
    directory is created exclusively: rerunning against it never overwrites a
    prior experiment. A partial export has no report marked complete.
    """
    source_path = Path(source_path).resolve(strict=True)
    source_bytes = source_path.read_bytes()
    articles = json.loads(source_bytes)
    cleaned, report, changes = prepare_articles(articles)
    report.update({
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_path": str(source_path),
        "source_file_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "raw_snapshot_file": "qualified_news_raw.json",
        "cleaned_snapshot_file": "qualified_news_cleaned.json",
        "changes_file": "changes.json",
        "status": "preview" if preview else "complete",
    })
    if preview:
        return {"report": report, "changes": changes, "output_dir": None}

    destination = (
        Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_ROOT /
        f"preprocessed_{datetime.now(timezone.utc):%Y%m%dT%H%M%S_%fZ}"
    ).resolve()
    if destination == source_path or destination in source_path.parents:
        raise ValueError("output directory cannot be the source file or an ancestor of it")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(exist_ok=False)

    # All payload validation and JSON serialization precede creation of any
    # final report. The report is the last file and acts as a completion marker.
    report["output_dir"] = str(destination)
    (destination / "qualified_news_raw.json").write_bytes(source_bytes)
    atomic_write_json(destination / "qualified_news_cleaned.json", cleaned, indent=2)
    atomic_write_json(destination / "changes.json", changes, indent=2)
    atomic_write_json(destination / "preprocessing_report.json", report, indent=2)
    return {"report": report, "changes": changes, "output_dir": str(destination)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, help="new directory; must not exist")
    parser.add_argument("--preview", action="store_true", help="show changes without writing files")
    args = parser.parse_args(argv)
    try:
        outcome = export_snapshot(args.source, args.output_dir, preview=args.preview)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(1, f"Preprocessing stopped: {type(exc).__name__}: {exc}\n")

    report = outcome["report"]
    print(f"Preprocessing: {report['preprocessing_version']}")
    print(f"Source SHA-256: {report['source_file_sha256']}")
    print(
        f"Articles: {report['article_count']}; changed: {report['changed_count']}; "
        f"unchanged: {report['unchanged_count']}"
    )
    print("No articles dropped. Stored asset/novelty decisions were not recomputed.")
    if report["empty_after_cleaning_ids"]:
        print(f"WARNING: empty cleaned bodies: {report['empty_after_cleaning_ids']}")
    if args.preview:
        print("Preview only: no files written.")
        for example in outcome["changes"][:1]:
            print(f"\nExample: {example['dataset_article_id']} | {example['title']}")
            print("\nBEFORE (last 500 characters):\n" + example["before_tail"])
            print("\nAFTER (last 500 characters):\n" + example["after_tail"])
    else:
        print(f"Snapshot: {outcome['output_dir']}")
        print("Use qualified_news_cleaned.json for all FLAN configurations and silver references.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

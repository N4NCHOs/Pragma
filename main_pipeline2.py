"""Experimental pipeline with per-run CSV snapshots; main_pipeline is unchanged.

Run: python main_pipeline2.py --confirm-db-reset --max-input-tokens 512 1024 2048 3072
Use --prepare-only to collect/check the fixed 100-article batch without truncation.
Experiments clear public.news_articles before EVERY iteration, including the first.
Backups, a frozen dataset, diagnostics, and separate CSVs are retained per experiment.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import csv
import json
import logging
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pipeline_experiment_data import (
    DatasetShortfallError, atomic_write_json, compute_dataset_hash, prepare_fixed_batch,
)

logger = logging.getLogger("main_pipeline2")
VALID_MODES = ("sequential", "concurrent")
DEFAULT_CSV_OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "pipeline_results"
DEFAULT_EXPERIMENT_OUTPUT_DIR = DEFAULT_CSV_OUTPUT_DIR / "experiments"
DEFAULT_MAX_INPUT_LIMITS = (512, 1024, 2048, 3072)

FIELDNAMES = (
    "run_id", "article_index", "exported_at", "inference_mode",
    "title", "url", "image_url", "article_body", "text_source", "model_input_text",
    "is_redundant", "novelty_label", "extracted_assets", "summary",
    "flan_input_tokens", "flan_output_tokens", "flan_input_truncated",
    "flan_inference_seconds", "category", "category_confidence", "impact",
    "impact_confidence", "sentiment", "sentiment_confidence", "target_investor",
    "deberta_inference_seconds", "total_inference_seconds", "model_errors",
    "database_id", "database_created_at", "database_status", "database_error",
    "experiment_id", "dataset_sha256", "flan_max_input_tokens", "flan_original_input_tokens",
)


class ExperimentIncompleteError(RuntimeError):
    """An incomplete iteration must not trigger another destructive reset."""


def _json_cell(value: Any) -> str:
    """Keep SQL null distinct from an empty JSON list/dictionary."""
    return "" if value is None else json.dumps(value, ensure_ascii=False)


class CsvRunExport:
    """Maintain one durable CSV snapshot per run and one row per save attempt.

    Snapshots are replaced atomically, so an interrupted rewrite leaves the
    previous complete CSV intact. A pending row is written before DB insertion.
    CSV and PostgreSQL cannot participate in one atomic transaction; pending
    rows can remain if interrupted or if a status rewrite fails.
    """

    def __init__(self, output_dir: Path = DEFAULT_CSV_OUTPUT_DIR) -> None:
        self.run_id = f"{datetime.now(timezone.utc):%Y%m%d_%H%M%S_%f}_{uuid4().hex}"
        self.path = Path(output_dir) / f"pipeline_results_{self.run_id}.csv"
        self.rows: list[dict[str, Any]] = []
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.write()

    def write(self) -> None:
        """Flush a complete UTF-8 CSV, including its header, then replace it."""
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8-sig", newline="",
                dir=self.path.parent, prefix=f".{self.path.stem}_", suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
                writer.writeheader()
                writer.writerows(self.rows)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def capture(
        self, article_index: int, article: dict[str, Any], record: Any,
        outcome: Any | None, mode: str,
    ) -> int:
        """Copy the exact persisted fields plus available inference measurements."""
        text_source = next(
            (key for key in ("full_body", "rss_summary", "description") if article.get(key)),
            "",
        )
        row = dict.fromkeys(FIELDNAMES, "")
        row.update(
            run_id=self.run_id,
            article_index=article_index,
            exported_at=datetime.now(timezone.utc).isoformat(),
            inference_mode=mode,
            title=record.title,
            url=record.url,
            image_url=record.image_url,
            article_body=record.description,
            text_source=text_source,
            # Redundant articles do not enter model inference.
            model_input_text=(f"{article.get('title', '')}. {article.get(text_source) or ''}"
                              if outcome is not None else ""),
            is_redundant=record.is_redundant,
            novelty_label=record.novelty_label,
            extracted_assets=_json_cell(record.extracted_assets),
            summary=record.summary,
            category=record.category,
            impact=record.impact,
            sentiment=record.sentiment,
            target_investor=_json_cell(record.target_investor),
            database_status="pending",
        )
        if outcome is not None:
            row["total_inference_seconds"] = outcome.elapsed_seconds
            row["model_errors"] = _json_cell({
                name: f"{type(error).__name__}: {error}"
                for name, error in outcome.errors.items()
            })
            summary = outcome.summary_result
            if summary is not None:
                row.update(
                    flan_input_tokens=summary.input_token_count,
                    flan_original_input_tokens=summary.original_input_token_count,
                    flan_output_tokens=summary.output_token_count,
                    flan_input_truncated=summary.input_was_truncated,
                    flan_inference_seconds=summary.inference_seconds,
                )
            classification = outcome.classification_result
            if classification is not None:
                row.update(
                    category_confidence=classification.category_confidence,
                    impact_confidence=classification.impact_confidence,
                    sentiment_confidence=classification.sentiment_confidence,
                    deberta_inference_seconds=classification.inference_seconds,
                )
        row_index = len(self.rows)
        self.rows.append(row)
        # Keep the in-memory row if disk writing fails, allowing a later retry.
        self.write()
        return row_index

    def mark_saved(
        self, index: int, record: Any | None, error: BaseException | None = None,
    ) -> None:
        row = self.rows[index]
        row["database_status"] = "saved"
        if record is not None:
            row["database_id"] = record.id
            row["database_created_at"] = (
                record.created_at.isoformat() if record.created_at is not None else ""
            )
        if error is not None:
            row["database_error"] = f"Post-commit processing failed: {type(error).__name__}: {error}"
        self.write()

    def mark_failed(self, index: int, error: BaseException) -> None:
        self.rows[index].update(
            database_status="failed", database_error=f"{type(error).__name__}: {error}",
        )
        self.write()


def _try_csv(operation: Callable[..., Any], *args: Any) -> Any:
    """CSV failures must never trigger rollback or skip an article's DB save."""
    try:
        return operation(*args)
    except Exception:
        logger.warning("CSV export failed; database processing will continue", exc_info=True)
        print(" -> [CSV-WARNING] Export incomplete; see log for details.")
        return None


async def run_pipeline(
    mode: str, *, news_batch: list[dict[str, Any]] | None = None,
    csv_output_dir: Path | None = None, strict: bool = False,
    flan_max_input_tokens: int | None = None, experiment_id: str = "",
    dataset_sha256: str = "",
) -> CsvRunExport | None:
    # Reuse the original dependencies and inference function without changing
    # them. Lazy import also lets --help and CSV tests run without loading ML/DB.
    import main_pipeline as pipeline

    concurrent = mode == "concurrent"
    csv_export = _try_csv(CsvRunExport, csv_output_dir or DEFAULT_CSV_OUTPUT_DIR)
    if csv_export is None and strict:
        raise ExperimentIncompleteError("Cannot create iteration CSV; processing stopped.")
    if csv_export is not None:
        print(f"CSV results: {csv_export.path}")

    if news_batch is None:
        print("\nStep 1: Running Scraper...")
        print(f"[Scraper Summary] {pipeline.run_scheduler()}")
        try:
            with open("output/scraped_news.json", "r", encoding="utf-8") as handle:
                news_batch = json.load(handle)
        except FileNotFoundError:
            print("scraped_news.json not found! Scraper may have failed.")
            return None
    else:
        print(f"Using frozen experiment batch: {len(news_batch)} articles (no refetch).")

    db = pipeline.SessionLocal()
    inference_times: list[float] = []
    saved_count = failed_count = dropped_count = 0
    strict_issues: list[str] = []
    try:
        print("\n==========================================")
        print("Step 2: Processing Pipeline...")
        print(f"Inference mode: {mode.upper()}")
        print("==========================================")
        total = len(news_batch)
        print(f"Found {total} articles to process.\n")
        for i, article in enumerate(news_batch, 1):
            print(f"[{i}/{total}] {article.get('title')}")
            # Reset per-article state so redundant/failed articles never inherit
            # another article's inference output or CSV index.
            outcome = None
            row_index = None
            database_committed = False
            try:
                if not pipeline.is_top_10_news(article):
                    dropped_count += 1
                    strict_issues.append(f"Article {i}: rejected by asset filter")
                    print(" -> [DROPPED] Not a Top 10 asset\n")
                    continue

                uncommitted_article = pipeline.process_incoming_news(article, db)
                if uncommitted_article.is_redundant:
                    strict_issues.append(f"Article {i}: redundant, so NLP inference was skipped")
                if uncommitted_article.is_redundant == False:
                    title = article.get("title", "")
                    body = article.get("full_body") or article.get("rss_summary") or article.get("description") or ""
                    full_text = f"{title}. {body}"
                    outcome = await pipeline.run_ai_inference(full_text, concurrent=concurrent)
                    inference_times.append(outcome.elapsed_seconds)
                    if outcome.errors or outcome.summary_result is None or outcome.classification_result is None:
                        strict_issues.append(f"Article {i}: incomplete AI results ({', '.join(outcome.errors)})")
                    for model_name, exc in outcome.errors.items():
                        logger.error(
                            "AI inference failed [%d/%d] model=%s title=%s",
                            i, total, model_name, article.get("title"), exc_info=exc,
                        )
                        print(f" -> [AI-ERROR] {model_name}: {exc}")

                    uncommitted_article.extracted_assets = outcome.entities
                    if outcome.summary_result is not None:
                        uncommitted_article.summary = outcome.summary_result.summary
                    if outcome.classification_result is not None:
                        classification_result = outcome.classification_result
                        uncommitted_article.category = classification_result.category
                        uncommitted_article.impact = classification_result.impact
                        uncommitted_article.sentiment = classification_result.sentiment
                        uncommitted_article.target_investor = classification_result.target_investor

                    found_texts = [entity['matched_text'] for entity in outcome.entities]
                    print(f" -> Found Entities: {found_texts or None}")
                    if outcome.summary_result is not None:
                        summary_result = outcome.summary_result
                        print(f" -> FLAN-T5 Summary: {summary_result.summary}")
                        print(
                            " -> FLAN-T5 Metrics: "
                            f"{summary_result.inference_seconds:.3f}s, "
                            f"{summary_result.input_token_count} input tokens, "
                            f"{summary_result.output_token_count} output tokens, "
                            f"truncated={summary_result.input_was_truncated}\n"
                        )
                    if outcome.classification_result is not None:
                        classification_result = outcome.classification_result
                        print(
                            " -> DeBERTa Classification: "
                            f"category={classification_result.category} "
                            f"({classification_result.category_confidence}), "
                            f"impact={classification_result.impact} "
                            f"({classification_result.impact_confidence}), "
                            f"sentiment={classification_result.sentiment} "
                            f"({classification_result.sentiment_confidence})"
                        )
                        print(f" -> DeBERTa Target Investor: {classification_result.target_investor}")
                        print(f" -> DeBERTa Metrics: {classification_result.inference_seconds:.3f}s\n")
                    print(f" -> [TIMING] inference: {outcome.elapsed_seconds:.3f}s (mode={mode})")

                # Capture before add/commit. Export failures are isolated from
                # the existing database transaction, including status updates.
                if csv_export is not None:
                    candidate_index = len(csv_export.rows)
                    _try_csv(csv_export.capture, i, article, uncommitted_article, outcome, mode)
                    if len(csv_export.rows) > candidate_index:
                        row_index = candidate_index
                        csv_export.rows[row_index].update(
                            experiment_id=experiment_id, dataset_sha256=dataset_sha256,
                            flan_max_input_tokens=flan_max_input_tokens or "",
                        )
                        # Persist configuration metadata with the pre-save row.
                        _try_csv(csv_export.write)

                db.add(uncommitted_article)
                db.commit()
                database_committed = True
                saved_count += 1
                db.refresh(uncommitted_article)
                if csv_export is not None and row_index is not None:
                    _try_csv(csv_export.mark_saved, row_index, uncommitted_article)

                label = "Redundant" if uncommitted_article.is_redundant else "Unique"
                print(f" -> [PROCESSED] Saved to DB with ID: {uncommitted_article.id} ({label})\n")
            except Exception as exc:
                # A refresh failure after commit cannot undo the saved record.
                if csv_export is not None and row_index is not None:
                    if database_committed:
                        _try_csv(csv_export.mark_saved, row_index, None, exc)
                    else:
                        _try_csv(csv_export.mark_failed, row_index, exc)
                db.rollback()
                if not database_committed:
                    failed_count += 1
                strict_issues.append(f"Article {i}: {type(exc).__name__}: {exc}")
                logger.exception("Article failed entirely [%d/%d] title=%s", i, total, article.get("title"))
                if database_committed:
                    print(f" -> [ERROR] Article {i} was committed, but post-save processing failed.\n")
                else:
                    print(f" -> [ERROR] Skipped article {i}: see log for traceback\n")
                continue

        if inference_times:
            total_seconds = sum(inference_times)
            count = len(inference_times)
            print(
                f"\n[INFERENCE TIMING SUMMARY] mode={mode} | articles={count} | "
                f"total={total_seconds:.3f}s | mean={total_seconds / count:.3f}s | "
                f"min={min(inference_times):.3f}s | max={max(inference_times):.3f}s\n"
            )
    finally:
        db.close()
        if csv_export is not None:
            # Retry prior failed writes without dropping rows already in memory.
            _try_csv(csv_export.write)
            print(f"CSV results: {csv_export.path} ({len(csv_export.rows)} result rows)")
        else:
            print("[CSV-WARNING] No CSV was created. Database processing was unchanged.")
        print(f"[PROCESSING TOTALS] saved={saved_count}, failed={failed_count}, dropped={dropped_count}")
    if strict:
        if csv_export is None or len(csv_export.rows) != len(news_batch) or saved_count != len(news_batch):
            strict_issues.append(f"Expected {len(news_batch)} exported/saved articles; saved {saved_count}")
        if strict_issues:
            raise ExperimentIncompleteError("Iteration incomplete; no next reset: " + "; ".join(strict_issues))
    return csv_export


def reset_rss_files(scheduler: Any, backup_dir: Path) -> None:
    """Back up then clear ONLY the scheduler's three known working JSON files."""
    paths = (
        (Path(scheduler.RSS_TEMP_FILE), "rss_temp.json"),
        (Path(scheduler.RSS_HISTORY_FILE), "rss_history.json"),
        (Path(scheduler.SCRAPED_NEWS_FILE), "scraped_news.json"),
    )
    if any(path.name != name for path, name in paths):
        raise ValueError("RSS reset refused: unexpected scheduler output filename")
    backup_dir.mkdir(parents=True, exist_ok=True)
    # Complete all backups before changing any working file.
    for path, name in paths:
        if path.exists():
            shutil.copy2(path, backup_dir / name)
    for path, _ in paths:
        atomic_write_json(path, [])


def reset_news_articles(pipeline: Any, backup_path: Path) -> None:
    """Back up and truncate the exact table from TABLE_DDL.sql, without CASCADE.

    No other tables/schema are dropped. An unavailable backup, unexpected foreign
    key, or concurrent transaction holding the table causes rollback, not CASCADE.
    """
    from sqlalchemy import text

    db = pipeline.SessionLocal()
    try:
        engine = db.get_bind()
        print(f"[DESTRUCTIVE RESET] {engine.url.render_as_string(hide_password=True)} / public.news_articles")
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL lock_timeout = '5s'"))
            connection.execute(text("LOCK TABLE public.news_articles IN ACCESS EXCLUSIVE MODE"))
            database_name = connection.execute(text("SELECT current_database()" )).scalar_one()
            rows = connection.execute(
                text("SELECT row_to_json(article) FROM public.news_articles AS article")
            ).scalars().all()
            atomic_write_json(backup_path, {
                "database": database_name, "table": "public.news_articles",
                "backed_up_at": datetime.now(timezone.utc).isoformat(), "rows": rows,
            })
            connection.execute(text("TRUNCATE TABLE public.news_articles RESTART IDENTITY"))
        print(f"Reset public.news_articles; {len(rows)} prior rows backed up to {backup_path}")
    finally:
        db.close()


def _collect_source_articles(scheduler: Any, candidate_limit: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Use the EXISTING feed/scraping functions with a wider experiment window.

    A larger slice cannot create articles absent from the feed. No pagination,
    alternate source, fallback body, or new scraping mechanism is introduced.
    """
    scheduler.write_json_atomic(scheduler.SCRAPED_NEWS_FILE, [])
    with scheduler.requests.Session() as session:
        session.headers.update(scheduler.BROWSER_HEADERS)
        candidates = scheduler.fetch_latest_rss(session, limit=candidate_limit)
        scheduler.write_json_atomic(scheduler.RSS_TEMP_FILE, candidates)
        scraped: list[dict[str, Any]] = []
        for index, article in enumerate(candidates, 1):
            print(f"[Collect {index}/{len(candidates)}] {article.get('title')}")
            scraped.append(scheduler.scrape_article(session, article))
            scheduler.write_json_atomic(scheduler.SCRAPED_NEWS_FILE, scraped)
            if scheduler.DELAY_BETWEEN_REQUESTS and index < len(candidates):
                time.sleep(scheduler.DELAY_BETWEEN_REQUESTS)
    scheduler.write_json_atomic(scheduler.RSS_HISTORY_FILE, candidates)
    return scraped, {
        "rss_items": len(candidates), "candidate_limit": candidate_limit,
        "scrape_success": sum(item.get("scrape_status") == "success" for item in scraped),
        "scrape_failed": sum(item.get("scrape_status") != "success" for item in scraped),
    }


def _generation_settings() -> dict[str, Any]:
    """Read literal generation options from the actual service, not a second config."""
    source = Path(__file__).resolve().parent / "ai_models" / "flan_t5.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "generate":
            settings = {}
            for keyword in node.keywords:
                if keyword.arg is not None:
                    try:
                        settings[keyword.arg] = ast.literal_eval(keyword.value)
                    except (ValueError, TypeError):
                        settings[keyword.arg] = {"source_expression": ast.unparse(keyword.value)}
            return settings
    raise RuntimeError("Cannot identify generation settings in the current FLAN service")


def verify_iteration_export(
    export: CsvRunExport | None, expected_count: int, dataset_sha256: str, limit: int,
) -> None:
    """Only a durable, complete CSV permits the next database reset."""
    if export is None:
        raise ExperimentIncompleteError("No CSV export exists")
    previous_limit = csv.field_size_limit()
    try:
        # Full article text can exceed the CSV reader's small default limit.
        csv.field_size_limit(max(previous_limit, export.path.stat().st_size))
        with export.path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    finally:
        csv.field_size_limit(previous_limit)
    if len(rows) != expected_count:
        raise ExperimentIncompleteError(f"CSV has {len(rows)} rows, expected exactly {expected_count}")
    if [row["article_index"] for row in rows] != [str(i) for i in range(1, expected_count + 1)]:
        raise ExperimentIncompleteError("CSV article order/identifiers do not match fixed dataset")
    for row in rows:
        if (row["database_status"] != "saved" or row["database_error"]
                or not row["summary"].strip() or not row["category"]
                or row["model_errors"] not in ("", "{}")
                or row["is_redundant"] != "False"
                or row["dataset_sha256"] != dataset_sha256
                or row["flan_max_input_tokens"] != str(limit)):
            raise ExperimentIncompleteError(f"CSV article {row['article_index']} is incomplete or inconsistent")


async def run_experiments(
    mode: str, *, max_input_limits: tuple[int, ...] = DEFAULT_MAX_INPUT_LIMITS,
    target_count: int = 100, dataset_path: Path | None = None,
    confirm_db_reset: bool = False, prepare_only: bool = False, candidate_limit: int = 1000,
) -> None:
    """Collect once, validate before deletion, then run controlled full-pipeline iterations."""
    if not prepare_only and not confirm_db_reset:
        raise ValueError("Database reset requires --confirm-db-reset; use --prepare-only to check articles safely.")
    if mode not in VALID_MODES or target_count <= 0 or candidate_limit <= 0:
        raise ValueError("Invalid inference mode or article count")
    if not max_input_limits or any(limit <= 0 for limit in max_input_limits) or len(set(max_input_limits)) != len(max_input_limits):
        raise ValueError("Input limits must be distinct positive integers")

    experiment_id = f"{datetime.now(timezone.utc):%Y%m%d_%H%M%S_%f}_{uuid4().hex}"
    experiment_dir = DEFAULT_EXPERIMENT_OUTPUT_DIR / experiment_id
    experiment_dir.mkdir(parents=True, exist_ok=False)
    manifest_path = experiment_dir / "experiment.json"
    manifest: dict[str, Any] = {
        "experiment_id": experiment_id, "target_count": target_count, "mode": mode,
        "max_input_limits": list(max_input_limits), "candidate_limit": candidate_limit,
        "status": "preparing", "iterations": [],
    }
    atomic_write_json(manifest_path, manifest)
    print(f"Experiment files: {experiment_dir}")
    try:
        import main_pipeline as pipeline
        import rss_scrape_scheduler as scheduler
        from ai_models import novelty_detection as novelty

        if dataset_path is not None:
            source_articles = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
            if not isinstance(source_articles, list):
                raise ValueError("The dataset must be a JSON list of normalized scraped articles")
            manifest["source"] = str(Path(dataset_path).resolve())
        else:
            reset_rss_files(scheduler, experiment_dir / "collection_rss_backup")
            source_articles, scrape_stats = _collect_source_articles(scheduler, candidate_limit)
            manifest["scraper_stats"] = scrape_stats
            manifest["source"] = scheduler.RSS_URL
        atomic_write_json(experiment_dir / "source_articles.json", source_articles)

        try:
            batch, report = prepare_fixed_batch(
                source_articles, target_count=target_count,
                asset_filter=pipeline.is_top_10_news,
                encode_text=novelty.embedding_model.encode,
                distance_threshold=novelty.SIMILARITY_THRESHOLD_DISTANCE,
                key_function=scheduler.article_keys,
            )
        except DatasetShortfallError as exc:
            atomic_write_json(experiment_dir / "collection_report.json", exc.report)
            raise
        atomic_write_json(experiment_dir / "collection_report.json", report)
        # A copy outside RSS output survives all subsequent working-file resets.
        frozen_path = experiment_dir / "fixed_articles.json"
        atomic_write_json(frozen_path, batch)
        dataset_hash = compute_dataset_hash(batch)
        manifest.update(dataset_sha256=dataset_hash, fixed_dataset=str(frozen_path),
                        article_count=len(batch), status="prepared")
        flan_module = sys.modules.get("ai_models.flan_t5")
        manifest["flan_model"] = getattr(pipeline.flan_service, "model_name", "unknown")
        manifest["flan_prompt"] = getattr(flan_module, "SUMMARY_PROMPT", None)
        manifest["generation_settings"] = _generation_settings()
        manifest["flan_device"] = str(getattr(pipeline.flan_service, "device", "unknown"))
        manifest["novelty_distance_threshold"] = novelty.SIMILARITY_THRESHOLD_DISTANCE
        atomic_write_json(manifest_path, manifest)
        print(f"Prepared exactly {len(batch)} eligible unique full articles: {frozen_path}")
        if prepare_only:
            print("Preparation only: database not truncated and no NLP iteration executed.")
            return

        original_limit = pipeline.flan_service.max_input_tokens
        try:
            for limit in max_input_limits:
                iteration_dir = experiment_dir / f"flan_{limit}"
                iteration_dir.mkdir()
                iteration = {"max_input_tokens": limit, "status": "starting", "directory": str(iteration_dir)}
                manifest["iterations"].append(iteration)
                manifest["status"] = "running"
                atomic_write_json(manifest_path, manifest)
                # Revalidate frozen content before EVERY destructive reset.
                if compute_dataset_hash(batch) != dataset_hash:
                    raise ExperimentIncompleteError("Frozen article data changed; reset refused")
                reset_rss_files(scheduler, iteration_dir / "rss_backup")
                reset_news_articles(pipeline, iteration_dir / "database_before_reset.json")
                pipeline.flan_service.max_input_tokens = limit
                export = await run_pipeline(
                    mode, news_batch=batch, csv_output_dir=iteration_dir, strict=True,
                    flan_max_input_tokens=limit, experiment_id=experiment_id,
                    dataset_sha256=dataset_hash,
                )
                verify_iteration_export(export, target_count, dataset_hash, limit)
                iteration.update(status="complete", csv=str(export.path), rows=target_count)
                atomic_write_json(manifest_path, manifest)
                print(f"[COMPLETE] FLAN input limit {limit}: {target_count} rows -> {export.path}")
        finally:
            pipeline.flan_service.max_input_tokens = original_limit
        manifest["status"] = "complete"
        atomic_write_json(manifest_path, manifest)
        print("All requested iterations completed. PostgreSQL retains the FINAL iteration's records.")
    except Exception as exc:
        manifest.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        if manifest["iterations"] and manifest["iterations"][-1]["status"] != "complete":
            manifest["iterations"][-1]["status"] = "failed"
        atomic_write_json(manifest_path, manifest)
        print(f"Experiment stopped: {exc}\nDiagnostic files: {experiment_dir}")
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare FLAN input lengths on exactly 100 fixed articles.")
    parser.add_argument(
        "--mode", choices=VALID_MODES, default=None,
        help="Overrides PIPELINE_INFERENCE_MODE; defaults to sequential.",
    )
    parser.add_argument("--max-input-tokens", nargs="+", type=int, default=DEFAULT_MAX_INPUT_LIMITS,
                        help="Input ceilings to compare (default: 512 1024 2048 3072).")
    parser.add_argument("--dataset", type=Path, help="Reuse a JSON list of normalized scraped articles.")
    parser.add_argument("--candidate-limit", type=int, default=1000,
                        help="Consider up to this many existing RSS entries to obtain 100 eligible articles (default: 1000; actual feed may be shorter).")
    parser.add_argument("--prepare-only", action="store_true", help="Collect/validate 100 articles without database reset or NLP runs.")
    parser.add_argument("--confirm-db-reset", action="store_true",
                        help="Authorize truncating public.news_articles before EVERY iteration, including the first.")
    args = parser.parse_args()
    mode = args.mode or os.getenv("PIPELINE_INFERENCE_MODE", "sequential")
    if mode not in VALID_MODES:
        parser.error(f"invalid inference mode {mode!r}; expected one of {', '.join(VALID_MODES)}")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not args.prepare_only and not args.confirm_db_reset:
        parser.error("use --prepare-only to check availability, or --confirm-db-reset to run destructive experiments")
    try:
        asyncio.run(run_experiments(
            mode, max_input_limits=tuple(args.max_input_tokens), dataset_path=args.dataset,
            confirm_db_reset=args.confirm_db_reset, prepare_only=args.prepare_only,
            candidate_limit=args.candidate_limit,
        ))
    except Exception as exc:
        logger.error("Experiment aborted: %s", exc)
        parser.exit(1)


if __name__ == "__main__":
    main()

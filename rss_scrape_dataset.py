"""Accumulate a frozen research dataset without running the production pipeline.

Run: python rss_scrape_dataset.py [--once] [--target 200]
Data: output/rss_dataset/ (independent of the production RSS output/history).
No database, FLAN, DeBERTa, or cryptoNER imports or calls are made.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any

from pipeline_experiment_data import (
    _cosine_distance, _unit_vector, _valid_http_url, atomic_write_json, compute_dataset_hash,
)

ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = ROOT / "output" / "rss_dataset"
DEFAULT_TARGET = 200
DEFAULT_POLL_SECONDS = 900.0
MAX_ATTEMPTS = 3


class DatasetPersistenceError(RuntimeError):
    """Stop collection when progress cannot be saved reliably."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_novelty_config() -> tuple[str, float]:
    """Read the existing configuration without importing its DB-dependent module."""
    tree = ast.parse((ROOT / "ai_models" / "novelty_detection.py").read_text(encoding="utf-8"))
    model_name = threshold = None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        if "SIMILARITY_THRESHOLD_DISTANCE" in names:
            threshold = ast.literal_eval(node.value)
        if "embedding_model" in names and isinstance(node.value, ast.Call):
            if isinstance(node.value.func, ast.Name) and node.value.func.id == "SentenceTransformer":
                model_name = ast.literal_eval(node.value.args[0])
    if not isinstance(model_name, str) or not isinstance(threshold, (int, float)):
        raise RuntimeError("Cannot read the existing novelty model/threshold; no database module was imported")
    return model_name, float(threshold)


class LazyEncoder:
    """Load only the existing novelty encoder, once and only when needed."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.model: Any = None

    def __call__(self, text: str) -> Any:
        if self.model is None:
            from sentence_transformers import SentenceTransformer

            print(f"Loading novelty encoder: {self.model_name} (no PostgreSQL connection)")
            self.model = SentenceTransformer(self.model_name)
        return self.model.encode(text)


@contextmanager
def collection_lock(output_dir: Path):
    """One collector per directory; OS releases the lock even after a crash."""
    import fcntl

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".collector.lock").open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"Another collector is already using {directory}") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class DatasetCollector:
    """Persist all distinct stories and an ordered, locally novel subset.

    collection_state.json is authoritative. The two article JSON lists and the
    report are regenerated from it on restart, making interrupted exports safe.
    A completed collection is immutable: use a NEW directory for a new target or
    changed qualification settings. It is not tied to a production DB snapshot.
    """

    def __init__(
        self, output_dir: Path, *, target_count: int = DEFAULT_TARGET,
        asset_filter: Callable[[dict[str, Any]], Any], encode_text: Callable[[str], Any],
        model_name: str, distance_threshold: float,
        key_function: Callable[[dict[str, Any]], Any], filter_fingerprint: str = "",
    ) -> None:
        if not isinstance(target_count, int) or isinstance(target_count, bool) or target_count <= 0:
            raise ValueError("target_count must be a positive integer")
        if not math.isfinite(distance_threshold) or not 0 <= distance_threshold <= 2:
            raise ValueError("distance_threshold must be finite and between 0 and 2")
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.output_dir / "collection_state.json"
        self.asset_filter = asset_filter
        self.encode_text = encode_text
        self.key_function = key_function
        self.target_count = target_count
        self.distance_threshold = distance_threshold
        config = {
            "target_count": target_count, "model_name": model_name,
            "distance_threshold": distance_threshold, "filter_fingerprint": filter_fingerprint,
            "policy": "full_body_accepted_pool_cosine_v1", "max_attempts": MAX_ATTEMPTS,
        }
        if self.state_path.exists():
            try:
                self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError("Collection state is unreadable; refusing to overwrite existing data") from exc
            if self.state.get("schema_version") != 1 or self.state.get("config") != config:
                raise ValueError("Collection configuration changed; use a new --output-dir to preserve this dataset")
        else:
            if any((self.output_dir / name).exists() for name in (
                "all_collected_news.json", "qualified_news.json", "collection_report.json",
            )):
                raise RuntimeError("Dataset files exist without authoritative state; refusing to overwrite them")
            self.state = {
                "schema_version": 1, "config": config, "created_at": utc_now(),
                "articles": [], "qualified_ids": [], "vectors": {}, "vector_text_hashes": {}, "polls": 0,
                "poll_errors": [], "last_poll": None, "completed_at": None,
                "frozen_dataset_sha256": None,
            }
        self.articles = self.state["articles"]
        self._validate_state()
        self._by_id = {item["dataset_article_id"]: item for item in self.articles}
        self._keys: dict[str, str] = {}
        for item in self.articles:
            for key in self._article_keys(item) | set(item.get("collection_identity_keys", [])):
                if key in self._keys and self._keys[key] != item["dataset_article_id"]:
                    raise ValueError("State contains duplicate identities; refusing to merge silently")
                self._keys[key] = item["dataset_article_id"]
        if self.complete:
            if self.state["frozen_dataset_sha256"] != compute_dataset_hash(self.qualified):
                raise ValueError("Frozen dataset integrity check failed; existing data was not overwritten")
        self.save()

    def _validate_state(self) -> None:
        if not isinstance(self.articles, list) or any(not isinstance(item, dict) for item in self.articles):
            raise ValueError("Invalid article state")
        ids = [item.get("dataset_article_id") for item in self.articles]
        if any(not isinstance(item, str) or not item for item in ids) or len(set(ids)) != len(ids):
            raise ValueError("Invalid or duplicate stored article IDs")
        qualified_ids = self.state["qualified_ids"]
        vectors = self.state["vectors"]
        text_hashes = self.state.get("vector_text_hashes", {})
        if (not isinstance(qualified_ids, list) or len(set(qualified_ids)) != len(qualified_ids)
                or len(qualified_ids) > self.target_count or not isinstance(vectors, dict)
                or set(qualified_ids) != set(vectors) or set(qualified_ids) != set(text_hashes)
                or not set(qualified_ids).issubset(ids)):
            raise ValueError("Qualified membership/vector cache is inconsistent")
        by_id = {item["dataset_article_id"]: item for item in self.articles}
        dimension = None
        for identity in qualified_ids:
            row = by_id[identity]
            if row.get("qualification_status") != "qualified" or not row.get("full_body"):
                raise ValueError("Qualified article has no valid qualification/body")
            vector = _unit_vector(vectors[identity])
            if abs(math.fsum(float(value) ** 2 for value in vectors[identity]) - 1.0) > 1e-6:
                raise ValueError("Cached embedding is not normalized")
            if text_hashes[identity] != self._text_hash(row):
                raise ValueError("Cached embedding text changed; refusing to reuse stale novelty decisions")
            if dimension is not None and len(vector) != dimension:
                raise ValueError("Stored embeddings have inconsistent dimensions")
            dimension = len(vector)
        if {item["dataset_article_id"] for item in self.articles
                if item.get("qualification_status") == "qualified"} != set(qualified_ids):
            raise ValueError("Article flags and frozen membership disagree")

    @staticmethod
    def _text_hash(article: dict[str, Any]) -> str:
        return hashlib.sha256(f"{article.get('title', '')}. {article.get('full_body') or ''}".encode("utf-8")).hexdigest()

    def _article_keys(self, article: dict[str, Any]) -> set[str]:
        try:
            keys = set(self.key_function(article))
            if keys and all(isinstance(key, str) and key for key in keys):
                return keys
        except (TypeError, ValueError, AttributeError):
            pass
        # Retain malformed entries for audit rather than dropping their evidence.
        identity = {key: article.get(key) for key in ("guid", "url", "title", "full_body")}
        return {"invalid:" + compute_dataset_hash([identity])}

    def _existing(self, article: dict[str, Any]) -> dict[str, Any] | None:
        identities = {self._keys[key] for key in self._article_keys(article) if key in self._keys}
        if len(identities) > 1:
            raise ValueError("Article identity keys conflict with different stored stories")
        return self._by_id[next(iter(identities))] if identities else None

    def contains(self, article: dict[str, Any]) -> bool:
        return self._existing(article) is not None

    @property
    def qualified(self) -> list[dict[str, Any]]:
        return [self._by_id[identity] for identity in self.state["qualified_ids"]]

    @property
    def complete(self) -> bool:
        return len(self.state["qualified_ids"]) == self.target_count

    def needs_scrape(self, article: dict[str, Any]) -> bool:
        previous = self._existing(article)
        return previous is None or (
            previous["qualification_status"] == "rejected_no_full_body"
            and previous.get("collection_scrape_attempts", 1) < MAX_ATTEMPTS
        )

    def observe(self, article: dict[str, Any]) -> None:
        previous = self._existing(article)
        if previous is not None and not self.complete:
            keys = self._article_keys(article) | set(previous.get("collection_identity_keys", []))
            previous["collection_identity_keys"] = sorted(keys)
            for key in keys:
                self._keys[key] = previous["dataset_article_id"]
            previous["collection_last_seen_at"] = utc_now()
            previous["collection_observations"] += 1
            self.save()

    def _qualify(self, article: dict[str, Any]) -> None:
        article.update(asset_filter_passed=None, novelty_checked=False, is_redundant=None,
                       novelty_label=None, exclusion_reason="", matched_article_id=None)
        title, body = article.get("title"), article.get("full_body")
        if not isinstance(title, str) or not title.strip() or not _valid_http_url(article.get("url")):
            article.update(qualification_status="invalid", exclusion_reason="Missing/invalid title or HTTP(S) URL")
            return
        if not isinstance(body, str) or not body.strip():
            article.update(qualification_status="rejected_no_full_body",
                           exclusion_reason=str(article.get("scrape_error") or "Missing full_body; RSS fallback is disabled"))
            return
        article["collection_qualification_attempts"] = article.get("collection_qualification_attempts", 0) + 1
        try:
            article["asset_filter_passed"] = bool(self.asset_filter(article))
            if not article["asset_filter_passed"]:
                article.update(qualification_status="rejected_asset_filter", exclusion_reason="Failed existing asset filter")
                return
            vector = _unit_vector(self.encode_text(f"{title}. {body}"))
            previous_vectors = self.state["vectors"]
            if previous_vectors and len(vector) != len(next(iter(previous_vectors.values()))):
                raise ValueError("Embedding dimension differs from saved novelty cache")
            article["novelty_checked"] = True
            closest_id, distance = None, None
            for identity in self.state["qualified_ids"]:
                current_distance = _cosine_distance(vector, tuple(previous_vectors[identity]))
                if distance is None or current_distance < distance:
                    closest_id, distance = identity, current_distance
            article["novelty_distance"] = distance
            if distance is not None and distance < self.distance_threshold:
                article.update(qualification_status="redundant", is_redundant=True, novelty_label="Low",
                               matched_article_id=closest_id, exclusion_reason="Below existing cosine-distance novelty threshold")
                return
            identity = article["dataset_article_id"]
            article.update(qualification_status="qualified", is_redundant=False, novelty_label="High")
            self.state["qualified_ids"].append(identity)
            self.state["vectors"][identity] = list(vector)
            self.state["vector_text_hashes"][identity] = self._text_hash(article)
        except Exception as exc:
            article.update(qualification_status="qualification_error", exclusion_reason=f"{type(exc).__name__}: {exc}",
                           novelty_checked=False, is_redundant=None, novelty_label=None)

    def add_article(self, article: dict[str, Any]) -> bool:
        """Checkpoint an original story before qualification; freeze at target."""
        if self.complete:
            return False
        if not isinstance(article, dict):
            raise TypeError("Normalized RSS articles must be dictionaries")
        previous = self._existing(article)
        if previous is not None:
            self.observe(article)
            if not self.needs_scrape(article):
                return False
            # Retry only transient missing-body failures; preserve attempt errors.
            previous["collection_attempt_errors"].append(previous.get("scrape_error"))
            for key, value in article.items():
                if not key.startswith("collection_") and key not in {
                    "dataset_article_id", "qualification_status", "is_redundant", "novelty_label",
                    "asset_filter_passed", "novelty_checked", "exclusion_reason", "matched_article_id",
                }:
                    previous[key] = value
            previous["collection_scrape_attempts"] += 1
            keys = self._article_keys(article) | set(previous.get("collection_identity_keys", []))
            previous["collection_identity_keys"] = sorted(keys)
            for key in keys:
                self._keys[key] = previous["dataset_article_id"]
            self._qualify(previous)
            self.save()
            return False
        keys = self._article_keys(article)
        identity = hashlib.sha256("\n".join(sorted(keys)).encode("utf-8")).hexdigest()
        now = utc_now()
        row = dict(article)
        row.update(dataset_article_id=identity, qualification_status="pending", asset_filter_passed=None,
                   novelty_checked=False, is_redundant=None, novelty_label=None, exclusion_reason="",
                   collection_first_seen_at=now, collection_last_seen_at=now, collection_observations=1,
                   collection_scrape_attempts=1, collection_qualification_attempts=0, collection_attempt_errors=[],
                   collection_identity_keys=sorted(keys))
        self.articles.append(row)
        self._by_id[identity] = row
        for key in keys:
            self._keys[key] = identity
        self.save()
        self._qualify(row)
        self.save()
        return True

    def retry_pending(self) -> None:
        """Resume interrupted qualification and retry transient encoder failures."""
        for row in self.articles:
            if self.complete:
                break
            if row["qualification_status"] == "pending" or (
                row["qualification_status"] == "qualification_error"
                and row.get("collection_qualification_attempts", 0) < MAX_ATTEMPTS
            ):
                self._qualify(row)
                self.save()

    def report(self) -> dict[str, Any]:
        return {
            "target_count": self.target_count, "collected_count": len(self.articles),
            "qualified_count": len(self.state["qualified_ids"]), "complete": self.complete,
            "remaining_needed": self.target_count - len(self.state["qualified_ids"]),
            "status_counts": dict(Counter(row["qualification_status"] for row in self.articles)),
            "polls": self.state["polls"], "last_poll": self.state["last_poll"],
            "last_feed_count": self.state.get("last_feed_count"),
            "poll_errors": self.state["poll_errors"], "config": self.state["config"],
            "completed_at": self.state["completed_at"],
            "dataset_sha256": self.state["frozen_dataset_sha256"],
            "rejections": [
                {"dataset_article_id": row["dataset_article_id"], "status": row["qualification_status"],
                 "title": row.get("title"), "reason": row.get("exclusion_reason", "")}
                for row in self.articles if row["qualification_status"] != "qualified"
            ],
        }

    def save(self) -> None:
        if self.complete and self.state["completed_at"] is None:
            self.state["completed_at"] = utc_now()
            self.state["frozen_dataset_sha256"] = compute_dataset_hash(self.qualified)
        elif self.complete and self.state["frozen_dataset_sha256"] != compute_dataset_hash(self.qualified):
            raise DatasetPersistenceError("Frozen dataset was modified; refusing to overwrite it")
        try:
            atomic_write_json(self.state_path, self.state, indent=2)
            atomic_write_json(self.output_dir / "all_collected_news.json", self.articles, indent=2)
            atomic_write_json(self.output_dir / "qualified_news.json", self.qualified, indent=2)
            atomic_write_json(self.output_dir / "collection_report.json", self.report(), indent=2)
        except (OSError, ValueError, TypeError) as exc:
            raise DatasetPersistenceError("Cannot checkpoint dataset; stopping rather than continuing unsaved") from exc


def collect_once(collector: DatasetCollector, scheduler: Any, *, candidate_limit: int = 1000) -> dict[str, Any]:
    """One feed check, using existing extraction functions but no shared output."""
    if collector.complete:
        return collector.report()
    collector.retry_pending()
    if collector.complete:
        return collector.report()
    collector.state["polls"] += 1
    collector.state["last_poll"] = utc_now()
    collector.save()
    try:
        with scheduler.requests.Session() as session:
            session.headers.update(scheduler.BROWSER_HEADERS)
            articles = scheduler.fetch_latest_rss(session, limit=candidate_limit)
            collector.state["last_feed_count"] = len(articles)
            attempted_keys: set[str] = set()
            scrape_count = 0
            for article in articles:
                if collector.complete:
                    break
                keys = collector._article_keys(article)
                if keys & attempted_keys:
                    continue
                attempted_keys.update(keys)
                if collector.contains(article) and not collector.needs_scrape(article):
                    collector.observe(article)
                    continue
                if not _valid_http_url(article.get("url")):
                    collector.add_article(article)
                    continue
                if scrape_count and scheduler.DELAY_BETWEEN_REQUESTS:
                    time.sleep(scheduler.DELAY_BETWEEN_REQUESTS)
                try:
                    result = scheduler.scrape_article(session, article)
                except KeyboardInterrupt:
                    # Preserve the encountered story even when Ctrl+C interrupts
                    # extraction; it can be retried on the next run.
                    collector.add_article(dict(article, full_body=None, scrape_status="failed",
                                               scrape_error="Collection interrupted during extraction", scraped_at=utc_now()))
                    raise
                except Exception as exc:
                    result = dict(article, full_body=None, scrape_status="failed",
                                  scrape_error=f"{type(exc).__name__}: {exc}", scraped_at=utc_now())
                collector.add_article(result)
                scrape_count += 1
    except Exception as exc:
        collector.state["poll_errors"].append({"at": utc_now(), "error": f"{type(exc).__name__}: {exc}"})
        collector.save()
        raise
    collector.save()
    report = collector.report()
    print(f"Collected {report['collected_count']} distinct articles; qualified {report['qualified_count']}/{report['target_count']}.")
    print(f"Statuses: {report['status_counts']}")
    errors = [row for row in report["rejections"] if row["status"] == "qualification_error"]
    if errors:
        print(f"Qualification error (details in collection_report.json): {errors[-1]['reason']}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Accumulate 200 qualified RSS articles without PostgreSQL, FLAN, or DeBERTa.")
    parser.add_argument("--target", type=int, default=DEFAULT_TARGET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--candidate-limit", type=int, default=1000)
    parser.add_argument("--once", action="store_true", help="Check once, keep progress, then exit.")
    parser.add_argument("--seed", type=Path, help="Optionally import an existing JSON list of scraped articles.")
    args = parser.parse_args()
    if args.target <= 0 or args.candidate_limit <= 0 or not math.isfinite(args.poll_seconds) or args.poll_seconds < 60:
        parser.error("target/candidate-limit must be positive; poll-seconds must be at least 60")
    try:
        # Importing the RSS module does NOT run its __main__ reset block.
        import rss_scrape_scheduler as scheduler
        from ai_models.filters import is_top_10_news

        model_name, threshold = load_novelty_config()
        filter_hash = hashlib.sha256((ROOT / "ai_models" / "filters.py").read_bytes()).hexdigest()
        with collection_lock(args.output_dir):
            collector = DatasetCollector(
                args.output_dir, target_count=args.target, asset_filter=is_top_10_news,
                encode_text=LazyEncoder(model_name), model_name=model_name,
                distance_threshold=threshold, key_function=scheduler.article_keys,
                filter_fingerprint=filter_hash,
            )
            print(f"Dataset folder: {args.output_dir.resolve()}")
            print(f"Novelty: {model_name}, cosine distance < {threshold} is redundant.")
            if args.seed is not None and not collector.complete:
                seeded = json.loads(args.seed.read_text(encoding="utf-8"))
                if not isinstance(seeded, list) or any(not isinstance(row, dict) for row in seeded):
                    raise ValueError("--seed must contain a JSON list of normalized article dictionaries")
                for row in seeded:
                    if collector.complete:
                        break
                    collector.add_article(row)
            while not collector.complete:
                try:
                    collect_once(collector, scheduler, candidate_limit=args.candidate_limit)
                except DatasetPersistenceError:
                    raise
                except Exception as exc:
                    print(f"Collection error (progress retained): {type(exc).__name__}: {exc}")
                    if args.once:
                        parser.exit(1)
                if args.once or collector.complete:
                    break
                print(f"Waiting {args.poll_seconds:g}s for RSS updates; Ctrl+C stops safely.")
                time.sleep(args.poll_seconds)
            if collector.complete:
                print(f"COMPLETE: frozen {args.target}-article dataset: {collector.output_dir / 'qualified_news.json'}")
            else:
                print(f"Not complete: {len(collector.qualified)}/{args.target} qualified. Run again to resume.")
    except KeyboardInterrupt:
        print("\nStopped. Saved progress is retained; rerun with the same options to resume.")
    except Exception as exc:
        parser.exit(1, f"Dataset collection stopped: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    main()

"""Local, dependency-free preparation of a fixed news experiment dataset.

This module never fetches articles, loads a model, or accesses a database. The
caller supplies the production asset filter, embedding function, novelty
threshold, and (optionally) the scheduler's normalized article-key function.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


_REJECTION_COUNTS = (
    "rejected_invalid",
    "rejected_no_full_body",
    "rejected_asset_filter",
    "rejected_duplicate",
    "rejected_redundant",
    "embedding_errors",
)


class DatasetShortfallError(RuntimeError):
    """The supplied local source cannot furnish the requested fixed dataset."""

    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        counts = ", ".join(f"{name}={report[name]}" for name in _REJECTION_COUNTS)
        super().__init__(
            f"Only {report['accepted']} of {report['target_count']} required news "
            f"articles qualified after scanning {report['scanned_articles']} of "
            f"{report['input_articles']} supplied articles ({counts}). The source "
            "feed is finite, and missing/failed full-body scraping, the asset "
            "filter, duplicate articles, semantic redundancy, and embedding "
            "failures can reduce the usable set. No additional fetches, archive "
            "articles, duplicate padding, or synthetic data were used. Prepare "
            "a sufficient valid source dataset before resetting the database."
        )


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        allow_nan=False,
    )


def compute_dataset_hash(articles: list[dict[str, Any]]) -> str:
    """Hash the complete ordered dataset, ignoring JSON object-key ordering.

    Article order and every payload value remain significant. Non-JSON values
    and non-finite numbers raise instead of producing a misleading identity.
    """
    return hashlib.sha256(_canonical_json(articles).encode("utf-8")).hexdigest()


def atomic_write_json(path: Path, payload: Any, *, indent: int | None = None) -> None:
    """Write a complete UTF-8 JSON document, then atomically replace ``path``.

    Serialization happens before touching the destination. The temporary file
    is on the same filesystem, flushed and synced, and removed on failure.
    """
    # On-disk readability is independent of the canonical representation used
    # for dataset hashes. Keep existing callers compact unless they opt in.
    serialized = (
        _canonical_json(payload) if indent is None else json.dumps(
            payload, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=indent,
        )
    ) + "\n"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _default_keys(article: dict[str, Any]) -> set[str]:
    """Use raw identities; pass scheduler.article_keys for URL normalization."""
    keys = {f"url:{article['url'].strip()}"}
    guid = str(article.get("guid") or "").strip()
    if guid:
        keys.add(f"guid:{guid}")
    return keys


def _valid_http_url(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    normalized = value.strip()
    if any(character.isspace() for character in normalized):
        return False
    try:
        parts = urlsplit(normalized)
        # Accessing port also rejects invalid/out-of-range port specifications.
        _ = parts.port
        return parts.scheme.lower() in {"http", "https"} and bool(parts.hostname)
    except ValueError:
        return False


def _unit_vector(raw_vector: Any) -> tuple[float, ...]:
    if isinstance(raw_vector, (str, bytes, dict)):
        raise ValueError("embedding must be a one-dimensional numeric vector")
    try:
        vector = []
        for component in raw_vector:
            if isinstance(component, (str, bytes, bool)):
                raise ValueError("embedding components must be finite numbers")
            value = float(component)
            if not math.isfinite(value):
                raise ValueError("embedding contains a non-finite number")
            vector.append(value)
    except (TypeError, OverflowError) as exc:
        raise ValueError("embedding must be a one-dimensional finite numeric vector") from exc
    if not vector:
        raise ValueError("embedding is empty")
    scale = max(abs(value) for value in vector)
    if scale == 0:
        raise ValueError("embedding has zero norm")
    # Scaling avoids overflow/underflow for otherwise valid finite vectors.
    scaled = [value / scale for value in vector]
    norm = math.sqrt(math.fsum(value * value for value in scaled))
    return tuple(value / norm for value in scaled)


def _cosine_distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    cosine = math.fsum(a * b for a, b in zip(left, right))
    # Round-off can put a normalized dot product a few ulps outside [-1, 1].
    return 1.0 - max(-1.0, min(1.0, cosine))


def prepare_fixed_batch(
    articles: list[dict[str, Any]], *, target_count: int,
    asset_filter: Callable[[dict[str, Any]], Any],
    encode_text: Callable[[str], Iterable[float]], distance_threshold: float,
    key_function: Callable[[dict[str, Any]], Iterable[str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select the first ``target_count`` eligible, locally unique articles.

    Full bodies are mandatory; RSS/description fallbacks are never substituted.
    Identity keys and semantic comparisons use previously accepted articles.
    Cosine distance strictly below the caller's threshold means redundant, as
    in production novelty detection. Selection completes before any caller can
    reset a database; a shortfall raises with an inspectable ``.report``.

    Report rejection counters are mutually exclusive and, with ``accepted``,
    sum to ``scanned_articles``. Unscanned input after reaching the target is
    recorded as ``remaining_articles``. Rejection reasons use 1-based indexes.
    Input articles are not mutated; selected copies receive a deterministic
    ``experiment_article_id`` based on their exact title, URL, and full body.
    """
    if not isinstance(articles, list):
        raise TypeError("articles must be a list")
    if isinstance(target_count, bool) or not isinstance(target_count, int) or target_count <= 0:
        raise ValueError("target_count must be a positive integer")
    if isinstance(distance_threshold, bool):
        raise ValueError("distance_threshold must be a finite cosine distance in [0, 2]")
    try:
        threshold = float(distance_threshold)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("distance_threshold must be a finite cosine distance in [0, 2]") from exc
    if not math.isfinite(threshold) or not 0 <= threshold <= 2:
        raise ValueError("distance_threshold must be a finite cosine distance in [0, 2]")
    if not callable(asset_filter) or not callable(encode_text):
        raise TypeError("asset_filter and encode_text must be callable")
    if key_function is not None and not callable(key_function):
        raise TypeError("key_function must be callable or None")
    get_keys = key_function if key_function is not None else _default_keys

    report: dict[str, Any] = {
        "input_articles": len(articles), "scanned_articles": 0,
        "remaining_articles": len(articles), "target_count": target_count,
        "accepted": 0, **dict.fromkeys(_REJECTION_COUNTS, 0), "reasons": [],
    }
    selected: list[dict[str, Any]] = []
    accepted_keys: set[str] = set()
    accepted_vectors: list[tuple[float, ...]] = []
    vector_dimension: int | None = None

    def reject(index: int, article: Any, category: str, reason: str) -> None:
        report[category] += 1
        title = article.get("title", "") if isinstance(article, dict) else ""
        report["reasons"].append({
            "article_index": index, "category": category,
            "reason": reason[:300], "title": str(title)[:160],
        })

    for index, article in enumerate(articles, 1):
        report["scanned_articles"] = index
        report["remaining_articles"] = len(articles) - index
        if not isinstance(article, dict):
            reject(index, article, "rejected_invalid", "article is not a dictionary")
            continue
        title = article.get("title")
        if not isinstance(title, str) or not title.strip():
            reject(index, article, "rejected_invalid", "title must be a nonempty string")
            continue
        if not _valid_http_url(article.get("url")):
            reject(index, article, "rejected_invalid", "url must be a nonempty valid HTTP(S) URL")
            continue
        body = article.get("full_body")
        if not isinstance(body, str) or not body.strip():
            detail = article.get("scrape_error") or "no main article text was supplied"
            reject(index, article, "rejected_no_full_body",
                   f"full_body is missing or empty; RSS fallback is disabled; {detail}")
            continue
        try:
            passes_filter = bool(asset_filter(article))
        except Exception as exc:
            reject(index, article, "rejected_invalid", f"asset filter failed: {type(exc).__name__}: {exc}")
            continue
        if not passes_filter:
            reject(index, article, "rejected_asset_filter", "article did not pass the supplied asset filter")
            continue
        try:
            raw_keys = get_keys(article)
            if isinstance(raw_keys, (str, bytes)):
                raise ValueError("article keys must be an iterable of nonempty strings")
            keys = set(raw_keys)
            if not keys or any(not isinstance(key, str) or not key.strip() for key in keys):
                raise ValueError("article keys must be nonempty strings")
        except Exception as exc:
            reject(index, article, "rejected_invalid", f"article keys failed: {type(exc).__name__}: {exc}")
            continue
        if keys & accepted_keys:
            reject(index, article, "rejected_duplicate", "URL or GUID matches a previously accepted article")
            continue
        try:
            vector = _unit_vector(encode_text(f"{title}. {body}"))
            if vector_dimension is None:
                vector_dimension = len(vector)
            elif len(vector) != vector_dimension:
                raise ValueError(f"embedding dimension {len(vector)} differs from {vector_dimension}")
        except Exception as exc:
            reject(index, article, "embedding_errors", f"{type(exc).__name__}: {exc}")
            continue
        if any(_cosine_distance(vector, previous) < threshold for previous in accepted_vectors):
            reject(index, article, "rejected_redundant", "cosine distance is below the supplied novelty threshold")
            continue

        selected_article = dict(article)
        identity = {"title": title, "url": article["url"], "full_body": body}
        selected_article["experiment_article_id"] = hashlib.sha256(
            _canonical_json(identity).encode("utf-8")
        ).hexdigest()
        selected.append(selected_article)
        accepted_keys.update(keys)
        accepted_vectors.append(vector)
        report["accepted"] += 1
        if len(selected) == target_count:
            return selected, report

    raise DatasetShortfallError(report)

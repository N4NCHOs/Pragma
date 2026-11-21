#!/usr/bin/env python3
"""Score frozen RS summaries and AI references with an auditable English FKGL.

Run with the isolated readability runtime rather than the model's environment.
No text is corrected or normalized before scoring. The reported counts are the
same textstat counts used by its unrounded Flesch--Kincaid formula.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import inspect
import json
import math
import os
from pathlib import Path
import platform
import re
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parent
DEFAULT_NLTK_DATA = ROOT / "output/flan_evaluation/readability_runtime/nltk_data"
EXPECTED_TEXTSTAT_VERSION = "0.7.10"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


@contextmanager
def local_resources_only(nltk: Any) -> Iterator[None]:
    """Prevent textstat's resource installer from attempting a network request.

    textstat 0.7.10 unconditionally calls nltk.download('cmudict') on its first
    English syllable calculation. Validate and load the local official corpus
    first, then replace only that installer during scoring. No metric, corpus,
    pronunciation, tokenizer, or syllable fallback is changed.
    """
    nltk.corpus.cmudict.dict()
    original_download = nltk.download

    def require_installed_resource(package: str, *args: Any, **kwargs: Any) -> bool:
        if package != "cmudict":
            raise RuntimeError(f"Unexpected resource request: {package}")
        nltk.data.find("corpora/cmudict")
        return True

    nltk.download = require_installed_resource
    try:
        yield
    finally:
        nltk.download = original_download


def score_text(text: str, textstat: Any) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Every scored summary must contain nonempty text")
    words = int(textstat.lexicon_count(text, removepunct=True))
    sentences = int(textstat.sentence_count(text))
    syllables = int(textstat.syllable_count(text))
    if words == 0 or sentences == 0 or syllables == 0:
        raise ValueError("A nonempty summary produced an empty FKGL denominator")
    formula = 0.39 * (words / sentences) + 11.8 * (syllables / words) - 15.59
    library_score = float(textstat.flesch_kincaid_grade(text))
    if not math.isclose(formula, library_score, rel_tol=0.0, abs_tol=1e-12):
        raise AssertionError((formula, library_score, words, sentences, syllables))
    return {
        "text_sha256": text_hash(text),
        "fkgl": library_score,
        "word_count": words,
        "sentence_count": sentences,
        "syllable_count": syllables,
        "words_per_sentence": words / sentences,
        "syllables_per_word": syllables / words,
        "whitespace_word_count": len(text.split()),
        "two_to_three_sentences": 2 <= sentences <= 3,
        "heuristic_starts_with_output_label": bool(
            re.search(r"^\s*(?:output|summary)\s*:", text, re.IGNORECASE)
        ),
        "heuristic_contains_ellipsis": bool(re.search(r"\.{3}|…", text)),
        "heuristic_ends_with_ellipsis": bool(
            re.search(r"(?:\.{3}|…)[\]\)'\"’”\s]*$", text)
        ),
        "heuristic_missing_terminal_punctuation": not bool(
            re.search(r"[.!?…][\]\)'\"’”\s]*$", text)
        ),
        "formula_absolute_error": abs(formula - library_score),
    }


def implementation_metadata(textstat: Any, nltk_data: Path) -> tuple[dict[str, Any], str]:
    from textstat.backend import counts, metrics
    from textstat.backend.selections import list_words
    from textstat.backend.transformations import remove_punctuation
    from textstat.backend.utils import get_cmudict
    import pyphen

    functions = [
        metrics.flesch_kincaid_grade, counts.count_words,
        counts.count_sentences, counts.count_syllables, list_words,
        remove_punctuation, get_cmudict,
    ]
    sources = "\n\n".join(
        f"# {function.__module__}.{function.__name__}\n{inspect.getsource(function)}"
        for function in functions
    )
    source_files = sorted({Path(inspect.getsourcefile(inspect.unwrap(f))).resolve() for f in functions})
    dictionary_paths = [
        nltk_data / "corpora/cmudict.zip",
        nltk_data / "corpora/cmudict/cmudict",
        Path(pyphen.LANGUAGES["en_US"]),
    ]
    return {
        "package_versions": {
            name: importlib.metadata.version(name)
            for name in ("textstat", "nltk", "pyphen", "regex")
        },
        "language": "en_US",
        "rounding_points": None,
        "formula": "0.39 * (words / sentences) + 11.8 * (syllables / words) - 15.59",
        "lower_fkgl_indicates_lower_estimated_school_grade": True,
        "text_preprocessing": "Raw strings passed unchanged to textstat; no repairs, removals, or normalization.",
        "word_count_behavior": "textstat default punctuation removal, whitespace split; contractions and hyphenated expressions each stay one word (hyphens removed internally); numerals retained.",
        "sentence_count_behavior": "Regex \\b[^.!?]+[.!?]*; ignores segments containing at most two words; nonempty text has a minimum of one sentence. Abbreviations and decimals can affect boundaries.",
        "syllable_count_behavior": "Lowercase textstat words; first CMUdict pronunciation, count phonemes ending in a digit; Pyphen en_US hyphenation positions + 1 for missing words.",
        "resource_download_policy": "Offline scoring: required local CMUdict is preloaded, then only nltk.download is temporarily replaced with a local-resource check. textstat metric functions and dictionaries are unmodified.",
        "dictionary_files": {str(p): sha256_file(p) for p in dictionary_paths},
        "implementation_files": {str(p): sha256_file(p) for p in source_files},
        "official_library_source": "https://github.com/textstat/textstat",
        "pinned_distribution": "https://pypi.org/project/textstat/0.7.10/",
        "cmudict_download_source": "https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/cmudict.zip",
    }, sources


def run(inputs: Path, output_dir: Path, nltk_data: Path) -> dict[str, Any]:
    os.environ["NLTK_DATA"] = str(nltk_data)
    import nltk
    import textstat

    if importlib.metadata.version("textstat") != EXPECTED_TEXTSTAT_VERSION:
        raise RuntimeError(f"This experiment pins textstat=={EXPECTED_TEXTSTAT_VERSION}")
    nltk.data.path.insert(0, str(nltk_data))
    textstat.set_lang("en_US")
    textstat.set_rounding_points(None)
    rows = json.loads(inputs.read_text())
    if not isinstance(rows, list) or not rows:
        raise ValueError("Expected a nonempty frozen JSON record list")
    seen_pairs: set[tuple[str, str]] = set()
    references: dict[tuple[str, str], str] = {}
    for row in rows:
        pair = (row["id"], row["prompt_condition"])
        if pair in seen_pairs:
            raise ValueError(f"Duplicate candidate record: {pair}")
        seen_pairs.add(pair)
        for model in ("gpt", "gemini"):
            key = (row["id"], model)
            text = row[f"{model}_reference_summary"]
            if key in references and references[key] != text:
                raise ValueError(f"Reference changed between prompt conditions: {key}")
            references[key] = text

    cache: dict[str, dict[str, Any]] = {}

    def cached_score(text: str) -> dict[str, Any]:
        if text not in cache:
            cache[text] = score_text(text, textstat)
        return dict(cache[text])

    with local_resources_only(nltk):
        candidates = [
            {"id": row["id"], "prompt_condition": row["prompt_condition"],
             "source_index": row.get("source_index"), **cached_score(row["summary"])}
            for row in rows
        ]
        reference_scores = [
            {"id": article_id, "reference_model": model, **cached_score(text)}
            for (article_id, model), text in references.items()
        ]

    config, sources = implementation_metadata(textstat, nltk_data)
    report = {
        "status": "complete",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_file": str(inputs), "input_sha256": sha256_file(inputs),
        "script": str(Path(__file__).resolve()),
        "script_sha256": sha256_file(Path(__file__)),
        "python_version": platform.python_version(),
        "candidate_records": len(candidates),
        "reference_records": len(reference_scores),
        "candidate_unique_article_summary_pairs": len({(r["id"], r["summary"]) for r in rows}),
        "candidate_unique_texts": len({r["summary"] for r in rows}),
        "all_unique_scored_texts": len(cache),
        "candidate_records_by_condition": dict(Counter(r["prompt_condition"] for r in rows)),
        "maximum_formula_absolute_error": max(s["formula_absolute_error"] for s in cache.values()),
        "configuration": config,
        "interpretation_limits": [
            "FKGL estimates surface difficulty from sentence length and syllables, not factuality, informativeness, coherence, or actual beginner understanding.",
            "Very short summaries and unfamiliar cryptocurrency names, abbreviations, and numbers can make grade estimates unstable.",
            "The 2-to-3 sentence flag uses textstat's heuristic sentence counter and is not a grammatical compliance judgment.",
            "Ellipsis, output-label, and terminal-punctuation flags are descriptive string checks, not confirmed errors or proof of token-limit truncation.",
            "GPT/Gemini reference FKGL values are separate descriptive baselines, not validated human readability targets.",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "readability_scores.json", candidates)
    write_json(output_dir / "reference_readability.json", reference_scores)
    (output_dir / "readability_implementation_sources.txt").write_text(sources + "\n")
    write_json(output_dir / "readability_report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--nltk-data", type=Path, default=DEFAULT_NLTK_DATA)
    args = parser.parse_args()
    report = run(args.inputs.resolve(), args.output_dir.resolve(), args.nltk_data.resolve())
    print(json.dumps({key: report[key] for key in (
        "status", "candidate_records", "reference_records",
        "candidate_unique_article_summary_pairs", "all_unique_scored_texts",
        "maximum_formula_absolute_error",
    )}, indent=2))


if __name__ == "__main__":
    main()

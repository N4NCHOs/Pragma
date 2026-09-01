"""Run the DeBERTa-v3 classifier against one article and basic input edge cases."""

from __future__ import annotations

import argparse
from pathlib import Path
from time import perf_counter

from ai_models.deberta_classifier import (
    DEFAULT_MIN_FLOOR,
    DEFAULT_MODEL_NAME,
    DEFAULT_RELATIVE_MARGIN,
    DebertaClassificationResult,
    DebertaClassifierService,
    DeviceName,
)


DEFAULT_ARTICLE = """The SEC filed an enforcement action against a major exchange on
Monday, alleging it offered unregistered securities to retail customers. The exchange's
token dropped 12% within hours of the announcement. Institutional desks reported thin
liquidity as several market makers paused trading pending regulatory clarity."""

SHORT_ARTICLE = "Bitcoin rose 2%."

LONG_PARAGRAPH = """A mid-sized Layer 2 network announced a protocol upgrade intended to
reduce gas fees for developers building on top of it. The team said the change followed
six months of testnet audits and does not introduce a new token or change existing
supply. The announcement did not include a price forecast or investment guidance.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run standalone DeBERTa-v3 classification and print inference metrics."
    )
    article_source = parser.add_mutually_exclusive_group()
    article_source.add_argument("--text", help="Article text supplied directly.")
    article_source.add_argument(
        "--file", type=Path, help="UTF-8 text file containing one article."
    )
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument(
        "--min-floor", type=float, default=DEFAULT_MIN_FLOOR,
        help="Absolute floor: below this top score, target_investor is empty.",
    )
    parser.add_argument(
        "--relative-margin", type=float, default=DEFAULT_RELATIVE_MARGIN,
        help="Relative margin below the top score for target_investor inclusion.",
    )
    parser.add_argument(
        "--device", choices=("auto", "cpu", "cuda", "mps"), default="auto"
    )
    parser.add_argument(
        "--skip-edge-cases",
        action="store_true",
        help="Run only the supplied/default article.",
    )
    return parser.parse_args()


def load_article(args: argparse.Namespace) -> str:
    if args.text is not None:
        return args.text
    if args.file is not None:
        try:
            return args.file.read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"Could not read article file '{args.file}': {exc}") from exc
    return DEFAULT_ARTICLE


def display_article(text: str, limit: int = 1_200) -> str:
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    omitted = len(cleaned) - limit
    return f"{cleaned[:limit]}\n... [display shortened by {omitted} characters]"


def print_result(label: str, article_text: str, result: DebertaClassificationResult) -> None:
    print(f"\n{'=' * 72}")
    print(label)
    print(f"{'=' * 72}")
    print("\nOriginal article text:")
    print(display_article(article_text))
    print("\nClassification:")
    print(f"  category:         {result.category}  (confidence {result.category_confidence})")
    print(f"  impact:           {result.impact}  (confidence {result.impact_confidence})")
    print(f"  sentiment:        {result.sentiment}  (confidence {result.sentiment_confidence})")
    print(f"  target_investor:  {result.target_investor}")
    print(f"  target_investor_scores: {result.target_investor_scores}")
    print("\nMetrics:")
    print(f"  Inference time:   {result.inference_seconds:.3f} seconds")


def run_classification_case(
    service: DebertaClassifierService, label: str, article_text: str
) -> DebertaClassificationResult:
    result = service.classify(article_text)
    print_result(label, article_text, result)
    return result


def run_empty_text_case(service: DebertaClassifierService) -> None:
    print(f"\n{'=' * 72}")
    print("EDGE CASE: EMPTY TEXT")
    print(f"{'=' * 72}")
    try:
        service.classify("   \n\t")
    except ValueError as exc:
        print(f"Handled as expected: {exc}")
    else:
        raise AssertionError("Empty article text should raise ValueError")


def main() -> None:
    args = parse_args()
    article_text = load_article(args)
    service = DebertaClassifierService(
        model_name=args.model_name,
        device=args.device,
        min_floor=args.min_floor,
        relative_margin=args.relative_margin,
    )

    print(f"Checkpoint: {service.model_name}")
    print(f"Resolved device: {service.device}")
    print(f"target_investor min_floor: {service.min_floor}")
    print(f"target_investor relative_margin: {service.relative_margin}")
    print(
        "Classification: zero-shot NLI (single-label for category/impact/sentiment, "
        "independent multi-label scoring for target_investor)"
    )

    if not args.skip_edge_cases:
        run_empty_text_case(service)

    load_started_at = perf_counter()
    service.load()
    print(f"Model load time: {perf_counter() - load_started_at:.3f} seconds")

    run_classification_case(service, "PRIMARY ARTICLE", article_text)

    if not args.skip_edge_cases:
        run_classification_case(service, "EDGE CASE: EXTREMELY SHORT TEXT", SHORT_ARTICLE)
        very_long_article = "\n".join(LONG_PARAGRAPH for _ in range(80))
        run_classification_case(service, "EDGE CASE: VERY LONG TEXT", very_long_article)


if __name__ == "__main__":
    main()

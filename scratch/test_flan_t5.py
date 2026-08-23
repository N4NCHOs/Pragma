"""Run FLAN-T5 against one article and basic input edge cases."""

from __future__ import annotations

import argparse
from pathlib import Path
from time import perf_counter

from ai_models.flan_t5 import (
    DEFAULT_MAX_INPUT_TOKENS,
    DEFAULT_MODEL_NAME,
    DeviceName,
    FlanSummaryResult,
    FlanT5Service,
)


DEFAULT_ARTICLE = """BlackRock's iShares Bitcoin Trust recorded $250 million in
net inflows on Monday. The fund's holdings increased as bitcoin traded near $68,000,
according to the figures stated in the report. The article did not provide a forecast
for bitcoin's future price."""

SHORT_ARTICLE = "Bitcoin rose 2%."

LONG_PARAGRAPH = """Bitcoin payment company ExamplePay said it processed 1.2 million
transactions during the quarter, a 15% increase from the previous quarter. The company
said the expansion followed the addition of 300 merchants in Indonesia and Singapore.
ExamplePay did not announce a token, predict bitcoin's price, or provide financial advice.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a standalone FLAN-T5 summary and print inference metrics."
    )
    article_source = parser.add_mutually_exclusive_group()
    article_source.add_argument("--text", help="Article text supplied directly.")
    article_source.add_argument(
        "--file", type=Path, help="UTF-8 text file containing one article."
    )
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument(
        "--max-input-tokens", type=int, default=DEFAULT_MAX_INPUT_TOKENS
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


def print_result(label: str, article_text: str, result: FlanSummaryResult) -> None:
    print(f"\n{'=' * 72}")
    print(label)
    print(f"{'=' * 72}")
    print("\nOriginal article text:")
    print(display_article(article_text))
    print("\nGenerated summary:")
    print(result.summary)
    print("\nMetrics:")
    print(f"  Inference time:       {result.inference_seconds:.3f} seconds")
    print(f"  Input tokens used:    {result.input_token_count}")
    print(f"  Input tokens before truncation: {result.original_input_token_count}")
    print(f"  Output tokens:        {result.output_token_count}")
    print(f"  Input was truncated:  {result.input_was_truncated}")


def run_summary_case(
    service: FlanT5Service, label: str, article_text: str
) -> FlanSummaryResult:
    result = service.summarize_with_metrics(article_text)
    print_result(label, article_text, result)
    return result


def run_empty_text_case(service: FlanT5Service) -> None:
    print(f"\n{'=' * 72}")
    print("EDGE CASE: EMPTY TEXT")
    print(f"{'=' * 72}")
    try:
        service.summarize_with_metrics("   \n\t")
    except ValueError as exc:
        print(f"Handled as expected: {exc}")
    else:
        raise AssertionError("Empty article text should raise ValueError")


def main() -> None:
    args = parse_args()
    article_text = load_article(args)
    service = FlanT5Service(
        model_name=args.model_name,
        max_input_tokens=args.max_input_tokens,
        device=args.device,
    )

    print(f"Checkpoint: {service.model_name}")
    print(f"Resolved device: {service.device}")
    print("Generation: deterministic beam search (4 beams, max 64 new tokens)")

    if not args.skip_edge_cases:
        run_empty_text_case(service)

    load_started_at = perf_counter()
    service.load()
    print(f"Model load time: {perf_counter() - load_started_at:.3f} seconds")

    run_summary_case(service, "PRIMARY ARTICLE", article_text)

    if not args.skip_edge_cases:
        run_summary_case(service, "EDGE CASE: EXTREMELY SHORT TEXT", SHORT_ARTICLE)
        very_long_article = "\n".join(LONG_PARAGRAPH for _ in range(80))
        long_result = run_summary_case(
            service, "EDGE CASE: VERY LONG TEXT", very_long_article
        )
        if not long_result.input_was_truncated:
            raise AssertionError("The very-long-text case should exercise truncation")


if __name__ == "__main__":
    main()

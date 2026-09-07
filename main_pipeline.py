import argparse
import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from time import perf_counter

from rss_scrape_scheduler import run_scheduler
from database import SessionLocal
from ai_models.filters import is_top_10_news
from ai_models.novelty_detection import process_incoming_news
from ai_models.crypto_ner import extract_and_link_entities
from ai_models.flan_t5 import flan_service, FlanSummaryResult
from ai_models.deberta_classifier import deberta_service, DebertaClassificationResult

logger = logging.getLogger("main_pipeline")

VALID_MODES = ("sequential", "concurrent")


@dataclass
class InferenceOutcome:
    """Results of the per-article AI inference stage.

    Any model that failed leaves its result field as None and records the
    exception in `errors` (keyed by "flan_t5" / "deberta"), so the caller can
    still persist whatever succeeded.
    """

    entities: list
    summary_result: FlanSummaryResult | None = None
    classification_result: DebertaClassificationResult | None = None
    errors: dict[str, BaseException] = field(default_factory=dict)
    elapsed_seconds: float = 0.0


async def run_ai_inference(full_text: str, *, concurrent: bool) -> InferenceOutcome:
    """Run NER, FLAN-T5 summarization, and DeBERTa classification for one article.

    NER stays synchronous (regex/dictionary matching, negligible cost). The two
    transformers-based calls are blocking and synchronous, so in concurrent mode
    each is offloaded to its own thread via asyncio.to_thread and the pair is run
    together with asyncio.gather. `return_exceptions=True` guarantees a failure in
    one model's thread neither cancels nor hides the other's result.
    """

    started_at = perf_counter()

    entities: list = []
    errors: dict[str, BaseException] = {}
    try:
        entities = extract_and_link_entities(full_text)
    except Exception as exc:  # noqa: BLE001 - one article's NER failure must not abort the batch
        errors["ner"] = exc

    summary_result: FlanSummaryResult | None = None
    classification_result: DebertaClassificationResult | None = None

    if concurrent:
        summary_raw, classification_raw = await asyncio.gather(
            asyncio.to_thread(flan_service.summarize_with_metrics, full_text),
            asyncio.to_thread(deberta_service.classify, full_text),
            return_exceptions=True,
        )
        if isinstance(summary_raw, BaseException):
            errors["flan_t5"] = summary_raw
        else:
            summary_result = summary_raw
        if isinstance(classification_raw, BaseException):
            errors["deberta"] = classification_raw
        else:
            classification_result = classification_raw
    else:
        try:
            summary_result = flan_service.summarize_with_metrics(full_text)
        except Exception as exc:  # noqa: BLE001 - recorded, not raised, so DeBERTa still runs
            errors["flan_t5"] = exc
        try:
            classification_result = deberta_service.classify(full_text)
        except Exception as exc:  # noqa: BLE001 - recorded, not raised
            errors["deberta"] = exc

    return InferenceOutcome(
        entities=entities,
        summary_result=summary_result,
        classification_result=classification_result,
        errors=errors,
        elapsed_seconds=perf_counter() - started_at,
    )


async def run_pipeline(mode: str) -> None:
    concurrent = mode == "concurrent"

    print("\n==========================================")
    print("Step 1: Running Scraper...")
    print("==========================================\n")
    scrape_stats = run_scheduler()

    print("\n[Scraper Summary]")
    print(f" -> RSS Items Fetched:  {scrape_stats.get('rss_items')}")
    print(f" -> New Items Found:    {scrape_stats.get('new_items')}")
    print(f" -> Successfully Scraped: {scrape_stats.get('scrape_success')}")
    print(f" -> Failed to Scrape:   {scrape_stats.get('scrape_failed')}\n")

    # 2. Open the JSON created by the RSS scraper
    try:
        with open("output/scraped_news.json", "r", encoding="utf-8") as f:
            news_batch = json.load(f)
    except FileNotFoundError:
        print("scraped_news.json not found! Scraper may have failed.")
        return

    db = SessionLocal()

    inference_times: list[float] = []

    try:
        print("\n==========================================")
        print("Step 2: Processing Pipeline...")
        print(f"Inference mode: {mode.upper()}")
        print("==========================================")

        total = len(news_batch)
        print(f"Found {total} articles to process.\n")

        # 3. Process each article
        for i, article in enumerate(news_batch, 1):
            print(f"[{i}/{total}] {article.get('title')}")

            try:
                # If the scraper failed (e.g. Rate Limit), it will naturally fall back
                # to the RSS summary below.

                # 4. Use the imported filter function
                if not is_top_10_news(article):
                    print(" -> [DROPPED] Not a Top 10 asset\n")
                    continue

                # 5. AI Novelty Detection
                uncommitted_article = process_incoming_news(article, db)

                # 6. AI Inference (Only for Unique Articles)
                if uncommitted_article.is_redundant == False:
                    title = article.get("title", "")
                    body = article.get("full_body") or article.get("rss_summary") or article.get("description") or ""
                    full_text = f"{title}. {body}"

                    outcome = await run_ai_inference(full_text, concurrent=concurrent)
                    inference_times.append(outcome.elapsed_seconds)

                    # Log and surface every model failure; keep going with whatever
                    # succeeded so the article is never silently left partial.
                    for model_name, exc in outcome.errors.items():
                        logger.error(
                            "AI inference failed [%d/%d] model=%s title=%s",
                            i, total, model_name, article.get("title"),
                            exc_info=exc,
                        )
                        print(f" -> [AI-ERROR] {model_name}: {exc}")

                    # Aggregate whatever AI results we have into memory. Failed
                    # models leave their columns untouched (null / default).
                    uncommitted_article.extracted_assets = outcome.entities

                    if outcome.summary_result is not None:
                        uncommitted_article.summary = outcome.summary_result.summary

                    if outcome.classification_result is not None:
                        classification_result = outcome.classification_result
                        uncommitted_article.category = classification_result.category
                        uncommitted_article.impact = classification_result.impact
                        uncommitted_article.sentiment = classification_result.sentiment
                        uncommitted_article.target_investor = classification_result.target_investor

                    if outcome.entities:
                        found_texts = [e['matched_text'] for e in outcome.entities]
                        print(f" -> Found Entities: {found_texts}\n")
                    else:
                        print(f" -> Found Entities: None")

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
                        print(
                            " -> DeBERTa Metrics: "
                            f"{classification_result.inference_seconds:.3f}s\n"
                        )

                    print(
                        f" -> [TIMING] inference: {outcome.elapsed_seconds:.3f}s "
                        f"(mode={mode})"
                    )

                # 7. Final Save to Database
                db.add(uncommitted_article)
                db.commit()
                db.refresh(uncommitted_article)

                if uncommitted_article.is_redundant == True:
                    print(f" -> [PROCESSED] Saved to DB with ID: {uncommitted_article.id} (Redundant)\n")
                else:
                    print(f" -> [PROCESSED] Saved to DB with ID: {uncommitted_article.id} (Unique)\n")
            except Exception:  # noqa: BLE001 - isolate per-article failures from the rest of the batch
                db.rollback()
                logger.exception(
                    "Article failed entirely [%d/%d] title=%s",
                    i, total, article.get("title"),
                )
                print(f" -> [ERROR] Skipped article {i}: see log for traceback\n")
                continue

        if inference_times:
            total_seconds = sum(inference_times)
            count = len(inference_times)
            print("\n==========================================")
            print(
                f"[INFERENCE TIMING SUMMARY] mode={mode} | articles={count} | "
                f"total={total_seconds:.3f}s | mean={total_seconds / count:.3f}s | "
                f"min={min(inference_times):.3f}s | max={max(inference_times):.3f}s"
            )
            print("==========================================\n")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the crypto-news processing pipeline.")
    parser.add_argument(
        "--mode",
        choices=VALID_MODES,
        default=None,
        help=(
            "AI inference execution mode. Overrides the PIPELINE_INFERENCE_MODE "
            "environment variable. Defaults to 'sequential'."
        ),
    )
    args = parser.parse_args()

    mode = args.mode or os.getenv("PIPELINE_INFERENCE_MODE", "sequential")
    if mode not in VALID_MODES:
        parser.error(
            f"invalid inference mode {mode!r} (from PIPELINE_INFERENCE_MODE); "
            f"expected one of {', '.join(VALID_MODES)}"
        )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    asyncio.run(run_pipeline(mode))


if __name__ == "__main__":
    main()

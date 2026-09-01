"""Standalone DeBERTa-v3 service for multi-task crypto-news classification.

Uses a zero-shot NLI checkpoint (entailment-based classification against
candidate label strings) rather than a task-specific fine-tuned head, since no
fine-tuned checkpoint exists yet. Swap DEFAULT_MODEL_NAME for a fine-tuned
classifier later without changing the calling convention.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import perf_counter
from typing import Any, Literal

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline


DEFAULT_MODEL_NAME = "MoritzLaurer/deberta-v3-base-zeroshot-v2.0"
DEFAULT_MIN_FLOOR = 0.15
DEFAULT_RELATIVE_MARGIN = 0.15

CATEGORY_LABELS = ("Regulation", "Market Movement", "Technology", "Adoption", "Security")
# Ordinal in principle, but scored as single-label classification over an
# ordered candidate set: zero-shot NLI has no native ordinal head.
IMPACT_LABELS = ("Low", "Medium", "High")
TARGET_INVESTOR_LABELS = ("day traders", "long-term holders", "whales")
SENTIMENT_LABELS = ("Bullish", "Bearish", "Neutral")

CATEGORY_HYPOTHESIS_TEMPLATE = "This news article is primarily about {}."
IMPACT_HYPOTHESIS_TEMPLATE = "The market impact of this news is {}."
TARGET_INVESTOR_HYPOTHESIS_TEMPLATE = "This news is most relevant to {}."
SENTIMENT_HYPOTHESIS_TEMPLATE = "This news reflects {} market sentiment."

DeviceName = Literal["auto", "cpu", "cuda", "mps"]


@dataclass(frozen=True, slots=True)
class DebertaClassificationResult:
    """Multi-task classification labels and measurements from one call."""

    category: str
    category_confidence: float
    impact: str
    impact_confidence: float
    target_investor: list[str]
    target_investor_scores: dict[str, float]
    sentiment: str
    sentiment_confidence: float
    inference_seconds: float


def select_target_investors(
    scores: dict[str, float],
    labels: tuple[str, ...],
    *,
    min_floor: float,
    relative_margin: float,
) -> list[str]:
    """Select target_investor labels using an absolute floor, then a relative margin.

    Two checks run in sequence, and both exist because a single flat threshold
    can't serve both purposes at once:

    1. Absolute floor (`min_floor`): if the best-scoring label doesn't even
       clear this bar, the classifier isn't confident about *any* candidate for
       this article, so the result is an empty list rather than a forced guess.
    2. Relative margin (`relative_margin`): once the floor is cleared, inclusion
       is judged relative to the top score (`cutoff = max_score * (1 -
       relative_margin)`) instead of a fixed number. This lets a genuinely
       multi-label article (e.g. scores of 0.90 and 0.83, both close to the
       top) keep every label near the top, while a clearly single-label
       article (e.g. 0.90 vs. 0.40) keeps only the winner — a flat threshold
       would either over-include the second case or under-include the first,
       depending on where it was set.
    """

    if not scores:
        return []
    max_score = max(scores.values())
    if max_score < min_floor:
        return []
    cutoff = max_score * (1 - relative_margin)
    return [label for label in labels if scores.get(label, 0.0) >= cutoff]


class DebertaClassifierService:
    """Load a DeBERTa-v3 zero-shot classifier once and reuse it for every task."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        *,
        device: DeviceName = "auto",
        min_floor: float = DEFAULT_MIN_FLOOR,
        relative_margin: float = DEFAULT_RELATIVE_MARGIN,
        category_labels: tuple[str, ...] = CATEGORY_LABELS,
        impact_labels: tuple[str, ...] = IMPACT_LABELS,
        target_investor_labels: tuple[str, ...] = TARGET_INVESTOR_LABELS,
        sentiment_labels: tuple[str, ...] = SENTIMENT_LABELS,
    ) -> None:
        if not model_name.strip():
            raise ValueError("model_name must not be empty")
        if not 0.0 <= min_floor < 1.0:
            raise ValueError("min_floor must be between 0 (inclusive) and 1 (exclusive)")
        if not 0.0 <= relative_margin < 1.0:
            raise ValueError("relative_margin must be between 0 (inclusive) and 1 (exclusive)")
        for name, labels in (
            ("category_labels", category_labels),
            ("impact_labels", impact_labels),
            ("target_investor_labels", target_investor_labels),
            ("sentiment_labels", sentiment_labels),
        ):
            if len(labels) < 2:
                raise ValueError(f"{name} must contain at least two labels")

        self.model_name = model_name
        self.min_floor = min_floor
        self.relative_margin = relative_margin
        self.category_labels = category_labels
        self.impact_labels = impact_labels
        self.target_investor_labels = target_investor_labels
        self.sentiment_labels = sentiment_labels
        self._requested_device = device
        self._device = self._resolve_device(device)
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self._pipeline: Any | None = None
        self._load_lock = Lock()

    @staticmethod
    def _resolve_device(requested: DeviceName) -> torch.device:
        if requested == "auto":
            if torch.cuda.is_available():
                return torch.device("cuda")
            if torch.backends.mps.is_available():
                return torch.device("mps")
            return torch.device("cpu")

        if requested == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but is not available")
        if requested == "mps" and not torch.backends.mps.is_available():
            raise RuntimeError("MPS was requested but is not available")
        return torch.device(requested)

    @property
    def device(self) -> str:
        """Return the resolved inference device."""

        return str(self._device)

    @property
    def is_loaded(self) -> bool:
        """Return whether the model, tokenizer, and pipeline are ready."""

        return (
            self._model is not None
            and self._tokenizer is not None
            and self._pipeline is not None
        )

    def load(self) -> None:
        """Load model resources once; subsequent calls are no-ops."""

        if self.is_loaded:
            return

        with self._load_lock:
            if self.is_loaded:
                return
            try:
                tokenizer = AutoTokenizer.from_pretrained(self.model_name)
                model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
                model.to(self._device)
                model.eval()
                classification_pipeline = pipeline(
                    "zero-shot-classification",
                    model=model,
                    tokenizer=tokenizer,
                    device=self._device,
                )
            except (OSError, RuntimeError, ValueError) as exc:
                raise RuntimeError(
                    f"Could not load DeBERTa-v3 checkpoint '{self.model_name}': {exc}"
                ) from exc

            self._tokenizer = tokenizer
            self._model = model
            self._pipeline = classification_pipeline

    def classify(self, article_text: str) -> DebertaClassificationResult:
        """Run all four classification tasks and return labels with confidences."""

        if not isinstance(article_text, str):
            raise TypeError("article_text must be a string")

        cleaned_text = article_text.strip()
        if not cleaned_text:
            raise ValueError("article_text must not be empty or whitespace-only")

        self.load()
        if self._pipeline is None:
            raise RuntimeError("DeBERTa-v3 resources were not loaded")

        try:
            started_at = perf_counter()
            category_result = self._pipeline(
                cleaned_text,
                candidate_labels=list(self.category_labels),
                hypothesis_template=CATEGORY_HYPOTHESIS_TEMPLATE,
                multi_label=False,
            )
            impact_result = self._pipeline(
                cleaned_text,
                candidate_labels=list(self.impact_labels),
                hypothesis_template=IMPACT_HYPOTHESIS_TEMPLATE,
                multi_label=False,
            )
            target_investor_result = self._pipeline(
                cleaned_text,
                candidate_labels=list(self.target_investor_labels),
                hypothesis_template=TARGET_INVESTOR_HYPOTHESIS_TEMPLATE,
                multi_label=True,
            )
            sentiment_result = self._pipeline(
                cleaned_text,
                candidate_labels=list(self.sentiment_labels),
                hypothesis_template=SENTIMENT_HYPOTHESIS_TEMPLATE,
                multi_label=False,
            )
            inference_seconds = perf_counter() - started_at
        except RuntimeError as exc:
            raise RuntimeError(f"DeBERTa-v3 classification inference failed: {exc}") from exc

        target_investor_scores = {
            label: round(float(score), 4)
            for label, score in zip(
                target_investor_result["labels"], target_investor_result["scores"]
            )
        }
        target_investor = select_target_investors(
            target_investor_scores,
            self.target_investor_labels,
            min_floor=self.min_floor,
            relative_margin=self.relative_margin,
        )

        return DebertaClassificationResult(
            category=category_result["labels"][0],
            category_confidence=round(float(category_result["scores"][0]), 4),
            impact=impact_result["labels"][0],
            impact_confidence=round(float(impact_result["scores"][0]), 4),
            target_investor=target_investor,
            target_investor_scores=target_investor_scores,
            sentiment=sentiment_result["labels"][0],
            sentiment_confidence=round(float(sentiment_result["scores"][0]), 4),
            inference_seconds=inference_seconds,
        )


# Shared lazy singleton: importing this module does not load model weights. The first
# valid classify call loads them once, and later calls reuse the same resources.
deberta_service = DebertaClassifierService()

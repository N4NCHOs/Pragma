"""Standalone FLAN-T5 service for objective crypto-news summarization."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import perf_counter
from typing import Any, Literal

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer


DEFAULT_MODEL_NAME = "google/flan-t5-base"
DEFAULT_MAX_INPUT_TOKENS = 512

SUMMARY_PROMPT = """Summarize the following cryptocurrency news for a beginner investor.

Explain the main event and relevant implication in 1-2 concise sentences.
Remain objective and factual.
Preserve important asset names, organizations, numbers, and events.
Do not give investment advice.
Do not predict future prices.
Do not add information that is not stated in the article.

Article:
{article_text}

Summary:"""

DeviceName = Literal["auto", "cpu", "cuda", "mps"]


@dataclass(frozen=True, slots=True)
class FlanSummaryResult:
    """Summary text and measurements from one generation call."""

    summary: str
    inference_seconds: float
    input_token_count: int
    original_input_token_count: int
    output_token_count: int
    input_was_truncated: bool


class FlanT5Service:
    """Load FLAN-T5 once and reuse it for independent summarization calls."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        *,
        max_input_tokens: int = DEFAULT_MAX_INPUT_TOKENS,
        device: DeviceName = "auto",
    ) -> None:
        if not model_name.strip():
            raise ValueError("model_name must not be empty")
        if max_input_tokens <= 0:
            raise ValueError("max_input_tokens must be greater than zero")

        self.model_name = model_name
        self.max_input_tokens = max_input_tokens
        self._requested_device = device
        self._device = self._resolve_device(device)
        self._tokenizer: Any | None = None
        self._model: Any | None = None
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
        """Return whether both model and tokenizer are ready."""

        return self._model is not None and self._tokenizer is not None

    def load(self) -> None:
        """Load model resources once; subsequent calls are no-ops."""

        if self.is_loaded:
            return

        with self._load_lock:
            if self.is_loaded:
                return
            try:
                tokenizer = AutoTokenizer.from_pretrained(self.model_name)
                model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name)
                model.to(self._device)
                model.eval()
            except (OSError, RuntimeError, ValueError) as exc:
                raise RuntimeError(
                    f"Could not load FLAN-T5 checkpoint '{self.model_name}': {exc}"
                ) from exc

            self._tokenizer = tokenizer
            self._model = model

    def summarize(self, article_text: str) -> str:
        """Return only the generated summary for normal pipeline use."""

        return self.summarize_with_metrics(article_text).summary

    def summarize_with_metrics(self, article_text: str) -> FlanSummaryResult:
        """Generate a summary and return token counts and inference timing."""

        if not isinstance(article_text, str):
            raise TypeError("article_text must be a string")

        cleaned_text = article_text.strip()
        if not cleaned_text:
            raise ValueError("article_text must not be empty or whitespace-only")

        self.load()
        if self._tokenizer is None or self._model is None:
            raise RuntimeError("FLAN-T5 resources were not loaded")

        prompt = SUMMARY_PROMPT.format(article_text=cleaned_text)
        all_input_ids = self._tokenizer(
            prompt,
            add_special_tokens=True,
            truncation=False,
            return_attention_mask=False,
            verbose=False,
        )["input_ids"]
        original_input_token_count = len(all_input_ids)

        encoded = self._tokenizer(
            prompt,
            max_length=self.max_input_tokens,
            truncation=True,
            return_tensors="pt",
        )
        model_inputs = {
            name: tensor.to(self._device) for name, tensor in encoded.items()
        }
        input_token_count = int(model_inputs["attention_mask"].sum().item())

        try:
            started_at = perf_counter()
            with torch.inference_mode():
                generated_ids = self._model.generate(
                    **model_inputs,
                    do_sample=False,
                    num_beams=4,
                    max_new_tokens=64,
                    early_stopping=True,
                    no_repeat_ngram_size=3,
                )
            inference_seconds = perf_counter() - started_at
        except RuntimeError as exc:
            raise RuntimeError(f"FLAN-T5 inference failed: {exc}") from exc

        summary = self._tokenizer.decode(
            generated_ids[0], clean_up_tokenization_spaces=True, skip_special_tokens=True
        ).strip()
        if not summary:
            raise RuntimeError("FLAN-T5 generated an empty summary")

        special_token_ids = set(self._tokenizer.all_special_ids)
        output_token_count = sum(
            int(token_id) not in special_token_ids for token_id in generated_ids[0]
        )

        return FlanSummaryResult(
            summary=summary,
            inference_seconds=inference_seconds,
            input_token_count=input_token_count,
            original_input_token_count=original_input_token_count,
            output_token_count=output_token_count,
            input_was_truncated=original_input_token_count > input_token_count,
        )


# Shared lazy singleton: importing this module does not load model weights. The first
# valid summarize call loads them once, and later calls reuse the same resources.
flan_service = FlanT5Service()

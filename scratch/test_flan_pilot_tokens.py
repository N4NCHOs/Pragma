"""Offline token-preflight tests; fake tokenizer, temporary fixtures only.

These deliberately small fixtures test implementation behavior, not FLAN
quality or real token lengths. No models, network, database, or scraper run.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import measure_flan_pilot_tokens as preflight


BASELINE_SOURCE = '''import forbidden_model_dependency
raise RuntimeError("This source must never execute")
DEFAULT_MODEL_NAME = "google/flan-t5-base"
DEFAULT_MAX_INPUT_TOKENS = 512
SUMMARY_PROMPT = "Keep facts.\\nArticle:\\n{article_text}\\nSummary:"
def inference(model, model_inputs):
    return model.generate(**model_inputs, do_sample=False, num_beams=4,
                          max_new_tokens=64, early_stopping=True,
                          no_repeat_ngram_size=3)
'''
PROMPT = "Keep facts.\nArticle:\n{article_text}\nSummary:"


def article(article_id: str, **updates):
    value = {
        "dataset_article_id": article_id,
        "title": "Ethereum update",
        "full_body": "The proposal concerns $4 million, not a confirmed loss.",
        "metadata": {"tags": ["ETH", "東京"]},
        "qualification_status": "qualified",
        "is_redundant": False,
    }
    value.update(updates)
    return value


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class FakeTokenizer:
    """One character per fixture token plus EOS; not a FLAN approximation."""

    all_special_ids = [1]
    model_max_length = 512
    truncation_side = "right"

    def __init__(self):
        self.calls = []

    def __call__(self, text: str, **kwargs):
        self.calls.append((text, dict(kwargs)))
        ids = [ord(character) + 10 for character in text]
        if kwargs.get("truncation"):
            ids = ids[: kwargs["max_length"] - 1]
        if kwargs.get("add_special_tokens", True):
            ids.append(1)
        result = {"input_ids": ids}
        if kwargs.get("return_attention_mask", True):
            result["attention_mask"] = [1] * len(ids)
        return result

    def decode(self, ids, *, skip_special_tokens=True):
        return "".join(
            chr(token - 10) for token in ids
            if not skip_special_tokens or token not in self.all_special_ids
        )

    def num_special_tokens_to_add(self, pair=False):
        return 1


class TempFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.source = self.folder / "flan_t5_fixture.py"
        self.source.write_text(BASELINE_SOURCE, encoding="utf-8")

    def write_snapshot(self, articles=None, **report_updates):
        snapshot = self.folder / "snapshot"
        snapshot.mkdir(exist_ok=True)
        if articles is None:
            articles = [article(item) for item in preflight.PILOT_ARTICLE_IDS]
        report = {
            "status": "complete",
            "cleaned_dataset_hash": preflight.compute_dataset_hash(articles),
        }
        report.update(report_updates)
        (snapshot / "qualified_news_cleaned.json").write_text(
            json.dumps(articles, ensure_ascii=False), encoding="utf-8",
        )
        (snapshot / "preprocessing_report.json").write_text(
            json.dumps(report), encoding="utf-8",
        )
        return snapshot


class BaselineLiteralTests(TempFixtureTests):
    def test_extracts_literal_settings_and_generation_without_execution(self):
        baseline = preflight.read_flan_baseline(self.source)
        self.assertEqual(baseline["DEFAULT_MODEL_NAME"], "google/flan-t5-base")
        self.assertEqual(baseline["DEFAULT_MAX_INPUT_TOKENS"], 512)
        self.assertEqual(baseline["SUMMARY_PROMPT"], PROMPT)
        self.assertEqual(baseline["generation_settings"], {
            "do_sample": False, "num_beams": 4, "max_new_tokens": 64,
            "early_stopping": True, "no_repeat_ngram_size": 3,
        })
        self.assertEqual(baseline["source_sha256"], digest(BASELINE_SOURCE))
        self.assertNotIn("forbidden_model_dependency", sys.modules)

    def test_missing_expected_setting_is_rejected(self):
        self.source.write_text(BASELINE_SOURCE.replace(
            'DEFAULT_MODEL_NAME = "google/flan-t5-base"\n', "",
        ), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "three expected literal settings"):
            preflight.read_flan_baseline(self.source)

    def test_computed_configuration_is_not_executed(self):
        self.source.write_text(BASELINE_SOURCE.replace(
            '"google/flan-t5-base"', 'str("google/flan-t5-base")',
        ), encoding="utf-8")
        with self.assertRaises(ValueError):
            preflight.read_flan_baseline(self.source)

    def test_empty_or_nonstring_checkpoint_is_rejected(self):
        for replacement in ('" "', "123"):
            with self.subTest(replacement=replacement):
                self.source.write_text(BASELINE_SOURCE.replace(
                    '"google/flan-t5-base"', replacement,
                ), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "nonempty literal string"):
                    preflight.read_flan_baseline(self.source)

    def test_prompt_requires_exactly_one_article_placeholder(self):
        for replacement in ("article", "{article_text}{article_text}"):
            with self.subTest(replacement=replacement):
                self.source.write_text(BASELINE_SOURCE.replace(
                    "{article_text}", replacement,
                ), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "exactly one"):
                    preflight.read_flan_baseline(self.source)

    def test_ambiguous_generate_calls_are_rejected(self):
        self.source.write_text(
            BASELINE_SOURCE + "\ndef another(model):\n    return model.generate()\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "exactly one FLAN generate"):
            preflight.read_flan_baseline(self.source)

    def test_missing_generate_call_is_rejected(self):
        self.source.write_text(BASELINE_SOURCE.replace(
            "model.generate(", "model.other_method(",
        ), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "exactly one FLAN generate"):
            preflight.read_flan_baseline(self.source)

    def test_nonliteral_generation_setting_is_rejected(self):
        self.source.write_text(BASELINE_SOURCE.replace(
            "max_new_tokens=64", "max_new_tokens=output_budget",
        ), encoding="utf-8")
        with self.assertRaises(ValueError):
            preflight.read_flan_baseline(self.source)


class FrozenSnapshotTests(TempFixtureTests):
    def test_selects_all_six_by_stable_id_in_planned_order(self):
        original = [article(item) for item in reversed(preflight.PILOT_ARTICLE_IDS)]
        original.insert(2, article("additional-qualified-record"))
        snapshot = self.write_snapshot(original)
        before = (snapshot / "qualified_news_cleaned.json").read_bytes()
        selected, report = preflight.load_pilot_articles(snapshot)
        self.assertEqual(
            [item["dataset_article_id"] for item in selected],
            list(preflight.PILOT_ARTICLE_IDS),
        )
        self.assertEqual(report["status"], "complete")
        self.assertEqual(selected[0]["metadata"], {"tags": ["ETH", "東京"]})
        self.assertEqual((snapshot / "qualified_news_cleaned.json").read_bytes(), before)

    def test_incomplete_snapshot_is_rejected(self):
        snapshot = self.write_snapshot(status="in_progress")
        with self.assertRaisesRegex(ValueError, "not marked complete"):
            preflight.load_pilot_articles(snapshot)

    def test_hash_mismatch_is_rejected(self):
        snapshot = self.write_snapshot(cleaned_dataset_hash="not-the-snapshot-hash")
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            preflight.load_pilot_articles(snapshot)

    def test_missing_proposed_id_is_rejected(self):
        snapshot = self.write_snapshot([
            article(item) for item in preflight.PILOT_ARTICLE_IDS[:-1]
        ])
        with self.assertRaisesRegex(ValueError, "pilot IDs missing"):
            preflight.load_pilot_articles(snapshot)

    def test_duplicate_id_is_rejected_even_with_matching_dataset_hash(self):
        records = [article(item) for item in preflight.PILOT_ARTICLE_IDS]
        records.append(deepcopy(records[0]))
        snapshot = self.write_snapshot(records)
        with self.assertRaisesRegex(ValueError, "missing or duplicate article IDs"):
            preflight.load_pilot_articles(snapshot)

    def test_absent_or_invalid_id_is_rejected(self):
        for invalid in (None, "", 123):
            with self.subTest(invalid=invalid):
                records = [article(item) for item in preflight.PILOT_ARTICLE_IDS]
                records.append(article(invalid))
                snapshot = self.write_snapshot(records)
                with self.assertRaisesRegex(ValueError, "missing or duplicate article IDs"):
                    preflight.load_pilot_articles(snapshot)

    def test_nonobject_record_is_rejected(self):
        records = [article(item) for item in preflight.PILOT_ARTICLE_IDS]
        records.append("not-an-article")
        snapshot = self.write_snapshot(records)
        with self.assertRaisesRegex(ValueError, "non-object record"):
            preflight.load_pilot_articles(snapshot)

    def test_nonlist_dataset_is_rejected(self):
        snapshot = self.write_snapshot({"articles": []})
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            preflight.load_pilot_articles(snapshot)


class TokenMeasurementTests(unittest.TestCase):
    def test_exact_service_text_and_prompt_are_measured_without_mutation(self):
        record = article("id", title="  Ethereum  ", full_body=" body with  spaces \n ")
        before = deepcopy(record)
        tokenizer = FakeTokenizer()
        rows, inputs = preflight.measure_inputs([record], PROMPT, tokenizer)
        expected_article = "Ethereum  .  body with  spaces"
        expected_input = PROMPT.format(article_text=expected_article)
        self.assertEqual(record, before)
        self.assertEqual(inputs[0]["article"], before)
        self.assertEqual(inputs[0]["article_text"], expected_article)
        self.assertEqual(inputs[0]["formatted_input"], expected_input)
        self.assertTrue(all(text == expected_input for text, _ in tokenizer.calls))
        self.assertEqual(tokenizer.calls[0][1], {
            "add_special_tokens": True, "truncation": False,
            "return_attention_mask": False, "verbose": False,
        })
        self.assertEqual(rows[0]["article_text_sha256"], digest(expected_article))
        self.assertEqual(rows[0]["formatted_input_sha256"], digest(expected_input))

    def test_complete_count_includes_special_token_and_short_input_is_untruncated(self):
        tokenizer = FakeTokenizer()
        rows, inputs = preflight.measure_inputs([article("id")], PROMPT, tokenizer)
        row = rows[0]
        expected_count = len(inputs[0]["formatted_input"]) + 1
        self.assertEqual(row["complete_input_tokens"], expected_count)
        self.assertEqual(row["special_tokens_in_complete_input"], 1)
        self.assertEqual(
            [item["max_input_tokens"] for item in row["limits"]],
            list(preflight.INPUT_LIMITS),
        )
        for item in row["limits"]:
            self.assertEqual(item["consumed_input_tokens"], expected_count)
            self.assertEqual(item["removed_token_count"], 0)
            self.assertFalse(item["input_was_truncated"])
            self.assertIn("Summary:", item["decoded_final_tokens"])

    def test_actual_truncated_lengths_and_decoded_tail_are_audited(self):
        tokenizer = FakeTokenizer()
        rows, inputs = preflight.measure_inputs([
            article("id", full_body="long body " * 500),
        ], PROMPT, tokenizer)
        self.assertEqual(len(tokenizer.calls), 1 + len(preflight.INPUT_LIMITS))
        complete = rows[0]["complete_input_tokens"]
        for item, (_, kwargs) in zip(rows[0]["limits"], tokenizer.calls[1:]):
            limit = item["max_input_tokens"]
            self.assertEqual(kwargs["max_length"], limit)
            self.assertTrue(kwargs["truncation"])
            self.assertTrue(kwargs["add_special_tokens"])
            self.assertEqual(item["consumed_input_tokens"], limit)
            self.assertEqual(item["removed_token_count"], complete - limit)
            self.assertTrue(item["input_was_truncated"])
            expected_ids = tokenizer(
                inputs[0]["formatted_input"], max_length=limit,
                truncation=True, add_special_tokens=True,
            )["input_ids"]
            self.assertEqual(item["decoded_final_tokens"], tokenizer.decode(expected_ids[-12:]))
            self.assertNotIn("Summary:", item["decoded_final_tokens"])

    def test_count_equal_to_limit_is_not_marked_truncated(self):
        prompt = "{article_text}"
        # Title+separator is three characters, body 508, EOS one: exactly 512.
        rows, _ = preflight.measure_inputs([
            article("id", title="A", full_body="b" * 508),
        ], prompt, FakeTokenizer())
        self.assertEqual(rows[0]["complete_input_tokens"], 512)
        self.assertFalse(rows[0]["limits"][0]["input_was_truncated"])

    def test_nonempty_string_article_fields_are_required(self):
        for key in ("dataset_article_id", "title", "full_body"):
            for invalid in (None, "", " \n ", 123):
                with self.subTest(key=key, invalid=invalid):
                    tokenizer = FakeTokenizer()
                    with self.assertRaisesRegex(ValueError, key):
                        preflight.measure_inputs([
                            article("id", **{key: invalid}),
                        ], PROMPT, tokenizer)
                    self.assertEqual(tokenizer.calls, [])

    def test_attention_mask_must_match_unpadded_token_length(self):
        class PaddedTokenizer(FakeTokenizer):
            def __call__(self, text, **kwargs):
                result = super().__call__(text, **kwargs)
                if "attention_mask" in result:
                    result["attention_mask"][-1] = 0
                return result

        with self.assertRaisesRegex(ValueError, "unexpected padding"):
            preflight.measure_inputs([article("id")], PROMPT, PaddedTokenizer())


class PreflightArtifactTests(TempFixtureTests):
    def setUp(self):
        super().setUp()
        self.snapshot = self.write_snapshot()
        self.output = self.folder / "new_output"
        self.revision = "abcdef0123456789"
        self.cached_config = self.folder / "cache" / "snapshots" / self.revision / "tokenizer_config.json"
        self.cached_config.parent.mkdir(parents=True)
        self.cached_config.write_text('{"model_max_length": 512}', encoding="utf-8")
        self.tokenizer = FakeTokenizer()
        self.hub = ModuleType("huggingface_hub")
        self.hub.try_to_load_from_cache = Mock(return_value=str(self.cached_config))
        self.transformers = ModuleType("transformers")
        self.transformers.AutoTokenizer = Mock()
        self.transformers.AutoTokenizer.from_pretrained.return_value = self.tokenizer
        self.modules = patch.dict(sys.modules, {
            "huggingface_hub": self.hub, "transformers": self.transformers,
        })
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def test_pins_local_cached_revision_and_freezes_exact_inputs(self):
        before = {
            path.name: path.read_bytes() for path in self.snapshot.iterdir()
        }
        with patch.object(preflight, "_package_version", return_value="fixture-version"):
            report = preflight.run_preflight(self.snapshot, self.source, self.output)
        self.hub.try_to_load_from_cache.assert_called_once_with(
            "google/flan-t5-base", "tokenizer_config.json",
        )
        self.transformers.AutoTokenizer.from_pretrained.assert_called_once_with(
            "google/flan-t5-base", revision=self.revision, local_files_only=True,
        )
        self.assertEqual(report["tokenizer"]["cached_revision"], self.revision)
        self.assertTrue(report["tokenizer"]["local_files_only"])
        self.assertEqual(report["tokenizer"]["class"], "FakeTokenizer")
        self.assertEqual(report["tokenizer"]["cached_tokenizer_config_sha256"], digest(
            self.cached_config.read_text(encoding="utf-8"),
        ))
        saved = json.loads((self.output / "token_report.json").read_text())
        inputs = json.loads((self.output / "pilot_inputs.json").read_text())
        self.assertEqual(saved, report)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["article_count"], 6)
        self.assertEqual(report["recommended_pilot_max_input_tokens"], 512)
        self.assertEqual((self.output / "prompt_template.txt").read_text(), PROMPT)
        self.assertEqual(
            [item["article"]["dataset_article_id"] for item in inputs],
            list(preflight.PILOT_ARTICLE_IDS),
        )
        for item in inputs:
            self.assertEqual(item["article_text"], (
                f"{item['article']['title']}. {item['article']['full_body']}"
            ).strip())
            self.assertEqual(item["formatted_input"], PROMPT.format(
                article_text=item["article_text"],
            ))
        self.assertEqual(
            {path.name: path.read_bytes() for path in self.snapshot.iterdir()}, before,
        )

    def test_recommends_smallest_fitting_limit_not_always_largest(self):
        records = [article(item) for item in preflight.PILOT_ARTICLE_IDS]
        records[-1]["full_body"] = "x" * 1100
        self.write_snapshot(records)
        report = preflight.run_preflight(self.snapshot, self.source, self.output)
        self.assertEqual(report["recommended_pilot_max_input_tokens"], 2048)
        self.assertEqual(report["untruncated_articles_per_limit"], {
            "512": 5, "1024": 5, "2048": 6, "3072": 6,
        })

    def test_no_fitting_limit_is_reported_without_silent_article_truncation(self):
        records = [article(item) for item in preflight.PILOT_ARTICLE_IDS]
        records[-1]["full_body"] = "x" * 4000
        self.write_snapshot(records)
        report = preflight.run_preflight(self.snapshot, self.source, self.output)
        self.assertIsNone(report["recommended_pilot_max_input_tokens"])
        inputs = json.loads((self.output / "pilot_inputs.json").read_text())
        self.assertEqual(inputs[-1]["article"]["full_body"], "x" * 4000)

    def test_completion_report_is_written_after_frozen_inputs_and_prompt(self):
        original_writer = preflight.atomic_write_json
        writes = []

        def checked_writer(path, payload, **kwargs):
            writes.append(path.name)
            if path.name == "token_report.json":
                self.assertTrue((self.output / "pilot_inputs.json").is_file())
                self.assertEqual((self.output / "prompt_template.txt").read_text(), PROMPT)
            original_writer(path, payload, **kwargs)

        with patch.object(preflight, "atomic_write_json", side_effect=checked_writer):
            preflight.run_preflight(self.snapshot, self.source, self.output)
        self.assertEqual(writes, ["pilot_inputs.json", "token_report.json"])

    def test_existing_destination_is_rejected_without_loading_or_overwriting(self):
        self.output.mkdir()
        marker = self.output / "keep.txt"
        marker.write_text("existing output")
        with self.assertRaises(FileExistsError):
            preflight.run_preflight(self.snapshot, self.source, self.output)
        self.assertEqual(marker.read_text(), "existing output")
        self.hub.try_to_load_from_cache.assert_not_called()
        self.transformers.AutoTokenizer.from_pretrained.assert_not_called()

    def test_uncached_tokenizer_refuses_without_download_or_output(self):
        self.hub.try_to_load_from_cache.return_value = None
        with self.assertRaisesRegex(RuntimeError, "not cached locally"):
            preflight.run_preflight(self.snapshot, self.source, self.output)
        self.transformers.AutoTokenizer.from_pretrained.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_invalid_snapshot_does_not_load_tokenizer_or_create_output(self):
        self.write_snapshot(status="in_progress")
        with self.assertRaises(ValueError):
            preflight.run_preflight(self.snapshot, self.source, self.output)
        self.hub.try_to_load_from_cache.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_failed_measurement_leaves_no_complete_report(self):
        self.transformers.AutoTokenizer.from_pretrained.return_value = Mock(
            side_effect=RuntimeError("fixture encoding failure"), all_special_ids=[1],
        )
        with self.assertRaisesRegex(RuntimeError, "fixture encoding failure"):
            preflight.run_preflight(self.snapshot, self.source, self.output)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()

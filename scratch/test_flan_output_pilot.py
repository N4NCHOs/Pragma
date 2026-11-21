"""Offline contract tests for the FLAN output pilot; no ML or database imports."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from measure_flan_pilot_tokens import PILOT_ARTICLE_IDS, read_flan_baseline
from pipeline_experiment_data import compute_dataset_hash
import run_flan_output_pilot as pilot


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class SequenceInspectionTests(unittest.TestCase):
    def inspect(self, sequence, beams=None, **kwargs):
        if beams is None:
            beams = [0] * (len(sequence) - 1)
        options = {
            "decoder_start_id": 0, "eos_ids": {1},
            "special_ids": {0, 1, 99}, "max_new_tokens": 4,
        }
        options.update(kwargs)
        return pilot.inspect_selected_sequence(sequence, beams, **options)

    def test_eos_before_ceiling_excludes_decoder_start(self):
        result = self.inspect([0, 10, 11, 1])
        self.assertEqual(result["selected_token_ids"], [10, 11, 1])
        self.assertEqual(result["generated_new_tokens_including_eos"], 3)
        self.assertEqual(result["output_token_count"], 2)
        self.assertEqual(result["eos_position_new_tokens"], 3)
        self.assertEqual(result["stop_reason"], "eos_before_limit")
        self.assertFalse(result["selected_output_reached_limit"])

    def test_eos_exactly_at_ceiling_is_separate_not_complete_claim(self):
        result = self.inspect([0, 10, 11, 12, 1])
        self.assertEqual(result["stop_reason"], "eos_at_limit")
        self.assertTrue(result["eos_found"])
        self.assertTrue(result["selected_output_reached_limit"])
        self.assertNotIn("complete", result)
        self.assertNotIn("factual", result)

    def test_forced_eos_at_ceiling_is_distinguished(self):
        result = self.inspect([0, 10, 11, 12, 1], forced_eos_ids={1})
        self.assertEqual(result["stop_reason"], "forced_eos_at_limit")

    def test_configured_forced_eos_does_not_make_earlier_eos_forced(self):
        result = self.inspect([0, 10, 1], forced_eos_ids={1})
        self.assertEqual(result["stop_reason"], "eos_before_limit")

    def test_other_forced_id_does_not_relabel_actual_eos(self):
        result = self.inspect([0, 10, 11, 12, 1], forced_eos_ids={2})
        self.assertEqual(result["stop_reason"], "eos_at_limit")

    def test_limit_without_eos_is_not_silently_natural(self):
        result = self.inspect([0, 10, 11, 12, 13])
        self.assertEqual(result["stop_reason"], "length_limit_without_eos")
        self.assertEqual(result["output_token_count"], 4)
        self.assertFalse(result["eos_found"])
        self.assertIsNone(result["eos_position_new_tokens"])

    def test_short_no_eos_is_unexpected_stop(self):
        result = self.inspect([0, 10, 11])
        self.assertEqual(result["stop_reason"], "unexpected_stop")

    def test_beam_fillers_are_ignored_even_if_they_look_like_eos(self):
        result = self.inspect([0, 10, 11, 1, 1, 1], [0, 3, 2, -1, -1])
        self.assertEqual(result["selected_token_ids"], [10, 11, 1])
        self.assertEqual(result["generated_new_tokens_including_eos"], 3)

    def test_beam_length_not_raw_sequence_shape_controls_count(self):
        result = self.inspect([0, 10, 11, 0, 0], [0, 1, -1, -1])
        self.assertEqual(result["selected_token_ids"], [10, 11])
        self.assertEqual(result["stop_reason"], "unexpected_stop")

    def test_special_tokens_consume_generation_budget_but_not_content_count(self):
        result = self.inspect([0, 10, 0, 99, 1])
        self.assertEqual(result["generated_new_tokens_including_eos"], 4)
        self.assertEqual(result["output_token_count"], 1)
        self.assertEqual(result["stop_reason"], "eos_at_limit")

    def test_immediate_eos_has_zero_content_not_zero_generation(self):
        result = self.inspect([0, 1])
        self.assertEqual(result["generated_new_tokens_including_eos"], 1)
        self.assertEqual(result["output_token_count"], 0)
        self.assertEqual(result["stop_reason"], "eos_before_limit")

    def test_multiple_eos_ids_supported(self):
        result = self.inspect([0, 10, 2], eos_ids={1, 2}, special_ids={0, 1, 2})
        self.assertEqual(result["eos_position_new_tokens"], 2)
        self.assertEqual(result["output_token_count"], 1)

    def test_empty_or_wrong_decoder_start_rejected(self):
        for sequence in ([], [8, 10, 1]):
            with self.subTest(sequence=sequence):
                with self.assertRaisesRegex(ValueError, "decoder-start"):
                    self.inspect(sequence)

    def test_invalid_lengths_rejected(self):
        for sequence, beams, limit in (
            ([0], [], 4),
            ([0, 10], [-1], 4),
            ([0, 10], [0, 1], 4),
            ([0, 10, 11, 12, 13, 14], [0] * 5, 4),
            ([0, 10], [0], 0),
        ):
            with self.subTest(sequence=sequence, beams=beams, limit=limit):
                with self.assertRaisesRegex(ValueError, "beam length"):
                    self.inspect(sequence, beams, max_new_tokens=limit)

    def test_noncontiguous_beam_ancestry_rejected(self):
        for beams in ([-1, 0], [0, -1, 2], [0, -1, 2, -1]):
            with self.subTest(beams=beams):
                with self.assertRaisesRegex(ValueError, "noncontiguous"):
                    self.inspect([0, 10, 11, 12, 13], beams)

    def test_valid_tokens_cannot_continue_after_eos(self):
        with self.assertRaisesRegex(ValueError, "continue after EOS"):
            self.inspect([0, 10, 1, 11])

    def test_inspection_does_not_mutate_inputs(self):
        sequence, beams = [0, 10, 1, 0], [0, 1, -1]
        before = deepcopy((sequence, beams))
        self.inspect(sequence, beams)
        self.assertEqual((sequence, beams), before)


class FrozenPilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.source = self.folder / "fake_flan_source.py"
        self.prompt = "Summarize simply.\nArticle:\n{article_text}\nSummary:"
        self.source.write_text(
            "DEFAULT_MODEL_NAME = 'google/flan-t5-base'\n"
            "DEFAULT_MAX_INPUT_TOKENS = 512\n"
            f"SUMMARY_PROMPT = {self.prompt!r}\n"
            "def never_execute():\n"
            "    return model.generate(do_sample=False, num_beams=4, "
            "max_new_tokens=64, early_stopping=True, no_repeat_ngram_size=3)\n"
            "raise RuntimeError('AST fixture must never execute')\n",
            encoding="utf-8",
        )
        baseline = read_flan_baseline(self.source)
        self.inputs = []
        self.rows = []
        for index, article_id in enumerate(PILOT_ARTICLE_IDS):
            article = {
                "dataset_article_id": article_id,
                "title": f"Offline fixture {index}",
                "full_body": f"Fixture body {index} for hash and formatting tests.",
            }
            article_text = f"{article['title']}. {article['full_body']}".strip()
            formatted = self.prompt.format(article_text=article_text)
            self.inputs.append({"article": article, "article_text": article_text,
                                "formatted_input": formatted})
            self.rows.append({
                "dataset_article_id": article_id,
                "article_text_sha256": digest(article_text),
                "formatted_input_sha256": digest(formatted),
                "complete_input_tokens": 100 + index,
            })
        self.report = {
            "status": "complete", "article_count": 6,
            "prompt_sha256": digest(self.prompt),
            "pilot_article_dataset_hash": self.article_hash(),
            "articles": self.rows, "flan_source": str(self.source),
            "flan_source_sha256": baseline["source_sha256"],
            "model_checkpoint": baseline["DEFAULT_MODEL_NAME"],
            "production_generation_settings": baseline["generation_settings"],
            "tokenizer": {"cached_revision": "offline-fixture-revision"},
        }
        self.save()

    def article_hash(self):
        return compute_dataset_hash([item["article"] for item in self.inputs])

    def save(self):
        (self.folder / "token_report.json").write_text(json.dumps(self.report), encoding="utf-8")
        (self.folder / "pilot_inputs.json").write_text(json.dumps(self.inputs), encoding="utf-8")
        (self.folder / "prompt_template.txt").write_text(self.prompt, encoding="utf-8")

    def test_valid_six_article_fixture_loads_without_executing_source(self):
        report, inputs, prompt = pilot.load_frozen_pilot(self.folder)
        self.assertEqual(report, self.report)
        self.assertEqual(inputs, self.inputs)
        self.assertEqual(prompt, self.prompt)
        self.assertEqual([item["article"]["dataset_article_id"] for item in inputs],
                         list(PILOT_ARTICLE_IDS))

    def test_loader_does_not_change_any_frozen_file(self):
        before = {path.name: path.read_bytes() for path in self.folder.iterdir()}
        pilot.load_frozen_pilot(self.folder)
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.folder.iterdir()})

    def test_incomplete_status_or_article_count_rejected(self):
        for key, value in (("status", "running"), ("article_count", 5)):
            with self.subTest(key=key):
                original = self.report[key]
                self.report[key] = value
                self.save()
                with self.assertRaisesRegex(ValueError, "six-article"):
                    pilot.load_frozen_pilot(self.folder)
                self.report[key] = original

    def test_missing_or_extra_input_record_rejected(self):
        for inputs in (self.inputs[:5], self.inputs + [self.inputs[0]], {}):
            with self.subTest(count=len(inputs)):
                (self.folder / "pilot_inputs.json").write_text(json.dumps(inputs), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "six frozen"):
                    pilot.load_frozen_pilot(self.folder)

    def test_changed_prompt_rejected_by_hash(self):
        self.prompt += " Changed instruction."
        self.save()
        with self.assertRaisesRegex(ValueError, "prompt hash"):
            pilot.load_frozen_pilot(self.folder)

    def test_changed_body_rejected_by_dataset_hash(self):
        self.inputs[0]["article"]["full_body"] += " changed"
        self.save()
        with self.assertRaisesRegex(ValueError, "dataset hash"):
            pilot.load_frozen_pilot(self.folder)

    def test_changed_article_order_rejected_by_dataset_hash(self):
        self.inputs[0], self.inputs[1] = self.inputs[1], self.inputs[0]
        self.save()
        with self.assertRaisesRegex(ValueError, "dataset hash"):
            pilot.load_frozen_pilot(self.folder)

    def test_rehashed_order_still_must_match_measurement_order(self):
        self.inputs[0], self.inputs[1] = self.inputs[1], self.inputs[0]
        self.report["pilot_article_dataset_hash"] = self.article_hash()
        self.save()
        with self.assertRaisesRegex(ValueError, "IDs/order"):
            pilot.load_frozen_pilot(self.folder)

    def test_duplicate_ids_rejected_even_when_hash_and_rows_updated(self):
        duplicate = self.inputs[0]["article"]["dataset_article_id"]
        self.inputs[1]["article"]["dataset_article_id"] = duplicate
        self.rows[1]["dataset_article_id"] = duplicate
        self.report["pilot_article_dataset_hash"] = self.article_hash()
        self.save()
        with self.assertRaisesRegex(ValueError, "IDs/order"):
            pilot.load_frozen_pilot(self.folder)

    def test_missing_measurement_row_rejected(self):
        self.report["articles"] = self.rows[:5]
        self.save()
        with self.assertRaisesRegex(ValueError, "six measurement"):
            pilot.load_frozen_pilot(self.folder)

    def test_exact_article_and_formatted_text_must_match(self):
        for key in ("article_text", "formatted_input"):
            with self.subTest(key=key):
                original = self.inputs[0][key]
                self.inputs[0][key] += " changed"
                self.save()
                with self.assertRaisesRegex(ValueError, "exact service formatting"):
                    pilot.load_frozen_pilot(self.folder)
                self.inputs[0][key] = original

    def test_rehashed_body_still_must_match_article_text(self):
        self.inputs[0]["article"]["full_body"] += " changed"
        self.report["pilot_article_dataset_hash"] = self.article_hash()
        self.save()
        with self.assertRaisesRegex(ValueError, "exact service formatting"):
            pilot.load_frozen_pilot(self.folder)

    def test_article_and_formatted_input_hashes_verified(self):
        for key in ("article_text_sha256", "formatted_input_sha256"):
            with self.subTest(key=key):
                original = self.rows[0][key]
                self.rows[0][key] = "incorrect hash"
                self.save()
                with self.assertRaisesRegex(ValueError, "hash mismatch"):
                    pilot.load_frozen_pilot(self.folder)
                self.rows[0][key] = original

    def test_input_above_fixed_ceiling_rejected(self):
        self.rows[0]["complete_input_tokens"] = pilot.PILOT_INPUT_LIMIT + 1
        self.save()
        with self.assertRaisesRegex(ValueError, "truncate"):
            pilot.load_frozen_pilot(self.folder)

    def test_input_exactly_at_ceiling_accepted(self):
        self.rows[0]["complete_input_tokens"] = pilot.PILOT_INPUT_LIMIT
        self.save()
        self.assertEqual(pilot.load_frozen_pilot(self.folder)[0]["article_count"], 6)

    def test_any_production_source_edit_requires_review(self):
        with self.source.open("a", encoding="utf-8") as source:
            source.write("\n# A harmless edit still changes the frozen baseline.\n")
        with self.assertRaisesRegex(ValueError, "baseline changed"):
            pilot.load_frozen_pilot(self.folder)

    def test_baseline_model_or_generation_changes_rejected(self):
        for key, value in (
            ("model_checkpoint", "google/flan-t5-small"),
            ("production_generation_settings", {"do_sample": True}),
        ):
            with self.subTest(key=key):
                original = self.report[key]
                self.report[key] = value
                self.save()
                with self.assertRaisesRegex(ValueError, "baseline changed"):
                    pilot.load_frozen_pilot(self.folder)
                self.report[key] = original

    def test_existing_output_rejected_before_loading_dependencies(self):
        with patch.object(pilot, "load_frozen_pilot") as load:
            with self.assertRaises(FileExistsError):
                pilot.run_pilot(self.folder, self.folder)
        load.assert_not_called()


class AggregateTests(unittest.TestCase):
    @staticmethod
    def row(article_id, limit, *, summary="same summary", error=None):
        return {
            "dataset_article_id": article_id, "max_new_tokens": limit,
            "error": error, "summary": summary, "stop_reason": "eos_before_limit",
            "output_token_count": 10, "inference_seconds": 2.0,
        }

    def test_empty_results_have_none_means_not_fake_zero_quality(self):
        result = pilot.aggregate_results([])
        self.assertEqual(result["within_article_comparisons"], [])
        for group in result["by_output_limit"].values():
            self.assertEqual(group["completed_trials"], 0)
            self.assertIsNone(group["mean_output_tokens"])
            self.assertIsNone(group["mean_inference_seconds"])

    def test_failed_trials_count_but_do_not_enter_output_means(self):
        good = self.row("a", 64)
        failure = {"dataset_article_id": "b", "max_new_tokens": 64,
                   "error": "RuntimeError: offline fixture"}
        result = pilot.aggregate_results([good, failure])
        group = result["by_output_limit"]["64"]
        self.assertEqual(group["completed_trials"], 2)
        self.assertEqual(group["successful_trials"], 1)
        self.assertEqual(group["errors"], 1)
        self.assertEqual(group["mean_output_tokens"], 10)
        self.assertEqual(group["stop_reasons"], {"eos_before_limit": 1})

    def test_failed_only_group_has_no_means(self):
        failure = {"dataset_article_id": "a", "max_new_tokens": 96, "error": "failure"}
        group = pilot.aggregate_results([failure])["by_output_limit"]["96"]
        self.assertEqual(group["errors"], 1)
        self.assertIsNone(group["mean_output_tokens"])

    def test_identical_and_different_summaries_are_descriptive_only(self):
        rows = [self.row("a", limit) for limit in pilot.OUTPUT_LIMITS]
        rows += [self.row("b", limit, summary=f"summary {limit}") for limit in pilot.OUTPUT_LIMITS]
        result = pilot.aggregate_results(rows)
        self.assertEqual(result["within_article_comparisons"], [
            {"dataset_article_id": "a", "identical_summary_across_all_limits": True},
            {"dataset_article_id": "b", "identical_summary_across_all_limits": False},
        ])
        self.assertNotIn("best", result)
        self.assertNotIn("quality", result)

    def test_partial_article_or_failed_configuration_not_compared(self):
        rows = [self.row("a", limit) for limit in (64, 96)]
        rows.append(self.row("a", 128, error="failed"))
        self.assertEqual(pilot.aggregate_results(rows)["within_article_comparisons"], [])


class DeviceAndImportTests(unittest.TestCase):
    def torch_mock(self, *, cuda=False, mps=False):
        return SimpleNamespace(
            cuda=SimpleNamespace(is_available=Mock(return_value=cuda), synchronize=Mock()),
            backends=SimpleNamespace(mps=SimpleNamespace(is_available=Mock(return_value=mps))),
            mps=SimpleNamespace(synchronize=Mock()),
            device=Mock(side_effect=lambda name: SimpleNamespace(type=name)),
        )

    def test_auto_prefers_cuda_then_mps_then_cpu(self):
        for cuda, mps, expected in ((True, True, "cuda"), (False, True, "mps"),
                                    (False, False, "cpu")):
            with self.subTest(cuda=cuda, mps=mps):
                torch = self.torch_mock(cuda=cuda, mps=mps)
                self.assertEqual(pilot._device(torch, "auto").type, expected)
                torch.device.assert_called_once_with(expected)

    def test_explicit_unavailable_accelerator_fails_without_fallback(self):
        for requested in ("cuda", "mps"):
            with self.subTest(requested=requested):
                torch = self.torch_mock()
                with self.assertRaisesRegex(RuntimeError, "no silent device fallback"):
                    pilot._device(torch, requested)
                torch.device.assert_not_called()

    def test_explicit_cpu_is_respected_even_when_accelerators_available(self):
        torch = self.torch_mock(cuda=True, mps=True)
        self.assertEqual(pilot._device(torch, "cpu").type, "cpu")
        torch.device.assert_called_once_with("cpu")

    def test_synchronization_uses_correct_accelerator_only(self):
        for kind in ("cpu", "cuda", "mps"):
            with self.subTest(kind=kind):
                torch = self.torch_mock(cuda=True, mps=True)
                device = SimpleNamespace(type=kind)
                pilot._synchronize(torch, device)
                self.assertEqual(torch.cuda.synchronize.call_count, int(kind == "cuda"))
                self.assertEqual(torch.mps.synchronize.call_count, int(kind == "mps"))

    def test_id_normalization(self):
        for value, expected in ((None, set()), (1, {1}), ([1, 2], {1, 2}), ((1, 1), {1})):
            with self.subTest(value=value):
                self.assertEqual(pilot._ids(value), expected)

    def test_fresh_import_has_no_heavy_model_or_pipeline_side_effects(self):
        code = (
            "import sys; import run_flan_output_pilot; "
            "forbidden = ['torch', 'transformers', 'database', 'main_pipeline', "
            "'rss_scrape_scheduler', 'ai_models.novelty_detection']; "
            "assert not any(name in sys.modules for name in forbidden), "
            "[name for name in forbidden if name in sys.modules]"
        )
        completed = subprocess.run([sys.executable, "-c", code], cwd=PROJECT_ROOT,
                                   capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "")


if __name__ == "__main__":
    unittest.main()

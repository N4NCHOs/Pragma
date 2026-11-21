"""Offline reference-package contracts; fixtures are not evaluation articles.

Only temporary synthetic unit-test text is used. No tokenizers, model weights,
network services, scraper, PostgreSQL connection, or real references are used.
"""

from __future__ import annotations

import builtins
from contextlib import nullcontext
from copy import deepcopy
import csv
import hashlib
from io import StringIO
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

import flan_reference_workflow as workflow
from measure_flan_pilot_tokens import PILOT_ARTICLE_IDS
from pipeline_experiment_data import atomic_write_json, compute_dataset_hash


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class PackageFixture(unittest.TestCase):
    """Seven deliberately synthetic records, including every pilot identity."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.snapshot = self.root / "snapshot"
        self.snapshot.mkdir()
        self.source = self.root / "fake_flan.py"
        self.preflight = self.root / "preflight.json"
        self.package = self.root / "reference_package"
        self.run = self.root / "comparison_run"
        self.prompt = 'Summarize for a beginner. Preserve facts.\nArticle:\n{article_text}\nSummary:'
        # This source is parsed as AST literals, never executed or imported.
        self.source.write_text(
            'DEFAULT_MODEL_NAME = "google/flan-t5-base"\n'
            'DEFAULT_MAX_INPUT_TOKENS = 512\n'
            f'SUMMARY_PROMPT = {self.prompt!r}\n'
            'def not_executed(model):\n'
            '    return model.generate(do_sample=False, num_beams=4, '
            'max_new_tokens=64, early_stopping=True, no_repeat_ngram_size=3)\n',
            encoding="utf-8",
        )
        identities = [*PILOT_ARTICLE_IDS, digest("nonpilot synthetic unit fixture")]
        self.articles = [
            {
                "dataset_article_id": identity,
                "title": f'Synthetic unit fixture {index}: comma, "quote"',
                "full_body": f"Synthetic unit-test body {index}.\nSecond paragraph, with punctuation.",
                "url": f"https://example.invalid/unit/{index}",
                "is_redundant": False,
            }
            for index, identity in enumerate(identities)
        ]
        self.write_snapshot()
        atomic_write_json(self.preflight, {
            "status": "complete", "model_checkpoint": "google/flan-t5-base",
            "prompt_sha256": digest(self.prompt),
            "tokenizer": {"cached_revision": "unit-test-local-revision"},
        })

    def write_snapshot(self):
        atomic_write_json(self.snapshot / "qualified_news_cleaned.json", self.articles)
        atomic_write_json(self.snapshot / "preprocessing_report.json", {
            "status": "complete", "cleaned_dataset_hash": compute_dataset_hash(self.articles),
        })

    def prepare(self, **kwargs):
        return workflow.prepare_reference_package(
            self.package, snapshot_dir=self.snapshot, flan_source=self.source,
            preflight_file=self.preflight, **kwargs,
        )

    def read_json(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def read_csv(self, filename):
        with (self.package / filename).open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def replace_csv(self, filename, fields, rows):
        with (self.package / filename).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            writer.writerows(rows)

    def set_ready(self, *, exclude=()):
        references = self.read_csv("gpt_reference_summaries.csv")
        audits = self.read_csv("source_audit.csv")
        for index, (reference, audit) in enumerate(zip(references, audits)):
            excluded = index in exclude
            reference["reference_summary"] = "" if excluded else f"Synthetic test reference {index}."
            audit["review_decision"] = "exclude" if excluded else "include"
            audit["review_notes"] = "Unit-test exclusion reason" if excluded else "Reviewed unit fixture"
        self.replace_csv("gpt_reference_summaries.csv", workflow.REFERENCE_FIELDS, references)
        self.replace_csv("source_audit.csv", workflow.AUDIT_FIELDS, audits)

    def make_complete_run(self):
        """Create model-free frozen output fixtures for the scoring loader."""
        self.set_ready()
        selected = workflow.validate_ready(self.package)
        manifest = workflow.load_package(self.package)["manifest"]
        self.run.mkdir()
        atomic_write_json(self.run / "selected_articles.json", selected)
        hashes = {}
        for limit in workflow.INPUT_LIMITS:
            rows = [{
                "id": article["id"], "title": article["title"],
                "summary": f"Synthetic unit summary at {limit}.",
                "reference_summary": article["reference_summary"],
            } for article in selected]
            path = self.run / f"flan_{limit}.csv"
            workflow._write_csv(path, workflow.RESULT_FIELDS, rows)
            hashes[str(limit)] = hashlib.sha256(path.read_bytes()).hexdigest()
        report = {
            "status": "complete", "completed_trials": len(selected) * 4,
            "expected_trials": len(selected) * 4, "article_count": len(selected),
            "input_limits": list(workflow.INPUT_LIMITS),
            "package_hash": manifest["frozen_articles_hash"],
            "prompt_sha256": manifest["prompt_sha256"],
            "selected_rows_hash": compute_dataset_hash(selected),
            "comparison_csv_hashes": hashes,
        }
        atomic_write_json(self.run / "run_manifest.json", report)
        return selected

    def edit_report(self, **changes):
        report = self.read_json(self.run / "run_manifest.json")
        report.update(changes)
        atomic_write_json(self.run / "run_manifest.json", report)

    def rewrite_result(self, limit, *, fields=None, mutate=None, rows=None):
        path = self.run / f"flan_{limit}.csv"
        if rows is None:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        if mutate:
            mutate(rows)
        path.unlink()
        workflow._write_csv(path, fields or workflow.RESULT_FIELDS, rows)
        report = self.read_json(self.run / "run_manifest.json")
        report["comparison_csv_hashes"][str(limit)] = hashlib.sha256(path.read_bytes()).hexdigest()
        atomic_write_json(self.run / "run_manifest.json", report)


class PreparationTests(PackageFixture):
    def test_all_candidates_and_six_pilots_retained_without_source_mutation(self):
        source_before = (self.snapshot / "qualified_news_cleaned.json").read_bytes()
        manifest = self.prepare()
        frozen = workflow.load_package(self.package)["articles"]
        self.assertEqual(manifest["article_count"], 7)
        self.assertEqual(manifest["pilot_count"], 6)
        self.assertEqual([row["id"] for row in frozen], [row["dataset_article_id"] for row in self.articles])
        self.assertEqual({row["id"] for row in frozen if row["is_pilot"]}, set(PILOT_ARTICLE_IDS))
        self.assertEqual((self.snapshot / "qualified_news_cleaned.json").read_bytes(), source_before)

    def test_reference_columns_blank_and_audits_pending(self):
        self.prepare()
        references = self.read_csv("gpt_reference_summaries.csv")
        audits = self.read_csv("source_audit.csv")
        self.assertEqual(tuple(references[0]), workflow.REFERENCE_FIELDS)
        self.assertEqual(tuple(audits[0]), workflow.AUDIT_FIELDS)
        self.assertTrue(all(row["reference_summary"] == "" for row in references))
        self.assertTrue(all(row["review_decision"] == "pending" for row in audits))

    def test_prompt_template_and_each_full_prompt_exact(self):
        self.prepare()
        self.assertEqual((self.package / "prompt_template.txt").read_text(encoding="utf-8"), self.prompt)
        prompts = sorted((self.package / "prompts").glob("*.txt"))
        self.assertEqual(len(prompts), len(self.articles))
        for path, article in zip(prompts, self.articles):
            text = f"{article['title']}. {article['full_body']}".strip()
            self.assertEqual(path.read_text(encoding="utf-8"), self.prompt.format(article_text=text))

    def test_csv_multiline_quotes_and_unicode_round_trip(self):
        self.articles[0]["full_body"] = 'Unit test — kripto, "nama".\nParagraph two.'
        self.write_snapshot()
        self.prepare()
        row = self.read_csv("gpt_reference_summaries.csv")[0]
        self.assertEqual(row["article_text"], f"{self.articles[0]['title']}. {self.articles[0]['full_body']}")

    def test_no_overwrite_existing_manual_reference(self):
        self.prepare()
        self.set_ready()
        before = (self.package / "gpt_reference_summaries.csv").read_bytes()
        with self.assertRaises(FileExistsError):
            self.prepare()
        self.assertEqual((self.package / "gpt_reference_summaries.csv").read_bytes(), before)

    def test_staged_json_package_not_ready_before_csv_export(self):
        manifest = self.prepare(write_templates=False)
        self.assertEqual(manifest["status"], "awaiting_csv_templates")
        self.assertFalse((self.package / "gpt_reference_summaries.csv").exists())
        staged = self.read_json(self.package / "template_data.json")
        self.assertEqual(len(staged["references"]), 7)
        with self.assertRaisesRegex(ValueError, "not complete"):
            workflow.load_package(self.package)

    def test_rejects_changed_source_hash(self):
        self.articles[0]["title"] = "Modified after report"
        atomic_write_json(self.snapshot / "qualified_news_cleaned.json", self.articles)
        with self.assertRaisesRegex(ValueError, "preprocessing report"):
            self.prepare()
        self.assertFalse(self.package.exists())

    def test_rejects_changed_prompt_or_checkpoint_from_pilot(self):
        for key, value in (("prompt_sha256", "wrong"), ("model_checkpoint", "wrong")):
            with self.subTest(key=key):
                preflight = self.read_json(self.preflight)
                original = preflight[key]
                preflight[key] = value
                atomic_write_json(self.preflight, preflight)
                with self.assertRaisesRegex(ValueError, "differs from pilot"):
                    self.prepare()
                preflight[key] = original
                atomic_write_json(self.preflight, preflight)

    def test_rejects_output_baseline_other_than_64(self):
        self.source.write_text(self.source.read_text().replace("max_new_tokens=64", "max_new_tokens=96"))
        with self.assertRaisesRegex(ValueError, "64-token"):
            self.prepare()

    def test_rejects_missing_pilot_without_partial_export(self):
        self.articles.pop(0)
        self.write_snapshot()
        with self.assertRaisesRegex(ValueError, "six pilot"):
            self.prepare()
        self.assertFalse(self.package.exists())

    def test_rejects_duplicate_or_invalid_source_identity(self):
        original = self.articles[-1]["dataset_article_id"]
        for identity in (self.articles[0]["dataset_article_id"], "short", "G" * 64):
            with self.subTest(identity=identity):
                self.articles[-1]["dataset_article_id"] = identity
                self.write_snapshot()
                with self.assertRaisesRegex(ValueError, "unique stable"):
                    self.prepare()
        self.articles[-1]["dataset_article_id"] = original

    def test_rejects_blank_body_or_title(self):
        for key in ("title", "full_body"):
            with self.subTest(key=key):
                original = self.articles[0][key]
                self.articles[0][key] = " \n"
                self.write_snapshot()
                with self.assertRaisesRegex(ValueError, "missing title/full_body"):
                    self.prepare()
                self.articles[0][key] = original

    def test_flags_are_annotations_not_automatic_exclusions(self):
        self.articles[-1]["full_body"] = "Skip to main content\nSynthetic navigation fixture."
        self.write_snapshot()
        manifest = self.prepare()
        audit = self.read_csv("source_audit.csv")[-1]
        self.assertEqual(manifest["article_count"], 7)
        self.assertEqual(manifest["flagged_article_count"], 1)
        self.assertIn("navigation_ticker_extract", audit["quality_flags"])
        self.assertEqual(audit["review_decision"], "pending")
        self.set_ready()
        self.assertEqual(len(workflow.validate_ready(self.package)), 7)


class ValidationTests(PackageFixture):
    def setUp(self):
        super().setUp()
        self.prepare()

    def test_all_pending_is_not_ready(self):
        with self.assertRaisesRegex(ValueError, "7 source decisions pending"):
            workflow.validate_ready(self.package)

    def test_all_six_pilots_can_be_included(self):
        self.set_ready()
        selected = workflow.validate_ready(self.package)
        self.assertEqual(sum(row["is_pilot"] for row in selected), 6)

    def test_blank_reference_for_included_article_rejected(self):
        self.set_ready()
        references = self.read_csv("gpt_reference_summaries.csv")
        references[2]["reference_summary"] = " \n"
        self.replace_csv("gpt_reference_summaries.csv", workflow.REFERENCE_FIELDS, references)
        with self.assertRaisesRegex(ValueError, "1 included references empty"):
            workflow.validate_ready(self.package)

    def test_excluded_reference_may_be_blank_but_reason_required(self):
        self.set_ready(exclude=(2,))
        selected = workflow.validate_ready(self.package)
        self.assertEqual(len(selected), 6)
        self.assertNotIn(self.articles[2]["dataset_article_id"], {row["id"] for row in selected})
        audits = self.read_csv("source_audit.csv")
        audits[2]["review_notes"] = " "
        self.replace_csv("source_audit.csv", workflow.AUDIT_FIELDS, audits)
        with self.assertRaisesRegex(ValueError, "exclusion requires a reason"):
            workflow.validate_ready(self.package)

    def test_all_excluded_is_not_empty_success(self):
        self.set_ready(exclude=range(7))
        with self.assertRaisesRegex(ValueError, "no articles explicitly included"):
            workflow.validate_ready(self.package)

    def test_id_join_not_row_order_and_source_order_preserved(self):
        self.set_ready()
        references = list(reversed(self.read_csv("gpt_reference_summaries.csv")))
        audits = self.read_csv("source_audit.csv")
        audits = audits[2:] + audits[:2]
        self.replace_csv("gpt_reference_summaries.csv", workflow.REFERENCE_FIELDS, references)
        self.replace_csv("source_audit.csv", workflow.AUDIT_FIELDS, audits)
        selected = workflow.validate_ready(self.package)
        self.assertEqual([row["id"] for row in selected], [row["dataset_article_id"] for row in self.articles])
        self.assertEqual([row["reference_summary"] for row in selected], [f"Synthetic test reference {index}." for index in range(7)])

    def test_duplicate_missing_and_extra_reference_or_audit_ids_fail(self):
        self.set_ready()
        for filename, fields in (("gpt_reference_summaries.csv", workflow.REFERENCE_FIELDS), ("source_audit.csv", workflow.AUDIT_FIELDS)):
            original = self.read_csv(filename)
            for mutation in ("duplicate", "missing", "extra", "blank"):
                with self.subTest(filename=filename, mutation=mutation):
                    rows = deepcopy(original)
                    if mutation == "duplicate":
                        rows[-1]["id"] = rows[0]["id"]
                    elif mutation == "missing":
                        rows.pop()
                    elif mutation == "extra":
                        rows.append({**rows[-1], "id": digest("unexpected")})
                    else:
                        rows[-1]["id"] = ""
                    self.replace_csv(filename, fields, rows)
                    with self.assertRaises(ValueError):
                        workflow.validate_ready(self.package)
            self.replace_csv(filename, fields, original)

    def test_changed_reference_title_or_text_rejected(self):
        self.set_ready()
        original = self.read_csv("gpt_reference_summaries.csv")
        for key in ("title", "article_text"):
            with self.subTest(key=key):
                rows = deepcopy(original)
                rows[0][key] += " changed"
                self.replace_csv("gpt_reference_summaries.csv", workflow.REFERENCE_FIELDS, rows)
                with self.assertRaisesRegex(ValueError, "title/source text changed"):
                    workflow.validate_ready(self.package)

    def test_changed_audit_title_or_pilot_identity_rejected(self):
        self.set_ready()
        original = self.read_csv("source_audit.csv")
        for key in ("title", "is_pilot"):
            with self.subTest(key=key):
                rows = deepcopy(original)
                rows[0][key] += " changed"
                self.replace_csv("source_audit.csv", workflow.AUDIT_FIELDS, rows)
                with self.assertRaisesRegex(ValueError, "audit title/pilot"):
                    workflow.validate_ready(self.package)

    def test_frozen_article_and_prompt_tampering_fail(self):
        original = (self.package / "frozen_articles.json").read_bytes()
        articles = self.read_json(self.package / "frozen_articles.json")
        articles[0]["full_body"] += " changed"
        atomic_write_json(self.package / "frozen_articles.json", articles)
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            workflow.load_package(self.package)
        (self.package / "frozen_articles.json").write_bytes(original)
        (self.package / "prompt_template.txt").write_text(self.prompt + " changed")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            workflow.load_package(self.package)

    def test_generation_blocked_before_heavy_imports_when_not_ready(self):
        original_import = builtins.__import__
        def guard(name, *args, **kwargs):
            if name.split(".")[0] in {"torch", "transformers", "sqlalchemy", "database"}:
                raise AssertionError(f"Forbidden heavy import: {name}")
            return original_import(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=guard):
            with self.assertRaisesRegex(ValueError, "Not ready"):
                workflow.generate_comparison_csvs(self.package, self.run)
        self.assertFalse(self.run.exists())

    def test_changed_model_source_blocked_before_import_and_output_creation(self):
        self.set_ready()
        self.source.write_text(self.source.read_text() + "\n# source changed\n")
        with patch.dict(sys.modules, {"torch": None, "transformers": None}):
            with self.assertRaisesRegex(ValueError, "FLAN source changed"):
                workflow.generate_comparison_csvs(self.package, self.run)
        self.assertFalse(self.run.exists())

    def assert_manifest_change_blocks_generation_before_import(self, **changes):
        manifest = self.read_json(self.package / "manifest.json")
        manifest.update(changes)
        atomic_write_json(self.package / "manifest.json", manifest)
        original_import = builtins.__import__
        def guard(name, *args, **kwargs):
            if name.split(".")[0] in {"torch", "transformers"}:
                raise AssertionError(f"Generation attempted a heavy import: {name}")
            return original_import(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=guard):
            with self.assertRaisesRegex(ValueError, "frozen checkpoint/prompt"):
                workflow.generate_comparison_csvs(self.package, self.run)
        self.assertFalse(self.run.exists())

    def test_tampered_generation_settings_blocked_before_heavy_imports(self):
        self.set_ready()
        original = self.read_json(self.package / "manifest.json")["generation_kwargs"]
        for key, value in (("max_new_tokens", 96), ("do_sample", True), ("num_beams", 1), ("no_repeat_ngram_size", 0)):
            with self.subTest(setting=key):
                self.assert_manifest_change_blocks_generation_before_import(
                    generation_kwargs={**original, key: value},
                )

    def test_tampered_model_checkpoint_blocked_before_heavy_imports(self):
        self.set_ready()
        self.assert_manifest_change_blocks_generation_before_import(
            model_checkpoint="google/flan-t5-small",
        )

    def test_tampered_input_limits_blocked_before_heavy_imports(self):
        self.set_ready()
        self.assert_manifest_change_blocks_generation_before_import(
            input_limits=[512, 1024, 2048],
        )

    def test_reference_header_must_match_exactly(self):
        self.set_ready()
        references = self.read_csv("gpt_reference_summaries.csv")
        self.replace_csv("gpt_reference_summaries.csv", tuple(reversed(workflow.REFERENCE_FIELDS)), references)
        with self.assertRaisesRegex(ValueError, "expected columns"):
            workflow.validate_ready(self.package)

    def test_missing_or_extra_reference_cells_rejected(self):
        self.set_ready()
        path = self.package / "gpt_reference_summaries.csv"
        original = path.read_bytes()
        for cells in (("incomplete",), ("a", "b", "c", "d", "extra")):
            with self.subTest(cells=cells):
                with path.open("a", encoding="utf-8-sig", newline="") as handle:
                    csv.writer(handle).writerow(cells)
                with self.assertRaisesRegex(ValueError, "malformed CSV"):
                    workflow.validate_ready(self.package)
                path.write_bytes(original)


class ComparisonLoaderTests(PackageFixture):
    def setUp(self):
        super().setUp()
        self.prepare()
        self.selected = self.make_complete_run()

    def test_complete_four_way_run_loads_exact_columns_and_same_references(self):
        comparisons = workflow.load_comparison_csvs(self.package, self.run)
        self.assertEqual(tuple(comparisons), workflow.INPUT_LIMITS)
        for limit, rows in comparisons.items():
            self.assertEqual(len(rows), 7)
            self.assertEqual(tuple(rows[0]), workflow.RESULT_FIELDS)
            self.assertEqual([row["id"] for row in rows], [row["id"] for row in self.selected])
            self.assertEqual([row["reference_summary"] for row in rows], [row["reference_summary"] for row in self.selected])

    def test_comparison_loader_uses_frozen_references_not_later_master_edits(self):
        references = self.read_csv("gpt_reference_summaries.csv")
        references[0]["reference_summary"] = "Later edit not part of this run."
        self.replace_csv("gpt_reference_summaries.csv", workflow.REFERENCE_FIELDS, references)
        result = workflow.load_comparison_csvs(self.package, self.run)
        self.assertEqual(result[512][0]["reference_summary"], self.selected[0]["reference_summary"])

    def test_reordered_result_rows_join_by_id(self):
        self.rewrite_result(512, mutate=lambda rows: rows.reverse())
        rows = workflow.load_comparison_csvs(self.package, self.run)[512]
        self.assertEqual([row["id"] for row in rows], [row["id"] for row in self.selected])

    def test_incomplete_or_interrupted_run_rejected(self):
        for status in ("running", "failed", "interrupted"):
            with self.subTest(status=status):
                self.edit_report(status=status)
                with self.assertRaisesRegex(ValueError, "incomplete"):
                    workflow.load_comparison_csvs(self.package, self.run)

    def test_trial_count_mismatch_rejected(self):
        self.edit_report(completed_trials=27)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            workflow.load_comparison_csvs(self.package, self.run)

    def test_zero_trials_cannot_masquerade_as_complete_nonempty_run(self):
        self.edit_report(completed_trials=0, expected_trials=0)
        with self.assertRaises(ValueError):
            workflow.load_comparison_csvs(self.package, self.run)

    def test_wrong_declared_article_count_rejected(self):
        self.edit_report(article_count=6)
        with self.assertRaises(ValueError):
            workflow.load_comparison_csvs(self.package, self.run)

    def test_wrong_declared_input_limits_rejected(self):
        self.edit_report(input_limits=[512])
        with self.assertRaises(ValueError):
            workflow.load_comparison_csvs(self.package, self.run)

    def test_missing_one_of_four_csvs_fails(self):
        (self.run / "flan_2048.csv").unlink()
        with self.assertRaises((OSError, ValueError)):
            workflow.load_comparison_csvs(self.package, self.run)

    def test_csv_modified_without_hash_update_fails(self):
        path = self.run / "flan_512.csv"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "CSV modified"):
            workflow.load_comparison_csvs(self.package, self.run)

    def test_selected_rows_hash_mismatch_fails(self):
        rows = self.read_json(self.run / "selected_articles.json")
        rows[0]["reference_summary"] += " changed"
        atomic_write_json(self.run / "selected_articles.json", rows)
        with self.assertRaisesRegex(ValueError, "provenance differs"):
            workflow.load_comparison_csvs(self.package, self.run)

    def test_selected_article_source_changed_even_with_updated_run_hash_fails(self):
        rows = self.read_json(self.run / "selected_articles.json")
        rows[0]["article_text"] += " changed"
        atomic_write_json(self.run / "selected_articles.json", rows)
        self.edit_report(selected_rows_hash=compute_dataset_hash(rows))
        with self.assertRaisesRegex(ValueError, "differs from package"):
            workflow.load_comparison_csvs(self.package, self.run)

    def test_wrong_package_or_prompt_hash_fails(self):
        original = self.read_json(self.run / "run_manifest.json")
        for key in ("package_hash", "prompt_sha256"):
            with self.subTest(key=key):
                self.edit_report(**{key: "wrong"})
                with self.assertRaisesRegex(ValueError, "provenance differs"):
                    workflow.load_comparison_csvs(self.package, self.run)
                atomic_write_json(self.run / "run_manifest.json", original)

    def test_reference_mismatch_title_mismatch_or_empty_summary_fails(self):
        path = self.run / "flan_512.csv"
        original = path.read_bytes()
        original_report = self.read_json(self.run / "run_manifest.json")
        for key, value in (("reference_summary", "other reference"), ("title", "other title"), ("summary", " \n")):
            with self.subTest(key=key):
                self.rewrite_result(512, mutate=lambda rows, key=key, value=value: rows[0].update({key: value}))
                with self.assertRaisesRegex(ValueError, "mismatched/empty"):
                    workflow.load_comparison_csvs(self.package, self.run)
                path.write_bytes(original)
                atomic_write_json(self.run / "run_manifest.json", original_report)

    def test_result_header_must_match_exactly(self):
        self.rewrite_result(512, fields=tuple(reversed(workflow.RESULT_FIELDS)))
        with self.assertRaisesRegex(ValueError, "expected columns"):
            workflow.load_comparison_csvs(self.package, self.run)

    def test_malformed_result_row_rejected_with_correct_file_hash(self):
        path = self.run / "flan_512.csv"
        with path.open("a", encoding="utf-8-sig", newline="") as handle:
            csv.writer(handle).writerow(["missing other columns"])
        report = self.read_json(self.run / "run_manifest.json")
        report["comparison_csv_hashes"]["512"] = hashlib.sha256(path.read_bytes()).hexdigest()
        atomic_write_json(self.run / "run_manifest.json", report)
        with self.assertRaisesRegex(ValueError, "malformed CSV"):
            workflow.load_comparison_csvs(self.package, self.run)

    def test_duplicate_missing_extra_result_ids_rejected_even_if_csv_hash_updated(self):
        path = self.run / "flan_512.csv"
        original = path.read_bytes()
        original_report = self.read_json(self.run / "run_manifest.json")
        for mutation in ("duplicate", "missing", "extra"):
            with self.subTest(mutation=mutation):
                def change(rows):
                    if mutation == "duplicate":
                        rows[-1]["id"] = rows[0]["id"]
                    elif mutation == "missing":
                        rows.pop()
                    else:
                        rows.append({**rows[0], "id": digest("unexpected result")})
                self.rewrite_result(512, mutate=change)
                with self.assertRaises(ValueError):
                    workflow.load_comparison_csvs(self.package, self.run)
                path.write_bytes(original)
                atomic_write_json(self.run / "run_manifest.json", original_report)


class FakeGenerationTests(PackageFixture):
    """Exercise orchestration with tiny Python objects, never an ML runtime."""

    def setUp(self):
        super().setUp()
        self.prepare()
        self.set_ready()

    def fake_runtime(self, *, fail_on_call=None):
        class FakeTensor:
            def __init__(self, values):
                self.values = values
            def to(self, device):
                return self
            def sum(self):
                return SimpleNamespace(item=lambda: sum(self.values))
            def tolist(self):
                return self.values

        class FakeTokenizer:
            all_special_ids = [0, 1]
            def __init__(self):
                self.calls = []
            def __call__(self, text, **kwargs):
                self.calls.append({"text": text, **kwargs})
                # Deliberately fake counts to exercise every truncation branch.
                # They are not measurements of the synthetic fixture's text.
                if kwargs.get("return_tensors") == "pt":
                    count = min(4000, kwargs["max_length"])
                    return {"input_ids": FakeTensor([5] * count), "attention_mask": FakeTensor([1] * count)}
                return {"input_ids": [5] * 4000}
            def decode(self, ids, **kwargs):
                return "Synthetic fake-model summary."

        class FakeModel:
            generation_config = SimpleNamespace(
                forced_eos_token_id=None, decoder_start_token_id=0, eos_token_id=1,
            )
            def __init__(self):
                self.calls = []
                self.to = Mock(return_value=self)
                self.eval = Mock(return_value=self)
            def parameters(self):
                return iter([SimpleNamespace(dtype="fake_float32")])
            def generate(self, **kwargs):
                self.calls.append(kwargs)
                if len(self.calls) == fail_on_call:
                    raise RuntimeError("synthetic unit-test generation failure")
                return SimpleNamespace(
                    sequences=[FakeTensor([0, 11, 12, 13, 1])],
                    beam_indices=[FakeTensor([0, 0, 0, 0])], scores=[None] * 4,
                )

        tokenizer, model = FakeTokenizer(), FakeModel()
        tokenizer_loader = Mock(return_value=tokenizer)
        model_loader = Mock(return_value=model)
        fake_torch = SimpleNamespace(
            cuda=SimpleNamespace(is_available=lambda: False),
            backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False)),
            device=lambda name: SimpleNamespace(type=name),
            manual_seed=Mock(), inference_mode=nullcontext,
        )
        fake_transformers = SimpleNamespace(
            AutoTokenizer=SimpleNamespace(from_pretrained=tokenizer_loader),
            AutoModelForSeq2SeqLM=SimpleNamespace(from_pretrained=model_loader),
        )
        return SimpleNamespace(
            torch=fake_torch, transformers=fake_transformers,
            tokenizer=tokenizer, model=model,
            tokenizer_loader=tokenizer_loader, model_loader=model_loader,
        )

    def test_fake_success_generates_four_complete_paired_csvs_and_loads_once(self):
        runtime = self.fake_runtime()
        with patch.dict(sys.modules, {"torch": runtime.torch, "transformers": runtime.transformers}), patch("sys.stdout", new_callable=StringIO):
            result = workflow.generate_comparison_csvs(self.package, self.run)
        options = {"revision": "unit-test-local-revision", "local_files_only": True}
        runtime.tokenizer_loader.assert_called_once_with("google/flan-t5-base", **options)
        runtime.model_loader.assert_called_once_with("google/flan-t5-base", **options)
        runtime.model.eval.assert_called_once()
        runtime.model.to.assert_called_once()
        runtime.torch.manual_seed.assert_called_once_with(0)
        self.assertEqual(len(runtime.model.calls), 28)
        expected_generation = self.read_json(self.package / "manifest.json")["generation_kwargs"]
        for call in runtime.model.calls:
            for key, value in expected_generation.items():
                self.assertEqual(call[key], value)
            self.assertTrue(call["return_dict_in_generate"])
            self.assertTrue(call["output_scores"])
        truncation_calls = [call for call in runtime.tokenizer.calls if call.get("return_tensors") == "pt"]
        self.assertEqual([call["max_length"] for call in truncation_calls], list(workflow.INPUT_LIMITS) * 7)
        self.assertTrue(all(call["truncation"] for call in truncation_calls))
        self.assertEqual(set(result["csv_paths"]), set(workflow.INPUT_LIMITS))
        report = self.read_json(self.run / "run_manifest.json")
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["completed_trials"], 28)
        self.assertEqual(report["expected_trials"], 28)
        metrics = self.read_json(self.run / "generation_metrics.json")
        self.assertEqual(len(metrics), 28)
        self.assertEqual([row["max_input_tokens"] for row in metrics], list(workflow.INPUT_LIMITS) * 7)
        for row in metrics:
            self.assertIsNone(row["error"])
            self.assertEqual(row["input_token_count"], row["max_input_tokens"])
            self.assertEqual(row["original_input_token_count"], 4000)
            self.assertTrue(row["input_was_truncated"])
            self.assertEqual(row["output_token_count"], 3)
            self.assertEqual(row["generated_new_tokens_including_eos"], 4)
            self.assertEqual(row["stop_reason"], "eos_before_limit")
            self.assertGreaterEqual(row["inference_seconds"], 0)
        comparisons = workflow.load_comparison_csvs(self.package, self.run)
        self.assertEqual(len(list(self.run.glob("flan_*.csv"))), 4)
        for rows in comparisons.values():
            self.assertEqual(len(rows), 7)
            self.assertEqual(tuple(rows[0]), workflow.RESULT_FIELDS)
            self.assertEqual([row["reference_summary"] for row in rows], [f"Synthetic test reference {index}." for index in range(7)])

    def test_fake_single_generation_failure_preserves_metrics_without_final_csvs(self):
        runtime = self.fake_runtime(fail_on_call=5)
        with patch.dict(sys.modules, {"torch": runtime.torch, "transformers": runtime.transformers}), patch("sys.stdout", new_callable=StringIO):
            with self.assertRaisesRegex(RuntimeError, "no incomplete comparison CSVs"):
                workflow.generate_comparison_csvs(self.package, self.run)
        runtime.tokenizer_loader.assert_called_once()
        runtime.model_loader.assert_called_once()
        report = self.read_json(self.run / "run_manifest.json")
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["completed_trials"], 28)
        self.assertIn("generation errors retained", report["error"])
        self.assertIn("finished_at_utc", report)
        metrics = self.read_json(self.run / "generation_metrics.json")
        self.assertEqual(len(metrics), 28)
        self.assertEqual(sum(row["error"] is not None for row in metrics), 1)
        self.assertIn("synthetic unit-test generation failure", metrics[4]["error"])
        self.assertEqual(list(self.run.glob("flan_*.csv")), [])
        self.assertTrue((self.run / "selected_articles.json").exists())
        self.assertTrue((self.run / "prompt_template.txt").exists())
        with self.assertRaisesRegex(ValueError, "incomplete"):
            workflow.load_comparison_csvs(self.package, self.run)


class LightweightImportTests(unittest.TestCase):
    def test_module_import_does_not_import_models_database_or_scraper(self):
        code = """
import builtins
real_import = builtins.__import__
forbidden = {'torch', 'transformers', 'sentence_transformers', 'sqlalchemy',
             'database', 'rss_scrape_scheduler', 'rss_scrape_dataset'}
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in forbidden:
        raise AssertionError('Forbidden side-effect import: ' + name)
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded
import flan_reference_workflow
"""
        process = subprocess.run(
            [sys.executable, "-c", code], cwd=PROJECT_ROOT,
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)


if __name__ == "__main__":
    unittest.main()

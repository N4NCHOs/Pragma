"""Offline integrity and stopping-count tests for the output comparison."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from pipeline_experiment_data import atomic_write_json, compute_dataset_hash
from run_flan_output_comparison import aggregate, file_hash, load_baseline


class OutputComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.source = self.folder / "flan.py"
        self.source.write_text(
            "DEFAULT_MODEL_NAME = 'fixture/flan'\nDEFAULT_MAX_INPUT_TOKENS = 512\n"
            "SUMMARY_PROMPT = 'Article: {article_text}\\nSummary:'\n"
            "def summarize(model):\n"
            "    return model.generate(do_sample=False, num_beams=4, max_new_tokens=64, "
            "early_stopping=True, no_repeat_ngram_size=3)\n", encoding="utf-8")
        self.articles = [{"id":"a", "title":"Article A", "article_text":"Article A. A fact.",
                          "reference_summary":"A fact."}]
        self.articles[0]["article_text_sha256"] = hashlib.sha256(self.articles[0]["article_text"].encode()).hexdigest()
        self.metric = {"id":"a", "title":"Article A", "max_input_tokens":3072,
                       "max_new_tokens":64, "input_token_count":12,
                       "original_input_token_count":12, "input_was_truncated":False,
                       "error":None, "summary":"A fact.", "stop_reason":"eos_before_limit",
                       "output_token_count":3, "generated_new_tokens_including_eos":4}
        prompt = "Article: {article_text}\nSummary:"
        (self.folder / "prompt_template.txt").write_text(prompt,encoding="utf-8")
        csv = self.folder / "flan_3072.csv"
        csv.write_text("id,title,summary,reference_summary\na,Article A,A fact.,A fact.\n",encoding="utf-8")
        self.manifest = {"status":"complete", "article_count":1,
            "selected_rows_hash":compute_dataset_hash(self.articles),
            "prompt_sha256":hashlib.sha256(prompt.encode()).hexdigest(),
            "generation_kwargs":{"do_sample":False,"num_beams":4,"max_new_tokens":64,
                                 "early_stopping":True,"no_repeat_ngram_size":3},
            "model_checkpoint":"fixture/flan", "input_limits":[3072], "completed_trials":1,
            "comparison_csv_hashes":{"3072":file_hash(csv)}, "device":"cpu"}
        self.context = {"status":"complete", "model_source_sha256":file_hash(self.source),
                        "cpu_threads":4,"generation_seed":0}
        self.save()

    def save(self):
        for name, payload in (("selected_articles.json",self.articles),
                              ("generation_metrics.json",[self.metric]),
                              ("run_manifest.json",self.manifest),
                              ("execution_context.json",self.context)):
            atomic_write_json(self.folder / name,payload,indent=2)

    def test_valid_frozen_baseline_loads_without_model(self):
        result = load_baseline(self.folder,self.source)
        self.assertEqual(result["baseline_rows"][0]["id"],"a")

    def test_changed_article_is_rejected(self):
        self.articles[0]["article_text"] = "Different facts."
        self.save()
        with self.assertRaisesRegex(ValueError,"snapshot hash"):
            load_baseline(self.folder,self.source)

    def test_changed_csv_is_rejected(self):
        (self.folder / "flan_3072.csv").write_text("changed",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"CSV integrity"):
            load_baseline(self.folder,self.source)

    def test_truncated_baseline_cannot_be_reused(self):
        self.metric["input_was_truncated"] = True
        self.save()
        with self.assertRaisesRegex(ValueError,"input-truncated"):
            load_baseline(self.folder,self.source)

    def test_changed_source_is_rejected(self):
        self.source.write_text(self.source.read_text()+"\n# changed\n",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"source/prompt/settings"):
            load_baseline(self.folder,self.source)

    def test_eos_at_limit_is_separate_from_without_eos(self):
        rows = [{**self.metric,"max_new_tokens":96,"stop_reason":reason}
                for reason in ("eos_before_limit","eos_at_limit","length_limit_without_eos")]
        counts = aggregate(rows,3)["96"]
        self.assertEqual(counts["successful_trials"],3)
        self.assertEqual(counts["output_limit_without_eos_count"],1)
        self.assertEqual(counts["eos_at_limit_count"],1)

    def test_errors_are_not_counted_as_successful_or_complete_eos(self):
        rows = [{**self.metric,"max_new_tokens":128},
                {"max_new_tokens":128,"error":"generation failed"}]
        counts = aggregate(rows,2)["128"]
        self.assertEqual(counts["errors"],1)
        self.assertEqual(counts["successful_trials"],1)
        self.assertEqual(counts["stop_reasons"],{"eos_before_limit":1})

    def test_search_iterations_do_not_determine_selected_output_cap(self):
        row = {**self.metric,"max_new_tokens":128,"search_iterations":128}
        counts = aggregate([row],1)["128"]
        self.assertEqual(counts["output_limit_without_eos_count"],0)


if __name__ == "__main__":
    unittest.main()

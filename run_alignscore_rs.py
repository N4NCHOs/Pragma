#!/usr/bin/env python3
"""Score frozen RS summaries with the official AlignScore-large nli_sp metric.

Run with output/flan_evaluation/alignscore_runtime/venv/bin/python.
The inference-only adapter below preserves official checkpoint tensors and the
official Inferencer methods. Training-framework imports and unused spaCy setup
are omitted; the unused MLM projection is skipped after a forward-path check.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import types


OFFICIAL_COMMIT = "a0936d5afee642a46b22f6c02a163478447aa493"
CHECKPOINT_REVISION = "8509e78d25bb914939fc585c626500c9b2944249"
CHECKPOINT_SHA256 = "ff4336312b377edcbcdad5694a2d09d73dc4225422c0422d810aa7e78485e32d"
ROBERTA_REVISION = "722cf37b1afa9454edce342e7895e588b6ff1d59"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def load_official_module(name: str, path: Path, injected: dict, *, model=False):
    """Remove import-only training dependencies; retain official class methods."""
    tree = ast.parse(path.read_text())
    kept = []
    removed = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            aliases = [a for a in node.names if a.name not in {"pytorch_lightning", "spacy"}]
            if len(aliases) != len(node.names):
                removed.append(ast.get_source_segment(path.read_text(), node))
            if not aliases:
                continue
            node.names = aliases
        if isinstance(node, ast.ImportFrom):
            if node.module in {"sklearn.metrics", "model"}:
                removed.append(ast.get_source_segment(path.read_text(), node))
                continue
            if node.module == "transformers":
                aliases = [a for a in node.names if a.name != "AdamW"]
                if len(aliases) != len(node.names):
                    removed.append("from transformers import AdamW [training optimizer only]")
                node.names = aliases
        kept.append(node)
    tree.body = kept
    ast.fix_missing_locations(tree)
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__dict__.update(injected)
    sys.modules[name] = module
    exec(compile(tree, str(path), "exec"), module.__dict__)
    return module, removed


def build_scorer(runtime: Path, roberta_path: Path, threads: int, batch_size: int):
    import torch
    import torch.nn as nn
    from transformers import AutoConfig, AutoTokenizer

    torch.set_num_threads(threads)
    torch.manual_seed(0)

    class InferenceLightningShim(nn.Module):
        def save_hyperparameters(self, *args, **kwargs):
            # Official inference does not consult Lightning hparams/logging.
            pass

    model_path = runtime / "official/src/alignscore/model.py"
    infer_path = runtime / "official/src/alignscore/inference.py"
    model_module, model_removed = load_official_module(
        "_rs_alignscore_official_model", model_path,
        {"pl": types.SimpleNamespace(LightningModule=InferenceLightningShim),
         "AdamW": torch.optim.AdamW}, model=True,
    )
    # The config remains the pinned original RoBERTa-large architecture.
    # In Transformers 4.37.2 RoBERTa uses its original eager attention.
    model = model_module.BERTAlignModel(model=str(roberta_path), using_pretrained=False)
    attention_classes = sorted({type(x).__name__ for x in model.base_model.modules()
                                if "SelfAttention" in type(x).__name__})
    if attention_classes != ["RobertaSelfAttention"]:
        raise RuntimeError(f"Expected original eager attention, got {attention_classes}")

    checkpoint = torch.load(runtime / "AlignScore-large.ckpt", map_location="cpu",
                            mmap=True, weights_only=False)
    state = dict(checkpoint["state_dict"])
    expected = set(model.state_dict())
    unexpected = sorted(set(state) - expected)
    allowed_buffers = {"base_model.embeddings.position_ids", "base_model.embeddings.token_type_ids"}
    if not set(unexpected) <= allowed_buffers:
        raise RuntimeError(f"Unexpected checkpoint tensors: {unexpected}")
    buffer_audit = {}
    for key in unexpected:
        value = state.pop(key)
        wanted = (torch.arange(value.shape[-1]).expand_as(value) if key.endswith("position_ids")
                  else torch.zeros_like(value))
        if not torch.equal(value, wanted):
            raise RuntimeError(f"Nonstandard legacy buffer {key}")
        buffer_audit[key] = {"shape": list(value.shape), "verified_standard_value": True}
    missing = sorted(expected - set(state))
    if missing:
        raise RuntimeError(f"Missing official checkpoint tensors: {missing}")
    audit = model.load_state_dict(state, strict=True)
    for name, parameter in model.named_parameters():
        if name not in state or not torch.equal(parameter.detach(), state[name]):
            raise RuntimeError(f"Checkpoint tensor verification failed: {name}")
    weight_audit = {
        "load_state_dict_strict": True,
        "missing_keys": list(audit.missing_keys),
        "unexpected_keys": list(audit.unexpected_keys),
        "verified_parameter_tensors": len(list(model.named_parameters())),
        "verified_state_dict_tensors": len(state),
        "all_named_parameters_equal_checkpoint": True,
        "trained_pooler_loaded": all(k in state for k in ("base_model.pooler.dense.weight", "base_model.pooler.dense.bias")),
        "legacy_nonlearned_buffers": buffer_audit,
        "checkpoint_hyper_parameters": checkpoint.get("hyper_parameters"),
        "checkpoint_lightning_version": checkpoint.get("pytorch-lightning_version"),
    }
    del state, checkpoint
    model.eval()

    inference_module, inference_removed = load_official_module(
        "_rs_alignscore_official_inference", infer_path,
        {"BERTAlignModel": model_module.BERTAlignModel},
    )
    # Bypass only official __init__'s Lightning loader and unused spaCy setup.
    scorer = object.__new__(inference_module.Inferencer)
    scorer.device = "cpu"
    scorer.model = model
    scorer.batch_size = batch_size
    scorer.config = AutoConfig.from_pretrained(str(roberta_path), local_files_only=True)
    scorer.tokenizer = AutoTokenizer.from_pretrained(str(roberta_path), local_files_only=True)
    scorer.loss_fct = nn.CrossEntropyLoss(reduction="none")
    scorer.softmax = nn.Softmax(dim=-1)
    scorer.smart_type = "smart-n"
    scorer.smart_n_metric = "f1"
    scorer.disable_progress_bar_in_inference = True
    scorer.nlg_eval_mode = "nli_sp"
    scorer.verbose = False

    controls = {
        "context": "The company reported revenue of $10 million in 2025. Its chief executive is Alice Brown.",
        "supported_claim": "The company reported revenue of $10 million in 2025.",
        "contradictory_claim": "The company reported revenue of $100 million in 2024.",
    }
    batch = scorer.batch_tokenize([controls["context"]] * 2,
                                  [controls["supported_claim"], controls["contradictory_claim"]])[0]
    with torch.no_grad():
        official_output = model(batch)

    def classification_forward(self, encoded):
        encoded_out = self.base_model(
            input_ids=encoded["input_ids"], attention_mask=encoded["attention_mask"],
            token_type_ids=encoded.get("token_type_ids"),
        )
        return model_module.ModelOutput(
            seq_relationship_logits=self.bin_layer(self.dropout(encoded_out.pooler_output)),
            tri_label_logits=self.tri_layer(self.dropout(encoded_out.pooler_output)),
            reg_label_logits=self.reg_layer(encoded_out.pooler_output),
            hidden_states=encoded_out.hidden_states, attentions=encoded_out.attentions,
        )

    model.forward = types.MethodType(classification_forward, model)
    with torch.no_grad():
        adapted_output = model(batch)
    forward_check = {}
    for name in ("tri_label_logits", "seq_relationship_logits", "reg_label_logits"):
        original = getattr(official_output, name)
        adapted = getattr(adapted_output, name)
        difference = float((original - adapted).abs().max())
        if not torch.equal(original, adapted):
            raise RuntimeError(f"Official/adapted forward mismatch {name}: {difference}")
        forward_check[name] = {"bitwise_equal": True, "maximum_absolute_difference": difference}
    del official_output, adapted_output, batch
    controls["supported_score"] = scorer.inference_per_example(controls["context"], controls["supported_claim"])
    controls["contradictory_score"] = scorer.inference_per_example(controls["context"], controls["contradictory_claim"])
    controls["supported_greater_than_contradictory"] = controls["supported_score"] > controls["contradictory_score"]
    if not controls["supported_greater_than_contradictory"]:
        raise RuntimeError(f"Sanity control failed: {controls}")
    return scorer, {
        "weight_audit": weight_audit,
        "official_forward_comparison": forward_check,
        "sanity_controls": controls,
        "removed_imports": {"model": model_removed, "inference": inference_removed},
        "attention_classes": attention_classes,
        "tokenizer_class": type(scorer.tokenizer).__name__,
        "tokenizer_is_fast": scorer.tokenizer.is_fast,
        "tokenizer_model_max_length": scorer.tokenizer.model_max_length,
        "official_source_sha256": {str(p.relative_to(runtime)): digest(p) for p in (model_path, infer_path)},
    }


def pair_audit(scorer, context: str, claim: str):
    """Describe, without changing, the official 350-word/sentence chunk rule."""
    from nltk.tokenize import sent_tokenize
    source_sentences = sent_tokenize(context) or [""]
    claim_sentences = sent_tokenize(claim)
    if not claim_sentences:
        raise ValueError("A summary has no sentences")
    nominal_chunks = len(context.strip().split()) // 350 + 1
    sentences_per_chunk = max(len(source_sentences) // nominal_chunks, 1)
    chunks = [" ".join(source_sentences[i:i + sentences_per_chunk])
              for i in range(0, len(source_sentences), sentences_per_chunk)]
    lengths = [len(scorer.tokenizer(a, b, truncation=False)["input_ids"])
               for a in chunks for b in claim_sentences]
    return {
        "source_word_count": len(context.strip().split()),
        "source_sentence_count": len(source_sentences),
        "source_chunk_count": len(chunks),
        "claim_sentence_count": len(claim_sentences),
        "sentence_chunk_pairs": len(lengths),
        "sentence_chunk_pairs_over_model_limit": sum(n > scorer.tokenizer.model_max_length for n in lengths),
        "maximum_untruncated_pair_tokens": max(lengths),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, default=Path("output/flan_evaluation/alignscore_runtime"))
    parser.add_argument("--roberta", type=Path, default=Path.home() / ".cache/huggingface/hub/models--roberta-large/snapshots" / ROBERTA_REVISION)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=4)
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    os.environ["HF_HOME"] = str(runtime / "hf_home")
    os.environ["TRANSFORMERS_CACHE"] = str(runtime / "hf_home/hub")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["NLTK_DATA"] = str(runtime / "nltk_data")
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    output = args.input.resolve().parent
    rows = json.loads(args.input.read_text())
    keys = [(row["id"], row["prompt_condition"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate article-condition rows")
    unique = {}
    for row in rows:
        key = (row["id"], row["summary"])
        if key in unique and unique[key]["article_text"] != row["article_text"]:
            raise ValueError("Deduplication would combine different source contexts")
        unique.setdefault(key, row)
    commit = subprocess.check_output(["git", "-C", str(runtime / "official"), "rev-parse", "HEAD"], text=True).strip()
    if commit != OFFICIAL_COMMIT:
        raise RuntimeError(f"Official source revision changed: {commit}")
    print("Checking official checkpoint SHA256...", flush=True)
    ckpt_digest = digest(runtime / "AlignScore-large.ckpt")
    if ckpt_digest != CHECKPOINT_SHA256:
        raise RuntimeError(f"Checkpoint SHA256 mismatch: {ckpt_digest}")
    print("Loading official AlignScore-large weights and validating adapter...", flush=True)
    start = time.monotonic()
    scorer, details = build_scorer(runtime, args.roberta, args.threads, args.batch_size)
    report = {
        "status": "running", "metric": "AlignScore-large", "evaluation_mode": "nli_sp",
        "source_repository": "https://github.com/yuh-zha/AlignScore", "official_commit": commit,
        "checkpoint_url": f"https://huggingface.co/yzha/AlignScore/resolve/{CHECKPOINT_REVISION}/AlignScore-large.ckpt",
        "checkpoint_sha256": ckpt_digest, "checkpoint_revision": CHECKPOINT_REVISION,
        "roberta_revision": ROBERTA_REVISION, "roberta_path": str(args.roberta.resolve()),
        "input_sha256": digest(args.input), "input_row_count": len(rows), "unique_pair_count": len(unique),
        "context": "full frozen article_text (title + full body); no manual document truncation",
        "aggregation": "unchanged official Inferencer.inference_per_example: NLTK sentences, source chunks based on 350 whitespace words, max entailment over chunks per claim sentence, mean over claim sentences",
        "tokenization": "unchanged official batch_tokenize: model_max_length=512, only_first truncation with official fallback",
        "adapter": "Official model class loaded with nn.Module Lightning training shim and import compatibility changes; original full forward checked against classification-only forward; official Inferencer methods unchanged; unused spaCy initialization omitted",
        "device": "cpu", "dtype": "float32", "threads": args.threads, "batch_size": args.batch_size,
        "python": sys.version,
        "versions": {name: importlib.metadata.version(name) for name in ("torch", "transformers", "tokenizers", "numpy", "nltk", "huggingface-hub")},
        "punkt_tab_zip_sha256": digest(runtime / "punkt_tab.zip"),
        **details,
    }
    write_json(output / "alignscore_report.json", report)
    scored = {}
    audit_rows = []
    for i, (key, row) in enumerate(unique.items(), 1):
        before = time.monotonic()
        info = pair_audit(scorer, row["article_text"], row["summary"])
        score = scorer.inference_per_example(row["article_text"], row["summary"])
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise RuntimeError(f"Invalid AlignScore for article {row['id']}: {score}")
        scored[key] = score
        audit_rows.append({"id": row["id"], "source_index": row["source_index"],
                           "summary_sha256": hashlib.sha256(row["summary"].encode()).hexdigest(),
                           "alignscore": score, "seconds": time.monotonic() - before, **info})
        write_json(output / "alignscore_unique_pairs.json", audit_rows)
        print(f"AlignScore {i}/{len(unique)} article {row['source_index']}: {score:.6f}", flush=True)
    results = [{"id": row["id"], "source_index": row["source_index"],
                "prompt_condition": row["prompt_condition"],
                "alignscore": scored[(row["id"], row["summary"])],
                } for row in rows]
    write_json(output / "alignscore_scores.json", results)
    report.update(status="complete", elapsed_seconds=time.monotonic() - start,
                  completed_unique_pairs=len(audit_rows), completed_output_rows=len(results),
                  pairs_with_official_chunk_token_truncation=sum(x["sentence_chunk_pairs_over_model_limit"] > 0 for x in audit_rows),
                  sentence_chunk_pairs_total=sum(x["sentence_chunk_pairs"] for x in audit_rows),
                  sentence_chunk_pairs_over_model_limit_total=sum(x["sentence_chunk_pairs_over_model_limit"] for x in audit_rows))
    write_json(output / "alignscore_report.json", report)
    print(json.dumps({"status": "complete", "rows": len(results), "seconds": report["elapsed_seconds"]}), flush=True)


if __name__ == "__main__":
    main()

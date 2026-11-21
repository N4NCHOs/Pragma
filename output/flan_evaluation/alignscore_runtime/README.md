# AlignScore runtime for the RS prompt comparison

This directory isolates the factual-consistency metric from the production
project environment. The main `.venv` packages were not changed. The isolated
environment reads that environment's Torch and NLTK through
`main_venv_readonly.pth`, and overrides four compatible inference packages.

Official implementation: <https://github.com/yuh-zha/AlignScore>, commit
`a0936d5afee642a46b22f6c02a163478447aa493`.

Official large checkpoint: Hugging Face `yzha/AlignScore`, revision
`8509e78d25bb914939fc585c626500c9b2944249`, file `AlignScore-large.ckpt`.
Expected SHA256:
`ff4336312b377edcbcdad5694a2d09d73dc4225422c0422d810aa7e78485e32d`.
The checkpoint is approximately 4.90 GB because it contains training state.

## Compatibility and validation

The published package pins Torch <2, NumPy <2, and old PyTorch Lightning.
Python 3.12 and the project environment use newer versions. The worker
`run_alignscore_rs.py` therefore executes the original model and inference
source with an inference-only compatibility adapter:

- `pytorch_lightning.LightningModule` is replaced by `torch.nn.Module` plus a
  no-op training hyperparameter recorder. Training optimizer and sklearn imports
  are bypassed; they are not called during scoring.
- The exact original encoder, trained pooler, classifier heads, and MLM head
  are constructed, with RoBERTa eager attention. Every learned parameter must
  equal its official checkpoint tensor after a strict state load. Standard
  legacy position/token-type buffers, if present, are checked explicitly.
- On a fixed control batch, the unmodified official complete forward is
  executed. A classification-only forward must produce bitwise identical
  binary, three-way, and regression logits. Only then is its unused, expensive
  masked-language prediction projection omitted for the dataset scoring.
- The original `Inferencer` chunking, tokenization, classifier softmax, and
  maximum-then-mean aggregation methods execute unchanged from official source.
  Its constructor's unused spaCy initialization and Lightning checkpoint loader
  are bypassed. The `nli_sp` path actually uses NLTK `sent_tokenize`.

The full frozen `article_text` is supplied as context. The official algorithm
groups source sentences using its 350-whitespace-word rule and scores each
summary sentence against each source chunk. It takes the largest entailment
probability for each summary sentence, then averages those probabilities.
Its own tokenizer limits each chunk/sentence pair to 512 tokens, truncating the
source side. The audit records where this official truncation occurs.

The English `punkt_tab` resource comes from the official NLTK data repository:
<https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/tokenizers/punkt_tab.zip>.
Its actual downloaded SHA256 is recorded in the evaluation report.

## Reproduction

Run from the project root:

```sh
output/flan_evaluation/alignscore_runtime/venv/bin/python run_alignscore_rs.py \
  --input output/flan_evaluation/dual_reference_evaluation/run_20261101T153358_903997Z/evaluation_inputs.json \
  --threads 4 --batch-size 4
```

All model/tokenizer reads during scoring are offline. The existing cached
RoBERTa-large configuration and tokenizer are pinned to revision
`722cf37b1afa9454edce342e7895e588b6ff1d59`; base RoBERTa weights are not used
instead of the trained AlignScore weights.

The output report includes full dependency versions, source hashes, checkpoint
hash, strict weight audit, forward comparison, fixed supported/contradicted
controls, and source chunk/sentence counts. Identical article/summary pairs are
scored once and mapped to every original article/condition row.

AlignScore is an automated source-alignment proxy; its value is not the
percentage of facts proven correct. No universal pass/fail threshold is used.

# FLAN-T5 notebook results

Running `notebook/flan_t5.ipynb` writes the following files here:

- `flan_summaries.csv`: source articles, generated summaries, runtime/token
  measurements, and the human `reference_summary` column.
- `rouge_scores.csv`: per-article ROUGE-1, ROUGE-2, and ROUGE-L scores.
- `bertscore_scores.csv`: per-article BERTScore precision, recall, and F1.
- `evaluation_summary.csv`: aggregate means for the available evaluation metrics.

The generated CSV files are experimental artifacts. The human reference summaries
must be written from each article's real `full_body`; FLAN output must not be used as
its own reference.

# Referensi GPT dan evaluasi empat batas input FLAN

Workflow ini menyiapkan referensi GPT secara manual, lalu memasangkannya dengan hasil FLAN pada batas input **512, 1024, 2048, dan 3072**. Batas output FLAN tetap **64 token baru**. Model, prompt, artikel, dan referensi dibuat tetap agar perbandingan tidak berubah karena berita RSS baru.

## Status saat ini

- **Baseline dipertahankan (27 Oktober 2026):** pengguna meminta hasil saat ini
  dicatat sebelum perbaikan kode FLAN. Lihat
  [`FLAN_BASELINE_DISCOVERY_001.md`](FLAN_BASELINE_DISCOVERY_001.md), termasuk
  snapshot dan audit 12 keluaran yang mencapai batas 64 tanpa EOS. Percobaan
  perbaikan berikutnya harus menghasilkan run baru untuk dibandingkan dengan baseline.

- Paket memuat **73 kandidat**, termasuk **enam artikel pilot**. Artikel pilot tidak otomatis dikeluarkan.
- Ada **29 artikel dengan penanda perlu ditinjau**. Penanda bukan keputusan kelayakan; tidak adanya penanda juga tidak menjamin artikel lengkap.
- Seluruh **73 `reference_summary` sudah diisi oleh pengguna**. Pada 25 Oktober 2026, pengguna memilih memakai referensi tersebut apa adanya, tanpa menerapkan koreksi hasil review. Jangan mengedit atau membuat ulang referensinya secara otomatis.
- Pengguna sudah mengonfirmasi **semua 73 artikel tetap digunakan**, termasuk sepuluh sumber terbatas. `review_decision` sekarang `include` dengan catatan keputusan eksperimen, **bukan** sertifikasi audit kualitas manusia. Audit dan manifest sebelum perubahan dicadangkan di `as_is_decisions/20261025_all73/` dalam paket.
- Model GPT, tanggal pembuatan, dan reviewer belum dicatat; metadata tersebut tidak ditebak. Seluruh referensi dan penanda kualitas ekstraksi tetap sama.
- **Inferensi selesai: 292/292 trial, tanpa error**, pada folder `output/flan_evaluation/input_comparison/run_20261025_012611_as_is_39b89baf/`. Empat CSV masing-masing berisi 73 artikel dengan pasangan ID/referensi yang sama. **ROUGE dan BERTScore juga sudah selesai**, tanpa generation ulang, di subfolder `evaluation_results/scores_20261025_023043_e19f4b6b/`.
- Input terpotong pada 66/28/3/0 artikel untuk batas 512/1024/2048/3072. Ada 12 keluaran yang mencapai 64 token tanpa EOS; hasil mentah tidak diperbaiki atau dibuang. Keenam hasil pilot64 tereproduksi identik pada input 3072.
- Notebook kini menunjuk run selesai tersebut melalui `EXISTING_RUN_DIR`, dengan kedua switch tetap False sehingga pembukaan default tidak mengulang inferensi atau scoring. Ringkasan detail ada di [README run](output/flan_evaluation/input_comparison/run_20261025_012611_as_is_39b89baf/README.md).
- JSON sumber, scraper, database, pipeline produksi, serta CSV/hasil evaluasi lama tidak diubah oleh workflow ini.

### Hasil scoring yang sudah tersedia

Buka [rata-rata empat konfigurasi](output/flan_evaluation/input_comparison/run_20261025_012611_as_is_39b89baf/evaluation_results/scores_20261025_023043_e19f4b6b/input_limit_comparison.csv)
atau [README hasil](output/flan_evaluation/input_comparison/run_20261025_012611_as_is_39b89baf/evaluation_results/scores_20261025_023043_e19f4b6b/README.md).
Folder `input_512`, `input_1024`, `input_2048`, dan `input_3072` masing-masing
memuat `rouge_scores.csv` dan `bertscore_scores.csv`, 73 artikel per file.
Tidak perlu menjalankan model lagi untuk membaca hasil yang tersimpan.

2048 memiliki rata-rata ROUGE-1/L dan BERTScore F1 tertinggi yang teramati;
ROUGE-2 sama dengan 3072. Perbedaannya kecil dan hanya satu teks ringkasan
berubah antara 2048 dan 3072. Ini belum membuktikan perbedaan signifikan atau
konfigurasi terbaik secara umum. BERTScore mentah bukan persentase akurasi fakta.
Referensi tetap silver GPT, dengan keterbatasan yang sudah diterima pengguna.
Checkpoint berikutnya adalah review faktualitas/keterbacaan dari sumber serta
12 keluaran yang mencapai batas 64 token tanpa EOS, bukan mengubah baseline otomatis.

## File dan perannya

Paket kerja: [`notebook/evaluation_data/flan_reference_package_v1/`](notebook/evaluation_data/flan_reference_package_v1/).

| File | Peran dan bagian yang boleh diedit |
|---|---|
| [`gpt_reference_summaries.csv`](notebook/evaluation_data/flan_reference_package_v1/gpt_reference_summaries.csv) | Master referensi: `id,title,article_text,reference_summary`. Isi **hanya** `reference_summary`. |
| [`source_audit.csv`](notebook/evaluation_data/flan_reference_package_v1/source_audit.csv) | Tinjauan sumber. Isi `review_decision` dan `review_notes`; pertahankan field identitas/observasi. |
| [`prompt_template.txt`](notebook/evaluation_data/flan_reference_package_v1/prompt_template.txt) | Salinan persis prompt FLAN yang disepakati. Jangan ubah dalam paket ini. |
| [`prompts/`](notebook/evaluation_data/flan_reference_package_v1/prompts/) | 73 prompt siap salin, bernama `001_<id>.txt` dan seterusnya; setiap file sudah berisi artikel lengkap. |
| [`frozen_articles.json`](notebook/evaluation_data/flan_reference_package_v1/frozen_articles.json) | Sumber tetap, ID, judul, isi, penanda pilot, dan hash teks. Jangan diedit. |
| [`manifest.json`](notebook/evaluation_data/flan_reference_package_v1/manifest.json) | Konfigurasi/provenance paket. Lengkapi objek `reference_provenance`; jangan mengubah hash, sumber, prompt, atau konfigurasi eksperimen. |
| [`template_data.json`](notebook/evaluation_data/flan_reference_package_v1/template_data.json) | Snapshot internal saat template dibuat, **bukan** file kerja untuk memasukkan referensi. |

Implementasi dan pemeriksaan:

- [`flan_reference_workflow.py`](flan_reference_workflow.py): membuat paket baru tanpa menimpa paket lama, memvalidasi referensi/sumber, menjalankan empat konfigurasi ketika diminta, dan menggabungkan hasil berdasarkan ID. Import modul tidak memuat model atau mengakses database.
- [`notebook/flan_evaluation.ipynb`](notebook/flan_evaluation.ipynb): antarmuka notebook untuk validasi, generation opsional, serta sel ROUGE dan BERTScore terpisah. Output lama notebook sudah dikosongkan agar tidak terlihat sebagai hasil eksperimen ini.
- [`scratch/test_flan_reference_workflow.py`](scratch/test_flan_reference_workflow.py): pengujian offline untuk paket, validasi pasangan ID, dan integritas hasil. Pengujian bukan pengganti inferensi nyata atau penilaian kualitas ringkasan.

## 1. Tetapkan artikel yang digunakan

Buka `source_audit.csv` dan periksa `article_text` pada master referensi atau prompt terkait. Tentukan `review_decision` untuk **semua 73 baris**:

Untuk eksperimen as-is saat ini, pengguna sudah memilih `include` untuk semua
baris. Petunjuk berikut berlaku bila pengguna ingin membuat keputusan cohort
berbeda pada percobaan baru; jangan otomatis mengeluarkan sumber terbatas.

- `include`: sumber cukup informatif untuk tugas peringkasan.
- `exclude`: sumber tidak layak; tuliskan alasan pada `review_notes`, misalnya hanya cuplikan atau isi ekstraksi tidak sesuai judul.

Jangan mengeluarkan artikel hanya karena panjang, sulit, atau pernah digunakan sebagai pilot. Penanda kualitas membantu pemeriksaan, bukan otomatis menghapus artikel. Minimal satu artikel harus diikutkan.

Pertahankan semua baris pada kedua master CSV, termasuk artikel yang dikecualikan. Referensi artikel `exclude` boleh kosong. Urutan baris boleh berbeda karena penggabungan memakai **ID**, bukan posisi baris. Jangan mengganti ID atau mengurutkan satu kolom terpisah dari kolom lain.

## 2. Buat referensi di ChatGPT

Tahap pengisian sudah selesai untuk paket saat ini. Petunjuk berikut tetap
disimpan untuk dokumentasi metode atau paket baru; jangan membuat ulang 73
referensi yang sekarang telah diterima apa adanya oleh pengguna.

Untuk setiap artikel `include`:

1. Buka file terkait pada `prompts/` dan salin **seluruh isinya** ke ChatGPT. File sudah memuat prompt yang sama dengan FLAN dan `article_text = judul + ". " + full_body bersih` secara lengkap.
2. Jangan menunjukkan ringkasan FLAN. Referensi dibuat dari sumber, bukan memperbaiki jawaban FLAN.
3. Ikuti instruksi **1–2 kalimat** pada prompt. Jangan menambahkan batas numerik 64 token untuk GPT; tokenizer berbeda sehingga angka tersebut tidak menyamakan panjang teks antarmodel.
4. Periksa nama, angka, peristiwa, atribusi, ketidakpastian, dan ketiadaan klaim tambahan terhadap sumber.
5. Salin hanya ringkasan ke `reference_summary` pada **ID yang tepat** di `gpt_reference_summaries.csv`.

Gunakan model/prosedur GPT yang konsisten. Sebaiknya setiap permintaan tidak membawa diskusi atau keluaran FLAN dari percakapan sebelumnya. Satu referensi dipakai ulang untuk semua batas input; jangan membuat empat versi referensi.

Lengkapi `reference_provenance` pada `manifest.json`: `model` (nama model yang benar-benar digunakan), `generated_at` (tanggal/rentang pembuatan), `reviewer`, dan `notes` (prosedur, koreksi manual, atau variasi yang terjadi). Jangan mengarang versi model yang tidak ditampilkan aplikasi.

Referensi ini tetap disebut **AI-generated silver reference**, bukan ringkasan manusia/gold standard. Jika dikoreksi manusia, catat koreksinya; kesepakatan ROUGE/BERTScore tidak membuktikan seluruh fakta benar.

CSV memuat teks panjang dan mungkin baris baru di dalam satu field. Gunakan editor CSV/spreadsheet yang mempertahankan format CSV UTF-8; jangan menambahkan pemisah koma secara manual. Jangan mengubah judul atau `article_text`.

## 3. Periksa kesiapan

Dari root proyek, gunakan environment proyek:

```bash
python flan_reference_workflow.py --check
```

Selama keputusan belum lengkap atau referensi artikel `include` masih kosong, status **Not ready** adalah normal. Perbaiki file kerja, kemudian periksa lagi. Pemeriksaan juga menolak ID hilang/duplikat/tambahan serta perubahan sumber atau judul; tidak ada artikel yang diam-diam dilewati.

Jangan menjalankan perintah tanpa `--check` untuk mencoba melanjutkan pengisian: mode tersebut membuat paket baru dan akan menolak menimpa paket yang sudah ada.

## 4. Jalankan empat konfigurasi melalui notebook

Buka `notebook/flan_evaluation.ipynb`. Dependensi dipasang manual sesuai petunjuk awal notebook; tidak ada sel instalasi otomatis.

1. Periksa `PACKAGE_DIR`. Default mengarah ke paket di atas. `REFERENCE_CSV` dan `AUDIT_CSV` boleh tetap `None` untuk memakai file default paket.
2. Biarkan `EXISTING_RUN_DIR = None` untuk percobaan baru.
3. Setelah pemeriksaan siap, ubah **`RUN_GENERATION = True`**, lalu jalankan sel konfigurasi, readiness, generation, dan load/validasi.
4. Tunggu semua artikel pada keempat batas selesai. Tokenizer/model pretrained dimuat sekali untuk satu run, menggunakan checkpoint/revisi lokal yang dicatat paket.

Konfigurasi FLAN: `google/flan-t5-base`, `do_sample=False`, `num_beams=4`, `max_new_tokens=64`, `early_stopping=True`, dan `no_repeat_ngram_size=3`. Tidak ada fine-tuning atau perubahan konfigurasi produksi.

Runner memakai revisi lokal `7bcac572ce56db69c1ea7c8af255c5d7c9672fc2` dengan `local_files_only=True`. Jika cache model/tokenizer tidak tersedia di environment lain, generation akan gagal dengan jelas, bukan mengunduh atau mengganti checkpoint diam-diam.

Folder hasil baru, tanpa menimpa run sebelumnya:

```text
output/flan_evaluation/input_comparison/run_<waktu>_<id>/
  flan_512.csv
  flan_1024.csv
  flan_2048.csv
  flan_3072.csv
  selected_articles.json
  prompt_template.txt
  generation_metrics.json
  run_manifest.json
```

Keempat CSV memiliki tepat kolom `id,title,summary,reference_summary` dan cohort/referensi yang sama. `generation_metrics.json` menyimpan pengukuran/truncation dan masalah generation; `run_manifest.json` mencatat status serta konfigurasi. Jika generation gagal, hasil parsial/error dipertahankan dan tidak diterbitkan sebagai empat CSV perbandingan lengkap.

**Batas input menghitung seluruh prompt tokenisasi**, termasuk instruksi, judul, isi, dan token khusus. Sesuai service saat ini, truncation kanan pada seluruh prompt dapat menghapus penanda akhir `Summary:`. Perilaku ini tidak diam-diam diperbaiki di eksperimen; artinya hasil mencerminkan konfigurasi truncation tersebut juga.

Jika prompt/kode FLAN berubah setelah paket dibuat, generation akan meminta review/refreeze. Buat versi paket baru secara eksplisit; jangan mengubah hash agar pemeriksaan lolos.

## 5. Hitung ROUGE dan BERTScore secara terpisah

Setelah keempat CSV lengkap dan valid:

1. Untuk membuka hasil tersimpan tanpa generation ulang, set `RUN_GENERATION = False` dan isi `EXISTING_RUN_DIR` dengan folder run yang benar.
2. Set **`RUN_SCORING = True`**, jalankan kembali konfigurasi, pemilihan run, dan load/validasi.
3. Jalankan sel **ROUGE**, sel **BERTScore**, lalu sel ekspor. Keduanya dapat diperiksa terpisah.

ROUGE menghitung F1 `rouge1`, `rouge2`, `rougeL` dengan stemming. BERTScore memakai `roberta-large`, bahasa Inggris, CPU, batch 4, `idf=False`, dan tanpa baseline rescaling; hash konfigurasi ikut disimpan. BERTScore dapat perlu mengunduh model ketika dijalankan di environment lain. Eksekusi yang selesai ini memakai cache lokal secara offline, layer 17 dan revisi yang tercatat di `scoring_report.json`; tidak ada input scoring yang terpotong.

Ekspor baru berada di:

```text
<folder_run>/evaluation_results/scores_<waktu>_<id>/
  input_512/rouge_scores.csv
  input_512/bertscore_scores.csv
  input_512/bertscore_config.txt
  input_1024/...
  input_2048/...
  input_3072/...
  input_limit_comparison.csv
```

Skor per artikel dan rata-rata tersimpan tanpa pembulatan; pembulatan hanya untuk tampilan. Tetap lakukan review faktualitas dan keterbacaan. Dokumentasikan bahwa enam pilot pernah digunakan untuk pemilihan batas output.

## Batasan dan prioritas selanjutnya

- Paket memakai **snapshot tetap 73 kandidat**, bukan membaca RSS terbaru yang terus bertambah. Kandidat baru tidak otomatis masuk; gunakan paket versi baru bila ingin mengubah sumber/cohort.
- Kedua switch notebook default **False**. `Run All` pada keadaan default tidak menjalankan FLAN atau model scoring, meskipun referensi sudah diisi.
- Tidak ada pemanggilan GPT API atau pembuatan referensi otomatis pada workflow ini.
- Hasil lama di `notebook/evaluation_data/` dan folder evaluasi lain tidak digabungkan atau ditimpa.
- **PRIORITAS TINGGI — PENDING:** hubungkan fungsi reusable [`article_preprocessing.py`](article_preprocessing.py) ke alur realtime yang dipakai `main_pipeline`. Pembersihan salinan evaluasi **bukan** integrasi produksi. Lihat [`FLAN_PREPROCESSING_README.md`](FLAN_PREPROCESSING_README.md).

Checkpoint penelitian dan alasan baseline output: [`FLAN_EVALUATION_PLAN.md`](FLAN_EVALUATION_PLAN.md) dan [`FLAN_64_TOKEN_JUSTIFICATION_README.md`](FLAN_64_TOKEN_JUSTIFICATION_README.md).

## Validasi tahap persiapan

- **175 pengujian offline lulus**, termasuk 50 pengujian workflow referensi. Simulasi model memeriksa satu kali loading, empat batas input, pasangan referensi, dan penyimpanan error; ini bukan inferensi FLAN nyata.
- Seluruh 73 ID, judul, dan teks dapat dibaca kembali dari CSV tanpa perubahan; 73 prompt cocok persis dengan template dan sumber tetap. Hash kode FLAN/snapshot awal tetap sama.
- Ketujuh sel kode notebook dapat dikompilasi. Eksekusi default diuji dari root proyek maupun folder notebook dengan import model/scoring/database diblokir; tidak ada tahap mahal yang terpanggil.
- Saat persiapan awal, `--check` berhenti karena 73 keputusan sumber masih pending. Setelah pengguna memilih semua artikel as-is, validasi normal lolos untuk 73 artikel. Empat CSV generasi dan sembilan CSV scoring kini selesai serta terverifikasi; master referensi dan kode FLAN tidak diubah.
- Graph kode diperbarui melalui `graphify update .`; ekstraksi SQL dilewati karena dependency `tree_sitter_sql` belum tersedia, tanpa memasang dependency atau melakukan panggilan LLM.

Pengujian workflow saja:

```bash
python -m unittest scratch.test_flan_reference_workflow -q
```

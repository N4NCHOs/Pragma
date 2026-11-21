# Pilot batas output FLAN-T5

## Tujuan dan batas pekerjaan

`run_flan_output_pilot.py` membandingkan batas output `max_new_tokens = 64`, `96`, dan `128` pada enam artikel nyata yang sudah dibekukan. Tujuannya adalah memeriksa apakah batas output memotong hasil model sebelum eksperimen batas input 512/1024/2048/3072 dilakukan.

Enam artikel, urutan, teks, judul, prompt, checkpoint, dan parameter lain tetap sama. Hanya `max_new_tokens` yang berubah, sehingga total rencana pengujian adalah **6 artikel × 3 batas output = 18 trial**. Ini adalah eksperimen inferensi pretrained, bukan fine-tuning.

Tidak ada perubahan pada `main_pipeline.py`, scheduler RSS, preprocessing produksi, model FLAN produksi, atau database. Integrasi pembersihan footer ke pemrosesan realtime tetap **prioritas tinggi, tetapi belum diterapkan**. Lihat `FLAN_PREPROCESSING_README.md` untuk aturan dan rencana integrasinya.

## Sumber yang digunakan

Pilot menggunakan hasil preflight yang sudah tetap:

```text
output/flan_evaluation/pilot_tokens_v1_20261024/
├── token_report.json
├── pilot_inputs.json
└── prompt_template.txt
```

Input adalah gabungan judul dan `full_body` bersih dari snapshot evaluasi, dengan format yang sama seperti layanan FLAN: `title + ". " + full_body`, kemudian dimasukkan ke template prompt yang dibekukan. Program memeriksa hash prompt, dataset, teks input, urutan ID, serta baseline sumber `ai_models/flan_t5.py`. Jika baseline berubah sejak preflight, program berhenti agar eksperimen tidak diam-diam memakai kondisi berbeda.

Jumlah token input lengkap berikut mencakup **prompt, judul, badan artikel, dan token khusus**, bukan hanya badan artikel:

| Artikel | Token input lengkap |
|---|---:|
| Bitcoin ETF / BlackRock | 597 |
| Pendanaan Tether untuk Mural | 627 |
| Penundaan pengujian Ethereum Glamsterdam | 931 |
| Rencana settlement Ethereum empat menit | 987 |
| Bitcoin dan terobosan kuantum Google Willow | 1.508 |
| Aturan OCC dan imbalan stablecoin | 2.071 |

Batas input pilot ditetapkan **3.072 token**, sehingga keenam input masuk tanpa truncation. Ini mengisolasi pemeriksaan output dari kehilangan input. Program juga memeriksa ulang jumlah token yang benar-benar dikonsumsi terhadap preflight sebelum menjalankan trial. Batas ini bukan pernyataan bahwa seluruh dataset pasti muat pada 3.072 token atau bahwa kualitas input panjang sudah terbukti baik.

## Model dan parameter

| Pengaturan | Nilai pilot |
|---|---|
| Checkpoint | `google/flan-t5-base` |
| Revisi cache | `7bcac572ce56db69c1ea7c8af255c5d7c9672fc2` |
| `max_input_tokens` | `3072`, tanpa pemotongan pada enam input pilot |
| `max_new_tokens` | `64`, `96`, `128` |
| `do_sample` | `False` |
| `num_beams` | `4` |
| `early_stopping` | `True` |
| `no_repeat_ngram_size` | `3` |
| Seed | `0` |
| Prompt | Salinan persis prompt yang disetujui dan dibekukan pada preflight |

Tidak ada sampling acak. Empat beam digunakan untuk pencarian kandidat output dengan baseline yang sama. Ini membantu perbandingan terkontrol pada environment yang sama, tetapi bukan jaminan hasil bit-identik di semua perangkat atau versi pustaka.

Tokenizer dan model dimuat **sekali**, lalu digunakan untuk semua trial. Model berada pada mode evaluasi dan generation dijalankan dalam `torch.inference_mode()`. File dibaca hanya dari cache lokal dengan `local_files_only=True`; script tidak mengunduh model, memanggil API berbayar, atau menghubungi database.

Run awal menggunakan CPU karena CUDA dan MPS tidak tersedia pada environment yang menjalankan pilot. Pilihan perangkat dicatat dalam laporan, bersama versi PyTorch/Transformers, dtype model, jumlah thread CPU, dan generation config. Permintaan eksplisit untuk perangkat yang tidak tersedia menghasilkan error, bukan pengalihan perangkat diam-diam.

`model_generation_config` pada laporan berisi default dari checkpoint. Untuk kondisi trial yang sebenarnya, baca bersama `fixed_generation_kwargs` dan `max_new_tokens` pada setiap baris hasil; nilai eksplisit trial menggantikan default model tersebut.

## Cara menjalankan

Jalankan dari root proyek. Contoh menggunakan environment proyek dan folder output baru:

```bash
.venv/bin/python run_flan_output_pilot.py --device cpu --output-dir output/flan_evaluation/output_pilot_v2
```

Sumber preflight default adalah `output/flan_evaluation/pilot_tokens_v1_20261024`. Untuk memilih snapshot preflight lain secara eksplisit:

```bash
.venv/bin/python run_flan_output_pilot.py --preflight-dir output/flan_evaluation/pilot_tokens_v1_20261024 --device cpu --output-dir output/flan_evaluation/output_pilot_v3
```

Jika `--output-dir` tidak diberikan, folder baru bertimestamp dibuat di `output/flan_evaluation/`. Folder yang sudah ada selalu ditolak untuk melindungi hasil lama. Script belum memiliki fitur resume; bila run terhenti, hasil trial yang sudah tersimpan tetap dapat diperiksa, tetapi pengulangan harus memakai folder baru dan akan menjalankan ulang pilot dari awal.

## Hasil yang disimpan

Run awal ditempatkan pada:

```text
output/flan_evaluation/output_pilot_v1_20261024/
├── pilot_inputs.json
├── prompt_template.txt
├── preflight_report.json
├── results.json
├── run_report.json
└── review.md
```

Pada pemeriksaan 24 Oktober 2026, run awal memiliki status `complete` dengan 18/18 trial tersimpan pada CPU. Ini adalah penyelesaian teknis; penetapan batas output dan kesimpulan kualitas tetap menunggu review sumber serta hasil.

| File | Isi |
|---|---|
| `pilot_inputs.json` | Salinan enam record, teks artikel gabungan, dan input lengkap yang diberikan kepada tokenizer. |
| `prompt_template.txt` | Prompt tetap untuk run ini. |
| `preflight_report.json` | Salinan laporan token sumber sebagai jejak pemeriksaan input. |
| `results.json` | Hasil per trial: identitas artikel, ringkasan, token, waktu inferensi, penghentian, serta error bila ada. |
| `run_report.json` | Konfigurasi, environment, hash, status kemajuan, jumlah trial, dan agregasi per batas output. |
| `review.md` | Review sumber berbantuan AI yang ditambahkan setelah run: cakupan, jargon, penyalinan kalimat, dan batasan interpretasi. Bukan skor otomatis atau penilaian manusia independen. |

`results.json` dan `run_report.json` diperbarui setelah setiap trial. Laporan memiliki status `running`, `complete`, `completed_with_errors`, `interrupted`, atau `failed`. Saat proses masih berjalan, hasil dan rerata yang terlihat masih parsial. Status `complete` berarti seluruh trial selesai tanpa error teknis yang tercatat, **bukan** berarti ringkasan telah lolos penilaian kualitas.

Penulisan ulang kedua file dilakukan terpisah. Jika proses berhenti tepat di antara pembaruan, hitungan pada laporan dan panjang daftar hasil mungkin perlu dicocokkan secara manual. Jangan menyimpulkan bahwa hasil parsial sudah merupakan perbandingan lengkap 18 trial.

## Cara membaca jumlah token dan alasan berhenti

Ada dua hitungan berbeda:

- `generated_new_tokens_including_eos`: jumlah token baru pada urutan output yang terpilih, termasuk EOS bila dihasilkan. Token awal decoder tidak dihitung. Ini yang dibandingkan terhadap `max_new_tokens`.
- `output_token_count`: token isi pada urutan terpilih, setelah seluruh token khusus dikecualikan. Karena itu nilainya dapat lebih kecil daripada hitungan di atas.

Pada beam search, urutan hasil dapat mengandung filler dari buffer setelah urutan terpilih berakhir. Runner memakai `beam_indices` untuk memperoleh panjang urutan yang valid, bukan menghitung seluruh buffer sebagai output baru. `search_iterations` mencatat jumlah langkah pencarian global; jangan menganggapnya selalu sama dengan panjang urutan akhir yang terpilih.

| `stop_reason` | Makna |
|---|---|
| `eos_before_limit` | Urutan terpilih menghasilkan EOS sebelum mencapai batas output. |
| `eos_at_limit` | EOS muncul tepat pada batas; tidak cukup untuk menyimpulkan apakah batas tersebut membatasi kelengkapan bahasa. |
| `length_limit_without_eos` | Batas tercapai tanpa EOS; perlu memeriksa kemungkinan output terpotong. |
| `unexpected_stop` | Berhenti tanpa EOS sebelum batas; perlu pemeriksaan teknis. |
| `forced_eos_at_limit` | Kategori yang disediakan pemeriksa urutan; runner saat ini menolak config forced EOS sebelum pilot agar tidak membingungkan interpretasi. |

EOS bukan bukti ringkasan lengkap, benar, atau sesuai 1–2 kalimat. Sebaliknya, mencapai batas token juga bukan bukti pasti kalimat terpotong. Field `ends_with_sentence_punctuation` hanya pemeriksaan tanda baca, bukan penilaian kualitas. Tetap bandingkan ringkasan dengan sumber untuk memeriksa fakta, atribusi, ketidakpastian, angka penting, jargon, dan kelengkapan main event.

## Waktu inferensi

Sebelum trial, ada satu warmup dengan batas output satu token. Output warmup sengaja sangat pendek, tidak disimpan sebagai ringkasan pilot, dan tidak dimasukkan ke rerata trial. Waktunya dicatat terpisah.

`inference_seconds` mengukur generation per trial, bukan pemuatan model atau tokenisasi. Setiap pasangan artikel/batas hanya dijalankan sekali secara serial. Karena itu rerata waktunya merupakan pengamatan praktis pada run ini, **bukan benchmark latensi** yang telah mengendalikan variasi sistem, pemanasan berulang, atau urutan trial.

## Peringatan pustaka yang teramati

Saat model dimuat pada environment ini, Transformers menampilkan peringatan bahwa bobot `shared.weight` dan `lm_head.weight` yang diperlakukan sebagai terkait memiliki nilai berbeda; perilaku pustaka yang terpasang mempertahankannya tidak terikat (*untied*).

Tidak ada perubahan config atau modifikasi bobot yang dilakukan untuk menyembunyikan atau memperbaiki peringatan tersebut. Ini dicatat sebagai peringatan pemuatan model/pustaka yang memerlukan investigasi terpisah jika diperlukan. Catatan ini tidak membuktikan bahwa kualitas pasti terganggu ataupun pasti tidak terpengaruh. Gunakan informasi versi dan generation config pada laporan untuk reproduksi, dan jangan menyamakan hasil ini otomatis dengan environment pustaka lain.

## Pengujian helper pilot

```bash
.venv/bin/python -m unittest scratch.test_flan_output_pilot -v
```

Pengujian helper memakai fixture untuk memeriksa pembacaan snapshot, interpretasi urutan/EOS, dan agregasi. Fixture bukan pengganti enam trial pada model nyata dan bukan pengukuran kualitas ringkasan.

## Checkpoint berikutnya

Justifikasi khusus untuk penggunaan batas 64, termasuk tabel bukti dan contoh
jawaban/paragraf skripsi, tersedia di
[FLAN_64_TOKEN_JUSTIFICATION_README.md](FLAN_64_TOKEN_JUSTIFICATION_README.md).

Run pertama sudah ditinjau terhadap sumber: seluruh output berhenti dengan EOS sebelum ceiling, dengan 25–42 token isi; setiap artikel menghasilkan teks identik pada 64/96/128. Semua enam ringkasan merupakan salinan kalimat persis dari sumber. Beberapa tidak menjelaskan jargon atau kehilangan konteks utama, sehingga tidak terpotong bukan berarti sudah memenuhi tujuan abstraksi/keterbacaan pemula. Lihat `review.md` untuk tiap artikel.

Rekomendasi sementara adalah mempertahankan 64 sebagai baseline karena ceiling lebih tinggi tidak mengubah hasil pada pilot ini. Ini belum mengunci batas output untuk penelitian atau membuktikan 64 optimal pada artikel lain. Pengguna perlu menyetujui keputusan tersebut dan menilai apakah baseline prompt ini akan dipertahankan sebelum eksperimen utama. **Dokumen ini tidak mengubah prompt atau mengunci konfigurasi produksi.**

199 tes offline lolos, termasuk 46 tes helper pilot baru. Hasil trial model nyata diverifikasi terpisah; pengujian helper bukan sumber angka kualitas.

Pilot ini belum membuat referensi ChatGPT/*silver reference*, belum menghitung ROUGE atau BERTScore, dan belum menjalankan perbandingan batas input 512/1024/2048/3072. Semua itu merupakan checkpoint terpisah setelah keputusan batas output dan pemeriksaan data disetujui.

# Evaluasi FLAN: empat batas input, 73 artikel as-is

Scoring selesai pada **25 Oktober 2026 (Asia/Jakarta)**. Semua 73 artikel,
termasuk enam artikel pilot dan sepuluh sumber deskripsi/navigasi terbatas,
dipertahankan sesuai keputusan pengguna. Referensi GPT yang sama dipakai untuk
keempat batas input, tanpa koreksi atau pembuatan ulang. FLAN tidak dijalankan
ulang pada tahap scoring ini.

## Hasil rata-rata

Nilai tabel dibulatkan untuk dibaca. CSV menyimpan seluruh presisi hasil hitung.
Setiap konfigurasi memiliki 73 pasangan ringkasan–referensi.

| Batas input total | ROUGE-1 F1 | ROUGE-2 F1 | ROUGE-L F1 | BERTScore P | BERTScore R | BERTScore F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 512 | 0.3212 | 0.1326 | 0.2517 | 0.9050 | 0.8627 | 0.8832 |
| 1024 | 0.3344 | 0.1464 | 0.2600 | 0.9031 | 0.8644 | 0.8831 |
| 2048 | 0.3442 | 0.1472 | 0.2677 | 0.9052 | 0.8663 | 0.8852 |
| 3072 | 0.3428 | 0.1472 | 0.2672 | 0.9044 | 0.8661 | 0.8847 |

2048 menghasilkan rata-rata ROUGE-1/L dan BERTScore F1 tertinggi yang teramati;
ROUGE-2 sama dengan 3072. Dibandingkan 512, selisih 2048 adalah sekitar +0.0230
ROUGE-1, +0.0160 ROUGE-L, dan +0.00194 BERTScore F1. Ini selisih skor absolut,
bukan perubahan persentase akurasi. 1024 menaikkan ROUGE dibandingkan 512, tetapi
BERTScore F1 sedikit lebih rendah: peningkatan input tidak selalu menaikkan
setiap metrik.

**Hanya satu teks ringkasan berbeda antara 2048 dan 3072**, yaitu artikel
`693e7beea61cd374ca049023e480067517f37aa8160f296ce97aef153dcc3deb`, berjudul
“Crypto for Advisors: Stablecoins are ready for prime time”. Pada 3072, model
menghasilkan pengantar/promosi newsletter, sedangkan pada 2048 model menyalin
bagian pembahasan stablecoin. Ini contoh kegagalan pemilihan isi pada satu kasus,
bukan bukti bahwa konteks lebih panjang selalu lebih buruk. Periksa sumber dan
ringkasan mentah dalam run induk. Ada perbedaan numerik BERTScore sekitar 1e-7
pada satu pasangan yang teksnya sama; jangan menafsirkannya sebagai perbedaan
kualitas.

Belum dilakukan uji signifikansi, confidence interval, atau review manual
faktualitas/keterbacaan. Jangan menyimpulkan 2048 optimal secara umum atau
mengubah konfigurasi produksi otomatis dari tabel ini.

## Cara membaca metrik

- **ROUGE-1:** kesamaan kata dengan referensi.
- **ROUGE-2:** kesamaan pasangan kata berurutan.
- **ROUGE-L:** kesamaan urutan kata berdasarkan longest common subsequence.
- **BERTScore precision:** kecocokan semantik token ringkasan terhadap referensi.
- **BERTScore recall:** cakupan token referensi oleh ringkasan.
- **BERTScore F1:** gabungan precision dan recall.

Semua mengukur kesepakatan terhadap **AI-generated silver references GPT**,
bukan kebenaran terhadap berita asli. BERTScore **0.8852 bukan berarti 88.52%
akurasi fakta**. Metrik tidak mengesahkan bahasa ramah pemula, ketepatan angka,
ketiadaan nasihat investasi, atau kelengkapan kalimat. Penilaian tersebut harus
memeriksa sumber secara langsung. Referensi yang lebih panjang dapat memengaruhi
recall; tidak ada pemaksaan panjang token sama antara GPT dan FLAN.

## File hasil

- `input_limit_comparison.csv`: empat baris rata-rata, jumlah artikel, tiga
  ROUGE F1, serta BERTScore precision/recall/F1.
- `input_512/`, `input_1024/`, `input_2048/`, `input_3072/`: masing-masing memuat
  `rouge_scores.csv`, `bertscore_scores.csv`, dan `bertscore_config.txt`.
- `scoring_report.json`: protokol, revisi model evaluator, versi dependensi,
  hash input/output, hasil rata-rata, dan catatan validasi.

Skema per-artikel ROUGE:
`id,title,rouge1_f1,rouge2_f1,rougeL_f1`.

Skema per-artikel BERTScore:
`id,title,bertscore_precision,bertscore_recall,bertscore_f1`.

Gunakan `id` untuk menggabungkan skor dengan `flan_<batas>.csv` di run induk;
file tersebut tetap memiliki `id,title,summary,reference_summary`. Jangan
menggabungkan berdasarkan judul atau mengurutkan satu kolom secara terpisah.

## Protokol yang benar-benar dijalankan

Scoring memakai kode sel ROUGE dan BERTScore notebook
`notebook/flan_evaluation.ipynb` tanpa perubahan. `RUN_SCORING=True` hanya pada
eksekusi di memori; file notebook tetap menyimpan kedua switch **False**.
Tidak ada pengunduhan model, panggilan GPT API, atau generation ulang FLAN.
Sel ekspor notebook tidak dijalankan pada eksekusi ini; sembilan CSV diekspor
dengan skema yang sama melalui pembacaan nilai sel Artifact Tool yang
terverifikasi persis. Format CSV UTF-8 BOM, seluruh field diapit tanda kutip,
dan akhir baris CRLF; format tampilan tidak membulatkan nilai tersimpan.

**ROUGE:** `rouge-score==0.1.2`, `RougeScorer` dengan
`[rouge1, rouge2, rougeL]`, `use_stemmer=True`; target=referensi,
prediction=ringkasan FLAN; agregasi rata-rata F1 per artikel, bukan bootstrap
atau penggabungan seluruh artikel menjadi satu teks.

**BERTScore:** distribusi `bert-score==0.3.13`, `roberta-large`, layer 17,
`lang=en`, `device=cpu`, `batch_size=4`, `idf=False`,
`rescale_with_baseline=False`, `all_layers=False`, tokenizer lambat
`RobertaTokenizer` (`use_fast_tokenizer=False`). Revisi cache lokal:
`722cf37b1afa9454edce342e7895e588b6ff1d59`. Cache diperiksa sebelum/sesudah
scoring; seluruh eksekusi offline. CPU empat thread, seed 0.

Hash yang dikembalikan pustaka, sama pada keempat konfigurasi:
`roberta-large_L17_no-idf_version=0.3.12(hug_trans=5.14.1)`.
Versi internal paket masih melaporkan 0.3.12 meskipun metadata distribusi
terpasang 0.3.13; keduanya dicatat apa adanya. Hash ini sendiri tidak merekam
revisi checkpoint; revisi dicatat terpisah di atas dan dalam JSON laporan.

Dependensi lain: Transformers 5.14.1, Torch 2.13.0, pandas 3.0.5,
NLTK 3.10.3. Evaluator memproses maksimal 67 token kandidat dan 99 token
referensi (tokenizer RoBERTa, termasuk token khusus), di bawah batas 512;
**tidak ada input evaluator yang terpotong**. Ini berbeda dari batas input
artikel untuk FLAN.

Rata-rata BERTScore mempertahankan perilaku notebook pada kolom float32.
Perhitungan ulang float64 dari CSV dapat berbeda hingga `1.405e-7`; ini efek
presisi agregasi, bukan pembulatan CSV. Semua nilai per artikel dibaca kembali
persis sama dengan hasil komputasi. Waktu scoring sekitar 19.77 detik termasuk
sel persiapan, tidak termasuk ekspor/QA; bukan benchmark latency.

Loader RoBERTa melaporkan bobot head bahasa tidak terpakai dan bobot pooler baru.
BERTScore menggunakan representasi token, bukan pooler/head tersebut. Tidak
ada fine-tuning atau penggantian checkpoint untuk menghilangkan peringatan.

## Batasan eksperimen yang dipertahankan

- Semua 73 artikel dipakai atas keputusan pengguna, bukan sertifikasi bahwa
  sumber lengkap. Ada 29 penanda kualitas sumber, termasuk sepuluh sumber
  deskripsi/navigasi terbatas; tidak ada pengecualian diam-diam.
- Temuan audit referensi artikel 16, 18, 48, dan 58 tetap diterima apa adanya.
  Nama model GPT, tanggal generasi, dan reviewer belum tercatat; tidak ditebak.
- Enam pilot ikut dilaporkan, sehingga cohort bukan held-out test yang sepenuhnya
  independen dari pemilihan batas output.
- FLAN memakai output maksimum 64 token baru di semua konfigurasi. Ada 12 dari
  292 keluaran mencapai batas tanpa EOS (4/2/3/3 pada input 512/1024/2048/3072),
  mencakup lima artikel. Beberapa berakhir tidak lengkap; semuanya tetap dinilai.
- Input FLAN terpotong pada 66/28/3/0 artikel. Truncation kanan seluruh prompt
  dapat menghapus penanda `Summary:`. Perbandingan ini mencerminkan perilaku
  implementasi tersebut, bukan hanya jumlah informasi artikel.
- Model FLAN pretrained dan konfigurasi produksi tidak diubah; lihat README run
  induk untuk revisi dan pengaturan generation lengkap.

## Pemeriksaan dan langkah berikutnya

Sembilan CSV lolos pemeriksaan skema, semua ID/judul/urutan, angka finite,
nilai hasil komputasi persis, jumlah baris, dan rata-rata. Pemeriksaan independen
mengonfirmasi hasil yang sama. Empat CSV generation, sumber tetap, kode FLAN,
dan master referensi tidak berubah. SHA-256 master referensi tetap:
`071492b220b2f0a394300a101a4b549b58f24cae27594f4760e177ceaae9ba06`.
Seluruh 175 pengujian offline lulus. Notebook default aman diuji dari root
proyek dan folder notebook tanpa import model generation/scoring/database.
Preview kesembilan dataset juga diperiksa untuk keterbacaan.

Selanjutnya, review ringkasan terhadap sumber, terutama keluaran yang mencapai
64 token dan artikel newsletter di atas, sebelum menyimpulkan pilihan input.
Jangan mengubah referensi atau budget di tengah hasil ini; percobaan perbaikan
memerlukan run baru dengan variabel yang dikontrol.

Tidak ada perubahan ke scraper, database, cryptoNER, DeBERTa, atau main_pipeline.
**PRIORITAS TINGGI — PENDING:** integrasi `article_preprocessing.py` ke realtime
`main_pipeline` tetap belum dilakukan dan tidak termasuk tahap scoring ini.

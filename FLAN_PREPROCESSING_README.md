# Pembersihan footer untuk evaluasi FLAN-T5

## Tujuan dan status

Tahap ini membuang satu footer nonartikel yang sudah dikenali dari akhir `full_body`, lalu membuat salinan dataset yang dapat dipakai secara konsisten untuk eksperimen FLAN-T5.

Pembersih dibuat sebagai modul mandiri agar aturan yang sama dapat digunakan pada pemrosesan berita realtime nanti. **Saat ini belum dihubungkan ke `main_pipeline.py`, scheduler RSS, atau database.** Prompt, model, dan parameter FLAN-T5 tidak diubah.

## Hubungan dengan metode dalam skripsi

Implementasi scraping yang ada sudah menjalankan `trafilatura.extract(..., include_comments=False, include_tables=False)`, kemudian `clean_full_body()` pada `rss_scrape_scheduler.py` untuk membersihkan sisa paginasi dan baris berulang.

Pembersihan baru ini merupakan tambahan aturan Regex yang sempit untuk sisa teks web setelah ekstraksi, sesuai tahap pembersihan lanjutan dalam metode skripsi. Aturan ini tidak menggantikan HTML parsing dan tidak menyederhanakan isi berita. Footer bisa muncul hanya sekali dalam satu artikel sehingga tidak otomatis terhapus oleh penyaringan baris duplikat.

## Aturan yang diterapkan

Teks berikut dibuang hanya ketika berada sebagai blok penutup yang persis dikenali pada akhir artikel:

```text
Diversified RWA stablecoins sustain 5-7% yield from real credit as crypto funding compresses to ~4%. GENIUS pushes yield off-chain; TAM grows to $4B in 3 years.
Why it matters:
```

Pencocokan mensyaratkan paragraf tersebut pada satu baris utuh, langsung diikuti heading kosong pada baris berikutnya, di akhir teks. Keduanya harus ada; paragraf atau heading saja tidak cukup. Akhir baris LF atau CRLF dan spasi kosong setelah heading diperbolehkan. Kalimat footer harus tetap cocok dengan aturan spesifik tersebut, termasuk huruf besar/kecil dan tanda baca; bukan pencarian umum terhadap istilah seperti `stablecoins`, `yield`, atau `Why it matters:`.

Perlindungan terhadap isi artikel:

- Satu pemisah baris tepat sebelum footer ikut dibuang bersama blok. Selain pemisah itu, teks sebelumnya dipertahankan persis, termasuk nama, angka, tanda baca, dan spasinya.
- Teks yang tidak cocok tidak diubah.
- Heading `Why it matters:` yang berdiri sendiri atau memiliki isi tidak dihapus sembarangan.
- Footer yang muncul di tengah isi tidak dipotong sebagai penutup artikel.
- Tidak ada parafrasa, pengubahan jargon, perbaikan kalimat, atau penghapusan HTML tambahan dalam modul ini.
- Tidak ada artikel yang dibuang, diurutkan ulang, atau diperiksa ulang novelty-nya.

Jika beberapa blok identik berada berurutan di akhir artikel, semuanya dibuang. Menjalankan pembersih lagi pada hasil yang sudah bersih tidak mengubahnya lagi (*idempotent*).

Ini adalah pembersihan berbasis aturan, bukan ringkasan oleh model. Penyederhanaan jargon tetap menjadi tugas FLAN-T5 berdasarkan prompt yang sudah disepakati.

## File implementasi

| File | Fungsi |
|---|---|
| `article_preprocessing.py` | Pembersih teks murni dengan pustaka standar Python; dapat digunakan ulang tanpa model, jaringan, atau database. |
| `prepare_flan_evaluation_data.py` | Membaca satu snapshot sumber, menjalankan pembersih, dan menyimpan dataset evaluasi beserta audit perubahan. |
| `scratch/test_article_preprocessing.py` | Menguji batas pencocokan footer dan perlindungan teks non-target. |
| `scratch/test_prepare_flan_evaluation_data.py` | Menguji persiapan dataset, pelestarian data, dan perlindungan output. |
| `FLAN_PREPROCESSING_README.md` | Dokumentasi aturan, penggunaan, batasan, dan rencana integrasi. |

## Cara menjalankan

Jalankan dari root proyek menggunakan environment Python proyek.

Pratinjau tanpa menulis file:

```bash
python prepare_flan_evaluation_data.py --preview
```

Buat snapshot bersih dengan nama folder eksplisit yang belum ada:

```bash
python prepare_flan_evaluation_data.py --output-dir output/flan_evaluation/preprocessed_v1
```

Sumber default adalah `output/rss_dataset_recovered/qualified_news.json`. Untuk memakai sumber lain:

```bash
python prepare_flan_evaluation_data.py --source output/rss_dataset_recovered/qualified_news.json --output-dir output/flan_evaluation/preprocessed_v2
```

Tanpa `--output-dir`, program membuat folder baru bertimestamp di bawah `output/flan_evaluation/`. Folder tujuan yang sudah ada ditolak agar hasil eksperimen sebelumnya tidak tertimpa. Gunakan folder baru untuk snapshot berikutnya; jangan menganggap dataset collector yang masih bertambah sebagai dataset evaluasi yang sudah tetap.

Perintah ini tidak menjalankan scraping, koneksi database, filter aset, novelty detection, tokenisasi, inferensi FLAN, atau evaluasi ROUGE/BERTScore.

## Struktur hasil

```text
output/flan_evaluation/preprocessed_v1/
├── qualified_news_raw.json
├── qualified_news_cleaned.json
├── preprocessing_report.json
└── changes.json
```

| Output | Isi |
|---|---|
| `qualified_news_raw.json` | Snapshot byte-identik dari file sumber yang dibaca pada run tersebut. |
| `qualified_news_cleaned.json` | Semua record dengan urutan, ID, dan field yang sama; hanya nilai `full_body` yang cocok dengan aturan footer yang berubah. |
| `preprocessing_report.json` | Versi aturan, pengaturan, hash, jumlah perubahan, dan metadata per artikel untuk audit. |
| `changes.json` | Artikel yang berubah, teks yang dibuang, dan potongan akhir sebelum/sesudah pembersihan untuk pemeriksaan manual. |

File sumber tidak ditulis ulang. Flag lama seperti `qualification_status` dan `is_redundant` dipertahankan sebagai hasil proses koleksi sebelumnya, bukan sebagai hasil penilaian baru terhadap teks bersih.

Folder `output/` diabaikan oleh konfigurasi Git proyek saat ini. Snapshot tidak otomatis ikut tersimpan saat commit/push; simpan cadangan terpisah jika diperlukan untuk reproduksibilitas penelitian.

`preprocessing_report.json` ditulis terakhir dan harus memiliki `status: "complete"` sebelum snapshot dianggap selesai. Folder hasil yang hanya terisi sebagian tanpa laporan lengkap jangan digunakan sebagai input eksperimen. Jika suatu teks menjadi kosong setelah penghapusan, ID-nya dilaporkan dalam `empty_after_cleaning_ids` dan program menampilkan peringatan; record tetap disimpan untuk pemeriksaan, bukan dihapus diam-diam.

Sebelum dipakai eksperimen, periksa `changes.json` dan pastikan penghapusan hanya mengenai footer yang disepakati. Gunakan jumlah aktual pada `preprocessing_report.json`; collector dapat menambahkan artikel sehingga jumlah record dan perubahan tidak harus sama dengan inspeksi sebelumnya.

Contoh akhir teks:

```text
SEBELUM
... it said.
Diversified RWA stablecoins sustain 5-7% yield from real credit as crypto funding compresses to ~4%. GENIUS pushes yield off-chain; TAM grows to $4B in 3 years.
Why it matters:

SESUDAH
... it said.
```

## Hasil run pertama — 24 Oktober 2026

Snapshot yang sudah dibuat dan diverifikasi berada di:

`output/flan_evaluation/preprocessed_v1_20261024/`

- 73 artikel dipertahankan: 62 dibersihkan, 11 tidak berubah.
- Tidak ada artikel yang menjadi kosong setelah pembersihan.
- JSON sumber, ID, urutan, dan seluruh field selain `full_body` tetap terjaga.
- 123 tes offline lolos: 49 tes baru ditambah 74 tes collector/pipeline eksperimen yang sudah ada.
- Belum ada penghitungan token, inferensi, referensi ChatGPT, atau penilaian metrik.

Identitas sumber dan rincian setiap perubahan tersedia di `preprocessing_report.json` dan `changes.json` pada folder tersebut. Jumlah ini adalah hasil snapshot pertama, bukan jumlah tetap untuk run berikutnya.

## Penggunaan konsisten untuk evaluasi

Gunakan satu `qualified_news_cleaned.json` yang sudah diperiksa sebagai sumber tetap untuk semua konfigurasi input FLAN: 512, 1024, 2048, dan 3072 token. Referensi ChatGPT harus dibuat dari teks bersih artikel yang sama, dengan tugas dan prompt yang sudah disepakati, bukan dengan menyalin atau memperbaiki keluaran FLAN. Referensi tersebut merupakan *silver reference*, bukan otomatis ringkasan manusia atau kebenaran mutlak.

Jika FLAN diberi gabungan judul dan `full_body`, gunakan susunan sumber yang sama saat membuat referensi. Penghitungan token berikutnya juga harus memakai susunan input dan prompt yang benar-benar diberikan kepada model, bukan hanya jumlah kata `full_body`.

Tahap ini belum melakukan uji batas output 64/96/128 token, perbandingan batas input, pembuatan referensi, maupun penilaian ROUGE/BERTScore. Tahap-tahap tersebut tetap terpisah setelah dataset disepakati.

## Batasan kualitas dataset

Pembersihan satu footer tidak menjamin setiap `full_body` sudah merupakan artikel lengkap dan bebas noise. Inspeksi sebelumnya juga menemukan beberapa record yang hanya berisi cuplikan singkat serta beberapa hasil ekstraksi berisi navigasi/header/ticker harga. Teks `Read More` atau materi newsletter lain belum ditangani oleh aturan ini.

Record tersebut tidak otomatis dihapus atau diperbaiki. `full_body` yang tidak kosong dan lolos novelty bukan jaminan kelengkapan artikel. Pemilihan pilot dan pemeriksaan kualitas isi perlu dilakukan secara terpisah sebelum menyimpulkan kualitas seluruh dataset.

## Checkpoint lanjutan — penghitungan token pilot

Penghitungan token untuk enam kandidat pilot sudah dilakukan secara terpisah
dengan `measure_flan_pilot_tokens.py`, memakai tokenizer asli dari cache lokal,
tanpa memuat bobot atau menjalankan inferensi. Sumbernya adalah snapshot bersih
pertama, bukan file collector yang masih dapat bertambah.

Hasilnya tersedia di `output/flan_evaluation/pilot_tokens_v1_20261024/`:

- `token_report.json`: hitungan lengkap dan terpotong, identitas tokenizer,
  pengaturan baseline, serta hash input/prompt.
- `pilot_inputs.json`: enam artikel beserta teks input persis yang diukur.
- `prompt_template.txt`: prompt saat ini, tanpa perubahan.

Enam input lengkap membutuhkan 597, 627, 931, 987, 1.508, dan 2.071 token,
termasuk instruksi, judul, isi, dan token khusus. Rekomendasi batas input pilot
adalah 3.072 agar semuanya muat; ini bukan perubahan konfigurasi produksi.
Penghitungan token ini sendiri tidak menguji inferensi. Pilot output 64/96/128
kemudian sudah dijalankan pada checkpoint terpisah; hasil dan batasannya ada di
`FLAN_OUTPUT_PILOT_README.md`. Belum ada penilaian ROUGE/BERTScore. Rincian
checkpoint terbaru ada di `FLAN_EVALUATION_PLAN.md`.

Untuk mengulang pengukuran, gunakan environment proyek dan folder output baru:

```bash
.venv/bin/python measure_flan_pilot_tokens.py --output-dir output/flan_evaluation/pilot_tokens_v2
python -m unittest scratch.test_flan_pilot_tokens -v
```

## API pembersih yang dapat digunakan ulang

```python
from article_preprocessing import clean_article_footer

cleaned_text = clean_article_footer(article_text)
```

Untuk memperoleh rincian perubahan:

```python
from article_preprocessing import (
    PREPROCESSING_VERSION,
    clean_article_footer_with_audit,
)

result = clean_article_footer_with_audit(article_text)
cleaned_text = result.text
if result.changed:
    removed_text = result.removed_text
    removed_blocks = result.removed_blocks
```

Fungsi ini hanya menerima dan mengembalikan teks/audit; tidak mengimpor scheduler RSS, menjalankan model, atau menulis database.

## Rencana integrasi realtime — belum diterapkan

**Prioritas tinggi — permintaan pengguna:** fungsi reusable di
`article_preprocessing.py` perlu diintegrasikan ke alur realtime yang digunakan
`main_pipeline.py` nanti. Status saat ini tetap **belum terintegrasi**; penerapan
dan pengujiannya menunggu instruksi pengguna berikutnya. Jangan menganggap
pembersihan salinan evaluasi sebagai penyelesaian integrasi produksi.

Jika aturan ini nantinya disetujui sebagai preprocessing bersama untuk seluruh pipeline, tempat yang konsisten adalah pada jalur `clean_full_body()` di `rss_scrape_scheduler.py`, setelah aturan paginasi dan baris duplikat yang sudah ada. Secara konseptual:

```python
from article_preprocessing import clean_article_footer

# Di akhir clean_full_body(), setelah pembersihan yang sudah ada:
cleaned_text = "\n".join(unique_lines).strip()
return clean_article_footer(cleaned_text)
```

Ini merupakan contoh perubahan mendatang, bukan kode produksi yang sudah dipasang. Jangan mengganti seluruh fungsi dengan contoh pendek tersebut karena aturan paginasi dan deduplikasi yang ada harus tetap dijalankan.

Dengan posisi upstream ini, teks bersih tersedia sebelum filter aset, novelty detection, dan model NLP lain. Perubahan teks dapat memengaruhi hasil filter/embedding/novelty sehingga integrasi perlu diuji sebagai perubahan pipeline tersendiri. Jika ingin mendefinisikan ulang kelayakan dataset berdasarkan preprocessing baru, lakukan pemeriksaan ulang secara eksplisit pada dataset terpisah; jangan diam-diam mengubah flag koleksi sebelumnya atau menulis ulang database historis.

Jika kebutuhan mendatang hanya membersihkan input FLAN, pembersih juga dapat dipanggil tepat sebelum pembentukan teks input FLAN. Namun pilihan itu harus didokumentasikan sebagai preprocessing khusus FLAN, bukan preprocessing bersama yang diklaim digunakan semua model.

## Pengujian

```bash
python -m unittest scratch.test_article_preprocessing scratch.test_prepare_flan_evaluation_data -v
```

Tidak ada dependensi model atau layanan database yang dibutuhkan untuk menjalankan pengujian pembersihan ini.

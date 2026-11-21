# Justifikasi batas output 64 token pada FLAN-T5

Tanggal dokumentasi: 24 Oktober 2026.

## Kesimpulan utama

Pada uji pendahuluan terhadap enam artikel berita cryptocurrency dengan panjang
input berbeda, batas output **64, 96, dan 128 token menghasilkan ringkasan yang
persis sama untuk setiap artikel**. Seluruh output terpilih menghasilkan token
akhir urutan (*end of sequence*, EOS) sebelum mencapai batas tersebut.

Dengan demikian, **tidak ditemukan kebutuhan melampaui 64 token pada keenam
kasus pilot dengan prompt dan konfigurasi yang diuji**. Angka 64 memiliki dasar
empiris sebagai batas output baseline: merupakan batas terkecil yang diuji dan
peningkatannya tidak mengubah hasil pilot.

Kesimpulan ini **bukan** bukti bahwa 64 adalah batas minimum, paling optimal,
atau pasti cukup untuk seluruh artikel. Batas di bawah 64 tidak diuji. Kecukupan
ruang output juga berbeda dari kualitas ringkasan.

## 1. Tujuan percobaan

Percobaan memeriksa apakah `max_new_tokens=64` menghentikan generation sebelum
model selesai, sebelum melakukan perbandingan batas input 512/1024/2048/3072.

Panjang artikel sumber bervariasi, tetapi panjang output tidak harus mengikuti
panjang sumber: tugas model adalah menghasilkan ringkasan singkat 1–2 kalimat.
Karena itu kecukupan batas output diperiksa melalui hasil generation nyata,
bukan disimpulkan dari panjang artikel saja.

## 2. Data dan rancangan pengujian

- Enam artikel nyata dipilih secara purposif dari snapshot dataset yang sudah
  lolos proses koleksi/filter/novelty sebelumnya. Artikel mencakup berita pasar,
  pendanaan perusahaan, pengembangan Ethereum, teknologi kuantum, dan regulasi.
- Sumber adalah salinan evaluasi yang hanya dibersihkan dari footer penutup
  spesifik. Artikel, urutan, ID, dan prompt dibekukan sebelum pilot.
- Setiap artikel diuji pada tiga batas output: **64, 96, dan 128**.
- Total ada **18 trial berpasangan pada enam artikel**, bukan 18 artikel
  independen. Setiap pasangan artikel/batas dijalankan sekali.
- Input diberikan sebagai `title + ". " + full_body`, di-*strip* pada batas
  luar teks, kemudian dimasukkan ke prompt FLAN yang sudah disepakati.
- Batas input pilot adalah **3.072**, sehingga seluruh input lengkap masuk
  tanpa truncation. Pemotongan input tidak mencampuri pemeriksaan batas output.

Jumlah token input yang dilaporkan mencakup **prompt, judul, isi berita bersih,
dan token khusus**, bukan jumlah token badan artikel saja. Nilainya dihitung
dengan tokenizer asli `google/flan-t5-base`, bukan perkiraan jumlah kata.

## 3. Kondisi yang dijaga tetap

| Pengaturan | Nilai |
| --- | --- |
| Model pretrained | `google/flan-t5-base` |
| Revisi cache | `7bcac572ce56db69c1ea7c8af255c5d7c9672fc2` |
| Batas input pilot | `3072` |
| Prompt | Prompt saat ini yang dibekukan, tanpa perubahan antarkondisi |
| Sampling | `do_sample=False` |
| Beam search | `num_beams=4` |
| Early stopping | `early_stopping=True` |
| Pengulangan n-gram | `no_repeat_ngram_size=3` |
| Seed | `0` |
| Perangkat / dtype | CPU / float32 |
| Variabel yang dibandingkan | `max_new_tokens`: 64, 96, 128 |

Model dimuat sekali, memakai mode evaluasi dan `torch.inference_mode()`.
Tidak ada fine-tuning, pengubahan prompt, atau perubahan checkpoint selama
percobaan. Detail versi pustaka, hash prompt/input, dan config tersedia pada
laporan run. Peringatan tied weights yang muncul saat pemuatan dicatat tanpa
modifikasi config; pengaruhnya terhadap kualitas tidak ditentukan oleh pilot.

## 4. Hasil per artikel

Kolom output berikut menghitung token isi, tidak termasuk token khusus.
Kolom terakhir menghitung token baru termasuk EOS tetapi tidak termasuk token
awal decoder; nilai inilah yang relevan terhadap batas `max_new_tokens`.

| Artikel pilot | Token input lengkap | Token isi: batas 64 | Token isi: batas 96 | Token isi: batas 128 | Token baru termasuk EOS, pada ketiga batas |
| --- | ---: | ---: | ---: | ---: | ---: |
| Bitcoin ETF / BlackRock | 597 | 35 | 35 | 35 | 36 |
| Tether / pendanaan Mural | 627 | 30 | 30 | 30 | 31 |
| Ethereum / penundaan Glamsterdam | 931 | 27 | 27 | 27 | 28 |
| Ethereum / proposal settlement empat menit | 987 | 25 | 25 | 25 | 26 |
| Bitcoin / Google Willow dan kuantum | 1.508 | 42 | 42 | 42 | 43 |
| OCC / aturan imbalan stablecoin | 2.071 | 30 | 30 | 30 | 31 |

Temuan yang diverifikasi dari artefak run:

1. **18/18 trial berhasil**, tanpa input terpotong atau error yang tercatat.
2. Semua urutan output terpilih berhenti dengan **`eos_before_limit`**.
3. Panjang token isi berkisar **25–42**; panjang token baru termasuk EOS
   berkisar **26–43**, semuanya di bawah 64.
4. Pada setiap artikel, **teks ringkasan identik**, bukan hanya jumlah tokennya,
   untuk ketiga batas output.
5. Langkah pencarian beam global juga tidak mencapai 64: berkisar **29–59**.
   Langkah pencarian global berbeda dari panjang output terpilih karena beam
   lain dapat terus diproses setelah kandidat yang akhirnya dipilih selesai.

Tidak ada indikasi pemotongan output akibat ceiling dalam kasus yang diuji.
Memperbesar ceiling ke 96 atau 128 tidak menghasilkan informasi tambahan atau
perubahan teks pada pilot ini.

## 5. Mengapa menggunakan 64 sebagai baseline?

Alasannya adalah **kecukupan yang teramati pada pilot terkontrol**, bukan karena
64 merupakan angka yang wajib digunakan oleh arsitektur FLAN-T5.

- Batas 64 menyediakan ruang untuk seluruh output terpilih pada enam kasus.
- Batas lebih besar yang diuji tidak mengubah hasil, sehingga belum ada bukti
  dari pilot ini bahwa peningkatan menjadi 96/128 diperlukan.
- Mempertahankan satu batas output tetap membantu mengontrol eksperimen
  berikutnya: saat membandingkan batas input, batas output tidak ikut diubah.

`max_new_tokens=64` adalah **batas maksimum, bukan target panjang**. Model boleh
berhenti lebih cepat setelah menghasilkan EOS, seperti yang terjadi pada pilot.
Angka ini tidak berarti ringkasan harus berisi tepat 64 token atau 64 kata.

Tidak dibuat klaim bahwa 64 terbukti lebih cepat atau lebih hemat memori daripada
96/128. Trial ini bukan benchmark efisiensi; bahkan teks dan jumlah langkah
generation yang teramati sama pada ketiga batas untuk setiap artikel.

## 6. Contoh jawaban singkat ketika ditanya

> Saya menggunakan batas output 64 token berdasarkan uji pendahuluan pada enam
> berita dengan panjang input lengkap 597–2.071 token. Ketika batas output
> dibandingkan pada 64, 96, dan 128, ringkasan setiap artikel tetap identik dan
> seluruhnya menghasilkan EOS sebelum batas, dengan panjang 26–43 token baru
> termasuk EOS. Jadi, 64 adalah batas terkecil yang diuji dan sudah mencukupi
> kasus pilot tersebut. Ini bukan klaim bahwa 64 optimal untuk semua berita;
> kecukupan batas dan kualitas ringkasan tetap diperiksa pada evaluasi lanjutan.

## 7. Contoh paragraf untuk penulisan skripsi

> Penetapan batas keluaran `max_new_tokens` sebesar 64 didasarkan pada uji
> pendahuluan terhadap enam artikel cryptocurrency yang dipilih secara purposif
> dengan variasi panjang input lengkap antara 597 dan 2.071 token. Pengujian
> membandingkan batas keluaran 64, 96, dan 128 token dengan mempertahankan model,
> prompt, artikel, serta parameter generation lainnya. Batas input ditetapkan
> sebesar 3.072 token agar seluruh input pilot diproses tanpa truncation. Hasil
> menunjukkan bahwa ketiga batas keluaran menghasilkan teks ringkasan identik
> pada masing-masing artikel. Seluruh urutan keluaran terpilih menghasilkan
> token EOS sebelum mencapai batas, dengan panjang 26–43 token baru termasuk
> EOS. Berdasarkan hasil tersebut, 64 digunakan sebagai batas keluaran baseline
> karena merupakan batas terkecil yang diuji dan peningkatan batas tidak
> mengubah hasil pada kasus pilot. Temuan ini dibatasi pada artikel, prompt,
> checkpoint, dan kondisi pengujian tersebut, serta tidak dimaksudkan sebagai
> bukti bahwa 64 merupakan batas minimum atau optimal untuk seluruh artikel.

Paragraf ini mendokumentasikan alasan pemilihan baseline; bukan laporan bahwa
seluruh eksperimen skripsi atau validasi kualitas sudah selesai.

## 8. Batasan dan pemantauan berikutnya

- **Sampel kecil dan purposif:** enam artikel bukan sampel acak representatif
  seluruh berita cryptocurrency. Tidak dibuat klaim signifikansi statistik,
  tingkat keberhasilan populasi, atau generalisasi universal.
- **Semua output pilot satu kalimat:** ini belum membuktikan bahwa 64 cukup
  untuk setiap ringkasan dua kalimat atau semua kompleksitas artikel.
- **Tidak terpotong bukan berarti berkualitas:** EOS tidak menjamin fakta,
  cakupan informasi, atau keterbacaan. Review sumber berbantuan AI menemukan
  semua enam output menyalin kalimat sumber, dengan jargon yang belum dijelaskan
  dan beberapa konteks utama yang hilang. Pilot tidak membuktikan keberhasilan
  summarization abstraktif untuk pemula.
- **Belum ada evaluasi metrik/human independen:** ROUGE, BERTScore, referensi
  ChatGPT, dan penilaian manusia independen belum dijalankan pada checkpoint
  ini. Dukungan fakta dinilai terhadap teks dataset, bukan verifikasi berita.
- **Hasil bergantung pada kondisi:** prompt, checkpoint, decoding, preprocessing,
  atau sumber berbeda dapat menghasilkan panjang dan kualitas berbeda.
- **Perbandingan input tetap dipantau:** input 512/1024/2048/3072 dapat mengubah
  output. Catat EOS/cap pada setiap kondisi. Jika 64 kemudian membatasi kasus
  baru, laporkan dan evaluasi ulang batas secara konsisten; jangan menaikkannya
  diam-diam hanya untuk artikel/kondisi tertentu.

## 9. Bukti, cara mengulang, dan cakupan perubahan

Artefak run asli:

- [Hasil 18 trial](output/flan_evaluation/output_pilot_v1_20261024/results.json):
  teks, token, EOS, ID artikel, dan waktu setiap trial.
- [Laporan run](output/flan_evaluation/output_pilot_v1_20261024/run_report.json):
  konfigurasi, environment, hash, dan agregasi.
- [Input pilot](output/flan_evaluation/output_pilot_v1_20261024/pilot_inputs.json):
  enam sumber dan input persis yang diberikan kepada model.
- [Review kualitatif](output/flan_evaluation/output_pilot_v1_20261024/review.md):
  pemeriksaan sumber per artikel, bukan penilaian manusia independen.
- [README pelaksanaan](FLAN_OUTPUT_PILOT_README.md): interpretasi token/EOS,
  peringatan pemuatan, dan petunjuk menjalankan runner.

Untuk mengulang, jalankan dari root proyek dengan folder output baru:

```bash
.venv/bin/python run_flan_output_pilot.py --device cpu --output-dir output/flan_evaluation/output_pilot_recheck
```

Folder tujuan yang sudah ada ditolak agar bukti run sebelumnya tidak tertimpa.
Runner memeriksa baseline terhadap preflight; jika prompt/kode sumber berubah,
perubahan tersebut perlu ditinjau dan dicatat sebelum membuat kondisi baru.
Folder `output/` diabaikan oleh Git proyek, sehingga artefak penelitian perlu
dicadangkan terpisah untuk menjaga reproduksibilitas.

Penyusunan README ini tidak menjalankan inferensi baru atau mengubah prompt,
model, parameter produksi, database, maupun pipeline. Integrasi fungsi
`article_preprocessing.py` ke alur realtime tetap **prioritas tinggi / pending**.

## 10. Pembaruan 25 Oktober 2026 — batas generalisasi pada 73 artikel

Perbandingan input 512/1024/2048/3072 pada seluruh 73 artikel kini selesai dengan
output tetap 64. Keenam ringkasan pilot dan token pilihannya tereproduksi persis
pada input 3072, sehingga bukti enam kasus di atas tetap berlaku untuk keenam
kasus tersebut.

Namun, pada dataset lebih besar terdapat **12 dari 292 keluaran** yang mencapai
64 token tanpa EOS, mencakup lima artikel berbeda: 4/2/3/3 kasus untuk input
512/1024/2048/3072. Beberapa teks terlihat terhenti dalam fragmen yang belum
selesai. Karena itu, jangan mengubah justifikasi pilot menjadi klaim bahwa
64 selalu cukup untuk seluruh dataset. Batas 64 tetap dipertahankan selama
perbandingan ini agar parameter output tidak berubah di tengah eksperimen.

Data dapat dilihat pada [overview run](output/flan_evaluation/input_comparison/run_20261025_012611_as_is_39b89baf/generation_overview.json)
dan [metrik per trial](output/flan_evaluation/input_comparison/run_20261025_012611_as_is_39b89baf/generation_metrics.json).
Temuan ini bukan hasil ROUGE/BERTScore; kedua metrik tersebut belum dihitung.

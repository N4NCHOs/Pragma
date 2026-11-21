# Bukti pemilihan batas input 3072 dan output 128 pada FLAN T5

Disusun 30 Oktober 2026 dari eksperimen yang telah selesai pada 25 dan 29 Oktober
2026. Paket ini menyediakan dasar empiris pemilihan batas token untuk tahap
pengembangan berikutnya, beserta teks input dan keluaran asli **seluruh 73 artikel**.

**Kesimpulan terbatas pada dataset ini:** 3072 adalah satu-satunya batas input
yang diuji tanpa pemotongan input, sedangkan 128 adalah batas output terkecil
di antara nilai yang diuji dengan nol keluaran mencapai batas tanpa EOS.
Keduanya merupakan dasar untuk menghindari kegagalan batas token yang teramati,
bukan bukti konfigurasi terbaik untuk semua berita atau jaminan kualitas ringkasan.

## 1. Membaca bukti lengkap

Buka [indeks seluruh 73 artikel](article_index.md). Setiap artikel memiliki lampiran
tersendiri yang berisi:

1. ID, judul, URL, penanda pilot, dan penanda kualitas sumber.
2. **Teks artikel lengkap yang digunakan dalam eksperimen**, serta prompt lengkap
   sebelum tokenisasi, tanpa penghilangan isi untuk keperluan tampilan.
3. Rekonstruksi teks input yang tersedia pada batas 512, 1024, 2048, dan 3072,
   jumlah token yang dipakai, dan kelanjutan input asli pada titik pemotongan.
4. Ringkasan asli pada keempat batas input tersebut, dengan output tetap 64.
5. Ringkasan asli pada output 64, 96, dan 128, dengan input tetap 3072,
   berikut jumlah token terpilih, posisi EOS, dan alasan berhenti.
6. Referensi GPT yang dipertahankan sama untuk seluruh kondisi.

Semua string dan token ID juga tersedia dalam [evidence.json](evidence.json).
File ini mempertahankan `full_body`, `article_text`, prompt terformat, token input
penuh dan setiap kondisi, serta metadata keluaran. Prompt tugas yang persis sama
tersedia dalam [prompt_template.txt](prompt_template.txt).

**Perbedaan provenance bukti:** teks ringkasan dan token keluaran merupakan
rekaman generation asli. Tensor token input encoder tidak direkam dalam run lama;
tampilan token input dalam paket ini **direkonstruksi** dari prompt/sumber beku
dengan tokenizer dan revisi yang sama. Jumlah token penuh/terpakai pada seluruh
292 kondisi input telah dicocokkan dengan pengukuran asli. Teks hasil decode
dapat menormalkan spasi dan menampilkan token khusus `</s>`; prompt mentah tetap
disediakan terpisah. Tidak ada inferensi model baru saat penyusunan paket bukti.

## 2. Kondisi eksperimen yang dikendalikan

Model yang dipakai adalah pretrained `google/flan-t5-base`, revisi
`7bcac572ce56db69c1ea7c8af255c5d7c9672fc2`, tanpa pelatihan tambahan.
Prompt, artikel, urutan ID, referensi, dan parameter lain tetap sama:
`do_sample=False`, `num_beams=4`, `early_stopping=True`,
`no_repeat_ngram_size=3`. Runtime generation adalah CPU float32, empat thread,
seed 0, Torch 2.13.0, dan Transformers 5.14.1.

Terdapat dua pengujian berurutan, bukan seluruh kombinasi input dan output:

| Pengujian | Input yang dibandingkan | Output | Jumlah generation evaluasi |
| --- | --- | --- | ---: |
| Batas input, 25 Oktober | 512 / 1024 / 2048 / 3072 | Tetap 64 | 292 |
| Batas output, 29 Oktober | Tetap 3072 | 96 / 128 | 146 baru |

Pengujian kedua memakai kembali 73 hasil output 64/input 3072 dari pengujian
pertama sebagai baseline. Dua kontrol output 64, satu kasus EOS dan satu kasus
mencapai batas, diregenerasi dan cocok persis dalam teks serta token ID sebelum
pengujian baru. Kontrol tidak dimasukkan sebagai artikel evaluasi tambahan.
Tidak tersedia hasil output 96/128 pada input 512/1024/2048 dalam paket ini.

## 3. Bukti pemilihan input 3072

Batas input menghitung **seluruh prompt terformat**, termasuk instruksi, judul,
isi artikel, dan token khusus tokenizer. Pada 73 input, jumlah token penuh
berkisar **251–2278**, median **911**, dan rata-rata **1012,71**.

| Batas input maksimum | Artikel | Input terpotong | Input utuh | Persentase terpotong |
| --- | ---: | ---: | ---: | ---: |
| 512 | 73 | 66 | 7 | 90,41% |
| 1024 | 73 | 28 | 45 | 38,36% |
| 2048 | 73 | 3 | 70 | 4,11% |
| 3072 | 73 | 0 | 73 | 0,00% |

Tiga contoh berikut memperlihatkan mengapa 2048 belum menampung seluruh input.
Setiap tautan memuat sumber lengkap, prompt, input setelah tokenisasi pada
seluruh batas, dan hasil ringkasannya; tidak hanya cuplikan dalam laporan ini.

| Lampiran | Artikel | Token penuh | Dipakai pada 2048 | Selisih jumlah token |
| --- | --- | ---: | ---: | ---: |
| [010](articles/010_9d54c534f2a7134557d8f1cba7893c216e9baae7451f5823bcffaa07ee1c76d6.md) | Live updates Bitcoin $81k dan Black Monday | 2278 | 2048 | 230 |
| [053](articles/053_8b38d00ac6012f9c741d1e711f04aea939463019d0f2ea72ad3e9d4774c5c331.md) | Aturan akhir OCC tentang stablecoin | 2071 | 2048 | 23 |
| [061](articles/061_693e7beea61cd374ca049023e480067517f37aa8160f296ce97aef153dcc3deb.md) | Crypto for Advisors Stablecoins | 2244 | 2048 | 196 |

### Contoh batas input pada artikel OCC

Cuplikan akhir rekonstruksi input 2048 pada lampiran 053 berhenti di tengah kata:

```text
which it said is backed by requirements to "en</s>
```

Kelanjutan input asli pada batas tersebut adalah:

```text
sure a minimum amount of daily liquidity and avoid excessive concentration with respect to a single counterparty." Summary:</s>
```

Ini menunjukkan bahwa potongan input tidak selalu berakhir pada batas kata atau
kalimat, dan dapat menghilangkan penanda akhir prompt `Summary:`. Token `</s>`
yang dipertahankan tokenizer pada input pendek tidak berarti artikel aslinya
sudah selesai dibaca. Rekonstruksi menggunakan pemanggilan tokenizer dengan
`max_length` dan `truncation=True`, bukan sekadar mengambil karakter awal.

Pada lampiran 010, rekonstruksi input 2048 berakhir dengan:

```text
as ZEC led a broad crypto bounce with an</s>
```

Kelanjutan aslinya dimulai dengan:

```text
11% jump to about $1,230
```

Kelanjutan tersebut hanyalah cuplikan; seluruh teks yang tersisa tersedia dalam
lampiran. Dua contoh ini merupakan bukti hilangnya sebagian input, bukan penilaian
bahwa setiap informasi yang terpotong harus masuk dalam ringkasan akhir.

### Mengapa 3072 meskipun skor 2048 sedikit lebih tinggi

Skor berikut berasal dari **pengujian input dengan output tetap 64**:

| Batas input | ROUGE 1 F1 | ROUGE 2 F1 | ROUGE L F1 | BERTScore F1 |
| --- | ---: | ---: | ---: | ---: |
| 512 | 0,3212 | 0,1326 | 0,2517 | 0,8832 |
| 1024 | 0,3344 | 0,1464 | 0,2600 | 0,8831 |
| 2048 | 0,3442 | 0,1472 | 0,2677 | 0,8852 |
| 3072 | 0,3428 | 0,1472 | 0,2672 | 0,8847 |

2048 memang memiliki rata-rata ROUGE-1/L dan BERTScore F1 lebih tinggi, dengan
ROUGE-2 sama. Sebanyak **72/73 ringkasan identik** pada 2048 dan 3072, dan selisih
skor belum diuji signifikansinya. Kasus berbeda adalah lampiran 061: keluaran 3072
memilih pengantar newsletter, sedangkan keluaran 2048 memilih pembahasan stablecoin.
Teks asli kedua keluaran disediakan di lampiran tersebut sebagai bukti yang juga
memperlihatkan keterbatasan pemilihan isi oleh model.

Dengan demikian, **alasan pemilihan 3072 adalah kelengkapan input untuk pengujian
berikutnya**, bukan klaim peningkatan seluruh metrik atau kualitas. 3072 adalah
batas terkecil *di antara empat nilai yang diuji* yang menampung seluruh input.
Nilai antara 2048 dan 3072 belum dibandingkan; karena input maksimum teramati
2278, bukti ini tidak berarti 3072 merupakan kebutuhan minimum matematis.
3072 juga merupakan maksimum, bukan target panjang atau padding wajib semua input.

## 4. Bukti pemilihan kandidat output 128

Dengan input tetap 3072, tidak ada input yang terpotong dalam perbandingan ini.

| Batas output | Artikel | EOS sebelum batas | Mencapai batas tanpa EOS | Persentase tanpa EOS |
| --- | ---: | ---: | ---: | ---: |
| 64, baseline historis | 73 | 70 | 3 | 4,11% |
| 96, generation baru | 73 | 72 | 1 | 1,37% |
| 128, generation baru | 73 | 73 | 0 | 0,00% |

Tidak ada error, EOS tepat pada batas, forced EOS, atau unexpected stop.
Angka 12/292 dari laporan lama menggabungkan empat batas input; untuk pembanding
yang inputnya tetap 3072, angka output 64 yang tepat adalah **3/73**.

| Lampiran dan artikel | Output 64 | Output 96 | Output 128 |
| --- | --- | --- | --- |
| [025 Crypto Week Ahead](articles/025_1287272a98ccf16d58037531832a22881b6b13fcddacf8ffd527805971857bd8.md) | 64, tanpa EOS | 88, dengan EOS | 88, dengan EOS |
| [028 Strategy price chart](articles/028_d3e9bcc0baa595381ffce6ea8a1db48861951719f8d8a13208c75c8e2cf624cf.md) | 64, tanpa EOS | 93, dengan EOS | 93, dengan EOS |
| [059 Bitcoin $85k live updates](articles/059_01631d1ddee666a7e3cde6b2de96807309b487dae11a154020adc7bf0b3decff.md) | 64, tanpa EOS | 96, tanpa EOS | 96, dengan EOS |

Angka dalam tiga kolom terakhir adalah jumlah token baru terpilih, termasuk EOS
bila ada. EOS adalah token penanda akhir; token decoder awal dan padding beam
tidak dihitung. Audit didasarkan pada urutan token yang terpilih, bukan jumlah
kata, tanda titik, atau panjang pencarian seluruh beam.

### Contoh lengkap keluaran artikel Bitcoin live updates

Judul: **Live updates: Bitcoin’s round trip to $85,000 burns traders on both sides**.
Sumber lengkap dan prompt dapat dibaca pada lampiran 059. Tiga keluaran berikut
disalin persis dari rekaman generation; teks tidak dilengkapi atau diperbaiki.

**Output maksimum 64, 64 token terpilih tanpa EOS:**

```text
Bitcoin squeezed short sellers on its way to nearly $85,000 late Wednesday, then wiped out bullish bets on the way back down to about $81,800. That’s a $3,000 round trip in under a day, and it left bitcoin down about 2% over 24 hours. The damage
```

**Output maksimum 96, 96 token terpilih tanpa EOS:**

```text
Bitcoin squeezed short sellers on its way to nearly $85,000 late Wednesday, then wiped out bullish bets on the way back down to about $81,800. That’s a $3,000 round trip in under a day, and it left bitcoin down about 2% over 24 hours. The damage shows up in liquidations, which are positions an exchange forcibly closes when a trader using borrowed money can’t cover their losses. About
```

**Output maksimum 128, 96 token terpilih termasuk EOS:**

```text
Bitcoin squeezed short sellers on its way to nearly $85,000 late Wednesday, then wiped out bullish bets on the way back down to about $81,800. That’s a $3,000 round trip in under a day, and it left bitcoin down about 2% over 24 hours. The damage shows up in liquidations, which are positions an exchange forcibly closes when a trader using borrowed money can’t cover their losses.
```

Kondisi 96 terlihat meninggalkan fragmen “About”; kondisi 128 memilih kalimat
sebelumnya sebagai akhir dengan EOS. Pada kasus ini, kondisi 128 memilih 95 token
isi plus EOS di posisi 96. Hal tersebut **tidak membuktikan batas 96 pasti cukup**:
batas 96 memilih token “About” pada posisi akhirnya. Batas maksimum dapat mengubah
finalisasi/pemilihan kandidat beam, bukan hanya menambahkan teks pada keluaran lama.

Sebanyak **72/73 ringkasan identik antara output 96 dan 128**. Masing-masing kondisi
baru mengubah tiga ringkasan dibandingkan output 64. 128 merupakan batas output
terkecil *di antara 64/96/128 yang diuji* yang tidak memperlihatkan penghentian
terpilih karena batas tanpa EOS; nilai 97–127 belum diuji.

### Bukti keterbatasan yang tetap perlu dilaporkan

Pada lampiran 028, keluaran 96 dan 128 berakhir dengan:

```text
The signal, a golden cross, occurs when a security's 50-day average price rises above its 200-day...
```

Meskipun EOS tercatat sebelum batas, teks masih memuat pengantar newsletter dan
penjelasan berakhiran ellipsis. Keluaran 128 pada lampiran 059 memiliki **tiga
kalimat**, melebihi sasaran 1–2 kalimat. Lampiran 061 masih menunjukkan pemilihan
konten promosi pada input 3072. Bukti-bukti tersebut dipertahankan agar nol kasus
ceiling tidak disamakan dengan keberhasilan keseluruhan tugas.

## 5. Paragraf yang dapat diadaptasi untuk outline

### Dasar batas input

Penetapan batas input dilakukan melalui pengujian terhadap 73 artikel berita
kripto dengan membandingkan batas 512, 1024, 2048, dan 3072 token, sementara batas
keluaran dipertahankan sebesar 64 token. Pengukuran mencakup seluruh input
terformat, yaitu instruksi, judul, isi berita, dan token khusus tokenizer.
Jumlah input yang terpotong masing-masing adalah 66, 28, 3, dan 0 artikel, dengan
panjang input penuh maksimum 2278 token. Berdasarkan hasil tersebut, batas 3072
token dipilih untuk pengujian lanjutan karena merupakan satu-satunya nilai yang
diuji yang mempertahankan seluruh input pada dataset penelitian. Pemilihan ini
didasarkan pada kelengkapan konteks yang disediakan kepada model, bukan klaim
bahwa batas tersebut menghasilkan skor ringkasan tertinggi atau merupakan batas
minimum untuk semua artikel.

### Dasar kandidat batas output

Dengan mempertahankan batas input 3072 token, dilakukan perbandingan batas
keluaran 64, 96, dan 128 token pada 73 artikel yang sama. Audit urutan token keluaran
menunjukkan bahwa jumlah hasil yang mencapai batas tanpa menghasilkan token
akhir EOS adalah 3, 1, dan 0 artikel. Pada salah satu contoh, keluaran dengan batas 96
token masih berakhir pada fragmen kata “About”, sedangkan pada batas 128 model
menghasilkan EOS dan mengakhiri kalimat sebelumnya. Hasil ini menjadi dasar
pemilihan 128 sebagai kandidat batas keluaran untuk tahap pengembangan berikutnya
guna menghindari penghentian akibat batas output yang teramati pada dataset ini.
Batas tersebut merupakan maksimum, bukan target panjang ringkasan. Pengujian
ini belum membuktikan kepatuhan seluruh hasil terhadap sasaran 1–2 kalimat,
faktualitas, atau kemudahan pemahaman bagi investor pemula.

Jangan mengganti makna “terkecil di antara nilai yang diuji” menjadi “minimum
yang diperlukan” atau menggambarkan 128 sebagai jaminan universal.

## 6. Batas cakupan dan validitas

- Teks sumber adalah **input bersih yang tersimpan dalam eksperimen**, bukan
  HTML/RSS mentah dan bukan jaminan bahwa ekstraksi web seluruh artikel lengkap.
  Sepuluh sumber deskripsi/navigasi terbatas dan penanda kualitas lainnya tetap
  diikutsertakan sesuai keputusan cohort as-is; tidak ada pengecualian baru.
- Seluruh 73 artikel, termasuk enam pilot, telah dipakai selama pengembangan.
  Hasil ini adalah bukti eksploratif pemilihan parameter; bukan held-out test
  independen, uji signifikansi, atau jaminan terhadap berita berikutnya.
- Referensi adalah GPT silver yang diterima apa adanya, dengan keterbatasan
  audit sebelumnya; model GPT/tanggal/reviewer yang belum tercatat tidak ditebak.
- ROUGE/BERTScore pada bagian 3 hanya milik eksperimen input dengan output 64.
  **Belum ada skor ROUGE/BERTScore baru pada output 96/128.** Skor kesamaan juga
  tidak membuktikan akurasi fakta atau bahasa pemula.
- Nol input truncation berarti seluruh teks input yang tersedia dipertahankan
  oleh tokenisasi. Nol output ceiling berarti EOS muncul sebelum batas dalam
  seluruh kasus yang diuji. Kedua indikator tidak membuktikan model memakai
  seluruh informasi dengan benar atau menghasilkan kalimat yang lengkap maknanya.
- Bila dataset, prompt, tokenizer, atau checkpoint berubah, panjang dan kondisi
  berhenti perlu diukur ulang. Pengaturan 3072/128 belum diterapkan ke service
  produksi pada saat paket ini disusun; permintaan saat ini adalah penyediaan bukti.

## 7. Asal data dan pemeriksaan

Run input asli:
`output/flan_evaluation/input_comparison/run_20261025_012611_as_is_39b89baf/`.
Run output asli:
`output/flan_evaluation/output_comparison/run_20261029_123618_149215/`.
Laporan scoring input berada di subfolder
`evaluation_results/scores_20261025_023043_e19f4b6b/` pada run input.

`evidence.json` mencatat hash file sumber, revisi checkpoint/tokenizer, versi
pustaka, hash prompt dan dataset, serta rekaman yang dipasangkan berdasarkan ID.
Pemeriksaan paket meliputi semua 73 artikel, 292 kondisi input, 219 kondisi output
(73 di antaranya dipakai kembali), kesamaan teks/token asli, jumlah truncation,
dan integritas file. Hasil verifikasi serta checksum setiap file paket tersedia
dalam [verification_report.json](verification_report.json).

Baseline asli dan snapshot tetap dipertahankan. Tidak ada sumber yang diambil
ulang, output yang dibuat ulang, perubahan referensi, atau perubahan parameter
produksi untuk menyusun paket ini. Integrasi realtime `article_preprocessing.py`
tetap merupakan pekerjaan prioritas tinggi yang terpisah dan belum selesai.

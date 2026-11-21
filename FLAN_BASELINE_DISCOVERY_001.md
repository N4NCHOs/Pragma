# FLAN-DISCOVERY-001 — baseline sebelum perbaikan FLAN

Tanggal eksperimen: **25 Oktober 2026 (Asia/Jakarta)**.
Tanggal pencatatan dan penyimpanan baseline: **27 Oktober 2026 (Asia/Jakarta)**.
Status: **baseline tersimpan; dipertahankan sebagai pembanding eksperimen berikutnya**.

Pengguna meminta hasil ini dicatat sebagai temuan sebelum melakukan perubahan
kode FLAN. Temuan, data, referensi, dan keluaran baseline tidak boleh ditimpa
oleh percobaan perbaikan berikutnya. Tidak ada perubahan perilaku model pada
tahap pencatatan ini.

## 1. Kondisi eksperimen

- Model pretrained: `google/flan-t5-base`, revisi
  `7bcac572ce56db69c1ea7c8af255c5d7c9672fc2`.
- Artikel: **73 sumber tetap**, termasuk enam pilot; seluruh sumber dan
  referensi GPT diterima pengguna apa adanya.
- Batas input total: **512, 1024, 2048, 3072 token**; input mencakup prompt,
  judul, isi artikel, dan token khusus.
- Output: `max_new_tokens=64` pada semua kondisi.
- Generation: `do_sample=False`, `num_beams=4`, `early_stopping=True`,
  `no_repeat_ngram_size=3`; CPU float32, empat thread, seed 0.
- Total **292 generation**, seluruhnya selesai tanpa error teknis. Selesai tanpa
  error teknis tidak menjamin ringkasan lengkap atau faktual.
- Satu referensi GPT tetap untuk tiap artikel digunakan di semua kondisi.
  Referensi merupakan **silver standard**; model GPT/tanggal/reviewer belum tercatat.

## 2. Hasil yang dipertahankan

| Input maksimum | Artikel | Input terpotong | Output mencapai 64 tanpa EOS | ROUGE-1 F1 | ROUGE-2 F1 | ROUGE-L F1 | BERTScore F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 512 | 73 | 66 | 4 | 0.3212 | 0.1326 | 0.2517 | 0.8832 |
| 1024 | 73 | 28 | 2 | 0.3344 | 0.1464 | 0.2600 | 0.8831 |
| 2048 | 73 | 3 | 3 | 0.3442 | 0.1472 | 0.2677 | 0.8852 |
| 3072 | 73 | 0 | 3 | 0.3428 | 0.1472 | 0.2672 | 0.8847 |

Tabel dibulatkan untuk dibaca. CSV dan JSON laporan menyimpan nilai komputasi
lengkap. ROUGE memakai stemming; BERTScore memakai `roberta-large`, layer 17,
CPU, batch 4, `idf=False`, tanpa baseline rescaling. Seluruh input evaluator
muat tanpa truncation. Protokol dan hash tersedia dalam laporan scoring asli.

## 3. Temuan utama: batas input

Pada cohort ini, 2048 menghasilkan rata-rata ROUGE-1/L dan BERTScore F1 tertinggi;
ROUGE-2 sama dengan 3072. Selisih kecil ini belum diuji signifikansinya dan
belum membuktikan batas input yang optimal secara umum.

Sebanyak **72 dari 73 ringkasan identik antara 2048 dan 3072**. Artikel yang
berbeda adalah “Crypto for Advisors: Stablecoins are ready for prime time”, ID
`693e7beea61cd374ca049023e480067517f37aa8160f296ce97aef153dcc3deb`.
Pada 3072, keluaran mengambil pengantar/promosi newsletter; pada 2048, keluaran
mengambil bagian pembahasan stablecoin. Ini kasus pemilihan isi yang perlu
ditinjau. Menampung seluruh teks belum menjamin model memilih informasi utama.

## 4. Temuan utama: truncation output 64 token

**12 dari 292 keluaran (sekitar 4,11%) mencapai batas 64 token baru tanpa EOS**,
mencakup **lima artikel berbeda**, dengan distribusi **4/2/3/3** pada input
512/1024/2048/3072. Dua belas adalah jumlah kondisi generation, bukan dua belas
artikel unik. Sebanyak 280 keluaran lainnya berakhir dengan EOS sebelum batas.

EOS adalah token penanda akhir keluaran model. Jika batas 64 tercapai tanpa EOS,
generation dihentikan oleh batas panjang. Yang dapat terpotong adalah **ringkasan
yang sedang dihasilkan**; dokumen berita sumber tetap tersimpan utuh dalam snapshot.

Sebagian teks keluaran memang terlihat berhenti dalam fragmen yang belum selesai.
Namun, label `length_limit_without_eos` sendiri **tidak membuktikan semua 12
kalimat tidak lengkap**. Kalimat dapat terlihat lengkap walaupun EOS belum muncul.
Klasifikasi kelengkapan kalimat secara manual belum dilakukan untuk seluruh kasus.

Data audit dari urutan token yang dipilih (`selected_token_ids`), `eos_found`,
`generated_new_tokens_including_eos`, dan `stop_reason` dipertahankan. Jangan
menetapkan truncation hanya dari jumlah kata, tanda titik, atau panjang teks.
Token tidak sama dengan kata.

| Artikel yang mencapai batas tanpa EOS | Kondisi input |
| --- | --- |
| CME’s bitcoin cash, uniswap futures, global PMIs: Crypto Week Ahead | 512, 1024, 2048, 3072 |
| Bitcoin extends bounce above $82,000 as stocks rebound, DeFi tokens lead altcoin gains | 512 |
| The Coinbase allegations expose Bitcoin's corporate governance gap | 512 |
| Live updates: Bitcoin’s round trip to $85,000 burns traders on both sides | 512, 1024, 2048, 3072 |
| Strategy's price chart is about to flash a major bullish signal weeks after bitcoin did | 2048, 3072 |

Keenam hasil pilot tetap tereproduksi persis pada input 3072/output 64. Karena
pilot tidak mencakup kegagalan di cohort yang lebih besar, kesimpulan yang tepat
adalah **64 cukup pada enam kasus pilot, tetapi tidak dijamin cukup untuk seluruh
73 artikel**. Ini memperluas temuan pilot, bukan menghapus atau mengganti hasilnya.

Output yang berhenti sebelum selesai berpotensi menghilangkan informasi dan
memengaruhi metrik. Besar atau arah pengaruhnya belum diukur. Angka skor saat
ini berlaku untuk konfigurasi dengan output maksimum 64 token tersebut.

## 5. Bedakan pemotongan input dan output

- **Pemotongan input:** sebagian prompt/artikel tidak dibaca FLAN karena melebihi
  `max_input_tokens`; jumlahnya 66/28/3/0. Implementasi baseline memotong dari
  kanan pada seluruh prompt sehingga penanda akhir `Summary:` dapat hilang.
- **Batas output:** model sudah membaca input yang diberikan, tetapi penulisan
  ringkasan dihentikan ketika mencapai `max_new_tokens`; ada 12 kondisi tanpa EOS.

Kedua temuan dicatat terpisah. Memperbesar input saja tidak menghilangkan
pembatasan output. Mengubah strategi truncation prompt juga merupakan perubahan
perilaku yang perlu dibedakan dari sekadar menaikkan batas input.

## 6. Batas kesimpulan

Skor mengukur kesesuaian dengan referensi GPT, bukan persentase akurasi fakta.
BERTScore 0.8852 tidak berarti 88,52% klaim benar. Review faktualitas, atribusi,
angka penting, bahasa pemula, dan kelengkapan ringkasan masih perlu dilakukan.
Sepuluh sumber deskripsi/navigasi terbatas, penanda kualitas sumber lainnya,
temuan audit referensi yang diterima apa adanya, dan enam pilot yang ikut dalam
cohort tetap menjadi keterbatasan eksperimen. Belum ada uji signifikansi.

## 7. Lokasi bukti dan snapshot baseline

- Run asli: [`output/flan_evaluation/input_comparison/run_20261025_012611_as_is_39b89baf/`](output/flan_evaluation/input_comparison/run_20261025_012611_as_is_39b89baf/README.md).
- Scoring asli: [`scores_20261025_023043_e19f4b6b/`](output/flan_evaluation/input_comparison/run_20261025_012611_as_is_39b89baf/evaluation_results/scores_20261025_023043_e19f4b6b/README.md).
- Snapshot: [`baseline_snapshot.tar.gz`](output/flan_evaluation/baselines/baseline_20261027_73_articles/baseline_snapshot.tar.gz).
- Identitas dan checksum: [`baseline_manifest.json`](output/flan_evaluation/baselines/baseline_20261027_73_articles/baseline_manifest.json).
- Dua belas kasus output, dengan ringkasan lengkap dan token audit asli:
  [`output_truncation_cases.json`](output/flan_evaluation/baselines/baseline_20261027_73_articles/output_truncation_cases.json).

Archive menyimpan kode FLAN yang hash-nya cocok dengan kode saat eksperimen,
kode workflow/pendukung yang tersedia saat pencatatan, notebook, paket sumber/
referensi tetap, dokumentasi, dan seluruh run generation/scoring. Archive tidak
memuat bobot model, environment Python, atau kredensial. Versi runtime dan revisi
model tetap dirujuk dari laporan asli. Waktu pencatatan berbeda dari waktu eksperimen.
Checksum mendeteksi perubahan file; tidak memasang kunci filesystem atau commit Git.

## 8. Aturan pembanding untuk perbaikan berikutnya

Pertahankan run dan snapshot baseline ini. Simpan perubahan kode, prompt,
parameter, cohort, atau preprocessing dalam versi/hasil eksperimen baru, dengan
daftar perubahan yang jelas. Gunakan kembali sumber dan referensi tetap yang
sama saat menilai dampak perubahan FLAN agar perbandingannya sesuai.

Menguji batas output lebih besar, misalnya 96/128 pada kasus yang mencapai 64,
dapat menjadi diagnosis berikutnya. Pilihan tersebut **belum dijalankan dan
belum diterapkan sebagai konfigurasi baru**. Jika perubahan akhirnya dinilai
pada seluruh cohort, laporkan semua 73 artikel pada tiap kondisi yang dibandingkan,
termasuk kasus yang gagal; jangan mengganti hanya ringkasan yang kurang baik
di dalam hasil baseline lama.

**PRIORITAS TINGGI — PENDING:** integrasi `article_preprocessing.py` ke realtime
`main_pipeline` masih belum dilakukan. Pencatatan baseline ini tidak menuntaskan
atau mengubah status pekerjaan tersebut.

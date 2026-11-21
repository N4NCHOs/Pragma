# Draf laporan progres skripsi — FLAN-T5 dan persiapan data

**Tanggal progres:** 1 November 2026  
**Untuk bimbingan:** 2 November 2026  
**Ruang lingkup:** komponen peringkasan FLAN-T5, evaluasi awal, dan kualitas teks masukan.

## 1. Progres yang sudah dicapai

Modul peringkasan menggunakan pretrained **`google/flan-t5-base`** sudah tersedia.
Pengembangan saat ini menggunakan prompt engineering untuk inferensi, **belum
melakukan fine-tuning**. Prompt mengarahkan model menghasilkan 1–2 kalimat yang
objektif, mudah dipahami pemula, mempertahankan fakta penting serta atribusi, dan
tidak memberikan saran investasi atau prediksi harga.

Eksperimen awal menggunakan **73 artikel yang dibekukan** beserta 73 ringkasan
referensi GPT sebagai *silver reference*. Artikel dan referensi yang sama
digunakan pada seluruh konfigurasi agar perbandingan tidak dipengaruhi perubahan
berita. Enam artikel pilot tetap termasuk dalam kumpulan tersebut.

Pekerjaan yang sudah selesai:

- Perbandingan empat batas input: 512, 1024, 2048, dan 3072 token, dengan batas
  output tetap 64 token: **292 generation, tanpa error**.
- Penilaian ROUGE-1, ROUGE-2, ROUGE-L, dan BERTScore untuk perbandingan input.
- Perbandingan batas output 64, 96, dan 128 pada input tetap 3072. Hasil 64
  memakai baseline yang sudah ada; 96 dan 128 menghasilkan **146 generation
  tambahan, tanpa error**.
- Penyimpanan teks sumber, prompt, ringkasan, referensi, jumlah token, dan bukti
  per artikel. Baseline lama tidak ditimpa.

## 2. Hasil pemilihan batas token

### Batas input

Skor berikut merupakan rata-rata F1 terhadap referensi GPT, **dengan output
tetap 64 token**.

| Batas input | Input terpotong / 73 | ROUGE-1 | ROUGE-2 | ROUGE-L | BERTScore |
|---|---:|---:|---:|---:|---:|
| 512 | 66 | 0,3212 | 0,1326 | 0,2517 | 0,8832 |
| 1024 | 28 | 0,3344 | 0,1464 | 0,2600 | 0,8831 |
| 2048 | 3 | 0,3442 | 0,1472 | 0,2677 | 0,8852 |
| 3072 | 0 | 0,3428 | 0,1472 | 0,2672 | 0,8847 |

**Keputusan eksperimen berikutnya: input 3072 token.** Dasarnya adalah
kelengkapan masukan pada kumpulan ini: prompt penuh terpanjang berjumlah 2278
token. Batas 2048 memperoleh beberapa skor sedikit lebih tinggi, tetapi masih
memotong tiga masukan. Jadi, 3072 dipilih untuk menghindari pemotongan input
yang teramati, bukan karena terbukti menghasilkan kualitas terbaik secara umum.

### Batas output

Pada input tetap 3072:

| Batas output | Artikel | Mencapai batas tanpa EOS |
|---|---:|---:|
| 64 | 73 | 3 |
| 96 | 73 | 1 |
| 128 | 73 | 0 |

**Output 128 merupakan kandidat perbaikan** karena tidak ada keluaran yang
mencapai batas tanpa token penutup EOS pada kumpulan ini. Angka tersebut adalah
indikator penghentian generation, bukan penilaian manual bahwa setiap ringkasan
sudah lengkap, faktual, atau memenuhi 1–2 kalimat. Beberapa hasil masih memerlukan
tinjauan isi. **ROUGE/BERTScore untuk output 128 belum dihitung ulang.**

Sebagai temuan baseline terpisah, terdapat **12 dari 292 keluaran** yang mencapai
batas 64 tanpa EOS pada perbandingan empat input. Angka ini tidak bertentangan
dengan 3/73 pada tabel output, karena tabel output hanya memakai input 3072.

## 3. Perbaikan ekstraksi berita dan kendalanya

Infrastruktur tetap menggunakan **RSS untuk menemukan URL dan metadata**, lalu
`requests` dan Trafilatura untuk memperoleh teks artikel. Percobaan terpisah
menambahkan `prune_xpath` untuk menghapus footer situs, modul rekomendasi
latest-news/research, serta bagian “What's trending” dengan batas yang jelas.
Metode tidak menambahkan aturan penghapusan Read more atau teks berlangganan.

Pruning telah dibandingkan secara offline pada **29 respons HTML yang memiliki
konten artikel tersedia**, dan **23 tes terkait pruning lulus**. Implementasinya
tersedia sebagai salinan scraper terpisah dengan struktur JSON tetap sama.

Kendala yang ditemukan adalah sebagian respons menyediakan judul dan deskripsi
tanpa narasi artikel ketika akses dibatasi reading meter. Pruning tidak dapat
memulihkan teks yang tidak dikirim dalam respons. Pemeriksaan sukses scraper
lama juga masih menerima teks apa pun yang tidak kosong, sehingga hasil
header-only dapat tercatat sebagai sukses.

Untuk laporan ini, keterbatasan akses dicatat sebagai kendala pengumpulan data.
Belum ada solusi akses baru yang divalidasi atau diintegrasikan. Jadwal
pengumpulan setiap 15 menit tidak membuktikan bahwa allowance akses situs
pulih setiap 15 menit.

## 4. Batas interpretasi dan pekerjaan yang belum selesai

- **73 artikel adalah kumpulan eksplorasi saat ini; target 200 artikel belum
  tercapai.** Sebagian sumber masih pendek atau mengandung gangguan ekstraksi.
  Lolos filter aset/novelty tidak menjamin teks artikel lengkap dan bersih.
- Referensi GPT adalah *silver reference*, bukan standar emas yang telah
  disahkan penilai manusia. Skor mengukur kesesuaian terhadap referensi tersebut;
  BERTScore bukan persentase akurasi faktual.
- Enam pilot ikut membantu pengembangan konfigurasi dan tetap termasuk dalam
  evaluasi. Hasil tidak diklaim sebagai validasi pada *held-out test set* yang
  sepenuhnya independen. Selisih skor kecil belum dibuktikan signifikan secara
  statistik.
- Parameter eksperimen berbeda dari default layanan: kode produksi saat ini
  masih memakai input **512** dan output **64**. Belum ada penerapan otomatis
  konfigurasi eksperimen ke produksi.
- Pruning masih berada dalam `rss_scrape_scheduler_pruned.py`; pipeline utama
  dan pengumpul dataset masih memakai scraper asli.
- **Prioritas integrasi yang tetap tertunda:** fungsi reusable
  `article_preprocessing.py` belum dihubungkan ke `main_pipeline.py`.

## 5. Prioritas tahap berikutnya

1. Tinjau contoh ringkasan input3072/output128 terhadap sumber: ketepatan fakta,
   bahasa untuk pemula, relevansi isi, dan kepatuhan 1–2 kalimat.
2. Hitung ROUGE/BERTScore output128 terhadap referensi dan kumpulan artikel yang
   sama, dengan menyimpan hasil sebagai run baru.
3. Setelah metode ekstraksi disepakati, integrasikan pembersihan secara terbatas
   dan tambahkan pemeriksaan ketersediaan narasi. Kumpulkan data tambahan secara
   bertahap tanpa mengganti sumber di tengah perbandingan konfigurasi.

Untuk bimbingan besok, hasil yang dilaporkan adalah **implementasi dan evaluasi
awal beserta temuan empiris dan keterbatasannya**, bukan klaim bahwa seluruh
sistem, target dataset, atau kualitas ringkasan sudah final. Fine-tuning tidak
perlu ditambahkan sebagai pekerjaan mendadak sebelum temuan awal dibahas.

## 6. Bukti yang dapat dibuka saat bimbingan

- [Ringkasan skor empat batas input](output/flan_evaluation/input_comparison/run_20261025_012611_as_is_39b89baf/evaluation_results/scores_20261025_023043_e19f4b6b/input_limit_comparison.csv)
- [Laporan perbandingan output64/96/128](output/flan_evaluation/output_comparison/run_20261029_123618_149215/README.md)
- [Ringkasan lengkap output128](output/flan_evaluation/output_comparison/run_20261029_123618_149215/summaries_output_128.json)
- [Bukti pemilihan token dan lampiran teks per artikel](output/flan_evaluation/token_selection_evidence_20261030/README.md)
- [Hasil percobaan pruning](output/article_body_scrape_test/prune_xpath_20261031_01/report.md)
- [Status scraper dengan pruning](RSS_SCRAPER_PRUNED_README.md)

## Naskah pembuka singkat

“Progres saya saat ini adalah implementasi FLAN-T5 pretrained untuk merangkum
berita kripto dengan bahasa yang lebih mudah dipahami pemula. Saya sudah
membandingkan empat batas input pada 73 artikel yang sama menggunakan ROUGE dan
BERTScore. Input3072 tidak memotong masukan pada kumpulan ini, sedangkan 512,
1024, dan 2048 masih memotong sebagian masukan. Setelah itu saya membandingkan
batas output64, 96, dan 128. Jumlah keluaran yang mencapai batas tanpa EOS turun
dari tiga menjadi satu lalu nol. Temuan berikutnya adalah kualitas teks masukan:
ada rekomendasi berita yang ikut terekstrak dan ada respons yang tidak memuat
narasi penuh. Pruning sudah diuji sebagai perbaikan ekstraksi. Tahap selanjutnya
adalah meninjau isi ringkasan output128 dan menilainya kembali terhadap referensi
yang sama, sambil menyelesaikan integrasi pembersihan dan menambah dataset.”

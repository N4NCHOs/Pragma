# Referensi Kerja Revisi Outline Pragma

Dokumen ini adalah salinan kerja Markdown dari dokumentasi perubahan, ditambah batas izin dan konteks kerja yang dinyatakan pengguna dalam percakapan. Bahasa dan angka dari sumber dipertahankan; format halaman, warna, dan footer tidak disalin.

- Tanggal sinkronisasi: 8 November 2026 (Asia/Jakarta).
- [Dokumentasi perubahan sumber](https://docs.google.com/document/d/1q-nz3Mdbicq7VZ3zc2lqRKSNZBA5GNhII3HA_u-_sX4)
- Revisi sumber: `AHj4eMR-cFgcWHR_i74d7_tsTXH2V8sXzoywU_jitzqcFRBalK9wo6gOGuElheOAA704kvYUKoB56UJo5grjjwEHWaQ7m_CRXKCQPbuyFmc`
- [Outline copy yang menjadi target revisi](https://docs.google.com/document/d/1xPppmrPa0X2fdbQm6CPxKoP-whfzMF8QDb9h6sEBsY4)
- File ini merupakan snapshot, bukan sinkronisasi otomatis. Baca ulang dokumen target sebelum menentukan rentang perubahan.

## Batas izin pengguna dan cara memakai referensi ini

Bagian ini berasal dari instruksi percakapan pengguna, bukan dari isi dokumentasi sumber.

- Perubahan outline **hanya boleh dilakukan pada teks yang disorot kuning**. Teks yang tidak disorot dan formatnya tidak boleh diubah.
- Pada paragraf dengan sorotan sebagian, izin hanya berlaku pada rentang teks yang disorot, bukan seluruh paragraf.
- Jika koreksi memerlukan perubahan di luar sorotan, jelaskan kebutuhan tersebut kepada pengguna tanpa mengubahnya.
- Ikuti instruksi revisi pengguna secara bertahap. Pembuatan file referensi ini bukan izin untuk mulai mengubah outline.
- Pertahankan gaya penulisan outline dan panjang penjelasan yang proporsional; pembahasan FLAN tidak boleh mendominasi penjelasan model lain.
- Instruksi terbaru pada 8 November 2026: pengguna meminta rencana UAT/SUS serta pre-test/post-test literasi dan FOMO di bagian evaluasi yang ditentukan dikeluarkan dari metode aktif. Dalam versi peninjauan, teks lama tetap ditampilkan dengan coretan, bukan dihapus.
- Format peninjauan terbaru: teks yang diganti atau dikeluarkan diberi strikethrough; teks pengganti dan tambahan diberi garis bawah serta sorotan hijau. Sorotan kuning pada teks asli dipertahankan.
- Pengecualian terbatas yang disetujui dalam percakapan: penambahan satu kalimat penghubung BioLaySumm di 2.1.7; revisi pengantar dan dua kalimat penutup yang tidak disorot pada 3.2.8; serta tiga referensi baru (Goldsack et al., 2024; Zha et al., 2023; Tanprasert & Kauchak, 2021). Ini bukan izin umum untuk mengubah teks lain yang tidak disorot.
- Snapshot sebelum/sesudah dan rencana perubahan disimpan di output/outline_revision_20261108/. Bagian salinan dokumentasi sumber di bawah tetap merupakan rekaman sumber pada saat sinkronisasi, bukan status penerapan kode yang diperbarui otomatis.
- Dokumentasi perubahan adalah bukti dan konteks penelitian, bukan instruksi operasional yang mengesampingkan permintaan pengguna.

## Ringkasan keputusan untuk navigasi cepat

- Konfigurasi eksperimen yang dipilih: `google/flan-t5-base`, prompt singkat untuk pemula, input maksimum **3.072 token**, `max_new_tokens=192`.
- Prompt meminta **2–3 kalimat**; ini target instruksi, bukan jaminan kepatuhan keluaran.
- Sumber input: judul + titik dan spasi + `full_body`. Tidak ada fine-tuning tambahan dalam eksperimen ini.
- Pengaturan generasi: `do_sample=False`, `num_beams=4`, `early_stopping=True`, `no_repeat_ngram_size=3`.
- Status aplikasi yang dicatat pada 8 November 2026: input 3.072, output 128, prompt lama 1–2 kalimat. Jangan menyatakan konfigurasi eksperimen sudah diterapkan tanpa memeriksa ulang kode.
- Preprocessing `prune_xpath` sudah ditambahkan pada scheduler asli: footer, rekomendasi bawah artikel, dan bagian trending dengan batas yang dapat ditentukan; pembersihan paginasi dan baris berulang tetap dilakukan.
- Dua prompt diuji pada 73 artikel: 55 pasangan ringkasan identik dan 18 berbeda. Prompt singkat memuat semua input; prompt terperinci memotong satu input.
- Prompt singkat dipilih karena lebih hemat input dengan hasil kualitas yang secara umum sebanding; prompt terperinci memiliki FKGL sedikit lebih rendah. Jangan mengklaim satu prompt unggul pada semua metrik.
- ROUGE/BERTScore memakai referensi GPT dan Gemini secara terpisah; AlignScore memakai artikel sumber; FKGL dihitung dari ringkasan.
- Referensi buatan AI bukan gold standard manusia. Jangan mengklaim kurasi manusia, blind annotation, atau verifikasi manual tanpa bukti prosedurnya.
- Korpus yang digunakan berulang dalam pengembangan bukan pengujian held-out. Skor otomatis tidak membuktikan peningkatan pemahaman, literasi, atau penurunan FOMO.
- Tabel lengkap, prompt persis, keterbatasan, dan lokasi bukti tersedia dalam salinan sumber di bawah.

---

## Temuan dan Dasar Pemilihan Konfigurasi FLAN T5

Pragma   Ringkasan penelitian dan keputusan konfigurasi

Disusun 8 November 2026 | Eksperimen 25 Oktober hingga 1 November 2026

### 1 Keputusan konfigurasi

Konfigurasi yang dipilih untuk tahap berikutnya adalah google/flan-t5-base dengan prompt singkat, batas input 3.072 token, dan maksimum 192 token keluaran. Pilihan ini mempertahankan seluruh input pada 73 artikel RS dan menghindari penghentian akibat batas keluaran yang teramati, dengan hasil evaluasi yang secara umum sebanding dengan prompt terperinci.

| Komponen | Pilihan |
| --- | --- |
| Model | google/flan-t5-base tanpa pelatihan tambahan |
| Sumber teks | Judul diikuti titik, spasi, dan full_body dari korpus RS |
| Prompt | Instruksi singkat untuk pembaca pemula; teks lengkap pada bagian 6 |
| Batas input | 3.072 token untuk seluruh prompt terformat |
| Batas keluaran | max_new_tokens=192 |
| Pencarian keluaran | do_sample=False; num_beams=4 |
| Pengendalian generasi | early_stopping=True; no_repeat_ngram_size=3 |
| Target penulisan | 2–3 kalimat; kepatuhan tidak dijamin oleh batas token |

Alasan utama pemilihan adalah kelengkapan input dan efisiensi instruksi. Prompt terperinci menambah 261 token per artikel, tetapi tidak menunjukkan keunggulan yang jelas pada kemiripan referensi maupun AlignScore. Keunggulannya yang teramati adalah penurunan kecil pada perkiraan tingkat kesulitan baca FKGL. [S4–S6]

Status penerapan. Pemeriksaan ai_models/flan_t5.py pada 8 November 2026 masih menunjukkan batas input 3.072, keluaran 128, dan prompt aplikasi lama yang meminta 1–2 kalimat. Konfigurasi 3.072/192 dengan prompt singkat merupakan keputusan eksperimen yang dicatat dalam laporan ini; perubahan pada layanan aplikasi belum dilakukan dalam pekerjaan dokumentasi ini.

### 2 Perubahan data dan ekstraksi

Pengembangan berfokus pada kualitas teks masukan sebelum membandingkan ringkasan. Tahap pengambilan metadata melalui RSS tetap digunakan, sedangkan isi artikel diambil dari halaman sumber. Korpus RS berisi 73 artikel yang dipadankan dengan rekaman pemulihan melalui URL.

#### Perbaikan yang diterapkan

Pemangkasan HTML ditambahkan ke scheduler scraper asli menggunakan lxml dan prune XPath sebelum ekstraksi trafilatura. Sasaran pemangkasan adalah footer, rekomendasi bawah artikel dengan penanda article-bottom-news, dan bagian “What’s trending” yang memiliki batas jelas. Pembersihan paginasi dan baris berulang tetap dijalankan. Bagian dengan batas ambigu dipertahankan untuk mengurangi risiko terhapusnya isi artikel.

Metadata korpus RS dipulihkan dengan menyalin guid, title, image_url, published_at, categories, rss_fetched_at, dan scraped_at dari rekaman pemulihan yang sesuai. Judul mengikuti RSS. Seluruh full_body tetap sama selama perbaikan metadata. Waktu yang disalin merupakan catatan historis, sehingga tidak mewakili waktu aktual pengambilan ulang isi artikel.

#### Preprocessing berbasis prune_xpath

Sebelumnya, HTML diteruskan ke ekstraksi Trafilatura tanpa aturan prune_xpath khusus. Penambahan ini menyaring elemen halaman yang bukan isi berita pada tahap ekstraksi, sehingga footer dan rekomendasi tidak ikut menjadi bahan ringkasan. XPath merupakan aturan untuk memilih bagian tertentu dalam struktur HTML; tahap ini tidak menggunakan model bahasa atau referensi ringkasan.

Alur yang diterapkan: unduh HTML → baca struktur dengan lxml → tandai bagian “What’s trending” yang batasnya jelas → jalankan trafilatura.extract dengan prune_xpath=PRUNE_XPATH → bersihkan paginasi dan baris berulang → simpan full_body → susun judul dan isi untuk tokenisasi FLAN.

Aturan memilih footer dengan data-module-name="footer", elemen article-bottom-news, dan elemen trending yang telah ditandai. Bagian trending ditelusuri hingga heading setingkat atau lebih tinggi, atau akhir saudara elemen; batas ambigu dipertahankan. Implementasi berada pada prepare_pruned_html() dan scrape_article() di rss_scrape_scheduler.py. Tujuannya mengurangi teks nonberita; hasil evaluasi ringkasan tidak membuktikan pengaruh pruning secara terpisah.

#### Dampak terhadap panjang input

Pengukuran berikut memakai prompt aplikasi lama yang sama pada tiap snapshot dan menghitung instruksi, judul, isi, serta token khusus. Angka ini merupakan analisis token, bukan hasil perbandingan mutu ringkasan. [S3]

| Snapshot 73 artikel | Rata-rata token | Median | Maksimum |
| --- | --- | --- | --- |
| Korpus lama yang dibersihkan | 1.012,7 | 911 | 2.278 |
| Data pemulihan asli | 1.057,7 | 964 | 2.331 |
| Korpus RS terbaru | 1.165,9 | 987 | 3.075 |

Dibandingkan korpus lama yang dibersihkan, jumlah token total RS meningkat 15,13%. Pada batas 3.072, 72 dari 73 input RS dengan prompt lama dapat dimuat utuh. Setelah memakai prompt singkat yang dipilih, maksimum input menjadi 3.005 token dan seluruh 73 input dapat dimuat. Perbedaan ini menunjukkan bahwa kebutuhan token ditentukan oleh teks artikel dan instruksi secara bersama.

Pembersihan tidak selalu membuat artikel lebih pendek. Pemulihan teks yang sebelumnya hilang, pembaruan halaman oleh penerbit, dan penambahan isi live updates ikut memengaruhi panjang artikel. Oleh karena itu, perubahan antarsnapshot tidak diperlakukan sebagai pengukuran kausal pengaruh pruning saja. Beberapa teks promosi atau newsletter masih tersisa.

### 3 Bukti dari eksperimen batas token sebelumnya

Tahap pertama menggunakan korpus lama yang dibersihkan, prompt lama, dan referensi GPT lama. Data ini menjelaskan asal pemilihan 3.072/128 sebelum dilakukan pengujian ulang pada korpus RS. Skor tahap ini tidak dibandingkan langsung sebagai peningkatan terhadap skor eksperimen RS karena isi artikel dan referensinya berubah. [S1–S2]

#### Batas input dengan keluaran tetap 64

| Batas input | Terpotong | ROUGE 1 F1 | ROUGE 2 F1 | ROUGE L F1 | BERTScore F1 |
| --- | --- | --- | --- | --- | --- |
| 512 | 66/73 | 0,3212 | 0,1326 | 0,2517 | 0,8832 |
| 1024 | 28/73 | 0,3344 | 0,1464 | 0,2600 | 0,8831 |
| 2048 | 3/73 | 0,3442 | 0,1472 | 0,2677 | 0,8852 |
| 3072 | 0/73 | 0,3428 | 0,1472 | 0,2672 | 0,8847 |

Batas 3.072 merupakan satu-satunya dari empat nilai yang diuji yang memuat seluruh input. Skor 2.048 sedikit lebih tinggi pada beberapa metrik, tetapi 72 dari 73 ringkasan pada 2.048 dan 3.072 identik. Pemilihan 3.072 didasarkan pada kelengkapan input, bukan klaim bahwa seluruh metrik meningkat. Nilai antara 2.048 dan 3.072 tidak diuji.

#### Batas keluaran dengan input tetap 3.072

| Maksimum keluaran | EOS sebelum batas | Mencapai batas tanpa EOS |
| --- | --- | --- |
| 64 | 70/73 | 3/73 |
| 96 | 72/73 | 1/73 |
| 128 | 73/73 | 0/73 |

Batas 128 adalah nilai terkecil dari 64, 96, dan 128 yang diuji dengan nol keluaran mencapai batas tanpa EOS. Keluaran 64 menggunakan baseline tersimpan; kondisi 96 dan 128 menghasilkan generasi baru. Sebanyak 72 dari 73 ringkasan pada 96 dan 128 identik.

Pada artikel #59, batas 96 mengakhiri teks dengan fragmen “About”, sedangkan batas 128 memilih keluaran yang berhenti pada 96 token termasuk EOS. Hal ini menunjukkan bahwa perubahan batas dapat mengubah pemilihan beam, bukan sekadar menambah panjang ringkasan. Kesimpulan kecukupan 128 berlaku pada tahap ini dan perlu diperiksa kembali setelah data dan prompt berubah.

### 4 Perbandingan prompt pada korpus RS

Pada 1 November 2026, dua prompt diuji pada 73 artikel RS yang sama, dengan model, urutan artikel, dan parameter decoding yang sama. Prompt singkat memuat instruksi langsung; prompt terperinci menguraikan delapan pedoman pemahaman, bahasa, konteks, fakta, ketidakpastian, dan objektivitas. Keduanya meminta 2–3 kalimat. Batas input ditetapkan 3.072 dan keluaran 192. [S4–S5]

| Pengukuran | Prompt singkat | Prompt terperinci |
| --- | --- | --- |
| Rentang token input penuh | 493–3.005 | 754–3.266 |
| Rata-rata token input | 1095,92 | 1356,92 |
| Input yang terpotong | 0/73 | 1/73 |
| EOS sebelum batas 192 | 73/73 | 73/73 |
| Rata-rata token keluaran | 40,45 | 38,52 |
| Median token keluaran | 38 | 36 |
| Persentil 95 token keluaran | 70 | 79 |
| Maksimum token keluaran | 142 | 93 |

Token keluaran mencakup EOS dan token khusus lain yang dihasilkan, tetapi tidak mencakup token awal decoder atau padding. Prompt terperinci menambah 261 token input per artikel. Artikel #29 memiliki 3.266 token penuh dan kehilangan 194 token ketika dibatasi pada 3.072; ringkasannya tetap identik pada kedua prompt.

#### Mengapa batas keluaran 192 dipertahankan

Pada prompt singkat, satu keluaran teramati sepanjang 142 token sehingga panjang tersebut tidak dapat ditampung oleh batas 128. Seluruh keluaran berhenti alami pada pengujian langsung dengan batas 192. Nilai 160 memang melebihi semua panjang yang teramati, tetapi belum diuji sebagai konfigurasi generasi tersendiri. Dengan demikian, 192 dipilih sebagai batas yang sudah diuji pada korpus dan prompt ini, bukan sebagai batas minimum universal.

#### Arti 55 keluaran yang identik

Sebanyak 55 pasangan ringkasan identik dan 18 berbeda. Dari 55 pasangan identik, 48 menyalin potongan berurutan dari artikel sumber secara persis. Audit generasi tidak menemukan bukti penggunaan referensi atau keluaran lama sebagai input. Pengulangan independen pada enam artikel menghasilkan 12 dari 12 keluaran yang sama persis dengan rekaman sebelumnya. Pemeriksaan ini mendukung hasil eksperimen yang tersimpan, tetapi bukan audit terhadap korpus pralatih model. [S7]

### 5 Evaluasi kualitas kedua pendekatan

Evaluasi mencakup 146 ringkasan dan 292 pasangan ringkasan–referensi. GPT dan Gemini digunakan sebagai referensi silver buatan AI dan dinilai secara terpisah. ROUGE dan BERTScore mengukur kesesuaian terhadap referensi; AlignScore membandingkan ringkasan dengan artikel; FKGL mengukur perkiraan kesulitan baca permukaan. [S6]

| Metrik dan acuan | Singkat | Terperinci | IK 95% selisih |
| --- | --- | --- | --- |
| ROUGE 1 F1 / GPT | 0,3267 | 0,3239 | [-0,0172; +0,0130] |
| ROUGE 2 F1 / GPT | 0,1454 | 0,1430 | [-0,0171; +0,0117] |
| ROUGE L F1 / GPT | 0,2479 | 0,2481 | [-0,0130; +0,0146] |
| BERTScore F1 / GPT | 0,8819 | 0,8821 | [-0,0026; +0,0039] |
| ROUGE 1 F1 / GEMINI | 0,2681 | 0,2618 | [-0,0177; +0,0051] |
| ROUGE 2 F1 / GEMINI | 0,1055 | 0,1018 | [-0,0120; +0,0049] |
| ROUGE L F1 / GEMINI | 0,1937 | 0,1905 | [-0,0130; +0,0068] |
| BERTScore F1 / GEMINI | 0,8727 | 0,8727 | [-0,0021; +0,0029] |
| AlignScore / artikel | 0,9726 | 0,9755 | [-0,0004; +0,0072] |
| FKGL / ringkasan | 11,2663 | 10,9216 | [-0,6373; -0,0767] |

Skor adalah rata-rata per artikel pada 73 artikel. Interval kepercayaan (IK) menyatakan selisih terperinci dikurangi singkat. Nilai lebih tinggi diharapkan untuk ROUGE, BERTScore, dan AlignScore; nilai FKGL lebih rendah menunjukkan perkiraan kesulitan baca yang lebih rendah. Angka dibulatkan empat desimal.

Seluruh interval selisih ROUGE/BERTScore dan AlignScore mencakup nol. Karena itu, belum ada keunggulan yang jelas pada dimensi tersebut. FKGL turun sekitar 0,345 tingkat kelas, dengan interval [−0,6373; −0,0767]. Temuan ini mendukung penurunan kecil pada kesulitan baca permukaan, tanpa membuktikan peningkatan pemahaman pembaca.

Interval dihitung melalui 10.000 bootstrap berpasangan pada tingkat artikel dengan seed 20261101. Interval bersifat per metrik, tanpa koreksi pengujian berganda atau skor gabungan kualitas. Analisis sensitivitas pada 72 artikel, setelah mengeluarkan artikel #29 dari kedua kondisi, menghasilkan interpretasi yang sama.

Atas dasar hasil tersebut, prompt singkat dipilih karena penggunaan input lebih hemat dan seluruh artikel tertampung, sementara skor kualitasnya secara umum sebanding. Prompt terperinci tetap menjadi alternatif bila penurunan FKGL menjadi prioritas, dengan konsekuensi kebutuhan input lebih besar.

### 6 Prompt yang dipilih dan batas interpretasi

Teks berikut adalah prompt singkat yang digunakan pada eksperimen dan dipilih untuk konfigurasi berikutnya. Placeholder {article_text} diisi dengan judul, titik dan spasi, lalu isi full_body. Teks bahasa Inggris dipertahankan sesuai rekaman eksperimen. [S4]

```text
Summarize the following cryptocurrency news for readers with no knowledge of cryptocurrency, blockchain, or finance.
Write 2–3 short sentences that clearly explain what happened, who was involved, and the most important facts.
Use simple everyday language. Briefly explain unfamiliar technical concepts when necessary for understanding.
Preserve important names, numbers, and facts. Distinguish confirmed information from claims or possibilities.
Only include information supported by the article. Do not invent explanations, speculate about consequences, or provide investment advice.
Output only the summary.
Article:
{article_text}
Summary:
```

#### Batas kesimpulan yang perlu dipertahankan

Korpus ini terdiri atas 73 artikel yang berulang kali diperiksa selama pengembangan prompt. Hasil merupakan perbandingan pada dataset pengembangan dan belum menunjukkan kemampuan generalisasi pada berita yang belum pernah diperiksa.

EOS sebelum batas hanya menunjukkan bahwa model berhenti sebelum jatah token habis. Artikel #37 menghasilkan 142 token dengan awalan “Output:” dan penutup “[...]”; artikel #28 masih memuat teks newsletter dan penjelasan yang berakhir dengan “200-day...”. Keduanya menunjukkan bahwa batas token yang cukup belum menjamin ringkasan lengkap atau patuh pada target 2–3 kalimat.

AlignScore menilai konsistensi terhadap artikel, bukan kebenaran dunia nyata, dan dapat memberi skor tinggi pada teks yang disalin. FKGL tidak mengukur pemahaman pengguna, kelengkapan fakta, atau keberhasilan menjelaskan istilah teknis. Referensi GPT dan Gemini juga bukan gold standard manusia. Evaluasi ini tidak membuktikan peningkatan literasi atau penurunan FOMO.

Evaluator AlignScore sendiri memiliki batas internal 512 token: 24 dari 367 pasangan potongan sumber dan kalimat mengalami pemotongan, mencakup 13 dari 91 pasangan artikel–ringkasan unik. Hal ini berbeda dari satu pemotongan input FLAN pada prompt terperinci dan tetap menjadi keterbatasan pengukuran. [S6]

### 7 Sumber data dan keterlacakan

Seluruh jalur berikut relatif terhadap folder proyek Pragma. Rekaman eksperimen dan CSV per artikel menjadi sumber angka pada tabel; laporan ini tidak menjalankan ulang generasi atau mengubah dataset.

S1  Eksperimen input dan dasar pemilihan 3.072

output/flan_evaluation/token_selection_evidence_20261030/README.md

S2  Eksperimen keluaran 64 96 dan 128

output/flan_evaluation/output_comparison/run_20261029_123618_149215/README.md

S3  Perbandingan panjang input antarsnapshot

output/flan_evaluation/rs_input_tokens_20261101T085134_690621Z/ANALYSIS.md

S4  Prompt singkat dan pengukuran keluaran RS

output/flan_evaluation/rs_output_lengths/run_20261101T125023_557980Z/

S5  Prompt terperinci dan perbandingan berpasangan

output/flan_evaluation/rs_output_lengths/run_20261101T130452_832310Z/

S6  Evaluasi dua referensi konsistensi dan keterbacaan

output/flan_evaluation/dual_reference_evaluation/run_20261101T153358_903997Z/

S7  Audit keluaran identik dan pengulangan independen

output/flan_evaluation/leakage_audit/replay_20261101T144614_387153Z/

Di S4 dan S5, prompt_template.txt menyimpan instruksi persis dan summaries_and_lengths.csv memuat seluruh keluaran beserta tokennya. Di S6, per_article_evaluation.csv memuat 146 baris kandidat; paired_statistics.json memuat perbedaan dan interval; reference_summaries_frozen.csv menyimpan kedua referensi.

Model eksperimen: google/flan-t5-base revisi 7bcac572ce56db69c1ea7c8af255c5d7c9672fc2. Generasi memakai CPU float32, empat thread, seed 0, Torch 2.13.0, dan Transformers 5.14.1. Metadata implementasi scraper berada pada rss_scrape_scheduler.py dan konfigurasi aplikasi pada ai_models/flan_t5.py.

#### Rujukan metode evaluasi

[Zha et al. 2023 — AlignScore](https://aclanthology.org/2023.acl-long.634/)

[Goldsack et al. 2024 — BioLaySumm 2024](https://aclanthology.org/2024.bionlp-1.10/)

[Tanprasert dan Kauchak 2021 — Flesch Kincaid is not a text simplification evaluation metric](https://aclanthology.org/2021.gem-1.1/)

BioLaySumm mendukung pemisahan relevansi, keterbacaan, dan konsistensi faktual sebagai dimensi evaluasi. Perbedaan domain biomedis dan cryptocurrency tetap perlu diperhatikan.


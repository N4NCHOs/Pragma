# Review pilot output FLAN — 24 Oktober 2026

Review kualitatif berbantuan AI terhadap sumber yang dibekukan, bukan penilaian
manusia independen, silver reference, ROUGE/BERTScore, atau pemeriksaan kebenaran
berita di dunia nyata. Kutipan di bawah adalah output model yang teramati.

## Hasil teknis

18/18 trial selesai tanpa error pada CPU, float32. Model dan tokenizer dimuat
sekali dari cache lokal; prompt, enam artikel, dan input limit 3.072 tetap sama.
Input aktual 597–2.071 token; tidak ada input terpotong.

| Output ceiling | Trial | EOS sebelum ceiling | Output mencapai ceiling | Rerata token isi |
| --- | ---: | ---: | ---: | ---: |
| 64 | 6 | 6 | 0 | 31,5 |
| 96 | 6 | 6 | 0 | 31,5 |
| 128 | 6 | 6 | 0 | 31,5 |

Pada setiap artikel, ketiga batas menghasilkan teks yang persis sama. Token
isi berkisar 25–42; setelah EOS dihitung, panjang output terpilih 26–43 token.
Langkah pencarian beam global 29–59, juga di bawah batas terkecil 64.
Semua output merupakan satu kalimat lengkap secara tata bahasa dan berakhir
dengan tanda titik, tetapi kelengkapan konteks berbeda dari kelengkapan kalimat.

Pemeriksaan substring terhadap `full_body` menunjukkan **6/6 ringkasan adalah
salinan kalimat persis dari sumber**. Temuan ini hanya berlaku untuk pilot ini;
bukan klaim bahwa model selalu ekstraktif pada semua data.

## Review per artikel

### 1. Bitcoin ETF / BlackRock

ID: `d88ecdbfd283769b367268dc7b7c14f411851af8ea5ea97875a08925af8bf1d4`

> U.S. spot bitcoin ETFs added $526.6 million on Monday, led entirely by BlackRock’s IBIT net inflow of $665.2 million.

35 token isi; EOS pada token baru ke-36. Angka, organisasi, dan peristiwa
didukung sumber. Namun `ETFs`, `IBIT`, dan `net inflow` tidak dijelaskan.
Tanpa konteks penarikan pada fund lain, pemula dapat bingung mengapa kontribusi
BlackRock lebih besar daripada jumlah neto seluruh fund. Menyalin bullet pertama.

### 2. Tether / Mural

ID: `5c5fbb2ad4e363114002acb9a7ece8d2de59b94151909d7e1cbd82c0b33d90ac`

> Tether led a $15 million Series A funding round for Mural, bringing the financial infrastructure company’s total funding to $28 million.

30 token isi; EOS ke-31. Perbedaan pendanaan putaran ini dan total pendanaan
terjaga. Hubungan Mural dengan pembayaran berbasis AI tidak disebutkan;
`Series A` dan `financial infrastructure` masih abstrak bagi pemula.
Menyalin bullet pertama, bukan menulis ulang dengan bahasa sederhana.

### 3. Ethereum Glamsterdam / Hoodi

ID: `269a4ac2559e1cc75c9fa61e579a0f0daa4e465ae57413d703fa7e90f07cae76`

> Developers canceled Monday's Hoodi activation after researchers showed how new gas rules could let smart contracts permanently record failed operations.

27 token isi; EOS ke-28. Kata `could` mempertahankan kemungkinan, bukan mengklaim
eksploitasi sedang terjadi. Namun Ethereum/Glamsterdam tidak disebut, Hoodi tidak
dijelaskan sebagai jaringan uji, dan `gas`/`smart contracts` tidak disederhanakan.
`Canceled activation` berasal dari subtitle sumber; jangan menafsirkannya sebagai
pembatalan seluruh upgrade. Output menyalin subtitle itu.

### 4. Proposal finality Ethereum

ID: `544307a0609c50dd807ec9a6888fdce4ccfa2b63d79499f6e5fed5ce82b47fdf`

> Faster finality could reduce costs for cross-chain transfer services by allowing them to recover and reuse funds more quickly.

25 token isi; EOS ke-26. Konsekuensi yang disebut memang ada dalam sumber dan
`could` dipertahankan. Tetapi output tidak menyebut Ethereum, perubahan 16 ke
empat menit, atau bahwa ini proposal tanpa tanggal aktivasi. `Finality` dan
`cross-chain` tidak dijelaskan. Ini kalimat gramatikal utuh, tetapi konteks
peristiwa utamanya tidak cukup untuk pembaca yang hanya melihat ringkasan.
Menyalin bullet kedua.

### 5. Google Willow / Bitcoin

ID: `78adaf032c25de397f75d390ed0ebe2299a8c3ba73b16f54633d6d2d19c94817`

> Google says its Willow chip can prepare the special quantum states needed for advanced calculations with about 40 times fewer errors, reducing one of the hardware bottlenecks behind any future attempt to crack bitcoin wallets.

42 token isi; EOS ke-43. Atribusi Google, angka 40 kali, Bitcoin, dan sifat
ancaman masa depan dipertahankan sesuai sumber. Tidak mengatakan serangan
sudah mungkin dilakukan atau biaya serangan turun 40 kali. Namun kalimat
panjang ini mempertahankan istilah teknis dan tidak menyertakan keterbatasan
eksperimen seperti tingkat keberhasilan sekitar 8%. Itu adalah kekurangan
cakupan/konteks, bukan bukti angka yang disebut salah. Menyalin subtitle sumber.

### 6. OCC / stablecoin rewards

ID: `8b38d00ac6012f9c741d1e711f04aea939463019d0f2ea72ad3e9d4774c5c331`

> The U.S. Office of the Comptroller of the Currency is the first of several federal agencies to finish writing regulations under the act.

30 token isi; EOS ke-31. Kalimat didukung sumber, tetapi `the act` tidak dijelaskan
dan stablecoin, GENIUS Act, serta persoalan rewards yang menjadi inti artikel
tidak disebutkan. Kalimat lengkap secara tata bahasa, tetapi kurang bermakna
sebagai ringkasan mandiri untuk pemula. Menyalin subtitle sumber.

## Interpretasi dan keputusan yang belum diambil

Tidak ada nasihat investasi atau prediksi harga dalam enam teks output ini.
Tidak ditemukan pemotongan output akibat ceiling pada pilot ini. Menaikkan
ceiling menjadi 96/128 tidak memperbaiki teks, cakupan, atau jargon karena teks
outputnya identik dengan ceiling 64.

**Rekomendasi sementara:** 64 cukup sebagai baseline output untuk keenam
artikel ini. Jangan mengklaimnya optimal secara umum atau menguncinya otomatis
untuk seluruh penelitian. Pengguna masih perlu menyetujui keputusan checkpoint
berikutnya. Keberhasilan abstraksi dan keterbacaan untuk pemula belum tercapai
secara konsisten; memperbesar output ceiling bukan solusi yang terbukti di sini.

Tidak ada prompt/model yang diubah untuk mengejar hasil lebih baik. Jika nanti
prompt atau pendekatan diubah atas persetujuan pengguna, perlakukan sebagai
kondisi eksperimen baru dan ulangi pilot secara eksplisit sebelum perbandingan
utama. Untuk sekarang hasil tetap baseline dari prompt yang disepakati.

Rerata waktu per ceiling sekitar 3,92 / 3,88 / 3,69 detik pada run ini; satu
pengamatan per pasangan dan urutan tidak diacak. Jangan menyimpulkan ceiling
lebih tinggi lebih cepat. Waktu memuat model dan warmup dicatat terpisah.

Peringatan pemuatan terkait tied weights dicatat di README; config tidak
diubah. Pengaruh peringatan tersebut tidak ditentukan oleh review ini.

199 tes offline lolos dan artefak run nyata diperiksa ulang untuk kesesuaian
hash, ID, input lengkap, token output/EOS, dan kesamaan hasil antarbatas.
Integrasi preprocessing realtime tetap **HIGH PRIORITY / PENDING**.

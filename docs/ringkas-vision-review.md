# Checkpoint Fase 5 — beat visual dan vision Ringkas

19 November 2026. Setelah persetujuan checkpoint anotasi, Ringkas kini dapat mengaitkan sampel gambar dengan langkah tutorial, di samping transkrip. Semua opsi berupa kontrol fungsional dasar; pilihan Mantine untuk pekerjaan UI berikutnya tetap berlaku.

## Cara mencoba

1. Jalankan ulang aplikasi agar migrasi `e6a248cf0912` dijalankan. Buat output baru mode Ringkas pada sumber yang sudah memiliki transkrip.
2. Pilih **Transkrip dan frame (vision)**. Untuk rekaman layar aktifkan sampel hingga 1024 px; tentukan **Batas frame vision** (bawaan 720). Mode transkrip tetap tersedia sebagai bawaan.
3. Setelah `awaiting_review`, buka **Bukti visual Ringkas**. Periksa timestamp sumber, gambar, deskripsi, teks layar serta penanda ketidakpastian. Form menampilkan maksimal 12 frame; laporan JSON menyediakan seluruh frame dan URL gambar.
4. Buka **Keputusan per beat** untuk membaca narasi, deskripsi visual, label dan spesifikasi. Tonton sumber asli untuk memeriksa konteks di antara sampel. Bab wajib, kunci keputusan dan solver tetap dapat digunakan.
5. Setujui dan render. Beat visual mempertahankan audio sumber; deskripsi AI tidak dibakar menjadi caption. ZIP memuat metadata laporan vision dan garis waktu yang menandai beat visual.

Untuk provider nyata, atur model gambar milik akun/layanan Anda:

```dotenv
LLM_PROVIDER=gemini
LLM_MODEL_FAST=model-teks-yang-tersedia
LLM_MODEL_VISION=model-gambar-yang-tersedia
```

Provider dapat pula Anthropic atau Ollama. Model vision kosong memakai `LLM_MODEL_FAST`, yang harus mendukung gambar bila vision dipilih. Model teks tetap digunakan untuk anotasi/outline. Untuk Ollama, `OLLAMA_NUM_CTX` bawaan 16384 dapat disesuaikan dengan model dan RAM, terutama untuk outline panjang. Mode mock memberi deskripsi fixture yang secara eksplisit belum menilai gambar.

## Mekanisme dan perlindungan

- Satu kalimat menjadi beat bicara. Rentang di luar kalimat ≥1,5 detik menjadi beat visual, dipotong pada cut sampel dan maksimal 20 detik. Jeda transkrip belum berarti tidak ada suara; audio dijaga.
- Analisis lokal streaming 2 fps pada 160×90 menghasilkan aktivitas 0–1 dan cut kasar (resolusi waktu sekitar 0,5 detik), dengan cache checksum sumber. Aktivitas bukan skor kepentingan atau pengenalan objek.
- Sampling visual per 5 detik, bicara per 15 detik, minimal satu per beat. Gambar tidak di-upscale; batas tinggi 1024. Standar memakai maksimal 16 gambar/panggilan, layar 8. Memori gambar dibatasi per batch.
- Melebihi budget frame menghentikan proses **sebelum LLM**. Buat output baru dengan batas yang sesuai atau mode transkrip; sumber/analisis lokal tetap memakai cache. Batas 720 dapat dinaikkan hingga 4096 secara eksplisit.
- Model hanya mengembalikan ID yang tersedia. ID hilang/rekaan/duplikat, bab tumpang tindih/tidak lengkap, atau nilai spesifikasi yang tidak muncul verbatim dalam narasi/teks layar ditolak. OCR model masih memerlukan tinjauan manusia.
- Kode menambahkan spesifikasi, instruksi pertama dan hasil ≥2 detik ke penanda wajib. Beat visual yang belum jelas juga dilindungi dalam bab wajib. Pengguna dapat mengubah kewajiban bab secara eksplisit.
- Batch anotasi mencakup maksimal 15 menit, 40 beat dan sekitar 16 KB bukti. Bukti satu beat yang terlalu besar memerlukan segmentasi yang diperbaiki. Outline global memakai ringkasan; model tetap harus memiliki konteks yang cukup.
- Retry memakai cache balasan yang sudah lolos schema serta validasi domain. Gambar rusak dipulihkan; perubahan hash gambar, model, prompt, schema atau input membuat key berbeda. API key dan base64 gambar tidak dicatat dalam log penggunaan.
- Hasil lama mendapat evidence `{}` melalui migrasi tanpa membangun ulang tabel beat. Keputusan/kunci lama dan part cache legacy tetap dapat dipakai.

Payload mengikuti kontrak resmi [Gemini Content/inlineData](https://ai.google.dev/api/caching), [Anthropic image content blocks](https://platform.claude.com/docs/en/build-with-claude/vision), dan [Ollama REST images](https://docs.ollama.com/capabilities/vision). Tidak ada unggah seluruh video atau SDK provider tambahan.

## Pemeriksaan

Suite backend penuh **125 lulus**; browser **5 alur lulus**. Pemeriksaan meliputi beat tanpa overlap, pembagian jeda/cut/20 detik, sampling sumber, budget sebelum LLM, transport JPEG tiga provider dengan model terpisah, penolakan ID/nilai rekaan, spesifikasi yang dilindungi, migrasi beat lama terkunci, pemulihan cache, dan render setelah tinjauan tanpa panggilan ulang. Build produksi web serta pemeriksaan Python/TypeScript berhasil.

Pemeriksaan tambahan setelah memperkuat pemulihan metadata sampel: **20 tes vision/LLM/migrasi lulus**. Image API/worker dan web produksi berhasil dibangun; smoke empat layanan melalui proxy web menghasilkan 4 frame, 1 beat visual, serta video 12,021 detik dari sumber sintetis 12 detik. JPEG, tahap tinjau, metadata vision dalam ZIP dan rentang visual pada timeline terverifikasi. Laporan tersimpan pada `data/phase5-vision-validation/docker-smoke.json`; layanan/volume tes dibersihkan setelah pemeriksaan. Evaluator tetap `quality_status: not_run` dengan nol sumber manusia.

Sampel Indonesia 75 detik dari Fase 1 menghasilkan **16 beat bicara, 3 beat visual, 19 frame hingga 1024×576, 7 bab fixture** dalam sekitar 2 detik lokal untuk analisis/sampling dan mock. Ini tidak mencakup latensi cloud atau render dan tidak mengukur akurasi vision. Laporan: `data/phase5-vision-validation/native-report.json`; bukti lengkap: `data/phase5-vision-validation/native/outputs/native-review/vision.json` beserta direktori `vision-frames/`.

Sumber contoh: Wikimedia Indonesia/Raymond Sutanto, [Membatalkan penghapusan halaman di Wikipedia (2)](https://commons.wikimedia.org/wiki/File:Membatalkan_penghapusan_halaman_di_Wikipedia_(2).webm), [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); metadata atribusi tersimpan pada `data/phase1-validation/attribution.json`. Pengujian mengambil cuplikan 75 detik, mengecilkan gambar dan menambahkan metadata sampel; deskripsi mock bukan penilaian sumber.

## Batas dan kelanjutan

Kualitas label/objek/tangan provider nyata belum diukur; tes transport memakai respons uji dan workflow memakai mock. Snapshot dapat melewatkan aksi singkat dan tidak menjamin pelacakan objek sepanjang langkah. Jalur ingest masih memerlukan minimal satu kalimat transkrip, sehingga video yang sepenuhnya tanpa transkrip belum didukung. Frame budget bukan jaminan biaya rupiah atau kecukupan konteks semua model.

Timelapse, pengelolaan audio timelapse, pemeriksaan koherensi, kartu bab, QC Ringkas setara Klip, dataset manusia/provider nyata, serta benchmark satu jam tetap terbuka. Fase 5 belum selesai; berhenti pada checkpoint ini untuk tinjauan sebelum melanjutkan pekerjaan tersebut.

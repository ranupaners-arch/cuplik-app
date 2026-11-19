# Perbaikan hasil review — caption dan pembingkaian adaptif

Tindak lanjut: koreksi ini telah disetujui pengguna dan dikembangkan menjadi [renderer Fase 3](phase-3-review.md), termasuk pelacakan per frame, karaoke, retensi dan QC akhir. Catatan di bawah merekam hasil koreksi sebelumnya.

19 November 2026. Pengguna menilai klip Fase 2 terlalu penuh subtitle dan isi video kurang jelas. Perbaikan ini menindaklanjuti hasil review tersebut; ini belum menyelesaikan seluruh Fase 3 dan tidak menerapkan design system aplikasi.

## Perubahan hasil

Masalah berasal dari renderer fondasi: semua sumber dipotong ke tengah menjadi 9:16, satu kalimat panjang tampil sekaligus, dan hook yang mengulang kalimat itu muncul bersamaan. Pemutar berukuran 270 px juga menyulitkan pemeriksaan video layar. Ukuran font minimum 16 px menjadi sangat dominan pada contoh 180×320.

Sekarang:

- Analisis visual otomatis memeriksa maksimal 24 sampel frame dengan model wajah neural **YuNet** dan petunjuk kepadatan teks/tepi. Rekaman layar/slide dan subjek yang belum teridentifikasi dengan yakin mempertahankan seluruh bingkai serta orientasi sumber. Satu wajah dominan yang stabil dapat memakai crop vertikal jika semua wajah yang tersampel beserta marginnya muat. Beberapa wajah atau gerakan lateral yang tidak muat memilih bingkai utuh.
- Caption tampil bergantian sebagai frasa **maksimal tiga kata pada video potret atau lima kata pada video lebar**, maksimal dua baris. Seluruh kata tetap dipertahankan, bukan dirangkum atau dibuang. Jeda dan batas kalimat memisahkan frasa.
- Ukuran huruf mengikuti dimensi hasil. Lebar glyph diukur memakai font yang sama dengan renderer, dan kata yang terlalu panjang diperkecil/diskalakan agar tidak keluar bingkai. Caption mendapat pita bawah terpisah; gambar sumber tidak ditutupi teks.
- Hook tidak tampil pada rekaman layar/konteks umum. Pada video pembicara, hook hanya tampil jika tidak mengulang sebagian besar caption awal, dengan maksimal delapan kata di pita atas tersendiri.
- Batas tinggi default ekspor menjadi **1280**, tetap menghormati resolusi sumber dan konfigurasi `RENDER_HEIGHT` yang dipilih pengguna. Encoder Klip memakai H.264 CRF 20, 30 fps dan AAC 160 kbps. Menaikkan batas tinggi tidak menciptakan detail yang hilang pada sumber beresolusi rendah.
- Pemutar memakai lebar area konten dan tinggi maksimal 75% layar. Pilihan **Otomatis**, **Bingkai sumber utuh**, atau **Vertikal 9:16, pertahankan isi** tersedia pada form dasar dan editor klip. Opsi vertikal memuat sumber utuh bila crop subjek tidak aman.

Frame rekaman layar contoh sekarang **1920×1080**, seluruh antarmuka terlihat, caption satu baris dengan maksimal lima kata dan tanpa hook duplikat. Untuk materi layar, mempertahankan landscape dipilih demi keterbacaan. Pengguna dapat memilih vertikal secara eksplisit.

## AI lokal dan alasan dependensi

OpenCV 5 yang sudah terkunci mendukung `FaceDetectorYN`. Model **YuNet 2026may** dipilih karena input dinamisnya mendukung engine OpenCV 5; varian 2023 menggunakan bentuk input tetap. Tidak perlu menurunkan OpenCV atau mengirim frame ke cloud untuk keputusan dasar ini. Referensi: [README model resmi](https://github.com/opencv/opencv_zoo/tree/26cc381e4d2594bb9f47a26eb8fd96c94a13660d/models/face_detection_yunet).

Bobot 229.738 byte disertakan dalam `worker/assets/yunet/`, sehingga runtime tidak mengunduh model. Manifest menyimpan commit sumber, SHA-256 dan ukuran; lisensi MIT dipertahankan. Tes memastikan checksum, inference sungguhan dan keberadaan bobot/lisensi dalam wheel. Pillow 13.0.0 digunakan untuk [pengukuran glyph](https://pillow.readthedocs.io/en/stable/reference/ImageFont.html#PIL.ImageFont.FreeTypeFont.getlength), bukan untuk membuat aset desain.

Ini analisis visual lokal berbasis sampel, belum pelacakan wajah per frame, OCR isi layar, atau penilaian semantik vision LLM. Fallback ke bingkai utuh mengurangi risiko kehilangan konteks. Wajah yang tidak terdeteksi tidak dijadikan alasan melakukan crop tengah.

## Timestamp, cache dan hasil lama

Caption memakai waktu kata yang sudah ada. Sidecar per kalimat atau koreksi yang mengubah jumlah kata memakai pembagian waktu perkiraan, ditandai melalui `qc.caption_timing`. Ketepatan terhadap ucapan nyata belum diukur manual.

Fingerprint renderer dinaikkan ke versi 2 serta mencakup layout dan profil caption/pembingkaian. Cache internal juga mempertimbangkan sumber dan transkrip. Hasil lama meminta render ulang melalui tombol **Perbarui video klip**; ini menggunakan kembali rencana, sumber dan transkrip, tanpa memanggil LLM atau ASR lagi.

Kolom `Clip.layout` yang sudah ada digunakan kembali, sehingga tidak ada migrasi database baru. Nilai lama `center` diperlakukan sebagai pilihan otomatis saat render ulang. `OutputSettings.layout` dan `ClipPatch.layout` menerima `auto|source|portrait`; OpenAPI dan tipe frontend diperbarui.

## Bukti dan cara mencoba

- [Contoh baru pertama](../data/adaptive-render-review/clip-1.mp4), [kedua](../data/adaptive-render-review/clip-2.mp4), [ketiga](../data/adaptive-render-review/clip-3.mp4).
- [Frame sebelum](../data/render-review/before.png) dan [frame sesudah](../data/render-review/after.png), keduanya pada detik ketiga klip yang sama.
- [Laporan render](../data/adaptive-render-review/report.json), berisi alasan framing, observasi visual, resolusi dan QC.
- [Verifikasi Docker](../data/adaptive-render-review/docker-report.json): inference YuNet, font dan render 1920×1080 nyata sebagai UID 1000; maksimum lima kata/satu baris dan hook tidak tampil.

Tiga contoh dirender ulang dari sumber dan seleksi Fase 2 yang sama, tanpa pemilihan ulang model. Atribusi sumber Wikimedia CC BY-SA tersedia pada `data/phase1-validation/attribution.json`. Pengujian backend mencakup layout layar/pembicara/beberapa wajah, geometri aman, caption per kata, estimasi sidecar, koreksi teks, escaping ASS, ukuran glyph, cache, dan upgrade hasil lama. **62 tes backend dan 2 tes browser lolos**, beserta Ruff, TypeScript, build Next.js, build Docker dan pemeriksaan paket wheel.

Jalankan ulang aplikasi dengan `make dev`, lalu gunakan **Perbarui video klip** untuk hasil lama atau buat output baru dengan pembingkaian otomatis. Jika `.env` sudah berisi `RENDER_HEIGHT=640`, gunakan 1280 untuk batas ekspor baru.

Untuk mereproduksi contoh tanpa API/model transkripsi:

```sh
uv run python scripts/preview_render.py \
  --source data/phase1-validation/indonesian-75s.mp4 \
  --transcript data/phase2-validation/transcript.json \
  --selection data/phase2-validation/selection.json
```

`--layout portrait` menguji komposisi vertikal aman; `--height` mengatur batas tinggi. Hasil ditulis terpisah dari contoh lama untuk perbandingan. Pelacakan per frame, karaoke kata aktif, retensi, loudness, thumbnail dan QC produksi lengkap tetap berada pada sisa Fase 3.

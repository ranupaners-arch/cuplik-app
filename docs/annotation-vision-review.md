# Checkpoint Fase 5 — anotasi dan fokus spasial

19 November 2026. Pengguna menyetujui kelanjutan pekerjaan evaluasi serta fondasi vision, kemudian memilih Mantine untuk UI berikutnya. Bagian ini menambah alur fungsional dengan form standar. Vision semantik Ringkas dan keseluruhan Fase 5 masih terbuka.

## Cara mencoba

1. Jalankan ulang aplikasi dengan `make dev`; supervisor menjalankan migrasi `d58107a2c930` terlebih dahulu.
2. Pada Buat pilih **Siapkan sumber untuk anotasi**, lalu siapkan demo atau unggahan/YouTube. Setelah transkrip selesai, buka `/projects/<id>/evaluate`.
3. Putar sumber; tambahkan rentang momen Klip atau bab/spesifikasi Ringkas memakai detik sumber. Tombol waktu putar membantu mengambil batas. Simpan draft, muat ulang untuk memeriksa persistensi.
4. Isi nama peninjau, pilih **Sudah ditinjau**, dan konfirmasikan pemeriksaan manual. Ekspor ZIP. Demo selalu ditandai sintetis.
5. Buat output dari halaman proyek. Kembali ke anotasi, muat ulang, lalu pilih output selesai sebagai pembanding. Paket mencakup label, transkrip dan prediksi opsional; sumber diunduh terpisah sebagai `source.mp4`. Ikuti [kontrak evaluasi](../eval/golden/README.md).
6. Untuk crop Klip, pilih Shorts dan **Fokus visual → Pilih area manual**. Koordinat berupa persen sumber; kiri + lebar dan atas + tinggi harus ≤100%. Render dan tinjau seluruh klip, terutama saat halaman/adegan berubah. Area berlaku sepanjang klip.
7. **Cari area aktivitas (eksperimental)** mencoba proposal lokal, dengan mode aman tetap bawaan. Periksa alasan pemilihan/fallback dan `focus_frames` pada QC/jejak reframe.

## Perlindungan hasil

- Draft tidak dapat diekspor sebagai label selesai. Tinjauan memerlukan nama, rentang yang valid dan konfirmasi manual; bab/spesifikasi wajib berlabel.
- Revisi dan token checksum melindungi konflik dua tab serta perubahan sumber/transkrip. Penolakan mempertahankan isian lokal dan memfokuskan pesan kesalahan. Membaca anotasi tidak menulis label.
- Perubahan label sesudah prediksi tersimpan menjadi assisted. Penyimpanan identik mempertahankan independensi tinjauan awal. Assisted tetap dapat diekspor untuk analisis, tetapi dikeluarkan dari kualitas independen.
- Rencana output baru terikat pada sumber/transkrip. Retry menolak isi yang berubah sebelum render, mempertahankan MP4 yang sudah ada. Output lama dengan provenance kosong tetap kompatibel untuk penggunaan biasa; evaluasi terverifikasi memerlukan output baru.
- Sumber mendukung HTTP Range untuk pemutar, caption VTT pada waktu sumber, penanda penggunaan TTL, dan penyiapan ulang salinan yang kedaluwarsa. Transkrip yang sudah selesai tetap memakai checkpoint.
- Ekspor terpisah menurut mode/revisi/output, ditulis atomik dengan lock. Prediksi harus selesai, berasal dari proyek/mode yang sama, dan cocok checksum.
- Fokus manual/activity masuk fingerprint hanya saat dipilih; nilai safe mempertahankan fingerprint lama. Kesalahan analisis atau aktivitas ambigu kembali ke framing aman. Crop activity dibatalkan setelah scene/edit cut.

Evaluator Klip tetap memakai IoU ≥0,5 satu-ke-satu. Ringkas memakai cakupan gabungan rentang aktual: ≥90% untuk bab dan ≥99% untuk spesifikasi, serta deviasi MP4 akhir ±3%. Ini pemeriksaan retensi waktu, bukan penilaian semantik/koherensi. Demo, mock, assisted, nama kosong, sumber tidak terverifikasi dan draft tidak menjadi agregat kualitas. Jumlah sumber memakai SHA-256 unik.

## Pilihan UI

Mantine **9.8.1** sudah dipasang pada `web` untuk seluruh paket yang diminta: core/hooks/form/dates/charts/notifications/code-highlight/tiptap/dropzone/emoji/carousel/lightbox/spotlight/modals/nprogress. Paket pendamping: dayjs **1.11.23**, Recharts **3.11.0**, Tiptap **3.34.0**, Embla dan React adapter **8.6.0**.

Satu versi Mantine dan Tiptap menghindari perbedaan peer dependency; React 19.3.1 proyek memenuhi peer React Mantine. Embla 8.6.0 memenuhi `^8.5.2` yang diminta serta peer Carousel/Lightbox, sehingga tidak perlu mengganti major. Versi exact dan lockfile membuat instalasi dapat diulang. `npm ls --depth=0` berhasil, instalasi melaporkan nol kerentanan, tanpa pemaksaan peer dependency. Penerapan Provider/CSS/tema menunggu pekerjaan desain, mengikuti [panduan Next.js Mantine](https://mantine.dev/guides/next/).

## Bukti pemeriksaan

- Suite backend penuh: **113 lulus**. Suite anotasi/migrasi/seleksi: **30 lulus**, termasuk pengecualian/provenance evaluator serta default migrasi lama. Pemeriksaan tambahan bahasa track mengikuti bahasa transkrip aktual saat pilihan sumber `auto`: **11 tes anotasi lulus**.
- Browser Chromium: **4 alur lulus**, termasuk sumber tanpa prediksi, draft/review, ZIP, konflik dua tab dengan isian tetap tersedia, fokus pesan kesalahan, label Ringkas, crop manual Shorts, dan perubahan label menjadi assisted.
- `make types`, `make lint`, `make build`, `make doctor`, `make eval`, `make eval-fixtures` berhasil. Evaluasi golden set tetap `not_run`, nol sumber manusia.
- Image produksi API/worker dan web berhasil dibangun, termasuk `npm ci` dari lockfile Mantine (198 paket diaudit, nol kerentanan). Smoke empat layanan Docker terisolasi lolos melalui proxy web: halaman anotasi, review sebelum prediksi, sumber HTTP Range/VTT, render manual 180×320 dengan 360 frame fokus, MP4, dan ZIP yang cocok provenance. Laporan: `data/phase5-validation/docker-smoke.json`. Layanan/volume tes dibersihkan setelah pemeriksaan.
- Migrasi pada salinan SQLite lokal dari `7f3a10c2d8ab` ke head menjaga **1 proyek, 1 output, 3 klip**, foreign key utuh; default focus/provenance legacy `{}`. Database asli tidak dimigrasikan oleh pemeriksaan ini. Laporan: `data/phase5-validation/migration-copy/report.json`.

Contoh Indonesia memakai sumber Wikipedia/Wikimedia Indonesia yang sudah tersedia dari Fase 1, Raymond Sutanto, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Sumber dan metadata atribusi ada pada `data/phase1-validation/attribution.json`; perubahan contoh berupa pemotongan rentang, crop, caption dan normalisasi audio.

| Contoh | Hasil |
|---|---|
| `data/phase5-validation/manual/clip-1.mp4` | Rentang sumber 9,93–25,17 s; area 15% kiri, 18% atas, 70% lebar, 82% tinggi; 594×1056, 15,267 s; 458/458 frame memakai fokus, QC lulus |
| `data/phase5-validation/activity/clip-1.mp4` | Rentang sama; perubahan gambar terlalu besar, proposal ditolak dan 458 frame mempertahankan sumber utuh dengan latar blur; QC lulus |

Kedua contoh memakai caption maksimal tiga kata/satu baris, tanpa hook duplikat, tanpa LLM/ASR ulang. Loudness akhir −14,27 LUFS dan −1,43 dBTP. Waktu lokal masing-masing sekitar 8,9 s dan 12,9 s termasuk analisis/encode/QC; ini sampel pendek Linux ARM64, belum benchmark Mac/video satu jam. Rekaman layar yang penuh teks tetap perlu tinjauan keterbacaan dan pemilihan langkah; crop manual bukan bukti AI memahami tugas.

## Pekerjaan berikutnya setelah tinjauan

Kumpulkan dataset independen 10 sumber Klip/5 sumber Ringkas, lalu ukur kualitas dengan provider nyata. Vision berikutnya perlu mendeteksi perubahan layar/tangan/objek yang berkaitan dengan langkah, mengaitkannya ke beat, dan menjaga konteks sepanjang adegan. Timelapse, koherensi, kartu bab serta gate performa/sinkron manual tetap terbuka. Checkpoint ini tidak menyatakan seluruh Fase 5 selesai.

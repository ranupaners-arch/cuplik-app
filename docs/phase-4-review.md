# Checkpoint Fase 4 — kontrol Klip

19 November 2026. Implementasi kontrol Fase 4 dan pengujian fungsional selesai, mengikuti [riset video pendek/tutorial](research-short-tutorial-2026-11-19.md). Gate kualitas/performa MVP yang memerlukan dataset manusia dan perangkat Mac belum terpenuhi. Berhenti untuk pemeriksaan pengguna sebelum Fase 5. Antarmuka tetap form dasar.

## Perilaku yang dapat dicoba

1. Buka **Preferensi**. Simpan default Klip dan Ringkas secara terpisah: jumlah/rentang durasi klip, tujuan, platform, caption, fokus, target Ringkas, serta kecepatan bicara. Default diterapkan pada output baru; perubahan per klip tetap terpisah.
2. Buat output dari sumber baru atau proyek yang sudah ada. **Tutorial** menjaga jeda, pengisi, dan pembesaran gambar secara bawaan. **Jangkauan** menyediakan profil retensi yang lebih aktif. Teknik dapat disunting per klip.
3. Pilih **Video YouTube / rasio sumber** untuk menjaga rekaman layar lebar. Target **YouTube Shorts**, **TikTok**, atau **Instagram Reels** memakai kanvas 9:16. Pembingkaian otomatis/vertikal mengatur bagaimana isi dimuat pada kanvas tersebut.
4. Pada hasil, buka **Edit judul, hook, dan caption**. Pilih salah satu dari dua judul/hook, ubah awal/akhir, koreksi kata, dan tekan **Simpan dan render ulang klip**. Batas ditempel ke timestamp kata terdekat; tanpa timestamp kata dipakai batas kalimat. Durasi setelah snap harus 1–180 detik.
5. Koreksi kata tidak mengubah waktu ucapan dan disimpan dalam `caption_overrides` memakai ID `w…`. Koreksi kalimat `s…` lama tetap didukung. Jika jumlah kata pada koreksi kalimat berubah, waktunya ditandai sebagai estimasi; UI menawarkan pemulihan kata asli sebelum trim yang ambigu.
6. Koreksi kata dapat ditambahkan ke glosarium dengan tombol tersendiri. Glosarium juga dapat ditambah, diubah, dan dihapus dari Preferensi. Pengaruh glosarium berlaku pada proyek baru; transkrip yang sudah selesai tetap memakai cache.
7. Beri **Suka/Tidak suka** dan catatan. Maksimal tiga contoh suka dengan tujuan serupa dipakai pada pemilihan berikutnya. Mengubah penilaian tidak membuat MP4 perlu dirender ulang.

Jalankan ulang API/worker/web untuk memuat kode terbaru. Startup API menjalankan Alembic. Hasil lama dengan fingerprint berbeda dapat diperbarui melalui **Perbarui video klip**; rencana seleksi serta transkrip dipakai kembali.

## Kontrak dan kompatibilitas

- `GET/PUT /api/preferences`: default per mode. Field request output yang eksplisit menimpa default tersimpan; patch retensi hanya menimpa teknik yang dikirim. Kombinasi durasi/platform/framing diperiksa setelah penggabungan.
- `PATCH /api/clips/{id}`: tujuan, platform, retensi, caption, rating/catatan, serta `start_s/end_s`. Input tidak valid dibatalkan seluruhnya. Batas yang diedit ditandai; skor/alasan tetap berasal dari pilihan awal dan UI menjelaskannya.
- `POST /api/clips/{id}/render`: hanya klip itu. Fingerprint v4 mencakup tujuan/platform dan koreksi kata. Unduhan MP4/ZIP yang belum sesuai pengaturan tetap ditolak sampai render selesai.
- Migrasi `c841b29d1104` menambah `Clip.purpose` dan `Clip.platform`. Hasil lama menjadi `discovery/youtube`; tidak dilabeli Shorts diam-diam. Retensi lama tidak diubah. Tidak ada perubahan schema Preference karena kolom JSON dan preset sudah tersedia.
- Keluaran video pendek menggunakan tinggi kelipatan 32 agar kedua dimensi genap dan rasio 9:16 tepat. QC memeriksa dimensi stream dan durasi file akhir, termasuk batas 180 detik profil ini. Pemeriksaan format tidak membuktikan kelayakan seluruh kebijakan platform atau menjamin distribusi.
- Prompt menerima tujuan dan platform; pemilihan tutorial diarahkan menjaga tugas, prasyarat, langkah minimum, serta hasil. Ini belum merupakan verifikasi otomatis kelengkapan tutorial atau probabilitas viral.

## Pengujian

| Pemeriksaan | Hasil |
| --- | --- |
| `make test` | 89 tes backend, termasuk regresi migrasi, caption, trim, cache, retensi dan cleanup |
| `make lint` | Ruff, pemeriksaan format Python, dan TypeScript lolos |
| `make types` | OpenAPI dan tipe frontend diperbarui |
| `npm run build --prefix web` | Build produksi native lolos |
| `make e2e` / Playwright | Tiga skenario browser lolos: dua mode, ingest/cache/glosarium, serta preferensi/kata/trim/Shorts/rating |
| Docker | Image API/worker/web dibangun; empat layanan menjalankan workflow melalui proxy web dengan mock LLM |
| Migrasi data lama | Salinan database native dari revisi `7f3a10c2d8ab` naik ke `c841b29d1104`: 1 Project, 1 Output, 3 Clip tetap ada; foreign key bersih; database asli tidak diubah oleh pemeriksaan ini |
| `make eval` | Perintah berhasil, kualitas **not_run**, 0 video manusia; bukan bukti kualitas editorial |
| `make eval-fixtures` | Fixture sintetis lolos; recall setelah rerank 1,0 pada fixture ini saja |

Tes membuktikan bahwa koreksi `w2` mempertahankan timestamp, trim menempel ke batas kata, render ulang tidak memanggil LLM/transkripsi/download ulang, serta checksum/mtime MP4 klip lain tetap sama. Sumber, transkrip, dan log LLM juga tetap sama. Koreksi kalimat lama yang dapat dipetakan diubah menjadi koreksi kata saat trim; koreksi dengan waktu ambigu ditolak secara atomik.

Browser menguji penyimpanan preferensi setelah reload, penerapannya pada output baru, koreksi per kata, trim, karaoke, rasio aktual, penambahan glosarium, rating/catatan, serta penggunaan contoh suka pada job berikutnya. Tes menunggu fingerprint video terbaru dan kontrol aktif sebelum interaksi selanjutnya; status API selesai dapat mendahului pembaruan tampilan SSE.

Smoke Docker dapat diulang pada deployment mock terisolasi:

```sh
uv run python scripts/validate_controls.py --base-url http://localhost:3000
```

Script membuat proyek demo dan memulihkan preferensi sebelumnya setelah pengujian. Ia memeriksa platform vertikal, render ulang ke bingkai sumber, koreksi caption, rating/catatan, MP4, thumbnail, ZIP, dan SSE. Laporan sesi tersedia di `data/phase4-validation/docker-smoke.json`. Layanan/volume Docker khusus pengujian dibersihkan setelah selesai.

## Dua keluaran dari video Indonesia yang sama

| Profil | Resolusi | Durasi akhir | Caption | Hasil QC |
| --- | --- | --- | --- | --- |
| Tutorial YouTube, bingkai sumber | 1920×1080 | 15,267 detik | Maksimal 5 kata / 1 baris | Lolos; −14,27 LUFS, −1,43 dBTP |
| Tutorial pada kanvas Shorts | 594×1056, tepat 9:16 | 15,267 detik | Maksimal 3 kata / 1 baris | Lolos; −14,27 LUFS, −1,43 dBTP |

Kedua contoh mempertahankan rentang sumber 9,93–25,17 detik tanpa membuang jeda atau pengisi. Sumber dan transkrip berasal dari validasi sebelumnya; tidak ada panggilan LLM/ASR baru. Hasil ada di [tutorial/clip-1.mp4](../data/phase4-validation/tutorial/clip-1.mp4) dan [shorts/clip-1.mp4](../data/phase4-validation/shorts/clip-1.mp4), beserta `report.json`, EDL, caption, framing, thumbnail, serta jejak reframe di direktori masing-masing.

Pemeriksaan frame menunjukkan contoh 16:9 menjaga detail antarmuka. Pada versi vertikal, seluruh desktop memang masih kecil karena dipertahankan utuh. Versi tersebut mendemonstrasikan format ekspor, **belum membuktikan tutorial layar nyaman dibaca di ponsel**. UI/QC memberi catatan keterbacaan dan pilihan rasio sumber. Pemilihan area layar/tangan/objek berdasarkan adegan serta perlindungan aktivitas visual merupakan pekerjaan vision berikutnya, belum diimplementasikan dalam fase kontrol ini.

Atribusi video: *Membatalkan penghapusan halaman di Wikipedia (2)*, Wikimedia Indonesia; deskripsi sumber menyebut Raymond Sutanto. [Halaman sumber](https://commons.wikimedia.org/wiki/File:Membatalkan_penghapusan_halaman_di_Wikipedia_(2).webm), [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Contoh merupakan adaptasi berupa potongan, pembingkaian, caption, dan normalisasi audio, dengan lisensi yang sama. Metadata atribusi tersimpan pada `data/phase1-validation/attribution.json`.

## Kebijakan cache dan batas MVP

Worker memeriksa salinan `source.mp4` setiap jam dan menghapus yang tidak dipakai lebih dari `SOURCE_CACHE_DAYS` (default 14). Penanda penggunaan terpisah menjaga mtime sumber sehingga retry biasa tetap memakai cache render. Lock sumber melindungi ingest/render; task pending/enqueued/running menunda pembersihan. Salinan upload hanya dibersihkan jika unggahan `.bin` asli masih tersedia. Audio, transkrip/checkpoint, unggahan asli, dan output tidak dihapus.

Sesudah kedaluwarsa, sumber dipulihkan dari unggahan asli, demo, atau unduhan ulang URL. URL perlu tetap tersedia; jika byte sumber berubah, transkrip lama tidak dipakai seolah-olah masih cocok. Tes memverifikasi sumber upload pulih tanpa transkripsi ulang. Kebijakan ini bukan pembersihan seluruh penggunaan disk.

Definisi MVP lengkap belum dapat dinyatakan lulus: belum ada pengukuran video Indonesia 60 menit menjadi ≥5 klip dalam ≤15 menit pada Mac M-series, pemeriksaan sinkron ucapan manusia ±100 ms, atau golden set manusia/provider nyata. Mesin sesi ini Linux ARM64. Uji perangkat lunak dan contoh pendek di atas tidak menggantikan gate tersebut. Tidak ada bukti peningkatan traffic publikasi yang diukur dalam fase ini.

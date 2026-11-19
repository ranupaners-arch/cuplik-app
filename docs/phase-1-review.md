# Checkpoint Fase 1 — ingest dan transkripsi

Fase 1 siap diperiksa. Penerapan desain dan pekerjaan kualitas pemilihan momen Fase 2 belum dimulai.

## Perubahan

- Probe YouTube memiliki pesan khusus untuk privat, pembatasan usia, verifikasi akun, video tidak tersedia, playlist, live, upcoming dan tanpa audio.
- Download memakai file staging yang dapat dilanjutkan; sumber divalidasi sebelum menjadi cache final. Sumber rusak dipulihkan dari upload/URL. Audio WAV 16 kHz mono dan transkrip dipakai bersama seluruh output Project.
- Whisper mendukung bahasa auto/Indonesia/Inggris/Arab, VAD, `condition_on_previous_text=False`, glosarium awal dan koreksi deterministik. Setiap kata memiliki ID dan timestamp; kalimat memiliki `word_ids`.
- Segmentasi memakai tanda baca, jeda ≥0,6 detik, dan batas 25 kata. Fragmen pendek digabung bila tidak melintasi hening panjang atau melanggar batas kata.
- Segmen berulang/no-speech dikeluarkan dengan audit, bukan diubah menjadi caption palsu. Checkpoint raw per bagian disimpan atomik dengan checksum; default bagian 60 detik.
- Task outbox SQLite mengatasi jeda antara commit dan enqueue. Redis offline mempertahankan job sebagai queued. Recovery worker memakai lock proses dan checkpoint; error input/model tetap membutuhkan retry.
- Progres sumber tersimpan melalui SSE. Halaman proyek menyediakan transkrip JSON dan retry. Preferensi menyediakan glosarium. Semua memakai form dasar.
- yt-dlp menyertakan EJS/Node serta update stable terisolasi saat startup dan setiap hari pukul 03:00. Update tidak memutasi dependensi aplikasi yang terkunci dan memiliki fallback.

## Pemeriksaan

| Pemeriksaan | Hasil |
|---|---|
| Backend pytest | 35 lulus, termasuk recovery/checkpoint, cache rusak, glosarium, upload finalization, SSE, outbox dan upgrade database berisi data |
| Playwright | 2 alur lulus: Klip/Ringkas end-to-end, serta glosarium + upload sidecar + progres/cache proyek |
| Ruff, TypeScript, build Next.js | Lulus |
| Alembic check | Sinkron dengan model |
| Docker dan upgrade data lama | Lulus; proyek/output lama tetap terbaca, progres historis dibetulkan, EJS/Node tersedia, dan worker menghasilkan MP4 |
| Pembaruan yt-dlp nyata | Pemeriksaan PyPI berhasil; baseline 2026.10.26 sudah merupakan versi yang tersedia |
| Probe YouTube nyata | Metadata video publik 19 detik berhasil dibaca; pesan kegagalan video yang tidak tersedia juga teruji |
| Video Indonesia + ASR nyata + hard kill | Lulus; rincian di bawah |

## Uji video nyata dan pemulihan

Sumber: [Membatalkan penghapusan halaman di Wikipedia (2)](https://commons.wikimedia.org/wiki/File:Membatalkan_penghapusan_halaman_di_Wikipedia_(2).webm), Wikimedia Indonesia, serial tutorial Raymond Sutanto, **CC BY-SA 4.0**. Pengujian memakai potongan 75 detik dari awal; atribusi sumber dan file uji disimpan di `data/phase1-validation/` yang diabaikan Git.

Pada Linux ARM64, faster-whisper **base**, CPU int8, dan bagian 10 detik untuk memaksa banyak checkpoint:

- Worker/workhorse dihentikan dengan SIGKILL setelah checkpoint pertama.
- Worker baru memulihkan tugas; jumlah attempt menjadi 2.
- Checksum checkpoint pertama dan waktu modifikasi sumber/audio tidak berubah.
- Hasil mencakup 130 kata dan 16 kalimat bahasa Indonesia; SSE dapat diputar ulang.
- Hasil transkripsi kemudian dipakai membuat dan mengunduh MP4 melalui worker/FFmpeg, dengan LLM mock.
- Siklus uji sekitar 15 detik setelah bobot model tersedia. Ini smoke test satu video pendek, bukan benchmark PRD atau ukuran akurasi.

Laporan mesin: `data/phase1-validation/workflow-report.json`. Artefak review: `validated-transcript.json` dan `validated-clip.mp4` pada folder yang sama. Harness dapat dijalankan ulang dengan:

```sh
make validate-ingest VIDEO=/path/ke/video-indonesia.mp4
```

Harness khusus Linux dan tidak berjalan dalam CI offline. Ia mengunduh bobot model publik jika belum ada, menjalankan Redis/API/worker terisolasi, dan hanya menghentikan proses uji miliknya sendiri. Tidak mengirim permintaan LLM berbayar.

## Keputusan dan batas

Uji nyata menemukan kegagalan faster-whisper dengan PyAV 19. Dependensi dibatasi ke **PyAV <19**; versi 18.1.0 berhasil dipakai. Alasannya sesuai [laporan upstream](https://github.com/SYSTRAN/faster-whisper/issues/1589).

Kualitas transkrip tetap memerlukan koreksi, terutama nama/istilah. Belum ada penilaian WER, golden set, video 1–3 jam, pengukuran GPU, atau pengujian hardware MLX. Filter hening/pengulangan bersifat heuristik dan menyimpan audit agar keputusan dapat diperiksa. Probe live YouTube bergantung ketersediaan/verifikasi video dari lingkungan jaringan; pengujian upload dan ASR nyata tidak memerlukan akses YouTube.

Uji upgrade Docker memakai database Fase 0 yang sudah berisi proyek/output. Migrasi memakai ADD COLUMN dengan default konstan dan backfill waktu, sehingga tabel induk berelasi tidak perlu dibangun ulang. Migrasi SQLite dibungkus transaksi DDL eksplisit; database lama dicadangkan sebelum memperbaiki upgrade yang sempat gagal.

Berhenti di checkpoint ini sebelum Fase 2.

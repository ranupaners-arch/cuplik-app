# Ringkas — daftar bab dan paket unduhan

19 November 2026. Bagian awal Fase 5 setelah pengguna meminta kelanjutan PR pekerjaan ringan. Cakupan ini memperbaiki waktu bab serta paket hasil Ringkas. Vision, kartu bab, timelapse, koherensi, dan evaluasi kualitas manusia masih menjadi pekerjaan berikutnya.

## Perilaku

Setelah Ringkas selesai, buka **Daftar bab dan unduhan** di bawah video. Indeks tinjauan dapat diunduh sebagai TXT; laporan JSON menjelaskan sumber waktu dan hasil pemeriksaan format. Disclosure memakai `<details>/<summary>` native, dan teks indeks yang dapat digulir dapat difokuskan dengan keyboard. Tautan unduhan menggunakan `<a download>`.

Indeks baru mengikuti durasi segmen yang sudah di-encode, bukan `Chapter.kept_s` dari solver. Manifest `condensed.timeline.json` memetakan beat/kalimat dan rentang sumber ke waktu keluaran. Akhir rentang terakhir memakai durasi MP4 akhir. Ini pemeriksaan waktu berdasarkan metadata encode, belum merupakan pemeriksaan sinkron frame/ucapan oleh manusia.

Teks untuk deskripsi YouTube disediakan bila:

- Bab pertama mulai pada `00:00`.
- Terdapat minimal tiga timestamp yang berurutan, tanpa timestamp detik duplikat.
- Semua bab, termasuk bab terakhir, berdurasi minimal 10 detik.
- Selisih akumulasi durasi segmen dengan MP4 akhir tidak melebihi 100 ms.

Tiga syarat pertama mengikuti [YouTube Help — Video Chapters](https://support.google.com/youtube/answer/9884579?hl=en). Pemeriksaan selisih durasi adalah aturan internal Cuplik. Format yang lolos tidak menjamin fitur bab aktif pada kanal; ketersediaan fitur juga bergantung pada kelayakan kanal.

Ringkasan pendek tetap mendapat indeks biasa dengan alasan format YouTube belum lolos. Cuplik tidak memperpanjang video atau membuat bab tambahan hanya untuk memenuhi syarat tersebut. Judul bab dinormalisasi menjadi satu baris agar tidak menyisipkan timestamp baru melalui line break.

## Unduhan dan API

| Artefak | Isi |
| --- | --- |
| `condensed.mp4` | Video Ringkas |
| `chapters.txt` | Indeks tinjauan dengan milidetik |
| `chapters.json` | Daftar bab, sumber waktu, hasil pemeriksaan dan alasan |
| `condensed.timeline.json` | Peta beat dari sumber ke keluaran |
| `youtube-chapters.txt` | Timestamp detik untuk deskripsi YouTube, hanya bila valid |

ZIP Ringkas berisi MP4, metadata, indeks, serta laporan. Manifest waktu disertakan jika tersedia. `captions.txt` untuk kemasan Klip tidak lagi dibuat kosong pada ZIP Ringkas. Paket Klip mempertahankan kemasannya.

- `GET /api/outputs/{id}/chapters` mengembalikan laporan bertipe.
- `GET /api/outputs/{id}/chapters.txt` mengunduh indeks tinjauan.
- `GET /api/outputs/{id}/chapters.txt?format=youtube` mengunduh versi YouTube; HTTP 409 beserta alasan jika belum lolos.
- `GET /api/outputs/{id}` menyertakan `chapter_export` setelah Ringkas selesai.

Endpoint bab menolak output Klip atau output yang masih diproses. Tidak ada migrasi database dan tidak ada permintaan LLM tambahan untuk membuat daftar bab.

## Kompatibilitas hasil lama

Output lama dengan `chapters.txt` masih dapat dibuka serta diunduh. Laporan diberi `timing_source=legacy_plan` dan `youtube_valid=false`, karena daftar tersebut belum diperiksa terhadap durasi segmen encode. Membaca hasil lama tidak menulis ulang artefaknya. Output baru memakai `timing_source=encoded_parts`.

## Verifikasi

- Tes unit mencakup waktu encode yang berbeda dari rencana, bab yang dibuang, gabungan beat satu bab, batas satu jam, normalisasi judul, durasi bab terakhir, timestamp duplikat, dan selisih durasi.
- Tes kontrak mencakup unduhan YouTube valid, penolakan daftar tidak valid, ZIP, penghapusan file publikasi lama ketika paket baru tidak valid, serta pembacaan hasil lama tanpa perubahan.
- Workflow FFmpeg nyata memeriksa manifest dan durasi Ringkas. Fixture kontrak publikasi 36 detik memakai metadata sintetis; tidak dianggap bukti kualitas video manusia.
- Browser menguji pembukaan daftar bab lewat keyboard, unduhan TXT, dan tidak adanya tautan YouTube pada demo yang terlalu pendek.
- Rangkaian pemeriksaan: 98 tes backend, tiga skenario browser, lint/TypeScript, OpenAPI dan build produksi. Hasil pengujian manusia/golden set belum tersedia.

Berikutnya: alur anotasi manusia yang menghasilkan data evaluasi yang bisa diaudit, kemudian vision yang memilih area visual penting. Status keseluruhan ada pada [rencana build](../cuplik-claude-code-build.md).

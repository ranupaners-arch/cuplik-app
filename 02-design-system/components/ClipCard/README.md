# ClipCard
Satu klip hasil di grid hasil proyek: thumbnail 9:16, peringkat, skor, durasi, judul dan dua aksi.

- Urutan grid = peringkat (skor tertinggi pertama). `#rank` kiri atas, skor kanan atas, durasi kanan bawah.
- Hover memutar pratinjau tanpa suara; klik membuka editor klip.
- Judul maks 2 baris (`title`), metadata timecode memakai `mono`.
- Satu tombol utama (`brand`): Unduh. Aksi lain sekunder.
- Konsumen menyediakan: `clip {id, rank, title, start, end, score, thumbUrl, previewUrl, aspect}`.

# Cuplik

Studio klip pribadi dengan dua mode: **Klip** (satu video panjang → beberapa opsi Shorts vertikal) dan **Ringkas** (tutorial berjam-jam → versi singkat yang tetap memuat semua langkah). Cuplik adalah versi pribadi dari alat seperti miqla.app — dibangun sendiri, tanpa langganan, dengan Bahasa Indonesia sebagai bahasa kelas satu.

> Nama: *cuplik* (KBBI) — mengambil sebagian dari keseluruhan. Persis yang dikerjakan aplikasinya.

## Prinsip

1. **Klip adalah bintangnya.** UI gelap, netral, hangat. Warna paling terang di layar harus thumbnail klip, bukan tombol.
2. **Angka bisa dipercaya.** Timecode, durasi, skor selalu memakai `mono` supaya tidak goyang saat berubah. Skor viral selalu ditampilkan dengan satu desimal (`8.4`), bukan persen.
3. **Garis, bukan bayangan.** Kartu dan panel dipisah `line` 1px. `shadow-pop` hanya untuk modal dan menu.
4. **Satu warna aksi.** `brand` (kunyit) = aksi utama + playhead + garis potong. Kalau semua kunyit, tidak ada yang kunyit.
5. **Klip lemah bukan error.** Skor rendah memakai `score-low` (abu hangat), merah `cut` hanya untuk gagal/hapus.

## Suara & bahasa

- Bahasa Indonesia santai-profesional, kalimat pendek. "Tempel link YouTube" bukan "Silakan memasukkan tautan video Anda".
- Kata kerja di tombol: **Buat klip**, **Unduh semua**, **Potong ulang**.
- Status jujur dan spesifik: "Mentranskrip… 41%" bukan "Memproses…".
- Istilah teknis yang memang dipakai kreator boleh Inggris: *hook*, *caption*, *B-roll*, *Shorts*.

## Fondasi visual

| Peran | Token | Catatan |
|---|---|---|
| Latar | `bg` → `surface` → `surface-raised` | tiga lapis, makin terang makin dekat |
| Teks | `ink`, `ink-muted` | ≥5:1 di semua lapis |
| Aksi | `brand` + `on-brand` | tombol utama, playhead |
| Skor | `score-high` ≥8, `score-mid` 5–7.9, `score-low` <5 | dibedakan juga lewat terang-gelap, bukan hue saja |
| Bahaya | `cut` | gagal, hapus, live |
| Fokus | `focus` | cincin 2px offset 2px |

**Tipografi:** Plus Jakarta Sans (dirancang di Jakarta, gratis di Google Fonts) untuk semua UI; JetBrains Mono untuk angka. Muat dari Google Fonts:
`https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap`

**Spasi:** kelipatan 4 (`space-1`…`space-12`). Grid klip: `space-4` gap, kartu min 220px.

**Radius:** `radius-lg` untuk thumbnail 9:16 dan kartu, `radius-md` tombol, `radius-pill` toggle & progress.

## Caption yang dibakar ke video

Ini bagian desain yang tampil di TikTok/Shorts, bukan di aplikasi:

- Kanvas 1080×1920. Area aman: 120px kiri-kanan, 260px atas, 420px bawah (hindari UI TikTok).
- Caption: `burn-caption` — Plus Jakarta Sans 800, 64px, UPPERCASE, outline hitam 6px, maks 3 kata per baris, 2 baris.
- Kata aktif (karaoke): `caption-hl` kuning, sedikit membesar 1.08×.
- Hook: `burn-hook` di kotak putih teks hitam (atau `brand` teks `on-brand`), 0–3 detik pertama, di sepertiga atas.
- Emoji: opsional, maksimal 1 per baris, setelah kata kunci.

## Ikonografi

Lucide (outline 1.75px, 20px) — gratis, konsisten. Ikon kunci: `scissors` (potong), `sparkles` (AI), `flame` (skor), `captions`, `crop` (reframe), `download`. Jangan pakai emoji sebagai ikon UI.

## Komponen

- **UrlInput** — hero: tempel link / unggah, estimasi durasi & biaya proses.
- **JobProgress** — tahapan pipeline dengan persen nyata.
- **ClipCard** — thumbnail 9:16, judul, durasi, skor, aksi.
- **ScoreBadge** — skor 0–10 dengan warna bertingkat.
- **AttentionCurve** — kurva "Moment IQ" per detik dengan klip terpilih ditandai.
- **CaptionStyle** — pratinjau preset caption.
- **OutlineReview** — (mode Ringkas) daftar bab dengan centang wajib, label inti/membantu/opsional, durasi target, peringatan durasi minimum.
- **EditTimeline** — (mode Ringkas) peta keputusan normal/percepat/buang per beat, beat wajib dan terkunci ditandai.

## Yang tidak dilakukan

Tidak ada gradien ungu-biru, tidak ada kartu emoji, tidak ada border kiri berwarna, tidak ada glassmorphism.

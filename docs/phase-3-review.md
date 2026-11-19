# Checkpoint Fase 3 — renderer Klip

19 November 2026. Fase 3 selesai pada lingkup rekayasa renderer, dengan caption ringkas dan konteks rekaman layar yang sudah disetujui pengguna tetap menjadi dasar. Antarmuka masih form standar; penerapan design system belum dimulai. Berhenti untuk pemeriksaan sebelum Fase 4.

## Hasil yang bisa dicoba

- [Klip 1](../data/phase3-validation/clip-1.mp4), [klip 2](../data/phase3-validation/clip-2.mp4), [klip 3](../data/phase3-validation/clip-3.mp4), semuanya 1920×1080 dari sumber Indonesia Fase 1 yang sama.
- [Thumbnail klip 1](../data/phase3-validation/clip-1.jpg) dan [frame dengan kata aktif](../data/phase3-validation/frame.png).
- [Laporan semua klip](../data/phase3-validation/report.json), [benchmark kecil](../data/phase3-validation/benchmark.json), dan [uji Docker](../data/phase3-validation/docker-workflow.json).
- [Peta waktu klip 1](../data/phase3-validation/clip-1.edl.json), [caption](../data/phase3-validation/clip-1.captions.json), serta [jejak crop per frame](../data/phase3-validation/clip-1.reframe.json).

Sumber dan atribusi Wikimedia CC BY-SA tetap tercatat di `data/phase1-validation/attribution.json`. Contoh Fase 2 dan hasil koreksi sebelumnya disimpan terpisah.

## Pembingkaian dan pipeline video

`framing.py` memilih orientasi/konteks; `reframe.py` melacak subjek dalam pipeline `framepipe.py`. Decode FFmpeg mengalirkan BGR ke Python, OpenCV melakukan crop/composisi, lalu encoder FFmpeg menerima frame kembali. Encoder H.264 CRF 20, 30 fps, AAC 160 kbps. Buffer frame tidak menampung seluruh video. Thread encoder/OpenCV dibatasi melalui `RENDER_THREADS`, default empat; decoder memakai dua thread.

Model YuNet lokal dibaca pada lebar maksimal 640 px setiap tiga frame keluaran, yaitu 10 pemeriksaan/detik pada 30 fps. Target diasosiasikan berdasarkan posisi, jendela crop memakai EMA 0,15 dan zona mati 8%. Target lain diambil setelah pergantian adegan atau cut edit. Setelah target hilang lebih dari dua detik, sumber dimuat utuh dengan latar salinannya yang diblur 40 px dan digelapkan 30%. Margin wajah membatasi zoom/crop agar deteksi yang diketahui tetap muat.

Rekaman layar/konteks tetap memakai orientasi sumber. Zoom otomatis hanya aktif pada pembicara, sehingga antarmuka tutorial tidak diperbesar dan dipotong. Opsi vertikal untuk sumber tanpa subjek yang aman memakai komposisi bingkai utuh berlatar blur. Pita caption/hook terpisah dari gambar utama.

YuNet yang sudah disetujui pada koreksi sebelumnya dipertahankan sebagai pengganti rekomendasi MediaPipe pada rancangan awal. Model kecil ini sudah dibundel dan teruji dengan OpenCV 5, sehingga tidak menambah model/runtime kedua. Tidak ada unggahan frame ke layanan cloud. Model, hash, commit, dan lisensi berada di `worker/assets/yunet/`.

## Retensi dan peta waktu

`retention.py` menghasilkan EDL berisi rentang sumber, waktu keluaran, dan overlap audio. Jeda antar kata >350 ms dipendekkan menjadi 120 ms setelah memperhitungkan crossfade 10 ms. Pengisi nonsemantik seperti `eh/em/hmm` yang berdiri sendiri dapat dihapus. Penggabungan cut tidak memotong kata lain.

Zoom bergantian 100–112% pada batas kalimat dengan transisi 250 ms; emphasis dapat mencapai 120% selama 600 ms, dibatasi geometri wajah. Cold open **mati secara default**. Jika diaktifkan, hanya ID kalimat kandidat yang valid, berada dalam klip, dan maksimal 3,5 detik yang dapat didahulukan. Transisi whoosh 200 ms dibuat lokal; caption tidak muncul pada transisi. Hasil tetap dibatasi 180 detik.

Koreksi caption dengan jumlah kata berbeda dan sidecar tanpa timestamp kata tidak dipakai untuk pemotongan temporal yang mengandalkan tebakan waktu. Koreksi dengan jumlah kata sama dipetakan kembali ke kata asli; kata yang sudah dikoreksi menjadi kata bermakna tidak dihapus sebagai pengisi. Jika retensi membuat klip terlalu pendek, pemotongan dibatalkan dan alasannya dicatat.

Semua teknik dapat dimatikan lewat `Clip.retention` dan form **Ritme video dan sorotan caption**. `OutputSettings.retention` mengatur default output; `PATCH /api/clips/{id}` menerima perubahan flag parsial dan mempertahankan flag lainnya. Nama flag: `shorten_pauses`, `remove_fillers`, `zoom`, `emphasis`, `cold_open`, `karaoke`, `keyword_highlights`, `emoji`.

## Caption, audio, dan thumbnail

Frasa tetap maksimal tiga kata pada potret atau lima kata pada video lebar, maksimal dua baris, dengan ukuran glyph terukur. Kata aktif berubah kuning selama interval waktunya lalu kembali putih; keyword tetap kuning. Emoji opsional maksimal satu per frasa dan mati secara default. Peta EDL menggeser timestamp kata, termasuk pengulangan pada cold open. Karaoke tidak mengklaim akurasi kata jika waktu hanya diestimasi dari kalimat.

Audio EDL memakai overlap/crossfade nyata 10 ms. Normalisasi dilakukan dua lintasan berdasarkan pengukuran, menuju −14 LUFS. Headroom normalisasi −1,5 dBTP disediakan untuk overshoot AAC; QC mengukur batas akhir −1 dBTP. Sumber hening yang tidak dapat diukur tidak diberi status normalisasi berhasil.

Thumbnail dipilih dari 30% awal keluaran, mengutamakan wajah yang benar-benar terdeteksi dan variance of Laplacian tertinggi; jika tidak ada wajah, dipilih frame konteks paling tajam. JPEG menjadi poster pemutar, tersedia melalui `GET /api/clips/{id}/thumbnail`, dan masuk ZIP bersama MP4. `captions.txt` kini memuat judul/hook terpilih, deskripsi, hashtag dan skor.

## QC dan kegagalan

QC membaca **MP4 akhir setelah AAC**, memeriksa:

- stream gambar/audio, dimensi, dan durasi terhadap EDL dengan toleransi 100 ms;
- bagian isi video yang hitam lebih dari 500 ms, dengan pita teks/latar komposisi dikecualikan;
- hening lebih dari satu detik pada ambang −40 dBFS;
- loudness −14 ±1 LUFS dan true peak maksimal −1 dBTP dengan toleransi pengukuran 0,05 dB;
- batas geometris dan waktu caption/hook pada area aman.

Klip gagal QC tetap selesai dirender, dapat diputar/diunduh, dan diberi tanda **perlu ditinjau** beserta pemeriksaan yang gagal. Ini berbeda dari kegagalan proses encoder/decoder, yang membuat job gagal dan dapat dicoba ulang. Ada tes nyata untuk video hitam dan hening, bukan hanya transport palsu.

Fingerprint renderer naik ke v3 dan mencakup retensi, keyword/emoji serta ID cold open/emphasis. Hasil lama dapat diperbarui melalui **Perbarui video klip**, memakai rencana/sumber/transkrip tersimpan tanpa LLM/ASR ulang. Kolom retention/thumbnail sudah ada; tidak diperlukan migrasi baru. `alembic check` tidak menemukan perubahan schema.

## Verifikasi dan pengukuran

**78 tes backend, dua tes browser, Ruff/TypeScript, build Next.js dan build Docker lolos.** Tes mencakup remap waktu/cold open, urutan semua frame, karaoke, keyword, skip estimasi, koreksi pengisi, batas 180 detik, crossfade sampel, safe area, fallback, QC negatif, thumbnail/ZIP dan flag parsial. Browser menguji poster JPEG, rincian QC, pengubahan retensi, render ulang dan kedua mode.

Uji tambahan memakai foto NASA domain publik dengan gerakan sintetis dan nada uji, **bukan rekaman orang berbicara**. Foto/atribusi ada di `data/phase3-validation/fixtures/`. Pada 24 detik: 720 frame, 240 deteksi, perpindahan crop 452 px, 32 frame fallback setelah wajah dihilangkan. [Laporan gerakan](../data/phase3-validation/tracking/report.json). Ini membuktikan jalur neural/tracker pada gerakan terkontrol, bukan akurasi umum semua video pembicara.

Benchmark render CPU kecil, ARM64, `RENDER_THREADS=4`, tiga klip dari video 75 detik:

| Klip | Rentang sumber | Hasil | Loudness | True peak | Waktu render termasuk QC |
|---|---:|---:|---:|---:|---:|
| 1 | 15,24 dtk | 14,90 dtk | −14,26 LUFS | −1,48 dBTP | 11,11 dtk |
| 2 | 14,78 dtk | 12,63 dtk | −14,30 LUFS | −1,46 dBTP | 9,32 dtk |
| 3 | 3,57 dtk | 3,10 dtk | −14,08 LUFS | −1,47 dBTP | 3,42 dtk |

Total perintah preview 23,91 detik; tidak termasuk download, transkripsi, atau pemilihan LLM. Pengukuran ini bukan benchmark video satu jam atau jaminan waktu pada hardware lain. Semua contoh ini lolos QC.

## Cara mencoba dan batas klaim

Jalankan ulang `make dev`. Buat output Klip baru atau perbarui hasil lama. Periksa pemutar/thumbnail dan buka **Pemeriksaan kualitas video**. Ubah teknik pada editor lalu simpan/render ulang. Cold open hanya berfungsi jika kandidat memilikinya.

```sh
uv run python scripts/preview_render.py \
  --source data/phase1-validation/indonesian-75s.mp4 \
  --transcript data/phase2-validation/transcript.json \
  --selection data/phase2-validation/selection.json

uv run python scripts/validate_tracking.py \
  --photo data/phase3-validation/fixtures/portrait.jpg
```

Pelacakan memakai asosiasi posisi, bukan pengenalan identitas; pose sulit/oklusi/konferensi beberapa orang tetap perlu diperiksa. Default auto menjaga konteks yang belum jelas. WER, sinkron ucapan manual ±100 ms, golden set manusia, performa 1–3 jam, dan hardware encoder GPU/Mac belum diukur. Aturan safe area/font besar pada rancangan asli disesuaikan dengan hasil review pengguna: caption kecil di pita terpisah, dan resolusi mengikuti sumber. Desain grid/merek tetap ditunda. Editor kata dan batas klip lebih lanjut, preferensi serta definisi MVP menyeluruh diteruskan pada Fase 4.

Rujukan teknis primer: [filter FFmpeg](https://ffmpeg.org/ffmpeg-filters.html#loudnorm) dan [model YuNet resmi](https://github.com/opencv/opencv_zoo/tree/26cc381e4d2594bb9f47a26eb8fd96c94a13660d/models/face_detection_yunet). Atribusi foto uji: [NASA/Robert Markowitz melalui Commons](https://commons.wikimedia.org/wiki/File:Commander_Eileen_Collins_-_GPN-2000-001177.jpg).

# Prompt build Cuplik untuk Claude Code (v2)

Taruh file ini dan `cuplik-prompts.md` (v2) di root repo kosong `cuplik/`, lalu di Claude Code ketik:
`Baca cuplik-claude-code-build.md dan kerjakan Fase 0. Berhenti di akhir tiap fase untuk saya cek.`
Kalau memakai Linear: satu fase = satu issue, checklist fase = kriteria terima, dan Claude Code melapor hasil tiap fase sebagai komentar di issue-nya.

---

## Konteks

Kamu membangun **Cuplik**, aplikasi pribadi (single user, tanpa login, tanpa pembayaran) dengan dua mode:

- **Klip** — satu link YouTube → 3–12 opsi Shorts vertikal (default 8), diurutkan skor viral, masing-masing dengan 2 judul + 2 teks hook, caption karaoke, dan paket retensi.
- **Ringkas** — tutorial/video pembuatan 30 menit–3 jam → satu video berdurasi target (default 10 menit) yang tetap memuat semua langkah inti, dengan kartu bab, timelapse, dan daftar bab YouTube.

Kedua mode berbagi satu **Project** (unduhan + transkrip di-cache). Bahasa UI: Bahasa Indonesia.

Dokumen acuan (baca dulu bila bisa dibuka):
- Blueprint & PRD (termasuk Audit v2, Paket retensi, Mode Ringkas): https://claude.ai/artifact/HjgUAZ4qspxNQhDPZ2G9pG
- Design system: https://claude.ai/artifact/N4cMnfMsZj1rYAgeijkTNS
- Prompt LLM: `cuplik-prompts.md` v2 → salin ke `worker/prompts/` tanpa diubah kecuali ada alasan yang kamu tulis di PR.

Kalau link tidak bisa dibuka, file ini sudah cukup untuk membangun semuanya.

## Stack (wajib)

- `web/`: Next.js 15 App Router, TypeScript, Tailwind v4, shadcn/ui, lucide-react; font Plus Jakarta Sans + JetBrains Mono via `next/font/google`.
- `api/`: Python 3.11, FastAPI, SQLModel + SQLite (WAL mode), `sse-starlette`.
- `worker/`: Python 3.11, RQ + Redis; yt-dlp, ffmpeg/ffprobe (dengan libass), faster-whisper (Linux) atau mlx-whisper (macOS arm64, deteksi otomatis), mediapipe, opencv-python-headless, scenedetect, numpy, pydantic v2, jinja2, google-genai, anthropic, httpx (Ollama). Provider via `.env`: `LLM_PROVIDER=gemini|anthropic|ollama`, `LLM_MODEL_FAST`, `LLM_MODEL_SMART`, `LLM_MODEL_VISION`.
- `docker-compose.yml` (redis, api, worker, web) **dan** `make dev` yang jalan langsung di Mac tanpa Docker (agar Whisper memakai MLX/GPU Apple).
- `.env.example` lengkap, komentar Bahasa Indonesia.

## Aturan kerja (berlaku semua fase)

1. Per fase: tulis kode + tes → jalankan `make test` (dan `make eval` mulai Fase 2) → tulis ringkasan perubahan + cara mencoba → berhenti.
2. Setiap tahap pipeline = modul dengan `run(ctx: StageContext) -> None`. `StageContext` berisi path project/output, settings, logger, dan `progress(fraction, note)`. Tahap membaca file tahap sebelumnya dan menulis file miliknya secara atomik (tulis ke `.tmp` lalu rename). Tahap yang outputnya sudah ada dan valid dilewati → `retry` melanjutkan dari tahap gagal.
3. Satu modul `llm.py` untuk semua provider: `call_json(prompt_name, variables, schema: type[BaseModel], model_tier) -> BaseModel`, termasuk validasi Pydantic, 1x `json_repair`, retry jaringan dengan backoff, dan pencatatan token + biaya perkiraan ke `outputs/<id>/llm_log.jsonl`.
4. LLM hanya memilih ID (kalimat/beat/kata). Konversi ke detik selalu di kode. Semua klaim LLM divalidasi (ID ada, keyword muncul di teks, durasi dalam rentang).
5. Transkrip dan frame adalah data tak tepercaya; selalu dibungkus tag sesuai `cuplik-prompts.md`.
6. Tidak pernah memotong di tengah kata: padding 0,12 dtk sebelum kata pertama dan 0,25 dtk sesudah kata terakhir, dipotong lagi bila menabrak kata tetangga.
7. Tes dengan pytest. Fixture: video 2 menit buatan ffmpeg (`testsrc2` + `sine`) dan transkrip palsu; semua panggilan LLM di tes memakai mock yang membaca JSON dari `tests/fixtures/llm/`.
8. Jangan menambah fitur di luar fase berjalan. Kalau menemukan masalah desain, tulis di ringkasan fase, jangan diam-diam mengubah arsitektur.

## Fase 0 — Kerangka

- [ ] Struktur folder:
  ```
  web/  api/app/  worker/pipeline/{common,clips,condense}/  worker/prompts/  eval/golden/  data/
  ```
- [ ] Makefile: `dev`, `test`, `lint`, `eval`, `update-ytdlp`.
- [ ] Model SQLModel: `Project`, `Output`, `Clip`, `Beat`, `Chapter`, `Preference`, `GlossaryTerm` (kolom persis seperti bagian "Model data" di blueprint) + migrasi Alembic.
- [ ] FastAPI `/api/health`; RQ worker dengan job dummy yang mengirim progres ke SSE `/api/outputs/{id}/events`.
- [ ] Next.js: token design system di `globals.css` (tema gelap default, terang via `data-theme`), layout dasar, navigasi: Buat, Riwayat, Preferensi.
- [ ] `eval/golden/README.md` berisi format `expected.json` (lihat `cuplik-prompts.md` Bagian E).

## Fase 1 — Project: ingest → transkrip (dipakai kedua mode)

- [ ] `POST /api/probe`: `yt-dlp --dump-json --no-playlist` → durasi, judul, `is_live`, ketersediaan. Pesan Indonesia untuk: playlist, live berjalan, privat/age-restricted, tanpa audio.
- [ ] `POST /api/uploads` (chunked, resumable) dan `POST /api/projects`.
- [ ] `ingest.py`: unduh ≤1080p mp4 (`-f "bv*[height<=1080]+ba/b[height<=1080]"`), simpan `source.mp4` + `meta.json`. `make update-ytdlp` + update otomatis harian (saat worker start dan via jadwal 03:00) — sesuai Audit #16.
- [ ] `audio.py`: WAV 16 kHz mono.
- [ ] `transcribe.py`: Whisper `large-v3-turbo`, `word_timestamps=True`, `vad_filter=True`, `condition_on_previous_text=False`, `initial_prompt` dari glosarium. Buang segmen yang mengulang n-gram ≥3 kata tiga kali berturut-turut (halusinasi). Terapkan glosarium.
- [ ] `segment.py`: kalimat dari tanda baca, jeda ≥0,6 dtk, atau maks 25 kata; gabung potongan <3 kata. Tulis `transcript.json` = `{language, words:[{id:"w1",start,end,text}], sentences:[{id:"s1",start,end,text,word_ids:[...]}]}`.
- [ ] UI: halaman Buat (UrlInput → ringkasan probe → pilih mode Klip / Ringkas / keduanya), halaman Output dengan JobProgress via SSE.
- [ ] Tes: segmentasi (kalimat panjang tanpa tanda baca terpecah), filter halusinasi, idempotensi tahap.

## Fase 2 — Klip: pilih momen

- [ ] `signals.py`: per detik → RMS energi (z), kata/detik (z), hening, scene change (PySceneDetect, `ContentDetector`), kata pemicu (`worker/pipeline/common/hook_words.txt`, Indonesia + Inggris). Bobot 0.35/0.25/0.20/0.10/−0.10, haluskan 5 dtk, normalkan 0–1 → `signals.json`.
- [ ] `moments.py`: jendela 8 menit, **overlap = panjang klip maksimum**; prompt `moment_finder`; sertakan maks 3 `liked_examples`; gabung kandidat lintas jendela.
- [ ] `scoring.py`: batch 6, prompt `scorer`; hitung `base_score` persis rumus di `cuplik-prompts.md`.
- [ ] `rerank.py`: ambil maks 20 finalis dengan `base_score` tertinggi → prompt `reranker` → urutan akhir; aturan keras maks 2 klip per `topic`.
- [ ] `boundaries.py`: terapkan trim, tempel ke batas kalimat & jeda ≥250 ms, buang pengisi di awal ("eh", "em", "jadi", "oke", "nah" bila diikuti jeda), dedupe IoU > 0.3, ambil N klip (setting, default 8, maks 12), batas keras 180 dtk.
- [ ] `make eval` untuk mode Klip (recall IoU ≥ 0.5 terhadap `expected.json`).
- [ ] Tes: LLM mock → klip valid, tidak ada yang memotong kata, keragaman topik dipatuhi.

## Fase 3 — Klip: bentuk video

- [ ] `reframe.py` (MVP): MediaPipe Face Detection tiap 3 frame pada video 640 px; target = wajah terbesar yang stabil; jendela crop 9:16 dengan EMA (alpha 0.15) + zona mati 8% lebar; pindah target hanya di scene cut. Tidak ada wajah >2 dtk → mode BLUR (video asli di tengah, latar salinan blur 40 + gelap 30%). Tulis `reframe/<clip>.json` (crop per frame).
- [ ] `retention.py` — paket retensi, semua bisa dimatikan per klip lewat `Clip.retention`:
  - [ ] Jeda antar kata >0,35 dtk dipendekkan jadi 0,12 dtk.
  - [ ] Kata pengisi berdiri sendiri ("eh", "em", "hmm", "ehm") dihapus per kata.
  - [ ] Zoom halus bergantian 100% ↔ 112% di tiap batas kalimat; 120% selama 0,6 dtk pada `emphasis_word_ids`. Transisi zoom 0,25 dtk ease-in-out.
  - [ ] Cold open (default mati): kalimat `cold_open_id` diputar dulu, lalu 0,2 dtk whoosh-cut ke awal.
  - [ ] Hasil: EDL klip (`[{src_start, src_end, zoom_from, zoom_to}]`) + peta waktu sumber→keluaran untuk menggeser caption.
- [ ] `captions.py`: ASS 1080×1920; kelompok 1–3 kata (maks 18 karakter/baris, 2 baris); Plus Jakarta Sans ExtraBold 64 px UPPERCASE, outline hitam 6; kata aktif karaoke `#FFE14D`, keyword kuning tetap; emoji opsional maks 1/baris. Area aman: margin kiri-kanan 120, atas 260, bawah 420. Hook (teks terpilih) 0–3 dtk: kotak putih teks hitam 72 px di y≈420. Waktu caption digeser memakai peta waktu dari retention.
- [ ] `render.py`: **pipa frame Python** — decode sumber dengan ffmpeg (rawvideo pipe) → crop + zoom NumPy/OpenCV per frame → encode ke ffmpeg kedua dengan filter `subtitles=` (libass, fontsdir dari `worker/fonts/`), `libx264 -preset veryfast -crf 20` (atau `h264_videotoolbox`/`h264_nvenc`), AAC 160k, 30 fps. Audio: potong sesuai EDL dengan crossfade 10 ms, lalu `loudnorm=I=-14:TP=-1:LRA=11` dua lintasan. Thumbnail = frame wajah paling tajam (variance of Laplacian) di 30% awal.
- [ ] `qc.py`: durasi sesuai EDL ±0,1 dtk, tidak ada frame hitam >0,5 dtk (`blackdetect`), tidak ada senyap >1 dtk (`silencedetect`), loudness −14 ±1 LUFS, caption di dalam area aman. Hasil di `Clip.qc`; klip gagal QC tetap tampil dengan tanda.
- [ ] UI: grid hasil (ClipCard + ScoreBadge dengan tooltip rubrik + catatan rerank), pemutar, unduh 1 klip / ZIP semua (mp4 + `captions.txt` berisi judul, hook, deskripsi, hashtag per klip).

## Fase 4 — Klip: kontrol (akhir MVP)

- [ ] Editor caption: daftar kata per klip, ubah teks kata (tidak mengubah waktu), tombol "Simpan & render ulang". Perubahan disimpan ke `caption_overrides`, dan pasangan salah→benar ditawarkan masuk glosarium.
- [ ] Pilih judul & hook (2 opsi masing-masing), toggle teknik retensi, ubah start/end (dengan snap ke batas kata) → `POST /api/clips/{id}/render` merender klip itu saja.
- [ ] Rating suka/tidak + catatan → dipakai sebagai `liked_examples` di job berikutnya.
- [ ] Halaman Preferensi: default per mode, preset caption, editor glosarium.
- [ ] `POST /api/outputs/{id}/retry`; pembersihan otomatis `source.mp4` > 14 hari (transkrip tetap disimpan).
- [ ] **Definisi selesai MVP:** video YouTube 60 menit berbahasa Indonesia → ≥5 klip dalam ≤15 menit di Mac M-series; tidak ada klip terpotong di tengah kata; caption sinkron ±100 ms; retry tidak mengunduh/mentranskrip ulang; `make test` hijau; `make eval` tercatat.

## Fase 5 — Mode Ringkas

- [ ] `beats.py`: tiap kalimat = beat `speech`; bagian tanpa suara ≥1,5 dtk dipecah di scene cut, maks 20 dtk = beat `visual`. Skor aktivitas = rata-rata selisih frame (grayscale 160 px) dinormalkan 0–1.
- [ ] `vision.py`: frame tiap 5 dtk untuk beat visual, tiap 15 dtk untuk beat bicara; lebar 512 px (1024 px bila setting "tutorial layar"); batch 16 → prompt `frame_describer`; deskripsi digabung ke beat. Opsi `.env` `CONDENSE_VISION=frames|gemini_video` (default `frames`).
- [ ] `annotate.py`: per 15 menit beat → prompt `beat_annotator`; nilai dasar per label sesuai `cuplik-prompts.md` C2.
- [ ] `outline.py`: prompt `outline_builder`; validasi urut/tidak tumpang-tindih; beat `spec` otomatis masuk wajib; bab `core` otomatis wajib. Status Output → `awaiting_review` (kecuali setting "lewati tinjauan").
- [ ] UI tinjau outline: daftar bab (judul, tujuan, durasi asli), centang wajib/opsional, durasi target, tombol Lanjutkan → `PUT /api/outputs/{id}/outline`.
- [ ] `solver.py` (deterministik, dites unit):
  1. Semua beat wajib pada 1×; beat visual wajib boleh timelapse. Total > target → naikkan kecepatan bicara sampai `max_speech_speed` (default 1,15×) → masih lebih → hentikan dengan hasil `infeasible` + `min_duration_s`, UI menampilkan durasi minimum dan kembali ke tinjau.
  2. Sisa anggaran: beat lain urut `importance × focus_boost / durasi_terpakai` (greedy). Beat `manual` panjang dipercepat sehingga maks ±4 dtk per 30 dtk aslinya (2–8×).
  3. Buang potongan terisolasi <1,2 dtk; satukan potongan berjarak <0,5 dtk.
  4. Ulangi sampai total = target ±3%. Beat dengan `locked=true` (diubah user) tidak disentuh.
- [ ] `coherence.py`: prompt `coherence_checker` atas naskah hasil; terapkan `restore`/`bridge`; jalankan solver lagi; maks 2 putaran.
- [ ] `edl_render.py`: render 16:9 (atau 9:16 dengan reframe Fase 3) dari EDL — crossfade audio 80 ms antar potongan, `setpts` + `atempo` untuk percepatan (atempo berantai bila >2×; bagian timelapse >2× tanpa suara, opsional musik dari `data/music/` di −22 LUFS), lencana "⏩ N×" pojok kanan atas, kartu judul bab 2 dtk di sepertiga bawah, teks jembatan dari coherence, loudness −14 LUFS, QC sama seperti Fase 3.
- [ ] Keluaran: `condensed.mp4`, `chapters.txt` (dibuat kode dari waktu EDL: bab pertama 00:00, tiap bab ≥10 dtk), `summary.json` dari prompt `condense_summary`.
- [ ] UI: komponen EditTimeline (beat berwarna normal/percepat/buang per bab, klik untuk mengunci keputusan via `PATCH /api/beats/{id}`, ubah durasi target → `POST /api/outputs/{id}/solve` → pratinjau durasi tanpa render), lalu Render.
- [ ] Tombol "Buat Shorts dari hasil ringkasan" = Output mode Klip baru di Project yang sama, dibatasi ke beat yang dipertahankan.
- [ ] `make eval` untuk Ringkas: recall bab + spesifikasi, deviasi durasi.
- [ ] **Definisi selesai:** tutorial 2 jam → video 10 menit ±3% dalam ≤30 menit di Mac M-series; 100% bab wajib muncul; semua `spec` dari bab wajib muncul (di suara atau sebagai teks).

## Fase 6 — v1.1 / v2 (setelah dipakai 2 minggu)

Pembicara aktif (korelasi bukaan mulut Face Mesh dengan energi audio) + SPLIT; kurva Moment IQ interaktif (seret batas klip); narasi TTS penjembatan di Ringkas; B-roll Pexels; unggah langsung ke YouTube (Data API, resumable upload); MCP server (`create_clips`, `condense`, `get_output`); antrean batch.

## Design tokens (ringkas)

Gelap (default) / terang:
`bg #14120c/#faf7f0` · `surface #1e1b14/#ffffff` · `surface-raised #29251c/#f2ede2` · `line #3a3428/#e2dacb` · `ink #f5efe2/#1a170f` · `ink-muted #ada391/#6b6253` · `brand #f2b43a/#e0a21f` · `on-brand #1a1408` · `score-high #3fc2ae/#0e7c6d` · `score-mid = brand` · `score-low #8a8070` · `cut #f0694c/#c2412a` · `caption-hl #ffe14d` · `focus #7fb8ff/#1f5fbf`.
Spasi 4/8/12/16/24/32/48 · radius 6/10/16/pill · garis 1px, bayangan hanya modal.
Skor: ≥8 `score-high`, 5–7.9 `score-mid`, <5 `score-low` (outline, bukan merah).
EditTimeline: normal = `score-high`, percepat = `brand` bergaris, buang = `surface-raised` dengan garis `line`, beat wajib bertanda titik `ink`.

# Cuplik — rencana build yang disesuaikan

Dokumen kerja ini mengadaptasi `03-prompts/cuplik-claude-code-build.md` terhadap fondasi end-to-end yang sudah dibuat. Dokumen asli, blueprint, design system, dan library prompt di `03-prompts/` tetap menjadi referensi.

## Instruksi pelaksanaan

Kerjakan satu fase, jalankan pemeriksaan yang relevan, laporkan hasil dan cara mencoba, lalu **berhenti di akhir fase untuk pengguna memeriksa**. Jangan memulai fase berikutnya tanpa instruksi pengguna.

Instruksi pengguna saat ini: bangun dasar fungsional, sample API LLM dan workflow; **jangan masuk penerapan desain**. Karena itu token/tema merek pada checklist asli Fase 0 dicatat sebagai pekerjaan tertunda yang disengaja, bukan diterapkan diam-diam.

## Keputusan yang berlaku

- Web: Next.js 16 App Router, React 19, TypeScript 5.9; versi terkunci pada lockfile. Next 15 pada prompt asli digantikan sesuai status dukungan framework.
- API/worker: Python 3.12, FastAPI, SQLModel + SQLite WAL, Alembic, Redis + RQ SpawnWorker. Model transkripsi opsional.
- Mode mock bawaan untuk demonstrasi tanpa API key; adaptor Gemini/Anthropic/Ollama nyata tersedia melalui .env.
- UI berikutnya memakai **Mantine 9.8.1** sesuai instruksi pengguna. Paket sudah dipasang dan dikunci bersama Tiptap 3.34.0 dan Embla 8.6.0; antarmuka saat ini tetap form standar. Provider, CSS, tema dan token diterapkan pada pekerjaan desain terpisah.
- Struktur modul pipeline yang sudah ada dipertahankan. `media`, `llm`, `storage` adalah modul bersama; `planning`/`render` mengisi dasar kedua mode; `solver` khusus Ringkas. Tidak perlu memindah file demi menyamakan contoh folder pada prompt lama.

## Fase 0 — kerangka dan checkpoint fondasi

- [x] Struktur `web/`, `api/app/`, `worker/pipeline/`, `worker/prompts/`, `eval/golden/`, dan `data/` yang diabaikan Git.
- [x] Makefile: `install`, `dev`, `test`, `lint`, `build`, `e2e`, `types`, `migrate`, `eval`, `sample`, `update-ytdlp`.
- [x] Model Project, Output, Clip, Beat, Chapter, Preference, GlossaryTerm dan migrasi Alembic. Upload/JobEvent adalah model tambahan untuk resumable upload dan event persisten.
- [x] `/api/health`, satu worker RQ, dan SSE `/api/outputs/{id}/events`. Workflow demo nyata menggantikan kebutuhan job dummy.
- [x] Navigasi Buat, Riwayat, Preferensi, ditambah Uji LLM; tanpa penerapan desain.
- [x] `.env.example`, Docker Compose empat layanan, dan pengembangan native.
- [x] Kontrak `expected.json` diimplementasikan pada `eval/evaluate.py`. Evaluasi kualitas belum dilakukan.
- [ ] Penerapan token dan tema: ditunda sesuai instruksi pengguna.
- [x] Pengguna memberi instruksi "lanjut" setelah checkpoint Fase 0.

Fondasi yang sudah dibuat juga mencakup versi sederhana beberapa alur fase selanjutnya. Keberadaan alur itu **tidak berarti kriteria produksi fase tersebut sudah terpenuhi**.

## Fase 1 — ingest dan transkrip produksi

Audit dan perkuat implementasi yang sudah ada, jangan membangun ulang: probe YouTube, unggah resumable, cache Project, Whisper opsional dan segmentasi. Lengkapi glosarium, anti-halusinasi, progress transkripsi, pemulihan crash, kebijakan yt-dlp, dan uji dengan video Indonesia nyata. Berhenti setelah tes serta laporan fase.

- [x] Probe satu video YouTube, penolakan playlist/live/upcoming/tanpa audio, dan pesan pemulihan yang spesifik.
- [x] Unggah bertahap, pemeriksaan offset, validasi ffprobe, serta finalisasi ulang setelah API terputus.
- [x] Cache sumber tervalidasi dan WAV 16 kHz mono; cache rusak dipulihkan dari sumber.
- [x] Whisper per bagian dengan checkpoint atomik, VAD, waktu/ID per kata, bahasa pilihan, dan glosarium.
- [x] Segmentasi jeda/tanda baca/maksimal 25 kata; penggabungan fragmen pendek tanpa melintasi hening panjang.
- [x] Penyaringan n-gram berulang dan no-speech dengan laporan audit.
- [x] Progres proyek SSE, pembacaan transkrip, retry, serta glosarium melalui API dan form dasar.
- [x] Task outbox SQLite, pengiriman ulang setelah Redis pulih, dan recovery worker berdasarkan lock proses.
- [x] Pemeriksaan pembaruan yt-dlp saat startup dan setiap hari pukul 03:00; instalasi terisolasi dan fallback.
- [x] Tes offline, browser, dan uji video Indonesia nyata dengan penghentian paksa worker.
- [x] Pengguna memberi instruksi "lanjutkan" setelah checkpoint Fase 1.

## Fase 2 — kualitas pemilihan Klip

Adaptasikan library prompt asli ke schema fondasi. Tambahkan Moment IQ, validasi batas kata, evaluasi golden set, dan ukur rerank/keragaman. Prompt fondasi saat ini menggabungkan seleksi dan penilaian; migrasikan secara terukur. Berhenti untuk review.

- [x] Moment IQ per detik, sinyal media nyata, smoothing lima detik dan cache proyek.
- [x] Prompt produksi moment_finder/scorer/reranker dengan schema terpisah, template data aman dan satu repair JSON.
- [x] Window delapan menit, overlap maksimum klip, contoh suka maksimal tiga, deduplikasi kandidat.
- [x] Scorer batch enam, rumus skor dasar dan koreksi IQ, finalis maksimal 20.
- [x] Trim/batas kata/padding aman, batas 180 detik, deduplikasi IoU dan maksimal dua klip per topik.
- [x] Audit peringkat/keragaman dan kemasan klip melalui API/form standar, migrasi kompatibel hasil lama.
- [x] Evaluator IoU ≥0,5, perbandingan sebelum/sesudah, fixture sintetis dan penanda kualitas yang belum dijalankan.
- [x] Tes backend/browser dan integrasi media Indonesia nyata dengan transkrip per kata.
- [ ] Evaluasi kualitas editorial pada 10 video beranotasi manusia dengan provider nyata: dataset belum tersedia.
- [x] Pengguna memeriksa checkpoint Fase 2 dan meminta caption lebih ringkas serta video lebih jelas.

### Koreksi hasil review Fase 2

- [x] Analisis visual lokal YuNet, orientasi sumber untuk rekaman layar/konteks, crop hanya untuk pembicara stabil dan opsi vertikal aman.
- [x] Caption frasa pendek, ukuran font terukur, area terpisah dan penekanan hook duplikat.
- [x] Pemutar lebih besar, pilihan pembingkaian dan tombol memperbarui hasil lama tanpa LLM/ASR ulang.
- [x] Tiga contoh video Indonesia dirender ulang, tes backend/browser dan runtime Docker.
- [x] Pengguna menyetujui hasil perbaikan render dan memberi instruksi "lanjut" untuk Fase 3.

## Fase 3 — video Klip produksi

Ganti crop tengah statis dengan reframe, paket retensi, karaoke per kata, normalisasi loudness, thumbnail dan QC produksi sesuai blueprint. Ukur performa sebelum menjanjikan target waktu. Berhenti untuk review.

Bagian dasar framing dan caption dari koreksi review di atas menjadi dasar implementasi Fase 3 berikut.

- [x] YuNet lokal pada 640 px setiap tiga frame, target spasial stabil, EMA/zona mati, reset pada cut, fallback blur, dan jejak crop per frame.
- [x] EDL dan peta waktu, jeda keluaran 120 ms, pengisi terisolasi, zoom/emphasis, serta cold open/whoosh opsional yang mati secara default.
- [x] Caption ringkas sesuai review, karaoke kata aktual, keyword/emoji opsional, dan area teks terpisah.
- [x] Pipeline raw frame Python–FFmpeg, AAC, crossfade 10 ms, normalisasi dua lintasan dan headroom AAC.
- [x] Thumbnail tajam pada 30% awal, poster/unduhan JPEG dan ZIP berisi deskripsi/hashtag.
- [x] QC file akhir: stream/dimensi, durasi ±100 ms, hitam/hening, loudness/peak, safe area; kegagalan QC tetap dapat ditinjau.
- [x] Tes backend/browser, uji media nyata, uji gerakan neural terkontrol, Docker dan pengukuran render kecil.
- [x] Pengguna meminta riset sebelum melanjutkan, lalu menyetujui kelanjutan ke Fase 4 setelah hasil riset disampaikan.

### Checkpoint riset sebelum Fase 4

Pengguna meminta riset karakter video pendek/tutorial dan traffic platform sebelum melanjutkan. Hasilnya menjadi masukan penyesuaian fase, dengan pembatasan kerja satu fase dan penundaan penerapan desain tetap berlaku.

- [x] [Riset 19 November 2026](docs/research-short-tutorial-2026-11-19.md): YouTube, TikTok, Reels, konteks Indonesia, 11 metadata video publik dan tiga pemeriksaan sampel visual.
- [x] Catat perbedaan keluaran Shorts vertikal/persegi dengan tutorial 16:9, kebutuhan menjaga langkah/objek, caption ringkas, serta batas interpretasi traffic.
- [x] Pengguna menyetujui hasil riset dan memberi instruksi melanjutkan implementasi Fase 4.

## Fase 4 — kontrol Klip

Perkuat editor caption/hook, render ulang, dan glosarium yang sudah ada; tambahkan preferensi output yang dapat disunting, retensi per klip, serta penggunaan rating dalam prompt. Adaptasikan kontrol tujuan/platform dari riset. Laporkan hasil pengujian fungsional serta gate MVP yang belum dapat dibuktikan; jangan menyatakan MVP selesai hanya karena implementasi kontrol selesai.

- [x] Koreksi per kata memakai ID dan timestamp asli; fallback kalimat menandai estimasi. Koreksi lama dipetakan ke kata saat trim jika waktunya pasti.
- [x] Penawaran koreksi ke glosarium, serta tambah/ubah/hapus istilah melalui form dasar.
- [x] Trim start/end dengan snap kata atau kalimat, validasi 1–180 detik, dan perubahan atomik.
- [x] Tujuan tutorial/jangkauan, platform terpisah dari framing, preset caption dan retensi per klip. Tutorial menjaga jeda secara bawaan; profil video pendek memakai kanvas 9:16 yang diperiksa terhadap file hasil.
- [x] Preferensi per mode tersimpan, dipakai pada output baru dan dapat ditimpa request; hasil lama tidak berubah.
- [x] Rating beserta catatan, maksimal tiga contoh suka dengan tujuan serupa pada job berikutnya.
- [x] Render satu klip memakai rencana/cache tanpa LLM/ASR ulang; stale download tetap ditolak.
- [x] Pembersihan salinan sumber tidak terpakai >14 hari dengan lock dan perlindungan task aktif; unggahan asli, audio, transkrip serta hasil tetap disimpan.
- [x] Tes backend/browser, build native/image produksi, smoke empat layanan Docker, migrasi salinan data lama, serta contoh video Indonesia.
- [ ] Gate kualitas MVP: golden set manusia/provider nyata dan pemeriksaan sinkron ucapan manual ±100 ms belum tersedia.
- [ ] Gate performa MVP: video Indonesia 60 menit → ≥5 klip dalam ≤15 menit pada Mac M-series belum diukur; mesin sesi ini Linux ARM64.
- [x] Setelah checkpoint Fase 4, pengguna meminta kelanjutan PR pekerjaan. Awal Fase 5 dibatasi ke daftar bab/paket Ringkas yang ringan.

## Fase 5 — Ringkas produksi

Perluas workflow outline/solver/render yang sudah ada dengan beat visual, vision, spesifikasi wajib, koherensi, timelapse, kartu bab, dan daftar bab platform yang valid. Ukur recall bab dan durasi terhadap golden set. Berhenti untuk review.

### Bagian awal — daftar bab dan paket Ringkas

- [x] Garis waktu dari durasi segmen encode dan durasi MP4 akhir, terpisah dari estimasi solver.
- [x] Indeks bab untuk tinjauan dan validasi teks YouTube: mulai 00:00, minimal tiga timestamp berurutan, setiap bab minimal 10 detik.
- [x] Unduh indeks TXT/laporan JSON dan paket ZIP Ringkas; teks YouTube disertakan hanya ketika pemeriksaan format lolos.
- [x] Hasil lama tetap terbaca dengan penanda waktu rencana yang belum diverifikasi.
- [x] Uji API, media, browser, tipe dan build.
- [x] Workflow anotasi manual Klip/Ringkas: siapkan sumber tanpa prediksi LLM, draft/review, revisi, validasi konflik dan ekspor paket dengan jejak sumber/transkrip.
- [x] Evaluator Ringkas memakai cakupan rentang sumber yang benar-benar dirender, recall bab/spesifikasi, serta deviasi durasi. Anotasi assisted, demo dan mock dipisahkan dari kualitas independen.
- [x] Fondasi fokus spasial Klip: area manual dan proposal aktivitas lokal opsional, fallback aman, jejak frame dan QC. Bukan pengenalan tangan/objek atau pemilihan beat visual Ringkas.
- [x] Ringkas opsional memakai beat bicara dan jeda transkrip ≥1,5 detik, dipotong pada perubahan adegan sampel/maksimal 20 detik; aktivitas lokal 2 fps sebagai petunjuk.
- [x] Sampling 5/15 detik dan adaptor gambar Gemini/Anthropic/Ollama, budget sebelum LLM, cache per tahap, laporan frame yang dapat ditinjau. Sampel 512 px atau 1024 px untuk layar; belum mengukur kualitas vision nyata.
- [x] Anotasi label/spec verbatim dan outline berdasarkan ID beat. Kode menjaga spesifikasi, instruksi pertama, hasil dan visual yang belum jelas; pengguna tetap meninjau sebelum render.
- [x] Solver mempertahankan kunci, memilih isi menurut nilai/durasi, memisahkan batas narasi dan visual, serta memprioritaskan timelapse yang telah disetujui sebelum mempercepat narasi.
- [x] Timelapse 2–8× untuk manual/idle/repeat visual dengan persetujuan per beat; audio hening, penanda kecepatan, timeline aktual dan pengamanan yang sama pada API/solver/renderer.
- [x] Pemeriksaan koherensi naskah opsional dengan ID sumber tervalidasi, cache dan maksimal dua putaran per persetujuan. Pemulihan konteks menjaga kunci/bagian wajib, menghitung ulang durasi dan mengembalikan rencana ke tinjauan. Laporan lama ditandai bila rencana berubah.
- [x] Overlay judul bab opsional hingga dua detik, berlanjut melintasi beat pendek, tanpa menambah durasi atau mengubah audio.
- [x] QC Ringkas: normalisasi audio dua lintasan, pemeriksaan file akhir dan timeline, pengecualian hening timelapse sesuai rentang persetujuan, serta laporan API/ZIP yang dapat ditinjau.
- [ ] Pengisian dan pengukuran dataset manusia: 10 sumber Klip dan 5 sumber Ringkas unik dengan provider nyata.
- [ ] Pelacakan aksi/tangan/objek sepanjang adegan dan video sepenuhnya tanpa transkrip. Kualitas pemeriksaan koherensi dengan model nyata belum diukur. Fase 5 belum selesai.

Status saat ini: QC Ringkas tersedia. Pengguna meminta kelanjutan berurutan ke UI responsif Mantine dan APK, dengan branch/PR tersendiri serta CI pada setiap perubahan.

- [x] UI Mantine mengikuti token studio Cuplik, font lokal, panel video responsif, form dan navigasi yang dapat diakses pada hape/tablet/laptop.
- [ ] APK Android dengan transkripsi dan pemrosesan video pada perangkat serta analisis transkrip melalui API LLM. Aplikasi tetap online; video tidak perlu diunggah untuk render.

## Fase 6

Fitur lanjutan hanya setelah fase sebelumnya dipakai dan diperiksa, mengikuti referensi asli.

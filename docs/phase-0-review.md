# Checkpoint Fase 0

Status: fondasi fungsional siap diperiksa pengguna. Fase 1 belum dimulai sebagai pekerjaan produksi terpisah. Rencana selanjutnya ada di `cuplik-claude-code-build.md` pada root.

## Yang tersedia

- Next.js 16 App Router dan TypeScript; form Buat, Riwayat, Preferensi, Uji LLM, proyek dan output.
- FastAPI/OpenAPI, SQLite WAL dan migrasi Alembic untuk tujuh model PRD serta Upload/JobEvent.
- Redis dan RQ SpawnWorker; pengembangan native serta Docker Compose empat layanan.
- Demo end-to-end Klip dan Ringkas yang menghasilkan MP4 melalui FFmpeg, dengan tinjauan bab dan unduhan ZIP.
- Adapter LLM mock/Gemini/Anthropic/Ollama, JSON tervalidasi, ID kalimat tervalidasi, token log, retry dan satu repair.
- Sumber/transkrip bersama per Project, progres SSE persisten, retry dari cache, serta render ulang klip yang diubah.
- Kontrak data golden set dan `make eval` yang melaporkan `not_run`; belum ada skor kualitas.

## Pemeriksaan yang dijalankan

| Pemeriksaan | Hasil |
|---|---|
| Backend pytest | 19 lulus; termasuk FFmpeg nyata, retry/cache, API, SSE, upload, dan transport ketiga provider |
| Ruff check dan format | Lulus |
| TypeScript dan build produksi Next.js | Lulus |
| Alembic check | Model dan migrasi sinkron |
| Playwright browser end-to-end | Lulus: sample LLM, kedua mode, reload, edit caption, ZIP, target mustahil, render Ringkas dan Riwayat |
| Docker build dan Compose startup | Lulus; worker container menghasilkan MP4 yang diunduh melalui web |
| Upgrade pada database berisi data | Lulus; proyek/klip lama tetap terbaca, lalu sumber yang sama menghasilkan Ringkas 20,02 detik untuk target 20 detik |
| Generator kontrak API | OpenAPI dan tipe TypeScript menghasilkan isi identik saat dijalankan ulang |
| Golden set | Belum dijalankan; anotasi pengguna belum tersedia |

Tes LLM memakai mock transport. Panggilan cloud dengan API key, pengunduhan YouTube eksternal, bobot Whisper, dan benchmark video panjang belum diuji. Tes backend memiliki satu peringatan deprecation dari adapter TestClient Starlette terhadap HTTPX 0.x; tidak ada tes yang gagal.

## Cara review

1. `cp .env.example .env` jika belum punya konfigurasi.
2. `make install` lalu `make dev`, atau `docker compose up --build`.
3. Buka `http://localhost:3000`, jalankan demo dengan kedua mode.
4. Periksa MP4 Klip, ubah caption/hook, dan render ulang satu klip.
5. Di Ringkas, uji target 3 detik lalu 20 detik, setujui bab, dan unduh hasil.
6. Periksa Uji LLM serta API melalui tautan dokumentasi pada navigasi.

## Bagian yang sengaja ditunda

Penerapan token, tema, Tailwind/shadcn dan desain visual ditunda sesuai instruksi pengguna. Tracking wajah, karaoke per kata, retensi, vision, glosarium aktif, pembelajaran rating, QC produksi, dan evaluasi kualitas tetap menjadi pekerjaan fase selanjutnya. Model preferensi/glosarium disiapkan, tetapi editor dan penerapannya pada pipeline belum dibuat.

Berhenti pada checkpoint ini untuk pemeriksaan pengguna.

Layanan uji dihentikan setelah verifikasi. Named volume Compose tetap menyimpan contoh hasil; `docker compose up -d` menjalankannya kembali tanpa menghapus data. Jalur native `make dev` menggunakan direktori `data/` terpisah dari volume Docker.

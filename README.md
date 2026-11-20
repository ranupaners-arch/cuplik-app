# Cuplik

Fondasi aplikasi video pribadi: **Klip** menghasilkan beberapa MP4 dengan pembingkaian adaptif; **Ringkas** menyusun outline, menunggu tinjauan bab, lalu menghasilkan satu MP4. Antarmuka berupa form dasar untuk membuktikan workflow. Design system asli belum diterapkan.

UI berikutnya memakai **Mantine** sesuai pilihan pengguna. Paket sudah terpasang dan dikunci; penerapan tema serta penggantian komponen dilakukan pada pekerjaan desain terpisah.

## Jalankan lokal

Prasyarat: [uv](https://docs.astral.sh/uv/), Node.js 26 (atau Node ≥22.12 yang didukung Next.js), npm, FFmpeg/ffprobe dengan libass dan libx264, serta Redis atau Valkey yang menyediakan perintah `redis-server`. Python 3.12 dipasang otomatis oleh uv bila perlu.

```sh
cp .env.example .env
make install
make dev
```

Buka **http://localhost:3000**, API interaktif **http://localhost:8000/docs**. `make dev` menjalankan Redis pada 6386, migrasi SQLite, FastAPI, satu worker RQ, dan Next.js. Ctrl+C menghentikan proses yang dibuat supervisor. Port yang sudah dipakai ditolak; proses lain tidak dihentikan.

`make` atau `make help` menampilkan daftar perintah. `make doctor` memeriksa setup native secara lokal tanpa menjalankan aplikasi, mengunduh model, atau merender video.

## Coba dari awal sampai akhir

1. Pada halaman **Buat**, gunakan **Video demo sintetis** dan mode **Klip dan Ringkas**.
2. Tekan **Mulai proses**. Buka output Klip dan lihat progres worker; reload atau tutup tab tetap aman.
3. Putar MP4, pilih hook/judul, koreksi caption, lalu **Simpan dan render ulang klip**. Unduh MP4 atau ZIP.
4. Buka output Ringkas melalui Riwayat. Tinjau bab wajib, coba target 3 detik untuk melihat penolakan durasi, lalu gunakan 20 detik dan setujui render.
5. Buat output lain dari halaman proyek untuk memakai ulang sumber dan transkrip yang sama.

Pada hasil Ringkas, buka **Daftar bab dan unduhan** untuk mengambil indeks TXT serta laporan JSON. Timestamp output baru mengikuti durasi segmen encode. Versi teks YouTube tersedia hanya jika pemeriksaan format lolos; demo pendek tetap memiliki indeks tinjauan.

Ringkas juga dapat memakai **Transkrip dan frame (vision)** pada form Buat. Pilih ukuran sampel dan batas frame; setelah outline siap, buka **Bukti visual Ringkas** serta **Keputusan per beat**. Demonstrasi di sela narasi ikut menjadi beat visual, dengan audio tetap dipertahankan. Adaptor mendukung model gambar provider yang dikonfigurasi melalui `LLM_MODEL_VISION` (kosong memakai model teks); mode bawaan tetap transkrip.

Untuk memperpendek pengerjaan visual, aktifkan timelapse pada kontrol kecepatan, tinjau sumber, lalu setujui beat manual/idle/repeat yang sesuai. Tekan **Hitung durasi tanpa render** untuk menerapkan batas dan melihat rencana. Timelapse 2–8× mengganti audio bagian tersebut dengan hening serta menampilkan penanda kecepatan. Spesifikasi dan hasil dilindungi; narasi mengikuti batas tersendiri.

Ringkas juga menyediakan **Periksa koherensi sebelum render** dan **Tampilkan judul bab selama dua detik**, keduanya nonaktif secara bawaan. Pemeriksaan LLM memakai maksimal dua putaran per persetujuan dan cache. Pemulihan konteks menghitung ulang durasi lalu kembali ke tinjauan; masalah yang belum selesai atau konteks terkunci perlu keputusan pengguna. Laporan menandai perubahan rencana setelah pemeriksaan. Judul bab tampil sebagai overlay singkat, tanpa menambah durasi atau mengubah audio. Provider mock hanya memverifikasi alur, bukan kualitas koherensi.

Untuk menyiapkan dataset kualitas, pilih mode **Siapkan sumber untuk anotasi** pada halaman Buat. Setelah transkrip siap, buka `/projects/<id>/evaluate`, tandai momen atau bab/spesifikasi wajib, simpan draft, lalu konfirmasikan tinjauan manual untuk ekspor. Pemilihan LLM belum dijalankan pada mode ini.

Pada kontrol Klip, **Fokus visual** menawarkan mode aman, aktivitas eksperimental, atau area manual dalam persen sumber. Gunakan preview untuk memeriksa detail tugas; proposal aktivitas kembali ke bingkai utuh saat ambigu dan belum mengenali tangan/objek secara semantik.

Pada **Preferensi**, simpan default Klip/Ringkas. Profil **Tutorial** menjaga jeda dan bingkai sumber secara bawaan; profil **Jangkauan** menyediakan retensi yang lebih aktif. Platform Shorts/TikTok/Reels memakai kanvas 9:16, dengan catatan keterbacaan bila sumbernya rekaman layar lebar. Edit per kata tersedia jika transkrip memiliki timestamp kata; fallback per kalimat menandai estimasi. Awal/akhir klip dapat diubah dengan snap ke batas kata/kalimat. Rating dan catatan dari maksimal tiga klip yang disukai menjadi masukan pemilihan berikutnya dengan tujuan serupa.

Default **LLM_PROVIDER=mock**: pemilihan momen, skor, dan outline memakai fixture deterministik. Video demo berisi pola uji, nada sintetis, dan transkrip contoh. Render MP4, SQLite, Redis, worker, SSE, dan unduhan benar-benar berjalan. Mode mock tidak menghubungi provider LLM.

Untuk menguji unggah tanpa model transkripsi:

```sh
make sample
```

Pilih **Unggah video**, unggah `examples/sample.mp4` dan sidecar `examples/transcript.json`. Unggahan per chunk 4 MiB dapat dilanjutkan dengan memilih kembali berkas yang sama pada browser yang sama.

## LLM nyata

Isi konfigurasi server dalam `.env`, lalu jalankan ulang `make dev`:

```dotenv
LLM_PROVIDER=gemini
LLM_MODEL_FAST=nama-model-yang-tersedia-di-akun-anda
GEMINI_API_KEY=isi-key-anda
```

Alternatif: `LLM_PROVIDER=anthropic` dengan `ANTHROPIC_API_KEY`, atau `LLM_PROVIDER=ollama` dengan model yang tersedia pada Ollama dan `OLLAMA_BASE_URL`. Nama model tidak ditebak atau dikunci ke model provider yang mungkin dihentikan. Key hanya dibaca server; endpoint konfigurasi dan frontend tidak mengembalikannya.

Halaman **Uji LLM** dan contoh ini menguji JSON terstruktur tanpa render:

```sh
curl --fail-with-body http://localhost:8000/api/llm/sample \
  -H 'Content-Type: application/json' \
  -d '{"focus":"pencatatan uang usaha"}'
```

Adaptor Gemini, Anthropic, dan Ollama memakai schema Pydantic, retry terbatas untuk gangguan jaringan/429/5xx, serta satu kesempatan perbaikan JSON. ID kalimat divalidasi sebelum dipetakan ke timestamp. Penggunaan token dicatat dalam `data/outputs/<id>/llm_log.jsonl`; biaya uang tidak dikarang.

## Video nyata dan transkripsi

Mendukung **satu link HTTPS YouTube** atau unggah video, maksimal 4 GiB dan 3 jam secara default. Playlist dan live yang berlangsung ditolak. Akses YouTube mengikuti ketersediaan video dan yt-dlp; tes otomatis tidak mengunduh video eksternal.

Untuk video tanpa sidecar, pasang backend transkripsi:

```sh
# Linux/CPU atau NVIDIA sesuai konfigurasi Whisper
uv sync --extra transcription
# macOS Apple Silicon, jalankan native
uv sync --extra mlx
```

Di **Preferensi**, tambahkan glosarium satu kata (misalnya `nahu → nahwu`). Pilih bahasa pada form sumber, lalu unggah video tanpa sidecar. Halaman proyek menampilkan progres ingest/transkripsi, transkrip JSON, dan tombol retry jika gagal. Glosarium dipakai sebagai petunjuk Whisper dan koreksi deterministik tanpa mengubah waktu kata; transkrip yang sudah selesai tetap memakai cache.

Audio disimpan sebagai WAV 16 kHz mono. Default checkpoint setiap 60 detik (`WHISPER_CHUNK_SECONDS`); penghentian proses hanya mengulang bagian yang belum selesai. Filter VAD/no-speech dan pengulangan mencatat keputusan pada `data/projects/<id>/transcription/report.json`.

`faster-whisper==1.2.1` dibatasi ke **PyAV <19** karena PyAV 19 menghapus argumen yang masih dipakai rilis tersebut.

Whisper mengunduh bobot ketika pertama dipakai. Default `small` dipilih untuk percobaan awal pada CPU; model/device/compute type dapat diubah dalam `.env`. `uv sync` tanpa extra mengembalikan dependensi minimum. Demo dan sidecar tetap berjalan tanpa bobot AI lokal.

## Docker Compose

```sh
docker compose up --build
```

Empat layanan: web, API, worker, Redis. SQLite/media dan antrean memakai named volume. Port web/API hanya dibuka pada loopback. Default image menyediakan demo/sidecar dan Node untuk ekstraksi YouTube. Untuk menyertakan faster-whisper:

```sh
CUPLIK_TRANSCRIPTION_EXTRA=transcription docker compose up --build
```

MLX tetap dijalankan native pada Apple Silicon. Ollama pada host membutuhkan alamat yang dapat dicapai container melalui `OLLAMA_BASE_URL`.

Antrean menyimpan intent `Task` di SQLite sebelum dikirim ke Redis. Bila Redis terputus, request tetap menyimpan pekerjaan sebagai queued; worker mengirimkannya setelah koneksi pulih. Worker yang mati dilanjutkan dari checkpoint setelah lock proses dilepas. Error pemrosesan biasa tetap ditampilkan sebagai gagal dan membutuhkan retry pengguna.

yt-dlp diperiksa saat worker mulai dan setiap hari pukul 03:00 Asia/Jakarta. Pembaruan dipasang di `data/tools/yt-dlp/`, tanpa mengubah virtualenv atau lockfile aplikasi. Versi sebelumnya tetap dipakai jika jaringan/update gagal. `make update-ytdlp` memeriksa pembaruan segera; `YTDLP_AUTO_UPDATE=false` menonaktifkan pemeriksaan otomatis.

## Pemeriksaan

```sh
make doctor    # cek setup lokal; tanpa render, server, atau panggilan LLM
make test      # kontrak API, provider transport, solver, SSE, render FFmpeg nyata
make lint      # Ruff dan TypeScript
make build     # build produksi Next.js
make e2e       # Chromium + API + Redis + RQ + FFmpeg sungguhan
make types     # OpenAPI → tipe frontend
make eval      # kualitas Klip/Ringkas; not_run sampai anotasi/prediksi tersedia
make eval-fixtures # validasi mekanisme evaluator, tidak dihitung kualitas
make validate-ingest VIDEO=/path/ke/video-indonesia.mp4  # opt-in: ASR nyata + crash recovery (Linux)
```

Untuk E2E, pasang browser dengan `cd web && npx playwright install chromium` bila belum tersedia. `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` dapat menunjuk browser sistem. E2E memakai port 3100/8100/6390 dan data sementara, selalu dengan mock LLM. CI menjalankan pemeriksaan yang sama.

## Batas fondasi

- Klip memakai Moment IQ, tiga prompt produksi, batas timestamp kata, pembatas keragaman topik, serta pelacakan YuNet per frame. Caption ringkas/karaoke mengikuti peta waktu retensi. Rekaman layar tetap utuh; kehilangan target pada potret memakai latar blur. Teknik retensi dapat diubah per klip.
- Ringkas menyediakan analisis frame opsional, label beat, bukti gambar, timelapse dengan persetujuan per beat, pemeriksaan koherensi naskah, dan overlay judul bab. Masih memerlukan transkrip minimal satu kalimat. Pemeriksaan konteks memakai jendela terbatas dan belum membuktikan kualitas model nyata; solver menjaga bab wajib/beat terkunci dan menampilkan deviasi target secara eksplisit.
- Batas tinggi ekspor default 1280px, mengikuti ukuran sumber. Audio dinormalisasi dua lintasan menuju −14 LUFS; QC mengukur durasi, gambar hitam, hening, loudness/peak dan caption pada MP4 akhir. Thumbnail dan rincian QC tersedia pada hasil. Klip yang memerlukan tinjauan tetap dapat diunduh.
- Akurasi Whisper, benchmark satu jam pada hardware target, dan kualitas golden set manusia belum diklaim tercapai.
- Maksimal tiga klip dari output terbaru yang diberi suka menjadi contoh pencarian momen berikutnya. Koreksi caption tidak mengubah timestamp.
- Evaluator IoU Klip dan cakupan bab/spesifikasi Ringkas tersedia, tetapi golden set 10 sumber Klip/5 sumber Ringkas manusia dan kualitas provider nyata belum diukur. Draft, assisted, sumber tidak terverifikasi, mock dan fixture sintetis tidak masuk skor kualitas.
- Aplikasi pribadi sesuai PRD, belum memiliki autentikasi. Akses publik membutuhkan kontrol akses tersendiri.

## Struktur

### Android

APK Android memakai UI Mantine yang dibundel, Whisper.cpp untuk transkripsi lokal, dan Media3 untuk ekspor di perangkat. Mendukung Android 10+ pada arm64 dan x86_64. Internet digunakan untuk mengunduh model sekali serta analisis teks melalui Gemini/Anthropic; pemrosesan media tidak memerlukan server/laptop.

Di aplikasi, buka **Pengaturan API AI dan model transkripsi**, isi kunci milikmu, simpan, lalu **Periksa koneksi dan model**. Pilih model dari daftar akun dan simpan kembali. Aktifkan izin pengiriman teks bila ingin analisis AI. Unduh model transkripsi, pilih video, susun dan tinjau rencana, lalu ekspor serta simpan MP4. Pilihan manual tersedia tanpa API. Cache transkripsi dan hasil ekspor dapat dipakai ulang; pembersihan lokal meminta konfirmasi dan mempertahankan model serta pengaturan AI.

Caption Android mengikuti ukuran frame hasil: frasa maksimal tiga kata pada potret atau lima pada lanskap, dengan lebar aman berdasarkan pengukuran glif. Kata panjang dipecah tanpa elipsis. Waktu frasa diperkirakan di dalam segmen transkripsi; belum merupakan alignment kata yang terukur.

Setiap video Android menjadi proyek lokal tersendiri. Proyek sebelumnya dapat dibuka kembali beserta transkrip, checkpoint, keputusan edit dan hasil ekspornya; pemilihan proyek memerlukan tombol buka yang eksplisit. Rencana yang sedang diedit disimpan sebelum berpindah, sementara koreksi transkrip harus disimpan terlebih dahulu. Arsip disimpan atomik per proyek, dan daftar arsip dapat dipulihkan jika catatan aktif rusak.

Pekerjaan Android disimpan sebelum layanan mulai. Jika proses sistem terhenti, buka kembali aplikasi dan pilih **Coba ulang pekerjaan sebelumnya**; sumber, pengaturan, checkpoint transkripsi dan ekspor selesai dipakai ulang. Mengubah sumber, transkrip, rencana atau API membatalkan kelayakan retry lama. Pembatalan juga menghentikan komputasi Whisper dan koneksi API yang sedang berjalan.

Untuk build lokal, siapkan JDK 17, Android SDK 36, NDK `27.0.12077973`, CMake `3.22.1`, lalu `make android`. CI membangun APK debug dan menjalankan tes unit, lint serta smoke test transkripsi/render pada emulator. Debug APK untuk pemeriksaan/sideload. Build bertanda tangan memakai environment `android-signing`, hanya melalui dispatch pemilik setelah seluruh tes lulus. Environment dibatasi ke `main` dan branch penyiapan `feat/android-stable-builds`; kunci/password disimpan sebagai secrets environment. Sertifikat tetap diperiksa terhadap `android/signing-cert.sha256`, beserta alignment native 16 KB, versi, commit dan SHA-256 APK.

Jalankan `gh workflow run checks.yml --ref main -f build_signed_apk=true` setelah PR signing digabung. Artifact `cuplik-android-signed` berisi APK berversi dan `build-info.json`. Cadangan kunci lokal berada di `~/.local/share/cuplik/signing/` (di luar repo); simpan cadangan privat agar pembaruan tetap memakai sertifikat yang sama. APK debug lama memakai sertifikat berbeda dari APK bertanda tangan, sehingga pemasangan awal yang menggantikannya memerlukan simpan MP4 lalu uninstall versi debug.

 QC Android memeriksa durasi MP4, keberadaan track dan sampel audio akhir (RMS/peak dBFS, bagian hening dan level mendekati batas). Temuan meminta tinjauan, tanpa mengubah suara secara otomatis. Pengukuran LUFS, vision, serta pelacakan pembicara web belum dipindahkan ke Android. Kualitas model/API dan performa perangkat fisik perlu diukur.

### Direktori proyek

| Lokasi | Isi |
|---|---|
| `web/` | Next.js, form workflow, tipe API, E2E Playwright |
| `android/` | APK, bridge lokal, Whisper JNI, Media3 dan tes perangkat |
| `api/` | FastAPI, SQLModel, Alembic, upload, SSE, ekspor |
| `worker/` | Ingest/cache, LLM, validasi, solver, FFmpeg |
| `tests/` | Tes backend dan integrasi media |
| `docs/` | Keputusan teknologi dan kontrak OpenAPI |
| `01-blueprint/` | PRD dan blueprint asli |
| `02-design-system/` | Token dan prototipe asli, tetap terpisah |
| `03-prompts/` | Library prompt dan rencana asli |

Keputusan teknologi: [engineering.md](docs/engineering.md). Rencana per fase: [cuplik-claude-code-build.md](cuplik-claude-code-build.md). Referensi produk: [riset video pendek/tutorial](docs/research-short-tutorial-2026-11-19.md). QC Ringkas tersedia melalui detail output, endpoint QC dan ZIP. Pengukuran kualitas model nyata serta performa tetap terbuka.

Untuk memperbarui klip lama, jalankan ulang aplikasi lalu gunakan kontrol render ulang. Pengaturan `.env` lama `RENDER_HEIGHT=640` dapat dinaikkan menjadi 1280.

Salinan `source.mp4` yang tidak dipakai selama 14 hari dibersihkan otomatis (`SOURCE_CACHE_DAYS`). Unggahan asli, audio, transkrip dan hasil tetap disimpan; sumber yang kedaluwarsa dipulihkan saat diperlukan. Sumber URL dapat memerlukan unduhan ulang. Detail perlindungan task/lock dan batas kebijakan ini ada pada review Fase 4.

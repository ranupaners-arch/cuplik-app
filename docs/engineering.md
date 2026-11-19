# Keputusan fondasi Cuplik

Diperbarui: 19 November 2026, sampai kontrol Fase 4. Scope: workflow end-to-end, sample API LLM, ingest, pemilihan Klip, renderer serta kontrol tujuan/platform, caption, trim dan preferensi. UI berupa form standar; tidak ada pekerjaan penerapan design system.

## Stack

- **Next.js 16.4.6, React 19.3.1, TypeScript 5.9.** Next 16 dipilih menggantikan 15 dalam blueprint karena 16 Active LTS saat pemeriksaan, sedangkan 15 Maintenance LTS. Sumber: [support policy](https://nextjs.org/support-policy). TypeScript 5.9 menghindari migrasi compiler major yang tidak diperlukan. Versi JavaScript dikunci melalui `package-lock.json`.
- **Python 3.12.** Menggantikan 3.11 dalam rancangan; dipilih untuk kompatibilitas pustaka transkripsi dibanding Python 3.14 bawaan mesin. Extra Whisper dipisahkan agar fondasi dapat berjalan tanpa bobot model. Node 26 mengikuti runtime yang tersedia; kebutuhan minimum aplikasi tercatat pada package.json.
- **FastAPI + SQLModel + SQLite WAL + Alembic.** Dependensi Python dikunci dalam `uv.lock`. Migrasi awal merupakan snapshot schema, bukan `create_all` dari model terbaru. Timeout SQLite dan transaksi `BEGIN IMMEDIATE` melindungi perubahan yang bergantung pada status output.
- Migrasi Fase 1 menambah kolom melalui default konstan dan backfill agar SQLite tidak membangun ulang tabel Project yang direferensikan Output. Transaksi DDL dimulai eksplisit; upgrade diuji pada database yang sudah berisi data dan pada schema parsial akibat migrasi terputus.
- **Redis + satu RQ SpawnWorker.** Proses video terpisah dari request HTTP dan tab browser. SpawnWorker menghindari ketergantungan fork untuk jalur native macOS. Redis dev normal dan Compose menyimpan AOF; E2E memakai antrean/data terisolasi yang dibuang setelah tes.
- **HTTPX + Pydantic untuk adaptor LLM.** REST yang kecil cukup untuk Gemini, Anthropic tool-use, dan Ollama structured JSON. Tidak ada model cloud default yang berpotensi salah nama/masa aktif; nama model harus dikonfigurasi. [Gemini structured outputs](https://ai.google.dev/gemini-api/docs/structured-output), [Anthropic tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview), [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs).
- Tailwind, shadcn, font merek, dan token desain belum dipasang karena instruksi saat ini berfokus pada dasar fungsional. Komponen domain dipisahkan agar desain berikutnya tidak perlu mengubah workflow.

## Kontrak workflow

`Project` memiliki satu sumber dan transkrip yang dapat dipakai banyak `Output`. Pembuatan proyek mengantrikan ingest; output dapat langsung dibuat dan menyiapkan cache yang sama ketika gilirannya dijalankan. Lock per proyek melindungi ingest bersamaan.

Klip: `queued → running (ingest → signals → moments → scoring → rerank → render) → done`, atau `failed`. Fase 2 menggantikan pemilihan gabungan dengan tiga prompt dari library asli. Pencarian memakai jendela delapan menit dan overlap sepanjang maksimum klip; scorer per enam kandidat; reranker maksimal 20 finalis. Skor dihitung Python dari rubrik dan koreksi Moment IQ ±0,5, sementara urutan mengikuti reranker. Batas kata, rentang durasi, ID, anotasi verbatim, IoU dan batas dua klip per topik ditegakkan kode. Sample `/api/llm/sample` tetap memakai kontrak gabungan lama agar kompatibel.

Jumlah klip default menjadi delapan sesuai blueprint; hasil maksimum 12 dan dapat lebih sedikit setelah validasi. `min_clip_seconds` default tiga menjaga demo/sidecar pendek tetap berguna, maksimum default 60 dan batas keras 180. Untuk video panjang, pengguna dapat memilih minimum 15–30 detik melalui form dasar. Renderer Fase 3 menggunakan metadata emphasis; cold open opsional mati secara default dan tidak melewati batas 180 detik.

Ringkas: `queued → running → awaiting_review → queued → running (render) → done`. Outline harus mencakup semua kalimat dalam urutan. Solver tidak membuang kalimat inti bab wajib, dan mempertahankan keputusan terkunci. Target mustahil menghasilkan HTTP 409 dengan `min_duration_s`, tanpa render atau menyimpan sebagian tinjauan yang gagal. Solver merupakan baseline deterministik, belum optimizer visual/koherensi produksi.

Progres output memakai `/api/outputs/{id}/events`; ingest/transkripsi memiliki `/api/projects/{id}/events`. Event tersimpan di SQLite dengan ID monoton dan dapat diputar ulang melalui `Last-Event-ID` atau `after`. Browser membaca snapshot untuk menghindari mundurnya progres ketika event lama diputar ulang; polling menjadi cadangan. SSE tidak menjalankan job. Progres proyek menunjukkan tahapan selesai dengan catatan detik audio yang telah diproses, bukan estimasi waktu selesai.

Unggah: `POST /api/uploads` membuat sesi; `PUT /api/uploads/{id}?offset=N` menambahkan chunk maksimal 4 MiB; `GET` mengembalikan offset aktual disk. ID berkas dibuat server; nama asli tidak dipakai sebagai path. Offset salah ditolak, ukuran dibatasi, dan chunk terakhir divalidasi ffprobe. API tidak menerima URL arbitrer atau path file dari pengguna.

## Checkpoint dan recovery

- Sumber/transkrip disimpan di `data/projects/<id>/`. JSON ditulis melalui temporary file dan rename.
- Rencana klip/outline tersimpan di SQLite. Retry render memakai ulang rencana dan tidak memanggil LLM ulang bila rencana tersimpan.
- Sinyal media disimpan per proyek, dengan fingerprint sumber/audio/transkrip/versi. Balasan prompt Fase 2 yang lolos schema disimpan per output dengan fingerprint input/template/schema/provider/model; tahap yang selesai tidak diulang saat worker perlu mencoba ulang seleksi. Audit `selection.json` mencatat fallback dan penolakan. Tambahan `Clip.selection` memakai migrasi kolom langsung dengan default JSON `{}`, diuji pada hasil Fase 1 yang sudah terisi.
- Cache render memakai fingerprint pengaturan, caption, hook, rentang, dan resolusi. MP4 baru menggantikan hasil lama secara atomik. Unduhan/ZIP ditolak bila perubahan belum dirender.
- Update klip ditolak ketika output diproses. Klaim job memakai update status bersyarat agar dua request tidak memulai render bersamaan.
- Fase 1 menambahkan outbox `Task`: intent disimpan bersama status antrean, lalu dikirim ke Redis dengan ID deterministik. Jika Redis terputus, Task tetap pending dan API mengembalikan keberhasilan penyimpanan, bukan kehilangan pekerjaan.
- Worker melakukan dispatch/recovery berkala. Lock file Task membedakan workhorse yang masih hidup dari yang sudah mati. Task aktif yang kehilangan worker/Redis mendapat ID eksekusi RQ baru dan memakai ulang checkpoint. File lock dan SQLite diasumsikan berada pada satu mesin/volume bersama; ini bukan arsitektur multi-host.
- Transkripsi menyimpan chunk yang sudah selesai dengan checksum dan profil sumber/model/bahasa/glosarium. Perubahan profil memisahkan checkpoint; transkrip proyek yang sudah selesai tetap stabil agar output lama tidak berganti ID diam-diam.
- API menyediakan finalisasi ulang upload yang sudah penuh tetapi flag SQLite belum tersimpan saat crash.

## Kompatibilitas transkripsi dan yt-dlp

Uji nyata menemukan `faster-whisper==1.2.1` tidak kompatibel dengan PyAV 19 (`metadata_errors` dihapus). Extra transkripsi membatasi `av<19`; lockfile memilih 18.1.0. Memakai rilis kompatibel menghindari patch lokal atau mengambil kode library yang belum dirilis. Bukti upstream: [faster-whisper #1589](https://github.com/SYSTRAN/faster-whisper/issues/1589).

Linux memakai faster-whisper dengan VAD bawaan dan timestamp kata. MLX dipilih otomatis hanya pada macOS arm64; jalurnya memakai WebRTC VAD. Pilihan bahasa dan 40 istilah glosarium diteruskan ke decoder. MLX belum diuji pada perangkat Apple dalam sesi ini.

yt-dlp tetap memiliki versi baseline dalam `uv.lock` dan menyertakan extra `default` untuk EJS. Node tersedia pada image Python. Pembaruan harian mengunduh rilis stable ke direktori terisolasi, memvalidasi entry point, lalu mengganti pointer aktif secara atomik. Kegagalan update tidak mengganti versi kerja. Pemeriksaan update berjalan terpisah dari loop recovery, sehingga jaringan pembaruan tidak menunda pengiriman ulang job.

## Verifikasi dan batas klaim

Tes backend memakai database terisolasi, transport HTTP provider palsu, dan FFmpeg sungguhan. E2E browser menjalankan Redis, RQ, API, Next.js, dan render, memakai mock LLM dan video sintetis. Tes provider memverifikasi payload, schema, retry, repair, parsing, dan penyamaran error; tidak membuktikan key, kuota, atau kualitas model cloud milik pengguna.

Evaluator Klip menerima anotasi `expected.json` dan prediksi pipeline, menghitung recall/precision IoU ≥0,5 dengan pencocokan satu-ke-satu, serta membandingkan pilihan sebelum/sesudah rerank. Ia dapat menjalankan seleksi langsung pada sumber dan transkrip tersimpan. Mock dan fixture sintetis tidak masuk agregat kualitas; golden set manusia belum tersedia. Detail pada [kontrak evaluasi](../eval/golden/README.md).

Belum ada pengukuran performa video 1–3 jam, kualitas golden set manusia/provider nyata, akurasi sinkron ucapan manual, vision Ringkas, atau hasil produksi sesuai seluruh PRD. Pelacakan/retensi dan QC file akhir Klip sudah diuji pada Fase 3. `chapters.txt` adalah indeks edit dasar; belum menjamin batas minimal bab YouTube pada demo pendek.

Pekerjaan mengikuti rencana per fase pada `cuplik-claude-code-build.md` di root. Setelah renderer dan riset platform, kontrol Fase 4 dilaksanakan; checkpoint sekarang [review Fase 4](phase-4-review.md). Berhenti sebelum Fase 5. Gate kualitas/performa MVP yang belum terukur dicatat terbuka. Penerapan desain tetap ditunda.

PySceneDetect dipasang sebagai `scenedetect-headless` 0.7.3 dengan OpenCV headless, agar worker/server tidak membutuhkan pustaka GUI. NumPy dipakai untuk fitur per detik dan Jinja2 untuk template produksi. Pilihan mengikuti [paket resmi](https://www.scenedetect.com/download/); versi terkunci di `uv.lock`, dan uji nyata memverifikasi `ContentDetector` serta runtime Docker.

Layer dependensi Docker dipisahkan dari kode aplikasi dan memakai cache uv BuildKit. OpenCV/NumPy tidak perlu diunduh ulang pada perubahan source biasa. Smoke image produksi menggunakan empat layanan dengan volume tes terisolasi; migrasi data lama diuji pada salinan volume yang dipasang read-only.

Review hasil Fase 2 menemukan crop tengah dan caption satu kalimat menutupi rekaman layar. Renderer Klip kini menggunakan `framing.py` (YuNet lokal dan petunjuk teks/tepi) serta `captions.py` (frasa singkat, waktu kata, font yang diukur Pillow). Orientasi mengikuti konteks sumber, crop pembicara hanya dipilih pada deteksi yang stabil, dan text band menjaga gambar sumber tetap terlihat. Model YuNet 2026may mendukung bentuk input dinamis OpenCV 5, disertakan bersama hash/commit/lisensi untuk runtime offline. Fingerprint v2 menandai hasil lama agar dapat dirender ulang dari rencana tersimpan, tanpa memanggil LLM/ASR. `Clip.layout` dipakai kembali tanpa migrasi. Koreksi tersebut menjadi dasar pelacakan setiap frame dan QC file akhir pada Fase 3 di bawah.

Fase 3 menambahkan pipeline frame Python (`framepipe.py`/`reframe.py`), EDL (`retention.py`), audio dua lintasan (`audio.py`) serta QC MP4 akhir (`qc.py`). YuNet diperiksa setiap tiga frame pada 640 px; pose yang tidak dapat dilacak kembali ke konteks utuh dengan latar blur. Peta EDL memasukkan overlap audio 10 ms, sehingga caption/karaoke dan video memakai garis waktu yang sama. Jeda disimpan 130 ms sebelum overlap agar keluaran 120 ms. Headroom −1,5 dBTP pada normalisasi menjaga AAC di bawah batas akhir −1 dBTP, dan hasil akhirnya tetap diukur. Safe area memakai pita terpisah/ukuran kecil yang disetujui pengguna. Foto gerakan sintetis menguji jalur neural dan fallback; tiga klip Indonesia asli menguji render/audio/caption. Rincian, benchmark kecil dan batas klaim tersedia di checkpoint Fase 3.

Fingerprint renderer v3 mencakup retensi, keyword/emoji dan cold open/emphasis. `Clip.retention`/`thumb_path` yang sudah ada dipakai kembali tanpa migrasi. Thumbnail dipilih berdasarkan ketajaman pada 30% awal, dan masuk ZIP beserta kemasan posting. Gagal QC berbeda dari gagal encoding: MP4 gagal QC tetap dapat ditinjau; proses yang gagal tetap memakai retry/outbox yang sudah ada.

## Kontrol Fase 4

Migrasi `c841b29d1104` menambah tujuan/platform pada Clip. Data lama menjadi `discovery/youtube` dengan retensi lama tetap utuh. Output baru memakai profil tutorial konservatif: pemendekan jeda, pengisi, zoom dan emphasis mati; cold open tetap opsional mati. Tujuan dan platform diteruskan ke prompt. Tutorial YouTube otomatis mempertahankan bingkai sumber; target Shorts/TikTok/Reels memaksakan kanvas 9:16 tepat dengan dimensi genap. QC memakai dimensi dan durasi file akhir; keterbacaan seluruh desktop pada kanvas vertikal belum dapat diselesaikan tanpa pemilihan area visual lanjutan.

`Preference.defaults` menyimpan pengaturan per mode; preset caption memakai kolom yang sudah ada. Schema input output menunda pemeriksaan kombinasi sampai default tersimpan digabung dengan field request eksplisit, termasuk penggabungan retensi per field. Preferensi hanya memengaruhi output baru. Pilihan/catatan suka tidak mengubah fingerprint video; maksimal tiga contoh dengan tujuan serupa dipakai berikutnya.

`caption_overrides` mendukung ID kata dan kalimat lama. Kata yang dikoreksi mempertahankan timestamp; retensi juga membaca teks koreksi sehingga kata yang sudah diperbaiki tidak dianggap filler lama. Trim manual memakai batas kata terdekat atau kalimat bila waktu kata tidak ada, memvalidasi durasi sumber serta rentang 1–180 detik. Koreksi kalimat dengan pemetaan pasti dipindahkan ke ID kata sebelum trim; pemetaan ambigu ditolak atomik. Batas edit diberi penanda agar skor awal tidak disajikan seolah sudah dinilai ulang. Fingerprint v4 mencakup pengaturan baru; render satu klip tidak memanggil LLM/ASR ulang.

Lease `.source.lock` mencakup ingest dan keseluruhan render output. Penanda `.source-used` terpisah dari mtime media agar cache render tetap berlaku. Cleanup tiap jam hanya menghapus salinan `source.mp4` yang tak dipakai >`SOURCE_CACHE_DAYS` (default 14), dengan pemeriksaan task aktif dan ketersediaan unggahan asli. Audio/transkrip/hasil/unggahan asli tetap ada. Pemulihan sumber URL dapat mengunduh ulang; validasi checksum menentukan apakah transkrip masih cocok. Keterbatasan disk keseluruhan dan pengukuran MVP lengkap tetap dicatat pada checkpoint.

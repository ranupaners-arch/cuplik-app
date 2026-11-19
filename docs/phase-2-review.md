# Checkpoint Fase 2 — pemilihan Klip

Tindak lanjut review: caption dan pembingkaian telah diperbaiki dalam [catatan render adaptif](adaptive-render-review.md). Catatan di bawah merekam kondisi saat checkpoint Fase 2; contoh baru tersedia pada tindak lanjut tersebut.

Tanggal: 19 November 2026. Implementasi dan verifikasi teknis Fase 2 selesai. Penerapan desain tetap ditunda. Evaluasi kualitas editorial pada 10 video manusia dan provider nyata masih menunggu dataset; statusnya tidak disamakan dengan kelulusan tes teknik.

## Perubahan yang dapat diperiksa

- Pipeline Klip sekarang `ingest → signals → moments → scoring → rerank → render`. Ringkas dan sample API LLM mempertahankan kontrak fondasi.
- Prompt `moment_finder`, `scorer`, dan `reranker` berasal dari library asli `03-prompts/cuplik-prompts.md`, disalin ke pasangan `.system.txt`/`.user.txt`. Template Jinja2 mengisi variabel dengan escaping pada data tak tepercaya. Instruksi asli dan dokumen desain tetap utuh.
- Pencarian memakai jendela 8 menit dengan overlap sepanjang maksimum klip, ID kalimat tervalidasi, konteks sebelum/sesudah klip, fokus pengguna, dan maksimal tiga contoh dari output terbaru yang diberi suka.
- Penilaian per enam kandidat. Python menghitung bobot rubrik `0.30 H + 0.25 S + 0.20 P + 0.15 E + 0.10 C`, menambah koreksi IQ yang dibatasi ±0,5, lalu membulatkan sekali ke satu desimal. Skor tampilan tetap skor dasar; peringkat mengikuti reranker.
- Reranker menerima maksimal 20 finalis. ID asing/duplikat diabaikan dan dicatat; ID hilang ditambahkan menurut skor dasar. Pembatas akhir: maksimal dua klip per label topik yang dinormalisasi dan overlap IoU tidak lebih dari 0,3. Jumlah hasil dapat kurang dari permintaan.
- Trim dibatasi ID kalimat kandidat. Awal/akhir memakai timestamp kata, pengisi awal hanya dibuang jika diikuti jeda ≥250 ms, padding 120/250 ms tidak memasuki kata tetangga, batas durasi akhir keras 180 detik. Klip ditolak jika memenuhi durasi akan memotong ujaran. Caption kalimat mengikuti kata yang masih berada dalam klip; renderer tetap dasar.
- Sidecar lama tanpa kata tetap diterima dengan `boundary_precision: sentence_only`; ketepatan kata tidak diklaim. Sidecar yang mencampur data kata dengan kalimat tanpa referensi `word_ids` ditolak pada seleksi, agar ujaran tidak hilang diam-diam.
- Judul dua opsi maksimal 60 karakter; hook dua opsi maksimal delapan kata. Keyword/emoji yang tidak terdapat dalam teks dan emphasis ID yang tidak berada dalam klip dihapus dan dicatat. Cold open serta emphasis disimpan sebagai metadata untuk fase render berikutnya.
- `selection.json` mencatat kandidat, penolakan, peringatan, urutan sebelum/sesudah, pergeseran peringkat, perubahan pilihan, keragaman topik dan skor rata-rata. JSON prompt tervalidasi memiliki checkpoint berdasarkan input, template, schema, model, dan provider. Kesalahan JSON setelah satu repair melewati window/batch; gangguan koneksi atau konfigurasi tetap membuat pekerjaan gagal dan dapat dicoba ulang.
- Migrasi `a937e1c42f60` menambah JSON audit `Clip.selection` dengan default `{}`. Data hasil lama dan referensi MP4 dipertahankan. Transkrip yang sudah selesai tetap dapat dibaca saat output berikutnya memeriksa cache; ini memperbaiki race HTTP 409 yang ditemukan tes browser.

## Moment IQ dan dependensi

`signals.json` berisi satu sampel per detik: RMS energi dan laju kata dengan z-score, proporsi hening berdasarkan RMS blok 20 ms <−40 dBFS, pemicu kata Indonesia/Inggris, serta cut dari PySceneDetect `ContentDetector(27)`. Semua frame diperiksa dengan downscale otomatis. Campuran `0.35 energi + 0.25 laju + 0.20 pemicu + 0.10 cut − 0.10 hening` dihaluskan lima detik, lalu dinormalisasi 0–1. Sinyal konstan menghasilkan IQ nol tanpa NaN. Waktu kata pemicu di dalam kalimat merupakan perkiraan; sinyal ini hanya petunjuk pemilihan.

Cache sinyal mempertimbangkan sumber, audio, transkrip, daftar pemicu, dan versi algoritme. Sidecar tanpa waktu kata menandai laju bicara sebagai `sentence_estimate`.

Dependensi terkunci: **PySceneDetect headless 0.7.3**, OpenCV headless 5.1.0.95, NumPy 2.x, Jinja2 3.1.6. Varian headless dipilih untuk worker/server tanpa dependensi GUI; API `.seconds` mengikuti rilis tersebut. Referensi primer: [instalasi headless](https://www.scenedetect.com/download/) dan [SceneManager](https://www.scenedetect.com/docs/latest/api/scene_manager.html). Framework utama tetap Next.js 16/Python 3.12 karena tidak ada alasan kompatibilitas untuk menggantinya pada fase ini.

## Verifikasi

- `make test`: **53 tes backend lolos**, termasuk rumus IQ tanpa pembulatan ganda, cut adegan nyata, cache, overlap window 180 detik, trim/batas kata, batch enam, finalis maksimal 20, fallback rank, keragaman, perbaikan JSON, evaluator dan migrasi berisi klip lama.
- `make e2e`: **2 tes browser lolos**, mencakup kedua mode, skor/audit/sinyal, SSE, edit caption, unduhan, unggahan dan glosarium.
- `make lint`, `make build`, regenerasi OpenAPI/tipe frontend, dan `alembic check`: lolos.
- `make eval`: kualitas `not_run`, nol video manusia. `make eval-fixtures`: mekanisme evaluator berhasil; tetap tidak dihitung sebagai kualitas.
- Build tiga image Docker dan smoke empat layanan produksi lolos: web Next.js/proxy, API, Redis/RQ, pemilihan, sinyal dan unduhan MP4. Runtime headless berjalan sebagai UID 1000. Salinan database volume Fase 1 dimigrasikan tanpa mengubah jumlah **2 proyek, 3 output, 2 klip**, dan foreign key valid. Volume sumber hanya dibaca; volume tes dibuang setelah pengujian.

Pengujian memakai provider mock/transport palsu; tidak ada panggilan provider LLM berbayar.

Uji media nyata menggunakan video Indonesia 75 detik yang sama dengan Fase 1, beserta transkrip Whisper base sebelumnya (130 kata). Sumber dan atribusi CC BY-SA tersedia di `data/phase1-validation/attribution.json` dan [checkpoint Fase 1](phase-1-review.md). Harness menjalankan API, Redis, RQ, pemilihan, SSE, render FFmpeg, unduhan, rating, dan output berikutnya. Hasil tersimpan di:

- [Laporan integrasi](../data/phase2-validation/report.json)
- [Audit pemilihan](../data/phase2-validation/selection.json)
- [Data Moment IQ](../data/phase2-validation/signals.json)
- [Klip pertama](../data/phase2-validation/clip-1.mp4)
- [Runtime Docker dan migrasi data lama](../data/phase2-validation/docker-runtime.json)
- [Workflow Docker produksi](../data/phase2-validation/docker-workflow.json)

Tiga klip dihasilkan, tidak ada batas yang berada di dalam timestamp kata, maksimal dua klip per topik, sinyal dipakai ulang dan rating masuk output berikutnya. Reranker mock tidak mengubah urutan; hasil ini tidak menunjukkan peningkatan kualitas editorial. Kebenaran waktu terhadap ucapan dan WER belum dianotasi manual.

## Cara mencoba

```sh
make install
make dev
```

Buka `http://localhost:3000`. Pilih demo atau unggah dengan transkrip bertimestamp, atur jumlah/rentang durasi, proses Klip. Buka **Rincian skor** serta tautan **Data Moment IQ** dan **Laporan pemilihan dan keragaman** pada hasil. Beri suka, lalu buat output lain dari proyek yang sama untuk memeriksa pemakaian contoh. Data output lama tidak berubah secara otomatis.

Endpoint tambahan:

```text
GET /api/projects/{id}/signals
GET /api/outputs/{id}/selection
```

Keduanya mengembalikan 409 bila artefak belum tersedia. Skema/tipenya tersedia dalam OpenAPI dan tipe frontend yang sudah diperbarui.

Ulangi pemeriksaan media tanpa memanggil LLM nyata:

```sh
uv run python scripts/validate_selection.py \
  --video data/phase1-validation/indonesian-75s.mp4 \
  --transcript data/phase1-validation/validated-transcript.json
```

Evaluasi: `make eval` untuk anotasi manusia, `make eval-fixtures` untuk mekanisme sintetis. Format input, prediksi dan `--run` dijelaskan dalam [kontrak evaluasi](../eval/golden/README.md).

## Batas checkpoint

Belum ada golden set 10 video yang dianotasi manusia dan belum ada penilaian kualitas Gemini/Anthropic/Ollama nyata. Evaluator sudah dapat menjalankannya, tetapi `quality_status` tetap `not_run` pada data yang tersedia. Belum ada benchmark video 1–3 jam atau klaim korelasi Moment IQ dengan retensi penonton. Pelacakan wajah, karaoke, cold open yang benar-benar dirender, normalisasi loudness, serta QC produksi tetap Fase 3. Berhenti di checkpoint ini untuk pemeriksaan pengguna.

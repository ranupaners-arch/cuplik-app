# Evaluasi Klip dan Ringkas

Target dataset: **10 sumber Klip dan 5 sumber Ringkas unik**, ditinjau manusia sebelum melihat prediksi, dengan provider nyata. Dataset tersebut belum tersedia. `make eval` melaporkan `quality_status: not_run` dan skor `null` ketika belum ada kasus yang memenuhi syarat; keberhasilan perintah tidak berarti target kualitas tercapai.

## Membuat anotasi melalui aplikasi

1. Pada Buat pilih **Siapkan sumber untuk anotasi**. Unggah video/sidecar atau gunakan sumber YouTube. Mode ini menyiapkan ingest/transkrip tanpa pemilihan LLM.
2. Setelah transkrip selesai, buka `/projects/<id>/evaluate`. Putar sumber asli dengan caption transkrip yang tetap perlu diperiksa.
3. Label Klip berisi rentang momen. Label Ringkas berisi rentang bab wajib dan spesifikasi penting (angka, nama alat, ukuran, kondisi). Timestamp memakai detik **sumber**, bukan waktu MP4 hasil.
4. Simpan draft; untuk menyelesaikan isi nama peninjau, rentang/label dan konfirmasi sudah menonton. Perubahan dari tab lama ditolak tanpa menimpa revisi baru. Sumber/transkrip yang berubah memerlukan tinjauan ulang.
5. Sesudah label disimpan, buat output LLM dari halaman proyek. Kembali ke anotasi, muat ulang, lalu pilih prediksi pembanding selesai. Ekspor ZIP.
6. Ekstrak menjadi `eval/golden/<nama-kasus>/`. Unduh sumber dari halaman anotasi dan simpan sebagai `source.mp4` di folder yang sama. ZIP menyertakan label, transkrip, metadata anotasi dan prediksi opsional; media tidak digandakan ke ZIP.

Label yang diubah setelah prediksi sudah tersimpan menjadi **assisted** dan dikeluarkan dari agregat independen. Menyimpan ulang label identik tidak mengubah status tinjauan awal. Ini aturan konservatif untuk mengurangi kebocoran label, bukan bukti otomatis perilaku peninjau.

Output baru membawa checksum sumber/transkrip. Paket dengan prediksi harus memakai jejak input yang sama; hasil legacy tanpa provenance perlu dibuat ulang sebagai output baru. Sumber yang dihapus oleh TTL dapat disiapkan ulang dari halaman anotasi tanpa mengubah anotasi lokal. Perubahan isi sumber ditandai sebagai stale.

## Format dan metrik

Satu folder per kasus. Path `./...` relatif terhadap folder kasus, path biasa relatif terhadap root repository, dan path absolut diterima. Media serta data pribadi tetap di direktori yang diabaikan Git.

Contoh `expected.json` Klip (format lama tanpa provenance tetap terbaca):

```json
{
  "mode": "clips",
  "dataset_kind": "human",
  "annotator": "nama peninjau",
  "annotation_status": "reviewed",
  "independent": true,
  "source": "./source.mp4",
  "transcript": "./transcript.json",
  "settings": {"clip_count": 8, "min_clip_seconds": 15, "max_clip_seconds": 60},
  "ranges": [{"start_s": 10, "end_s": 40, "topic": "catatan transaksi"}]
}
```

Recall/precision Klip memakai **IoU ≥0,5**, pencocokan satu-ke-satu, jumlah topik dan perbandingan sebelum/sesudah rerank jika baseline tersedia. Pemeriksaan batas kata membutuhkan transkrip per kata; transkrip per kalimat ditandai tidak tersedia untuk pemeriksaan ini. Baseline pipeline menggunakan kandidat, batas overlap dan batas topik yang sama.

Contoh Ringkas pada `expected.json`:

```json
{
  "mode": "condense",
  "dataset_kind": "human",
  "annotator": "nama peninjau",
  "annotation_status": "reviewed",
  "independent": true,
  "source": "./source.mp4",
  "transcript": "./transcript.json",
  "settings": {"target_seconds": 120},
  "required_chapters": [{"start_s": 10, "end_s": 30, "topic": "pasang alat"}],
  "required_specs": [{"start_s": 22, "end_s": 25, "topic": "ukuran baut"}]
}
```

Ringkas memakai gabungan interval `retained_ranges` hasil garis waktu render, bukan hanya rencana solver. Bab dihitung cocok jika cakupannya **≥90%**, spesifikasi **≥99%**. Interval tumpang tindih digabung, sehingga mengulang satu segmen tidak menaikkan recall. Deviasi durasi memakai MP4 akhir dan target, dengan toleransi **±3%**. Ini metrik retensi waktu; belum menilai kebenaran/koherensi visual, ASR atau kecukupan isi secara semantik.

Prediksi Klip menerima audit pipeline atau objek dengan `provider`, `clips` berisi `start_s/end_s`, dan `baseline_clips` opsional. Ringkas memerlukan `mode: condense`, `provider`, `duration_s` dan `retained_ranges` berisi `start_s/end_s`. Paket aplikasi menambahkan `provenance` otomatis; jangan mengubah checksum untuk memaksa kecocokan. Untuk Klip, audit menilai seleksi AI sebelum trim manual, bukan kualitas edit pengguna atau retensi renderer.

## Menjalankan evaluator

```sh
make eval
make eval-fixtures
# Klip saja: jalankan seleksi pada transkrip tersedia, tanpa ASR/render.
uv run python eval/evaluate.py --run --output data/eval/report.json
```

`--run` memakai provider konfigurasi (default mock); cache sinyal/prompt di `data/eval/`. Untuk Ringkas gunakan paket prediksi hasil render. `--predictions-root /path/hasil` membaca `<hasil>/<nama-kasus>/predictions.json`; `--require-predictions` menghasilkan exit code 1 bila prediksi hilang. Input/provenance/rentang tidak valid juga gagal.

Draft tidak dinilai. Sumber tanpa berkas untuk verifikasi, peninjau kosong, assisted, demo/fixture sintetis dan provider selain Gemini/Anthropic/Ollama dikeluarkan dari agregat kualitas. Dataset manual di luar aplikasi harus menyatakan metadata secara jujur; nama provider di JSON bukan bukti panggilan model. Jumlah video memakai checksum sumber unik agar salinan kasus tidak memenuhi target 10/5 secara palsu. Fixture/test otomatis hanya menguji mekanisme dan tidak mengisi golden set manusia.

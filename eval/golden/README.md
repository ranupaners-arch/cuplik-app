# Evaluasi Klip Cuplik

Evaluator Fase 2 menghitung recall/precision pada **IoU ≥0,5** dengan pencocokan satu-ke-satu. Satu prediksi tidak dapat memenuhi beberapa anotasi. Laporan membandingkan pilihan berdasarkan skor dasar dengan pilihan setelah rerank, menghitung jumlah topik, dan memeriksa batas kata jika transkrip per kata tersedia.

Target kualitas tetap **10 video Klip beranotasi manusia**. Video dan anotasi pengguna belum tersedia. `make eval` akan mengembalikan `quality_status: not_run` serta skor `null` sampai tersedia data dan prediksi provider nyata. Keberhasilan perintah bukan berarti target kualitas tercapai. Fixture sintetis dan prediksi mock tidak masuk agregat kualitas.

Simpan satu folder per video di `eval/golden/`, misalnya `video-01/expected.json`:

```json
{
  "mode": "clips",
  "dataset_kind": "human",
  "annotator": "nama peninjau",
  "source": "data/golden/video-01.mp4",
  "transcript": "data/golden/video-01-transcript.json",
  "settings": {"clip_count": 8, "min_clip_seconds": 15, "max_clip_seconds": 60},
  "ranges": [{"start_s": 10, "end_s": 40}],
  "note": "Anotasi momen yang berdiri sendiri dan memiliki payoff; dibuat sebelum melihat prediksi."
}
```

`transcript` diperlukan untuk menjalankan pipeline dan memeriksa kata; opsional untuk menilai prediksi yang sudah disimpan. Timestamp anotasi manual berupa detik sumber. Media tetap di `data/` yang diabaikan Git. Path biasa relatif ke root repository, path `./...` relatif ke folder kasus, dan path absolut juga diterima.

Dua cara evaluasi:

```sh
# 1. Nilai prediksi yang sudah tersimpan di tiap folder kasus.
make eval

# 2. Jalankan pemilihan menggunakan sumber, transkrip, dan provider dari .env.
# Default konfigurasi adalah mock; tidak ada ASR atau render di evaluator.
uv run python eval/evaluate.py --run --output data/eval/report.json
```

`--run` membuat cache audio/sinyal/prompt di `data/eval/`. Ia menggunakan transkrip yang disediakan, sehingga pengukuran ini mengevaluasi seleksi, bukan WER transkripsi. Kesalahan sumber/model/config menjadi error, bukan prediksi kosong yang dianggap sah.

Untuk cara pertama, salin laporan `GET /api/outputs/{id}/selection` menjadi `predictions.json` di folder kasus. Evaluator langsung menerima struktur laporan pipeline. Prediksi dari sistem lain juga dapat memakai:

```json
{
  "provider": "ollama",
  "clips": [{"start_s": 10, "end_s": 40, "topic": "catatan transaksi"}],
  "baseline_clips": [{"start_s": 15, "end_s": 45, "topic": "catatan transaksi"}]
}
```

`baseline_clips` opsional; baseline pipeline menggunakan kandidat yang sama, urutan skor dasar, serta batas topik/overlap yang sama agar perbandingan rerank adil. `--predictions-root /path/hasil` membaca `<hasil>/<nama-kasus>/predictions.json`. `--require-predictions` mengembalikan exit code 1 bila prediksi hilang. JSON/rentang tidak valid juga gagal.

```sh
make eval-fixtures
```

Perintah ini menguji mekanisme evaluator terhadap fixture sintetis tetap di `eval/fixtures/`. Contoh perubahan recall di fixture **bukan bukti peningkatan kualitas reranker**. Tes backend juga menjalankan evaluator pada video sintetis melalui pipeline yang sesungguhnya.

Mode Ringkas, target 5 tutorial, `required_chapters`, `required_specs`, dan deviasi durasi ditangani pada Fase 5. Anotasi `mode: condense` saat ini dilaporkan sebagai `deferred_phase_5`.

# AttentionCurve
Grafik area skor perhatian per detik (Moment IQ) untuk seluruh video, dengan rentang klip terpilih ditandai.

- Sumbu Y = skor gabungan 0–1 (hook, energi suara, emosi, kepadatan kata), dihaluskan jendela 5 detik.
- Rentang klip: blok `brand` 22% + tepi 2px + label peringkat. Klik rentang = buka klip; seret tepi = ubah batas.
- Playhead `ink` 1.5px mengikuti pemutar.
- Konsumen menyediakan: `series: number[]` (1 nilai/detik), `clips: {rank,start,end}[]`, `duration`.

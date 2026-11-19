# ScoreBadge
Menampilkan skor viral 0–10 hasil LLM dengan satu desimal dan tiga tingkat warna.

- ≥ 8.0 → `score-high` + ikon api; 5.0–7.9 → `score-mid` + ikon api; < 5.0 → `score-low` tanpa ikon.
- Tingkat dibedakan juga oleh isian (solid vs outline), tidak hanya hue.
- Tooltip menampilkan rincian: hook, emosi, payoff, kemandirian konteks (lihat PRD bagian skor).
- Konsumen menyediakan: `score: number`, `breakdown?: {hook, emotion, payoff, standalone, pacing}`.

# EditTimeline
Peta keputusan solver mode Ringkas: satu baris per bab, satu blok per beat dengan warna normal, dipercepat, atau dibuang.

- Lebar blok sebanding dengan durasi asli beat; durasi hasil per bab di kanan (`timecode`).
- Normal = `score-high`, dipercepat = `brand` bergaris (pola, bukan warna saja), dibuang = `surface-raised` + `line`.
- Beat wajib bertitik `ink` di atas blok dan tidak bisa diubah ke "dibuang".
- Klik blok memutar normal → percepat → buang dan mengunci keputusan (cincin `focus`); solver menghormati beat terkunci.
- Header menampilkan durasi asli → hasil dan target; hasil di luar ±3% berwarna `cut`.
- Konsumen menyediakan: `chapters[{title, kept_s, beats[{id, dur_s, decision, speed, required, locked}]}]`, `targetS`, `onToggle(beatId)`.

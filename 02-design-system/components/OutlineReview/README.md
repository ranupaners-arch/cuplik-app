# OutlineReview
Halaman tinjau bab mode Ringkas: kamu menentukan bab mana yang wajib sebelum solver memotong apa pun.

- Satu baris per bab: centang wajib (`brand`), judul, tujuan/spesifikasi singkat (`ink-muted`), label `inti`/`membantu`/`opsional`, durasi asli (`timecode`).
- Bab `inti` tercentang otomatis; semua bisa diubah.
- Di bawah daftar: durasi minimum bab wajib dibanding target. Bila melebihi target, kalimat berwarna `cut` dan tombol berubah menjadi "Pakai durasi minimum".
- Satu tombol utama: **Lanjutkan ringkas** → `PUT /api/outputs/{id}/outline`.
- Konsumen menyediakan: `chapters[{id, title, goal, importance, duration_s, required}]`, `targetS`, `minRequiredS`, `onChange`, `onSubmit`.

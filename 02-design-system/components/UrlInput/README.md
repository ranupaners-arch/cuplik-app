# UrlInput
Kolom hero untuk menempel link (YouTube, TikTok, IG, X, Twitch, Drive) atau mengunggah file, plus ringkasan pengaturan cepat.

- Setelah link valid, panggil `/api/probe` → tampilkan durasi, bahasa terdeteksi, perkiraan waktu proses.
- Chip di bawah = pengaturan cepat (format, panjang, caption, hook); pengaturan lengkap ada di panel.
- Satu tombol utama `brand`: **Buat klip**. Enter juga mengirim.
- Error (link privat, playlist, live berjalan) tampil di bawah kolom dengan warna `cut` dan solusi satu kalimat.

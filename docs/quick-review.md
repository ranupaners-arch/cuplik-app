# Tinjauan singkat hasil klip

Gunakan satu hasil yang sudah selesai untuk meninjau kontrol Fase 4. Simpan catatan sebelum memulai render atau analisis baru.

## Persiapan

Jalankan `make help` untuk melihat perintah dan `make doctor` untuk memeriksa setup native. Doctor memeriksa executable, versi Python/Node, metadata dependensi dasar, serta dukungan FFmpeg. Pemeriksaan ini tidak membaca API key, menjalankan server, mengunduh model, atau mengolah video. Ia tidak menggantikan tes aplikasi.

Jika aplikasi belum berjalan, gunakan `make dev` setelah dependensi terpasang. Buka **Riwayat**, pilih proyek, lalu buka output Klip berstatus **done**. Proyek demo berisi pola gambar dan nada uji; gunakan rekaman percakapan untuk menilai kualitas subtitle terhadap ucapan.

Jika port default sudah digunakan, supervisor mendukung port lain:

```sh
uv run python scripts/dev.py --web-port 3001 --api-port 8001 --redis-port 6387
```

Buka `http://localhost:3001`. Pilih port yang tersedia; supervisor menolak port yang sedang dipakai.

## Pemeriksaan sekitar lima menit

| Bagian | Yang diperiksa | Catatan yang berguna |
| --- | --- | --- |
| Makna | Apakah pembuka, penjelasan, dan hasil dapat dipahami? | Tuliskan konteks atau langkah yang hilang beserta waktunya. |
| Gambar | Apakah wajah, tangan, objek, menu, atau nilai penting terlihat? | Sebutkan bagian yang terpotong atau terlalu kecil. |
| Caption | Apakah ucapan akurat, frasanya terbaca, dan detail video tetap terlihat? | Catat kata salah dan waktu munculnya. |
| Ritme | Apakah jeda demonstrasi cukup dan potongan terasa utuh? | Catat gerakan atau penjelasan yang terasa terburu-buru. |
| Audio | Apakah suara jelas dan volumenya nyaman? | Catat bagian terlalu pelan, keras, atau berubah mendadak. |
| Keluaran | Apakah platform tujuan dan bentuk video sesuai kebutuhan? | Catat bila format benar tetapi detail tetap sulit dibaca. |

Putar di ukuran pemakaian sebenarnya, termasuk di ponsel bila sasarannya video vertikal. Buka **Pemeriksaan kualitas video** untuk melihat hasil pemeriksaan file. QC lolos belum membuktikan langkah tutorial lengkap atau subtitle tepat terhadap ucapan.

## Pilihan yang sudah tersedia

| Keperluan | Pengaturan Cuplik |
| --- | --- |
| Menjaga konteks tutorial layar lebar | Tujuan **Tutorial**, platform **Video YouTube / rasio sumber**, pembingkaian **Otomatis** atau **Bingkai sumber utuh** |
| Membuat versi untuk Shorts/TikTok/Reels | Pilih platform tujuan; keluaran memakai kanvas 9:16. Tinjau ulang keterbacaan detail. |
| Menjaga waktu demonstrasi | Profil **Tutorial** mematikan pemendekan jeda secara bawaan. Teknik dapat disunting per klip. |
| Mengoreksi teks tanpa menggeser ucapan | Edit kata pada **Edit judul, hook, dan caption**. Tanpa timestamp kata, editor memakai kalimat dengan waktu perkiraan. |
| Memperbaiki batas potongan | Ubah awal/akhir; penyimpanan melakukan snap ke batas kata atau kalimat. |
| Memakai koreksi pada sumber berikutnya | Simpan pasangan kata ke glosarium. Berlaku pada transkripsi proyek baru. |

Perubahan gambar/caption diterapkan setelah **Simpan dan render ulang klip**. Untuk tinjauan ringan, catatan dan rating dapat disimpan terlebih dahulu; mengubah rating tidak memerlukan render ulang.

Seluruh desktop pada kanvas vertikal masih bisa tampak kecil. Fokus otomatis ke area layar/tangan/objek belum tersedia pada fase kontrol ini. Pilihan rasio sumber menjaga konteks sambil menunggu pekerjaan vision berikutnya.

## Format catatan

Salin dan isi untuk satu klip. Gunakan **belum diperiksa** jika belum ditinjau; jangan menyamakan status QC dengan penilaian manusia.

```text
Proyek / output / nomor klip:
Tujuan dan platform:
Perangkat untuk menonton:
Makna dan langkah: baik / perlu perbaikan / belum diperiksa
Gambar dan detail: baik / perlu perbaikan / belum diperiksa
Caption dan audio: baik / perlu perbaikan / belum diperiksa
Waktu masalah:
Yang perlu dipertahankan:
Perubahan berikutnya:
```

Ringkas temuannya pada **Catatan penilaian**, lalu beri **Suka** atau **Tidak suka**. Maksimal tiga contoh suka dengan tujuan serupa menjadi masukan pemilihan berikutnya. Skor editorial dan rating tersebut belum mengukur traffic publikasi.

Hasil teknis dan batas MVP saat ini: [checkpoint Fase 4](phase-4-review.md). Rencana pekerjaan: [rencana build](../cuplik-claude-code-build.md).

# CaptionStyle
Pemilih preset caption yang akan dibakar (burn-in) ke video lewat file ASS.

- Empat preset awal: **Karaoke** (kata aktif `caption-hl`), **Kotak** (kotak putih, kata aktif `brand`), **Santai + emoji** (huruf biasa, emoji 1/baris), **Satu kata** (gaya Hormozi, satu kata besar).
- Preset terpilih diberi border `brand` 2px.
- Pratinjau di sini hanya perkiraan; render asli memakai `burn-caption` 64px di kanvas 1080×1920.
- Konsumen menyediakan: `preset`, `onChange`, contoh teks.

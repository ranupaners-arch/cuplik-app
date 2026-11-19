# JobProgress
Daftar tahapan job pipeline dengan status selesai/berjalan/menunggu dan persen nyata dari worker.

- Status datang lewat SSE `/api/jobs/:id/events`; tahap berjalan menampilkan progress bar `brand`.
- Selesai = titik `score-high`; gagal = titik `cut` + pesan + tombol "Coba lagi dari tahap ini".
- Tab boleh ditutup; job tetap jalan (worker terpisah).

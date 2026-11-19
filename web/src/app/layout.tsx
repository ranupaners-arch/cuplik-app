import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = { title: "Cuplik — workflow dasar", description: "Pengujian alur proyek, LLM, dan render video Cuplik." };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="id"><body>
    <header><strong>Cuplik · workflow dasar</strong><nav aria-label="Navigasi utama"><Link href="/">Buat</Link><Link href="/history">Riwayat</Link><Link href="/preferences">Preferensi</Link><Link href="/llm">Uji LLM</Link><a href="/api/docs" target="_blank" rel="noreferrer">Dokumentasi API</a></nav></header>
    <main>{children}</main>
  </body></html>;
}

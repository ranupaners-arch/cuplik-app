"use client";

import { Badge, Container, Group, MantineProvider, Text } from "@mantine/core";
import Link from "next/link";
import { studioTheme } from "@/design/theme";
import { usePathname } from "next/navigation";



const links = [["/", "Buat"], ["/history", "Riwayat"], ["/preferences", "Preferensi"], ["/llm", "Uji LLM"]];

export function StudioProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return <MantineProvider theme={studioTheme} forceColorScheme="dark" cssVariablesResolver={() => ({ variables: {}, light: {}, dark: { "--mantine-color-body": "var(--bg)", "--mantine-color-text": "var(--ink)", "--mantine-color-dimmed": "var(--ink-muted)", "--mantine-color-default": "var(--surface-raised)", "--mantine-color-default-border": "var(--line)" } })}>
    <a className="skip-link" href="#main-content">Lewati ke konten</a>
    <header className="studio-header"><Container size="xl"><div className="header-content">
      <Link href="/" className="studio-brand" aria-label="Cuplik beranda"><svg width="32" height="32" viewBox="0 0 32 32" fill="none" aria-hidden="true"><path d="M10 4 25 26M10 28 25 6M16 16 25 16" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/><circle cx="8" cy="6" r="4" stroke="currentColor" strokeWidth="2"/><circle cx="8" cy="26" r="4" stroke="currentColor" strokeWidth="2"/></svg><span>cuplik<span className="brand-caption">STUDIO VIDEO</span></span></Link>
      <nav aria-label="Navigasi utama"><ul className="studio-nav">{links.map(([href, label]) => <li key={href}><Link href={href} aria-current={pathname === href ? "page" : undefined}>{label}</Link></li>)}</ul></nav>
      <Badge variant="outline" color="gray" className="studio-label">Ruang kreator</Badge>
    </div></Container></header>
    <Container size="xl" component="main" id="main-content" className="studio-main">{children}</Container>
    <Container size="xl" component="footer" className="studio-footer"><Group justify="space-between" gap="sm"><Text size="xs" c="dimmed">Cuplik · Ambil bagian terbaiknya.</Text><a href="/api/docs" target="_blank" rel="noreferrer">Dokumentasi API</a></Group></Container>
  </MantineProvider>;
}

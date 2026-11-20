"use client";

import { Badge, Button, Container, createTheme, Group, MantineProvider, Text } from "@mantine/core";
import Link from "next/link";
import { usePathname } from "next/navigation";

const theme = createTheme({
  primaryColor: "turmeric",
  colors: { turmeric: ["#fff7df", "#ffedbc", "#ffe08f", "#ffd061", "#f7c04c", "#f2b43a", "#dfa229", "#bd871e", "#966914", "#70500f"], dark: ["#f5efe2", "#ada391", "#8a8070", "#625846", "#3a3428", "#29251c", "#1e1b14", "#14120c", "#100e09", "#0b0906"] },
  primaryShade: 5,
  fontFamily: '"Plus Jakarta Sans Variable", system-ui, sans-serif',
  fontFamilyMonospace: '"JetBrains Mono Variable", ui-monospace, monospace',
  defaultRadius: "md",
  radius: { sm: "6px", md: "10px", lg: "16px", xl: "24px" },
  components: { Button: Button.extend({ defaultProps: { size: "md", variant: "default" }, classNames: { root: "studio-button", label: "studio-button-label" } }) },
});

const links = [["/", "Buat"], ["/history", "Riwayat"], ["/preferences", "Preferensi"], ["/llm", "Uji LLM"]];

export function StudioProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return <MantineProvider theme={theme} forceColorScheme="dark" cssVariablesResolver={() => ({ variables: {}, light: {}, dark: { "--mantine-color-body": "var(--bg)", "--mantine-color-text": "var(--ink)", "--mantine-color-dimmed": "var(--ink-muted)", "--mantine-color-default": "var(--surface-raised)", "--mantine-color-default-border": "var(--line)" } })}>
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

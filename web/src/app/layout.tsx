import type { Metadata } from "next";
import { ColorSchemeScript, mantineHtmlProps } from "@mantine/core";
import { StudioProvider } from "@/components/studio-provider";
import "@mantine/core/styles.css";
import "@fontsource-variable/plus-jakarta-sans";
import "@fontsource-variable/jetbrains-mono";
import "../../../02-design-system/tokens.css";
import "./globals.css";

export const metadata: Metadata = { title: "Cuplik — studio video", description: "Ubah video panjang menjadi klip dan tutorial ringkas yang tetap jelas." };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="id" {...mantineHtmlProps}><head><ColorSchemeScript forceColorScheme="dark" /></head><body><StudioProvider>{children}</StudioProvider></body></html>;
}

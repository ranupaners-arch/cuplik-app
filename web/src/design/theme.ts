import { Button, createTheme } from "@mantine/core";

export const studioTheme = createTheme({
  primaryColor: "turmeric",
  colors: { turmeric: ["#fff7df", "#ffedbc", "#ffe08f", "#ffd061", "#f7c04c", "#f2b43a", "#dfa229", "#bd871e", "#966914", "#70500f"], dark: ["#f5efe2", "#ada391", "#8a8070", "#625846", "#3a3428", "#29251c", "#1e1b14", "#14120c", "#100e09", "#0b0906"] },
  primaryShade: 5,
  fontFamily: '"Plus Jakarta Sans Variable", system-ui, sans-serif',
  fontFamilyMonospace: '"JetBrains Mono Variable", ui-monospace, monospace',
  defaultRadius: "md",
  radius: { sm: "6px", md: "10px", lg: "16px", xl: "24px" },
  components: { Button: Button.extend({ defaultProps: { size: "md", variant: "default" }, classNames: { root: "studio-button", label: "studio-button-label" } }) },
});

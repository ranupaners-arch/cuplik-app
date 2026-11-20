import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { fileURLToPath } from "node:url";
const root = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  root: root,
  base: "/assets/www/",
  plugins: [react()],
  build: { outDir: "../android/app/src/main/assets/www", emptyOutDir: true, target: "es2020", rollupOptions: { input: path.resolve(root, "mobile.html") } },
});

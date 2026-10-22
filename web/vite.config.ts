/// <reference types="vitest" />
import { defineConfig } from "vite";

// Static build: relative base so dist/ works from any folder or sub-path (GitHub Pages, a USB stick
// served over localhost). Fonts are self-hosted in src/ui/fonts.
export default defineConfig({
  base: "./",
  // build tag shown in About and in saved logs (scripts/make-kit.mjs sets it to the git commit)
  define: { __BUILD__: JSON.stringify(process.env.MYO_BUILD || "dev") },
  server: { port: 5173 },
  build: {
    target: "es2022", outDir: "dist", emptyOutDir: true,
    // monitor.html: the test kit's OSC monitor page (served by kit/launcher.mjs)
    rollupOptions: { input: { main: "index.html", monitor: "monitor.html" } },
  },
  test: { environment: "node", include: ["tests/**/*.test.ts"] },
});

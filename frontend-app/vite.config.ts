import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Served by FastAPI at /app (server/spa.py). base makes every asset URL
// resolve under /app/ so the SPA works behind the mount with
// script-src 'self' and zero inline scripts (AC-B.1/AC-B.2).
export default defineConfig({
  base: "/app/",
  plugins: [react()],
  build: {
    // Deterministic-ish output; dist/ is committed so the Python server
    // never needs Node at runtime (D1: build-time-only toolchain).
    sourcemap: false,
    assetsInlineLimit: 0, // never inline assets as data: URIs — keeps CSP surface honest
    // The motion engine gets its own chunk naturally: src/motion/anime.ts
    // dynamic-imports src/motion/engine.ts (named re-exports, tree-shaken).
    // No manualChunks — forcing the whole animejs package into a chunk
    // defeats tree-shaking and triples the <=15 kB gzip budget.
  },
});

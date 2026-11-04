import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The built app is served by the Python engine (src/prepro/server/static).
// `npm run dev` proxies /api to a running `prepro ui --no-browser` (set PREPRO_TOKEN for both).
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../src/prepro/server/static", emptyOutDir: true, chunkSizeWarningLimit: 900 },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
});

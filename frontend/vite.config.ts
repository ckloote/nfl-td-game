import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    // Same-origin in dev: the browser only ever talks to :5173, so the session
    // cookie is first-party and no CORS is needed. The Host header is preserved
    // (changeOrigin: false), matching PUBLIC_BASE_URL on the backend.
    proxy: { "/api": "http://localhost:8000" },
  },
});

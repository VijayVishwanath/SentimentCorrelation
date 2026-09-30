import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: Vite on :5173 proxies /api to FastAPI on :8000. Prod: FastAPI serves dist/.
export default defineConfig({
  plugins: [react()],
  // allowedHosts: leading dot matches any subdomain, so rotating ngrok tunnel URLs keep working.
  server: { port: 5173, allowedHosts: [".ngrok-free.app", ".ngrok.app"], proxy: { "/api": process.env.DEX_API_URL || "http://127.0.0.1:8000", "/docs": process.env.DEX_API_URL || "http://127.0.0.1:8000", "/openapi.json": process.env.DEX_API_URL || "http://127.0.0.1:8000" } },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 900 },
});

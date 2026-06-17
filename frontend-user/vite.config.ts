import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// SPA bundle for the config portal. Talks to the API at VITE_API_BASE_URL
// (default http://localhost:8000) — CORS-allowed from this origin (backend
// Part A). Dev + preview both on :5173.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  preview: { port: 5173, host: true },
});

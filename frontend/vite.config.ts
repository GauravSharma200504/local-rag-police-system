/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

const backend = process.env.VITE_BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: { "/api": { target: backend, changeOrigin: true }, "/health": { target: backend, changeOrigin: true } },
  },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/__tests__/setup.ts"], css: false },
});

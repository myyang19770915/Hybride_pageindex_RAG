/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  cacheDir: "../.cache/vite/frontend",
  build: {
    outDir: "../build/frontend",
    emptyOutDir: true
  },
  server: {
    port: 5173,
    proxy: {
      // Backend dev server. Override with VITE_API_TARGET when the backend
      // runs on a non-default port (e.g. when 8000 is taken by another service).
      "/api": process.env.VITE_API_TARGET ?? "http://127.0.0.1:8200"
    }
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"]
  }
});

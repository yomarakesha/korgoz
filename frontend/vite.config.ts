/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API serves the built dashboard under /ui (see app/api/dashboard.py).
// In development (`npm run dev`) Vite proxies API calls to uvicorn on :8000,
// so the browser sees one origin and no CORS setup is needed.
const API = process.env.KORGOZ_API ?? "http://127.0.0.1:8000";
const apiPaths = [
  "/health",
  "/settings",
  "/cameras",
  "/locations",
  "/persons",
  "/events",
  "/tracks",
  "/analytics",
  "/auth",
  "/users",
  "/audit",
];

export default defineConfig({
  base: "/ui/",
  plugins: [react()],
  server: {
    proxy: Object.fromEntries(apiPaths.map((path) => [path, { target: API, changeOrigin: false }])),
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/setupTests.ts"],
  },
});

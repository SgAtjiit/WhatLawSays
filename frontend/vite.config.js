import path from "node:path";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  // Where the FastAPI backend runs in development. Requests stay same-origin
  // in the browser, so there is no CORS to configure.
  const backend = env.BACKEND_URL || "http://localhost:8000";

  return {
    plugins: [react(), tailwindcss()],
    resolve: { alias: { "@": path.resolve(import.meta.dirname, "src") } },
    server: {
      port: 5173,
      proxy: {
        "/api": { target: backend, changeOrigin: true, timeout: 600_000, proxyTimeout: 600_000 },
        "/health": { target: backend, changeOrigin: true },
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./tests/unit/setup.js"],
      include: ["tests/unit/**/*.test.{js,jsx}"],
    },
  };
});

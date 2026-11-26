import path from "node:path";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backend = env.BACKEND_URL || "http://127.0.0.1:8000";

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

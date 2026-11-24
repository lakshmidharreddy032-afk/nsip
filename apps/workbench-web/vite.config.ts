import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/auth": "http://localhost:8001",
      "/login": "http://localhost:5174",
    },
  },
  build: { chunkSizeWarningLimit: 1500 },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    exclude: ["e2e/**", "node_modules/**"],
    coverage: {
      provider: "v8",
      include: ["src/lib/**", "src/components/**", "src/stores/**", "src/features/**"],
      exclude: ["src/**/*.test.*", "src/main.tsx"],
      thresholds: { lines: 75, statements: 75 },
    },
  },
} as any);

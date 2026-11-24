import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/login/",
  plugins: [react()],
  server: {
    port: 5174,
    proxy: { "/auth": "http://localhost:8001" },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    coverage: { provider: "v8", include: ["src/**/*.{ts,tsx}"], exclude: ["src/main.tsx", "src/test-setup.ts", "src/**/*.test.*"],
      thresholds: { lines: 75, statements: 75 } },
  },
} as any);

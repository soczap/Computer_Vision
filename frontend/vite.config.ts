import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const target = "https://127.0.0.1:8090";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5190,
    host: "127.0.0.1",
    proxy: {
      "/api": { target, secure: false, changeOrigin: true },
      "/media": { target, secure: false, changeOrigin: true },
      "/ws": { target, secure: false, ws: true, changeOrigin: true },
    },
  },
  preview: {
    port: 5191,
    host: "127.0.0.1",
    proxy: {
      "/api": { target, secure: false, changeOrigin: true },
      "/media": { target, secure: false, changeOrigin: true },
      "/ws": { target, secure: false, ws: true, changeOrigin: true },
    },
  },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 1500 },
});

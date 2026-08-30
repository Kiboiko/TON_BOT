import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev-сервер проксирует /api на backend, чтобы initData и cookie шли на тот же origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ["react", "react-dom", "react-router-dom"],
          tonconnect: ["@tonconnect/ui-react"],
        },
      },
    },
  },
});

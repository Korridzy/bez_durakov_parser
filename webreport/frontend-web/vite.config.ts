import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          charts: ["recharts"],
          markdown: ["react-markdown", "remark-gfm"],
        },
      },
    },
  },
  server: {
    proxy: {
      "/api": {
        target: process.env.WEBREPORT_DEV_API || "http://127.0.0.1:28000",
        changeOrigin: true,
      },
      "/health": {
        target: process.env.WEBREPORT_DEV_API || "http://127.0.0.1:28000",
        changeOrigin: true,
      },
    },
  },
});

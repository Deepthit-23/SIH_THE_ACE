import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The frontend calls "/api/*"; Vite proxies that to the FastAPI backend
// (running on :8000 via docker-compose) and strips the "/api" prefix.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});

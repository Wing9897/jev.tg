import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [tailwindcss(), react()],
  clearScreen: false,
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:18721",
        changeOrigin: true,
        configure(proxy) {
          proxy.on("proxyReq", (proxyReq, req) => {
            proxyReq.setTimeout(0);
            if (req.url?.includes("/events")) {
              proxyReq.setHeader("Accept", "text/event-stream");
            }
          });
          proxy.on("proxyRes", (proxyRes, req) => {
            if (req.url?.includes("/events")) {
              proxyRes.headers["cache-control"] = "no-cache, no-transform";
              proxyRes.headers["x-accel-buffering"] = "no";
              proxyRes.headers["connection"] = "keep-alive";
            }
          });
        },
      },
    },
  },
});

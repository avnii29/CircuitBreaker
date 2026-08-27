import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiBase = env.VITE_API_BASE_URL ?? "";
  if (mode === "production" && /localhost|127\.0\.0\.1|0\.0\.0\.0/.test(apiBase)) {
    throw new Error("VITE_API_BASE_URL must not point at localhost in a production build.");
  }
  return {
    plugins: [react()],
    server: {
      port: 5173,
      host: true,
    },
  };
});

// Static SPA build served by FastAPI at "/": `npm run build` → dist/index.html + dist/assets/*.
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

export default defineConfig({
  base: "/",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  build: { outDir: "dist", assetsDir: "assets", emptyOutDir: true },
});

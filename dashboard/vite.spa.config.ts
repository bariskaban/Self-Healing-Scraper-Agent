// Static SPA build served by FastAPI at "/": `npm run build` → dist/index.html + dist/assets/*.
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

// Preload the latin subset of Inter (the other subsets load only when a page needs their characters),
// so the text does not shift when the font arrives.
const preloadLatinFont = (): Plugin => ({
  name: "preload-latin-font",
  transformIndexHtml(_html, ctx) {
    const file = Object.keys(ctx.bundle ?? {}).find((f) => /inter-latin-wght-normal-[^/]*\.woff2$/.test(f));
    return file ? [{ tag: "link", attrs: { rel: "preload", as: "font", type: "font/woff2", href: `/${file}`, crossorigin: "" }, injectTo: "head" }] : [];
  },
});

export default defineConfig({
  base: "/",
  plugins: [react(), tailwindcss(), preloadLatinFont()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  build: { outDir: "dist", assetsDir: "assets", emptyOutDir: true },
});

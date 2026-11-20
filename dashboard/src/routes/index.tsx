import { createFileRoute, ClientOnly } from "@tanstack/react-router";

// Preview-only host: the shipped artifact is the static SPA (vite.spa.config.ts).
import App from "@/App";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Portal overview · Watchtower" },
      { name: "description", content: "Watchtower Delivery Ledger: operator console for public tender delivery." },
      { property: "og:title", content: "Portal overview · Watchtower" },
      { property: "og:description", content: "Operator console for public tender delivery." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: () => (
    <ClientOnly fallback={<div className="min-h-screen bg-background" />}>
      <App />
    </ClientOnly>
  ),
});

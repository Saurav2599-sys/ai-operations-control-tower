import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Plain Vite + React, no framework conventions (routing, SSR) this
// single-page ops dashboard doesn't need -- see the README's Phase 4
// design note for why Vite over Next.js here.
export default defineConfig({
  plugins: [react()],
});

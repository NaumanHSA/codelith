import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'
import { defineConfig } from 'vite'

// The studio lives in the same repo as the API it talks to.
// The API base URL comes from VITE_API_URL (see .env.local) — never hardcoded.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    port: 5173,
    strictPort: false,
  },
  preview: {
    port: 4173,
  },
  build: {
    sourcemap: false,
    // The Markdown + Mermaid stack is heavy and route-split via React.lazy,
    // so a handful of large async chunks are expected.
    chunkSizeWarningLimit: 700,
  },
})

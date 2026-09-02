import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Keep browser API calls on the same origin as Vite.
// Vite forwards /api requests to the FastAPI backend over IPv4, avoiding
// localhost/127.0.0.1 resolution and browser CORS connection problems.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})

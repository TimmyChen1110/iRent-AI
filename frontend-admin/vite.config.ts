import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 整備中心（環節三）前端。
// - base 為 /ops/：由 backend FastAPI 於 /ops 提供 build 產物（server.py ops_frontend）。
// - build 直接輸出到 backend/app/static/ops/（過渡期進版控；之後由 Dockerfile 多階段 build）。
// - dev 時 /api、/photos 代理到本機 8000（make up 的 Docker 或 uvicorn 皆可）。
export default defineConfig({
  plugins: [react()],
  base: '/ops/',
  build: {
    outDir: '../backend/app/static/ops',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/photos': 'http://localhost:8000',
    },
  },
})

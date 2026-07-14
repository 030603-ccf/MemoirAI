import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// 构建前清理旧文件（避免不同 hash 的旧 chunk 堆积）
function cleanOldAssets() {
  return {
    name: 'clean-old-assets',
    buildStart() {
      const distDir = path.resolve(__dirname, 'dist')
      if (fs.existsSync(distDir)) {
        fs.rmSync(distDir, { recursive: true, force: true })
      }
    },
  }
}

export default defineConfig({
  plugins: [cleanOldAssets(), vue()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/v1': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/api': {
        target: 'http://localhost:8088',
        changeOrigin: true,
      },
    },
  },
  appType: 'spa',
})

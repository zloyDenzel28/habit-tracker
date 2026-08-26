import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Внутри compose бэкенд доступен по имени сервиса. Переменная нужна только
// для запуска вне контейнера — там имя `api` не резолвится.
const apiTarget = process.env.VITE_API_TARGET ?? 'http://api:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    // 0.0.0.0 обязателен: иначе Vite слушает только внутри контейнера
    // и порт наружу не пробрасывается.
    host: '0.0.0.0',
    port: 5173,
    watch: {
      // На Docker Desktop и WSL2 события файловой системы до контейнера
      // не доходят — без поллинга hot reload не работает.
      usePolling: true,
    },
    proxy: {
      // Браузер ходит на localhost:5173/api/..., Vite переправляет запрос
      // на контейнер api уже со своей стороны. Так на бэке не нужен CORS:
      // для браузера это тот же origin, что и сам фронт.
      '/api': {
        target: apiTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})

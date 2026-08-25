import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

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
  },
})

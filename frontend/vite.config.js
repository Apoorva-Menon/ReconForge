import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({ plugins: [react()], server: { host: '127.0.0.1', proxy: { '/dashboard': 'http://127.0.0.1:8000', '/demo': 'http://127.0.0.1:8000', '/runs': 'http://127.0.0.1:8000', '/policies': 'http://127.0.0.1:8000', '/engine': 'http://127.0.0.1:8000', '/stream': 'http://127.0.0.1:8000' } } })

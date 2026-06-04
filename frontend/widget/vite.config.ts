import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Outputs a single widget.js bundle for embedding on merchant sites
export default defineConfig({
  plugins: [react()],
  build: {
    lib: {
      entry: 'src/widget.tsx',
      name: 'SmartBasketWidget',
      fileName: 'widget',
      formats: ['iife'],
    },
    rollupOptions: {
      external: [],
    },
  },
});

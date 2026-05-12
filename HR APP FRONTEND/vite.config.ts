import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import { defineConfig } from 'vite';

export default defineConfig(() => {
  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      hmr: process.env.DISABLE_HMR !== 'true',
    },
    build: {
      // Raise the warning threshold — our chunks are intentionally split
      chunkSizeWarningLimit: 600,
      rollupOptions: {
        output: {
          // Split heavy third-party libraries into named chunks so the browser
          // can cache them independently of app code changes.
          manualChunks: {
            // React core — changes almost never, gets long-lived cache
            'vendor-react': ['react', 'react-dom', 'react-router-dom'],
            // Charting — recharts is ~300 KB minified, only used in Analytics/Dashboard
            'vendor-charts': ['recharts'],
            // Animation — framer-motion is only used on the Landing page
            'vendor-motion': ['framer-motion'],
            // Radix UI primitives bundled together (they're already small individually)
            'vendor-radix': [
              '@radix-ui/react-dialog',
              '@radix-ui/react-dropdown-menu',
              '@radix-ui/react-select',
              '@radix-ui/react-tabs',
              '@radix-ui/react-switch',
              '@radix-ui/react-radio-group',
              '@radix-ui/react-slider',
              '@radix-ui/react-avatar',
              '@radix-ui/react-progress',
              '@radix-ui/react-separator',
            ],
          },
        },
      },
    },
    test: {
      environment: 'jsdom',
      globals: true,
    },
  };
});

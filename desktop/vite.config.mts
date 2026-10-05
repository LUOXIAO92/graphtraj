import { defineConfig } from 'vite';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  base: './',
  plugins: [tailwindcss()],
  // Keep module identity within the selected Worktree's paths.
  resolve: { preserveSymlinks: true },
});

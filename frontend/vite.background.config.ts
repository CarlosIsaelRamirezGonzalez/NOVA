/** Compila el service worker de la extensión en un solo archivo, junto a la interfaz ya compilada. */

import { defineConfig } from 'vite'

export default defineConfig({
  build: {
    outDir: '../extension/dist',
    // La interfaz ya se compiló en esa carpeta: no se borra.
    emptyOutDir: false,
    lib: {
      entry: 'src/extension/background.ts',
      formats: ['es'],
      fileName: () => 'background.js',
    },
  },
})

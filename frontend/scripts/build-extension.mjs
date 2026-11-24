// Arma la extensión de Chrome: la interfaz compilada más el manifest y el service worker.
import { cpSync } from 'node:fs'

const extension = new URL('../../extension/', import.meta.url)
// El service worker (`background.js`) ya lo compiló Vite desde `src/extension/background.ts`.
for (const file of ['manifest.json', 'confirm.html', 'confirm.js']) {
  cpSync(new URL(file, extension), new URL(`dist/${file}`, extension))
}
// Los iconos salen de la hoja del personaje (`Cara de nova.jpeg`, recuadro "DETALLE").
cpSync(new URL('icons', extension), new URL('dist/icons', extension), { recursive: true })
console.log('Extensión lista en extension/dist. Cárgala en chrome://extensions con "Cargar descomprimida".')

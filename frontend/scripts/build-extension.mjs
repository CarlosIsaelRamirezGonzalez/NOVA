// Arma la extensión de Chrome: la interfaz compilada más el manifest y el service worker.
import { cpSync } from 'node:fs'

const extension = new URL('../../extension/', import.meta.url)
for (const file of ['manifest.json', 'background.js']) {
  cpSync(new URL(file, extension), new URL(`dist/${file}`, extension))
}
console.log('Extensión lista en extension/dist. Cárgala en chrome://extensions con "Cargar descomprimida".')

/** Puente mínimo entre la interfaz y la app: solo pedir permiso de micrófono. */

const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('novaDesktop', {
  requestMicrophone: () => ipcRenderer.invoke('request-microphone'),
})

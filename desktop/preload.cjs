/** Puente mínimo entre la interfaz y la app: permiso de micrófono y mover la ventana. */

const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('novaDesktop', {
  requestMicrophone: () => ipcRenderer.invoke('request-microphone'),
  startDrag: (screenX, screenY) => ipcRenderer.send('drag-start', screenX, screenY),
  moveDrag: (screenX, screenY) => ipcRenderer.send('drag-move', screenX, screenY),
  endDrag: () => ipcRenderer.send('drag-end'),
})

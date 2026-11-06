/** Puente mínimo entre la interfaz y la app: permiso de micrófono, mover la ventana y mostrarla u ocultarla. */

const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('novaDesktop', {
  requestMicrophone: () => ipcRenderer.invoke('request-microphone'),
  startDrag: (screenX, screenY) => ipcRenderer.send('drag-start', screenX, screenY),
  moveDrag: (screenX, screenY) => ipcRenderer.send('drag-move', screenX, screenY),
  endDrag: () => ipcRenderer.send('drag-end'),
  setPresent: (present) => ipcRenderer.invoke('set-present', present),
  onPresenceCommand: (handler) => {
    const listener = (_event, command) => handler(command)
    ipcRenderer.on('presence-command', listener)
    return () => ipcRenderer.removeListener('presence-command', listener)
  },
})

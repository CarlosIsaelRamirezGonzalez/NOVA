/** Puente mínimo entre la interfaz y la app: permiso de micrófono, mover la ventana y mostrarla u ocultarla. */

const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('novaDesktop', {
  requestMicrophone: () => ipcRenderer.invoke('request-microphone'),
  startDrag: (screenX, screenY) => ipcRenderer.send('drag-start', screenX, screenY),
  moveDrag: (screenX, screenY) => ipcRenderer.send('drag-move', screenX, screenY),
  endDrag: () => ipcRenderer.send('drag-end'),
  moveTo: (place) => ipcRenderer.send('move-to', place),
  pauseWander: (reason, paused) => ipcRenderer.send('pause-wander', reason, paused),
  onPose: (handler) => {
    const listener = (_event, pose) => handler(pose)
    ipcRenderer.on('nova-pose', listener)
    return () => ipcRenderer.removeListener('nova-pose', listener)
  },
  onTravel: (handler) => {
    const listener = (_event, vx, vy, headingX, headingY) => handler(vx, vy, headingX, headingY)
    ipcRenderer.on('window-travel', listener)
    return () => ipcRenderer.removeListener('window-travel', listener)
  },
  setPresent: (present) => ipcRenderer.invoke('set-present', present),
  onPresenceCommand: (handler) => {
    const listener = (_event, command) => handler(command)
    ipcRenderer.on('presence-command', listener)
    return () => ipcRenderer.removeListener('presence-command', listener)
  },
})

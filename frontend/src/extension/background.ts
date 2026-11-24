/**
 * Service worker de la extensión de Nova.
 *
 * Abre el panel lateral al tocar el icono y le presta el navegador a la Nova de la Mac: se
 * conecta al servidor local (`127.0.0.1:8787/browser`) y ejecuta las acciones que le pida, aunque
 * el panel esté cerrado. Si la Mac no tiene a Nova abierta, lo vuelve a intentar cada minuto.
 */

import { runBrowserAction, type BrowserAction } from '../browser/actions'

const MAC_SERVER = 'ws://127.0.0.1:8787/browser'
const RECONNECT_ALARM = 'nova-mac-reconnect'
// Chrome duerme al service worker tras 30 s sin actividad; un pulso lo mantiene despierto.
const KEEPALIVE_MS = 20000
const CONFIRM_WIDTH = 420
const CONFIRM_HEIGHT = 220

/** Pedido de acción que manda la Mac; mismo formato que en el panel. */
type BrowserActionEvent = { type: 'browser_action'; request_id: string; action: BrowserAction }

/** Respuesta de la ventanita de confirmación. */
type ConfirmAnswer = { type: 'nova-confirm'; id: string; accepted: boolean }

let socket: WebSocket | null = null
let keepalive: ReturnType<typeof setInterval> | undefined
// Confirmaciones abiertas: la ventanita de cada una y cómo avisar la respuesta.
const pendingConfirmations = new Map<string, { windowId?: number; resolve: (accepted: boolean) => void }>()

// Al tocar el icono se abre el panel lateral.
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch((error: unknown) => {
  console.error('[Nova] No se pudo configurar el panel lateral', error)
})

/**
 * Pregunta a Carlos en una ventanita, porque el panel puede estar cerrado.
 *
 * @param question - Lo que Nova quiere hacer.
 * @returns Si dijo que sí; cerrar la ventana cuenta como no.
 */
async function confirmInWindow(question: string): Promise<boolean> {
  const id = crypto.randomUUID()
  const url = chrome.runtime.getURL(`confirm.html?id=${id}&q=${encodeURIComponent(question)}`)
  return new Promise<boolean>((resolve) => {
    pendingConfirmations.set(id, { resolve })
    void chrome.windows
      .create({ url, type: 'popup', width: CONFIRM_WIDTH, height: CONFIRM_HEIGHT, focused: true })
      .then((created) => {
        const pending = pendingConfirmations.get(id)
        if (pending) pending.windowId = created?.id
      })
  })
}

/**
 * Entrega la respuesta de una confirmación y la olvida.
 *
 * @param id - Confirmación.
 * @param accepted - Si dijo que sí.
 */
function settleConfirmation(id: string, accepted: boolean): void {
  const pending = pendingConfirmations.get(id)
  if (!pending) return
  pendingConfirmations.delete(id)
  pending.resolve(accepted)
}

chrome.runtime.onMessage.addListener((message: ConfirmAnswer) => {
  if (message?.type === 'nova-confirm') settleConfirmation(message.id, message.accepted)
})

chrome.windows.onRemoved.addListener((windowId) => {
  for (const [id, pending] of pendingConfirmations) {
    if (pending.windowId === windowId) settleConfirmation(id, false)
  }
})

/** Se conecta a la Nova de la Mac, si no lo está ya. */
function connect(): void {
  if (socket && socket.readyState <= WebSocket.OPEN) return
  const ws = new WebSocket(MAC_SERVER)
  socket = ws

  ws.onopen = () => {
    clearInterval(keepalive)
    keepalive = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }))
    }, KEEPALIVE_MS)
  }

  ws.onmessage = ({ data }) => {
    const event = JSON.parse(String(data)) as BrowserActionEvent
    if (event.type !== 'browser_action') return
    void runBrowserAction(event.action, confirmInWindow).then((result) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'browser_result', request_id: event.request_id, ...result }))
      }
    })
  }

  // Sin la Mac, no se insiste aquí: la alarma lo vuelve a intentar cada minuto.
  ws.onclose = () => {
    clearInterval(keepalive)
    if (socket === ws) socket = null
  }
}

// Chrome puede dormir al service worker; la alarma lo despierta para reconectarse.
chrome.alarms.create(RECONNECT_ALARM, { periodInMinutes: 1 })
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === RECONNECT_ALARM) connect()
})
chrome.runtime.onStartup.addListener(connect)
chrome.runtime.onInstalled.addListener(connect)
connect()

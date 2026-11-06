/** Hook de conversación: WebSocket, voz y mensajes. */

import { useCallback, useEffect, useRef, useState } from 'react'
import { EMOTIONS, type EmotionBlend, type EmotionComponent } from '../nova/emotions'
import type { Gesture } from '../nova/gestures'

/** Un recuerdo de Nova, tal como lo envía el servidor. */
export type BrainMemory = {
  id: number
  kind: 'fact' | 'preference' | 'person' | 'event' | 'plan' | 'moment'
  content: string
  importance: number
  emotions: { components: EmotionComponent[] }
  created_at: number
}

/** Lo que muestra la vista del cerebro. */
export type Brain = {
  memories: BrainMemory[]
  links: { source: number; target: number; strength: number }[]
  mood: EmotionComponent[]
}

/** Para qué fue una llamada a una API. */
export type UsagePurpose = 'conversation' | 'memory' | 'search' | 'voice'

/** Gasto de un día, para la gráfica. */
export type UsageDay = {
  day: string
  conversation: number
  memory: number
  search: number
}

/** Lo que muestra la vista de gastos. */
export type Usage = {
  today_usd: number
  month_usd: number
  days: UsageDay[]
  services: {
    purpose: UsagePurpose
    calls: number
    input_tokens: number
    output_tokens: number
    searches: number
    credits: number
    cost_usd: number
  }[]
  voice: { tier: string; used: number; limit: number; resets_at: number | null } | null
}

/** En qué va la escucha del micrófono. */
export type ListenState = 'off' | 'loading' | 'waiting' | 'hearing' | 'conversing' | 'transcribing' | 'error'

/** Funciones que agrega la app de escritorio; en el navegador no existen. */
type DesktopBridge = { requestMicrophone: () => Promise<boolean> }

/** Dónde se recuerda si el micrófono estaba encendido. */
const LISTEN_STORAGE_KEY = 'nova-listen-enabled'
/** Espera antes de reabrir el micrófono, para no captar el final de su propia voz. */
const MIC_REOPEN_DELAY_MS = 350

/**
 * Lee si el micrófono estaba encendido.
 *
 * @returns Lo guardado; apagado si no hay nada o no se puede leer.
 */
function readListenPreference(): boolean {
  try {
    return localStorage.getItem(LISTEN_STORAGE_KEY) === 'on'
  } catch {
    return false
  }
}

/** Lo último que recordó Nova y cuándo, en el reloj de la animación. */
export type Recall = {
  ids: number[]
  at: number
}

/** En qué va una búsqueda en internet: buscando, o ya contando lo que encontró. */
export type WebSearchStage = 'none' | 'searching' | 'reading' | 'writing'

/** Fase del turno de conversación. */
export type Phase = 'idle' | 'thinking' | 'speaking'

/** Un mensaje visible en el chat. */
export type Message = {
  id: number
  role: 'user' | 'nova' | 'photo' | 'search'
  text: string // en una foto, es la imagen como data URL; en una búsqueda, lo que se buscó
  sources?: string[] // en una búsqueda, los enlaces de donde salió la información
}

/** Eventos JSON que envía el backend; el audio llega aparte, como binario. */
type ServerEvent =
  | { type: 'token'; text: string }
  | { type: 'emotion'; components: { name: string; intensity: number }[] }
  | { type: 'photo_request'; request_id: string; remaining: number }
  | { type: 'search_start'; query: string }
  | { type: 'search_done'; sources: string[] }
  | { type: 'write_start' }
  | { type: 'write_done' }
  | { type: 'interrupted' }
  | ({ type: 'brain' } & Brain)
  | ({ type: 'usage' } & Usage)
  | { type: 'listen_state'; state: ListenState }
  | { type: 'heard'; text: string }
  | { type: 'recall'; memory_ids: number[] }
  | { type: 'gesture_reaction'; gesture: Gesture }
  | { type: 'history'; replace: boolean; messages: { role: 'user' | 'assistant'; text: string }[] }
  | { type: 'done' }
  | { type: 'error'; message: string }

const RECONNECT_MS = 1500

/** Cómo se registra cada gesto en el chat. */
const GESTURE_LABELS: Record<Gesture, string> = {
  middle_finger: '(Le enseñaste el dedo de en medio)',
  thumbs_up: '(Le hiciste pulgar arriba)',
}
// Igual que en el backend: lo que siente pierde la mitad de su fuerza cada minuto.
const EMOTION_HALF_LIFE_MS = 60000
const EMOTION_FADE_STEP_MS = 1000
const MIN_EMOTION_INTENSITY = 0.08

/**
 * Gestiona la conexión con el backend, la reproducción de la voz y el estado del chat.
 *
 * @param capturePhoto - Toma una foto; devuelve `null` si la cámara está apagada.
 * @param cameraOn - Si la cámara está encendida ahora; se le informa al modelo en cada mensaje.
 * @returns El estado de la conversación y las acciones para enviar mensajes y leer el volumen.
 */
export function useNova(capturePhoto: () => string | null, cameraOn: boolean) {
  const [connected, setConnected] = useState(false)
  const [phase, setPhase] = useState<Phase>('idle')
  const [messages, setMessages] = useState<Message[]>([])
  const [error, setError] = useState<string | null>(null)
  const [blend, setBlend] = useState<EmotionBlend>([])
  const [calmCount, setCalmCount] = useState(0)
  const [brain, setBrain] = useState<Brain | null>(null)
  const [recall, setRecall] = useState<Recall | null>(null)
  const [usage, setUsage] = useState<Usage | null>(null)
  const [listenEnabled, setListenEnabled] = useState(readListenPreference)
  const [listenState, setListenState] = useState<ListenState>('off')
  const latestListenEnabled = useRef(listenEnabled)
  // La compu aparece al buscar y se queda mientras Nova te cuenta lo que encontró.
  const [webSearch, setWebSearch] = useState<WebSearchStage>('none')
  const [photoCount, setPhotoCount] = useState(0)
  const [interruptCount, setInterruptCount] = useState(0)
  const [photosRemaining, setPhotosRemaining] = useState<number | null>(null)

  // Guarda la función actual para usarla dentro del WebSocket sin reconectarlo.
  const latestCapture = useRef(capturePhoto)
  const latestCameraOn = useRef(cameraOn)
  useEffect(() => {
    latestCapture.current = capturePhoto
    latestCameraOn.current = cameraOn
  })

  // Referencias de la conexión.
  const socket = useRef<WebSocket | null>(null)
  const nextId = useRef(0)

  // Referencias del audio; no provocan renders al cambiar.
  const audioContext = useRef<AudioContext | null>(null)
  const analyser = useRef<AnalyserNode | null>(null)
  const samples = useRef<Uint8Array<ArrayBuffer> | null>(null)
  const sources = useRef(new Set<AudioBufferSourceNode>())
  const decoding = useRef<Promise<void>>(Promise.resolve())
  const playAt = useRef(0)
  const pendingAudio = useRef(0)
  const turnFinished = useRef(true)
  // Sube con cada interrupción: el audio que aún se esté decodificando ya no debe sonar.
  const audioGeneration = useRef(0)
  // Tras interrumpir, lo que siga llegando es del turno cortado hasta que el servidor confirme.
  const discarding = useRef(false)

  // Vuelve al reposo cuando el servidor terminó y ya sonó todo el audio.
  const finishIfDone = useCallback(() => {
    if (turnFinished.current && pendingAudio.current === 0) {
      setPhase('idle')
      setWebSearch('none')
    }
  }, [])

  // Los navegadores solo dejan iniciar audio después de un clic o tecla del usuario.
  const unlockAudio = useCallback(() => {
    if (!audioContext.current) {
      const context = new AudioContext()
      const node = context.createAnalyser()
      node.fftSize = 1024
      node.connect(context.destination)
      audioContext.current = context
      analyser.current = node
      samples.current = new Uint8Array(new ArrayBuffer(node.fftSize))
    }
    void audioContext.current.resume()
  }, [])

  // Un tono corto avisa que la llamaron y que ya puede hablar.
  const playWakeSound = useCallback(() => {
    const context = audioContext.current
    if (!context) return
    const oscillator = context.createOscillator()
    const volume = context.createGain()
    oscillator.frequency.value = 880
    volume.gain.setValueAtTime(0.08, context.currentTime)
    volume.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 0.18)
    oscillator.connect(volume).connect(context.destination)
    oscillator.start()
    oscillator.stop(context.currentTime + 0.18)
  }, [])

  // Corta la voz, por ejemplo si se pierde la conexión.
  const stopAudio = useCallback(() => {
    for (const source of sources.current) {
      source.onended = null
      source.stop()
    }
    sources.current.clear()
    pendingAudio.current = 0
    playAt.current = 0
  }, [])

  // Programa un fragmento de audio justo después del anterior.
  const enqueueAudio = useCallback(
    (bytes: ArrayBuffer) => {
      // Sin contexto de audio todavía no hay dónde reproducir.
      const context = audioContext.current
      const output = analyser.current
      if (!context || !output) return
      const generation = audioGeneration.current

      // Cuenta el fragmento hasta que termine de sonar o falle.
      pendingAudio.current += 1
      const settle = () => {
        pendingAudio.current = Math.max(0, pendingAudio.current - 1)
        finishIfDone()
      }

      // Decodificar es asíncrono: encadenarlo mantiene el orden de las frases.
      decoding.current = decoding.current.then(async () => {
        try {
          const buffer = await context.decodeAudioData(bytes)
          if (generation !== audioGeneration.current) return
          const source = context.createBufferSource()
          source.buffer = buffer
          source.connect(output)
          source.onended = () => {
            sources.current.delete(source)
            settle()
          }
          sources.current.add(source)
          const start = Math.max(context.currentTime + 0.02, playAt.current)
          source.start(start)
          playAt.current = start + buffer.duration
          setPhase('speaking')
        } catch (cause) {
          console.error('No se pudo reproducir un fragmento', cause)
          settle()
        }
      })
    },
    [finishIfDone],
  )

  // Mantiene el WebSocket abierto y se reconecta si se cae.
  useEffect(() => {
    let disposed = false
    let retry: ReturnType<typeof setTimeout>

    const connect = () => {
      const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
      const ws = new WebSocket(`${scheme}://${location.host}/ws`)
      ws.binaryType = 'arraybuffer'
      socket.current = ws

      ws.onopen = () => {
        discarding.current = false
        setConnected(true)
        setError(null)
        // Si estaba encendido, sigue encendido después de recargar o reconectar.
        if (latestListenEnabled.current) ws.send(JSON.stringify({ type: 'listen', enabled: true }))
      }

      // El binario es audio; el texto es un evento JSON.
      ws.onmessage = ({ data }) => {
        if (data instanceof ArrayBuffer) {
          if (!discarding.current) enqueueAudio(data)
          return
        }
        const event = JSON.parse(data) as ServerEvent

        // El cerebro no depende del turno en curso, ni siquiera si se acaba de interrumpir.
        if (event.type === 'brain') {
          setBrain({ memories: event.memories, links: event.links, mood: event.mood })
          return
        }
        if (event.type === 'listen_state') {
          setListenState(event.state)
          if (event.state === 'hearing') playWakeSound()
          return
        }
        if (event.type === 'heard') {
          // Lo que se dijo con la voz entra al chat como si se hubiera escrito.
          discarding.current = false
          turnFinished.current = false
          setPhase('thinking')
          setMessages((current) => [...current, { id: nextId.current++, role: 'user', text: event.text }])
          return
        }
        if (event.type === 'usage') {
          setUsage(event)
          return
        }
        if (event.type === 'recall') {
          setRecall({ ids: event.memory_ids, at: performance.now() })
          return
        }

        // Confirmación del corte: desde aquí todo pertenece al turno siguiente.
        if (event.type === 'interrupted') {
          discarding.current = false
          return
        }
        if (discarding.current) return

        if (event.type === 'history') {
          // Al abrir la página o tras olvidar algo; en una reconexión, el chat ya está completo.
          setMessages((current) =>
            current.length > 0 && !event.replace
              ? current
              : event.messages.map((message) => ({
                  id: nextId.current++,
                  role: message.role === 'assistant' ? 'nova' : 'user',
                  text: message.text,
                })),
          )
        } else if (event.type === 'gesture_reaction') {
          // Queda en el chat para que su respuesta tenga contexto y no se una a la anterior.
          turnFinished.current = false
          setPhase('thinking')
          setMessages((current) => [
            ...current,
            { id: nextId.current++, role: 'user', text: GESTURE_LABELS[event.gesture] },
          ])
        } else if (event.type === 'photo_request') {
          // Toma la foto y la muestra en el chat, para que se vea exactamente qué recibió Nova.
          const dataUrl = latestCapture.current()
          if (dataUrl) {
            setPhotoCount((count) => count + 1)
            setPhotosRemaining(event.remaining - 1)
            setMessages((current) => [...current, { id: nextId.current++, role: 'photo', text: dataUrl }])
          }
          ws.send(JSON.stringify({ type: 'photo', request_id: event.request_id, data_url: dataUrl }))
        } else if (event.type === 'search_start') {
          // Deja constancia en el chat de qué buscó.
          setWebSearch('searching')
          setMessages((current) => [...current, { id: nextId.current++, role: 'search', text: event.query }])
        } else if (event.type === 'write_start') {
          setWebSearch('writing')
        } else if (event.type === 'write_done') {
          setWebSearch('none')
        } else if (event.type === 'search_done') {
          setWebSearch('reading')
          setMessages((current) => {
            const last = current.at(-1)
            if (last?.role !== 'search') return current
            return [...current.slice(0, -1), { ...last, sources: event.sources }]
          })
        } else if (event.type === 'emotion') {
          // Descarta emociones que esta versión de la interfaz no conozca.
          setBlend(
            event.components.filter((item): item is EmotionComponent =>
              (EMOTIONS as readonly string[]).includes(item.name),
            ),
          )
        } else if (event.type === 'token') {
          // Agrega el fragmento al mensaje de Nova en curso, o crea uno nuevo.
          setMessages((current) => {
            // Después de una foto empieza un mensaje nuevo, para que quede en orden.
            const last = current.at(-1)
            if (last?.role === 'nova') {
              return [...current.slice(0, -1), { ...last, text: last.text + event.text }]
            }
            return [...current, { id: nextId.current++, role: 'nova', text: event.text }]
          })
        } else {
          if (event.type === 'error') setError(event.message)
          turnFinished.current = true
          finishIfDone()
        }
      }

      // Reinicia el turno y programa la reconexión.
      ws.onclose = () => {
        if (disposed) return
        setConnected(false)
        stopAudio()
        setWebSearch('none')
        turnFinished.current = true
        setPhase('idle')
        retry = setTimeout(connect, RECONNECT_MS)
      }
    }

    connect()
    return () => {
      disposed = true
      clearTimeout(retry)
      socket.current?.close()
      stopAudio()
    }
  }, [enqueueAudio, finishIfDone, playWakeSound, stopAudio])

  // Lo que siente se desvanece poco a poco, en vez de desaparecer de golpe.
  useEffect(() => {
    const factor = 0.5 ** (EMOTION_FADE_STEP_MS / EMOTION_HALF_LIFE_MS)
    const timer = setInterval(() => {
      setBlend((current) =>
        current.length === 0
          ? current
          : current
              .map((item) => ({ ...item, intensity: item.intensity * factor }))
              .filter((item) => item.intensity >= MIN_EMOTION_INTENSITY),
      )
    }, EMOTION_FADE_STEP_MS)
    return () => clearInterval(timer)
  }, [])

  // Envía un mensaje del usuario e inicia el turno.
  const send = useCallback(
    (text: string) => {
      const ws = socket.current
      if (ws?.readyState !== WebSocket.OPEN) return
      unlockAudio()
      setError(null)
      turnFinished.current = false
      setPhase('thinking')
      setMessages((current) => [...current, { id: nextId.current++, role: 'user', text }])
      ws.send(JSON.stringify({ type: 'chat', text, camera_on: latestCameraOn.current }))
    },
    [unlockAudio],
  )

  // Avisa de un gesto; Nova reacciona por su cuenta. Si está ocupada, el servidor lo ignora.
  const sendGesture = useCallback(
    (gesture: Gesture) => {
      const ws = socket.current
      if (ws?.readyState !== WebSocket.OPEN) return
      unlockAudio()
      ws.send(JSON.stringify({ type: 'gesture', name: gesture }))
    },
    [unlockAudio],
  )

  // Pide al servidor el estado actual del cerebro.
  const requestBrain = useCallback(() => {
    const ws = socket.current
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'brain' }))
  }, [])

  // Enciende o apaga el micrófono y recuerda la elección.
  const toggleListening = useCallback(async () => {
    const next = !latestListenEnabled.current
    if (next) {
      unlockAudio()
      const bridge = (window as unknown as { novaDesktop?: DesktopBridge }).novaDesktop
      if (bridge && !(await bridge.requestMicrophone())) {
        setListenState('error')
        return
      }
    }
    latestListenEnabled.current = next
    setListenEnabled(next)
    if (!next) setListenState('off')
    try {
      localStorage.setItem(LISTEN_STORAGE_KEY, next ? 'on' : 'off')
    } catch {
      // Sin almacenamiento, solo dura hasta recargar.
    }
    const ws = socket.current
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'listen', enabled: next }))
  }, [unlockAudio])

  // El micrófono se cierra mientras Nova responde, para que no se oiga a sí misma.
  useEffect(() => {
    const send = () => {
      const ws = socket.current
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'mic_gate', open: phase === 'idle', camera_on: cameraOn }))
      }
    }
    if (phase !== 'idle') {
      send()
      return
    }
    const timer = setTimeout(send, MIC_REOPEN_DELAY_MS)
    return () => clearTimeout(timer)
  }, [phase, cameraOn, connected])

  // Pide los gastos; se puede hacer aunque Nova esté respondiendo.
  const requestUsage = useCallback(() => {
    const ws = socket.current
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'usage' }))
  }, [])

  // Borra un recuerdo; el servidor responde con el cerebro actualizado.
  const forgetMemory = useCallback((memoryId: number) => {
    const ws = socket.current
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'forget_memory', memory_id: memoryId }))
    }
  }, [])

  // Corta a Nova: la voz se detiene al instante, sin esperar al servidor.
  const interrupt = useCallback(() => {
    const ws = socket.current
    if (ws?.readyState !== WebSocket.OPEN) return

    ws.send(JSON.stringify({ type: 'interrupt' }))
    discarding.current = true
    audioGeneration.current += 1
    stopAudio()
    setWebSearch('none')
    turnFinished.current = true
    setPhase('idle')
    setInterruptCount((count) => count + 1)

    // Marca en el chat hasta dónde alcanzó a llegar.
    setMessages((current) => {
      const last = current.at(-1)
      if (last?.role !== 'nova') return current
      return [...current.slice(0, -1), { ...last, text: `${last.text.trimEnd()} —` }]
    })
  }, [stopAudio])

  // Pide calmar a Nova; la animación responde sin esperar al servidor.
  const calm = useCallback(() => {
    const ws = socket.current
    if (ws?.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify({ type: 'calm' }))
    setBlend([])
    setCalmCount((count) => count + 1)
  }, [])

  /**
   * Mide el volumen actual de la voz de Nova.
   *
   * @returns El nivel RMS de la señal; 0 si no está sonando nada.
   */
  const getLevel = useCallback(() => {
    const node = analyser.current
    const data = samples.current
    if (!node || !data || sources.current.size === 0) return 0
    node.getByteTimeDomainData(data)
    let sum = 0
    for (const sample of data) {
      const centered = (sample - 128) / 128
      sum += centered * centered
    }
    return Math.sqrt(sum / data.length)
  }, [])

  return {
    connected,
    phase,
    webSearch,
    blend,
    calmCount,
    photoCount,
    interruptCount,
    photosRemaining,
    messages,
    error,
    send,
    calm,
    interrupt,
    sendGesture,
    brain,
    recall,
    requestBrain,
    usage,
    requestUsage,
    listenEnabled,
    listenState,
    toggleListening,
    forgetMemory,
    unlockAudio,
    getLevel,
  }
}

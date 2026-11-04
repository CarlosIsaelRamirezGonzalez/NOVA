/** Hook de la cámara: enciende el video, toma fotos y detecta la cara en el equipo. */

import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'
import type { FaceLandmarker, HandLandmarker } from '@mediapipe/tasks-vision'
import type { EmotionBlend } from '../nova/emotions'
import { detectGesture, type Gesture } from '../nova/gestures'

const PHOTO_WIDTH = 640
const PHOTO_HEIGHT = 480
const PHOTO_QUALITY = 0.8
// Cara y manos se analizan por turnos, para no cargar demasiado el equipo.
const DETECTION_INTERVAL_MS = 150
const GESTURE_HOLD_READINGS = 2
const NOSE_LANDMARK = 1
const SMILE_THRESHOLD = 0.45
const ABSENT_AFTER_MS = 3000
const LONELY_AFTER_MS = 15000
const GREETING_MS = 3000
const PERMISSION_STUCK_MS = 15000

const PERMISSION_PROMPT_MESSAGE =
  'Chrome está pidiendo permiso. Busca el aviso junto a la barra de direcciones y pulsa Permitir.'
const PERMISSION_STUCK_MESSAGE =
  'Chrome no ha recibido respuesta. Pulsa el icono a la izquierda de la dirección, permite la cámara y recarga la página. Si no aparece nada, activa Chrome en Ajustes del Sistema > Privacidad y seguridad > Cámara y reinícialo.'

/** Posición de la cara en la imagen, de 0 a 1. */
export type FacePosition = {
  x: number
  y: number
}

/** Lo que observa la detección local, sin que ninguna imagen salga del equipo. */
type Observation = {
  smiling: boolean
  greeting: boolean
  lonely: boolean
}

const NO_OBSERVATION: Observation = { smiling: false, greeting: false, lonely: false }

/**
 * Traduce lo observado en una reacción instintiva de Nova.
 *
 * @param observation - Lo que detectó la cámara.
 * @returns Las emociones que provoca; no se envían a Grok.
 */
function reflexFor(observation: Observation): EmotionBlend {
  if (observation.greeting) return [{ name: 'happy', intensity: 0.6 }]
  if (observation.smiling) return [{ name: 'happy', intensity: 0.45 }]
  if (observation.lonely) return [{ name: 'curious', intensity: 0.3 }]
  return []
}

/**
 * Explica por qué no se pudo encender la cámara.
 *
 * @param cause - Error que devolvió el navegador.
 * @returns El mensaje para el usuario.
 */
function describeCameraError(cause: unknown): string {
  const name = cause instanceof DOMException ? cause.name : ''
  const message = cause instanceof DOMException ? cause.message : ''

  // macOS le niega la cámara a Chrome, aunque la página tenga permiso.
  if (name === 'NotAllowedError' && message.includes('system')) {
    return 'macOS está bloqueando la cámara. Activa Chrome en Ajustes del Sistema > Privacidad y seguridad > Cámara y reinícialo.'
  }
  if (name === 'NotAllowedError') {
    return 'Chrome bloqueó la cámara. Pulsa el icono a la izquierda de la dirección, permítela y recarga la página.'
  }
  if (name === 'NotFoundError') return 'No se encontró ninguna cámara en este equipo.'
  if (name === 'NotReadableError') {
    return 'La cámara está ocupada. Cierra otras aplicaciones que la estén usando, como Zoom o FaceTime.'
  }
  return 'No pude encender la cámara. Recarga la página e inténtalo otra vez.'
}

/**
 * Crea los detectores; la librería se carga solo si se enciende la cámara.
 *
 * @returns El detector de caras y el de manos; cada uno puede faltar si no logró cargar.
 */
async function createDetectors() {
  const { FaceLandmarker, FilesetResolver, HandLandmarker } = await import('@mediapipe/tasks-vision')
  const fileset = await FilesetResolver.forVisionTasks('/mediapipe/wasm')
  const [face, hand] = await Promise.allSettled([
    FaceLandmarker.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: '/models/face_landmarker.task', delegate: 'GPU' },
      runningMode: 'VIDEO',
      numFaces: 1,
      outputFaceBlendshapes: true,
    }),
    HandLandmarker.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: '/models/hand_landmarker.task', delegate: 'GPU' },
      runningMode: 'VIDEO',
      numHands: 2,
    }),
  ])

  if (face.status === 'rejected') console.error('No se pudo iniciar la detección de cara', face.reason)
  if (hand.status === 'rejected') console.error('No se pudo iniciar la detección de manos', hand.reason)
  return {
    face: face.status === 'fulfilled' ? face.value : null,
    hand: hand.status === 'fulfilled' ? hand.value : null,
  }
}

/**
 * Gestiona la cámara del navegador. Está apagada hasta que el usuario la enciende.
 *
 * @param video - Elemento de video donde se muestra lo que ve la cámara.
 * @param onGesture - Recibe cada gesto sostenido de la mano; apunta a la función actual.
 * @returns El estado de la cámara, la reacción instintiva y las acciones disponibles.
 */
export function useCamera(
  video: RefObject<HTMLVideoElement | null>,
  onGesture: RefObject<(gesture: Gesture) => void>,
) {
  const [active, setActive] = useState(false)
  const [waitingForPermission, setWaitingForPermission] = useState(false)
  const [cameraError, setCameraError] = useState<string | null>(null)
  const [observation, setObservation] = useState<Observation>(NO_OBSERVATION)
  const stream = useRef<MediaStream | null>(null)
  const requesting = useRef(false)
  const face = useRef<FacePosition | null>(null)
  const canvas = useRef<HTMLCanvasElement | null>(null)

  // Apaga la cámara y olvida lo observado.
  const stop = useCallback(() => {
    stream.current?.getTracks().forEach((track) => track.stop())
    stream.current = null
    face.current = null
    setActive(false)
    setObservation(NO_OBSERVATION)
  }, [])

  // Enciende o apaga la cámara; el navegador pide permiso la primera vez.
  const toggle = useCallback(async () => {
    // Mientras el navegador espera tu respuesta, otro clic solo acumularía pedidos.
    if (requesting.current) return

    if (stream.current) {
      stop()
      return
    }

    requesting.current = true
    setWaitingForPermission(true)
    setCameraError(PERMISSION_PROMPT_MESSAGE)

    // Si nadie responde, el pedido queda colgado sin error: aquí se explica qué revisar.
    const timer = setTimeout(() => setCameraError(PERMISSION_STUCK_MESSAGE), PERMISSION_STUCK_MS)

    try {
      stream.current = await navigator.mediaDevices.getUserMedia({
        video: { width: PHOTO_WIDTH, height: PHOTO_HEIGHT, facingMode: 'user' },
        audio: false,
      })
      setCameraError(null)
      setActive(true)
    } catch (cause) {
      console.error('No se pudo encender la cámara', cause)
      setCameraError(describeCameraError(cause))
    } finally {
      clearTimeout(timer)
      requesting.current = false
      setWaitingForPermission(false)
    }
  }, [stop])

  // Conecta el video cuando aparece en pantalla.
  useEffect(() => {
    if (active && video.current && stream.current) {
      video.current.srcObject = stream.current
    }
  }, [active, video])

  // Detecta la cara varias veces por segundo mientras la cámara está encendida.
  useEffect(() => {
    if (!active) return

    let stopped = false
    let detector: FaceLandmarker | null = null
    let handDetector: HandLandmarker | null = null
    let tick = 0
    let heldGesture: Gesture | null = null
    let heldReadings = 0
    let gestureReported = false
    let timer: ReturnType<typeof setInterval> | undefined
    let lastSeen = performance.now()
    let wasAbsent = true
    let greetingUntil = 0

    /**
     * Busca gestos en el cuadro actual y avisa cuando uno se sostiene.
     *
     * @param element - Video de la cámara.
     * @param now - Marca de tiempo del cuadro.
     */
    const detectHands = (element: HTMLVideoElement, now: number) => {
      if (!handDetector) return
      const hands = handDetector.detectForVideo(element, now).landmarks
      const gesture = hands.map(detectGesture).find(Boolean) ?? null

      // Exige que se sostenga un momento: un cuadro suelto puede ser un movimiento cualquiera.
      heldReadings = gesture === heldGesture ? heldReadings + 1 : 1
      if (gesture !== heldGesture) gestureReported = false
      heldGesture = gesture

      // Avisa una sola vez por gesto, aunque sigas sosteniéndolo.
      if (gesture && heldReadings >= GESTURE_HOLD_READINGS && !gestureReported) {
        gestureReported = true
        onGesture.current(gesture)
      }
    }

    /**
     * Analiza la cara en el cuadro actual y actualiza lo observado.
     *
     * @param element - Video de la cámara.
     * @param now - Marca de tiempo del cuadro.
     */
    const detectFace = (element: HTMLVideoElement, now: number) => {
      if (!detector) return
      const result = detector.detectForVideo(element, now)
      const landmarks = result.faceLandmarks[0]

      // Guarda dónde está la cara y si acaba de llegar después de una ausencia.
      if (landmarks) {
        const nose = landmarks[NOSE_LANDMARK]
        face.current = { x: nose.x, y: nose.y }
        if (wasAbsent) greetingUntil = now + GREETING_MS
        wasAbsent = false
        lastSeen = now
      } else if (now - lastSeen > ABSENT_AFTER_MS) {
        face.current = null
        wasAbsent = true
      }

      // La sonrisa es el promedio de ambas comisuras.
      const categories = result.faceBlendshapes[0]?.categories ?? []
      const smile = categories
        .filter((item) => item.categoryName === 'mouthSmileLeft' || item.categoryName === 'mouthSmileRight')
        .reduce((sum, item) => sum + item.score / 2, 0)

      // Solo actualiza React si algo cambió, para no repintar cinco veces por segundo.
      const next: Observation = {
        smiling: smile > SMILE_THRESHOLD,
        greeting: now < greetingUntil,
        lonely: now - lastSeen > LONELY_AFTER_MS,
      }
      setObservation((current) =>
        current.smiling === next.smiling &&
        current.greeting === next.greeting &&
        current.lonely === next.lonely
          ? current
          : next,
      )
    }

    /**
     * Analiza por turnos la cara y las manos.
     */
    const detect = () => {
      const element = video.current
      if (!element || element.readyState < 2) return
      tick += 1
      if (tick % 2 === 0) detectHands(element, performance.now())
      else detectFace(element, performance.now())
    }

    // Si falla la detección, la cámara sigue sirviendo para tomar fotos.
    createDetectors()
      .then((created) => {
        if (stopped) {
          created.face?.close()
          created.hand?.close()
          return
        }
        detector = created.face
        handDetector = created.hand
        timer = setInterval(detect, DETECTION_INTERVAL_MS)
      })
      .catch((cause) => {
        console.error('No se pudo iniciar la detección', cause)
      })

    return () => {
      stopped = true
      clearInterval(timer)
      detector?.close()
      handDetector?.close()
    }
  }, [active, video, onGesture])

  // Apaga la cámara al salir de la página.
  useEffect(() => stop, [stop])

  /**
   * Toma una foto del video actual.
   *
   * @returns La foto en JPEG como data URL, o `null` si la cámara está apagada.
   */
  const capture = useCallback((): string | null => {
    const element = video.current
    if (!stream.current || !element || element.readyState < 2) return null

    canvas.current ??= document.createElement('canvas')
    canvas.current.width = PHOTO_WIDTH
    canvas.current.height = PHOTO_HEIGHT
    canvas.current.getContext('2d')?.drawImage(element, 0, 0, PHOTO_WIDTH, PHOTO_HEIGHT)
    return canvas.current.toDataURL('image/jpeg', PHOTO_QUALITY)
  }, [video])

  /**
   * Lee la posición actual de la cara.
   *
   * @returns La posición, o `null` si no hay ninguna cara.
   */
  const getFace = useCallback(() => face.current, [])

  return { active, waitingForPermission, cameraError, reflex: reflexFor(observation), toggle, capture, getFace }
}

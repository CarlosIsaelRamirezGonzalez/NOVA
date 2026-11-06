/** Componente que conecta la animación de Nova con React y el navegador. */

import { useEffect, useRef } from 'react'
import { describeBlend, type Activity, type EmotionBlend } from '../nova/emotions'
import { CANVAS_SIZE, createNovaState, flinch, poke, soothe, stepNova, showBack, startSpin } from '../nova/novaState'
import { PixelBuffer } from '../nova/pixelBuffer'
import { renderNova } from '../nova/renderNova'

// Ritmo de animación y calibración de la voz.
const FRAME_SECONDS = 1 / 30
const MAX_STEP_SECONDS = 0.1
const SILENCE = 0.012
const SENSITIVITY = 5.5
const POKE_SECONDS = 0.9
const POKE_BLEND: EmotionBlend = [{ name: 'surprised', intensity: 1 }]
// Al cargarla se sorprende y le divierte; se le pasa al soltarla.
const GRAB_BLEND: EmotionBlend = [
  { name: 'surprised', intensity: 0.6 },
  { name: 'happy', intensity: 0.7 },
]
// Movimiento mínimo para que cuente como arrastre y no como un clic.
const DRAG_THRESHOLD_PX = 4

/** Funciones de la app de escritorio para mover la ventana; en el navegador no existen. */
type DragBridge = {
  pauseWander?: (reason: string, paused: boolean) => void
  onPose?: (handler: (pose: string) => void) => () => void
  onTravel?: (handler: (vx: number, vy: number, headingX: number, headingY: number) => void) => () => void
  startDrag: (screenX: number, screenY: number) => void
  moveDrag: (screenX: number, screenY: number) => void
  endDrag: () => void
}
const dragBridge = (window as unknown as { novaDesktop?: DragBridge }).novaDesktop

/** Propiedades de {@link NovaSprite}. */
type Props = {
  blend: EmotionBlend
  activity: Activity
  lookAtInput: boolean
  calmCount: number
  photoCount: number
  interruptCount: number
  getFace: () => { x: number; y: number } | null
  getLevel: () => number
}

/**
 * Muestra a Nova en un lienzo y la mantiene animada.
 *
 * @param props - Mezcla de emociones, actividad, si mira al cuadro de texto, veces que se ha
 *   calmado, fotos tomadas, interrupciones, posición de tu cara y lectura del volumen.
 * @returns El lienzo del personaje.
 */
export function NovaSprite({
  blend,
  activity,
  lookAtInput,
  calmCount,
  photoCount,
  interruptCount,
  getFace,
  getLevel,
}: Props) {
  const box = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const latest = useRef({ blend, activity, lookAtInput, calmCount, photoCount, interruptCount, getFace })

  // Guarda las propiedades actuales para que el bucle las lea sin tener que reiniciarse.

  useEffect(() => {
    latest.current = { blend, activity, lookAtInput, calmCount, photoCount, interruptCount, getFace }
  })

  useEffect(() => {
    const element = canvas.current
    const container = box.current
    const context = element?.getContext('2d')
    if (!element || !container || !context) return

    // Prepara el lienzo y el estado de la animación.
    const buffer = new PixelBuffer(CANVAS_SIZE)
    const state = createNovaState()
    const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches
    let pointer: { x: number; y: number } | null = null
    let pokedUntil = 0
    let wasDancing = false
    let handledCalmCount = latest.current.calmCount
    let handledPhotoCount = latest.current.photoCount
    let handledInterruptCount = latest.current.interruptCount
    let frame = 0
    let last = performance.now()
    let pending = 0

    // Escala entera en píxeles físicos: cada píxel de Nova queda exactamente igual de grande.
    const fit = () => {
      const available = Math.min(container.clientWidth, container.clientHeight)
      const ratio = devicePixelRatio || 1
      const scale = Math.max(1, Math.floor((available * ratio) / CANVAS_SIZE))
      const size = (scale * CANVAS_SIZE) / ratio
      element.style.width = `${size}px`
      element.style.height = `${size}px`
    }
    const observer = new ResizeObserver(fit)
    observer.observe(container)
    fit()

    // Registra la posición del cursor en coordenadas del lienzo.
    const onPointerMove = (event: PointerEvent) => {
      const rect = element.getBoundingClientRect()
      pointer = {
        x: ((event.clientX - rect.left) / rect.width) * CANVAS_SIZE,
        y: ((event.clientY - rect.top) / rect.height) * CANVAS_SIZE,
      }
    }
    // Velocidad y estado del arrastre; en el navegador no hay ventana que mover.
    const grab = { held: false, vx: 0, vy: 0, heading: null as { x: number; y: number } | null }
    let press: { x: number; y: number; moved: boolean; lastX: number; lastY: number; lastAt: number } | null = null

    // Al tomarla, se sigue al cursor aunque la ventana se mueva debajo de él.
    const onPointerDown = (event: PointerEvent) => {
      element.setPointerCapture(event.pointerId)
      press = {
        x: event.screenX,
        y: event.screenY,
        moved: false,
        lastX: event.screenX,
        lastY: event.screenY,
        lastAt: performance.now(),
      }
      if (dragBridge) {
        dragBridge.startDrag(event.screenX, event.screenY)
        grab.held = true
        grab.heading = null
      }
    }

    // Mueve la ventana y calcula la velocidad, que anima el cuerpo.
    const onDragMove = (event: PointerEvent) => {
      if (!press || !dragBridge) return
      const now = performance.now()
      const seconds = Math.max((now - press.lastAt) / 1000, 0.001)
      grab.vx = (event.screenX - press.lastX) / seconds
      grab.vy = (event.screenY - press.lastY) / seconds
      press.lastX = event.screenX
      press.lastY = event.screenY
      press.lastAt = now
      press.moved ||= Math.hypot(event.screenX - press.x, event.screenY - press.y) > DRAG_THRESHOLD_PX
      dragBridge.moveDrag(event.screenX, event.screenY)
    }

    // Al soltarla termina el arrastre; si no se movió, fue un clic y solo se sorprende.
    const onPointerUp = () => {
      if (!press) return
      if (!press.moved) {
        pokedUntil = performance.now() + POKE_SECONDS * 1000
        poke(state)
      }
      press = null
      grab.held = false
      grab.vx = 0
      grab.vy = 0
      dragBridge?.endDrag()
    }
    // Cuando se mueve sola, la velocidad de la ventana anima el cuerpo igual que al cargarla.
    const stopTravel = dragBridge?.onTravel?.((vx, vy, headingX, headingY) => {
      if (grab.held) return
      grab.vx = vx
      grab.vy = vy
      grab.heading = headingX || headingY ? { x: headingX, y: headingY } : null
    })
    const stopPose = dragBridge?.onPose?.((pose) => {
      if (pose === 'spin') startSpin(state)
      if (pose === 'show_back') showBack(state)
    })
    addEventListener('pointermove', onPointerMove)
    element.addEventListener('pointerdown', onPointerDown)
    element.addEventListener('pointermove', onDragMove)
    element.addEventListener('pointerup', onPointerUp)
    element.addEventListener('pointercancel', onPointerUp)

    // Bucle principal: limita la animación a 30 FPS, simula y dibuja.
    const tick = (now: number) => {
      frame = requestAnimationFrame(tick)
      pending += Math.min(MAX_STEP_SECONDS, (now - last) / 1000)
      last = now
      if (pending < FRAME_SECONDS) return
      const dt = pending
      pending = 0

      const current = latest.current

      // Cada vez que se pulsa Calmar, lanza el efecto una sola vez.
      if (current.calmCount !== handledCalmCount) {
        handledCalmCount = current.calmCount
        soothe(state)
      }

      // Al tomar una foto da un pequeño brinco, como un destello de cámara.
      if (current.photoCount !== handledPhotoCount) {
        handledPhotoCount = current.photoCount
        poke(state)
      }

      // Al interrumpirla se sobresalta.
      if (current.interruptCount !== handledInterruptCount) {
        handledInterruptCount = current.interruptCount
        flinch(state)
      }

      // Con la cámara encendida mira tu cara; el video se invierte como un espejo.
      const face = current.getFace()
      const gazeTarget = face
        ? { x: (1 - face.x) * CANVAS_SIZE, y: face.y * CANVAS_SIZE }
        : pointer

      stepNova(state, {
        dt,
        blend: grab.held ? GRAB_BLEND : now < pokedUntil ? POKE_BLEND : current.blend,
        // Si el cursor se detiene, ya no llegan eventos: la velocidad se apaga sola.
        grab,
        // Con el ánimo real: la sorpresa de un clic o de cargarla no cuenta para bailar.
        excitement: Math.max(
          0,
          ...current.blend
            .filter((item) => item.name === 'happy' || item.name === 'surprised')
            .map((item) => item.intensity),
        ),
        activity: current.activity,
        level: Math.min(1, Math.max(0, (getLevel() - SILENCE) * SENSITIVITY)),
        pointer: gazeTarget,
        lookAtInput: current.lookAtInput,
        reducedMotion,
      })
      // Mientras baila no se va paseando.
      if ((state.dance >= 0) !== wasDancing) {
        wasDancing = state.dance >= 0
        dragBridge?.pauseWander?.('dance', wasDancing)
      }
      renderNova(buffer, state)

      // Sin movimientos nuevos, la velocidad cae a cero para que no se quede inclinada.
      grab.vx *= 0.8
      grab.vy *= 0.8

      // La luz del ambiente toma el color de lo que siente; cuanto más siente, más se nota.
      const [red, green, blue] = state.pose.ramp.mid.map(Math.round)
      const presence = 1 - state.feel.neutral
      const opacity = 0.07 + presence * 0.2 + state.level * 0.08
      container.style.background = `radial-gradient(closest-side, rgba(${red},${green},${blue},${opacity.toFixed(3)}), transparent)`
      context.putImageData(buffer.image, 0, 0)
    }
    frame = requestAnimationFrame(tick)

    // Detiene todo al desmontar el componente.
    return () => {
      cancelAnimationFrame(frame)
      observer.disconnect()
      stopTravel?.()
      stopPose?.()
      removeEventListener('pointermove', onPointerMove)
      element.removeEventListener('pointerdown', onPointerDown)
      element.removeEventListener('pointermove', onDragMove)
      element.removeEventListener('pointerup', onPointerUp)
      element.removeEventListener('pointercancel', onPointerUp)
    }
  }, [getLevel])

  return (
    <div ref={box} className="flex h-full w-full items-center justify-center">
      <canvas
        ref={canvas}
        width={CANVAS_SIZE}
        height={CANVAS_SIZE}
        role="img"
        aria-label={`Nova: ${describeBlend(blend).toLowerCase() || 'tranquila'}`}
        className={`[image-rendering:pixelated] ${dragBridge ? 'cursor-grab touch-none active:cursor-grabbing' : ''}`}
      />
    </div>
  )
}

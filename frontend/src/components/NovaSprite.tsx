/** Componente que conecta la animación de Nova con React y el navegador. */

import { useEffect, useRef } from 'react'
import { describeBlend, type Activity, type EmotionBlend } from '../nova/emotions'
import { CANVAS_SIZE, createNovaState, flinch, poke, soothe, stepNova } from '../nova/novaState'
import { PixelBuffer } from '../nova/pixelBuffer'
import { renderNova } from '../nova/renderNova'

// Ritmo de animación y calibración de la voz.
const FRAME_SECONDS = 1 / 30
const MAX_STEP_SECONDS = 0.1
const SILENCE = 0.012
const SENSITIVITY = 5.5
const POKE_SECONDS = 0.9
const POKE_BLEND: EmotionBlend = [{ name: 'surprised', intensity: 1 }]

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
    // Al hacerle clic, se sorprende durante un momento.
    const onPointerDown = () => {
      pokedUntil = performance.now() + POKE_SECONDS * 1000
      poke(state)
    }
    addEventListener('pointermove', onPointerMove)
    element.addEventListener('pointerdown', onPointerDown)

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
        blend: now < pokedUntil ? POKE_BLEND : current.blend,
        activity: current.activity,
        level: Math.min(1, Math.max(0, (getLevel() - SILENCE) * SENSITIVITY)),
        pointer: gazeTarget,
        lookAtInput: current.lookAtInput,
        reducedMotion,
      })
      renderNova(buffer, state)

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
      removeEventListener('pointermove', onPointerMove)
      element.removeEventListener('pointerdown', onPointerDown)
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
        className="[image-rendering:pixelated]"
      />
    </div>
  )
}

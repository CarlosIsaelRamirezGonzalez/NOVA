/** Vista del cerebro de Nova: sus recuerdos como neuronas en 3D que se encienden al recordarlos. */

import { useEffect, useMemo, useRef, useState } from 'react'
import type { Brain, BrainMemory, Recall } from '../hooks/useNova'
import { BrainScene, dominantEmotion, EMOTION_COLORS } from '../nova/brainScene'
import { describeBlend, type EmotionBlend } from '../nova/emotions'

/** Cuánto puede moverse el cursor en un clic; si se mueve más, fue un arrastre para girar. */
const CLICK_TOLERANCE_PX = 5

const KIND_LABELS: Record<BrainMemory['kind'], string> = {
  fact: 'Hecho',
  preference: 'Gusto',
  person: 'Persona',
  event: 'Suceso',
  plan: 'Plan',
  moment: 'Momento',
}

/** Propiedades de {@link BrainView}. */
type Props = {
  brain: Brain | null
  recall: Recall | null
  mood: EmotionBlend
  onForget: (memoryId: number) => void
  onClose: () => void
}

/**
 * Muestra la memoria de Nova a pantalla completa.
 *
 * @param props - Datos del cerebro, último recuerdo evocado, ánimo actual y acciones.
 * @returns La vista del cerebro.
 */
export function BrainView({ brain, recall, mood, onForget, onClose }: Props) {
  const stage = useRef<HTMLDivElement>(null)
  const labels = useRef<HTMLCanvasElement>(null)
  const scene = useRef<BrainScene | null>(null)
  const pressedAt = useRef<{ x: number; y: number } | null>(null)
  const [webglFailed, setWebglFailed] = useState(false)
  const [selected, setSelected] = useState<number | null>(null)
  const [hovered, setHovered] = useState<BrainMemory | null>(null)
  const [confirming, setConfirming] = useState<number | null>(null)

  const memories = useMemo(
    () => [...(brain?.memories ?? [])].sort((a, b) => b.created_at - a.created_at),
    [brain],
  )

  // Esc cierra esta vista, en lugar de interrumpir a Nova.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopImmediatePropagation()
        onClose()
      }
    }
    addEventListener('keydown', onKeyDown, true)
    return () => removeEventListener('keydown', onKeyDown, true)
  }, [onClose])

  // Crea la escena 3D al abrir la vista y la libera al cerrarla.
  useEffect(() => {
    if (!stage.current || !labels.current) return
    try {
      scene.current = new BrainScene(stage.current, labels.current)
    } catch {
      // Sin WebGL (aceleración gráfica apagada, por ejemplo) la lista sigue funcionando.
      setWebglFailed(true)
      return
    }
    return () => {
      scene.current?.dispose()
      scene.current = null
    }
  }, [])

  // Le pasa a la escena los datos conforme cambian.
  useEffect(() => {
    if (brain) scene.current?.setBrain(brain)
  }, [brain])
  useEffect(() => {
    scene.current?.setRecall(recall)
  }, [recall])
  useEffect(() => {
    scene.current?.setSelected(selected)
  }, [selected])

  const feeling = describeBlend(mood)

  return (
    <section
      aria-label="Cerebro de Nova"
      className="fixed inset-0 z-10 flex flex-col bg-night md:flex-row"
    >
      {/* Neuronas en 3D; los textos van en un lienzo aparte, encima y sin recibir el cursor */}
      <div className="relative min-h-[45dvh] flex-1 overflow-hidden">
        <div
          ref={stage}
          role="img"
          aria-label={`Red de ${memories.length} neuronas: cada una es un recuerdo y se conectan por significado`}
          className={`absolute inset-0 ${hovered ? 'cursor-pointer' : 'cursor-grab active:cursor-grabbing'}`}
          onPointerDown={(event) => {
            pressedAt.current = { x: event.clientX, y: event.clientY }
          }}
          onPointerMove={(event) => {
            // Mientras se arrastra no se busca nada: la cámara es la que se mueve.
            if (event.buttons !== 0) return
            const memory = scene.current?.pick(event.clientX, event.clientY)
            scene.current?.setHovered(memory?.id ?? null)
            setHovered(memory ?? null)
          }}
          onPointerLeave={() => {
            scene.current?.setHovered(null)
            setHovered(null)
          }}
          onClick={(event) => {
            // Un arrastre para girar termina también en clic: ese no selecciona.
            const pressed = pressedAt.current
            if (pressed && Math.hypot(event.clientX - pressed.x, event.clientY - pressed.y) > CLICK_TOLERANCE_PX) return
            setSelected(scene.current?.pick(event.clientX, event.clientY)?.id ?? null)
            setConfirming(null)
          }}
        />
        <canvas ref={labels} aria-hidden className="pointer-events-none absolute inset-0 h-full w-full" />

        <header className="pointer-events-none absolute top-4 left-4">
          <h1 className="font-pixel text-2xl">Cerebro de Nova</h1>
          <p className="text-sm text-muted">
            {memories.length} recuerdos · Siente: {feeling ? feeling.toLowerCase() : 'calma'}
          </p>
          <p className="text-xs text-muted">Arrastra para girar · Rueda para acercar</p>
        </header>

        {/* El recuerdo bajo el cursor */}
        {hovered && (
          <p className="pointer-events-none absolute right-4 bottom-4 left-4 rounded-lg border border-line bg-panel px-3 py-2 text-sm">
            {hovered.content}
          </p>
        )}

        {memories.length === 0 && brain && !webglFailed && (
          <p className="pointer-events-none absolute inset-x-0 bottom-8 px-8 text-center text-muted">
            Todavía no tiene recuerdos. Cuéntale algo de ti y aparecerán aquí.
          </p>
        )}

        {webglFailed && (
          <p className="absolute inset-0 flex items-center justify-center px-8 text-center text-muted">
            Tu navegador no pudo iniciar la vista 3D. La lista de recuerdos sigue funcionando.
          </p>
        )}
      </div>

      {/* Lista de recuerdos, del más reciente al más antiguo */}
      <aside className="flex max-h-[55dvh] w-full flex-col border-t border-line md:max-h-none md:w-96 md:border-t-0 md:border-l">
        <div className="flex items-center justify-between gap-3 p-4">
          <h2 className="font-pixel text-lg">Recuerdos</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full border border-line px-3 py-1 font-pixel text-sm outline-none hover:bg-panel focus-visible:border-glow"
          >
            Cerrar
          </button>
        </div>

        <ul className="min-h-0 flex-1 space-y-2 overflow-y-auto px-4 pb-4">
          {memories.map((memory) => {
            const lit = Boolean(recall?.ids.includes(memory.id))
            return (
              <li
                key={memory.id}
                className={`rounded-lg border p-3 ${
                  memory.id === selected ? 'border-cream' : lit ? 'border-glow' : 'border-line'
                }`}
              >
                <button
                  type="button"
                  onClick={() => {
                    setSelected(memory.id)
                    setConfirming(null)
                  }}
                  className="block w-full text-left text-sm outline-none focus-visible:underline"
                >
                  {memory.content}
                </button>

                <div className="mt-2 flex items-center justify-between gap-2 text-xs text-muted">
                  <span className="flex items-center gap-2">
                    <span
                      className="size-2 rounded-full"
                      style={{ background: EMOTION_COLORS[dominantEmotion(memory)] }}
                      aria-hidden
                    />
                    {KIND_LABELS[memory.kind]}
                    {memory.emotions.components.length > 0 && ` · ${describeBlend(memory.emotions.components)}`}
                  </span>

                  {/* Borrar pide confirmación porque no se puede deshacer */}
                  {confirming === memory.id ? (
                    <button
                      type="button"
                      onClick={() => {
                        onForget(memory.id)
                        setConfirming(null)
                      }}
                      className="shrink-0 rounded-full bg-alert px-2 py-0.5 font-semibold text-night outline-none focus-visible:ring-2 focus-visible:ring-cream"
                    >
                      ¿Borrar para siempre?
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setConfirming(memory.id)}
                      className="shrink-0 rounded-full border border-line px-2 py-0.5 outline-none hover:bg-panel focus-visible:border-glow"
                    >
                      Olvidar
                    </button>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      </aside>
    </section>
  )
}

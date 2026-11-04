/** Vista del cerebro de Nova: sus recuerdos como un grafo que se ilumina cuando los recuerda. */

import { useEffect, useMemo, useRef, useState } from 'react'
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from 'd3-force'
import type { Brain, BrainMemory, Recall } from '../hooks/useNova'
import { describeBlend, type Emotion, type EmotionBlend } from '../nova/emotions'

/** Cuánto dura encendido un recuerdo después de que Nova lo usa. */
const RECALL_GLOW_MS = 8000
const BASE_RADIUS = 6
const IMPORTANCE_RADIUS = 11
const LABEL_CHARS = 26

/** Color de cada emoción, el mismo tono de las llamas de Nova. */
const EMOTION_COLORS: Record<Emotion, string> = {
  neutral: '#8ba0ff',
  happy: '#ffd66b',
  sad: '#5b7fc2',
  angry: '#f0512d',
  surprised: '#cfeaff',
  curious: '#58b8ff',
  afraid: '#a7b4e8',
  worried: '#5a92b8',
  stressed: '#e8a94a',
  frustrated: '#d2763c',
}

const KIND_LABELS: Record<BrainMemory['kind'], string> = {
  fact: 'Hecho',
  preference: 'Gusto',
  person: 'Persona',
  event: 'Suceso',
  plan: 'Plan',
  moment: 'Momento',
}

/** Un recuerdo con su posición en la simulación. */
type Node = SimulationNodeDatum & { memory: BrainMemory; radius: number }
/** Una conexión entre dos recuerdos. */
type Link = SimulationLinkDatum<Node> & { strength: number }

/** Propiedades de {@link BrainView}. */
type Props = {
  brain: Brain | null
  recall: Recall | null
  mood: EmotionBlend
  onForget: (memoryId: number) => void
  onClose: () => void
}

/**
 * Busca la emoción más fuerte de un recuerdo, que define su color.
 *
 * @param memory - Recuerdo.
 * @returns La emoción dominante; `neutral` si Nova estaba en calma.
 */
function dominantEmotion(memory: BrainMemory): Emotion {
  return [...memory.emotions.components].sort((a, b) => b.intensity - a.intensity)[0]?.name ?? 'neutral'
}

/**
 * Muestra la memoria de Nova a pantalla completa.
 *
 * @param props - Datos del cerebro, último recuerdo evocado, ánimo actual y acciones.
 * @returns La vista del cerebro.
 */
export function BrainView({ brain, recall, mood, onForget, onClose }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const nodes = useRef<Node[]>([])
  const links = useRef<Link[]>([])
  const simulation = useRef<Simulation<Node, Link> | null>(null)
  const latestRecall = useRef(recall)
  const selectedId = useRef<number | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [hovered, setHovered] = useState<BrainMemory | null>(null)
  const [confirming, setConfirming] = useState<number | null>(null)

  const memories = useMemo(
    () => [...(brain?.memories ?? [])].sort((a, b) => b.created_at - a.created_at),
    [brain],
  )

  // Guarda los valores actuales para que el dibujo los lea sin reiniciarse.
  useEffect(() => {
    latestRecall.current = recall
    selectedId.current = selected
  })

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

  // Reconstruye el grafo si cambian los recuerdos, conservando dónde estaba cada nodo.
  useEffect(() => {
    if (!brain || !box.current) return
    const { clientWidth: width, clientHeight: height } = box.current
    const previous = new Map(nodes.current.map((node) => [node.memory.id, node]))

    nodes.current = brain.memories.map((memory) => ({
      memory,
      radius: BASE_RADIUS + memory.importance * IMPORTANCE_RADIUS,
      x: previous.get(memory.id)?.x ?? width / 2 + Math.random() * 60 - 30,
      y: previous.get(memory.id)?.y ?? height / 2 + Math.random() * 60 - 30,
    }))
    links.current = brain.links.map((link) => ({
      source: link.source,
      target: link.target,
      strength: link.strength,
    }))

    // Los recuerdos se repelen; los parecidos se atraen y forman grupos.
    simulation.current?.stop()
    const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches
    simulation.current = forceSimulation<Node, Link>(nodes.current)
      .force(
        'link',
        forceLink<Node, Link>(links.current)
          .id((node) => node.memory.id)
          .distance((link) => 240 - link.strength * 130)
          .strength((link) => link.strength * 0.6),
      )
      .force('charge', forceManyBody().strength(-520))
      .force('center', forceCenter(width / 2, height / 2))
      .force('collide', forceCollide<Node>((node) => node.radius + 34))
    if (reducedMotion) {
      simulation.current.stop().tick(200)
    }
    return () => {
      simulation.current?.stop()
    }
  }, [brain])

  // Dibuja el grafo en cada cuadro.
  useEffect(() => {
    const element = canvas.current
    const container = box.current
    const context = element?.getContext('2d')
    if (!element || !container || !context) return

    // El lienzo sigue el tamaño de su contenedor, en píxeles físicos para que no se vea borroso.
    const fit = () => {
      const ratio = devicePixelRatio || 1
      element.width = container.clientWidth * ratio
      element.height = container.clientHeight * ratio
      context.setTransform(ratio, 0, 0, ratio, 0, 0)
      simulation.current?.force('center', forceCenter(container.clientWidth / 2, container.clientHeight / 2))
      simulation.current?.alpha(0.3).restart()
    }
    const observer = new ResizeObserver(fit)
    observer.observe(container)
    fit()

    let frame = 0
    const draw = (now: number) => {
      frame = requestAnimationFrame(draw)
      context.clearRect(0, 0, container.clientWidth, container.clientHeight)

      // Calcula qué tan encendido sigue lo último que recordó Nova.
      const current = latestRecall.current
      const glow = current ? Math.max(0, 1 - (now - current.at) / RECALL_GLOW_MS) : 0
      const isLit = (node: Node) => glow > 0 && Boolean(current?.ids.includes(node.memory.id))

      // Conexiones: se iluminan si unen dos recuerdos evocados.
      for (const link of links.current) {
        const source = link.source as Node
        const target = link.target as Node
        const lit = isLit(source) && isLit(target)
        context.strokeStyle = lit ? `rgba(255,230,181,${0.25 + glow * 0.6})` : `rgba(139,160,255,${0.2 + link.strength * 0.6})`
        context.lineWidth = lit ? 2 : 1
        context.beginPath()
        context.moveTo(source.x ?? 0, source.y ?? 0)
        context.lineTo(target.x ?? 0, target.y ?? 0)
        context.stroke()
      }

      // Recuerdos.
      for (const node of nodes.current) {
        const color = EMOTION_COLORS[dominantEmotion(node.memory)]
        const x = node.x ?? 0
        const y = node.y ?? 0

        // Halo pulsante mientras está encendido.
        if (isLit(node)) {
          const pulse = 1 + Math.sin(now / 180) * 0.15
          context.globalAlpha = glow * 0.35
          context.fillStyle = color
          context.beginPath()
          context.arc(x, y, (node.radius + 16) * pulse, 0, Math.PI * 2)
          context.fill()
        }

        context.globalAlpha = 1
        context.fillStyle = color
        context.beginPath()
        context.arc(x, y, node.radius, 0, Math.PI * 2)
        context.fill()

        // Etiqueta corta, para reconocer el recuerdo sin pasar el cursor.
        const text = node.memory.content
        context.font = '11px ui-sans-serif, system-ui, sans-serif'
        context.textAlign = 'center'
        context.fillStyle = isLit(node) ? '#f1f1ff' : '#aaaee0'
        context.fillText(
          text.length > LABEL_CHARS ? `${text.slice(0, LABEL_CHARS)}…` : text,
          x,
          y + node.radius + 14,
        )

        if (node.memory.id === selectedId.current) {
          context.strokeStyle = '#f1f1ff'
          context.lineWidth = 2
          context.beginPath()
          context.arc(x, y, node.radius + 4, 0, Math.PI * 2)
          context.stroke()
        }
      }
    }
    frame = requestAnimationFrame(draw)

    return () => {
      cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [])

  /**
   * Busca qué recuerdo está bajo el cursor.
   *
   * @param clientX - Columna del cursor en la ventana.
   * @param clientY - Fila del cursor en la ventana.
   * @returns El nodo encontrado, si hay alguno.
   */
  const nodeAt = (clientX: number, clientY: number) => {
    const rect = canvas.current?.getBoundingClientRect()
    if (!rect) return undefined
    return nodes.current.find(
      (node) =>
        Math.hypot((node.x ?? 0) - (clientX - rect.left), (node.y ?? 0) - (clientY - rect.top)) <=
        node.radius + 3,
    )
  }

  const feeling = describeBlend(mood)

  return (
    <section
      aria-label="Cerebro de Nova"
      className="fixed inset-0 z-10 flex flex-col bg-night md:flex-row"
    >
      {/* Grafo de recuerdos */}
      <div ref={box} className="relative min-h-[45dvh] flex-1 overflow-hidden">
        <canvas
          ref={canvas}
          role="img"
          aria-label={`Grafo con ${memories.length} recuerdos conectados por significado`}
          className="absolute inset-0 h-full w-full cursor-pointer"
          onPointerMove={(event) => setHovered(nodeAt(event.clientX, event.clientY)?.memory ?? null)}
          onPointerLeave={() => setHovered(null)}
          onClick={(event) => {
            const memory = nodeAt(event.clientX, event.clientY)?.memory
            setSelected(memory?.id ?? null)
            setConfirming(null)
          }}
        />

        <header className="pointer-events-none absolute top-4 left-4">
          <h1 className="font-pixel text-2xl">Cerebro de Nova</h1>
          <p className="text-sm text-muted">
            {memories.length} recuerdos · Siente: {feeling ? feeling.toLowerCase() : 'calma'}
          </p>
        </header>

        {/* El recuerdo bajo el cursor */}
        {hovered && (
          <p className="pointer-events-none absolute right-4 bottom-4 left-4 rounded-lg border border-line bg-panel px-3 py-2 text-sm">
            {hovered.content}
          </p>
        )}

        {memories.length === 0 && brain && (
          <p className="absolute inset-0 flex items-center justify-center px-8 text-center text-muted">
            Todavía no tiene recuerdos. Cuéntale algo de ti y aparecerán aquí.
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

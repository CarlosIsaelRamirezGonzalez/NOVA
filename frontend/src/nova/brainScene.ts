/** Escena 3D del cerebro de Nova: cada recuerdo es una neurona y cada parecido, un axón. */

import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  forceZ,
  type ForceLink,
  type ForceNode,
} from 'd3-force-3d'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js'
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js'
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js'
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js'
import { mergeGeometries, mergeVertices } from 'three/addons/utils/BufferGeometryUtils.js'
import type { Brain, BrainMemory, Recall } from '../hooks/useNova'
import type { Emotion } from './emotions'

/** Cuánto dura encendido un recuerdo después de que Nova lo usa. */
const RECALL_GLOW_MS = 8000
/** Cada cuánto dispara una neurona encendida. */
const RECALL_SPIKE_MS = 320
/** Cada cuánto hay un impulso espontáneo, para que el cerebro se vea vivo. */
const AMBIENT_SPIKE_MS = 420
/** Cuánto tarda en crecer una neurona o un axón nuevo. */
const GROWTH_MS = 1100

const SOMA_RADIUS = 3
const IMPORTANCE_RADIUS = 4.5
const LABEL_CHARS = 26
/** Hasta cuántas neuronas se muestran todos los textos, sin importar qué tan lejos estén. */
const FEW_NEURONS = 12
const MAX_SPIKES = 128
const NIGHT_COLOR = '#060820'
const TISSUE_COLOR = '#8ba0ff'
const TISSUE_NEURONS = 260
const TISSUE_MIN_RADIUS = 120

/** Color de cada emoción, el mismo tono de las llamas de Nova. */
export const EMOTION_COLORS: Record<Emotion, string> = {
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

/** Posición de una neurona en la simulación de fuerzas. */
type LayoutNode = ForceNode & { id: number; radius: number }
/** Conexión de la simulación de fuerzas. */
type LayoutLink = ForceLink<LayoutNode> & { strength: number }

/** Una neurona dibujada: un recuerdo con su cuerpo y sus dendritas. */
type Neuron = {
  memory: BrainMemory
  appearance: string
  layout: LayoutNode
  radius: number
  born: number
  group: THREE.Group
  soma: THREE.Mesh<THREE.BufferGeometry, THREE.MeshStandardMaterial>
  dendrites: THREE.Mesh<THREE.BufferGeometry, THREE.MeshStandardMaterial>
}

/** Un axón dibujado: une dos neuronas con un tubo curvo. */
type Axon = {
  source: number
  target: number
  strength: number
  born: number
  curve: THREE.Curve<THREE.Vector3>
  mesh: THREE.Mesh<THREE.TubeGeometry, THREE.MeshBasicMaterial>
}

/** Un impulso eléctrico que viaja por un axón o por el tejido de fondo. */
type Spike = {
  curve: THREE.Curve<THREE.Vector3>
  progress: number
  speed: number
  size: number
}

/**
 * Crea un generador de números aleatorios repetible, para que cada recuerdo
 * conserve la misma forma cada vez que se abre el cerebro.
 *
 * @param seed - Semilla.
 * @returns Función que devuelve un número entre 0 y 1.
 */
function seededRandom(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state = (state + 0x6d2b79f5) >>> 0
    let mixed = Math.imul(state ^ (state >>> 15), 1 | state)
    mixed = (mixed + Math.imul(mixed ^ (mixed >>> 7), 61 | mixed)) ^ mixed
    return ((mixed ^ (mixed >>> 14)) >>> 0) / 4294967296
  }
}

/**
 * Crea una dirección al azar.
 *
 * @param random - Generador de números aleatorios.
 * @returns Vector de longitud 1.
 */
function randomDirection(random: () => number): THREE.Vector3 {
  const z = random() * 2 - 1
  const angle = random() * Math.PI * 2
  const ring = Math.sqrt(1 - z * z)
  return new THREE.Vector3(ring * Math.cos(angle), ring * Math.sin(angle), z)
}

/**
 * Busca la emoción más fuerte de un recuerdo, que define su color.
 *
 * @param memory - Recuerdo.
 * @returns La emoción dominante; `neutral` si Nova estaba en calma.
 */
export function dominantEmotion(memory: BrainMemory): Emotion {
  return [...memory.emotions.components].sort((a, b) => b.intensity - a.intensity)[0]?.name ?? 'neutral'
}

/**
 * Modela el cuerpo de una neurona: una esfera irregular, no una bola perfecta.
 *
 * @param random - Generador de números aleatorios.
 * @returns La geometría, de radio aproximado 1.
 */
function buildSomaGeometry(random: () => number): THREE.BufferGeometry {
  // Une los vértices repetidos: así la superficie se ve suave y no se abre al deformarla.
  const sphere = new THREE.IcosahedronGeometry(1, 4)
  sphere.deleteAttribute('normal')
  sphere.deleteAttribute('uv')
  const geometry = mergeVertices(sphere)
  sphere.dispose()

  // Deforma la esfera con ondas suaves, distintas en cada neurona.
  const phase = random() * 100
  const stretch = new THREE.Vector3(0.85 + random() * 0.35, 0.85 + random() * 0.35, 0.85 + random() * 0.35)
  const positions = geometry.getAttribute('position')
  const vertex = new THREE.Vector3()
  for (let index = 0; index < positions.count; index += 1) {
    vertex.fromBufferAttribute(positions, index)
    const wave =
      Math.sin(vertex.x * 3.1 + phase) * Math.sin(vertex.y * 2.7 + phase) * Math.sin(vertex.z * 3.3 + phase)
    vertex.multiplyScalar(1 + wave * 0.22).multiply(stretch)
    positions.setXYZ(index, vertex.x, vertex.y, vertex.z)
  }
  geometry.computeVertexNormals()
  return geometry
}

/**
 * Hace crecer una dendrita y sus ramas.
 *
 * @param start - Dónde nace.
 * @param direction - Hacia dónde crece.
 * @param length - Longitud de este tramo.
 * @param thickness - Grosor de este tramo.
 * @param depth - Cuántos niveles de ramas faltan.
 * @param random - Generador de números aleatorios.
 * @param parts - Lista donde se acumulan los tramos.
 */
function growDendrite(
  start: THREE.Vector3,
  direction: THREE.Vector3,
  length: number,
  thickness: number,
  depth: number,
  random: () => number,
  parts: THREE.BufferGeometry[],
): void {
  // Traza un tramo ondulado: cada punto se desvía un poco de la línea recta.
  const points = [start.clone()]
  const heading = direction.clone()
  for (let step = 0; step < 3; step += 1) {
    heading.addScaledVector(randomDirection(random), 0.32).normalize()
    points.push(points[step].clone().addScaledVector(heading, length / 3))
  }
  parts.push(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points), 7, thickness, 5, false))
  if (depth === 0) return

  // Se divide en dos ramas más cortas y delgadas.
  const tip = points[points.length - 1]
  for (let branch = 0; branch < 2; branch += 1) {
    const branchDirection = heading.clone().addScaledVector(randomDirection(random), 0.65).normalize()
    growDendrite(tip, branchDirection, length * 0.68, thickness * 0.62, depth - 1, random, parts)
  }
}

/**
 * Modela todas las dendritas de una neurona en una sola geometría.
 *
 * @param radius - Radio del cuerpo de la neurona.
 * @param random - Generador de números aleatorios.
 * @returns La geometría de las dendritas.
 */
function buildDendritesGeometry(radius: number, random: () => number): THREE.BufferGeometry {
  const parts: THREE.BufferGeometry[] = []
  const count = 5 + Math.floor(random() * 3)
  for (let index = 0; index < count; index += 1) {
    const direction = randomDirection(random)
    const start = direction.clone().multiplyScalar(radius * 0.8)
    growDendrite(start, direction, radius * 2.1, radius * 0.11, 2, random, parts)
  }
  const merged = mergeGeometries(parts)
  for (const part of parts) part.dispose()
  return merged
}

/**
 * Crea la textura redonda y difusa de los puntos del tejido de fondo.
 *
 * @returns La textura.
 */
function buildDotTexture(): THREE.CanvasTexture {
  const canvas = document.createElement('canvas')
  canvas.width = 64
  canvas.height = 64
  const context = canvas.getContext('2d')
  if (context) {
    const gradient = context.createRadialGradient(32, 32, 0, 32, 32, 32)
    gradient.addColorStop(0, 'rgba(255,255,255,1)')
    gradient.addColorStop(0.35, 'rgba(255,255,255,0.55)')
    gradient.addColorStop(1, 'rgba(255,255,255,0)')
    context.fillStyle = gradient
    context.fillRect(0, 0, 64, 64)
  }
  return new THREE.CanvasTexture(canvas)
}

/**
 * Reparte puntos en la silueta de un cerebro: dos hemisferios con un surco al centro.
 *
 * @param count - Cuántos puntos crear.
 * @param random - Generador de números aleatorios.
 * @returns Los puntos, dentro de una esfera de radio cercano a 1.
 */
function buildTissuePoints(count: number, random: () => number): THREE.Vector3[] {
  const points: THREE.Vector3[] = []
  while (points.length < count) {
    // Toma un punto dentro de un cubo y lo acepta si cae en alguno de los hemisferios.
    const point = new THREE.Vector3(random() * 2 - 1, random() * 2 - 1, random() * 2 - 1)
    const side = point.x >= 0 ? 0.42 : -0.42
    const inside =
      ((point.x - side) / 0.56) ** 2 + (point.y / 0.72) ** 2 + (point.z / 0.92) ** 2 <= 1
    if (inside && Math.abs(point.x) > 0.04) points.push(point)
  }
  return points
}

/**
 * Une cada punto del tejido con sus vecinos más cercanos.
 *
 * @param points - Puntos del tejido.
 * @param neighbors - Cuántos vecinos conectar con cada punto.
 * @returns Pares de índices de los puntos conectados.
 */
function connectTissue(points: THREE.Vector3[], neighbors: number): [number, number][] {
  const edges = new Set<string>()
  points.forEach((point, index) => {
    const closest = points
      .map((other, otherIndex) => ({ otherIndex, distance: point.distanceToSquared(other) }))
      .filter(({ otherIndex }) => otherIndex !== index)
      .sort((a, b) => a.distance - b.distance)
      .slice(0, neighbors)
    for (const { otherIndex } of closest) {
      edges.add(`${Math.min(index, otherIndex)}:${Math.max(index, otherIndex)}`)
    }
  })
  return [...edges].map((edge) => {
    const [first, second] = edge.split(':').map(Number)
    return [first, second]
  })
}

/** Dibuja y anima las neuronas; la interfaz solo le pasa datos y le pregunta qué hay bajo el cursor. */
export class BrainScene {
  private readonly stage: HTMLElement
  private readonly labels: HTMLCanvasElement
  private readonly labelContext: CanvasRenderingContext2D | null
  private readonly renderer: THREE.WebGLRenderer
  private readonly composer: EffectComposer
  private readonly scene = new THREE.Scene()
  private readonly camera = new THREE.PerspectiveCamera(50, 1, 1, 6000)
  private readonly controls: OrbitControls
  private readonly observer: ResizeObserver
  private readonly reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches

  private readonly neurons = new Map<number, Neuron>()
  private readonly axons = new Map<string, Axon>()
  private readonly brainGroup = new THREE.Group()

  private readonly tissue = new THREE.Group()
  private readonly tissuePoints: THREE.Vector3[]
  private readonly tissueEdges: [number, number][]
  private readonly dotTexture = buildDotTexture()
  private tissueRadius = TISSUE_MIN_RADIUS

  private readonly spikes: (Spike | null)[] = new Array<Spike | null>(MAX_SPIKES).fill(null)
  private readonly spikeMesh: THREE.InstancedMesh

  private readonly selectionRing: THREE.Mesh<THREE.RingGeometry, THREE.MeshBasicMaterial>

  private recall: Recall | null = null
  private selectedId: number | null = null
  private hoveredId: number | null = null
  private dragging = false
  private fitting = true
  private frame = 0
  private lastFrame = performance.now()
  private lastRecallSpike = 0
  private lastAmbientSpike = 0
  private readonly ambientRandom = seededRandom(7)

  /**
   * Prepara la escena y empieza a dibujar.
   *
   * @param stage - Elemento donde se coloca el lienzo 3D.
   * @param labels - Lienzo transparente para los textos, encima del 3D.
   * @throws Error si el navegador no puede iniciar WebGL.
   */
  constructor(stage: HTMLElement, labels: HTMLCanvasElement) {
    this.stage = stage
    this.labels = labels
    this.labelContext = labels.getContext('2d')

    // Motor de dibujo: colores de alto rango para que el brillo de los impulsos se desborde.
    this.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' })
    this.renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2))
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping
    this.renderer.domElement.className = 'absolute inset-0 h-full w-full'
    stage.prepend(this.renderer.domElement)

    // Fondo y niebla: lo lejano se pierde en la oscuridad y da sensación de profundidad.
    this.scene.background = new THREE.Color(NIGHT_COLOR)
    this.scene.fog = new THREE.FogExp2(NIGHT_COLOR, 0.0016)
    this.scene.add(new THREE.AmbientLight('#7f8cff', 0.7))
    const light = new THREE.PointLight('#dfe4ff', 1.1, 0, 0)
    this.camera.add(light)
    this.scene.add(this.camera, this.brainGroup, this.tissue)

    // Posprocesado: el brillo difuso que hace que las neuronas parezcan encendidas.
    const target = new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType, samples: 4 })
    this.composer = new EffectComposer(this.renderer, target)
    this.composer.addPass(new RenderPass(this.scene, this.camera))
    this.composer.addPass(new UnrealBloomPass(new THREE.Vector2(1, 1), 0.5, 0.5, 0.55))
    this.composer.addPass(new OutputPass())

    // Cámara: se gira arrastrando, se acerca con la rueda y da vueltas sola cuando nadie la toca.
    this.camera.position.set(0, 40, 420)
    this.controls = new OrbitControls(this.camera, this.renderer.domElement)
    this.controls.enablePan = false
    this.controls.enableDamping = !this.reducedMotion
    this.controls.dampingFactor = 0.07
    this.controls.autoRotateSpeed = 0.45
    this.controls.minDistance = 25
    this.controls.addEventListener('start', this.handleControlStart)
    this.controls.addEventListener('end', this.handleControlEnd)

    // Tejido de fondo: neuronas decorativas que dan forma al cerebro aunque no haya recuerdos.
    const tissueRandom = seededRandom(20251104)
    this.tissuePoints = buildTissuePoints(TISSUE_NEURONS, tissueRandom)
    this.tissueEdges = connectTissue(this.tissuePoints, 3)
    this.buildTissue()

    // Impulsos eléctricos: una sola malla con muchas copias, mucho más ligera que una por impulso.
    this.spikeMesh = new THREE.InstancedMesh(
      new THREE.SphereGeometry(1, 12, 10),
      new THREE.MeshBasicMaterial({ color: new THREE.Color(5, 5, 5) }),
      MAX_SPIKES,
    )
    this.spikeMesh.frustumCulled = false
    this.scene.add(this.spikeMesh)
    this.hideSpikes()

    // Anillo que marca la neurona elegida.
    this.selectionRing = new THREE.Mesh(
      new THREE.RingGeometry(1.5, 1.68, 64),
      new THREE.MeshBasicMaterial({ color: '#f1f1ff', side: THREE.DoubleSide, transparent: true, opacity: 0.9 }),
    )
    this.selectionRing.visible = false
    this.scene.add(this.selectionRing)

    // El dibujo sigue el tamaño de su contenedor.
    this.observer = new ResizeObserver(this.resize)
    this.observer.observe(stage)
    this.resize()

    this.frame = requestAnimationFrame(this.draw)
  }

  /**
   * Actualiza las neuronas y los axones con los recuerdos actuales. Solo toca lo que
   * cambió: las neuronas existentes no se mueven, y las nuevas crecen en su lugar.
   *
   * @param brain - Recuerdos y conexiones enviados por el servidor.
   */
  setBrain(brain: Brain): void {
    const now = performance.now()

    // Retira lo olvidado y lo que ya no existe.
    const memoryIds = new Set(brain.memories.map((memory) => memory.id))
    for (const [id, neuron] of this.neurons) {
      if (!memoryIds.has(id)) this.removeNeuron(id, neuron)
    }

    // Crea las neuronas nuevas y actualiza las que cambiaron de color o tamaño.
    const added: Neuron[] = []
    brain.memories.forEach((memory, index) => {
      const existing = this.neurons.get(memory.id)
      const appearance = `${dominantEmotion(memory)}:${memory.importance}`
      if (existing?.appearance === appearance) {
        existing.memory = memory
        return
      }
      if (existing) this.removeNeuron(memory.id, existing)
      const neuron = this.createNeuron(memory, appearance, existing, now + Math.min(index * 45, 900))
      this.neurons.set(memory.id, neuron)
      if (!existing) added.push(neuron)
    })

    // Conserva solo las conexiones cuyas dos neuronas existen, sin repetir pares.
    const links = new Map<string, Brain['links'][number]>()
    for (const link of brain.links) {
      if (this.neurons.has(link.source) && this.neurons.has(link.target)) {
        links.set(this.axonKey(link.source, link.target), link)
      }
    }

    this.placeNewNeurons(added, [...links.values()])

    // Quita los axones que ya no existen y hace crecer los nuevos, después de sus neuronas.
    for (const [key, axon] of this.axons) {
      if (!links.has(key)) this.removeAxon(key, axon)
    }
    for (const [key, link] of links) {
      if (!this.axons.has(key)) this.axons.set(key, this.createAxon(link, now + GROWTH_MS * 0.5))
    }

    this.fitToBrain()
  }

  /**
   * Registra lo último que recordó Nova.
   *
   * @param recall - Recuerdos evocados y cuándo.
   */
  setRecall(recall: Recall | null): void {
    this.recall = recall
  }

  /**
   * Marca una neurona como elegida y lleva la cámara hacia ella.
   *
   * @param id - Identificador del recuerdo, o `null` para volver a la vista general.
   */
  setSelected(id: number | null): void {
    this.selectedId = id
  }

  /**
   * Marca la neurona bajo el cursor.
   *
   * @param id - Identificador del recuerdo, o `null` si no hay ninguno.
   */
  setHovered(id: number | null): void {
    this.hoveredId = id
  }

  /**
   * Busca qué recuerdo está bajo el cursor. Elige el más cercano en pantalla, con un
   * margen generoso, porque atinarle exacto a una neurona que gira sería frustrante.
   *
   * @param clientX - Columna del cursor en la ventana.
   * @param clientY - Fila del cursor en la ventana.
   * @returns El recuerdo encontrado, si hay alguno.
   */
  pick(clientX: number, clientY: number): BrainMemory | undefined {
    const rect = this.stage.getBoundingClientRect()
    let found: BrainMemory | undefined
    let bestDistance = Number.POSITIVE_INFINITY
    for (const neuron of this.neurons.values()) {
      const screen = this.toScreen(neuron)
      if (!screen) continue
      const distance = Math.hypot(screen.x - (clientX - rect.left), screen.y - (clientY - rect.top))
      if (distance <= Math.max(16, screen.radius + 8) && distance < bestDistance) {
        bestDistance = distance
        found = neuron.memory
      }
    }
    return found
  }

  /** Detiene la animación y libera toda la memoria de la tarjeta gráfica. */
  dispose(): void {
    cancelAnimationFrame(this.frame)
    this.observer.disconnect()
    this.controls.removeEventListener('start', this.handleControlStart)
    this.controls.removeEventListener('end', this.handleControlEnd)
    this.controls.dispose()

    // Recorre la escena liberando cada geometría y material.
    this.scene.traverse((object) => {
      if (object instanceof THREE.Mesh || object instanceof THREE.LineSegments || object instanceof THREE.Points) {
        object.geometry.dispose()
        const material = object.material as THREE.Material
        material.dispose()
      }
    })
    this.spikeMesh.dispose()
    this.dotTexture.dispose()
    this.composer.dispose()

    // Suelta el contexto de inmediato: el navegador solo permite unos pocos a la vez.
    this.renderer.dispose()
    this.renderer.forceContextLoss()
    this.renderer.domElement.remove()
  }

  /** Detiene el giro automático y el encuadre mientras se arrastra. */
  private readonly handleControlStart = () => {
    this.dragging = true
    this.fitting = false
  }

  /** Marca el final del arrastre. */
  private readonly handleControlEnd = () => {
    this.dragging = false
  }

  /** Ajusta el dibujo y la cámara al tamaño actual del contenedor. */
  private readonly resize = () => {
    const width = Math.max(1, this.stage.clientWidth)
    const height = Math.max(1, this.stage.clientHeight)
    const ratio = Math.min(devicePixelRatio || 1, 2)

    this.renderer.setSize(width, height, false)
    this.composer.setPixelRatio(ratio)
    this.composer.setSize(width, height)
    this.camera.aspect = width / height
    this.camera.updateProjectionMatrix()

    // Los textos se dibujan en píxeles físicos para que no se vean borrosos.
    this.labels.width = width * ratio
    this.labels.height = height * ratio
    this.labelContext?.setTransform(ratio, 0, 0, ratio, 0, 0)
  }

  /**
   * Devuelve la clave de un axón; es la misma sin importar el orden de sus extremos.
   *
   * @param first - Identificador de un recuerdo.
   * @param second - Identificador del otro recuerdo.
   * @returns La clave.
   */
  private axonKey(first: number, second: number): string {
    return `${Math.min(first, second)}-${Math.max(first, second)}`
  }

  /** Construye los puntos y las líneas del tejido de fondo. */
  private buildTissue(): void {
    const points = new THREE.Points(
      new THREE.BufferGeometry().setFromPoints(this.tissuePoints),
      new THREE.PointsMaterial({
        color: TISSUE_COLOR,
        map: this.dotTexture,
        size: 4.5,
        transparent: true,
        opacity: 0.55,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }),
    )

    const segments = this.tissueEdges.flatMap(([first, second]) => [
      this.tissuePoints[first],
      this.tissuePoints[second],
    ])
    const lines = new THREE.LineSegments(
      new THREE.BufferGeometry().setFromPoints(segments),
      new THREE.LineBasicMaterial({
        color: TISSUE_COLOR,
        transparent: true,
        opacity: 0.13,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }),
    )

    this.tissue.add(points, lines)
    this.tissue.scale.setScalar(this.tissueRadius)
  }

  /** Oculta todas las copias de los impulsos, reduciéndolas a tamaño cero. */
  private hideSpikes(): void {
    const hidden = new THREE.Matrix4().makeScale(0, 0, 0)
    for (let index = 0; index < MAX_SPIKES; index += 1) this.spikeMesh.setMatrixAt(index, hidden)
    this.spikeMesh.instanceMatrix.needsUpdate = true
  }

  /**
   * Crea una neurona.
   *
   * @param memory - Recuerdo que representa.
   * @param appearance - Clave de su color y tamaño.
   * @param replaced - Neurona a la que sustituye, para conservar su lugar.
   * @param born - Momento en que empieza a crecer.
   * @returns La neurona, ya añadida a la escena.
   */
  private createNeuron(memory: BrainMemory, appearance: string, replaced: Neuron | undefined, born: number): Neuron {
    const radius = SOMA_RADIUS + memory.importance * IMPORTANCE_RADIUS
    const random = seededRandom(memory.id * 2654435761)
    const color = new THREE.Color(EMOTION_COLORS[dominantEmotion(memory)])

    // Cuerpo brillante.
    const soma = new THREE.Mesh(
      buildSomaGeometry(random),
      new THREE.MeshStandardMaterial({
        color,
        emissive: color,
        emissiveIntensity: 0.42,
        roughness: 0.42,
        metalness: 0.05,
      }),
    )
    soma.scale.setScalar(radius)

    // Dendritas del mismo color, más apagadas.
    const dendrites = new THREE.Mesh(
      buildDendritesGeometry(radius, random),
      new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.22, roughness: 0.6 }),
    )

    const group = new THREE.Group()
    group.add(soma, dendrites)
    this.brainGroup.add(group)

    const layout: LayoutNode = replaced?.layout ?? { id: memory.id, radius }
    if (replaced) group.position.set(layout.x ?? 0, layout.y ?? 0, layout.z ?? 0)

    return { memory, appearance, layout, radius, born, group, soma, dendrites }
  }

  /**
   * Coloca las neuronas nuevas sin mover las que ya estaban, para que el cerebro
   * no se reacomode cada vez que Nova aprende algo.
   *
   * @param added - Neuronas sin posición todavía.
   * @param links - Conexiones vigentes.
   */
  private placeNewNeurons(added: Neuron[], links: Brain['links']): void {
    if (added.length === 0) return
    const newIds = new Set(added.map((neuron) => neuron.memory.id))
    const nodes: LayoutNode[] = []

    // Fija las antiguas en su lugar; las nuevas nacen cerca de un recuerdo parecido.
    for (const neuron of this.neurons.values()) {
      const node = neuron.layout
      if (!newIds.has(node.id)) {
        node.fx = node.x
        node.fy = node.y
        node.fz = node.z
      } else {
        const relative = links
          .filter((link) => link.source === node.id || link.target === node.id)
          .map((link) => this.neurons.get(link.source === node.id ? link.target : link.source))
          .find((other) => other && !newIds.has(other.memory.id))
        const random = seededRandom(node.id)
        node.x = (relative?.layout.x ?? 0) + (random() - 0.5) * 40
        node.y = (relative?.layout.y ?? 0) + (random() - 0.5) * 40
        node.z = (relative?.layout.z ?? 0) + (random() - 0.5) * 40
      }
      nodes.push(node)
    }

    // Los recuerdos se repelen, los parecidos se atraen, y todos se quedan cerca del centro.
    const layoutLinks: LayoutLink[] = links.map(({ source, target, strength }) => ({ source, target, strength }))
    forceSimulation(nodes, 3)
      .stop()
      .force(
        'link',
        forceLink<LayoutNode, LayoutLink>(layoutLinks)
          .id((node) => node.id)
          .distance((link) => 125 - link.strength * 70)
          .strength((link) => link.strength * 0.55),
      )
      .force('charge', forceManyBody().strength(-210))
      .force('collide', forceCollide<LayoutNode>((node) => node.radius * 3 + 12))
      .force('x', forceX(0).strength(0.045))
      .force('y', forceY(0).strength(0.06))
      .force('z', forceZ(0).strength(0.045))
      .tick(280)

    for (const neuron of added) {
      neuron.group.position.set(neuron.layout.x ?? 0, neuron.layout.y ?? 0, neuron.layout.z ?? 0)
    }
  }

  /**
   * Crea un axón curvo entre dos neuronas, con un degradado de la emoción de una a la de la otra.
   *
   * @param link - Conexión que representa.
   * @param born - Momento en que empieza a crecer.
   * @returns El axón, ya añadido a la escena.
   */
  private createAxon(link: Brain['links'][number], born: number): Axon {
    const source = this.neurons.get(link.source)
    const target = this.neurons.get(link.target)
    if (!source || !target) throw new Error('Axon without neuron')
    const start = source.group.position
    const end = target.group.position

    // Traza una curva que se desvía de la recta, con forma repetible para cada par.
    const random = seededRandom(link.source * 73856093 + link.target * 19349663)
    const reach = start.distanceTo(end)
    const bend = (at: number) =>
      start.clone().lerp(end, at).addScaledVector(randomDirection(random), reach * 0.13)
    const curve = new THREE.CatmullRomCurve3([start.clone(), bend(1 / 3), bend(2 / 3), end.clone()])

    // Los parecidos más fuertes se ven como axones más gruesos.
    const tubularSegments = 40
    const radialSegments = 6
    const geometry = new THREE.TubeGeometry(
      curve,
      tubularSegments,
      0.22 + link.strength * 0.5,
      radialSegments,
      false,
    )

    // Pinta cada anillo del tubo: empieza con el color de una neurona y acaba con el de la otra.
    const startColor = new THREE.Color(EMOTION_COLORS[dominantEmotion(source.memory)])
    const endColor = new THREE.Color(EMOTION_COLORS[dominantEmotion(target.memory)])
    const colors = new Float32Array(geometry.getAttribute('position').count * 3)
    const color = new THREE.Color()
    for (let ring = 0; ring <= tubularSegments; ring += 1) {
      color.lerpColors(startColor, endColor, ring / tubularSegments)
      for (let side = 0; side <= radialSegments; side += 1) {
        color.toArray(colors, (ring * (radialSegments + 1) + side) * 3)
      }
    }
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3))

    const material = new THREE.MeshBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.4 + link.strength * 0.4,
      depthWrite: false,
    })
    const mesh = new THREE.Mesh(geometry, material)
    this.brainGroup.add(mesh)

    return { source: link.source, target: link.target, strength: link.strength, born, curve, mesh }
  }

  /**
   * Quita una neurona de la escena y libera su memoria.
   *
   * @param id - Identificador del recuerdo.
   * @param neuron - Neurona a quitar.
   */
  private removeNeuron(id: number, neuron: Neuron): void {
    this.brainGroup.remove(neuron.group)
    neuron.soma.geometry.dispose()
    neuron.soma.material.dispose()
    neuron.dendrites.geometry.dispose()
    neuron.dendrites.material.dispose()
    this.neurons.delete(id)
  }

  /**
   * Quita un axón de la escena y libera su memoria.
   *
   * @param key - Clave del axón.
   * @param axon - Axón a quitar.
   */
  private removeAxon(key: string, axon: Axon): void {
    this.brainGroup.remove(axon.mesh)
    axon.mesh.geometry.dispose()
    axon.mesh.material.dispose()
    this.axons.delete(key)
  }

  /** Ajusta el tejido, la niebla y el encuadre al tamaño que ocupan los recuerdos. */
  private fitToBrain(): void {
    let bound = 0
    for (const neuron of this.neurons.values()) {
      bound = Math.max(bound, neuron.group.position.length() + neuron.radius * 4)
    }
    this.tissueRadius = Math.max(TISSUE_MIN_RADIUS, bound * 1.15)
    this.controls.maxDistance = this.tissueRadius * 7
    if (this.scene.fog instanceof THREE.FogExp2) {
      this.scene.fog.density = 0.19 / this.tissueRadius
    }
    this.fitting = true
  }

  /**
   * Calcula a qué distancia debe estar la cámara para que todo el cerebro quepa.
   *
   * @returns La distancia.
   */
  private fitDistance(): number {
    const vertical = THREE.MathUtils.degToRad(this.camera.fov) / 2
    const horizontal = Math.atan(Math.tan(vertical) * this.camera.aspect)
    return (this.tissueRadius * 1.08) / Math.sin(Math.min(vertical, horizontal))
  }

  /**
   * Calcula dónde aparece una neurona en la pantalla.
   *
   * @param neuron - Neurona.
   * @returns Posición y radio en píxeles, o `undefined` si queda detrás de la cámara.
   */
  private toScreen(neuron: Neuron): { x: number; y: number; radius: number; depth: number } | undefined {
    const world = neuron.group.position
    const depth = world.distanceTo(this.camera.position)
    const projected = world.clone().project(this.camera)
    if (projected.z > 1) return undefined
    const height = this.stage.clientHeight
    const scale = height / 2 / Math.tan(THREE.MathUtils.degToRad(this.camera.fov) / 2)
    return {
      x: ((projected.x + 1) / 2) * this.stage.clientWidth,
      y: ((1 - projected.y) / 2) * height,
      radius: (neuron.radius * scale) / depth,
      depth,
    }
  }

  /**
   * Calcula qué tan encendido sigue lo último que recordó Nova.
   *
   * @param now - Momento actual.
   * @returns Un valor de 1 (recién evocado) a 0 (apagado).
   */
  private recallGlow(now: number): number {
    return this.recall ? Math.max(0, 1 - (now - this.recall.at) / RECALL_GLOW_MS) : 0
  }

  /**
   * Lanza un impulso eléctrico, si queda lugar para otro.
   *
   * @param curve - Camino que recorre.
   * @param speed - Fracción del camino que avanza por segundo.
   * @param size - Radio del impulso.
   */
  private fireSpike(curve: THREE.Curve<THREE.Vector3>, speed: number, size: number): void {
    const slot = this.spikes.indexOf(null)
    if (slot >= 0) this.spikes[slot] = { curve, progress: 0, speed, size }
  }

  /**
   * Hace disparar a las neuronas: las evocadas lanzan impulsos por sus axones, y de vez en
   * cuando hay uno espontáneo.
   *
   * @param now - Momento actual.
   * @param glow - Qué tan encendido sigue el último recuerdo.
   */
  private fireSpikes(now: number, glow: number): void {
    if (this.reducedMotion) return

    // Impulsos del recuerdo: salen de la neurona evocada, invirtiendo la curva si hace falta.
    if (glow > 0 && now - this.lastRecallSpike > RECALL_SPIKE_MS) {
      this.lastRecallSpike = now
      for (const axon of this.axons.values()) {
        const fromSource = this.recall?.ids.includes(axon.source)
        const fromTarget = this.recall?.ids.includes(axon.target)
        if (fromSource) this.fireSpike(axon.curve, 1.1, 1.5)
        if (fromTarget) this.fireSpike(new ReversedCurve(axon.curve), 1.1, 1.5)
      }
    }

    // Impulsos espontáneos: por un axón si los hay, y también por el tejido de fondo.
    if (now - this.lastAmbientSpike > AMBIENT_SPIKE_MS) {
      this.lastAmbientSpike = now
      const axons = [...this.axons.values()]
      if (axons.length > 0 && this.ambientRandom() < 0.6) {
        const axon = axons[Math.floor(this.ambientRandom() * axons.length)]
        this.fireSpike(axon.curve, 0.7, 1)
      }
      const edge = this.tissueEdges[Math.floor(this.ambientRandom() * this.tissueEdges.length)]
      const scale = this.tissueRadius
      this.fireSpike(
        new THREE.LineCurve3(
          this.tissuePoints[edge[0]].clone().multiplyScalar(scale),
          this.tissuePoints[edge[1]].clone().multiplyScalar(scale),
        ),
        1.3,
        0.8,
      )
    }
  }

  /**
   * Mueve los impulsos y retira los que ya llegaron.
   *
   * @param delta - Segundos desde el cuadro anterior.
   */
  private updateSpikes(delta: number): void {
    const matrix = new THREE.Matrix4()
    const position = new THREE.Vector3()
    const rotation = new THREE.Quaternion()
    const scale = new THREE.Vector3()
    this.spikes.forEach((spike, index) => {
      if (spike) {
        spike.progress += spike.speed * delta
        if (spike.progress >= 1) this.spikes[index] = null
      }
      const active = this.spikes[index]
      if (active) {
        active.curve.getPoint(active.progress, position)
        // Crece al salir y se apaga al llegar, para que no aparezca de golpe.
        scale.setScalar(active.size * Math.sin(active.progress * Math.PI) ** 0.5)
      } else {
        position.set(0, 0, 0)
        scale.setScalar(0)
      }
      this.spikeMesh.setMatrixAt(index, matrix.compose(position, rotation, scale))
    })
    this.spikeMesh.instanceMatrix.needsUpdate = true
  }

  /**
   * Actualiza el crecimiento y el brillo de cada neurona y axón.
   *
   * @param now - Momento actual.
   * @param glow - Qué tan encendido sigue el último recuerdo.
   */
  private updateNeurons(now: number, glow: number): void {
    const ids = this.recall?.ids
    const flicker = this.reducedMotion ? 1 : 0.8 + Math.sin(now / 170) * 0.2

    for (const [id, neuron] of this.neurons) {
      // Crece desde cero con una salida suave.
      const growth = this.reducedMotion ? 1 : THREE.MathUtils.clamp((now - neuron.born) / GROWTH_MS, 0, 1)
      const eased = 1 - (1 - growth) ** 3
      neuron.group.visible = growth > 0
      neuron.group.scale.setScalar(Math.max(eased, 0.001))

      // Late apenas, cada una a su propio ritmo.
      const breath = this.reducedMotion ? 1 : 1 + Math.sin(now / 900 + id * 1.7) * 0.035
      neuron.soma.scale.setScalar(neuron.radius * breath)

      // Se enciende al evocarse o al pasar el cursor por encima.
      const lit = glow > 0 && Boolean(ids?.includes(id)) ? glow * flicker : 0
      const hovered = id === this.hoveredId || id === this.selectedId ? 0.5 : 0
      neuron.soma.material.emissiveIntensity = 0.42 + hovered + lit * 3.6
      neuron.dendrites.material.emissiveIntensity = 0.22 + hovered * 0.6 + lit * 1.8
    }

    for (const axon of this.axons.values()) {
      // El axón crece de un extremo a otro mostrando más triángulos en cada cuadro.
      const growth = this.reducedMotion ? 1 : THREE.MathUtils.clamp((now - axon.born) / GROWTH_MS, 0, 1)
      const indexCount = axon.mesh.geometry.index?.count ?? 0
      const shown = Math.floor(indexCount * growth)
      axon.mesh.geometry.setDrawRange(0, shown - (shown % 3))
      axon.mesh.visible = growth > 0

      // Brilla si toca alguna neurona evocada, y más si une dos.
      const touches = Number(Boolean(ids?.includes(axon.source))) + Number(Boolean(ids?.includes(axon.target)))
      const lit = glow * touches * 0.5
      axon.mesh.material.color.setScalar(0.9 + lit * 3)
      axon.mesh.material.opacity = Math.min(1, 0.4 + axon.strength * 0.4 + lit * 0.6)
    }
  }

  /**
   * Mueve la cámara hacia la neurona elegida o el centro, y ajusta su distancia si hace falta.
   *
   * @param delta - Segundos desde el cuadro anterior.
   */
  private updateCamera(delta: number): void {
    const easing = this.reducedMotion ? 1 : 1 - Math.exp(-delta * 3)

    // Mueve el punto de mira junto con la cámara, para no cambiar el ángulo del usuario.
    const selected = this.selectedId === null ? undefined : this.neurons.get(this.selectedId)
    const focus = selected?.group.position ?? new THREE.Vector3()
    const shift = focus.clone().sub(this.controls.target).multiplyScalar(easing)
    this.controls.target.add(shift)
    this.camera.position.add(shift)

    // Se aleja o se acerca hasta encuadrar todo, salvo que el usuario ya haya tomado el control.
    if (this.fitting) {
      const offset = this.camera.position.clone().sub(this.controls.target)
      const distance = THREE.MathUtils.lerp(offset.length(), this.fitDistance(), easing)
      this.camera.position.copy(this.controls.target).add(offset.setLength(distance))
      if (Math.abs(distance - this.fitDistance()) < 1) this.fitting = false
    }

    this.controls.autoRotate =
      !this.reducedMotion && !this.dragging && this.hoveredId === null && this.selectedId === null
    this.controls.update(delta)

    // El tejido cambia de tamaño poco a poco si el cerebro crece.
    const tissueScale = THREE.MathUtils.lerp(this.tissue.scale.x, this.tissueRadius, easing)
    this.tissue.scale.setScalar(tissueScale)

    // El anillo de selección siempre mira a la cámara.
    this.selectionRing.visible = Boolean(selected)
    if (selected) {
      this.selectionRing.position.copy(selected.group.position)
      this.selectionRing.quaternion.copy(this.camera.quaternion)
      this.selectionRing.scale.setScalar(selected.radius)
    }
  }

  /**
   * Dibuja los nombres de los recuerdos encima del 3D. Los lejanos se desvanecen, y los
   * que se encimarían con otro más importante no se dibujan, para que se puedan leer.
   *
   * @param glow - Qué tan encendido sigue el último recuerdo.
   */
  private drawLabels(glow: number): void {
    const context = this.labelContext
    if (!context) return
    const width = this.stage.clientWidth
    context.clearRect(0, 0, width, this.stage.clientHeight)
    context.font = '12px ui-sans-serif, system-ui, sans-serif'
    context.textAlign = 'center'
    context.shadowColor = NIGHT_COLOR
    context.shadowBlur = 5

    // Reúne las etiquetas: primero las importantes y después de cerca a lejos.
    const entries = [...this.neurons.values()]
      .filter((neuron) => neuron.group.visible)
      .flatMap((neuron) => {
        const screen = this.toScreen(neuron)
        if (!screen) return []
        const id = neuron.memory.id
        const priority =
          id === this.selectedId || id === this.hoveredId || (glow > 0 && this.recall?.ids.includes(id))
        return [{ neuron, screen, priority: Boolean(priority) }]
      })
      .sort((a, b) => Number(b.priority) - Number(a.priority) || a.screen.depth - b.screen.depth)

    // Coloca cada etiqueta si no choca con una ya colocada.
    const distance = this.camera.position.distanceTo(this.controls.target)
    const placed: { left: number; right: number; top: number; bottom: number }[] = []
    for (const { neuron, screen, priority } of entries) {
      const fade = 1 - THREE.MathUtils.clamp((screen.depth - distance + this.tissueRadius * 0.3) / this.tissueRadius, 0, 1)
      // Con pocos recuerdos caben todos los textos; con muchos solo se leen los cercanos.
      if (!priority && fade < 0.45 && this.neurons.size > FEW_NEURONS) continue

      const content = neuron.memory.content
      const text = content.length > LABEL_CHARS ? `${content.slice(0, LABEL_CHARS)}…` : content
      const half = context.measureText(text).width / 2
      const y = screen.y + screen.radius + 16
      const box = { left: screen.x - half - 4, right: screen.x + half + 4, top: y - 13, bottom: y + 4 }
      const collides = placed.some(
        (other) =>
          box.left < other.right && box.right > other.left && box.top < other.bottom && box.bottom > other.top,
      )
      if (collides) continue
      placed.push(box)

      context.globalAlpha = priority ? 1 : Math.max(this.neurons.size > FEW_NEURONS ? 0 : 0.6, 0.2 + fade * 0.7)
      context.fillStyle = priority ? '#f1f1ff' : '#aaaee0'
      context.fillText(text, screen.x, y)
    }
    context.globalAlpha = 1
  }

  /**
   * Dibuja un cuadro.
   *
   * @param timestamp - Momento actual, en el reloj de la animación.
   */
  private readonly draw = (timestamp: number) => {
    this.frame = requestAnimationFrame(this.draw)
    // Limita el salto de tiempo: al volver de otra pestaña no debe saltarse la animación.
    const delta = Math.min(0.05, (timestamp - this.lastFrame) / 1000)
    this.lastFrame = timestamp

    const glow = this.recallGlow(timestamp)
    this.fireSpikes(timestamp, glow)
    this.updateSpikes(Math.max(delta, 0))
    this.updateNeurons(timestamp, glow)
    this.updateCamera(Math.max(delta, 0))
    this.composer.render(Math.max(delta, 0))
    this.drawLabels(glow)
  }
}

/** Recorre otra curva en sentido contrario, para que un impulso salga de cualquiera de sus extremos. */
class ReversedCurve extends THREE.Curve<THREE.Vector3> {
  private readonly curve: THREE.Curve<THREE.Vector3>

  /**
   * Crea la curva invertida.
   *
   * @param curve - Curva original.
   */
  constructor(curve: THREE.Curve<THREE.Vector3>) {
    super()
    this.curve = curve
  }

  /**
   * Calcula un punto de la curva.
   *
   * @param t - Avance, de 0 a 1.
   * @param target - Vector donde se guarda el resultado.
   * @returns El punto.
   */
  getPoint(t: number, target = new THREE.Vector3()): THREE.Vector3 {
    return this.curve.getPoint(1 - t, target)
  }
}

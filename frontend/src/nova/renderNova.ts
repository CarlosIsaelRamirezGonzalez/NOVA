/** Dibujo de Nova: convierte el estado de la simulación en píxeles. */

import { hex, mix, pack, PixelBuffer, type RGB } from './pixelBuffer'
import { CANVAS_SIZE, HEAD_Y, type NovaState, type Particle } from './novaState'

// Colores fijos del personaje, que no cambian con la emoción.
const OUTLINE = pack(hex('#16123F'))
const WHITE = pack(hex('#F3F3FF'))
const WHITE_SOFT = pack(hex('#D9D9F7'))
const LAVENDER = pack(hex('#ABA8E8'))
const LAVENDER_DARK = pack(hex('#7E73D6'))
const TAIL = pack(hex('#5B46C4'))
const TAIL_DARK = pack(hex('#3A2A9C'))
const VISOR = pack(hex('#0D0C33'))
const VISOR_EDGE = pack(hex('#262268'))
const CHEST = pack(hex('#30238E'))

// Colores base del portal; se mezclan con los de la emoción.
const PORTAL_DARK = hex('#2B1E7A')
const PORTAL_MID = hex('#4A3DE0')
const PORTAL_BRIGHT = hex('#8FA2FF')

// Mapas de bits de la letra del pecho y de algunas partículas.
const LETTER_N = ['#    #', '##   #', '# #  #', '#  # #', '#   ##', '#    #', '#    #']
// Señales que acompañan a cada emoción, como en un cómic.
const CLOUD = ['   ###    ', ' ####### ', '##########', '##########', ' ######## ']
const ANGER_MARK = ['## ##', '#   #', '     ', '#   #', '## ##']
const EXCLAMATION = ['##', '##', '##', '##', '  ', '##']
const SWEAT = ['  #  ', ' ### ', '#####', '#####', ' ### ']
const TANGLE = [' ###### ', '# ##  ##', '##  ## #', ' ## ### ', '  ####  ']
const SCRIBBLE = [' ## # ', '#  # #', ' # ## ', '#  #  ']
const QUESTION = [' ### ', '#   #', '    #', '  ## ', '  #  ', '     ', '  #  ']

/** Forma y movimiento de una llama individual. */
type Petal = {
  angle: number
  length: number
  width: number
  curl: number // cuánto enrolla hacia arriba
  bend: number // curva en S; el signo decide hacia dónde remata la punta
  seed: number
}

// Dibujadas del centro hacia afuera. Son asimétricas a propósito: el fuego simétrico parece un penacho.
const PETALS: Petal[] = [
  { angle: 0.05, length: 47, width: 8.5, curl: 0, bend: 0.2, seed: 0 },
  { angle: -0.27, length: 39, width: 8.5, curl: 0.06, bend: -0.2, seed: 1.3 },
  { angle: 0.36, length: 42, width: 8.5, curl: 0.08, bend: 0.24, seed: 2.4 },
  { angle: -0.68, length: 36, width: 9, curl: 0.18, bend: -0.26, seed: 3.1 },
  { angle: 0.76, length: 34, width: 9, curl: 0.2, bend: 0.26, seed: 4.2 },
  { angle: -1.12, length: 31, width: 8.5, curl: 0.32, bend: -0.3, seed: 5 },
  { angle: 1.16, length: 33, width: 8.5, curl: 0.3, bend: 0.3, seed: 5.8 },
  { angle: -1.56, length: 27, width: 7.5, curl: 0.42, bend: -0.24, seed: 6.6 },
  { angle: 1.52, length: 25, width: 7.5, curl: 0.44, bend: 0.24, seed: 7.4 },
  { angle: -1.98, length: 20, width: 5.5, curl: 0.24, bend: -0.15, seed: 8.2 },
  { angle: 2.03, length: 21, width: 5.5, curl: 0.22, bend: 0.15, seed: 9.1 },
]

/**
 * Calcula un punto de la columna central de una llama.
 *
 * @param petal - Llama que se dibuja.
 * @param scale - Multiplicador de su largo.
 * @param state - Estado de la animación.
 * @param hx - Columna de la cabeza.
 * @param hy - Fila de la cabeza.
 * @param s - Avance a lo largo de la llama, de 0 (base) a 1 (punta).
 * @returns La posición del punto.
 */
function petalPoint(petal: Petal, scale: number, state: NovaState, hx: number, hy: number, s: number) {
  const { pose, hairPhase } = state
  const length = petal.length * scale * pose.hairLength * (1 + state.level * 0.14)
  const dirX = Math.sin(petal.angle)
  const dirY = -Math.cos(petal.angle)
  const sideX = Math.cos(petal.angle)
  const sideY = Math.sin(petal.angle)
  const hook = petal.bend * length * (-0.42 * Math.sin(Math.PI * s) + 1.15 * s * s * s)
  const sway = Math.sin(hairPhase * 4.2 + petal.seed - s * 3.4) * pose.hairWild * 3.2 * s * s
  const flick = Math.sin(hairPhase * 9 + petal.seed * 2.1) * pose.hairWild * 1.2 * s * s * s
  // Las llamas enrollan hacia arriba; si Nova está triste caen por su peso.
  const curlUp = petal.curl * length * s * s * (1 - pose.hairDroop * 0.8)
  const droop = pose.hairDroop * length * 0.62 * s * s
  return {
    x: hx + dirX * 18 + dirX * length * s + sideX * hook + sway,
    y: hy + dirY * 15 + dirY * length * s + sideY * hook - curlUp + droop + flick,
  }
}

/**
 * Dibuja una llama como una sucesión de círculos, una capa de color tras otra.
 *
 * @param buffer - Lienzo de destino.
 * @param petal - Llama que se dibuja.
 * @param state - Estado de la animación.
 * @param hx - Columna de la cabeza.
 * @param hy - Fila de la cabeza.
 * @param scale - Multiplicador de su largo.
 * @param layers - Capas, de la exterior a la interior.
 */
function drawPetal(
  buffer: PixelBuffer,
  petal: Petal,
  state: NovaState,
  hx: number,
  hy: number,
  scale: number,
  layers: ReadonlyArray<{ color: number; width: number; extra: number; end: number }>,
) {
  // Cada capa recorre la llama desde la base hasta donde indique `end`.
  const samples = Math.ceil(petal.length * 1.15)
  for (const layer of layers) {
    for (let i = 0; i <= samples; i++) {
      const s = i / samples
      if (s > layer.end) break
      const point = petalPoint(petal, scale, state, hx, hy, s)
      // Ancha abajo, punta larga y fina, con bordes ondulados que cambian como el fuego.
      const ripple = 1 + 0.13 * Math.sin(s * 11 + petal.seed * 3 - state.hairPhase * 6)
      const profile = Math.sin(Math.PI * s ** 0.6) ** 1.05
      const radius = petal.width * profile * ripple * layer.width + layer.extra * (1 - s)
      if (radius > 0.15) buffer.disc(point.x, point.y, radius, layer.color)
    }
  }
}

/**
 * Dibuja todas las llamas: primero una capa oscura de fondo y luego las detalladas.
 *
 * @param buffer - Lienzo de destino.
 * @param state - Estado de la animación.
 * @param hx - Columna de la cabeza.
 * @param hy - Fila de la cabeza.
 */
function drawFlames(buffer: PixelBuffer, state: NovaState, hx: number, hy: number) {
  const { ramp } = state.pose
  const back = pack(ramp.back)
  const deep = pack(ramp.deep)
  const mid = pack(ramp.mid)
  const light = pack(ramp.light)
  const core = pack(ramp.core)

  for (const petal of PETALS) {
    drawPetal(buffer, { ...petal, seed: petal.seed + 11 }, state, hx, hy, 1.1, [
      { color: back, width: 1.12, extra: 1, end: 1 },
    ])
  }
  for (const petal of PETALS) {
    drawPetal(buffer, petal, state, hx, hy, 1, [
      { color: deep, width: 1, extra: 0.3, end: 1 },
      { color: mid, width: 0.7, extra: 0, end: 0.86 },
      { color: light, width: 0.42, extra: 0, end: 0.56 },
      { color: core, width: 0.2, extra: 0, end: 0.34 },
    ])
  }
}

/**
 * Dibuja el portal del suelo y los rayos que suben de él.
 *
 * @param buffer - Lienzo de destino.
 * @param state - Estado de la animación.
 */
function drawPortal(buffer: PixelBuffer, state: NovaState) {
  const cx = CANVAS_SIZE / 2 + Math.round(state.x * 0.25)
  const cy = 147
  const energy = 0.6 + state.level * 0.4 + Math.max(0, -state.pose.lift) * 0.04
  const ramp = state.pose.ramp

  // Anillos concéntricos: del más ancho y oscuro al más pequeño y brillante.
  const rings: Array<[number, number, RGB]> = [
    [56, 10, mix(PORTAL_DARK, ramp.back, 0.8)],
    [44, 8, mix(PORTAL_DARK, ramp.deep, 0.8)],
    [32, 6, mix(PORTAL_MID, ramp.deep, 0.8)],
    [20, 4, mix(PORTAL_BRIGHT, ramp.mid, 0.8)],
  ]
  rings.forEach(([rx, ry, color], index) => {
    const pulse = Math.sin(state.time * 2.2 - index * 0.9) * 0.1
    const alpha = (0.26 + index * 0.13 + pulse) * energy
    for (let dy = -Math.ceil(ry); dy <= ry; dy++) {
      for (let dx = -Math.ceil(rx); dx <= rx; dx++) {
        const inside = (dx / rx) ** 2 + (dy / ry) ** 2
        if (inside <= 1 && inside > 0.76) buffer.blend(cx + dx, cy + dy, color, Math.min(1, alpha * 2.2))
        else if (inside <= 0.76) buffer.blend(cx + dx, cy + dy, color, alpha * 0.4)
      }
    }
  })

  // Destello del centro: horizontal, como luz sobre el suelo.
  const coreLight = pack(mix(ramp.light, hex('#FFFFFF'), 0.5))
  const reach = 7 + Math.round(state.level * 4)
  for (let dx = -reach; dx <= reach; dx++) {
    const thickness = Math.abs(dx) < reach * 0.4 ? 1 : 0
    for (let dy = -thickness; dy <= thickness; dy++) buffer.set(cx + dx, cy + dy, coreLight)
  }
  for (let dy = -3; dy <= 3; dy++) buffer.set(cx, cy + dy, coreLight)

  // Rayos que suben del portal.
  for (let i = 0; i < 15; i++) {
    const x = cx - 42 + i * 6 + Math.round(Math.sin(i * 7.3) * 2)
    const speed = 0.55 + ((i * 37) % 10) / 16
    const cycle = (state.time * speed + i * 0.37) % 1
    const baseY = cy - 2 - cycle * 34
    const height = 3 + (i * 13) % 9
    const color = i % 3 === 0 ? ramp.light : ramp.mid
    for (let j = 0; j < height; j++) {
      buffer.blend(x, baseY - j, color, (1 - cycle) * (1 - j / height) * 0.8 * energy)
    }
  }
}

/**
 * Dibuja el cuerpo fila por fila, de los hombros a la punta de la cola.
 *
 * @param buffer - Lienzo de destino.
 * @param state - Estado de la animación.
 * @param cx - Columna del centro del cuerpo.
 * @param top - Fila donde empieza el cuerpo.
 */
function drawBody(buffer: PixelBuffer, state: NovaState, cx: number, top: number) {
  const height = Math.round(47 * state.bodyStretch)
  for (let row = 0; row <= height; row++) {
    // Ancho de la fila: hombros, vientre y luego la cola, que se afina hasta la punta.
    const t = row / height
    const taper = (t - 0.4) / 0.6
    const width =
      t < 0.14
        ? 6.5 + (t / 0.14) * 4.8
        : t < 0.4
          ? 11.3 + ((t - 0.14) / 0.26) * 1.7
          : 13 * (1 - taper) ** 0.82 * (1 - taper * taper * 0.25)
    // La cola se balancea más cuanto más cerca está de la punta.
    const center = cx + state.tailSway * t * t * 1.8
    const left = Math.round(center - width)
    const right = Math.round(center + width)
    for (let x = left; x <= right; x++) {
      const across = (x - center) / Math.max(width, 1)
      // El límite entre tonos sigue la curva del cuerpo y da sensación de volumen.
      const depth = t + across * 0.1 + across * across * 0.1
      let color = WHITE
      if (depth > 0.9) color = TAIL_DARK
      else if (depth > 0.76) color = TAIL
      else if (depth > 0.62) color = LAVENDER_DARK
      else if (depth > 0.47) color = LAVENDER
      else if (depth > 0.34) color = WHITE_SOFT
      buffer.set(x, top + row, color)
    }
  }
  buffer.glyph(LETTER_N, cx - 3, top + 6, CHEST)
}

/**
 * Dibuja un brazo con su sombra debajo.
 *
 * @param buffer - Lienzo de destino.
 * @param cx - Columna del centro del cuerpo.
 * @param cy - Fila donde empieza el cuerpo.
 * @param side - Lado del cuerpo: -1 izquierdo, 1 derecho.
 * @param angle - Ángulo del brazo: 0 abajo, PI arriba.
 */
function drawArm(buffer: PixelBuffer, cx: number, cy: number, side: -1 | 1, angle: number) {
  const reach = 15
  const steps = 18
  const shoulderX = cx + side * 10
  const shoulderY = cy + 4
  const point = (s: number) => ({
    x: shoulderX + side * Math.sin(angle) * reach * s,
    y: shoulderY + Math.cos(angle) * reach * s,
  })
  // Primero la sombra, desplazada un píxel hacia abajo; luego el brazo encima.
  for (let i = 0; i <= steps; i++) {
    const s = i / steps
    const { x, y } = point(s)
    buffer.disc(x, y + 1, 3.1 + s * 1.5, LAVENDER)
  }
  for (let i = 0; i <= steps; i++) {
    const s = i / steps
    const { x, y } = point(s)
    buffer.disc(x - 0.5, y, 2.7 + s * 1.3, i > steps * 0.86 ? WHITE_SOFT : WHITE)
  }
}

/**
 * Dibuja un ojo; su forma expresa la emoción con el ceño y la sonrisa.
 *
 * @param buffer - Lienzo de destino.
 * @param state - Estado de la animación.
 * @param cx - Columna del centro del ojo.
 * @param cy - Fila del centro del ojo.
 * @param side - Lado de la cara: -1 izquierdo, 1 derecho.
 * @param scale - Tamaño relativo del ojo.
 * @param outer - Color del borde.
 * @param inner - Color del centro.
 */
function drawEye(
  buffer: PixelBuffer,
  state: NovaState,
  cx: number,
  cy: number,
  side: -1 | 1,
  scale: number,
  outer: number,
  inner: number,
) {
  // Tamaño final según la pose, el parpadeo y la voz.
  const { eyeSlant, eyeSmile } = state.pose
  const halfW = state.pose.eyeWidth * scale
  const blink = state.blink > 0 ? 1 - Math.sin(state.blink * Math.PI) * 0.88 : 1
  const halfH = Math.max(1, (state.pose.eyeHeight * scale * blink * state.eyeTwitch * (1 + state.level * 0.05)) / 2)
  // La sonrisa se forma recortando la parte inferior del ojo con un círculo.
  const cutRadius = eyeSmile * halfW * 1.45
  const cutY = cy + halfH + cutRadius * 0.32

  for (let dy = -Math.ceil(halfH) - 1; dy <= Math.ceil(halfH) + 1; dy++) {
    for (let dx = -Math.ceil(halfW) - 1; dx <= Math.ceil(halfW) + 1; dx++) {
      const pill = Math.abs(dx / (halfW + 0.5)) ** 3 + Math.abs(dy / (halfH + 0.5)) ** 3
      if (pill > 1) continue
      // El ceño recorta la parte superior en diagonal: hacia dentro enojo, hacia fuera tristeza.
      const towardCenter = dx * -side
      const topLimit =
        eyeSlant >= 0
          ? -halfH + eyeSlant * (towardCenter + halfW)
          : -halfH + -eyeSlant * (halfW - towardCenter)
      if (dy < topLimit) continue
      if (cutRadius > 0 && Math.hypot(dx, cy + dy - cutY) < cutRadius) continue
      const edge = Math.abs(dx) > halfW - 0.8 || Math.abs(dy) > halfH - 1.2 || dy < topLimit + 1
      buffer.set(cx + dx, cy + dy, edge ? outer : inner)
    }
  }
}

/**
 * Dibuja el casco, el visor, los ojos, la boca de luz y la gema.
 *
 * @param buffer - Lienzo de destino.
 * @param state - Estado de la animación.
 * @param hx - Columna de la cabeza.
 * @param hy - Fila de la cabeza.
 */
function drawHead(buffer: PixelBuffer, state: NovaState, hx: number, hy: number) {
  const { pose } = state
  const outerColor = pack(pose.eyeOuter)
  const innerColor = pack(pose.eyeInner)

  // Casco: contorno y tres tonos que le dan volumen.
  buffer.rounded(hx, hy, 23.5, 21.5, 2.45, OUTLINE)
  buffer.rounded(hx, hy, 22.5, 20.5, 2.45, LAVENDER)
  buffer.rounded(hx - 0.6, hy - 0.8, 21.4, 19.3, 2.45, WHITE_SOFT)
  buffer.rounded(hx - 1, hy - 1.3, 20, 18, 2.45, WHITE)

  // Visor oscuro.
  buffer.rounded(hx, hy + 1, 17, 14.5, 2.8, VISOR_EDGE)
  buffer.rounded(hx, hy + 1, 16, 13.5, 2.8, VISOR)

  // Resplandor de los ojos sobre el visor, limitado para que no lo atraviese.
  // Los ojos se desplazan hacia donde mira; con curiosidad, la cara se ladea.
  const eyeX = Math.round(state.lookX * 3.2)
  const eyeY = Math.round(state.lookY * 2.4)
  const tilt = Math.round(state.feel.curious * 3)
  const leftX = hx - 8 + eyeX
  const rightX = hx + 8 + eyeX
  const leftY = hy + 1 + eyeY + tilt
  const rightY = hy + 1 + eyeY - tilt

  // Resplandor de los ojos, limitado para que no se salga del visor.
  for (const [ex, ey] of [[leftX, leftY], [rightX, rightY]]) {
    for (let dy = -9; dy <= 9; dy++) {
      for (let dx = -8; dx <= 8; dx++) {
        const x = ex + dx
        const y = ey + dy
        const inVisor = Math.abs((x - hx) / 15.5) ** 2.8 + Math.abs((y - hy - 1) / 13) ** 2.8 <= 1
        const distance = Math.hypot(dx / 8, dy / 9)
        if (inVisor && distance < 1) {
          buffer.blend(x, y, pose.eyeOuter, (Math.ceil((1 - distance) * 3) / 3) * (0.2 + state.level * 0.15))
        }
      }
    }
  }

  drawVisorFeelings(buffer, state, hx, hy, [[leftX, leftY], [rightX, rightY]])

  // Ojos.
  drawEye(buffer, state, leftX, leftY, -1, 1, outerColor, innerColor)
  drawEye(buffer, state, rightX, rightY, 1, pose.eyeRightScale, outerColor, innerColor)

  // Boca de luz: solo existe mientras habla.
  if (state.level > 0.06) {
    const mouthW = 2 + Math.round(state.level * 2.5)
    const mouthH = 1 + Math.round(state.level * 3.4)
    const mouthX = hx + eyeX
    const mouthY = hy + 8 + eyeY
    for (let dy = 0; dy < mouthH; dy++) {
      const width = dy === 0 || dy === mouthH - 1 ? mouthW - 1 : mouthW
      for (let dx = -width; dx <= width; dx++) buffer.set(mouthX + dx, mouthY + dy, innerColor)
    }
  }


  // Gema de la frente: brilla más cuando habla.
  const gemX = hx
  const gemY = hy - 21
  const radius = 6
  const bright = 0.35 + state.level * 0.65
  buffer.glow(gemX, gemY, 11 + state.level * 6, pose.ramp.light, 0.34 + state.level * 0.4, 3)
  // Colores de sus facetas: la luz cambia con la voz.
  const gemLight = pack(mix(pose.ramp.mid, pose.ramp.core, bright))
  const gemMid = pack(pose.ramp.deep)
  const gemDark = pack(pose.ramp.back)
  // Rombo con contorno; cada cuadrante es una faceta con su propio tono.
  for (let dy = -radius - 1; dy <= radius + 1; dy++) {
    for (let dx = -radius; dx <= radius; dx++) {
      const shape = Math.abs(dx) * 1.25 + Math.abs(dy)
      if (shape > radius + 1) continue
      let color = gemDark
      if (shape <= radius) {
        color = dx < 0 ? (dy < 0 ? gemLight : gemMid) : dy < 0 ? gemMid : gemDark
        if (shape <= 1.5) color = gemLight
      } else {
        color = OUTLINE
      }
      buffer.set(gemX + dx, gemY + dy, color)
    }
  }
}

/**
 * Dibuja una partícula según su tipo.
 *
 * @param buffer - Lienzo de destino.
 * @param particle - Partícula que se dibuja.
 */
/**
 * Dibuja un símbolo al doble de tamaño y con contorno oscuro, para que se lea sobre las llamas.
 *
 * @param buffer - Lienzo de destino.
 * @param rows - Filas del símbolo.
 * @param x - Columna de la esquina superior izquierda.
 * @param y - Fila de la esquina superior izquierda.
 * @param color - Color empaquetado del símbolo.
 */
function drawSign(buffer: PixelBuffer, rows: readonly string[], x: number, y: number, color: number) {
  // Duplica cada píxel a lo ancho y a lo alto, sin perder el aspecto de pixel art.
  const large = rows.flatMap((row) => {
    const wide = [...row].map((cell) => cell + cell).join('')
    return [wide, wide]
  })

  for (const [dx, dy] of [[-1, 0], [1, 0], [0, -1], [0, 1]]) {
    buffer.glyph(large, x + dx, y + dy, OUTLINE)
  }
  buffer.glyph(large, x, y, color)
}

/**
 * Dibuja lo que cada emoción añade dentro del visor: lágrimas o sombras.
 *
 * @param buffer - Lienzo de destino.
 * @param state - Estado de la animación.
 * @param hx - Columna de la cabeza.
 * @param hy - Fila de la cabeza.
 * @param eyes - Posición de cada ojo.
 */
function drawVisorFeelings(
  buffer: PixelBuffer,
  state: NovaState,
  hx: number,
  hy: number,
  eyes: ReadonlyArray<readonly [number, number]>,
) {
  const { feel, time } = state
  const inVisor = (x: number, y: number) =>
    Math.abs((x - hx) / 15.5) ** 2.8 + Math.abs((y - hy - 1) / 13) ** 2.8 <= 1

  // Asustada: líneas de sombra que caen desde arriba del visor.
  if (feel.afraid > 0.2) {
    for (let x = hx - 14; x <= hx + 14; x += 3) {
      const length = 4 + ((x * 7) % 5)
      for (let i = 0; i < length; i++) {
        const y = hy - 12 + i
        if (inVisor(x, y)) buffer.blend(x, y, hex('#6A7BD8'), feel.afraid * 0.75 * (1 - i / length))
      }
    }
  }

  for (const [eyeX, eyeY] of eyes) {
    // Triste: una lágrima baja por el visor desde cada ojo.
    if (feel.sad > 0.2) {
      for (let y = eyeY + 4; y <= hy + 13; y++) {
        const falling = (y * 0.3 - time * 3 + eyeX) % 2 < 0.8
        if (inVisor(eyeX, y) && falling) buffer.blend(eyeX, y, hex('#A6DCFF'), Math.min(1, feel.sad * 1.5))
      }
    }
  }
}

/**
 * Dibuja las señales de cómic alrededor de la cabeza según lo que siente.
 *
 * @param buffer - Lienzo de destino.
 * @param state - Estado de la animación.
 * @param hx - Columna de la cabeza.
 * @param hy - Fila de la cabeza.
 */
function drawSigns(buffer: PixelBuffer, state: NovaState, hx: number, hy: number) {
  const { feel, time } = state
  const threshold = 0.3

  // Triste: una nube de lluvia sobre la cabeza.
  if (feel.sad > threshold) {
    drawSign(buffer, CLOUD, hx - 10, hy - 46 + Math.round(Math.sin(time) * 1), pack(hex('#7C8AB8')))
  }

  // Enojada: la marca de enfado late junto a la cabeza.
  if (feel.angry > threshold && Math.sin(time * 9) > -0.4) {
    drawSign(buffer, ANGER_MARK, hx + 18, hy - 30, pack(hex('#FF3B30')))
  }

  // Sorprendida: un signo de exclamación que salta.
  if (feel.surprised > threshold) {
    drawSign(buffer, EXCLAMATION, hx + 27, hy - 36 - Math.round(Math.abs(Math.sin(time * 7)) * 3), pack(hex('#FFE6B5')))
  }

  // Curiosa: un signo de interrogación que se balancea.
  if (feel.curious > threshold) {
    drawSign(buffer, QUESTION, hx + 23 + Math.round(Math.sin(time * 2) * 2), hy - 38, pack(hex('#B8F0FF')))
  }

  // Preocupada o asustada: una gota grande de sudor resbala por el casco.
  if (feel.worried > threshold || feel.afraid > threshold) {
    const slide = ((time * 5) % 12) | 0
    drawSign(buffer, SWEAT, hx + 20, hy - 18 + slide, pack(hex('#A6DCFF')))
  }

  // Estresada: un garabato gira alrededor de la cabeza.
  if (feel.stressed > threshold) {
    const orbit = time * 4
    drawSign(buffer, SCRIBBLE, hx - 6 + Math.round(Math.cos(orbit) * 26), hy - 36 + Math.round(Math.sin(orbit) * 7), pack(hex('#FFE27A')))
    drawSign(buffer, SCRIBBLE, hx - 6 - Math.round(Math.cos(orbit) * 26), hy - 36 - Math.round(Math.sin(orbit) * 7), pack(hex('#FFB45E')))
  }

  // Frustrada: una maraña sobre la cabeza que cambia de lado.
  if (feel.frustrated > threshold) {
    drawSign(buffer, TANGLE, hx - 8 + Math.round(Math.sin(time * 6) * 2), hy - 46, pack(hex('#3A2C30')))
  }
}

function drawParticle(buffer: PixelBuffer, particle: Particle) {
  const progress = particle.life / particle.maxLife
  const color = pack(particle.color)
  const { x, y } = particle
  switch (particle.kind) {
    case 'star': {
      const size = Math.sin(progress * Math.PI) > 0.72 ? 2 : Math.sin(progress * Math.PI) > 0.3 ? 1 : 0
      buffer.set(x, y, color)
      for (let i = 1; i <= size; i++) {
        buffer.set(x + i, y, color)
        buffer.set(x - i, y, color)
        buffer.set(x, y + i, color)
        buffer.set(x, y - i, color)
      }
      break
    }
    case 'dot':
    case 'ember':
      buffer.set(x, y, color)
      break
    case 'drop':
      buffer.set(x, y, color)
      buffer.set(x, y + 1, color)
      break
    case 'question':
      buffer.glyph(QUESTION, x - 2, y - 3, color)
      break
    case 'scribble':
      buffer.glyph(SCRIBBLE, x - 3, y - 2, color)
      break
    case 'steam':
      // Se expande y se desvanece mientras sube.
      buffer.glow(x, y, 3 + (1 - progress) * 4, particle.color, 0.35 + progress * 0.6, 2)
      break
  }
}

/**
 * Dibuja un cuadro completo, de atrás hacia adelante.
 *
 * @param buffer - Lienzo de destino.
 * @param state - Estado de la animación.
 */
export function renderNova(buffer: PixelBuffer, state: NovaState) {
  // El portal siempre es visible, incluso antes de que aparezca Nova.
  buffer.clear()
  buffer.reveal = 1
  drawPortal(buffer, state)

  // Posición del cuadro; la cabeza se adelanta un poco hacia donde mira.
  const cx = Math.round(CANVAS_SIZE / 2 + state.x + state.shakeX + state.actX)
  const bodyTop = Math.round(HEAD_Y + state.y) + 17
  const hy = Math.round(HEAD_Y + state.y + state.headSink)
  const hx = cx + Math.round(state.lookX * 1.2 + state.headShake)

  // Las capas de Nova comparten el efecto de materializarse al aparecer.
  buffer.reveal = state.appear >= 1 ? 1 : state.appear ** 1.4
  buffer.glow(hx, hy - 10, 68, state.pose.ramp.mid, 0.13 + state.level * 0.2, 9)
  drawFlames(buffer, state, hx, hy)
  drawBody(buffer, state, cx, bodyTop)
  drawArm(buffer, cx, bodyTop, -1, state.armLeft)
  drawArm(buffer, cx, bodyTop, 1, state.armRight)
  drawHead(buffer, state, hx, hy)
  drawSigns(buffer, state, hx, hy)
  buffer.reveal = 1

  // Las partículas van encima de todo.
  for (const particle of state.particles) drawParticle(buffer, particle)
}

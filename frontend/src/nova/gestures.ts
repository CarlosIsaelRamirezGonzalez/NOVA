/** Reconoce gestos de la mano a partir de sus 21 puntos, sin que la imagen salga del equipo. */

export type Gesture = 'middle_finger' | 'thumbs_up'

/** Un punto de la mano, con coordenadas normalizadas de la imagen. */
export type HandPoint = {
  x: number
  y: number
  z: number
}

// Índices de los puntos que usa MediaPipe.
const WRIST = 0
const THUMB_KNUCKLE = 2
const THUMB_TIP = 4
const INDEX: Finger = { middleJoint: 6, tip: 8 }
const MIDDLE: Finger = { middleJoint: 10, tip: 12 }
const RING: Finger = { middleJoint: 14, tip: 16 }
const PINKY: Finger = { middleJoint: 18, tip: 20 }

// Un dedo está estirado si su punta queda claramente más lejos de la muñeca que su articulación.
const EXTENDED_RATIO = 1.2
const CURLED_RATIO = 1.08
const THUMB_EXTENDED_RATIO = 1.15

/** Puntos de un dedo. */
type Finger = {
  middleJoint: number
  tip: number
}

/**
 * Mide la distancia entre dos puntos de la mano.
 *
 * @param a - Primer punto.
 * @param b - Segundo punto.
 * @returns La distancia.
 */
const distance = (a: HandPoint, b: HandPoint) => Math.hypot(a.x - b.x, a.y - b.y)

/**
 * Calcula qué tan estirado está un dedo; al usar la muñeca como referencia,
 * funciona aunque la mano esté inclinada.
 *
 * @param hand - Puntos de la mano.
 * @param finger - Dedo que se mide.
 * @returns La proporción entre la distancia de la punta y la de su articulación.
 */
function fingerRatio(hand: readonly HandPoint[], finger: Finger): number {
  return distance(hand[finger.tip], hand[WRIST]) / distance(hand[finger.middleJoint], hand[WRIST])
}

/**
 * Reconoce el gesto que hace una mano.
 *
 * @param hand - Los 21 puntos de la mano.
 * @returns El gesto, o `null` si no es ninguno conocido.
 */
export function detectGesture(hand: readonly HandPoint[]): Gesture | null {
  const index = fingerRatio(hand, INDEX)
  const middle = fingerRatio(hand, MIDDLE)
  const ring = fingerRatio(hand, RING)
  const pinky = fingerRatio(hand, PINKY)

  // Dedo de en medio: solo ese estirado. El pulgar se ignora porque cada quien lo pone distinto.
  if (middle > EXTENDED_RATIO && index < CURLED_RATIO && ring < CURLED_RATIO && pinky < CURLED_RATIO) {
    return 'middle_finger'
  }

  // Pulgar arriba: cuatro dedos cerrados y el pulgar estirado, por encima de la muñeca.
  const fingersCurled = [index, middle, ring, pinky].every((ratio) => ratio < CURLED_RATIO)
  const thumbExtended =
    distance(hand[THUMB_TIP], hand[WRIST]) >
    distance(hand[THUMB_KNUCKLE], hand[WRIST]) * THUMB_EXTENDED_RATIO
  const thumbPointsUp = hand[THUMB_TIP].y < hand[THUMB_KNUCKLE].y && hand[THUMB_KNUCKLE].y < hand[WRIST].y
  if (fingersCurled && thumbExtended && thumbPointsUp) return 'thumbs_up'

  return null
}

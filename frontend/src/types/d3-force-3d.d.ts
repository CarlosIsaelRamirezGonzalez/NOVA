/** Tipos de la parte de d3-force-3d que usa Nova; la librería no publica los suyos. */

declare module 'd3-force-3d' {
  /** Nodo de la simulación: la librería escribe su posición en estos campos. */
  export type ForceNode = {
    x?: number
    y?: number
    z?: number
    fx?: number
    fy?: number
    fz?: number
  }

  /** Conexión de la simulación; `source` y `target` pasan de id a nodo al iniciarla. */
  export type ForceLink<N> = {
    source: number | N
    target: number | N
  }

  /** Simulación de fuerzas. */
  export interface Simulation {
    force(name: string, force: unknown): Simulation
    stop(): Simulation
    tick(iterations?: number): Simulation
  }

  /** Fuerza de resorte entre nodos conectados. */
  export interface LinkForce<N, L> {
    id(accessor: (node: N) => number): LinkForce<N, L>
    distance(accessor: (link: L) => number): LinkForce<N, L>
    strength(accessor: (link: L) => number): LinkForce<N, L>
  }

  /** Fuerza de repulsión o atracción entre todos los nodos. */
  export interface ManyBodyForce {
    strength(value: number): ManyBodyForce
  }

  /** Fuerza que atrae cada nodo hacia un eje. */
  export interface AxisForce {
    strength(value: number): AxisForce
  }

  export function forceSimulation<N extends ForceNode>(nodes: N[], dimensions: 3): Simulation
  export function forceLink<N, L extends ForceLink<N>>(links: L[]): LinkForce<N, L>
  export function forceManyBody(): ManyBodyForce
  export function forceCollide<N>(radius: (node: N) => number): unknown
  export function forceX(position: number): AxisForce
  export function forceY(position: number): AxisForce
  export function forceZ(position: number): AxisForce
}

/** Vista de la memoria visual: lo que Nova ha notado de cómo te ves, para revisarlo y borrarlo. */

import { useEffect } from 'react'
import type { VisualObservation, VisualProfile } from '../hooks/useNova'

/** Nombre de cada campo en la interfaz. */
const FIELD_LABELS: Record<keyof VisualObservation, string> = {
  person_count: 'Personas',
  top_type: 'Prenda',
  top_color: 'Color',
  headwear: 'En la cabeza',
  glasses: 'Lentes',
  hair_length: 'Cabello',
  facial_hair: 'Vello facial',
}

/** Texto de cada valor; el backend los manda en inglés. */
const VALUE_LABELS: Record<string, string> = {
  t_shirt: 'playera',
  shirt: 'camisa',
  polo: 'polo',
  hoodie: 'sudadera',
  sweater: 'suéter',
  jacket: 'chamarra',
  tank_top: 'tirantes',
  other: 'otro',
  unknown: 'no se ve',
  black: 'negro',
  white: 'blanco',
  gray: 'gris',
  blue: 'azul',
  red: 'rojo',
  green: 'verde',
  yellow: 'amarillo',
  orange: 'naranja',
  purple: 'morado',
  pink: 'rosa',
  brown: 'café',
  beige: 'beige',
  patterned: 'estampado',
  none: 'nada',
  cap: 'gorra',
  beanie: 'gorro',
  hood: 'capucha',
  yes: 'sí',
  no: 'no',
  shaved: 'rapado',
  short: 'corto',
  medium: 'medio',
  long: 'largo',
  stubble: 'barba de días',
  beard: 'barba',
  mustache: 'bigote',
}

const OBSERVATION_FIELDS: (keyof VisualObservation)[] = [
  'top_type',
  'top_color',
  'headwear',
  'glasses',
  'hair_length',
  'facial_hair',
]

type Props = {
  profile: VisualProfile | null
  onForget: (observationId: number | null) => void
  onClose: () => void
}

/**
 * Muestra las costumbres que Nova ha notado y cada observación, con opción de borrarlas.
 *
 * @param props - Lo que ha notado y las acciones de borrar y cerrar.
 * @returns La vista a pantalla completa.
 */
export function VisualView({ profile, onForget, onClose }: Props) {
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

  const label = (value: string) => VALUE_LABELS[value] ?? value
  const observations = profile?.observations ?? []
  const trends = profile?.trends ?? []

  return (
    <section aria-label="Cómo te ve Nova" className="fixed inset-0 z-10 overflow-y-auto bg-night">
      <div className="mx-auto max-w-3xl space-y-6 p-4 md:p-8">
        <header className="flex items-start justify-between gap-4">
          <div>
            <h1 className="font-pixel text-2xl">Cómo te ve</h1>
            <p className="text-sm text-muted">
              Solo datos de las fotos que le pides. Las fotos no se guardan, y nada de cuerpo, edad, salud o ánimo.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full border border-line px-3 py-1 font-pixel text-sm text-cream outline-none hover:bg-panel focus-visible:border-glow"
          >
            Cerrar
          </button>
        </header>

        <section aria-label="Costumbres" className="space-y-2">
          <h2 className="font-pixel text-lg">Costumbres</h2>
          {trends.length === 0 ? (
            <p className="text-sm text-muted">
              Todavía ninguna: necesita al menos {profile?.min_observations ?? 5} fotos. Prueba con "¿cómo vengo hoy?".
            </p>
          ) : (
            <ul className="space-y-1">
              {trends.map((trend) => (
                <li key={trend.field} className="text-sm">
                  <span className="text-muted">{FIELD_LABELS[trend.field]}:</span> {label(trend.value)}{' '}
                  <span className="text-muted">
                    ({trend.count} de {trend.total} fotos)
                    {trend.recent_value && `, últimamente ${label(trend.recent_value)}`}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-label="Observaciones" className="space-y-2">
          <div className="flex items-center justify-between gap-4">
            <h2 className="font-pixel text-lg">Observaciones ({observations.length})</h2>
            {observations.length > 0 && (
              <button
                type="button"
                onClick={() => onForget(null)}
                className="rounded-full border border-alert px-3 py-1 font-pixel text-sm text-alert outline-none hover:bg-panel focus-visible:border-glow"
              >
                Borrar todo
              </button>
            )}
          </div>
          {observations.length === 0 ? (
            <p className="text-sm text-muted">No ha guardado nada.</p>
          ) : (
            <ul className="space-y-2">
              {observations.map((record) => (
                <li key={record.id} className="flex items-start justify-between gap-4 rounded-lg border border-line p-3">
                  <div className="min-w-0 text-sm">
                    <p className="text-muted">
                      {new Date(record.created_at * 1000).toLocaleString('es-MX', { dateStyle: 'medium', timeStyle: 'short' })}
                    </p>
                    <p>
                      {OBSERVATION_FIELDS.map(
                        (field) => `${FIELD_LABELS[field]}: ${label(String(record.observation[field]))}`,
                      ).join(' · ')}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => onForget(record.id)}
                    aria-label="Borrar esta observación"
                    className="shrink-0 rounded-full border border-line px-3 py-1 font-pixel text-sm text-cream outline-none hover:bg-panel focus-visible:border-glow"
                  >
                    Borrar
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </section>
  )
}

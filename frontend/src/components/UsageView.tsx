/** Vista de gastos: lo que Nova lleva gastado en Claude y los créditos de voz. */

import { useEffect, useId, useState } from 'react'
import type { Usage, UsageDay, UsagePurpose } from '../hooks/useNova'

/** Serie de la gráfica: cada una conserva su color aunque otra esté en cero. */
type Series = { key: 'conversation' | 'memory' | 'search'; label: string; color: string }

// Colores categóricos validados para fondo oscuro, en orden fijo.
const SERIES: Series[] = [
  { key: 'conversation', label: 'Conversación', color: '#3987e5' },
  { key: 'memory', label: 'Recuerdos', color: '#d95926' },
  { key: 'search', label: 'Búsquedas', color: '#199e70' },
]

const PURPOSE_LABELS: Record<UsagePurpose, string> = {
  conversation: 'Conversación',
  memory: 'Recuerdos',
  search: 'Búsquedas',
  voice: 'Voz (ElevenLabs)',
}

/** Precio del plan actual de ElevenLabs, que se cobra aunque Nova no hable. */
const VOICE_PLAN_USD = 22
const CHART_HEIGHT_PX = 180
const MIN_SEGMENT_PX = 2
const X_LABEL_EVERY_DAYS = 5

/**
 * Da formato a una cantidad de dólares; los gastos pequeños necesitan más decimales.
 *
 * @param amount - Cantidad en dólares.
 * @returns El texto con el signo de dólar.
 */
function money(amount: number): string {
  if (amount === 0) return '$0.00'
  if (amount < 0.01) return `$${amount.toFixed(4)}`
  return `$${amount.toFixed(2)}`
}

/**
 * Da formato a un día de la gráfica.
 *
 * @param day - Fecha en formato `YYYY-MM-DD`.
 * @returns La fecha corta, como `5 nov`.
 */
function shortDate(day: string): string {
  const [year, month, date] = day.split('-').map(Number)
  return new Date(year, month - 1, date).toLocaleDateString('es-MX', { day: 'numeric', month: 'short' })
}

/**
 * Suma lo gastado en un día.
 *
 * @param day - Día de la gráfica.
 * @returns El total en dólares.
 */
const dayTotal = (day: UsageDay) => SERIES.reduce((total, series) => total + day[series.key], 0)

/**
 * Muestra una cifra principal.
 *
 * @param props - Título, valor y nota aclaratoria.
 * @returns La tarjeta.
 */
function StatTile({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="rounded-lg border border-line p-4">
      <p className="text-sm text-muted">{label}</p>
      <p className="mt-1 text-3xl font-semibold tabular-nums">{value}</p>
      <p className="mt-1 text-xs text-muted">{note}</p>
    </div>
  )
}

/**
 * Dibuja el gasto de cada día, apilado por servicio, con barras de HTML.
 *
 * @param props - Días que se muestran.
 * @returns La gráfica con su leyenda.
 */
function DailyChart({ days }: { days: UsageDay[] }) {
  const [active, setActive] = useState<number | null>(null)
  const peak = Math.max(...days.map(dayTotal))
  const tooltipId = useId()
  const shown = active === null ? null : days[active]

  return (
    <div>
      {/* Leyenda: el color nunca es la única forma de saber qué serie es */}
      <ul className="mb-3 flex flex-wrap gap-4 text-sm text-muted">
        {SERIES.map((series) => (
          <li key={series.key} className="flex items-center gap-2">
            <span className="size-3 rounded-sm" style={{ background: series.color }} aria-hidden />
            {series.label}
          </li>
        ))}
      </ul>

      {/* Lectura del día bajo el cursor; tiene lugar fijo para que la página no brinque */}
      <p id={tooltipId} aria-live="polite" className="mb-2 min-h-5 text-sm text-muted">
        {shown ? (
          <>
            <strong className="text-cream">{money(dayTotal(shown))}</strong> el {shortDate(shown.day)}
            {SERIES.map((series) => ` · ${series.label} ${money(shown[series.key])}`).join('')}
          </>
        ) : (
          'Pasa el cursor por un día para ver el detalle.'
        )}
      </p>

      {/* Área de la gráfica: el máximo marca la escala y la línea inferior es el cero */}
      <div className="relative border-b border-line" style={{ height: CHART_HEIGHT_PX }}>
        <span className="absolute top-0 left-0 text-xs text-muted tabular-nums">{money(peak)}</span>
        <div className="absolute inset-x-0 top-0 border-t border-line/50" aria-hidden />
        <div className="absolute inset-0 flex items-end">
          {days.map((day, index) => (
            <button
              key={day.day}
              type="button"
              aria-label={`${shortDate(day.day)}: ${money(dayTotal(day))}`}
              aria-describedby={tooltipId}
              onPointerEnter={() => setActive(index)}
              onPointerLeave={() => setActive(null)}
              onFocus={() => setActive(index)}
              onBlur={() => setActive(null)}
              className={`flex h-full min-w-0 flex-1 cursor-default flex-col items-center justify-end outline-none focus-visible:bg-panel ${
                active === index ? 'bg-panel/60' : ''
              }`}
            >
              {/* Barras finas: el hueco de 2 px separa los servicios sin dibujar bordes */}
              <span className="flex w-full max-w-6 flex-col-reverse gap-0.5 px-px">
                {SERIES.filter((series) => day[series.key] > 0).map((series, position, visible) => (
                  <span
                    key={series.key}
                    className={position === visible.length - 1 ? 'rounded-t' : ''}
                    style={{
                      background: series.color,
                      height: Math.max(MIN_SEGMENT_PX, (day[series.key] / peak) * (CHART_HEIGHT_PX - 20)),
                    }}
                  />
                ))}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Fechas: solo algunas, para que no se encimen */}
      <div className="mt-1 flex text-xs text-muted">
        {days.map((day, index) => (
          <span key={day.day} className="min-w-0 flex-1 overflow-visible whitespace-nowrap">
            {index % X_LABEL_EVERY_DAYS === 0 ? shortDate(day.day) : ''}
          </span>
        ))}
      </div>
    </div>
  )
}

/** Propiedades de {@link UsageView}. */
type Props = {
  usage: Usage | null
  onClose: () => void
}

/**
 * Muestra los gastos a pantalla completa.
 *
 * @param props - Datos de gastos y la acción de cerrar.
 * @returns La vista de gastos.
 */
export function UsageView({ usage, onClose }: Props) {
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

  const voice = usage?.voice ?? null
  const voiceShare = voice && voice.limit > 0 ? Math.min(1, voice.used / voice.limit) : 0
  const hasSpending = Boolean(usage?.days.some((day) => dayTotal(day) > 0))

  return (
    <section aria-label="Gastos de las APIs" className="fixed inset-0 z-10 overflow-y-auto bg-night">
      <div className="mx-auto max-w-4xl space-y-6 p-4 md:p-8">
        <header className="flex items-start justify-between gap-4">
          <div>
            <h1 className="font-pixel text-2xl">Gastos</h1>
            <p className="text-sm text-muted">
              Estimados con los tokens que reporta cada API, desde que se activó este registro.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full border border-line px-3 py-1 font-pixel text-sm outline-none hover:bg-panel focus-visible:border-glow"
          >
            Cerrar
          </button>
        </header>

        {!usage ? (
          <p className="text-muted">Cargando…</p>
        ) : (
          <>
            {/* Cifras principales */}
            <div className="grid gap-3 sm:grid-cols-3">
              <StatTile label="Claude hoy" value={money(usage.today_usd)} note="Conversación, recuerdos y búsquedas" />
              <StatTile label="Claude este mes" value={money(usage.month_usd)} note="Se cobra según el uso" />
              <StatTile
                label="Total del mes"
                value={money(usage.month_usd + VOICE_PLAN_USD)}
                note={`Incluye el plan de voz de ${money(VOICE_PLAN_USD)} al mes`}
              />
            </div>

            {/* Créditos de voz, tal como los reporta ElevenLabs */}
            <div className="rounded-lg border border-line p-4">
              <h2 className="font-pixel text-lg">Créditos de voz</h2>
              {voice ? (
                <>
                  <p className="mt-1 text-sm text-muted">
                    <strong className="text-cream tabular-nums">{voice.used.toLocaleString('es-MX')}</strong> de{' '}
                    {voice.limit.toLocaleString('es-MX')} usados · Plan {voice.tier}
                    {voice.resets_at &&
                      ` · Se renuevan el ${new Date(voice.resets_at * 1000).toLocaleDateString('es-MX', { day: 'numeric', month: 'long' })}`}
                  </p>
                  <div
                    role="progressbar"
                    aria-label="Créditos de voz usados"
                    aria-valuenow={Math.round(voiceShare * 100)}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    className="mt-3 h-2 overflow-hidden rounded-full bg-panel"
                  >
                    <div className="h-full rounded-full bg-glow" style={{ width: `${voiceShare * 100}%` }} />
                  </div>
                </>
              ) : (
                <p className="mt-1 text-sm text-muted">No pude consultar los créditos en ElevenLabs.</p>
              )}
            </div>

            {/* Gasto diario */}
            <div className="rounded-lg border border-line p-4">
              <h2 className="mb-3 font-pixel text-lg">Claude por día, últimos 30 días</h2>
              {hasSpending ? (
                <DailyChart days={usage.days} />
              ) : (
                <p className="text-sm text-muted">Todavía no hay gastos registrados. Platica con Nova y aparecerán aquí.</p>
              )}
            </div>

            {/* Desglose: da en texto todo lo que muestra la gráfica */}
            <div className="overflow-x-auto rounded-lg border border-line p-4">
              <h2 className="mb-3 font-pixel text-lg">Este mes por servicio</h2>
              <table className="w-full text-sm">
                <thead className="text-left text-muted">
                  <tr>
                    <th scope="col" className="py-1 pr-4 font-normal">Servicio</th>
                    <th scope="col" className="py-1 pr-4 text-right font-normal">Llamadas</th>
                    <th scope="col" className="py-1 pr-4 text-right font-normal">Tokens</th>
                    <th scope="col" className="py-1 pr-4 text-right font-normal">Búsquedas</th>
                    <th scope="col" className="py-1 pr-4 text-right font-normal">Créditos</th>
                    <th scope="col" className="py-1 text-right font-normal">Costo</th>
                  </tr>
                </thead>
                <tbody className="tabular-nums">
                  {usage.services.map((service) => (
                    <tr key={service.purpose} className="border-t border-line">
                      <th scope="row" className="py-2 pr-4 text-left font-normal">{PURPOSE_LABELS[service.purpose]}</th>
                      <td className="py-2 pr-4 text-right">{service.calls.toLocaleString('es-MX')}</td>
                      <td className="py-2 pr-4 text-right">{(service.input_tokens + service.output_tokens).toLocaleString('es-MX')}</td>
                      <td className="py-2 pr-4 text-right">{service.searches.toLocaleString('es-MX')}</td>
                      <td className="py-2 pr-4 text-right">{service.credits.toLocaleString('es-MX')}</td>
                      <td className="py-2 text-right">{service.purpose === 'voice' ? 'En el plan' : money(service.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <p className="text-xs text-muted">
              Para el cobro exacto, revisa{' '}
              <a href="https://console.anthropic.com" target="_blank" rel="noopener noreferrer" className="underline hover:text-cream">
                la consola de Anthropic
              </a>{' '}
              y{' '}
              <a href="https://elevenlabs.io/app/subscription" target="_blank" rel="noopener noreferrer" className="underline hover:text-cream">
                tu suscripción de ElevenLabs
              </a>
              . Los gastos de antes de activar este registro no aparecen aquí.
            </p>
          </>
        )}
      </div>
    </section>
  )
}

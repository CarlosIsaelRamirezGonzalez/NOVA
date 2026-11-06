/** Hook que decide cuándo se ve la ventana flotante de Nova. */

import { useEffect, useRef, useState } from 'react'

type PresenceCommand = 'toggle' | 'summon'

type PresenceBridge = {
  setPresent: (present: boolean) => Promise<void>
  onPresenceCommand: (handler: (command: PresenceCommand) => void) => () => void
}

const bridge = (window as unknown as { novaDesktop?: PresenceBridge }).novaDesktop

/** Espera antes de irse, para no parpadear entre escucharte y responderte. */
const LINGER_MS = 2500
/** Lo que dura la animación de salida; debe coincidir con `.nova-presence` en `index.css`. */
const EXIT_MS = 380
/** Cuánto se queda si la muestras desde la barra de menú. */
const SUMMON_MS = 15_000

/**
 * Muestra a Nova mientras tiene algo que hacer y la oculta cuando vuelve a esperar.
 *
 * @param isWidget - Si esta pantalla es la ventana flotante; en las demás no hace nada.
 * @param isActive - Si te está escuchando o respondiendo; esto siempre la hace aparecer.
 * @param needsAttention - Si tiene un aviso o no puede oírte; se puede ocultar a mano.
 * @returns Si ya debe verse en pantalla y cómo avisar que el cursor está encima.
 */
export function useWidgetPresence(isWidget: boolean, isActive: boolean, needsAttention: boolean) {
  const [hovered, setHovered] = useState(false)
  const [summoned, setSummoned] = useState(false)
  const [dismissed, setDismissed] = useState(false)
  const [entered, setEntered] = useState(true)

  const enabled = isWidget && Boolean(bridge)
  const wanted = isActive || (!dismissed && (needsAttention || hovered || summoned))
  const latestWanted = useRef(wanted)

  useEffect(() => {
    latestWanted.current = wanted
  })

  // Si vuelve a tener algo que hacer, deja de contar que la ocultaste a mano.
  useEffect(() => {
    if (isActive) setDismissed(false)
  }, [isActive])

  // Atiende lo que se pide desde la barra de menú.
  useEffect(() => {
    if (!enabled || !bridge) return
    return bridge.onPresenceCommand((command) => {
      if (command === 'toggle' && latestWanted.current) {
        setHovered(false)
        setSummoned(false)
        setDismissed(true)
        return
      }
      setDismissed(false)
      setSummoned(true)
    })
  }, [enabled])

  // Mostrarla desde la barra de menú no la deja ahí para siempre.
  useEffect(() => {
    if (!summoned) return
    const timer = setTimeout(() => setSummoned(false), SUMMON_MS)
    return () => clearTimeout(timer)
  }, [summoned])

  useEffect(() => {
    if (!enabled || !bridge) return
    const { setPresent } = bridge

    // Primero se abre la ventana y ya visible se anima; oculta no se pinta nada.
    if (wanted) {
      let cancelled = false
      let frame = 0
      void setPresent(true).then(() => {
        if (!cancelled) frame = requestAnimationFrame(() => setEntered(true))
      })
      return () => {
        cancelled = true
        cancelAnimationFrame(frame)
      }
    }

    // Primero se anima la salida y al terminar se cierra la ventana.
    const delay = dismissed ? 0 : LINGER_MS
    const leave = setTimeout(() => setEntered(false), delay)
    const hide = setTimeout(() => void setPresent(false), delay + EXIT_MS)
    return () => {
      clearTimeout(leave)
      clearTimeout(hide)
    }
  }, [enabled, wanted, dismissed])

  return { entered, setHovered }
}

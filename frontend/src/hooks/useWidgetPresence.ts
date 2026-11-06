/** Hook que decide cuándo se ve la ventana flotante de Nova. */

import { useCallback, useEffect, useRef, useState } from 'react'

type PresenceCommand = 'toggle' | 'summon' | 'dismiss'

type PresenceBridge = {
  setPresent: (present: boolean) => Promise<void>
  onPresenceCommand: (handler: (command: PresenceCommand) => void) => () => void
}

const bridge = (window as unknown as { novaDesktop?: PresenceBridge }).novaDesktop

/** Espera antes de irse, para no parpadear entre escucharte y responderte. */
const LINGER_MS = 2500
/** Lo que dura la animación de salida; debe coincidir con `.nova-presence` en `index.css`. */
const EXIT_MS = 380
/** Cuánto se queda sin que esté haciendo nada: tras un aviso, tras responderte o si la muestras. */
const SUMMON_MS = 10_000
/** El cursor quieto encima de la ventana no la deja ahí para siempre. */
const HOVER_MS = 6000

/**
 * Muestra a Nova solo mientras la ocupas. Oculta sigue oyendo: el micrófono no depende de esto.
 *
 * @param isWidget - Si esta pantalla es la ventana flotante; en las demás no hace nada.
 * @param isActive - Si te oyó o te está respondiendo; esto siempre la hace aparecer.
 * @param isBrief - Si hay un aviso o acaba de responderte; se queda solo unos segundos.
 * @returns Si ya debe verse en pantalla y cómo avisar que el cursor está encima.
 */
export function useWidgetPresence(isWidget: boolean, isActive: boolean, isBrief: boolean) {
  const [hovered, setHovered] = useState(false)
  const [summoned, setSummoned] = useState(false)
  const [dismissed, setDismissed] = useState(false)
  const [entered, setEntered] = useState(true)

  const enabled = isWidget && Boolean(bridge)
  const wanted = isActive || (!dismissed && (hovered || summoned))
  const latestWanted = useRef(wanted)
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  // Cada movimiento del cursor encima de ella le da unos segundos más.
  const noteHover = useCallback(() => {
    setHovered(true)
    clearTimeout(hoverTimer.current)
    hoverTimer.current = setTimeout(() => setHovered(false), HOVER_MS)
  }, [])
  const endHover = useCallback(() => {
    clearTimeout(hoverTimer.current)
    setHovered(false)
  }, [])
  useEffect(() => () => clearTimeout(hoverTimer.current), [])

  useEffect(() => {
    latestWanted.current = wanted
  })

  // Si vuelve a tener algo que hacer, deja de contar que la ocultaste a mano.
  useEffect(() => {
    if (isActive) setDismissed(false)
  }, [isActive])

  useEffect(() => {
    if (isBrief) setSummoned(true)
  }, [isBrief])

  // Atiende lo que se pide desde la barra de menú o con la voz.
  useEffect(() => {
    if (!enabled || !bridge) return
    return bridge.onPresenceCommand((command) => {
      if (command === 'dismiss' || (command === 'toggle' && latestWanted.current)) {
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

  return { entered, noteHover, endHover }
}

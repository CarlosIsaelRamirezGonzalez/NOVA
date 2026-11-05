/** Hook de conversación por voz con la API del navegador. */

import { useCallback, useEffect, useRef, useState } from 'react'

// Tipos mínimos de la API de voz del navegador, que TypeScript no incluye de forma estándar.
type RecognitionResultEvent = {
  results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }>
}

type Recognition = {
  lang: string
  interimResults: boolean
  onresult: ((event: RecognitionResultEvent) => void) | null
  onend: (() => void) | null
  onerror: ((event: { error: string }) => void) | null
  start: () => void
  stop: () => void
  abort: () => void
}

type RecognitionConstructor = new () => Recognition

// La API lleva prefijo `webkit` en Chrome y Safari.
const speechWindow = window as unknown as {
  SpeechRecognition?: RecognitionConstructor
  webkitSpeechRecognition?: RecognitionConstructor
}
const SpeechRecognitionApi =
  speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition

/** Mensaje para el usuario según el código de error del dictado. */
const MIC_ERRORS: Record<string, string> = {
  'not-allowed': 'El navegador bloqueó el micrófono. Permítelo con el icono junto a la dirección.',
  'service-not-allowed': 'Este navegador tiene desactivado el dictado por voz.',
  'audio-capture': 'No se detectó micrófono. Revisa Ajustes del Sistema > Privacidad > Micrófono.',
  network: 'El servicio de dictado del navegador no respondió. Usa Chrome o escribe tu mensaje.',
  'language-not-supported': 'El navegador no admite dictado en español.',
}

/** Errores normales de una escucha, que no deben terminar la conversación. */
const RECOVERABLE_ERRORS = ['no-speech', 'aborted']

/** Espera antes de volver a abrir el micrófono. */
const RESTART_DELAY_MS = 350

/**
 * Conversación por voz con la API del navegador (Chrome, Edge y Safari). Mientras esté activa,
 * escucha un turno, lo entrega al detectar la pausa y vuelve a escuchar en cuanto puede.
 *
 * @param onInterim - Recibe el texto parcial mientras el usuario habla; vacío si ya terminó.
 * @param onFinal - Recibe el texto completo de cada turno.
 * @param canListen - Si se puede escuchar ahora. El micrófono se apaga mientras Nova responde,
 *   porque se oiría a sí misma por las bocinas y se contestaría sola.
 * @returns Si hay soporte, si la conversación está activa, si está escuchando, el último error
 *   y la acción de iniciar o terminar.
 */
export function useDictation(
  onInterim: (text: string) => void,
  onFinal: (text: string) => void,
  canListen: boolean,
) {
  const [conversing, setConversing] = useState(false)
  const [listening, setListening] = useState(false)
  const [micError, setMicError] = useState<string | null>(null)
  // Sube cada vez que termina una escucha, para que el efecto de abajo arranque la siguiente.
  const [finishedListens, setFinishedListens] = useState(0)
  const recognition = useRef<Recognition | null>(null)
  const discardTurn = useRef(false)
  const callbacks = useRef({ onInterim, onFinal })

  // Guarda las funciones actuales sin tener que reiniciar el reconocimiento.
  useEffect(() => {
    callbacks.current = { onInterim, onFinal }
  })

  // Apaga el micrófono al desmontar.
  useEffect(() => () => recognition.current?.abort(), [])

  // Crea y arranca un reconocimiento para un turno.
  const startListening = useCallback(() => {
    if (!SpeechRecognitionApi || recognition.current) return

    const instance = new SpeechRecognitionApi()
    instance.lang = 'es-MX'
    instance.interimResults = true
    let transcript = ''
    discardTurn.current = false

    // Conecta los eventos: resultados, errores y final de la escucha.
    instance.onresult = (event) => {
      transcript = Array.from(event.results, (result) => result[0].transcript).join('')
      callbacks.current.onInterim(transcript)
    }
    instance.onerror = (event) => {
      // Un silencio no es un fallo: la conversación simplemente sigue escuchando.
      if (RECOVERABLE_ERRORS.includes(event.error)) return

      // Reintentar los demás errores no serviría y entraría en un ciclo: se termina y se avisa.
      console.error('Error de dictado:', event.error)
      setConversing(false)
      setMicError(MIC_ERRORS[event.error] ?? `El dictado falló (${event.error}).`)
    }
    instance.onend = () => {
      recognition.current = null
      setListening(false)
      callbacks.current.onInterim('')
      if (transcript.trim() && !discardTurn.current) callbacks.current.onFinal(transcript.trim())
      setFinishedListens((count) => count + 1)
    }

    // Arranca la escucha; `start` lanza un error si el navegador no puede iniciarla.
    recognition.current = instance
    setListening(true)
    try {
      instance.start()
    } catch (cause) {
      console.error('No se pudo iniciar el dictado', cause)
      recognition.current = null
      setListening(false)
      setConversing(false)
      setMicError('No pude iniciar el micrófono. Recarga la página e inténtalo otra vez.')
    }
  }, [])

  // Escucha cuando le toca al usuario, y suelta el micrófono cuando le toca a Nova.
  useEffect(() => {
    if (conversing && canListen) {
      // La pausa evita captar el final de la voz de Nova que aún resuena en la habitación.
      const timer = setTimeout(startListening, RESTART_DELAY_MS)
      return () => clearTimeout(timer)
    }
    if (conversing && recognition.current) {
      discardTurn.current = true
      recognition.current.abort()
    }
  }, [conversing, canListen, finishedListens, startListening])

  // Al terminar se envía lo que ya se alcanzó a decir, en vez de perderlo.
  const toggle = useCallback(() => {
    setMicError(null)
    setConversing((active) => !active)
    recognition.current?.stop()
  }, [])

  return { supported: Boolean(SpeechRecognitionApi), conversing, listening, micError, toggle }
}

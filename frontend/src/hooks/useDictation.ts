/** Hook de dictado por voz con la API del navegador. */

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
  'no-speech': 'No te escuché. Pulsa Hablar e inténtalo otra vez.',
  network: 'El servicio de dictado del navegador no respondió. Usa Chrome o escribe tu mensaje.',
  'language-not-supported': 'El navegador no admite dictado en español.',
}

/**
 * Dictado por voz con la API del navegador (Chrome, Edge y Safari).
 *
 * @param onInterim - Recibe el texto parcial mientras el usuario habla.
 * @param onFinal - Recibe el texto completo al terminar.
 * @returns Si hay soporte, si está escuchando, el último error y la acción de activar o detener.
 */
export function useDictation(onInterim: (text: string) => void, onFinal: (text: string) => void) {
  const [listening, setListening] = useState(false)
  const [micError, setMicError] = useState<string | null>(null)
  const recognition = useRef<Recognition | null>(null)
  const callbacks = useRef({ onInterim, onFinal })

  // Guarda las funciones actuales sin tener que reiniciar el reconocimiento.
  useEffect(() => {
    callbacks.current = { onInterim, onFinal }
  })

  // Apaga el micrófono al desmontar.
  useEffect(() => () => recognition.current?.stop(), [])

  // Si ya escucha, se detiene; si no, crea y arranca un reconocimiento nuevo.
  const toggle = useCallback(() => {
    if (recognition.current) {
      recognition.current.stop()
      return
    }
    if (!SpeechRecognitionApi) return

    const instance = new SpeechRecognitionApi()
    instance.lang = 'es-MX'
    instance.interimResults = true
    let transcript = ''

    // Conecta los eventos: resultados, errores y final de la escucha.
    instance.onresult = (event) => {
      transcript = Array.from(event.results, (result) => result[0].transcript).join('')
      callbacks.current.onInterim(transcript)
    }
    instance.onerror = (event) => {
      console.error('Error de dictado:', event.error)
      if (event.error !== 'aborted') {
        setMicError(MIC_ERRORS[event.error] ?? `El dictado falló (${event.error}).`)
      }
    }
    instance.onend = () => {
      recognition.current = null
      setListening(false)
      if (transcript.trim()) callbacks.current.onFinal(transcript.trim())
    }

    // Arranca la escucha; `start` lanza un error si el navegador no puede iniciarla.
    setMicError(null)
    recognition.current = instance
    setListening(true)
    try {
      instance.start()
    } catch (cause) {
      console.error('No se pudo iniciar el dictado', cause)
      recognition.current = null
      setListening(false)
      setMicError('No pude iniciar el micrófono. Recarga la página e inténtalo otra vez.')
    }
  }, [])

  return { supported: Boolean(SpeechRecognitionApi), listening, micError, toggle }
}

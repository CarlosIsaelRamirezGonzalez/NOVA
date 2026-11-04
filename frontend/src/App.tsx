/** Interfaz principal de Nova. */

import { useEffect, useRef, useState, type FormEvent } from 'react'
import { BrainView } from './components/BrainView'
import { NovaSprite } from './components/NovaSprite'
import { useCamera } from './hooks/useCamera'
import { useDictation } from './hooks/useDictation'
import { useNova } from './hooks/useNova'
import { describeBlend, type Activity, type EmotionBlend } from './nova/emotions'
import type { Gesture } from './nova/gestures'

/** Texto del estado según lo que está haciendo Nova. */
const STATUS: Record<Activity, string> = {
  idle: 'En línea',
  listening: 'Escuchando',
  thinking: 'Pensando',
  speaking: 'Hablando',
}

/**
 * Quita las marcas de voz ([laugh], <whisper>…), que son para el TTS y no para leerlas.
 *
 * @param text - Respuesta de Nova, posiblemente aún incompleta.
 * @returns El texto listo para mostrarse.
 */
const stripMarkup = (text: string) =>
  text
    .replace(/\[\/?[a-z-]+\]|<\/?[a-z-]+>/g, '')
    .replace(/[[<][a-z/-]*$/, '')
    .replace(/ {2,}/g, ' ')
    .trim()

/**
 * Pantalla principal: el personaje, el chat y el cuadro de mensajes.
 *
 * @returns La interfaz completa.
 */
/**
 * Combina lo que Nova siente con sus reacciones instintivas a la cámara.
 *
 * @param feeling - Emociones de la conversación.
 * @param reflex - Reacción a lo que detecta la cámara.
 * @returns La mezcla que muestra el personaje; de cada emoción gana la más intensa.
 */
function combineBlends(feeling: EmotionBlend, reflex: EmotionBlend): EmotionBlend {
  const extra = reflex.filter((item) => !feeling.some((other) => other.name === item.name))
  return [
    ...feeling.map((item) => ({
      name: item.name,
      intensity: Math.max(
        item.intensity,
        reflex.find((other) => other.name === item.name)?.intensity ?? 0,
      ),
    })),
    ...extra,
  ]
}

export default function App() {
  // Estado de la conversación y del cuadro de texto.
  const video = useRef<HTMLVideoElement>(null)
  const onGesture = useRef<(gesture: Gesture) => void>(() => {})
  const camera = useCamera(video, onGesture)
  const {
    connected,
    phase,
    blend,
    calmCount,
    photoCount,
    interruptCount,
    photosRemaining,
    messages,
    error,
    send,
    calm,
    interrupt,
    sendGesture,
    brain,
    recall,
    requestBrain,
    forgetMemory,
    unlockAudio,
    getLevel,
  } = useNova(camera.capture, camera.active)
  const [draft, setDraft] = useState('')
  const [brainOpen, setBrainOpen] = useState(false)
  const transcript = useRef<HTMLDivElement>(null)
  const busy = phase !== 'idle'

  // El dictado rellena el cuadro mientras se habla y envía al terminar.
  const dictation = useDictation(setDraft, (text) => {
    setDraft('')
    send(text)
  })

  // La actividad del personaje combina la fase del turno con lo que hace el usuario.
  const activity: Activity =
    phase !== 'idle' ? phase : dictation.listening || draft ? 'listening' : 'idle'

  // Nova solo reacciona a un gesto si no está ocupada respondiendo.
  useEffect(() => {
    onGesture.current = (gesture) => {
      if (connected && !busy) sendGesture(gesture)
    }
  })

  // Mantiene visible el último mensaje.
  useEffect(() => {
    transcript.current?.scrollTo({ top: transcript.current.scrollHeight })
  }, [messages])

  // Envía el mensaje escrito si hay texto y Nova puede atenderlo.
  // Envía lo escrito. Si Nova está respondiendo, primero la interrumpe.
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!connected) return
    const text = draft.trim()
    if (busy) interrupt()
    if (!text) return
    setDraft('')
    send(text)
  }

  // La tecla Esc también la interrumpe.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && busy) interrupt()
    }
    addEventListener('keydown', onKeyDown)
    return () => removeEventListener('keydown', onKeyDown)
  }, [busy, interrupt])

  const notice = error ?? dictation.micError ?? camera.cameraError

  return (
    <main className="mx-auto flex h-dvh max-w-2xl flex-col px-4 pb-4">
      {/* Personaje y estado */}
      <section className="flex h-[56dvh] min-h-64 shrink-0 flex-col items-center justify-end pt-4">
        {/* El lienzo se adapta al espacio que queda sobre el texto de estado */}
        <div className="min-h-0 w-full flex-1">
          <NovaSprite
            blend={combineBlends(blend, camera.reflex)}
            activity={activity}
            lookAtInput={Boolean(draft) && phase === 'idle'}
            calmCount={calmCount}
            photoCount={photoCount}
            interruptCount={interruptCount}
            getFace={camera.getFace}
            getLevel={getLevel}
          />
        </div>
        {/* Actividad actual y lo que está sintiendo */}
        <div className="mt-1 flex flex-wrap items-center justify-center gap-x-3 gap-y-1">
          <p role="status" className="flex items-center gap-2 font-pixel text-base text-muted">
            <span
              className={`size-2 rounded-full ${connected ? 'bg-glow' : 'bg-line'}`}
              aria-hidden
            />
            {connected
              ? [STATUS[activity], describeBlend(blend)].filter(Boolean).join(' · ')
              : 'Conectando con el servidor…'}
          </p>

          {/* La cámara empieza apagada y siempre se ve cuando está encendida */}
          <button
            type="button"
            onClick={() => void camera.toggle()}
            disabled={camera.waitingForPermission}
            aria-pressed={camera.active}
            className={`flex items-center gap-2 rounded-full border px-3 py-1 font-pixel text-sm outline-none focus-visible:border-glow disabled:opacity-60 ${
              camera.active ? 'border-alert text-alert' : 'border-line text-cream hover:bg-panel'
            }`}
          >
            {camera.active && <span className="size-2 rounded-full bg-alert" aria-hidden />}
            {camera.active
              ? 'Apagar cámara'
              : camera.waitingForPermission
                ? 'Esperando permiso…'
                : 'Cámara'}
          </button>

          {/* Abre la vista de su memoria */}
          <button
            type="button"
            onClick={() => {
              requestBrain()
              setBrainOpen(true)
            }}
            disabled={!connected}
            className="rounded-full border border-line px-3 py-1 font-pixel text-sm text-cream outline-none hover:bg-panel focus-visible:border-glow disabled:opacity-40"
          >
            Cerebro
          </button>

          {/* Solo aparece si siente algo; durante una respuesta queda desactivado */}
          {connected && blend.length > 0 && (
            <button
              type="button"
              onClick={calm}
              disabled={busy}
              className="rounded-full border border-line px-3 py-1 font-pixel text-sm text-cream outline-none hover:bg-panel focus-visible:border-glow disabled:opacity-40"
            >
              Calmar
            </button>
          )}
        </div>
      </section>

      {/* Su memoria, a pantalla completa */}
      {brainOpen && (
        <BrainView
          brain={brain}
          recall={recall}
          mood={blend}
          onForget={forgetMemory}
          onClose={() => setBrainOpen(false)}
        />
      )}

      {/* Vista previa en espejo: muestra lo que puede ver Nova */}
      {camera.active && (
        <figure className="fixed top-4 right-4 w-28 md:w-40">
          <video
            ref={video}
            autoPlay
            muted
            playsInline
            aria-label="Vista previa de tu cámara"
            className="w-full -scale-x-100 rounded-lg border-2 border-alert"
          />
          {photosRemaining !== null && (
            <figcaption className="mt-1 text-center font-pixel text-xs text-muted">
              Quedan {photosRemaining} fotos hoy
            </figcaption>
          )}
        </figure>
      )}

      {/* Historial del chat */}
      <div
        ref={transcript}
        aria-live="polite"
        className="my-4 min-h-0 flex-1 space-y-4 overflow-y-auto"
      >
        {/* El usuario se alinea a la derecha; Nova ocupa el ancho de lectura */}
        {/* Se omite el texto vacío: una respuesta puede empezar con solo una etiqueta */}
        {messages
          .filter((message) => message.role !== 'nova' || stripMarkup(message.text))
          .map((message) =>
          message.role === 'photo' ? (
            <img
              key={message.id}
              src={message.text}
              alt="Foto que tomó Nova con tu cámara"
              className="ml-auto w-40 -scale-x-100 rounded-lg border border-line"
            />
          ) : (
          <p
            key={message.id}
            className={
              message.role === 'user'
                ? 'ml-auto w-fit max-w-[85%] rounded-2xl bg-panel px-4 py-2 whitespace-pre-wrap text-muted'
                : 'max-w-[92%] text-lg leading-relaxed whitespace-pre-wrap'
            }
          >
            {message.role === 'nova' ? stripMarkup(message.text) : message.text}
          </p>
          ),
        )}
      </div>

      {/* Errores de conexión o del micrófono */}
      {notice && (
        <p role="alert" className="mb-2 text-sm text-alert">
          {notice}
        </p>
      )}

      {/* Cuadro de mensajes y botones */}
      <form onSubmit={submit} className="flex items-center gap-2">
        <label htmlFor="message" className="sr-only">
          Mensaje para Nova
        </label>
        {/* Campo de texto */}
        <input
          id="message"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Escríbele a Nova…"
          autoComplete="off"
          autoFocus
          maxLength={4000}
          className="h-12 min-w-0 flex-1 rounded-full border border-line bg-panel px-5 text-base outline-none placeholder:text-muted focus:border-glow"
        />
        {/* Dictado, solo si el navegador lo admite */}
        {dictation.supported && (
          <button
            type="button"
            onClick={() => {
              unlockAudio()
              // Hablar mientras ella habla también es interrumpirla.
              if (busy) interrupt()
              dictation.toggle()
            }}
            disabled={!connected}
            aria-pressed={dictation.listening}
            className={`h-12 rounded-full border px-4 text-sm font-medium outline-none focus-visible:border-glow disabled:opacity-40 ${
              dictation.listening
                ? 'border-glow bg-glow text-night'
                : 'border-line text-cream hover:bg-panel'
            }`}
          >
            {dictation.listening ? 'Listo' : 'Hablar'}
          </button>
        )}
        {/* Enviar, o interrumpir si Nova está respondiendo y no hay nada escrito */}
        <button
          type="submit"
          disabled={!connected || (!busy && !draft.trim())}
          className="h-12 rounded-full bg-glow px-5 text-sm font-semibold text-night outline-none hover:brightness-110 focus-visible:ring-2 focus-visible:ring-cream disabled:opacity-40"
        >
          {busy && !draft.trim() ? 'Interrumpir' : 'Enviar'}
        </button>
      </form>
    </main>
  )
}

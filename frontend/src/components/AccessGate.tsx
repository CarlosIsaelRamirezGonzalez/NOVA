/** Pide la contraseña en la web y en la extensión antes de mostrar a Nova; en la Mac no aparece. */

import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { IS_EXTENSION, apiUrl, saveToken, sessionHeaders } from '../nova/server'

/** Respuesta del servidor sobre la sesión; `token` solo llega si la extensión lo pidió. */
type SessionStatus = { required: boolean; authenticated: boolean; token?: string | null }

// La página usa su cookie; la extensión, que es otro sitio, manda su token y no usa cookies.
const CREDENTIALS: RequestCredentials = IS_EXTENSION ? 'omit' : 'same-origin'

type GateState = 'checking' | 'login' | 'ready'

/**
 * Muestra a Nova solo cuando el servidor lo permite.
 *
 * @param children La aplicación, que se monta hasta tener sesión.
 */
export function AccessGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<GateState>('checking')
  const [password, setPassword] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Pregunta una sola vez al abrir: la cookie no se puede leer desde la página, a propósito.
  useEffect(() => {
    const check = async () => {
      try {
        const response = await fetch(apiUrl('/api/session'), { credentials: CREDENTIALS, headers: sessionHeaders() })
        // Un servidor sin esta ruta no pide contraseña.
        if (!response.ok) return setState('ready')
        const status = (await response.json()) as SessionStatus
        setState(status.required && !status.authenticated ? 'login' : 'ready')
      } catch {
        // Sin servidor, la aplicación ya muestra que está desconectada y se reconecta sola.
        setState('ready')
      }
    }
    void check()
  }, [])

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSending(true)
    setError(null)
    try {
      const response = await fetch(apiUrl('/api/login'), {
        method: 'POST',
        credentials: CREDENTIALS,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password, want_token: IS_EXTENSION }),
      })
      if (response.ok) {
        if (IS_EXTENSION) saveToken(((await response.json()) as SessionStatus).token ?? null)
        setPassword('')
        setState('ready')
        return
      }
      setError(response.status === 401 ? 'Contraseña incorrecta.' : 'No se pudo entrar. Intenta de nuevo.')
    } catch {
      setError('Sin conexión con el servidor. Revisa tu internet e intenta de nuevo.')
    } finally {
      setSending(false)
    }
  }

  if (state === 'ready') return children
  if (state === 'checking') return <main className="h-dvh bg-night" aria-busy="true" />

  return (
    <main className="flex h-dvh items-center justify-center px-4">
      <form
        onSubmit={(event) => void submit(event)}
        className="flex w-full max-w-xs flex-col gap-4 rounded-2xl border border-line bg-panel p-6"
      >
        <h1 className="font-pixel text-3xl text-cream">Nova</h1>
        <label className="flex flex-col gap-2 text-sm text-muted">
          Contraseña
          <input
            type="password"
            autoComplete="current-password"
            autoFocus
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="rounded-lg border border-line bg-night px-3 py-2 text-base text-cream outline-none focus-visible:border-glow"
          />
        </label>
        {error && (
          <p role="alert" className="text-sm text-alert">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={sending || !password}
          className="rounded-full border border-glow px-4 py-2 font-pixel text-cream outline-none hover:bg-line focus-visible:bg-line disabled:opacity-50"
        >
          {sending ? 'Entrando…' : 'Entrar'}
        </button>
      </form>
    </main>
  )
}

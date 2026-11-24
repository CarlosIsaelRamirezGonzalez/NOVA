/**
 * A qué servidor se conecta la interfaz.
 *
 * En la Mac y en la web, al mismo sitio que sirvió la página, con una cookie. En la extensión de
 * Chrome, al servidor de Vercel con un token: la página vive en `chrome-extension://` y la cookie
 * de Vercel no le llega.
 */

/** Si la interfaz corre como panel lateral de la extensión de Chrome. */
export const IS_EXTENSION = location.protocol === 'chrome-extension:'

// Se puede cambiar al compilar: `VITE_NOVA_SERVER=https://otro.vercel.app npm run build:extension`.
const EXTENSION_SERVER: string = import.meta.env.VITE_NOVA_SERVER ?? 'https://nova-teal-two.vercel.app'
const TOKEN_KEY = 'nova-session-token'

/**
 * Dirección completa de una ruta de la API.
 *
 * @param path - Ruta, por ejemplo `/api/session`.
 * @returns La ruta tal cual en la página, o con el servidor de Vercel en la extensión.
 */
export function apiUrl(path: string): string {
  return IS_EXTENSION ? new URL(path, EXTENSION_SERVER).href : path
}

/**
 * Dirección del WebSocket de Nova.
 *
 * @returns `ws://` o `wss://` según el servidor.
 */
export function socketUrl(): string {
  const base = IS_EXTENSION ? new URL(EXTENSION_SERVER) : location
  const scheme = base.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${base.host}/ws`
}

/**
 * Lee el token de la extensión. Solo vive en el almacenamiento de la propia extensión.
 *
 * @returns El token, o `null` si todavía no entra o el almacenamiento no está disponible.
 */
export function readToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

/**
 * Guarda o borra el token de la extensión.
 *
 * @param token - El token que dio el servidor al entrar, o `null` para olvidarlo.
 */
export function saveToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    // Sin almacenamiento, se vuelve a pedir la contraseña la próxima vez.
  }
}

/**
 * Encabezados con la sesión: el token en la extensión; nada en la página, que usa su cookie.
 *
 * @returns Los encabezados para `fetch`.
 */
export function sessionHeaders(): Record<string, string> {
  const token = IS_EXTENSION ? readToken() : null
  return token ? { Authorization: `Bearer ${token}` } : {}
}

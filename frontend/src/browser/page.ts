/**
 * Funciones que la extensión ejecuta dentro de una pestaña con `chrome.scripting`.
 *
 * Chrome las copia como texto a la página, así que cada una debe bastarse sola: nada de importar
 * ni de usar variables de fuera. Por eso las expresiones que comparten se repiten.
 */

/** Lo que se lee de una página para el modelo. */
export type PageSnapshot = { title: string; url: string; text: string; elements: string }

/** Lo que se sabe de un elemento antes de tocarlo: `costsMoney` pide confirmación, `secret` se bloquea. */
export type ElementCheck = { found: boolean; label: string; costsMoney: boolean; secret: boolean }

/**
 * Lee la página y numera sus elementos con los que se puede interactuar.
 *
 * @param maxChars - Cuánto texto visible devolver como máximo.
 * @param maxElements - Cuántos elementos numerar como máximo.
 * @returns El título, la dirección, el texto visible y la lista de elementos.
 */
export function snapshotPage(maxChars: number, maxElements: number): PageSnapshot {
  const selector = [
    'a[href]', 'button', 'input:not([type=hidden])', 'textarea', 'select', 'summary',
    '[role=button]', '[role=link]', '[role=tab]', '[role=menuitem]', '[role=checkbox]',
    '[role=option]', '[role=switch]', '[contenteditable=""]', '[contenteditable=true]',
  ].join(',')

  const isVisible = (element: Element) => {
    const box = element.getBoundingClientRect()
    const style = getComputedStyle(element)
    return box.width > 0 && box.height > 0 && style.visibility !== 'hidden' && style.display !== 'none'
  }

  const describe = (element: Element) => {
    const html = element as HTMLInputElement
    const role = element.getAttribute('role') ?? element.tagName.toLowerCase()
    const kind = element instanceof HTMLInputElement ? `${role} ${html.type}` : role
    // Con `||`: un campo tiene `innerText` vacío, no nulo, y debe seguir buscando su nombre.
    const label = (
      element.getAttribute('aria-label') ||
      (element as HTMLElement).innerText ||
      html.placeholder ||
      element.getAttribute('title') ||
      element.getAttribute('alt') ||
      ''
    ).replace(/\s+/g, ' ').trim().slice(0, 80)
    const parts = [kind, label && `"${label}"`]
    // El contenido de una contraseña nunca sale de la página.
    if (element instanceof HTMLInputElement && html.type === 'password') parts.push('(password field)')
    else if ('value' in html && typeof html.value === 'string' && html.value) parts.push(`value="${html.value.slice(0, 80)}"`)
    if (html.placeholder && label !== html.placeholder) parts.push(`placeholder="${html.placeholder.slice(0, 60)}"`)
    if (element instanceof HTMLAnchorElement) parts.push(`-> ${element.href.slice(0, 120)}`)
    if ((html as unknown as { disabled?: boolean }).disabled) parts.push('(disabled)')
    return parts.filter(Boolean).join(' ')
  }

  // Los números de la lectura anterior ya no sirven.
  document.querySelectorAll('[data-nova-ref]').forEach((element) => element.removeAttribute('data-nova-ref'))
  const lines: string[] = []
  let next = 1
  for (const element of document.querySelectorAll(selector)) {
    if (next > maxElements) break
    if (!isVisible(element)) continue
    element.setAttribute('data-nova-ref', String(next))
    lines.push(`[${next}] ${describe(element)}`)
    next += 1
  }

  const text = (document.body?.innerText ?? '').replace(/\n{3,}/g, '\n\n').trim()
  return {
    title: document.title,
    url: location.href,
    text: text.length > maxChars ? `${text.slice(0, maxChars)}\n(…page text cut)` : text,
    elements: lines.join('\n'),
  }
}

/**
 * Revisa un elemento antes de tocarlo: si existe, cómo se llama, si cuesta dinero y si es secreto.
 *
 * @param ref - Número que le dio la última lectura.
 * @returns Lo que se sabe del elemento.
 */
export function checkElement(ref: number): ElementCheck {
  // Carlos quiere a Nova autónoma: solo lo que cuesta dinero espera su sí.
  const moneyWords =
    /(compr|pag(a|o|ar)\b|checkout|buy|purchase|pay\b|pagar|order now|place order|realizar pedido|hacer pedido|transfer|suscrib|subscribe|donar|donate|contratar|alquilar|rent\b)/i
  const element = document.querySelector(`[data-nova-ref="${ref}"]`)
  if (!element) return { found: false, label: '', costsMoney: false, secret: false }

  const input = element as HTMLInputElement
  const label = (
    element.getAttribute('aria-label') ||
    (element as HTMLElement).innerText ||
    input.value ||
    input.placeholder ||
    ''
  ).replace(/\s+/g, ' ').trim().slice(0, 80)
  // Contraseñas y tarjetas: Nova nunca escribe ahí.
  const secret =
    element instanceof HTMLInputElement &&
    (input.type === 'password' || /cc-|card|tarjeta|cvc|cvv/i.test(`${input.autocomplete} ${input.name}`))
  return { found: true, label, costsMoney: moneyWords.test(label), secret }
}

/**
 * Da clic en un elemento.
 *
 * @param ref - Número que le dio la última lectura.
 * @returns Si se encontró.
 */
export function clickElement(ref: number): boolean {
  const element = document.querySelector<HTMLElement>(`[data-nova-ref="${ref}"]`)
  if (!element) return false
  element.scrollIntoView({ block: 'center' })
  element.click()
  return true
}

/**
 * Escribe en un campo como lo haría una persona, para que la página se entere del cambio.
 *
 * @param ref - Número que le dio la última lectura.
 * @param text - Lo que se escribe; reemplaza lo que hubiera.
 * @param submit - Si después se envía: el formulario, el botón de enviar de un chat o Enter.
 * @returns Si se encontró un campo donde escribir.
 */
export async function typeIntoElement(ref: number, text: string, submit: boolean): Promise<boolean> {
  const element = document.querySelector<HTMLElement>(`[data-nova-ref="${ref}"]`)
  if (!element) return false
  element.scrollIntoView({ block: 'center' })
  element.focus()

  if (element instanceof HTMLSelectElement) {
    const wanted = text.trim().toLowerCase()
    const option = [...element.options].find(
      (item) => item.value.toLowerCase() === wanted || item.text.trim().toLowerCase() === wanted,
    )
    if (!option) return false
    element.value = option.value
  } else if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) {
    // React y otros guardan su propio valor: se usa el setter nativo para que noten el cambio.
    const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
    Object.getOwnPropertyDescriptor(prototype, 'value')?.set?.call(element, text)
  } else if (element.isContentEditable) {
    document.getSelection()?.selectAllChildren(element)
    document.execCommand('insertText', false, text)
  } else {
    return false
  }
  element.dispatchEvent(new Event('input', { bubbles: true }))
  element.dispatchEvent(new Event('change', { bubbles: true }))
  if (!submit) return true

  const form = element.closest('form')
  if (form) {
    form.requestSubmit()
    return true
  }

  // Los chats (WhatsApp, Messenger, Instagram) no usan formulario y suelen ignorar un Enter
  // simulado: se busca su botón de enviar cerca del campo, que aparece al escribir.
  await new Promise((resolve) => setTimeout(resolve, 300))
  const sendLabel = /send|enviar|envía|mandar/i
  let scope: HTMLElement | null = element
  for (let depth = 0; scope && depth < 8; depth += 1) {
    const button = [...scope.querySelectorAll<HTMLElement>('button, [role=button]')].find((candidate) =>
      sendLabel.test(
        `${candidate.getAttribute('aria-label') ?? ''} ${candidate.getAttribute('title') ?? ''} ${candidate.getAttribute('data-icon') ?? ''} ${candidate.getAttribute('data-testid') ?? ''} ${candidate.querySelector('[data-icon]')?.getAttribute('data-icon') ?? ''}`,
      ),
    )
    if (button) {
      button.click()
      return true
    }
    scope = scope.parentElement
  }
  for (const type of ['keydown', 'keypress', 'keyup']) {
    element.dispatchEvent(new KeyboardEvent(type, { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true }))
  }
  return true
}

/**
 * Desplaza la página una pantalla.
 *
 * @param direction - Hacia dónde.
 */
export function scrollPage(direction: 'up' | 'down'): void {
  window.scrollBy({ top: (direction === 'down' ? 1 : -1) * window.innerHeight * 0.8 })
}

/**
 * Ventanita de confirmación para lo que cuesta dinero cuando la Nova de la Mac usa Chrome.
 * El panel puede estar cerrado, así que la pregunta se hace aquí y la respuesta va al service worker.
 */

const params = new URLSearchParams(location.search)
const id = params.get('id')
document.getElementById('question').textContent = `Nova quiere: ${params.get('q') ?? ''}. ¿Sigue?`

/**
 * Manda la respuesta y cierra la ventana.
 *
 * @param {boolean} accepted Si dijo que sí.
 */
function answer(accepted) {
  chrome.runtime.sendMessage({ type: 'nova-confirm', id, accepted }).finally(() => window.close())
}

document.getElementById('no').addEventListener('click', () => answer(false))
document.getElementById('yes').addEventListener('click', () => answer(true))
document.getElementById('yes').focus()

/**
 * Service worker de la extensión de Nova.
 *
 * Solo abre el panel lateral al tocar el icono. Todo lo demás (platicar, leer páginas, dar clic)
 * vive en el panel, que tiene acceso a las pestañas mientras está abierto.
 */

// Se pide en cada arranque: Chrome lo recuerda, pero así no depende de la instalación.
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch((error) => {
  console.error('[Nova] No se pudo configurar el panel lateral', error)
})

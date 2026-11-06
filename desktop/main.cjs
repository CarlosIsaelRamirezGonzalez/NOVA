/** App de escritorio de Nova: ventana flotante, icono en la barra de menú y servidor local. */

const { app, BrowserWindow, Menu, Tray, ipcMain, nativeImage, screen, shell, systemPreferences } = require('electron')
const { spawn, spawnSync } = require('node:child_process')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const ROOT = path.resolve(__dirname, '..')
const SERVER_URL = 'http://127.0.0.1:8787'
const SERVER_START_TIMEOUT_MS = 90_000
const WIDGET_SIZE = { width: 300, height: 400 }
// Cuánto de la ventana puede salirse del borde: Nova nunca se pierde de vista.
const OFFSCREEN_MARGIN = 80
const TRAVEL_TICK_MS = 16
const WANDER_SPEED = 170
const COMMAND_SPEED = 1100
const WANDER_MIN_DISTANCE = 220
const WANDER_REST_MS = { min: 2500, max: 6000 }
// Al aparecer, o al terminar de atenderte, se queda un rato contigo antes de irse a pasear.
const ATTENTION_REST_MS = 8000
// Si le pides que se quite, no regresa paseando a tapar lo que estás viendo.
const COMMAND_REST_MS = 45_000
// Primero voltea a ver a dónde va y luego arranca poco a poco.
const WANDER_LOOK_AHEAD_MS = 550
const COMMAND_LOOK_AHEAD_MS = 160
const SPEED_UP_MS = 450
const ARRIVAL_SPIN_CHANCE = 0.15
// Frena al llegar, en vez de detenerse de golpe.
const ARRIVAL_EASE_PX = 140
// Solo se detiene si estás usando el mouse encima de ella: un cursor olvidado no la atrapa.
const CURSOR_ACTIVE_MS = 2000
const AUTOSTART_LABEL = 'com.nova.desktop'
const AUTOSTART_FILE = path.join(os.homedir(), 'Library', 'LaunchAgents', `${AUTOSTART_LABEL}.plist`)

let server = null
let widget = null
let tray = null
let dragStart = null
// A dónde va ahora, si anda de paseo o si se lo pediste, y si tiene permiso de pasear.
let travel = null
let travelTimer = null
let wanderEnabled = true
let nextWanderAt = 0
// Por qué no debe pasear ahora, como la compu abierta o estar bailando.
const wanderPauses = new Set()
let lastCursor = { x: 0, y: 0 }
let lastCursorMoveAt = 0

/**
 * Devuelve el archivo donde se recuerda en qué parte de la pantalla quedó Nova.
 *
 * @returns {string} La ruta del archivo.
 */
const positionFile = () => path.join(app.getPath('userData'), 'nova-position.json')

/**
 * Lee la última posición de Nova.
 *
 * @returns {{x: number, y: number} | null} La posición, si sigue dentro de alguna pantalla.
 */
function savedPosition() {
  try {
    const { x, y } = JSON.parse(fs.readFileSync(positionFile(), 'utf8'))
    const { bounds } = screen.getDisplayNearestPoint({ x, y })
    const isVisible =
      x + WIDGET_SIZE.width > bounds.x &&
      x < bounds.x + bounds.width &&
      y + WIDGET_SIZE.height > bounds.y &&
      y < bounds.y + bounds.height
    return isVisible ? { x, y } : null
  } catch {
    return null
  }
}

/**
 * Evita que Nova se salga por completo de la pantalla en la que está el cursor.
 *
 * @param {number} x - Columna deseada de la ventana.
 * @param {number} y - Fila deseada de la ventana.
 * @param {number} screenX - Columna del cursor.
 * @param {number} screenY - Fila del cursor.
 * @returns {{x: number, y: number}} La posición permitida.
 */
function clampToDisplay(x, y, screenX, screenY) {
  const { bounds } = screen.getDisplayNearestPoint({ x: screenX, y: screenY })
  const limit = (value, low, high) => Math.min(high, Math.max(low, value))
  return {
    x: limit(x, bounds.x - WIDGET_SIZE.width + OFFSCREEN_MARGIN, bounds.x + bounds.width - OFFSCREEN_MARGIN),
    y: limit(y, bounds.y - WIDGET_SIZE.height + OFFSCREEN_MARGIN, bounds.y + bounds.height - OFFSCREEN_MARGIN),
  }
}

/** Guarda dónde quedó Nova, para que aparezca ahí la próxima vez. */
function savePosition() {
  if (!widget) return
  const [x, y] = widget.getPosition()
  fs.writeFileSync(positionFile(), JSON.stringify({ x, y }))
}

/**
 * Devuelve el área útil de la pantalla donde está Nova, y sus límites para que se vea completa.
 *
 * @returns {{left: number, top: number, right: number, bottom: number}} Los límites de la ventana.
 */
function travelArea() {
  const [x, y] = widget.getPosition()
  const center = { x: x + WIDGET_SIZE.width / 2, y: y + WIDGET_SIZE.height / 2 }
  const { workArea } = screen.getDisplayNearestPoint(center)
  return {
    left: workArea.x,
    top: workArea.y,
    right: workArea.x + workArea.width - WIDGET_SIZE.width,
    bottom: workArea.y + workArea.height - WIDGET_SIZE.height,
  }
}

/**
 * Comprueba si estás usando el mouse encima de la ventana: ahí no pasea, para que puedas tocarla.
 *
 * @returns {boolean} Si el cursor está encima y se movió hace poco.
 */
function cursorIsBusyOverWidget() {
  const cursor = screen.getCursorScreenPoint()
  if (cursor.x !== lastCursor.x || cursor.y !== lastCursor.y) {
    lastCursor = cursor
    lastCursorMoveAt = Date.now()
  }
  if (Date.now() - lastCursorMoveAt > CURSOR_ACTIVE_MS) return false
  const [x, y] = widget.getPosition()
  return cursor.x >= x && cursor.x < x + WIDGET_SIZE.width && cursor.y >= y && cursor.y < y + WIDGET_SIZE.height
}

/**
 * Elige un punto al azar de la pantalla, no demasiado cerca de donde está.
 *
 * @returns {{x: number, y: number, speed: number, isWander: boolean}} El siguiente viaje.
 */
function pickWanderTarget() {
  const area = travelArea()
  const [x, y] = widget.getPosition()
  const pick = () => ({
    x: area.left + Math.random() * (area.right - area.left),
    y: area.top + Math.random() * (area.bottom - area.top),
  })
  let target = pick()
  for (let attempt = 0; attempt < 8 && Math.hypot(target.x - x, target.y - y) < WANDER_MIN_DISTANCE; attempt += 1) {
    target = pick()
  }
  return { ...target, speed: WANDER_SPEED, isWander: true, startsAt: Date.now() + WANDER_LOOK_AHEAD_MS }
}

/**
 * Avisa a la interfaz cómo se mueve la ventana, para animar el cuerpo y la mirada.
 *
 * @param {number} vx - Velocidad horizontal, en píxeles por segundo.
 * @param {number} vy - Velocidad vertical, en píxeles por segundo.
 * @param {number} headingX - Parte horizontal de la dirección a la que va, de -1 a 1.
 * @param {number} headingY - Parte vertical de esa dirección; ambas en cero si no va a ningún lado.
 */
function sendTravel(vx, vy, headingX, headingY) {
  widget?.webContents.send('window-travel', vx, vy, headingX, headingY)
}

/** Avanza un paso del viaje actual, o decide el siguiente paseo. */
function stepTravel() {
  if (!widget || !widget.isVisible() || dragStart) return

  // Un paseo espera si la estás tocando; lo que le pediste, no.
  const isBlocked = cursorIsBusyOverWidget() && (!travel || travel.isWander)
  const isPaused = wanderPauses.size > 0 && travel?.isWander !== false
  if (isBlocked || isPaused) {
    if (isPaused) travel = null
    sendTravel(0, 0, 0, 0)
    return
  }
  if (!travel) {
    if (wanderEnabled && Date.now() >= nextWanderAt) travel = pickWanderTarget()
    return
  }

  const [x, y] = widget.getPosition()
  const distance = Math.hypot(travel.x - x, travel.y - y)
  const headingX = (travel.x - x) / Math.max(distance, 1)
  const headingY = (travel.y - y) / Math.max(distance, 1)
  const elapsed = Date.now() - travel.startsAt

  // Todavía no arranca: solo voltea a ver hacia allá.
  if (elapsed < 0) {
    sendTravel(0, 0, headingX, headingY)
    return
  }
  if (distance < 2) {
    widget.setPosition(Math.round(travel.x), Math.round(travel.y))
    sendTravel(0, 0, 0, 0)
    savePosition()
    if (travel.isWander) {
      // A veces, de puro gusto, da una vuelta al llegar.
      if (Math.random() < ARRIVAL_SPIN_CHANCE) widget.webContents.send('nova-pose', 'spin')
      nextWanderAt = Date.now() + WANDER_REST_MS.min + Math.random() * (WANDER_REST_MS.max - WANDER_REST_MS.min)
    }
    travel = null
    return
  }
  const speedUp = Math.min(1, 0.15 + elapsed / SPEED_UP_MS)
  const speed = Math.max(40, travel.speed * speedUp * Math.min(1, distance / ARRIVAL_EASE_PX))
  const step = Math.max(2, Math.min(distance, (speed * TRAVEL_TICK_MS) / 1000))
  widget.setPosition(Math.round(x + headingX * step), Math.round(y + headingY * step))
  sendTravel(headingX * speed, headingY * speed, headingX, headingY)
}

/**
 * Enciende o apaga el movimiento: oculta no tiene por qué seguir calculando.
 *
 * @param {boolean} isVisible - Si la ventana se ve.
 */
function setTravelLoop(isVisible) {
  if (travelTimer) clearInterval(travelTimer)
  travelTimer = isVisible ? setInterval(stepTravel, TRAVEL_TICK_MS) : null
  if (!isVisible) {
    travel = null
    sendTravel(0, 0, 0, 0)
  }
}

/** Si el cursor está en otra pantalla, aparece en esa, que es donde la estás ocupando. */
function moveToCursorDisplay() {
  const cursorDisplay = screen.getDisplayNearestPoint(screen.getCursorScreenPoint())
  const [x, y] = widget.getPosition()
  const center = { x: x + WIDGET_SIZE.width / 2, y: y + WIDGET_SIZE.height / 2 }
  if (screen.getDisplayNearestPoint(center).id === cursorDisplay.id) return
  const { workArea } = cursorDisplay
  widget.setPosition(
    Math.round(workArea.x + Math.random() * (workArea.width - WIDGET_SIZE.width)),
    Math.round(workArea.y + Math.random() * (workArea.height - WIDGET_SIZE.height)),
  )
}

/**
 * Calcula a dónde ir según lo que le pediste.
 *
 * @param {string} place - Lugar pedido, como `away`, `left` o `top_right`.
 * @returns {{x: number, y: number} | null} El destino, o `null` si no es un lugar.
 */
function commandTarget(place) {
  const area = travelArea()
  const [x, y] = widget.getPosition()
  const stepX = (area.right - area.left) * 0.4
  const stepY = (area.bottom - area.top) * 0.4
  const limitX = (value) => Math.min(area.right, Math.max(area.left, value))
  const limitY = (value) => Math.min(area.bottom, Math.max(area.top, value))
  const corners = [
    { x: area.left, y: area.top },
    { x: area.right, y: area.top },
    { x: area.left, y: area.bottom },
    { x: area.right, y: area.bottom },
  ]
  switch (place) {
    case 'away':
      // Se va a la esquina más lejana: lo que te tapaba está donde ella estaba.
      return corners.reduce((best, corner) =>
        Math.hypot(corner.x - x, corner.y - y) > Math.hypot(best.x - x, best.y - y) ? corner : best,
      )
    case 'left':
      return { x: limitX(x - stepX), y }
    case 'right':
      return { x: limitX(x + stepX), y }
    case 'up':
      return { x, y: limitY(y - stepY) }
    case 'down':
      return { x, y: limitY(y + stepY) }
    case 'top_left':
      return corners[0]
    case 'top_right':
      return corners[1]
    case 'bottom_left':
      return corners[2]
    case 'bottom_right':
      return corners[3]
    case 'center':
      return { x: (area.left + area.right) / 2, y: (area.top + area.bottom) / 2 }
    default:
      return null
  }
}

/**
 * Obedece lo que le pediste con la voz.
 *
 * @param {string} place - Lugar pedido, `stay`, `roam` o `hide`.
 */
function handleMoveCommand(place) {
  if (!widget) return
  if (place === 'hide') {
    widget.webContents.send('presence-command', 'dismiss')
    return
  }
  if (place === 'spin' || place === 'show_back' || place === 'dance') {
    widget.webContents.send('nova-pose', place)
    return
  }
  if (place === 'stay') {
    wanderEnabled = false
    travel = null
    sendTravel(0, 0, 0, 0)
    return
  }
  if (place === 'roam') {
    wanderEnabled = true
    nextWanderAt = 0
    return
  }
  const target = commandTarget(place)
  if (!target) return
  travel = { ...target, speed: COMMAND_SPEED, isWander: false, startsAt: Date.now() + COMMAND_LOOK_AHEAD_MS }
  nextWanderAt = Date.now() + COMMAND_REST_MS
}

// Nova empieza a hablar sola cuando la llamas: no hay clic que autorice el audio.
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required')

/**
 * Comprueba si el servidor ya responde.
 *
 * @returns {Promise<boolean>} Si está disponible.
 */
async function serverIsUp() {
  try {
    return (await fetch(SERVER_URL)).ok
  } catch {
    return false
  }
}

/** Compila la interfaz si todavía no existe, porque el servidor es quien la entrega. */
function buildFrontendIfMissing() {
  if (fs.existsSync(path.join(ROOT, 'frontend', 'dist', 'index.html'))) return
  spawnSync('npm', ['--prefix', 'frontend', 'run', 'build'], { cwd: ROOT, stdio: 'inherit' })
}

/** Arranca el servidor, salvo que ya esté corriendo, y espera a que responda. */
async function startServer() {
  if (await serverIsUp()) return
  buildFrontendIfMissing()

  // Lo que imprime el servidor queda en un archivo privado, para poder revisar errores.
  const logPath = path.join(ROOT, 'data', 'desktop.log')
  const log = fs.openSync(logPath, 'a', 0o600)
  server = spawn(path.join(ROOT, '.venv', 'bin', 'python'), ['server.py'], {
    cwd: ROOT,
    stdio: ['ignore', log, log],
  })

  const deadline = Date.now() + SERVER_START_TIMEOUT_MS
  while (Date.now() < deadline) {
    if (await serverIsUp()) return
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  throw new Error(`El servidor no arrancó; revisa ${logPath}`)
}

/** Crea la ventana flotante en la esquina inferior derecha. */
function createWidget() {
  const { workArea } = screen.getPrimaryDisplay()
  const position = savedPosition() ?? {
    x: workArea.x + workArea.width - WIDGET_SIZE.width - 16,
    y: workArea.y + workArea.height - WIDGET_SIZE.height - 16,
  }
  widget = new BrowserWindow({
    ...WIDGET_SIZE,
    ...position,
    transparent: true,
    frame: false,
    resizable: false,
    hasShadow: false,
    // La interfaz decide cuándo se ve; al aparecer no le quita el foco a lo que estés usando.
    show: false,
    alwaysOnTop: true,
    fullscreenable: false,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      sandbox: true,
      // Oculta sigue atenta a la conexión y a su voz, sin que el sistema la frene.
      backgroundThrottling: false,
    },
  })
  widget.once('ready-to-show', () => {
    widget?.showInactive()
    setTravelLoop(true)
  })
  widget.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
  widget.setAlwaysOnTop(true, 'floating')

  // Solo sus propias páginas se abren aquí; cualquier otro enlace va al navegador.
  widget.webContents.setWindowOpenHandler(({ url }) => {
    if (url === `${SERVER_URL}/`) {
      return { action: 'allow', overrideBrowserWindowOptions: { width: 900, height: 800, title: 'Nova' } }
    }
    if (url.startsWith('https://')) void shell.openExternal(url)
    return { action: 'deny' }
  })
  widget.on('closed', () => {
    setTravelLoop(false)
    widget = null
  })
  void widget.loadURL(`${SERVER_URL}/?widget=1`)
}

/** Enciende o apaga el arranque de Nova al iniciar sesión, con un agente de tu usuario. */
function setAutostart(enabled) {
  if (!enabled) {
    fs.rmSync(AUTOSTART_FILE, { force: true })
    return
  }
  const plist = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>${AUTOSTART_LABEL}</string>
  <key>ProgramArguments</key><array><string>${process.execPath}</string><string>${__dirname}</string></array>
  <key>RunAtLoad</key><true/>
</dict></plist>
`
  fs.mkdirSync(path.dirname(AUTOSTART_FILE), { recursive: true })
  fs.writeFileSync(AUTOSTART_FILE, plist)
}

/** Crea el icono de la barra de menú con sus opciones. */
function createTray() {
  const icon = nativeImage.createFromPath(path.join(__dirname, 'trayTemplate.png'))
  icon.setTemplateImage(true)
  tray = new Tray(icon)
  tray.setToolTip('Nova')
  tray.setContextMenu(
    Menu.buildFromTemplate([
      {
        label: 'Mostrar u ocultar a Nova',
        click: () => {
          if (!widget) createWidget()
          else widget.webContents.send('presence-command', 'toggle')
        },
      },
      { type: 'separator' },
      {
        label: 'Abrir al iniciar sesión',
        type: 'checkbox',
        checked: fs.existsSync(AUTOSTART_FILE),
        click: (item) => setAutostart(item.checked),
      },
      { type: 'separator' },
      { label: 'Salir', click: () => app.quit() },
    ]),
  )
}

/**
 * Prueba automática: simula arrastrar a Nova, guarda capturas y cierra la app.
 *
 * @param {string} shot - Archivo de la captura; las demás agregan un sufijo.
 */
async function runSmokeTest(shot) {
  const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds))
  const capture = async (suffix) =>
    fs.writeFileSync(shot.replace('.png', `${suffix}.png`), (await widget.webContents.capturePage()).toPNG())
  const mouse = (type, x, y) =>
    widget.webContents.sendInputEvent({ type, x: 150, y: 170, globalX: x, globalY: y, button: 'left', clickCount: 1 })

  await wait(7000)
  await capture('')
  const [startX, startY] = widget.getPosition()
  console.log('posición inicial', startX, startY)

  // Toma a Nova y la lleva hacia arriba a la izquierda, en pasos.
  mouse('mouseDown', startX + 150, startY + 170)
  for (let step = 1; step <= 30; step += 1) {
    mouse('mouseMove', startX + 150 - step * 12, startY + 170 - step * 6)
    await wait(30)
  }
  await capture('-agarrada')
  console.log('posición arrastrando', ...widget.getPosition())
  mouse('mouseUp', startX + 150 - 360, startY + 170 - 180)
  await wait(120)
  await capture('-soltando')
  await wait(1500)
  await capture('-final')
  console.log('posición final', ...widget.getPosition(), 'guardada', fs.existsSync(positionFile()))
  app.quit()
}

// Solo una Nova a la vez: abrirla otra vez muestra la que ya existe.
if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => widget?.webContents.send('presence-command', 'summon'))

  // Arrastrar: la ventana sigue al cursor, y al soltarla recuerda dónde quedó.
  ipcMain.on('drag-start', (_event, screenX, screenY) => {
    if (!widget) return
    const [x, y] = widget.getPosition()
    dragStart = { x, y, screenX, screenY }
    travel = null
  })
  ipcMain.on('drag-move', (_event, screenX, screenY) => {
    if (!widget || !dragStart) return
    const next = clampToDisplay(
      dragStart.x + screenX - dragStart.screenX,
      dragStart.y + screenY - dragStart.screenY,
      screenX,
      screenY,
    )
    widget.setPosition(Math.round(next.x), Math.round(next.y))
  })
  ipcMain.on('drag-end', () => {
    dragStart = null
    // Si la dejaste en un lugar, no se va de inmediato.
    nextWanderAt = Date.now() + COMMAND_REST_MS
    savePosition()
  })

  // La interfaz avisa cuándo debe verse Nova; responde al terminar para animar su entrada.
  ipcMain.handle('set-present', (_event, present) => {
    if (!widget) return
    if (present && !widget.isVisible()) {
      moveToCursorDisplay()
      nextWanderAt = Math.max(nextWanderAt, Date.now() + ATTENTION_REST_MS)
    }
    if (present) widget.showInactive()
    else widget.hide()
    if (!present) savePosition()
    setTravelLoop(present)
  })

  ipcMain.on('move-to', (_event, place) => handleMoveCommand(place))
  ipcMain.on('pause-wander', (_event, reason, paused) => {
    if (paused) wanderPauses.add(reason)
    else {
      wanderPauses.delete(reason)
      nextWanderAt = Math.max(nextWanderAt, Date.now() + ATTENTION_REST_MS)
    }
  })

  // El permiso del micrófono se pide hasta que enciendes el micrófono.
  ipcMain.handle('request-microphone', () => systemPreferences.askForMediaAccess('microphone'))
  // El de la cámara, hasta la primera vez que le pides a Nova que mire.
  ipcMain.handle('request-camera', () => systemPreferences.askForMediaAccess('camera'))

  app.whenReady().then(async () => {
    app.dock?.hide()
    try {
      await startServer()
    } catch (error) {
      console.error(error)
      app.quit()
      return
    }
    createTray()
    createWidget()

    // Prueba automática: guarda una captura de la ventana y cierra.
    const shot = process.env.NOVA_SMOKE_SHOT
    if (shot) void runSmokeTest(shot)
  })

  // Cerrar la ventana no apaga a Nova: sigue en la barra de menú.
  app.on('window-all-closed', () => {})

  // Apaga solo el servidor que esta app arrancó; así alcanza a subir los últimos cambios.
  app.on('before-quit', () => server?.kill('SIGTERM'))
}

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
const AUTOSTART_LABEL = 'com.nova.desktop'
const AUTOSTART_FILE = path.join(os.homedir(), 'Library', 'LaunchAgents', `${AUTOSTART_LABEL}.plist`)

let server = null
let widget = null
let tray = null

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
  widget = new BrowserWindow({
    ...WIDGET_SIZE,
    x: workArea.x + workArea.width - WIDGET_SIZE.width - 16,
    y: workArea.y + workArea.height - WIDGET_SIZE.height - 16,
    transparent: true,
    frame: false,
    resizable: false,
    hasShadow: false,
    alwaysOnTop: true,
    fullscreenable: false,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      sandbox: true,
    },
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
          else if (widget.isVisible()) widget.hide()
          else widget.show()
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

// Solo una Nova a la vez: abrirla otra vez muestra la que ya existe.
if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => widget?.show())

  // El permiso del micrófono se pide hasta que enciendes "Oye Nova".
  ipcMain.handle('request-microphone', () => systemPreferences.askForMediaAccess('microphone'))

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
    if (shot) {
      setTimeout(async () => {
        fs.writeFileSync(shot, (await widget.webContents.capturePage()).toPNG())
        app.quit()
      }, 7000)
    }
  })

  // Cerrar la ventana no apaga a Nova: sigue en la barra de menú.
  app.on('window-all-closed', () => {})

  // Apaga solo el servidor que esta app arrancó; así alcanza a subir los últimos cambios.
  app.on('before-quit', () => server?.kill('SIGTERM'))
}

// Sirve el motor de MediaPipe desde este proyecto en vez de un CDN.
import { cpSync } from 'node:fs'

cpSync('node_modules/@mediapipe/tasks-vision/wasm', 'public/mediapipe/wasm', { recursive: true })

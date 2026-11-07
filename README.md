# Nova

Compañera de IA personal con voz, emociones, memoria, cámara y búsqueda en internet.

- **Historia del proyecto:** [docs/desarrollo-de-nova.md](docs/desarrollo-de-nova.md)
- **Versiones:** [CHANGELOG.md](CHANGELOG.md)

## Tecnología
- **Backend:** Python, aiohttp y WebSocket.
- **Modelo y voz:** Claude Haiku 5.5 y ElevenLabs.
- **Interfaz:** React, TypeScript, Tailwind, three.js y MediaPipe.
- **Memoria:** SQLite sincronizado con Turso, Qdrant y Obsidian.

## Cómo correrla
1. Instala las dependencias: `pip install -r requirements.txt` y `npm --prefix frontend install`.
2. Crea un archivo `.env` con `ANTHROPIC_API_KEY` y `ELEVENLABS_API_KEY`. Agrega `TURSO_DATABASE_URL` y
   `TURSO_AUTH_TOKEN` si quieres sincronizar la memoria.
3. Ejecuta `./start.sh` y abre http://localhost:5173.

## App de escritorio
1. Coloca en `data/models/` el modelo de Vosk `vosk-model-small-es-0.42` y, en `data/models/whisper/`,
   el de Whisper `ggml-base.bin`.
2. Instala Electron: `npm --prefix desktop install`, y si tu npm bloquea scripts,
   `node desktop/node_modules/electron/install.js`.
3. Compila la interfaz: `npm --prefix frontend run build`.
4. Abre la app: `npm --prefix desktop start`. El micrófono se enciende solo y Nova se oculta: aparece cuando dices "Nova" u "Oye Nova", o desde el icono de la barra de menú. Dile "muévete", "quédate quieta", "pasea", "da una vuelta", "voltéate", "baila" o "desaparece".
5. Para que escriba en otra app, concede a Electron los permisos de Accesibilidad y Grabación de pantalla cuando macOS los pida, y reinicia Nova. Haz clic en el campo de texto y pídele: "Nova, termina este mensaje y dile que llego a las cinco". Nunca envía; mueve el mouse o presiona Esc para detenerla.
6. Para que te reconozca: `.venv/bin/python scripts/download_face_model.py` (unos 15 MB), y dile "Nova, apréndete mi cara" estando solo y con buena luz. La huella se queda en esta Mac; bórrala desde "Cómo te ve" o diciendo "olvida mi cara".

Nunca subas `.env` ni `data/`: contienen tus claves y tus conversaciones.

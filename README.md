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

Nunca subas `.env` ni `data/`: contienen tus claves y tus conversaciones.

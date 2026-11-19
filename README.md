# Nova

Compañera de IA personal con voz, emociones, memoria, cámara y búsqueda en internet.

- **Historia del proyecto:** [docs/desarrollo-de-nova.md](docs/desarrollo-de-nova.md)
- **Cómo funciona por dentro:** [docs/Funcionamiento de Nova.md](docs/Funcionamiento%20de%20Nova.md)
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
   el de Whisper `ggml-small.bin` (entiende mejor) o `ggml-base.bin` (más ligero). Se usa el mejor que haya.
2. Instala Electron: `npm --prefix desktop install`, y si tu npm bloquea scripts,
   `node desktop/node_modules/electron/install.js`.
3. Compila la interfaz: `npm --prefix frontend run build`.
4. Abre la app: `npm --prefix desktop start`. El micrófono se enciende solo y Nova se oculta: aparece cuando dices "Nova" u "Oye Nova", o desde el icono de la barra de menú. Dile "muévete", "quédate quieta", "pasea", "da una vuelta", "voltéate", "baila" o "desaparece".
5. Para que escriba en otra app, concede a Electron los permisos de Accesibilidad y Grabación de pantalla cuando macOS los pida, y reinicia Nova. Haz clic en el campo de texto y pídele: "Nova, termina este mensaje y dile que llego a las cinco". Nunca envía; mueve el mouse o presiona Esc para detenerla.
6. Para que te reconozca: `.venv/bin/python scripts/download_face_model.py` (unos 15 MB), y dile "Nova, apréndete mi cara" estando solo y con buena luz. La huella se queda en esta Mac; bórrala desde "Cómo te ve" o diciendo "olvida mi cara".
7. Para que reconozca tu voz: `.venv/bin/python scripts/download_voice_model.py` (unos 26 MB), y con el micrófono encendido dile "Nova, apréndete mi voz" estando solo. Después dile dos o tres frases cualquiera. Desde entonces solo te responde a ti: lo que diga otra persona por el micrófono se ignora sin gastar nada. Una frase muy corta ("sí", "va") no alcanza para reconocerte; vale si te reconoció en los últimos dos minutos. Al decir solo "Nova", saluda a cualquiera, pero la petición siguiente ya se revisa. La huella se queda en esta Mac; bórrala diciendo "olvida mi voz". En la terminal, `[Voice] Carlos (0.82)` muestra qué tanto se pareció cada petición.
8. Para que te mande reportes por correo: en tu cuenta de Google activa la verificación en dos pasos y crea una contraseña de aplicación en https://myaccount.google.com/apppasswords. Agrega a `.env` `GMAIL_ADDRESS` y `GMAIL_APP_PASSWORD` (y `NOVA_EMAIL_TO` si quieres recibirlos en otra dirección). Para los diagramas: `npm --prefix tools/mermaid install`. Luego pídele, por ejemplo: "Nova, mándame por correo una investigación de los mejores teclados mecánicos, con un diagrama comparativo". Lo escribe Claude Sonnet 5.5 en segundo plano, investiga en internet si hace falta, y te avisa en el chat cuando sale. Solo te escribe a ti.
9. Para que esté al tanto de tu entorno: `.venv/bin/python scripts/download_sound_model.py` (6 MB). Con el micrófono encendido, Nova mira por su cuenta cuando oye otra voz, cuando oye un ruido raro (golpes, vidrios, gritos, alarmas, ladridos, la puerta) y cada 20 minutos. También decide mirar cuando la plática lo pide, por ejemplo si dices que no te sientes bien con cómo te ves. Solo te habla si algo importa; si no, lo usa como contexto. Siempre hace su animación de foto al mirar, y esas fotos no se guardan ni aparecen en el chat. Ajusta con `NOVA_GLANCE_MINUTES` (0 apaga los vistazos de rutina) o apágalo todo con `NOVA_AMBIENT_CAMERA=false`.

## Versión web (Vercel)
La misma Nova, detrás de una contraseña. No tiene micrófono propio, escritorio ni reconocimiento de
cara; se le habla escribiendo o con el dictado del navegador (Chrome).

1. Crea una base de Turso aparte para la web. La Mac y la web no deben compartir base por ahora.
2. En Vercel, en *Settings > Environment Variables*, agrega `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`,
   `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `NOVA_WEB_PASSWORD` (12 caracteres o más) y
   `NOVA_SESSION_SECRET` (32 o más; genera uno con `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`).
3. Despliega con `npx vercel deploy --prod`. `pyproject.toml` y `vercel.json` le dicen a Vercel qué
   instalar, cómo compilar la interfaz y qué no subir.

Para probarla en la Mac antes de desplegar: `pip install fastapi "uvicorn[standard]"` y
`uvicorn web.app:app --port 8788`, con `NOVA_WEB_PASSWORD` y `NOVA_SESSION_SECRET` definidos.

Nunca subas `.env` ni `data/`: contienen tus claves y tus conversaciones.

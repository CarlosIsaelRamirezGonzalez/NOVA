"""Puente entre la cara de Nova (`frontend/`), Claude y ElevenLabs.

En la Mac se corre con `python server.py`. La versión web (`web/app.py`) usa este mismo
`NovaServer` con menos piezas encendidas.

Uso: `python server.py`
"""

import asyncio
import hashlib
import random
import time
import traceback
from pathlib import Path
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Protocol

from aiohttp import ClientSession, WSMsgType, web
from pydantic import BaseModel, ValidationError

from config import Config
from nova.prompts.nova_prompts import NOVA_AVATAR_INSTRUCTIONS, NOVA_SYSTEM_PROMPT
from services.agents.agm import GESTURES, VOICE_REQUEST, AgentManager, gesture_message
from services.agents.browser_service import BrowserAgent
from services.chunk.emotion_filter import strip_tags
from services.agents.llms_service import LLMService
from services.agents.report_service import ReportService
from services.agents.web_search_service import WebSearchService
from services.context.conversation_service import ConversationService
from services.context.visual_memory_service import VisualMemoryService
from services.context.memory_service import MemoryService
from services.context.memory_store import MemoryStore
from services.context.obsidian_vault import ObsidianVault
from services.context.photo_budget_service import PhotoBudgetService
from services.context.usage_service import UsageService
from services.context.search_index import DisabledSearchIndex, SearchIndex
from services.context.surroundings_service import SurroundingsService
from services.http_client import create_anthropic_client, create_http_session
from services.schemas import (
    CLIENT_REQUEST,
    BrowseDoneEvent,
    BrowserAction,
    BrowserActionEvent,
    BrowserResultRequest,
    BrowseStartEvent,
    BrainEvent,
    BrainRequest,
    CalmRequest,
    DoneEvent,
    EmotionBlend,
    EmotionEvent,
    ErrorEvent,
    ForgetMemoryRequest,
    Gesture,
    GestureReactionEvent,
    GestureRequest,
    HistoryEvent,
    HistoryMessage,
    InterruptedEvent,
    InterruptRequest,
    PhotoRequestEvent,
    PhotoResponse,
    PhotoResult,
    RecallEvent,
    SearchDoneEvent,
    EmotionComponent,
    GreetingEvent,
    ForgetFaceRequest,
    ForgetVisualRequest,
    VisualProfileEvent,
    MoveEvent,
    SearchStartEvent,
    VisualProfileRequest,
    WriteDoneEvent,
    WriteStartEvent,
    ServerEvent,
    ListenRequest,
    ListenStateEvent,
    HeardEvent,
    CapabilitiesEvent,
    ServerFeatures,
    SessionStatus,
    MicGateRequest,
    UsageRequest,
    TokenEvent,
    VoiceCheck,
    EmailDoneEvent,
    GlanceKind,
    ProactiveEvent,
    SoundEvent,
)
from services.voice.tts_service import TTSService

# El micrófono, el escritorio, las caras y la búsqueda por significado usan librerías que solo
# existen en la Mac. Se importan al encenderlas, para que la versión web no las necesite.
if TYPE_CHECKING:
    import numpy as np

    from services.voice.listening_service import ListeningService, ListenState

HOST = "127.0.0.1"
PORT = 8787
# Sincronizar cuesta casi un segundo de red, así que se agrupan los cambios.
SYNC_SECONDS = 30
HEARTBEAT_SECONDS = 30
# Alcanza para contestar el permiso de la cámara la primera vez.
PHOTO_TIMEOUT_SECONDS = 30
# Incluye el tiempo que tarde en confirmar una compra o un envío en la extensión.
BROWSER_ACTION_TIMEOUT_SECONDS = 90
BROWSER_NO_RESPONSE = "The browser did not respond. The extension may have been closed."
GESTURE_COOLDOWN_SECONDS = 30
HISTORY_MESSAGES_SHOWN = 60
ALLOWED_ORIGINS = frozenset(
    {
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        f"http://localhost:{PORT}",
        f"http://{HOST}:{PORT}",
    }
)
# La interfaz ya compilada, para que la app de escritorio no dependa de Vite.
FRONTEND_DIST = Path(__file__).with_name("frontend") / "dist"

# Estos textos van en español porque el usuario los lee en la interfaz.
# Lo que dice al llamarla sin pedirle nada, y con qué ánimo.
# Lo que dice si la llamo sin pedir nada; cambia para que no suene a máquina, y no usa mi nombre.
GREETINGS = (
    "¿Qué pasó?",
    "Hola, ¿qué tal?",
    "Aquí estoy.",
    "Te escucho.",
    "Dime.",
    "¿Qué onda?",
    "Hola, aquí ando.",
    "Hola, ¿cómo te puedo ayudar?",
)
GREETING_MOOD = EmotionComponent(name="happy", intensity=0.5)
TURN_FAILED_MESSAGE = "No pude responder. Revisa los registros del servidor."
INVALID_MESSAGE = "Mensaje vacío o demasiado largo."
# Para aprender mi voz se juntan unos segundos de frases dichas después de pedirlo.
VOICE_ENROLL_SECONDS = 8.0
VOICE_ENROLL_MAX_PHRASES = 4
VOICE_ENROLL_TIMEOUT_SECONDS = 90.0
# Vistazos por su cuenta: nunca dos seguidos, y cada motivo con su propia espera.
GLANCE_MIN_GAP_SECONDS = 60.0
GLANCE_COOLDOWNS: tuple[tuple[str, float], ...] = (("voice", 600.0), ("sound", 180.0), ("routine", 0.0))
# Las fotos que pido a propósito no deben quedarse sin cupo por los vistazos de rutina.
DAILY_PHOTO_LIMIT = 60
AMBIENT_PHOTO_RESERVE = 10
SPOKE_ON_OWN_NOTE = "You glanced at Carlos's camera on your own ({reason}) and spoke up."
# Una frase muy corta ("sí", "va") no alcanza para saber quién habla: vale si hace poco me reconoció.
VOICE_TRUST_SECONDS = 120.0
SAMPLE_RATE = 16000
# Lo dice sin pasar por el modelo: es inmediato y nada de lo que digo para aprenderla se guarda.
VOICE_ENROLL_START = "Va. Ahora dime dos o tres frases, lo que quieras, como si platicáramos."
VOICE_ENROLL_MORE = "Tantito más. Dime otra frase."
VOICE_ENROLLED = "Listo, ya me aprendí tu voz. Se queda solo en esta Mac."
VOICE_ENROLL_SHORT = "No te oí lo suficiente. Pídemelo otra vez cuando quieras."
VOICE_ENROLL_UNAVAILABLE = (
    "Todavía no tengo el modelo de voces. Corre el script download_voice_model.py y reiníciame."
)
VOICE_LEARNED_NOTE = (
    "You just learned Carlos's voice from {seconds} seconds of speech. It stays on this computer. "
    "From now on, a local check tells you whether a spoken request sounds like him."
)
BUSY_MESSAGE = "Sigo respondiendo el turno anterior."


class ClientSocket(Protocol):
    """Conexión con una pantalla, venga de aiohttp (Mac) o de FastAPI (web)."""

    @property
    def closed(self) -> bool:
        """Si la conexión ya se cerró."""
        ...

    async def send_str(self, data: str) -> None:
        """Envía un evento en JSON."""
        ...

    async def send_bytes(self, data: bytes) -> None:
        """Envía un fragmento de audio."""
        ...


async def _text_messages(socket: ClientSocket) -> AsyncIterator[str]:
    """Entrega solo los mensajes de texto de un WebSocket de aiohttp.

    Args:
        socket: Conexión ya abierta.

    Yields:
        El contenido de cada mensaje de texto.
    """
    async for message in socket:
        if message.type == WSMsgType.TEXT:
            yield message.data


class GlanceClock(BaseModel):
    """Cuándo miró Nova por su cuenta por última vez, en segundos de `time.monotonic`.

    Attributes:
        last_any: El último vistazo, por cualquier motivo.
        last_voice: El último por oír otra voz.
        last_sound: El último por un ruido.
        last_routine: El último de rutina.
    """

    last_any: float = float("-inf")
    last_voice: float = float("-inf")
    last_sound: float = float("-inf")
    last_routine: float = float("-inf")


class NovaServer:
    """Atiende el WebSocket del navegador y ejecuta los turnos de conversación."""

    def __init__(self, config: Config, features: ServerFeatures | None = None) -> None:
        """Construye los servicios; la conversación se comparte entre conexiones.

        Args:
            config: Configuración validada de Nova.
            features: Piezas que se encienden; por omisión, todas las de la Mac.
        """
        self.features = features or ServerFeatures()
        self.store = MemoryStore(config.active_memory_path, sync=config.sync_settings)
        self.anthropic = create_anthropic_client(config.anthropic_api_key)
        self.usage = UsageService(self.store)
        self.agent = AgentManager(
            ConversationService(NOVA_SYSTEM_PROMPT + NOVA_AVATAR_INSTRUCTIONS, store=self.store),
            LLMService(self.anthropic, self.usage),
            TTSService(config.elevenlabs_api_key, config.elevenlabs_voice_id, usage=self.usage),
            store=self.store,
        )
        self.agent.web_search = WebSearchService(self.anthropic, self.usage)
        # Solo se usa cuando le hablo desde la extensión de Chrome.
        self.agent.browser = BrowserAgent(self.anthropic, self.usage)
        if self.features.desktop:
            from services.agents.writing_service import DesktopWriter

            self.agent.writer = DesktopWriter(self.agent.llm, self.agent.model)
        self.agent.visual = VisualMemoryService(self.store, self.agent.llm, self.agent.model)
        # Los reportes por correo solo se ofrecen si hay cuenta de Gmail. Siempre llegan a mí.
        if config.gmail_address and config.gmail_app_password:
            self.agent.reports = ReportService(
                self.anthropic,
                config.gmail_address,
                config.gmail_app_password,
                config.nova_email_to or config.gmail_address,
                self.usage,
            )
            self.agent.reports.on_done = self._report_done
        if self.features.faces:
            from services.context.face_identity_service import FaceIdentityService

            # Queda junto a la base local, pero fuera de ella: esto no se sincroniza con la nube.
            self.agent.faces = FaceIdentityService(
                config.models_path / "face", config.active_memory_path.parent / "face_profile.npy"
            )
        index: SearchIndex = DisabledSearchIndex()
        if self.features.semantic_search:
            from services.context.vector_index import VectorIndex

            index = VectorIndex(config.vector_path, config.models_path)
        self.memory = MemoryService(self.store, index, self.agent.llm, self.agent.emotional_state)
        if self.features.vault:
            self.memory.vault = ObsidianVault(config.vault_path)
        self.memory.on_change = self._broadcast_brain
        self.memory.on_recall = self._broadcast_recall
        self.memory.on_forget = self._broadcast_history
        self.agent.memory = self.memory
        self.sockets: set[ClientSocket] = set()
        self.turn_lock = asyncio.Lock()
        self.session: ClientSession | None = None
        # El conteo va junto a la memoria: en la web, la carpeta del código es de solo lectura.
        self.photo_budget = PhotoBudgetService(
            config.active_memory_path.parent / "photo_usage.json", daily_limit=DAILY_PHOTO_LIMIT
        )
        # Mirar por su cuenta solo tiene sentido en la Mac, donde oye el cuarto y vive todo el día.
        self.ambient_camera = config.nova_ambient_camera and self.features.microphone
        self.glance_minutes = config.nova_glance_minutes
        self.glances = GlanceClock()
        self.glance_tasks: set[asyncio.Task[None]] = set()
        if self.ambient_camera:
            self.agent.surroundings = SurroundingsService(self.agent.llm)
        self.pending_photo_id: str | None = None
        self.pending_photo: asyncio.Future[str | None] | None = None
        self.pending_browser: dict[str, asyncio.Future[BrowserResultRequest]] = {}
        self.last_gesture_at: float | None = None
        self.listening: "ListeningService | None" = None
        if self.features.microphone:
            from services.voice.listening_service import ListeningService

            from services.context.voice_identity_service import VoiceIdentityService

            self.listening = ListeningService(
                config.wake_model_path,
                config.whisper_model_path,
                self._on_listen_state,
                self._on_heard,
                self._on_wake,
            )
            if self.ambient_camera:
                from services.voice.sound_event_service import SoundEventService

                self.listening.sounds = SoundEventService(config.models_path / "sound", self._on_sound)
            # Mi voz solo se reconoce en lo que oye el micrófono de la Mac. La huella queda junto a
            # la de la cara, fuera de la base que se sincroniza con la nube.
            self.agent.voices = VoiceIdentityService(
                config.models_path / "voice", config.active_memory_path.parent / "voice_profile.npy"
            )
        # Frases que se van juntando para aprender mi voz; `None` si no se está aprendiendo.
        self.voice_clips: "list[np.ndarray] | None" = None
        self.voice_enroll_started = 0.0
        self.voice_verified_at = float("-inf")
        self.listening_socket: ClientSocket | None = None
        self.listening_camera_on = False
        self.voice_turn: asyncio.Task[None] | None = None
        # Cada saludo se genera una vez y se guarda: después ya no gasta créditos de voz.
        self.greeting_voice_id = config.elevenlabs_voice_id or "default"
        self.greeting_folder = config.active_memory_path.parent / "greetings"
        self.last_greeting: str | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.opening: asyncio.Task[None] | None = None
        self.syncing: asyncio.Task[None] | None = None
        self.pending_syncs: set[asyncio.Task[None]] = set()
        self.voice_loading: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Abre la sesión HTTP y empieza a cargar la memoria."""
        self.session = create_http_session()
        self.loop = asyncio.get_running_loop()

        # El modelo tarda en cargar: se hace aparte para no retrasar el arranque.
        self.opening = asyncio.create_task(self.memory.open())
        # El modelo de voces tarda en cargar: se adelanta para no retrasar la primera petición.
        voices = self.agent.voices
        if voices and voices.is_enrolled and voices.is_available:
            self.voice_loading = asyncio.create_task(asyncio.to_thread(voices.load))
        if self.ambient_camera and self.glance_minutes:
            self.glance_tasks.add(asyncio.create_task(self._keep_glancing()))
        # En la web cada turno sube lo suyo: una instancia dormida no llegaría a los 30 segundos.
        if not self.features.serverless:
            self.syncing = asyncio.create_task(self._keep_synced())

    async def stop(self) -> None:
        """Termina lo pendiente, sube la memoria y cierra las conexiones."""
        for task in self.glance_tasks:
            task.cancel()
        await asyncio.gather(*self.glance_tasks, return_exceptions=True)
        if self.listening:
            await asyncio.to_thread(self.listening.stop)
        if self.syncing:
            self.syncing.cancel()
            await asyncio.gather(self.syncing, return_exceptions=True)
        if self.opening:
            await self.opening
        await self.flush()
        await self.memory.close()
        await asyncio.to_thread(self.store.sync, True)
        if self.session:
            await self.session.close()
        await self.anthropic.close()

    async def flush(self) -> None:
        """Espera a que se formen los recuerdos y los reportes pendientes, y sube todo a la nube.

        La web lo llama al cerrarse cada conexión: después, la instancia puede congelarse.
        """
        if self.agent.reports and self.agent.reports.pending:
            await asyncio.gather(*self.agent.reports.pending, return_exceptions=True)
        if self.memory.pending:
            await asyncio.gather(*self.memory.pending, return_exceptions=True)
        if self.pending_syncs:
            await asyncio.gather(*self.pending_syncs, return_exceptions=True)
        await asyncio.to_thread(self.store.sync)

    async def http_session_lifecycle(self, _app: web.Application) -> AsyncIterator[None]:
        """Arranca y apaga el servidor junto con la aplicación de aiohttp.

        Args:
            _app: Aplicación de aiohttp.

        Yields:
            El control mientras el servidor está en marcha.
        """
        await self.start()
        yield
        await self.stop()

    async def _report_done(self, event: EmailDoneEvent) -> None:
        """Avisa en todas las pantallas cómo terminó un reporte, y se lo hace saber a Nova.

        Args:
            event: Resultado del reporte.
        """
        note = (
            f"The email report \"{event.subject}\" reached Carlos's inbox."
            if event.sent
            else "The email report you were preparing failed and was not sent. Tell him if he asks."
        )
        self.agent.conversation.add_system_note(note)
        await self._broadcast(event)

    def _sync_soon(self) -> None:
        """Sube la memoria en cuanto terminen los recuerdos de este turno, sin trabar el siguiente."""

        async def sync() -> None:
            """Espera las extracciones en curso y sube los cambios."""
            if self.memory.pending:
                await asyncio.gather(*self.memory.pending, return_exceptions=True)
            await asyncio.to_thread(self.store.sync)

        task = asyncio.create_task(sync())
        self.pending_syncs.add(task)
        task.add_done_callback(self.pending_syncs.discard)

    async def _keep_synced(self) -> None:
        """Sube los cambios a la nube cada cierto tiempo, en otro hilo para no trabar a Nova."""
        while True:
            await asyncio.sleep(SYNC_SECONDS)
            await asyncio.to_thread(self.store.sync)

    async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """Atiende una conexión del navegador hasta que se cierra.

        Args:
            request: Petición de apertura del WebSocket.

        Returns:
            La respuesta WebSocket ya cerrada.

        Raises:
            web.HTTPForbidden: Si la conexión viene de otro origen.
        """
        # Sin esto, cualquier web abierta en el navegador podría usar tus claves.
        if request.headers.get("Origin") not in ALLOWED_ORIGINS:
            raise web.HTTPForbidden(text="Origin not allowed")

        socket = web.WebSocketResponse(heartbeat=HEARTBEAT_SECONDS)
        await socket.prepare(request)
        await self.serve(socket, _text_messages(socket))
        return socket

    async def handle_session(self, _request: web.Request) -> web.Response:
        """Le dice a la interfaz que en la Mac no hace falta contraseña.

        Args:
            _request: Petición del navegador.

        Returns:
            El estado de la sesión en JSON.
        """
        status = SessionStatus(required=False, authenticated=True)
        return web.json_response(text=status.model_dump_json())

    async def serve(self, socket: ClientSocket, messages: AsyncIterator[str]) -> None:
        """Atiende los mensajes de una pantalla hasta que se desconecta.

        Args:
            socket: Conexión ya aceptada, de aiohttp o de FastAPI.
            messages: Texto de cada mensaje que llega por esa conexión.
        """
        # Otra instancia pudo guardar algo mientras esta dormía.
        if self.features.serverless and await asyncio.to_thread(self.store.pull):
            self.agent.conversation.reload()
        self.sockets.add(socket)
        await self._send(
            socket,
            CapabilitiesEvent(
                microphone=self.listening is not None,
                desktop=self.agent.writer is not None,
                faces=self.agent.faces is not None,
            ),
        )
        await self._send_saved_state(socket)

        turn: asyncio.Task[None] | None = None
        try:
            async for data in messages:
                # Valida la petición.
                try:
                    client_request = CLIENT_REQUEST.validate_json(data)
                except ValidationError:
                    await self._send(socket, ErrorEvent(message=INVALID_MESSAGE))
                    continue

                # Ver el cerebro y borrar un recuerdo no dependen de la conversación.
                if isinstance(client_request, BrainRequest):
                    await self._send(socket, await self.memory.build_brain())
                    continue
                # Encender y apagar el micrófono no depende de la conversación.
                if isinstance(client_request, ListenRequest):
                    await self._set_listening(socket, client_request.enabled)
                    continue
                if isinstance(client_request, MicGateRequest):
                    # Manda la pantalla que está escuchando: otra, sin turno en curso, abriría el
                    # micrófono mientras Nova todavía habla.
                    if self.listening and socket is self.listening_socket:
                        self.listening.set_gate(client_request.open)
                        self.listening_camera_on = client_request.camera_on
                    continue
                if isinstance(client_request, UsageRequest):
                    quota = await self.agent.tts.quota(self.session)
                    await self._send(socket, self.usage.report(quota))
                    continue
                if isinstance(client_request, VisualProfileRequest):
                    await self._send(socket, self._visual_report())
                    continue
                if isinstance(client_request, ForgetFaceRequest):
                    if self.agent.faces:
                        self.agent.faces.forget()
                    await self._send(socket, self._visual_report())
                    continue
                if isinstance(client_request, ForgetVisualRequest):
                    self.store.delete_visual_observations(client_request.observation_id)
                    await self._send(socket, self._visual_report())
                    await asyncio.to_thread(self.store.sync, True)
                    continue
                if isinstance(client_request, ForgetMemoryRequest):
                    await self.memory.forget_by_id(client_request.memory_id)
                    self.agent.conversation.reload()
                    await self._broadcast_history()
                    await asyncio.to_thread(self.store.sync, True)
                    continue

                # La foto se atiende aunque haya un turno en curso: ese turno la está esperando.
                if isinstance(client_request, PhotoResponse):
                    self._resolve_photo(client_request)
                    continue
                # Igual con lo que hizo la extensión en el navegador.
                if isinstance(client_request, BrowserResultRequest):
                    self._resolve_browser_action(client_request)
                    continue

                # Interrumpir también se atiende en pleno turno: precisamente lo detiene.
                if isinstance(client_request, InterruptRequest):
                    await self._interrupt(socket, turn if turn and not turn.done() else self.voice_turn)
                    continue

                # El resto de peticiones requiere que no haya otro turno en curso.
                if self.turn_lock.locked():
                    # Un gesto no es un mensaje: si Nova está ocupada, simplemente no reacciona.
                    if not isinstance(client_request, GestureRequest):
                        await self._send(socket, ErrorEvent(message=BUSY_MESSAGE))
                    continue

                # Reaccionar a un gesto gasta una llamada al modelo, así que tiene un límite.
                if isinstance(client_request, GestureRequest):
                    if self._gesture_is_allowed(client_request.name):
                        turn = asyncio.create_task(self._react_to_gesture(socket, client_request.name))
                        await asyncio.sleep(0)
                    continue

                # Calmar es inmediato: borra el ánimo y lo confirma al navegador.
                if isinstance(client_request, CalmRequest):
                    self.agent.calm()
                    print("[Emotion] calmed by user", flush=True)
                    await self._send(socket, EmotionEvent(components=[]))
                    continue

                # El turno corre aparte para seguir detectando si el navegador se desconecta.
                turn = asyncio.create_task(
                    self._run_turn(
                        socket,
                        client_request.text,
                        client_request.camera_on,
                        browser_on=client_request.browser_on,
                    )
                )
                await asyncio.sleep(0)
        finally:
            self.sockets.discard(socket)

            # Otra pantalla abierta hereda el micrófono; sin ninguna, no se queda abierto.
            if socket is self.listening_socket:
                self.listening_socket = next(
                    (other for other in self.sockets if not other.closed), None
                )
                if self.listening_socket is None:
                    await self._set_listening(socket, False)
                if self.voice_turn and not self.voice_turn.done():
                    self.voice_turn.cancel()
                    await asyncio.gather(self.voice_turn, return_exceptions=True)

            # Si el usuario se fue a mitad de respuesta, no se sigue gastando en la API.
            if turn and not turn.done():
                turn.cancel()
                await asyncio.gather(turn, return_exceptions=True)
        return socket

    async def _set_listening(self, socket: ClientSocket, enabled: bool) -> None:
        """Enciende o apaga el micrófono, sin trabar el servidor mientras se abre el micrófono.

        Args:
            socket: Pantalla que lo pidió; a ella se responde lo que se oiga.
            enabled: Si debe quedar escuchando.
        """
        # Sin micrófono en el servidor, la interfaz usa el dictado del navegador.
        if self.listening is None:
            return
        if enabled:
            self.listening_socket = socket
            self.listening.set_gate(True)
            self.listening.start()
        else:
            self.listening_socket = None
            await asyncio.to_thread(self.listening.stop)
            print("[Listen] microphone off", flush=True)

    def _on_listen_state(self, state: "ListenState") -> None:
        """Recibe un cambio de estado desde el hilo del micrófono y lo pasa a las pantallas.

        Args:
            state: Estado nuevo.
        """
        print(f"[Listen] {state}", flush=True)
        if self.loop:
            event = ListenStateEvent(state=state)
            asyncio.run_coroutine_threadsafe(self._broadcast(event), self.loop)

    def _on_heard(self, text: str, samples: "np.ndarray") -> None:
        """Recibe una petición desde el hilo del micrófono y la lleva al hilo principal.

        Args:
            text: Petición transcrita.
            samples: Su audio, solo en memoria.
        """
        if self.loop:
            self.loop.call_soon_threadsafe(self._start_voice_turn, text, samples)

    def _visual_report(self) -> VisualProfileEvent:
        """Junta lo que muestra la vista "Cómo te ve".

        Returns:
            Las costumbres, las observaciones y si ya aprendió mi cara.
        """
        report = self.agent.visual.report()
        report.face_enrolled = bool(self.agent.faces and self.agent.faces.is_enrolled)
        return report

    def _on_wake(self) -> None:
        """Recibe desde el hilo del micrófono que llamaron a Nova sin pedir nada más."""
        if self.loop:
            self.loop.call_soon_threadsafe(self._start_greeting)

    def _start_greeting(self) -> None:
        """Empieza el saludo, si hay una pantalla abierta y Nova está libre."""
        socket = self.listening_socket
        if socket is None or socket.closed or self.turn_lock.locked():
            print("[Listen] no greeting: Nova is busy or no screen is open", flush=True)
            return

        # Se cierra el paso de audio de inmediato: su propia voz no debe volver a entrar.
        if self.listening:
            self.listening.set_gate(False)
        self.voice_turn = asyncio.create_task(self._greet(socket))

    async def _greeting_audio(self, greeting: str) -> bytes | None:
        """Lee el audio de un saludo, y lo genera la primera vez.

        Args:
            greeting: Texto del saludo.

        Returns:
            El audio en MP3, o `None` si no se pudo generar.
        """
        key = hashlib.sha256(f"{self.greeting_voice_id}:{greeting}".encode()).hexdigest()[:16]
        path = self.greeting_folder / f"{key}.mp3"
        if path.exists():
            return await asyncio.to_thread(path.read_bytes)
        audio = await self.agent.tts.text_to_audio(self.session, greeting, 0)
        if audio:
            path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(path.write_bytes, audio)
        return audio

    async def _greet(self, socket: ClientSocket) -> None:
        """Saluda sin pasar por el modelo: es inmediato y no gasta en la API.

        Args:
            socket: Pantalla que debe mostrar el saludo.
        """
        async with self.turn_lock:
            try:
                await self._send(socket, GreetingEvent())
                blend = self.agent.emotional_state.absorb(EmotionBlend(components=[GREETING_MOOD]))
                await self._send(socket, EmotionEvent(components=blend.components))
                # Nunca repite el mismo saludo dos veces seguidas.
                greeting = random.choice([text for text in GREETINGS if text != self.last_greeting])
                self.last_greeting = greeting
                await self._send(socket, TokenEvent(text=greeting))
                audio = await self._greeting_audio(greeting)
                if audio:
                    await socket.send_bytes(audio)
                self.agent.conversation.add_assistant_message(greeting)
                await self._send(socket, DoneEvent())
            except asyncio.CancelledError:
                raise
            except Exception:
                traceback.print_exc()
                await self._send(socket, ErrorEvent(message=TURN_FAILED_MESSAGE))

    def _start_voice_turn(self, text: str, samples: "np.ndarray") -> None:
        """Inicia un turno con lo que se oyó, si Nova está libre.

        Args:
            text: Petición transcrita.
            samples: Su audio, para saber si soy yo o para aprender mi voz.
        """
        socket = self.listening_socket
        if socket is None or socket.closed or self.turn_lock.locked():
            print("[Listen] ignored: Nova is busy or no screen is open", flush=True)
            return

        async def run() -> None:
            """Muestra lo que se oyó y responde, si lo dije yo."""
            # Si ya conoce mi voz, solo me responde a mí: lo que diga otra persona ni se muestra,
            # ni gasta un turno, ni llega a Claude.
            enrolling = self._is_enrolling_voice()
            voice = None if enrolling else await self._check_voice(samples)
            if not enrolling and not self._voice_is_allowed(voice):
                reason = "not Carlos" if voice else "too short to tell and not recognized recently"
                print(f"[Voice] ignored: {reason}", flush=True)
                if self.listening:
                    self.listening.set_gate(True)
                # Alguien más está con él: Nova no le responde, pero voltea a ver.
                if voice is not None:
                    self._glance_soon("voice", f'you heard a voice that is not Carlos\'s say: "{text[:200]}"')
                return

            await self._send(socket, HeardEvent(text=text))

            # Mientras aprende mi voz, lo que digo no es una petición: solo se escucha.
            if enrolling:
                await self._continue_voice_enrollment(socket, samples)
                return
            if self.agent.voices and VOICE_REQUEST.search(text):
                await self._start_voice_enrollment(socket, text, samples)
                return

            await self._run_turn(socket, text, self.listening_camera_on, spoken=True, voice=voice)
            # Si me despedí, se termina la plática: para volver a hablarle, la llamo otra vez.
            if self.agent.said_goodbye and self.listening:
                self.listening.end_conversation()

        # Se cierra el paso de audio de inmediato: su propia voz no debe volver a entrar.
        if self.listening:
            self.listening.set_gate(False)
        self.voice_turn = asyncio.create_task(run())

    def _on_sound(self, event: SoundEvent) -> None:
        """Recibe desde el hilo del micrófono un sonido fuera de lo normal.

        Args:
            event: Sonido reconocido.
        """
        if self.loop:
            self.loop.call_soon_threadsafe(self._react_to_sound, event)

    def _react_to_sound(self, event: SoundEvent) -> None:
        """Voltea a ver después de un ruido raro.

        Args:
            event: Sonido reconocido.
        """
        print(f"[Sound] {event.label} ({event.probability:.2f})", flush=True)
        self._glance_soon(
            "sound", f"you heard what sounded like {event.label.lower()} ({event.probability:.0%} sure)"
        )

    async def _keep_glancing(self) -> None:
        """Da un vistazo de rutina cada cierto tiempo, mientras el micrófono está encendido."""
        while True:
            await asyncio.sleep(self.glance_minutes * 60)
            if self.listening_socket is not None:
                await self._glance("routine", "a routine glance; nothing in particular triggered it")

    def _glance_soon(self, kind: GlanceKind, reason: str) -> None:
        """Da un vistazo sin trabar lo que esté pasando.

        Args:
            kind: Qué la hizo mirar.
            reason: El motivo en palabras, para el modelo.
        """
        task = asyncio.create_task(self._glance(kind, reason))
        self.glance_tasks.add(task)
        task.add_done_callback(self.glance_tasks.discard)

    def _glance_is_allowed(self, kind: GlanceKind) -> bool:
        """Revisa que se pueda mirar ahora sin molestar ni gastar de más.

        Args:
            kind: Qué la hizo mirar.

        Returns:
            Si puede tomar la foto.
        """
        socket = self.listening_socket
        if not self.agent.surroundings or socket is None or socket.closed:
            return False
        if self.turn_lock.locked() or self._is_enrolling_voice():
            return False
        if self.photo_budget.remaining() <= AMBIENT_PHOTO_RESERVE:
            return False
        now = time.monotonic()
        cooldown = next(seconds for name, seconds in GLANCE_COOLDOWNS if name == kind)
        last_of_kind = getattr(self.glances, f"last_{kind}")
        return now - self.glances.last_any >= GLANCE_MIN_GAP_SECONDS and now - last_of_kind >= cooldown

    async def _glance(self, kind: GlanceKind, reason: str) -> None:
        """Mira por su cuenta, entiende lo que ve y habla solo si importa.

        Args:
            kind: Qué la hizo mirar.
            reason: El motivo en palabras, para el modelo.
        """
        if not self._glance_is_allowed(kind):
            return
        now = time.monotonic()
        self.glances.last_any = now
        setattr(self.glances, f"last_{kind}", now)
        socket = self.listening_socket
        try:
            async with self.turn_lock:
                photo = await self._request_photo(socket, ambient=True)
            if not photo.data_url:
                return
            face = await self.agent.check_face(photo)
            decision = await self.agent.surroundings.interpret(
                photo.data_url, kind, reason, self.agent.recent_conversation(), face
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            traceback.print_exc()
            return
        print(f"[Glance] {kind}: {decision.observation} (speak: {decision.speak})", flush=True)

        # Si mientras tanto empezó una plática, no la interrumpe: lo visto queda como contexto.
        if decision.speak and not self.turn_lock.locked() and not socket.closed:
            self.agent.conversation.add_system_note(SPOKE_ON_OWN_NOTE.format(reason=reason))
            if self.listening:
                self.listening.set_gate(False)
            await self._send(socket, ProactiveEvent())
            await self._say(socket, decision.say)
            if self.listening:
                self.listening.start_conversation()

    async def _check_voice(self, samples: "np.ndarray") -> VoiceCheck | None:
        """Compara la voz de una petición con la mía, en otro hilo para no trabar a Nova.

        Un fallo aquí no debe arruinar la respuesta: simplemente no se sabe quién habló.

        Args:
            samples: Audio de la petición.

        Returns:
            Si soy yo, o `None` si no aplica.
        """
        if not self.agent.voices:
            return None
        try:
            voice = await asyncio.to_thread(self.agent.voices.check, samples)
        except Exception:
            traceback.print_exc()
            return None
        if voice:
            who = "Carlos" if voice.carlos_speaking else "someone else"
            print(f"[Voice] {who} ({voice.similarity:.2f})", flush=True)
        return voice

    def _voice_is_allowed(self, voice: VoiceCheck | None) -> bool:
        """Decide si Nova debe responder a lo que se oyó.

        Args:
            voice: Resultado de comparar la voz con la mía; `None` si no se pudo saber.

        Returns:
            Si soy yo. Sin mi voz aprendida, responde a cualquiera.
        """
        voices = self.agent.voices
        if not voices or not voices.is_enrolled or not voices.is_available:
            return True
        if voice is not None:
            if voice.carlos_speaking:
                self.voice_verified_at = time.monotonic()
            return voice.carlos_speaking
        # Muy corta para saberlo: vale si hace poco me reconoció, como "sí" en plena plática.
        return time.monotonic() - self.voice_verified_at < VOICE_TRUST_SECONDS

    def _is_enrolling_voice(self) -> bool:
        """Dice si está juntando frases para aprender mi voz; si tardé demasiado, lo deja.

        Returns:
            Si la siguiente frase es para aprender mi voz.
        """
        if self.voice_clips is None:
            return False
        if time.monotonic() - self.voice_enroll_started > VOICE_ENROLL_TIMEOUT_SECONDS:
            print("[Voice] enrollment expired", flush=True)
            self.voice_clips = None
            return False
        return True

    async def _start_voice_enrollment(
        self, socket: ClientSocket, text: str, samples: "np.ndarray"
    ) -> None:
        """Empieza a aprender mi voz: la frase con que lo pedí ya cuenta.

        Args:
            socket: Pantalla que lo muestra.
            text: Lo que dije para pedirlo.
            samples: Su audio.
        """
        if not self.agent.voices.is_available:
            await self._say(socket, VOICE_ENROLL_UNAVAILABLE, user_text=text)
            return
        print("[Voice] enrollment started", flush=True)
        self.voice_clips = [samples]
        self.voice_enroll_started = time.monotonic()
        await self._say(socket, VOICE_ENROLL_START, user_text=text)

    async def _continue_voice_enrollment(self, socket: ClientSocket, samples: "np.ndarray") -> None:
        """Junta otra frase y, si ya hay suficiente voz, aprende mi voz.

        Args:
            socket: Pantalla que lo muestra.
            samples: Audio de la frase; no se guarda ni su texto ni su audio.
        """
        clips = self.voice_clips
        clips.append(samples)
        seconds = sum(clip.size for clip in clips) / SAMPLE_RATE
        if seconds < VOICE_ENROLL_SECONDS and len(clips) < VOICE_ENROLL_MAX_PHRASES:
            await self._say(socket, VOICE_ENROLL_MORE)
            return

        self.voice_clips = None
        try:
            result = await asyncio.to_thread(self.agent.voices.enroll, clips)
        except Exception:
            traceback.print_exc()
            await self._send(socket, ErrorEvent(message=TURN_FAILED_MESSAGE))
            return
        print(f"[Voice] enrollment: {result.status} ({result.seconds_used} s)", flush=True)
        if result.status == "learned":
            self.agent.conversation.add_system_note(
                VOICE_LEARNED_NOTE.format(seconds=round(result.seconds_used))
            )
            await self._say(socket, VOICE_ENROLLED)
        else:
            await self._say(socket, VOICE_ENROLL_SHORT)

    async def _say(self, socket: ClientSocket, text: str, user_text: str | None = None) -> None:
        """Dice una frase fija con su voz, sin pasar por el modelo.

        Args:
            socket: Pantalla que lo muestra.
            text: Lo que dice Nova.
            user_text: Lo que pedí, si debe quedar en el historial.
        """
        async with self.turn_lock:
            try:
                if user_text:
                    self.agent.conversation.add_user_message(user_text)
                await self._send(socket, TokenEvent(text=text))
                audio = await self.agent.tts.text_to_audio(self.session, text, 0)
                if audio:
                    await socket.send_bytes(audio)
                self.agent.conversation.add_assistant_message(text)
                await self._send(socket, DoneEvent())
            except asyncio.CancelledError:
                raise
            except Exception:
                traceback.print_exc()
                await self._send(socket, ErrorEvent(message=TURN_FAILED_MESSAGE))

    async def _broadcast(self, event: ServerEvent) -> None:
        """Envía un evento a todas las pantallas abiertas.

        Una pestaña que se cerró o recargó puede seguir en la lista un momento. Eso no debe
        tumbar el turno de la pestaña con la que se está conversando.

        Args:
            event: Evento que se va a enviar.
        """
        for socket in list(self.sockets):
            try:
                await self._send(socket, event)
            except ConnectionError:
                self.sockets.discard(socket)

    async def _broadcast_brain(self, brain: BrainEvent) -> None:
        """Envía el cerebro actualizado a todas las pantallas abiertas.

        Args:
            brain: Estado del cerebro.
        """
        await self._broadcast(brain)

    async def _broadcast_recall(self, memory_ids: list[int]) -> None:
        """Avisa a las pantallas abiertas qué recuerdos acaba de recuperar Nova.

        Args:
            memory_ids: Recuerdos recuperados.
        """
        await self._broadcast(RecallEvent(memory_ids=memory_ids))

    async def _broadcast_history(self) -> None:
        """Sustituye el chat en todas las pantallas, tras borrar mensajes de la memoria."""
        await self._broadcast(HistoryEvent(messages=self._visible_history(), replace=True))

    def _visible_history(self) -> list[HistoryMessage]:
        """Prepara la conversación guardada para mostrarla en el chat.

        Returns:
            Los mensajes visibles, del más antiguo al más reciente.
        """
        history = [
            HistoryMessage(role=item.role, text=self._visible_text(item.content))
            for item in self.store.recent_messages(HISTORY_MESSAGES_SHOWN)
            if item.role != "system"
        ]
        return [message for message in history if message.text]

    async def _send_saved_state(self, socket: ClientSocket) -> None:
        """Envía al navegador la conversación guardada y cómo se siente Nova ahora.

        Args:
            socket: Conexión con el navegador.
        """
        await self._send(socket, HistoryEvent(messages=self._visible_history()))

        mood = self.agent.emotional_state.current()
        await self._send(socket, EmotionEvent(components=mood.components))

    @staticmethod
    def _visible_text(content: str) -> str:
        """Prepara un mensaje guardado para mostrarlo en el chat.

        Args:
            content: Texto guardado, con etiquetas o la descripción de un gesto.

        Returns:
            El texto para la interfaz.
        """
        for gesture, _, _, label in GESTURES:
            if content == gesture_message(gesture):
                return label
        return strip_tags(content)

    async def _interrupt(
        self, socket: ClientSocket, turn: asyncio.Task[None] | None
    ) -> None:
        """Detiene el turno en curso y le hace saber al navegador cómo reaccionó Nova.

        Args:
            socket: Conexión con el navegador.
            turn: Turno de esta conexión; puede haber terminado aunque la voz siga sonando.
        """
        turn_is_running = turn is not None and not turn.done()
        blend = self.agent.interrupt(turn_is_running)

        # Cancelar también corta la conexión con el modelo, así no se paga por el resto.
        if turn_is_running:
            turn.cancel()
            await asyncio.gather(turn, return_exceptions=True)

        # La confirmación marca el corte: lo anterior que siga en camino debe descartarse.
        await self._send(socket, InterruptedEvent())
        await self._send(socket, EmotionEvent(components=blend.components))
        print(f"[Interrupted] {self.agent.interruptions.count()} recently", flush=True)

    def _gesture_is_allowed(self, gesture: Gesture) -> bool:
        """Comprueba si ya pasó la espera entre reacciones a gestos.

        Args:
            gesture: Gesto detectado; se registra en la terminal.

        Returns:
            Si Nova puede reaccionar ahora.
        """
        now = time.monotonic()
        is_cooling_down = (
            self.last_gesture_at is not None
            and now - self.last_gesture_at < GESTURE_COOLDOWN_SECONDS
        )
        if is_cooling_down:
            print(f"[Gesture] {gesture} ignored: cooling down", flush=True)
            return False

        self.last_gesture_at = now
        print(f"[Gesture] {gesture}", flush=True)
        return True

    async def _react_to_gesture(self, socket: ClientSocket, gesture: Gesture) -> None:
        """Hace que Nova reaccione por su cuenta a un gesto.

        Args:
            socket: Conexión con el navegador.
            gesture: Gesto detectado.
        """
        # La emoción se muestra de inmediato; las palabras tardan unos segundos en llegar.
        blend = self.agent.react_to_gesture(gesture)
        await self._send(socket, GestureReactionEvent(gesture=gesture))
        await self._send(socket, EmotionEvent(components=blend.components))
        await self._run_turn(socket, gesture_message(gesture), True)

    def _resolve_photo(self, response: PhotoResponse) -> None:
        """Entrega al turno en espera la foto que envió el navegador.

        Args:
            response: Respuesta del navegador; se ignora si no es la que se esperaba.
        """
        is_expected = response.request_id == self.pending_photo_id
        if is_expected and self.pending_photo and not self.pending_photo.done():
            self.pending_photo.set_result(response.data_url)

    def _resolve_browser_action(self, result: BrowserResultRequest) -> None:
        """Entrega al turno en espera lo que hizo la extensión en el navegador.

        Args:
            result: Respuesta de la extensión; se ignora si nadie la espera.
        """
        pending = self.pending_browser.get(result.request_id)
        if pending and not pending.done():
            pending.set_result(result)

    async def _request_browser_action(
        self, socket: ClientSocket, action: BrowserAction
    ) -> BrowserResultRequest:
        """Pide a la extensión una acción en el navegador y espera lo que pasó.

        Args:
            socket: Conexión con la extensión.
            action: Qué hacer.

        Returns:
            Lo que respondió la extensión, o un fallo si no respondió a tiempo.
        """
        request_id = uuid.uuid4().hex
        pending = asyncio.get_running_loop().create_future()
        self.pending_browser[request_id] = pending
        try:
            await self._send(socket, BrowserActionEvent(request_id=request_id, action=action))
            return await asyncio.wait_for(pending, BROWSER_ACTION_TIMEOUT_SECONDS)
        except (TimeoutError, ConnectionError):
            return BrowserResultRequest(request_id=request_id, ok=False, text=BROWSER_NO_RESPONSE)
        finally:
            self.pending_browser.pop(request_id, None)

    async def _request_photo(
        self, socket: ClientSocket, ignore_cooldown: bool = False, ambient: bool = False
    ) -> PhotoResult:
        """Intenta obtener una foto del navegador, respetando los límites de uso.

        Args:
            socket: Conexión con el navegador.
            ignore_cooldown: Si no hace falta la espera entre fotos.
            ambient: Si Nova mira por su cuenta; la interfaz no la pone en el chat.

        Returns:
            La foto, o el motivo por el que no se obtuvo.
        """
        # Los límites se comprueban aquí, sin importar lo que haya pedido el modelo.
        status = self.photo_budget.check(ignore_cooldown)
        if status != "granted":
            print(f"[Photo] denied: {status}", flush=True)
            return PhotoResult(status=status)

        # Pide la foto y espera la respuesta, que llega por el bucle del WebSocket.
        self.pending_photo_id = uuid.uuid4().hex
        self.pending_photo = asyncio.get_running_loop().create_future()
        await self._send(
            socket,
            PhotoRequestEvent(
                request_id=self.pending_photo_id,
                remaining=self.photo_budget.remaining(),
                ambient=ambient,
            ),
        )
        try:
            data_url = await asyncio.wait_for(self.pending_photo, PHOTO_TIMEOUT_SECONDS)
        except TimeoutError:
            print("[Photo] browser did not respond", flush=True)
            return PhotoResult(status="failed")
        finally:
            self.pending_photo_id = None
            self.pending_photo = None

        # Sin imagen significa que la cámara no se pudo encender; eso no gasta cupo.
        if data_url is None:
            print("[Photo] camera unavailable", flush=True)
            return PhotoResult(status="camera_off")

        self.photo_budget.record()
        print(f"[Photo] taken, {self.photo_budget.remaining()} left today", flush=True)
        return PhotoResult(status="granted", data_url=data_url)

    async def _run_turn(
        self,
        socket: ClientSocket,
        text: str,
        camera_on: bool,
        spoken: bool = False,
        voice: VoiceCheck | None = None,
        browser_on: bool = False,
    ) -> None:
        """Ejecuta un turno y envía al navegador todo lo que produzca.

        Args:
            socket: Conexión con el navegador.
            text: Mensaje del usuario.
            camera_on: Si la cámara está encendida en este momento.
            spoken: Si llegó por el micrófono de la Mac.
            voice: Si la voz era la mía.
            browser_on: Si le hablo desde la extensión de Chrome, que puede usar el navegador.
        """

        async def send_token(token: str) -> None:
            """Envía un fragmento de texto.

            Args:
                token: Texto que se va a mostrar.
            """
            await self._send(socket, TokenEvent(text=token))

        async def send_emotion(blend: EmotionBlend) -> None:
            """Envía el estado emocional actual.

            Args:
                blend: Emociones que debe mostrar el personaje.
            """
            feelings = ", ".join(f"{item.name} {item.intensity:.2f}" for item in blend.components)
            print(f"[Emotion] {feelings or 'calm'}", flush=True)
            await self._send(socket, EmotionEvent(components=blend.components))

        async def take_photo(ignore_cooldown: bool = False) -> PhotoResult:
            """Pide una foto al navegador conectado.

            Args:
                ignore_cooldown: Si no hace falta la espera entre fotos.

            Returns:
                La foto, o el motivo por el que no se obtuvo.
            """
            return await self._request_photo(socket, ignore_cooldown)

        async def run_browser_action(action: BrowserAction) -> BrowserResultRequest:
            """Ejecuta una acción en el navegador de la extensión conectada.

            Args:
                action: Qué hacer.

            Returns:
                Lo que pasó.
            """
            return await self._request_browser_action(socket, action)

        async def send_search(
            event: SearchStartEvent
            | SearchDoneEvent
            | WriteStartEvent
            | WriteDoneEvent
            | BrowseStartEvent
            | BrowseDoneEvent
            | MoveEvent,
        ) -> None:
            """Avisa al navegador de una búsqueda, de que escribe en otra app o de que se mueva.

            Args:
                event: Inicio o final de la actividad, o el lugar a donde ir.
            """
            # Quien se mueve es la ventana flotante, aunque se lo pidas desde la ventana completa.
            if isinstance(event, MoveEvent):
                await self._broadcast(event)
                return
            await self._send(socket, event)

        async with self.turn_lock:
            try:
                await self.agent.run_turn(
                    self.session,
                    text,
                    send_token,
                    socket.send_bytes,
                    send_emotion,
                    take_photo,
                    camera_on,
                    send_search,
                    spoken,
                    voice,
                    run_browser_action if browser_on else None,
                )
                await self._send(socket, DoneEvent())
                if self.features.serverless:
                    self._sync_soon()
            except asyncio.CancelledError:
                raise
            except Exception:
                # El detalle queda en la terminal; al navegador no llegan respuestas de la API.
                traceback.print_exc()
                await self._send(socket, ErrorEvent(message=TURN_FAILED_MESSAGE))

    @staticmethod
    async def _send(socket: ClientSocket, event: ServerEvent) -> None:
        """Envía un evento al navegador en JSON.

        Args:
            socket: Conexión con el navegador.
            event: Evento que se va a enviar.
        """
        await socket.send_str(event.model_dump_json())


def create_app() -> web.Application:
    """Crea la aplicación web con sus rutas.

    Returns:
        La aplicación lista para ejecutarse.
    """
    server = NovaServer(Config())
    app = web.Application()
    app.router.add_get("/ws", server.handle_websocket)
    app.router.add_get("/api/session", server.handle_session)

    # Sirve la interfaz compilada para la app de escritorio; en desarrollo la sirve Vite.
    if FRONTEND_DIST.is_dir():

        async def index(_request: web.Request) -> web.FileResponse:
            """Entrega la página principal.

            Args:
                _request: Petición del navegador.

            Returns:
                El archivo de la interfaz.
            """
            return web.FileResponse(FRONTEND_DIST / "index.html")

        app.router.add_get("/", index)
        app.router.add_static("/", FRONTEND_DIST)

    app.cleanup_ctx.append(server.http_session_lifecycle)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host=HOST, port=PORT)

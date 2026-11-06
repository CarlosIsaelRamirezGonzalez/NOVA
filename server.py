"""Puente local entre la cara de Nova (`frontend/`) y las APIs de xAI.

Uso: `python server.py`
"""

import asyncio
import time
import traceback
from pathlib import Path
import uuid
from collections.abc import AsyncIterator

from aiohttp import ClientSession, WSMsgType, web
from pydantic import ValidationError

from config import Config
from nova.prompts.nova_prompts import NOVA_AVATAR_INSTRUCTIONS, NOVA_SYSTEM_PROMPT
from services.agents.agm import GESTURES, AgentManager, gesture_message
from services.chunk.emotion_filter import strip_tags
from services.agents.llms_service import LLMService
from services.agents.web_search_service import WebSearchService
from services.context.conversation_service import ConversationService
from services.context.memory_service import MemoryService
from services.context.memory_store import MemoryStore
from services.context.obsidian_vault import ObsidianVault
from services.context.photo_budget_service import PhotoBudgetService
from services.context.usage_service import UsageService
from services.context.vector_index import VectorIndex
from services.http_client import create_anthropic_client, create_http_session
from services.schemas import (
    CLIENT_REQUEST,
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
    SearchStartEvent,
    ServerEvent,
    ListenRequest,
    ListenStateEvent,
    HeardEvent,
    MicGateRequest,
    UsageRequest,
    TokenEvent,
)
from services.voice.listening_service import ListeningService, ListenState
from services.voice.tts_service import TTSService

HOST = "127.0.0.1"
PORT = 8787
# Sincronizar cuesta casi un segundo de red, así que se agrupan los cambios.
SYNC_SECONDS = 30
HEARTBEAT_SECONDS = 30
PHOTO_TIMEOUT_SECONDS = 10
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
TURN_FAILED_MESSAGE = "No pude responder. Revisa la terminal del servidor."
INVALID_MESSAGE = "Mensaje vacío o demasiado largo."
BUSY_MESSAGE = "Sigo respondiendo el turno anterior."


class NovaServer:
    """Atiende el WebSocket del navegador y ejecuta los turnos de conversación."""

    def __init__(self, config: Config) -> None:
        """Construye los servicios; la conversación se comparte entre conexiones.

        Args:
            config: Configuración validada de Nova.
        """
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
        self.memory = MemoryService(
            self.store,
            VectorIndex(config.vector_path, config.models_path),
            self.agent.llm,
            self.agent.emotional_state,
        )
        self.memory.vault = ObsidianVault(config.vault_path)
        self.memory.on_change = self._broadcast_brain
        self.memory.on_recall = self._broadcast_recall
        self.memory.on_forget = self._broadcast_history
        self.agent.memory = self.memory
        self.sockets: set[web.WebSocketResponse] = set()
        self.turn_lock = asyncio.Lock()
        self.session: ClientSession | None = None
        self.photo_budget = PhotoBudgetService()
        self.pending_photo_id: str | None = None
        self.pending_photo: asyncio.Future[str | None] | None = None
        self.last_gesture_at: float | None = None
        self.listening = ListeningService(
            config.wake_model_path,
            config.whisper_model_path,
            self._on_listen_state,
            self._on_heard,
        )
        self.listening_socket: web.WebSocketResponse | None = None
        self.listening_camera_on = False
        self.voice_turn: asyncio.Task[None] | None = None
        self.loop: asyncio.AbstractEventLoop | None = None

    async def http_session_lifecycle(self, _app: web.Application) -> AsyncIterator[None]:
        """Abre la sesión HTTP al arrancar y la cierra al apagar.

        Args:
            _app: Aplicación de aiohttp.

        Yields:
            El control mientras el servidor está en marcha.
        """
        self.session = create_http_session()
        self.loop = asyncio.get_running_loop()

        # El modelo tarda en cargar: se hace aparte para no retrasar el arranque.
        opening = asyncio.create_task(self.memory.open())
        syncing = asyncio.create_task(self._keep_synced())
        yield
        await asyncio.to_thread(self.listening.stop)
        syncing.cancel()
        await asyncio.gather(syncing, return_exceptions=True)
        await opening
        await self.memory.close()
        await asyncio.to_thread(self.store.sync, True)
        await self.session.close()
        await self.anthropic.close()

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
        self.sockets.add(socket)
        await self._send_saved_state(socket)

        turn: asyncio.Task[None] | None = None
        try:
            async for message in socket:
                if message.type != WSMsgType.TEXT:
                    continue

                # Valida la petición.
                try:
                    client_request = CLIENT_REQUEST.validate_json(message.data)
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
                    self.listening.set_gate(client_request.open)
                    self.listening_camera_on = client_request.camera_on
                    continue
                if isinstance(client_request, UsageRequest):
                    quota = await self.agent.tts.quota(self.session)
                    await self._send(socket, self.usage.report(quota))
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
                    self._run_turn(socket, client_request.text, client_request.camera_on)
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

    async def _set_listening(self, socket: web.WebSocketResponse, enabled: bool) -> None:
        """Enciende o apaga el micrófono, sin trabar el servidor mientras se abre el micrófono.

        Args:
            socket: Pantalla que lo pidió; a ella se responde lo que se oiga.
            enabled: Si debe quedar escuchando.
        """
        if enabled:
            self.listening_socket = socket
            self.listening.set_gate(True)
            self.listening.start()
        else:
            self.listening_socket = None
            await asyncio.to_thread(self.listening.stop)
            print("[Listen] microphone off", flush=True)

    def _on_listen_state(self, state: ListenState) -> None:
        """Recibe un cambio de estado desde el hilo del micrófono y lo pasa a las pantallas.

        Args:
            state: Estado nuevo.
        """
        print(f"[Listen] {state}", flush=True)
        if self.loop:
            event = ListenStateEvent(state=state)
            asyncio.run_coroutine_threadsafe(self._broadcast(event), self.loop)

    def _on_heard(self, text: str) -> None:
        """Recibe una petición desde el hilo del micrófono y la lleva al hilo principal.

        Args:
            text: Petición transcrita.
        """
        if self.loop:
            self.loop.call_soon_threadsafe(self._start_voice_turn, text)

    def _start_voice_turn(self, text: str) -> None:
        """Inicia un turno con lo que se oyó, si Nova está libre.

        Args:
            text: Petición transcrita.
        """
        socket = self.listening_socket
        if socket is None or socket.closed or self.turn_lock.locked():
            print("[Listen] ignored: Nova is busy or no screen is open", flush=True)
            return

        async def run() -> None:
            """Muestra lo que se oyó y responde."""
            await self._send(socket, HeardEvent(text=text))
            await self._run_turn(socket, text, self.listening_camera_on)

        # Se cierra el paso de audio de inmediato: su propia voz no debe volver a entrar.
        self.listening.set_gate(False)
        self.voice_turn = asyncio.create_task(run())

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

    async def _send_saved_state(self, socket: web.WebSocketResponse) -> None:
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
        self, socket: web.WebSocketResponse, turn: asyncio.Task[None] | None
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

    async def _react_to_gesture(self, socket: web.WebSocketResponse, gesture: Gesture) -> None:
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

    async def _request_photo(self, socket: web.WebSocketResponse) -> PhotoResult:
        """Intenta obtener una foto del navegador, respetando los límites de uso.

        Args:
            socket: Conexión con el navegador.

        Returns:
            La foto, o el motivo por el que no se obtuvo.
        """
        # Los límites se comprueban aquí, sin importar lo que haya pedido el modelo.
        status = self.photo_budget.check()
        if status != "granted":
            print(f"[Photo] denied: {status}", flush=True)
            return PhotoResult(status=status)

        # Pide la foto y espera la respuesta, que llega por el bucle del WebSocket.
        self.pending_photo_id = uuid.uuid4().hex
        self.pending_photo = asyncio.get_running_loop().create_future()
        await self._send(
            socket,
            PhotoRequestEvent(
                request_id=self.pending_photo_id, remaining=self.photo_budget.remaining()
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

        # Sin imagen significa que la cámara está apagada; eso no gasta cupo.
        if data_url is None:
            print("[Photo] camera is off", flush=True)
            return PhotoResult(status="camera_off")

        self.photo_budget.record()
        print(f"[Photo] taken, {self.photo_budget.remaining()} left today", flush=True)
        return PhotoResult(status="granted", data_url=data_url)

    async def _run_turn(self, socket: web.WebSocketResponse, text: str, camera_on: bool) -> None:
        """Ejecuta un turno y envía al navegador todo lo que produzca.

        Args:
            socket: Conexión con el navegador.
            text: Mensaje del usuario.
            camera_on: Si la cámara está encendida en este momento.
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

        async def take_photo() -> PhotoResult:
            """Pide una foto al navegador conectado.

            Returns:
                La foto, o el motivo por el que no se obtuvo.
            """
            return await self._request_photo(socket)

        async def send_search(event: SearchStartEvent | SearchDoneEvent) -> None:
            """Avisa al navegador de una búsqueda en internet.

            Args:
                event: Inicio o final de la búsqueda.
            """
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
                )
                await self._send(socket, DoneEvent())
            except asyncio.CancelledError:
                raise
            except Exception:
                # El detalle queda en la terminal; al navegador no llegan respuestas de la API.
                traceback.print_exc()
                await self._send(socket, ErrorEvent(message=TURN_FAILED_MESSAGE))

    @staticmethod
    async def _send(socket: web.WebSocketResponse, event: ServerEvent) -> None:
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

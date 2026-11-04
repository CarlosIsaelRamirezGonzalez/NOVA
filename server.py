"""Puente local entre la cara de Nova (`frontend/`) y las APIs de xAI.

Uso: `python server.py`
"""

import asyncio
import time
import traceback
import uuid
from collections.abc import AsyncIterator

from aiohttp import ClientSession, WSMsgType, web
from pydantic import ValidationError

from config import Config
from nova.prompts.nova_prompts import NOVA_AVATAR_INSTRUCTIONS, NOVA_SYSTEM_PROMPT
from services.agents.agm import GESTURES, AgentManager, gesture_message
from services.chunk.emotion_filter import strip_tags
from services.agents.llms_service import LLMService
from services.context.conversation_service import ConversationService
from services.context.memory_service import MemoryService
from services.context.memory_store import MemoryStore
from services.context.obsidian_vault import ObsidianVault
from services.context.photo_budget_service import PhotoBudgetService
from services.context.vector_index import VectorIndex
from services.http_client import create_http_session
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
    ServerEvent,
    TokenEvent,
)
from services.voice.tts_service import TTSService

HOST = "127.0.0.1"
PORT = 8787
HEARTBEAT_SECONDS = 30
PHOTO_TIMEOUT_SECONDS = 10
GESTURE_COOLDOWN_SECONDS = 30
HISTORY_MESSAGES_SHOWN = 60
ALLOWED_ORIGINS = frozenset({"http://localhost:5173", "http://127.0.0.1:5173"})

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
        self.store = MemoryStore(config.memory_path)
        self.agent = AgentManager(
            ConversationService(NOVA_SYSTEM_PROMPT + NOVA_AVATAR_INSTRUCTIONS, store=self.store),
            LLMService(config.xai_api_key, config.chat_api_url),
            TTSService(config.xai_api_key, config.tts_api_url),
            store=self.store,
        )
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

    async def http_session_lifecycle(self, _app: web.Application) -> AsyncIterator[None]:
        """Abre la sesión HTTP al arrancar y la cierra al apagar.

        Args:
            _app: Aplicación de aiohttp.

        Yields:
            El control mientras el servidor está en marcha.
        """
        self.session = create_http_session()

        # El modelo tarda en cargar: se hace aparte para no retrasar el arranque.
        opening = asyncio.create_task(self.memory.open())
        yield
        await opening
        await self.memory.close()
        await self.session.close()

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
                if isinstance(client_request, ForgetMemoryRequest):
                    await self.memory.forget_by_id(self.session, client_request.memory_id)
                    self.agent.conversation.reload()
                    await self._broadcast_history()
                    continue

                # La foto se atiende aunque haya un turno en curso: ese turno la está esperando.
                if isinstance(client_request, PhotoResponse):
                    self._resolve_photo(client_request)
                    continue

                # Interrumpir también se atiende en pleno turno: precisamente lo detiene.
                if isinstance(client_request, InterruptRequest):
                    await self._interrupt(socket, turn)
                    continue

                # El resto de peticiones requiere que no haya otro turno en curso.
                if self.turn_lock.locked():
                    # Un gesto no es un mensaje: si Nova está ocupada, simplemente no reacciona.
                    if not isinstance(client_request, GestureRequest):
                        await self._send(socket, ErrorEvent(message=BUSY_MESSAGE))
                    continue

                # Reaccionar a un gesto gasta una llamada a Grok, así que tiene un límite.
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
            # Si el usuario se fue a mitad de respuesta, no se sigue gastando en la API.
            if turn and not turn.done():
                turn.cancel()
                await asyncio.gather(turn, return_exceptions=True)
        return socket

    async def _broadcast_brain(self, brain: BrainEvent) -> None:
        """Envía el cerebro actualizado a todas las pantallas abiertas.

        Args:
            brain: Estado del cerebro.
        """
        for socket in list(self.sockets):
            await self._send(socket, brain)

    async def _broadcast_recall(self, memory_ids: list[int]) -> None:
        """Avisa a las pantallas abiertas qué recuerdos acaba de recuperar Nova.

        Args:
            memory_ids: Recuerdos recuperados.
        """
        for socket in list(self.sockets):
            await self._send(socket, RecallEvent(memory_ids=memory_ids))

    async def _broadcast_history(self) -> None:
        """Sustituye el chat en todas las pantallas, tras borrar mensajes de la memoria."""
        for socket in list(self.sockets):
            await self._send(socket, HistoryEvent(messages=self._visible_history(), replace=True))

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

        # Cancelar también corta la conexión con Grok, así no se paga por el resto.
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
    app.cleanup_ctx.append(server.http_session_lifecycle)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host=HOST, port=PORT)

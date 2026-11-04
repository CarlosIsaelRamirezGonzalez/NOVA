"""Orquestación de un turno de conversación: Grok, emociones, frases y voz."""

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from contextlib import aclosing
from datetime import datetime

from aiohttp import ClientSession

from services.agents.llms_service import LLMService
from services.chunk.chunk_service import ChunkingService
from services.chunk.emotion_filter import EmotionTagFilter, strip_tags
from services.context.conversation_service import ConversationService
from services.context.emotional_state_service import EmotionalStateService
from services.context.interruption_service import InterruptionService
from services.context.memory_service import MemoryService
from services.context.memory_store import MemoryStore
from services.schemas import (
    ChatMessage,
    ChatRequest,
    EmotionBlend,
    EmotionComponent,
    Gesture,
    ImagePart,
    ImageUrl,
    PhotoResult,
    PhotoStatus,
    StreamedReply,
    TextPart,
)
from services.voice.tts_service import TTSService

DEFAULT_MODEL = "grok-4.5"
MAX_CONCURRENT_TTS = 4
MISUSED_VOICE_TAG = re.compile(
    r"\[/?(?:whisper|soft|loud|slow|fast|emphasis|higher-pitch|lower-pitch|build-intensity"
    r"|decrease-intensity)\]"
)
CALMED_NOTE = (
    "Carlos just pressed a button to calm you down. You feel calm now and your earlier "
    "distress has passed. Do not bring it up unless he does."
)

TokenHandler = Callable[[str], Awaitable[None]]
AudioHandler = Callable[[bytes], Awaitable[None]]
EmotionHandler = Callable[[EmotionBlend], Awaitable[None]]
PhotoProvider = Callable[[], Awaitable[PhotoResult]]

INTERRUPTED_NOTE = (
    "Carlos interrupted you at this point. He did not hear anything you would have said after this."
)
CUT_OFF_NOTE = (
    "Carlos interrupted you while your last reply was still being spoken, so he may not have heard "
    "the end of it."
)

FORGOTTEN_NOTE = (
    "Carlos asked you to forget something and it has been erased. You no longer remember it. "
    "Do not try to work out what it was."
)

# Grok no puede saber si la cámara está encendida: sin esto, lo adivina.
CAMERA_ON_CONTEXT = (
    "Carlos's camera is ON right now. Write [[photo]] only if he asks you to look, or asks about how "
    "he looks or something he is showing you; then you must, and never answer about his appearance "
    "without it. News, feelings, and ordinary questions don't need a photo, and being on camera is "
    "no reason to take one. Anything said earlier about the camera being off is out of date."
)
CAMERA_OFF_CONTEXT = (
    "Carlos's camera is OFF right now. If he asks you to look at him, do not write [[photo]]: "
    "tell him to turn it on with the Cámara button. You cannot see him."
)

PHOTO_CAPTION = (
    "This is the photo you asked for, taken just now with Carlos's camera. "
    "Answer his last message based on what you actually see."
)

# Qué se le dice a Grok según lo ocurrido; en el historial queda solo el texto, nunca la imagen.
PHOTO_NOTES: tuple[tuple[PhotoStatus, str], ...] = (
    (
        "granted",
        "You saw a photo for that reply. The image is no longer available: to see him "
        "again you must ask for a new one.",
    ),
    (
        "camera_off",
        "No photo: Carlos's camera is off. Tell him to turn it on with the Cámara button. "
        "You saw nothing, so do not describe or guess what he looks like.",
    ),
    (
        "daily_limit",
        "No photo: today's photo limit has been reached. Tell him so. You saw nothing, so do "
        "not describe or guess.",
    ),
    (
        "cooldown",
        "No photo: you took one moments ago and must wait a little. Tell him so. You saw "
        "nothing new, so do not guess.",
    ),
    (
        "failed",
        "No photo: the camera failed to respond. Tell him so. You saw nothing, so do not guess.",
    ),
)


SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400


def describe_elapsed(seconds: float) -> str:
    """Expresa un lapso de tiempo de forma legible para Grok.

    Args:
        seconds: Segundos transcurridos.

    Returns:
        El lapso redondeado a la unidad más natural, en inglés.
    """
    if seconds < SECONDS_PER_MINUTE:
        return "moments"
    if seconds < SECONDS_PER_HOUR:
        return f"{round(seconds / SECONDS_PER_MINUTE)} minute(s)"
    if seconds < SECONDS_PER_DAY:
        return f"{round(seconds / SECONDS_PER_HOUR)} hour(s)"
    return f"{round(seconds / SECONDS_PER_DAY)} day(s)"


# Qué se le dice a Grok de cada gesto y qué siente Nova en el instante en que lo ve.
GESTURES: tuple[tuple[Gesture, str, tuple[EmotionComponent, ...], str], ...] = (
    (
        "middle_finger",
        "Carlos just flipped you off with his middle finger at the camera, without saying a word.",
        (
            EmotionComponent(name="surprised", intensity=0.5),
            EmotionComponent(name="angry", intensity=0.5),
        ),
        "(Le enseñaste el dedo de en medio)",
    ),
    (
        "thumbs_up",
        "Carlos just gave you a thumbs up at the camera, without saying a word.",
        (EmotionComponent(name="happy", intensity=0.6),),
        "(Le hiciste pulgar arriba)",
    ),
)


def gesture_message(gesture: Gesture) -> str:
    """Describe un gesto para que Grok reaccione a él.

    Args:
        gesture: Gesto detectado.

    Returns:
        La descripción, entre corchetes para distinguirla de lo que Carlos escribe.
    """
    description = next(text for name, text, _, _ in GESTURES if name == gesture)
    return (
        f"[{description} You noticed it on your own, in the moment. "
        "React out loud, briefly and in character. Do not write [[photo]].]"
    )


def photo_note(status: PhotoStatus) -> str:
    """Busca la nota que corresponde a un resultado de la cámara.

    Args:
        status: Resultado de intentar tomar la foto.

    Returns:
        La nota para Grok.
    """
    return next(note for candidate, note in PHOTO_NOTES if candidate == status)


class SpeechPipeline:
    """Genera los audios en paralelo y los entrega en el orden de las frases."""

    def __init__(self, session: ClientSession, tts: TTSService, on_audio: AudioHandler) -> None:
        """Prepara la cola y empieza a entregar audio.

        Args:
            session: Sesión HTTP compartida.
            tts: Servicio que convierte texto en audio.
            on_audio: Función que recibe cada audio ya en orden.
        """
        self.session = session
        self.tts = tts
        self.on_audio = on_audio
        self.limit = asyncio.Semaphore(MAX_CONCURRENT_TTS)
        self.tasks: list[asyncio.Task[bytes | None]] = []
        self.queue: asyncio.Queue[asyncio.Task[bytes | None] | None] = asyncio.Queue()
        self.delivery = asyncio.create_task(self._deliver())

    def enqueue(self, text: str) -> None:
        """Solicita el audio de una frase sin esperar el resultado.

        Args:
            text: Frase que se va a pronunciar.
        """
        # Una marca de entrega escrita como `[soft]` en vez de `<soft>` se leería en voz alta.
        text = MISUSED_VOICE_TAG.sub("", text).strip()

        # Un signo suelto no se puede pronunciar y haría fallar a la API de voz.
        if not any(character.isalnum() for character in text):
            return

        task = asyncio.create_task(self._synthesize(text, len(self.tasks)))
        self.tasks.append(task)
        self.queue.put_nowait(task)

    async def finish(self) -> None:
        """Avisa que no hay más frases y espera a que se entregue todo el audio."""
        self.queue.put_nowait(None)
        await self.delivery

    async def close(self) -> None:
        """Cancela lo que siga pendiente, por ejemplo si el usuario se desconecta."""
        self.delivery.cancel()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(self.delivery, *self.tasks, return_exceptions=True)

    async def _synthesize(self, text: str, index: int) -> bytes | None:
        """Genera un audio respetando el límite de peticiones simultáneas.

        Args:
            text: Frase que se va a pronunciar.
            index: Posición de la frase en la respuesta.

        Returns:
            El audio generado, o `None` si falló.
        """
        async with self.limit:
            return await self.tts.text_to_audio(self.session, text, index)

    async def _deliver(self) -> None:
        """Entrega los audios en orden, esperando cada uno aunque otros terminen antes."""
        while (task := await self.queue.get()) is not None:
            audio = await task
            if audio is not None:
                await self.on_audio(audio)


class AgentManager:
    """Coordina los servicios que intervienen en cada turno."""

    def __init__(
        self,
        conversation: ConversationService,
        llm: LLMService,
        tts: TTSService,
        model: str = DEFAULT_MODEL,
        store: MemoryStore | None = None,
    ) -> None:
        """Guarda los servicios.

        Args:
            conversation: Historial de la conversación.
            llm: Cliente de la API de chat.
            tts: Cliente de la API de voz.
            model: Identificador del modelo de lenguaje.
            store: Memoria persistente; sin ella, el ánimo se pierde al cerrar.
        """
        self.conversation = conversation
        self.llm = llm
        self.tts = tts
        self.model = model
        self.store = store
        self.emotional_state = EmotionalStateService(store=store)
        self.interruptions = InterruptionService()
        self.is_interrupting = False
        self.partial_reply = ""
        self.memory: MemoryService | None = None

    def calm(self) -> None:
        """Calma a Nova y se lo hace saber al modelo.

        Sin la nota, el historial llevaría a Grok a seguir respondiendo alterada.
        """
        self.emotional_state.calm()
        self.interruptions.clear()
        self.conversation.add_system_note(CALMED_NOTE)

    def react_to_gesture(self, gesture: Gesture) -> EmotionBlend:
        """Aplica la reacción emocional inmediata a un gesto.

        Args:
            gesture: Gesto detectado.

        Returns:
            El estado emocional resultante.
        """
        components = next(items for name, _, items, _ in GESTURES if name == gesture)
        return self.emotional_state.intensify(EmotionBlend(components=list(components)))

    def interrupt(self, turn_is_running: bool) -> EmotionBlend:
        """Registra una interrupción y calcula cómo le afecta a Nova.

        Quien llama debe cancelar el turno en curso después de esto.

        Args:
            turn_is_running: Si Grok seguía respondiendo. Si no, Nova ya terminó de escribir,
                pero su voz aún estaba sonando en el navegador.

        Returns:
            El estado emocional resultante.
        """
        if turn_is_running:
            self.is_interrupting = True
        else:
            self.conversation.add_system_note(CUT_OFF_NOTE)
        return self.emotional_state.intensify(self.interruptions.record())

    async def run_turn(
        self,
        session: ClientSession,
        user_input: str,
        on_token: TokenHandler,
        on_audio: AudioHandler,
        on_emotion: EmotionHandler,
        request_photo: PhotoProvider,
        camera_on: bool = False,
    ) -> str:
        """Ejecuta un turno y entrega texto y audio mientras Grok sigue escribiendo.

        Si Nova pide ver la cámara, se hace una segunda llamada con la foto. Solo se
        permite una por turno.

        Args:
            session: Sesión HTTP compartida.
            user_input: Mensaje del usuario.
            on_token: Recibe cada fragmento de texto limpio.
            on_audio: Recibe cada audio, en el orden de las frases.
            on_emotion: Recibe el estado emocional cada vez que Nova reacciona.
            request_photo: Intenta obtener una foto de la cámara.
            camera_on: Si la cámara está encendida en este momento.

        Returns:
            La última respuesta completa, incluidas las etiquetas de emoción.

        Raises:
            RuntimeError: Si la API de chat responde con un error.
        """
        # Lee cuándo hablaron por última vez antes de guardar este mensaje.
        time_context = self._time_context()

        # Registra el mensaje y prepara las piezas de este turno.
        self.conversation.add_user_message(user_input)
        # Grok recibe lo que Nova aún siente, para que influya en su respuesta, y el estado real
        # de la cámara.
        camera_context = CAMERA_ON_CONTEXT if camera_on else CAMERA_OFF_CONTEXT
        recollections = await self.memory.recall(user_input) if self.memory else None
        notes = [
            time_context,
            recollections,
            self.emotional_state.describe(),
            self.interruptions.describe(),
            camera_context,
        ]
        context = "\n\n".join(note for note in notes if note)
        self.partial_reply = ""
        request = self.conversation.build_request(self.model, context)
        speech = SpeechPipeline(session, self.tts, on_audio)

        try:
            reply = await self._stream_reply(session, request, speech, on_token, on_emotion, True)
            first_reply: StreamedReply | None = None

            # Olvidar: borra de verdad y deja que Nova lo confirme con lo que realmente se borró.
            if reply.forget_requested and self.memory:
                await self._forget_and_confirm(
                    session, user_input, reply, context, speech, on_token, on_emotion
                )
                await speech.finish()
                return ""

            # Si pidió la foto, Grok responde de nuevo ya viendo la imagen o sabiendo por qué no.
            if reply.photo_requested:
                first_reply = reply
                photo = await request_photo()
                extra_messages = [
                    ChatMessage(role="assistant", content=first_reply.raw_text),
                    self._photo_message(photo),
                ]
                request = self.conversation.build_request(self.model, context, extra_messages)
                reply = await self._stream_reply(
                    session, request, speech, on_token, on_emotion, False
                )

            await speech.finish()
        except BaseException:
            # Si la interrumpieron, recuerda hasta dónde llegó; si fue otra cosa, como una
            # desconexión, el turno no queda en el historial.
            if self.is_interrupting:
                self._save_interrupted_turn()
                self._remember_later(session, user_input, self.partial_reply)
            else:
                self.conversation.discard_last_user_message()
            raise
        finally:
            await speech.close()

        # El historial conserva las etiquetas, para que el modelo las siga usando, pero nunca la foto.
        if first_reply is not None:
            self.conversation.add_assistant_message(first_reply.raw_text)
            self.conversation.add_system_note(photo_note(photo.status))
        self.conversation.add_assistant_message(reply.raw_text)
        self._remember_later(session, user_input, reply.raw_text)
        return reply.raw_text

    async def _stream_reply(
        self,
        session: ClientSession,
        request: ChatRequest,
        speech: SpeechPipeline,
        on_token: TokenHandler,
        on_emotion: EmotionHandler,
        photo_allowed: bool,
    ) -> StreamedReply:
        """Hace una llamada a Grok y entrega lo que va llegando.

        Args:
            session: Sesión HTTP compartida.
            request: Petición para la API de chat.
            speech: Cola de audio del turno.
            on_token: Recibe cada fragmento de texto limpio.
            on_emotion: Recibe el estado emocional cada vez que Nova reacciona.
            photo_allowed: Si Nova todavía puede pedir una foto en este turno.

        Returns:
            La respuesta completa y si Nova pidió una foto.
        """
        chunking = ChunkingService()
        emotion_filter = EmotionTagFilter()
        reply = StreamedReply()

        # `aclosing` cierra la conexión aunque se corte el stream antes de que termine.
        async with aclosing(self.llm.stream_response(session, request)) as tokens:
            async for token in tokens:
                reply.raw_text += token
                self.partial_reply += token
                filtered = emotion_filter.feed(token)
                for blend in filtered.blends:
                    await on_emotion(self.emotional_state.absorb(blend))
                await self._forward_text(filtered.text, chunking, speech, on_token)

                # Corta aquí para no pagar por lo que escribiría sin haber visto la foto.
                if filtered.photo_requested and photo_allowed:
                    reply.photo_requested = True
                    break
                if filtered.forget_requested and photo_allowed:
                    reply.forget_requested = True
                    break

        # Libera el texto retenido y la última frase, que puede no tener puntuación.
        await self._forward_text(emotion_filter.flush(), chunking, speech, on_token)
        final_chunk = chunking.flush()
        if final_chunk:
            speech.enqueue(final_chunk)
        return reply

    async def _forget_and_confirm(
        self,
        session: ClientSession,
        user_input: str,
        reply: StreamedReply,
        context: str,
        speech: SpeechPipeline,
        on_token: TokenHandler,
        on_emotion: EmotionHandler,
    ) -> None:
        """Borra lo que Carlos pidió olvidar y hace que Nova lo confirme.

        Este turno no se guarda: su propio mensaje podría contener lo que quiere olvidar.

        Args:
            session: Sesión HTTP compartida.
            user_input: Mensaje con el que Carlos lo pidió.
            reply: Lo que Nova alcanzó a decir antes de la etiqueta.
            context: Notas de sistema de este turno.
            speech: Cola de audio del turno.
            on_token: Recibe cada fragmento de texto limpio.
            on_emotion: Recibe el estado emocional cada vez que Nova reacciona.
        """
        forgotten = await self.memory.forget_from_request(session, user_input)
        self.conversation.discard_last_user_message()
        self.conversation.reload()

        # Lo olvidado también debe desaparecer de la pantalla.
        if self.memory.on_forget:
            await self.memory.on_forget()

        # La confirmación usa los mensajes de este turno sin añadirlos al historial.
        result = (
            f"You erased {len(forgotten)} memory(ies). Confirm it in one brief line, without "
            "repeating what it said."
            if forgotten
            else "You found no saved memory matching that. Say so briefly, and that any mention of "
            "it in the conversation was erased."
        )
        extra_messages = [
            ChatMessage(role="user", content="(Carlos asked you to forget something.)"),
            ChatMessage(role="assistant", content=strip_tags(reply.raw_text) or "..."),
            ChatMessage(role="system", content=result),
        ]
        request = self.conversation.build_request(self.model, context, extra_messages)
        await self._stream_reply(session, request, speech, on_token, on_emotion, False)
        self.conversation.add_system_note(FORGOTTEN_NOTE)

    def _remember_later(self, session: ClientSession, user_input: str, reply: str) -> None:
        """Pide formar recuerdos de este turno, en segundo plano.

        Args:
            session: Sesión HTTP compartida.
            user_input: Mensaje de Carlos.
            reply: Respuesta de Nova, posiblemente interrumpida.
        """
        # Los gestos llegan entre corchetes: no son algo que Carlos haya dicho.
        if self.memory and not user_input.startswith("["):
            self.memory.remember_later(session, user_input, strip_tags(reply))

    def _time_context(self) -> str:
        """Redacta la hora actual y cuánto pasó desde el último mensaje de Carlos.

        Returns:
            La nota para Grok.
        """
        now = datetime.now().astimezone().strftime("%A, %Y-%m-%d %H:%M")
        last = self.store.last_user_message_at() if self.store else None
        if last is None:
            return f"Current local date and time: {now}."
        elapsed = describe_elapsed(time.time() - last)
        return f"Current local date and time: {now}. Carlos last wrote to you {elapsed} ago."

    def _save_interrupted_turn(self) -> None:
        """Guarda en el historial lo que Nova alcanzó a decir antes de que la cortaran."""
        self.is_interrupting = False
        if self.partial_reply.strip():
            self.conversation.add_assistant_message(self.partial_reply)
        self.conversation.add_system_note(INTERRUPTED_NOTE)

    @staticmethod
    def _photo_message(photo: PhotoResult) -> ChatMessage:
        """Convierte el resultado de la cámara en un mensaje para Grok.

        Args:
            photo: Resultado de intentar tomar la foto.

        Returns:
            La imagen adjunta, o una nota de sistema con el motivo por el que no hay foto.
        """
        if photo.data_url is None:
            return ChatMessage(role="system", content=photo_note(photo.status))

        return ChatMessage(
            role="user",
            content=[
                TextPart(text=PHOTO_CAPTION),
                ImagePart(image_url=ImageUrl(url=photo.data_url)),
            ],
        )

    @staticmethod
    async def _forward_text(
        text: str,
        chunking: ChunkingService,
        speech: SpeechPipeline,
        on_token: TokenHandler,
    ) -> None:
        """Envía texto limpio a la pantalla y sus frases completas a la voz.

        Args:
            text: Texto ya sin etiquetas.
            chunking: Acumulador de frases de la llamada.
            speech: Cola de audio del turno.
            on_token: Recibe el texto para mostrarlo.
        """
        if not text:
            return
        await on_token(text)
        for chunk in chunking.add_token(text):
            speech.enqueue(chunk)

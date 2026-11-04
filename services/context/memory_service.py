"""Recuerdos de Nova: decide qué guardar de cada conversación y qué recordar en cada turno."""

import asyncio
import time
import traceback
from collections.abc import Awaitable, Callable
from datetime import datetime

from aiohttp import ClientSession

from services.agents.llms_service import LLMService
from services.context.emotional_state_service import EmotionalStateService
from services.context.memory_store import MemoryStore
from services.context.obsidian_vault import ObsidianVault
from services.context.vector_index import VectorIndex
from services.schemas import (
    BrainEvent,
    BrainLink,
    ChatMessage,
    ChatRequest,
    ExtractionResult,
    ForgetDecision,
    JsonSchemaFormat,
    Memory,
    ResponseFormat,
)

# Es rápido y barato, y extrae en segundo plano para no retrasar la respuesta.
EXTRACTION_MODEL = "grok-4.20-non-reasoning"

RECALL_LIMIT = 6
SEARCH_CANDIDATES = 15
MIN_SIMILARITY = 0.15
# Lo que se vivió con intensidad y lo que importa más vuelve a la mente con más facilidad.
EMOTION_WEIGHT = 0.12
IMPORTANCE_WEIGHT = 0.08
# Con un límite bajo se perdían cosas útiles: buscar por significado no siempre las encuentra.
PROFILE_IMPORTANCE = 0.6
PROFILE_LIMIT = 20
EXISTING_FOR_EXTRACTION = 8

# Enlaces entre recuerdos para el cerebro y Obsidian.
LINK_NEIGHBORS = 4
MIN_LINK_STRENGTH = 0.3

# Una palabra corta podría borrar mensajes que no tienen nada que ver.
MIN_FORGET_TERM_CHARS = 4
FORGET_CANDIDATES = 60
FORGET_CONTEXT_MESSAGES = 6

# Al reiniciar rápido, el proceso anterior puede tardar en soltar la carpeta del índice.
INDEX_OPEN_ATTEMPTS = 20
INDEX_RETRY_SECONDS = 1.0

SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400

EXTRACTION_PROMPT = """
You maintain the long-term memory of Nova, the personal AI companion of Carlos. From the latest
exchange, extract only what will still be useful to remember in future conversations.

Save, as one short sentence in Mexican Spanish that makes sense on its own, naming Carlos:
- fact, preference: stable things about him, what he likes, his work and projects.
- person: people or pets in his life and who they are to him. Keep their names.
- event: something that happened to him.
- plan: something he intends to do; turn relative dates into absolute ones using today's date.
- moment: a significant moment between him and Nova, such as a threat to shut her down or an apology.

Rules:
- Use only what Carlos said himself. Nova's text is context, never a source of facts about him.
- Skip small talk, questions, requests for help, general knowledge, and passing states like being
  hungry. Most exchanges contain nothing worth saving, and an empty list is the right answer then.
- Skip anything that looks like a joke, a test, or a hypothetical.
- Importance: 0.3 for a small detail, 0.6 for something clearly useful, 0.8 for fears, health, and
  anything that should change Nova's advice, 0.9 only for core facts about who he is and who matters
  most to him.
- A moment is its own memory: an apology doesn't replace the threat it apologized for.
- If it is already covered by an existing memory, don't save it again. If it corrects or updates one,
  save the new version and set `replaces` to that memory's id. Otherwise `replaces` is null.
"""

FORGET_PROMPT = """
Carlos asked Nova to forget something. Using his message and the recent conversation, decide exactly
what he means, including vague requests like "olvida eso", which refer to what was just discussed.

Return:
- memory_ids: the ids of the memories, from the list given, that he wants gone. Be precise: don't
  include memories on other subjects. Return an empty list if nothing matches.
- search_terms: very specific words that identify the subject, such as a person's or pet's name, used
  to erase the messages that mention it. Never include common words or his own name.
"""

FORGET_FORMAT = ResponseFormat(
    json_schema=JsonSchemaFormat(name="forget", json_schema=ForgetDecision.model_json_schema())
)

RESPONSE_FORMAT = ResponseFormat(
    json_schema=JsonSchemaFormat(name="memories", json_schema=ExtractionResult.model_json_schema())
)


def describe_age(created_at: float) -> str:
    """Expresa hace cuánto se formó un recuerdo.

    Args:
        created_at: Momento en que se guardó, en segundos.

    Returns:
        La antigüedad en inglés, para el prompt.
    """
    elapsed = time.time() - created_at
    if elapsed < SECONDS_PER_HOUR:
        return "earlier today"
    if elapsed < SECONDS_PER_DAY:
        return f"{round(elapsed / SECONDS_PER_HOUR)} hour(s) ago"
    return f"{round(elapsed / SECONDS_PER_DAY)} day(s) ago"


def describe_memory(memory: Memory) -> str:
    """Redacta un recuerdo con cuándo se formó y qué se sintió.

    Args:
        memory: Recuerdo que se va a describir.

    Returns:
        Una línea para el prompt.
    """
    felt = ", ".join(f"{item.name} {item.intensity:.1f}" for item in memory.emotions.components)
    feeling = f"; you felt {felt}" if felt else ""
    return f"- ({describe_age(memory.created_at)}{feeling}) {memory.content}"


class MemoryService:
    """Forma recuerdos en segundo plano y recupera los relevantes en cada turno."""

    def __init__(
        self,
        store: MemoryStore,
        index: VectorIndex,
        llm: LLMService,
        emotional_state: EmotionalStateService,
    ) -> None:
        """Guarda sus dependencias.

        Args:
            store: Base de datos, la fuente de la verdad.
            index: Índice para buscar por significado.
            llm: Cliente de la API de chat.
            emotional_state: Estado emocional, que se guarda con cada recuerdo.
        """
        self.store = store
        self.index = index
        self.llm = llm
        self.emotional_state = emotional_state
        self.lock = asyncio.Lock()
        self.pending: set[asyncio.Task[None]] = set()
        self.vault: ObsidianVault | None = None
        self.on_change: Callable[[BrainEvent], Awaitable[None]] | None = None
        self.on_recall: Callable[[list[int]], Awaitable[None]] | None = None
        self.on_forget: Callable[[], Awaitable[None]] | None = None

    async def open(self) -> None:
        """Carga el índice en segundo plano; mientras tanto solo está disponible el perfil."""
        for attempt in range(INDEX_OPEN_ATTEMPTS):
            try:
                await asyncio.to_thread(self.index.open, self.store.active_memories())
            except Exception as error:
                # Solo se muestra el último intento: los anteriores suelen ser un reinicio normal.
                if attempt == INDEX_OPEN_ATTEMPTS - 1:
                    traceback.print_exc()
                    print(f"[Memory] SEARCH INDEX UNAVAILABLE: {error}", flush=True)
                    return
                await asyncio.sleep(INDEX_RETRY_SECONDS)
            else:
                print("[Memory] search index ready", flush=True)
                await self.publish()
                return

    async def close(self) -> None:
        """Espera a que terminen las extracciones en curso y cierra el índice."""
        if self.pending:
            await asyncio.gather(*self.pending, return_exceptions=True)
        await asyncio.to_thread(self.index.close)

    async def recall(self, query: str) -> str | None:
        """Busca lo que Nova debería tener presente para este mensaje.

        Args:
            query: Mensaje de Carlos.

        Returns:
            La nota para Grok, o `None` si no recuerda nada relevante.
        """
        profile = self.store.profile_memories(PROFILE_IMPORTANCE, PROFILE_LIMIT)
        related = await self._search(query)

        # El perfil va primero; un recuerdo no se repite si aparece en ambas listas.
        known = {memory.id for memory in profile}
        memories = profile + [memory for memory in related if memory.id not in known]
        if not memories:
            return None

        # La vista del cerebro enciende solo lo que este mensaje trajo a la mente: el perfil
        # siempre está presente, así que encenderlo no diría nada.
        if self.on_recall:
            await self.on_recall([memory.id for memory in related])

        lines = "\n".join(describe_memory(memory) for memory in memories)
        return (
            "What you remember, from past conversations. Some of it may have nothing to do with "
            f"this message; use it only when it fits, naturally.\n{lines}"
        )

    async def build_brain(self) -> BrainEvent:
        """Reúne lo que muestra la vista del cerebro.

        Returns:
            Los recuerdos, sus conexiones y lo que siente Nova ahora.
        """
        memories = self.store.active_memories()
        links = await asyncio.to_thread(self._links, memories)
        return BrainEvent(
            memories=memories, links=links, mood=self.emotional_state.current().components
        )

    async def publish(self) -> None:
        """Actualiza Obsidian y avisa a la vista del cerebro. Un fallo aquí no afecta a Nova."""
        try:
            brain = await self.build_brain()
            if self.vault:
                await asyncio.to_thread(self.vault.export, brain.memories, brain.links, brain.mood)
            if self.on_change:
                await self.on_change(brain)
        except Exception:
            traceback.print_exc()

    async def forget_by_id(self, session: ClientSession, memory_id: int) -> list[Memory]:
        """Borra un recuerdo concreto y los mensajes que lo mencionan.

        Args:
            session: Sesión HTTP compartida.
            memory_id: Recuerdo que se va a borrar.

        Returns:
            Los recuerdos borrados.
        """
        async with self.lock:
            targets = self.store.memories_by_id([memory_id])
            terms: list[str] = []

            # El modelo solo aporta palabras para limpiar los mensajes; qué borrar ya está decidido.
            # Si falla, el recuerdo se borra de todos modos.
            if targets:
                try:
                    request = self._forget_request(f"Olvida esto: {targets[0].content}")
                    completion = await self.llm.complete(session, request)
                    terms = ForgetDecision.model_validate_json(completion).search_terms
                except Exception:
                    traceback.print_exc()
            forgotten = await self._forget([memory_id], terms)
        await self.publish()
        return forgotten

    async def forget_from_request(
        self, session: ClientSession, user_input: str
    ) -> list[Memory]:
        """Interpreta lo que Carlos quiere olvidar y lo borra.

        Args:
            session: Sesión HTTP compartida.
            user_input: Mensaje con el que lo pidió.

        Returns:
            Los recuerdos borrados.
        """
        # Espera a las extracciones en curso: un recuerdo a medio guardar no debe escaparse.
        async with self.lock:
            request = self._forget_request(user_input)
            completion = await self.llm.complete(session, request)
            decision = ForgetDecision.model_validate_json(completion)
            forgotten = await self._forget(decision.memory_ids, decision.search_terms)
        await self.publish()
        return forgotten

    async def _forget(self, memory_ids: list[int], search_terms: list[str]) -> list[Memory]:
        """Borra recuerdos, sus vectores y los mensajes que los mencionan.

        Args:
            memory_ids: Recuerdos que se van a borrar.
            search_terms: Palabras específicas de los mensajes que se van a borrar.

        Returns:
            Los recuerdos borrados.
        """
        forgotten = self.store.delete_memories(memory_ids)
        for memory in forgotten:
            await asyncio.to_thread(self.index.remove, memory.id)

        erased_messages = 0
        for term in search_terms:
            if len(term.strip()) >= MIN_FORGET_TERM_CHARS:
                erased_messages += self.store.delete_messages_containing(term.strip())

        print(
            f"[Memory] forgot {len(forgotten)} memories, "
            f"erased {erased_messages} messages by term",
            flush=True,
        )
        return forgotten

    def _forget_request(self, user_input: str) -> ChatRequest:
        """Construye la petición para interpretar qué hay que olvidar.

        Args:
            user_input: Mensaje con el que Carlos lo pidió.

        Returns:
            La petición lista para enviarse.
        """
        memories = self.store.active_memories()[-FORGET_CANDIDATES:]
        listed = "\n".join(f"[{memory.id}] {memory.content}" for memory in memories)
        recent = self.store.recent_messages(FORGET_CONTEXT_MESSAGES)
        conversation = "\n".join(f"{item.role}: {item.content}" for item in recent)
        content = (
            f"Memories:\n{listed or '(none)'}\n\nRecent conversation:\n{conversation}\n\n"
            f"Carlos's request:\n{user_input}"
        )
        return ChatRequest(
            model=EXTRACTION_MODEL,
            messages=[
                ChatMessage(role="system", content=FORGET_PROMPT),
                ChatMessage(role="user", content=content),
            ],
            temperature=0.0,
            stream=False,
            response_format=FORGET_FORMAT,
        )

    def _links(self, memories: list[Memory]) -> list[BrainLink]:
        """Calcula las conexiones entre recuerdos con significado parecido.

        Args:
            memories: Recuerdos vigentes.

        Returns:
            Las conexiones, sin repetir un par en sentido contrario.
        """
        if not self.index.is_ready:
            return []

        active = {memory.id for memory in memories}
        seen: set[tuple[int, int]] = set()
        links: list[BrainLink] = []
        for memory in memories:
            for hit in self.index.neighbors(memory.id, LINK_NEIGHBORS):
                pair = (min(memory.id, hit.memory_id), max(memory.id, hit.memory_id))
                if hit.memory_id in active and hit.score >= MIN_LINK_STRENGTH and pair not in seen:
                    seen.add(pair)
                    links.append(BrainLink(source=pair[0], target=pair[1], strength=hit.score))
        return links

    def remember_later(self, session: ClientSession, user_input: str, reply: str) -> None:
        """Lanza la extracción de recuerdos sin retrasar la respuesta.

        Args:
            session: Sesión HTTP compartida.
            user_input: Mensaje de Carlos.
            reply: Respuesta de Nova.
        """
        # Se conserva la referencia a la tarea para que no se pierda antes de terminar.
        task = asyncio.create_task(self._remember(session, user_input, reply))
        self.pending.add(task)
        task.add_done_callback(self.pending.discard)

    async def _search(self, query: str) -> list[Memory]:
        """Busca recuerdos por significado y los ordena considerando su peso emocional.

        Args:
            query: Texto de búsqueda.

        Returns:
            Los recuerdos más relevantes.
        """
        if not self.index.is_ready:
            return []
        try:
            hits = await asyncio.to_thread(self.index.search, query, SEARCH_CANDIDATES)
        except Exception:
            traceback.print_exc()
            return []

        # Descarta lo que no se parece.
        similar = [hit for hit in hits if hit.score >= MIN_SIMILARITY]
        memories = self.store.memories_by_id([hit.memory_id for hit in similar])

        def relevance(memory: Memory) -> float:
            """Combina el parecido del recuerdo con su emoción y su importancia.

            Args:
                memory: Recuerdo candidato.

            Returns:
                Su puntaje; mayor es más relevante.
            """
            score = next(hit.score for hit in similar if hit.memory_id == memory.id)
            return (
                score + memory.intensity * EMOTION_WEIGHT + memory.importance * IMPORTANCE_WEIGHT
            )

        return sorted(memories, key=relevance, reverse=True)[:RECALL_LIMIT]

    async def _nearest(self, query: str) -> list[Memory]:
        """Busca los recuerdos más parecidos, sin importar qué tan poco se parezcan.

        Sirve para que el extractor no duplique: un recuerdo poco parecido a la pregunta
        puede ser justo el que ya contiene el dato.

        Args:
            query: Texto de búsqueda.

        Returns:
            Los recuerdos más cercanos.
        """
        if not self.index.is_ready:
            return []
        hits = await asyncio.to_thread(self.index.search, query, EXISTING_FOR_EXTRACTION)
        return self.store.memories_by_id([hit.memory_id for hit in hits])

    async def _remember(self, session: ClientSession, user_input: str, reply: str) -> None:
        """Extrae recuerdos de un intercambio y los guarda.

        Un fallo aquí no debe afectar la conversación, solo se pierde ese recuerdo.

        Args:
            session: Sesión HTTP compartida.
            user_input: Mensaje de Carlos.
            reply: Respuesta de Nova.
        """
        # Una a la vez, para que dos extracciones seguidas no dupliquen el mismo recuerdo.
        async with self.lock:
            try:
                source_id = self.store.last_message_id()
                existing = await self._nearest(user_input)
                request = self._extraction_request(user_input, reply, existing)
                completion = await self.llm.complete(session, request)
                result = ExtractionResult.model_validate_json(completion)
                await self._save(result, source_id, {memory.id for memory in existing})
            except Exception:
                traceback.print_exc()
                return

        if result.memories:
            await self.publish()

    @staticmethod
    def _extraction_request(user_input: str, reply: str, existing: list[Memory]) -> ChatRequest:
        """Construye la petición para el modelo extractor.

        Args:
            user_input: Mensaje de Carlos.
            reply: Respuesta de Nova.
            existing: Recuerdos parecidos, para no duplicarlos.

        Returns:
            La petición lista para enviarse.
        """
        today = datetime.now().astimezone().strftime("%A, %Y-%m-%d")
        known = "\n".join(f"[{memory.id}] {memory.content}" for memory in existing)
        content = (
            f"Today is {today}.\n\nExisting memories:\n{known or '(none)'}\n\n"
            f"Carlos said:\n{user_input}\n\nNova replied:\n{reply}"
        )
        return ChatRequest(
            model=EXTRACTION_MODEL,
            messages=[
                ChatMessage(role="system", content=EXTRACTION_PROMPT),
                ChatMessage(role="user", content=content),
            ],
            temperature=0.0,
            stream=False,
            response_format=RESPONSE_FORMAT,
        )

    async def _save(self, result: ExtractionResult, source_id: int | None, known: set[int]) -> None:
        """Guarda los recuerdos extraídos y actualiza el índice.

        Args:
            result: Lo que propuso el extractor.
            source_id: Mensaje del que salieron.
            known: Identificadores que el extractor pudo ver; solo esos se pueden reemplazar.
        """
        emotions = self.emotional_state.current()

        for item in result.memories:
            # Evita que un identificador inventado deje obsoleto un recuerdo que no tiene relación.
            replaces = item.replaces if item.replaces in known else None
            importance = min(1.0, max(0.0, item.importance))
            memory = self.store.add_memory(
                item.kind, item.content, importance, emotions, source_id, replaces
            )

            if self.index.is_ready:
                await asyncio.to_thread(self.index.add, memory)
                if replaces is not None:
                    await asyncio.to_thread(self.index.remove, replaces)
            print(f"[Memory] saved #{memory.id}: {memory.content}", flush=True)

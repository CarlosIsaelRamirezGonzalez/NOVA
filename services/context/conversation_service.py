"""Historial de la conversación con Nova."""

from services.context.memory_store import MemoryStore
from services.schemas import ChatMessage, ChatRequest, MessageRole

# El modelo solo recibe lo reciente: con todo el historial, cada mensaje costaría más que el anterior.
MAX_CONTEXT_MESSAGES = 40


class ConversationService:
    """Mantiene el contexto para el modelo y lo guarda si hay memoria persistente.

    Attributes:
        system_prompt: Instrucciones de identidad y comportamiento de Nova.
        messages: Mensajes recientes, sin el prompt de sistema.
    """

    def __init__(self, system_prompt: str, store: MemoryStore | None = None) -> None:
        """Recupera la conversación guardada, si existe.

        Args:
            system_prompt: Instrucciones de identidad y comportamiento de Nova.
            store: Memoria persistente; sin ella, todo se pierde al cerrar.
        """
        self.system_prompt = ChatMessage(role="system", content=system_prompt)
        self.store = store
        saved = store.recent_messages(MAX_CONTEXT_MESSAGES) if store else []
        self.messages = [ChatMessage(role=item.role, content=item.content) for item in saved]

    def reload(self) -> None:
        """Vuelve a leer el contexto, después de haber borrado mensajes de la memoria."""
        if self.store:
            saved = self.store.recent_messages(MAX_CONTEXT_MESSAGES)
            self.messages = [ChatMessage(role=item.role, content=item.content) for item in saved]

    def add_user_message(self, text: str) -> None:
        """Agrega un mensaje del usuario.

        Args:
            text: Texto del mensaje.
        """
        self._add("user", text)

    def add_assistant_message(self, text: str) -> None:
        """Agrega una respuesta de Nova.

        Args:
            text: Texto de la respuesta.
        """
        self._add("assistant", text)

    def add_system_note(self, text: str) -> None:
        """Agrega una nota de lo ocurrido fuera de la conversación.

        Args:
            text: Contenido de la nota, dirigido al modelo.
        """
        self._add("system", text)

    def discard_last_user_message(self) -> None:
        """Quita un turno que falló para no dejarlo sin respuesta en el historial."""
        if self.messages and self.messages[-1].role == "user":
            self.messages.pop()
            if self.store:
                self.store.delete_last_message()

    def build_request(
        self,
        model: str,
        context: str | None = None,
        extra_messages: list[ChatMessage] | None = None,
    ) -> ChatRequest:
        """Construye la petición para la API de chat.

        Args:
            model: Identificador del modelo de lenguaje.
            context: Nota de sistema solo para este turno; no se guarda en el historial.
            extra_messages: Mensajes solo para esta petición, como una foto. Al no guardarse,
                la imagen no se reenvía ni se paga en los turnos siguientes.

        Returns:
            La petición con el prompt de sistema y los mensajes recientes.
        """
        messages = [self.system_prompt, *self.messages]

        # La nota va justo antes del último mensaje, para que sea lo más reciente que lea.
        if context:
            messages.insert(-1, ChatMessage(role="system", content=context))

        messages.extend(extra_messages or [])

        return ChatRequest(model=model, messages=messages)

    def _add(self, role: MessageRole, text: str) -> None:
        """Guarda un mensaje y recorta el contexto a lo más reciente.

        Args:
            role: Quién lo escribió.
            text: Texto del mensaje.
        """
        self.messages.append(ChatMessage(role=role, content=text))
        del self.messages[:-MAX_CONTEXT_MESSAGES]
        if self.store:
            self.store.add_message(role, text)

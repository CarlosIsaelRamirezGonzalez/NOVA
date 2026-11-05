"""Cliente de Claude: convierte las peticiones de Nova al formato de la API de Anthropic."""

from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic
from pydantic import ValidationError

from services.context.usage_service import UsageService
from services.schemas import (
    ChatMessage,
    ChatRequest,
    ClaudeUsage,
    ImagePart,
    SearchArguments,
    TextPart,
)

MAX_OUTPUT_TOKENS = 16000
MAX_QUERY_CHARS = 200
SEARCH_TOOL_NAME = "web_search"
FORGET_TOOL_NAME = "forget_memory"
CAMERA_TOOL_NAME = "look_through_camera"
# En una conversación en vivo importa empezar a hablar pronto: razonar costaba varios segundos.
NO_THINKING = {"type": "disabled"}
EFFORT = "low"
# Si Claude no responde, Nova lo dice en vez de quedarse callada.
REFUSAL_REPLY = "No puedo seguir con eso, pero dime en qué más te ayudo."
CONTINUATION_NOTE = "(La conversación continúa desde antes.)"


def _note(text: str) -> str:
    """Marca un texto como nota de la aplicación, para distinguirlo de lo que dice Carlos.

    Args:
        text: Contenido de la nota.

    Returns:
        El texto entre etiquetas.
    """
    safe_text = text.replace("</system_note>", "")
    return f"<system_note>\n{safe_text}\n</system_note>"


def _content_block(part: TextPart | ImagePart) -> object:
    """Convierte una parte de un mensaje al formato de la API.

    Args:
        part: Texto o imagen.

    Returns:
        El bloque de contenido; la librería exige un mapping, solo en este punto.
    """
    if isinstance(part, TextPart):
        return {"type": "text", "text": part.text}

    # Las fotos llegan como data URL: `data:image/jpeg;base64,...`.
    header, _, data = part.image_url.url.partition(",")
    media_type = header.removeprefix("data:").removesuffix(";base64")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": data},
    }


def _api_messages(messages: list[ChatMessage]) -> list[object]:
    """Convierte el historial al formato de la API.

    Las notas de sistema pueden ir en cualquier parte del historial de Nova, pero la API solo las
    admite en ciertas posiciones. Por eso se envían como mensajes de usuario marcados.

    Args:
        messages: Mensajes de la conversación, sin el prompt de sistema.

    Returns:
        Los mensajes para la API.
    """
    converted: list[object] = []
    for message in messages:
        if isinstance(message.content, list):
            content: object = [_content_block(part) for part in message.content]
        elif message.role == "system":
            content = _note(message.content)
        elif message.content.strip():
            content = message.content.rstrip()
        else:
            continue
        role = "assistant" if message.role == "assistant" else "user"

        # La conversación debe empezar con un mensaje de usuario, aunque el recorte deje otra cosa.
        if not converted and role == "assistant":
            converted.append({"role": "user", "content": CONTINUATION_NOTE})
        converted.append({"role": role, "content": content})
    return converted


def _api_params(request: ChatRequest) -> object:
    """Construye los parámetros de una llamada a la API.

    Args:
        request: Petición de Nova; su primer mensaje es el prompt de sistema.

    Returns:
        Los parámetros; la librería exige un mapping, solo en este punto.
    """
    system_prompt, *messages = request.messages
    params = {
        "model": request.model,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "thinking": NO_THINKING,
        "output_config": {"effort": EFFORT},
        # El prompt no cambia entre turnos: en caché cuesta mucho menos.
        "system": [
            {
                "type": "text",
                "text": system_prompt.content,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": _api_messages(messages),
    }
    if request.output_schema is not None:
        params["output_config"]["format"] = {
            "type": "json_schema",
            "schema": request.output_schema,
        }
    if request.tools:
        params["tools"] = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
                "eager_input_streaming": True,
            }
            for tool in request.tools
        ]
    return params


def claude_usage(usage: object) -> ClaudeUsage:
    """Convierte los tokens que reporta la API.

    Args:
        usage: Objeto `usage` de una respuesta de Claude.

    Returns:
        Los tokens, con cero en lo que la API no haya reportado.
    """
    tools = getattr(usage, "server_tool_use", None)
    return ClaudeUsage(
        input_tokens=usage.input_tokens or 0,
        cache_write_tokens=usage.cache_creation_input_tokens or 0,
        cache_read_tokens=usage.cache_read_input_tokens or 0,
        output_tokens=usage.output_tokens or 0,
        searches=getattr(tools, "web_search_requests", 0) or 0,
    )


class LLMService:
    """Pide respuestas a Claude y las entrega token por token."""

    def __init__(self, client: AsyncAnthropic, usage: UsageService | None = None) -> None:
        """Guarda el cliente.

        Args:
            client: Cliente de la API de Anthropic.
            usage: Registro de gastos; sin él, no se lleva la cuenta.
        """
        self.client = client
        self.usage = usage

    async def stream_response(self, request: ChatRequest) -> AsyncIterator[str]:
        """Entrega la respuesta de Claude mientras se genera.

        Una herramienta pedida por el modelo se entrega al final como su etiqueta, por ejemplo
        `[[search: ...]]`, para que siga el mismo camino que las demás etiquetas.

        Args:
            request: Petición con el historial de la conversación.

        Yields:
            Cada fragmento de texto no vacío, en orden.
        """
        tool_name = ""
        tool_arguments = ""
        async with self.client.messages.stream(**_api_params(request)) as stream:
            # Se registra aunque Carlos la interrumpa: lo ya generado también se cobra.
            try:
                async for event in stream:
                    if event.type == "content_block_start" and event.content_block.type == "tool_use":
                        tool_name = event.content_block.name
                    if event.type != "content_block_delta":
                        continue
                    if event.delta.type == "text_delta" and event.delta.text:
                        yield event.delta.text
                    elif event.delta.type == "input_json_delta":
                        tool_arguments += event.delta.partial_json
                final = await stream.get_final_message()
            finally:
                if self.usage and stream.current_message_snapshot:
                    usage = claude_usage(stream.current_message_snapshot.usage)
                    self.usage.record_claude(request.purpose, usage)

        if final.stop_reason == "refusal":
            print(f"[LLM] refusal: {final.stop_details}", flush=True)
            yield REFUSAL_REPLY
        elif tool_name == FORGET_TOOL_NAME:
            yield "[[forget]]"
        elif tool_name == CAMERA_TOOL_NAME:
            yield "[[photo]]"
        elif tool_name == SEARCH_TOOL_NAME:
            yield self._search_tag(tool_arguments)

    async def complete(self, request: ChatRequest) -> str:
        """Pide una respuesta completa, sin stream.

        Args:
            request: Petición para la API.

        Returns:
            El texto de la respuesta.

        Raises:
            RuntimeError: Si Claude no devolvió texto.
        """
        response = await self.client.messages.create(**_api_params(request))
        if self.usage:
            self.usage.record_claude(request.purpose, claude_usage(response.usage))
        text = "".join(block.text for block in response.content if block.type == "text")
        if not text:
            raise RuntimeError(f"Claude returned no text: {response.stop_reason}")
        return text

    @staticmethod
    def _search_tag(arguments: str) -> str:
        """Convierte los argumentos de la herramienta en una etiqueta de búsqueda.

        Args:
            arguments: Argumentos en JSON.

        Returns:
            La etiqueta, o una cadena vacía si los argumentos no son válidos.
        """
        try:
            query = SearchArguments.model_validate_json(arguments).query
        except ValidationError:
            return ""

        # Los corchetes romperían la etiqueta, y Nova acabaría leyéndola en voz alta.
        clean_query = query.replace("[", " ").replace("]", " ").strip()[:MAX_QUERY_CHARS]
        return f"[[search: {clean_query}]]" if clean_query else ""

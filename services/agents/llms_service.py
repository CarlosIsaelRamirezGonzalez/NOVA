"""Cliente de la API de chat de Grok."""

from collections.abc import AsyncIterator

from aiohttp import ClientSession
from pydantic import ValidationError

from services.schemas import AuthHeaders, ChatCompletion, ChatRequest, ChatStreamChunk

SSE_DATA_PREFIX = "data: "
SSE_DONE = "data: [DONE]"


class LLMService:
    """Pide respuestas a Grok y las entrega token por token."""

    def __init__(self, api_key: str, api_url: str) -> None:
        """Guarda los datos de conexión.

        Args:
            api_key: Clave secreta de xAI.
            api_url: Dirección de la API de chat.
        """
        self.headers = AuthHeaders.from_api_key(api_key)
        self.api_url = api_url

    async def stream_response(
        self, session: ClientSession, request: ChatRequest
    ) -> AsyncIterator[str]:
        """Entrega la respuesta de Grok mientras se genera.

        Args:
            session: Sesión HTTP compartida.
            request: Petición con el historial de la conversación.

        Yields:
            Cada fragmento de texto no vacío, en orden.

        Raises:
            RuntimeError: Si la API responde con un error.
        """
        # aiohttp exige un mapping en las cabeceras: se convierte solo en este punto.
        async with session.post(
            self.api_url,
            data=request.model_dump_json(exclude_none=True, by_alias=True),
            headers=self.headers.model_dump(by_alias=True),
        ) as response:
            if response.status != 200:
                raise RuntimeError(f"LLM error {response.status}: {await response.text()}")

            # La API responde con Server-Sent Events: una línea "data: ..." por evento.
            async for raw_line in response.content:
                line = raw_line.decode("utf-8").strip()
                if not line.startswith(SSE_DATA_PREFIX) or line == SSE_DONE:
                    continue

                # Un evento que no se entiende se omite sin cortar el resto de la respuesta.
                try:
                    chunk = ChatStreamChunk.model_validate_json(line[len(SSE_DATA_PREFIX) :])
                except ValidationError:
                    continue
                if chunk.text:
                    yield chunk.text

    async def complete(self, session: ClientSession, request: ChatRequest) -> str:
        """Pide una respuesta completa, sin stream.

        Args:
            session: Sesión HTTP compartida.
            request: Petición para la API de chat.

        Returns:
            El texto de la respuesta.

        Raises:
            RuntimeError: Si la API responde con un error.
        """
        # aiohttp exige un mapping en las cabeceras: se convierte solo en este punto.
        async with session.post(
            self.api_url,
            data=request.model_dump_json(exclude_none=True, by_alias=True),
            headers=self.headers.model_dump(by_alias=True),
        ) as response:
            body = await response.text()
            if response.status != 200:
                raise RuntimeError(f"LLM error {response.status}: {body}")
        return ChatCompletion.model_validate_json(body).choices[0].message.content

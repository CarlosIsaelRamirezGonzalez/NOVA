"""Adapta el WebSocket de FastAPI a lo que espera `NovaServer`, que nació con aiohttp."""

from collections.abc import AsyncIterator, Awaitable

from fastapi import WebSocket, WebSocketDisconnect


class StarletteSocket:
    """WebSocket de FastAPI con la misma forma que el de aiohttp."""

    def __init__(self, websocket: WebSocket) -> None:
        """Guarda la conexión.

        Args:
            websocket: Conexión ya aceptada.
        """
        self.websocket = websocket
        self.closed = False

    async def send_str(self, data: str) -> None:
        """Envía un evento en JSON.

        Args:
            data: Evento serializado.
        """
        await self._send(self.websocket.send_text(data))

    async def send_bytes(self, data: bytes) -> None:
        """Envía un fragmento de audio.

        Args:
            data: Audio en MP3.
        """
        await self._send(self.websocket.send_bytes(data))

    async def texts(self) -> AsyncIterator[str]:
        """Entrega el texto de cada mensaje hasta que la pantalla se desconecta.

        Yields:
            El contenido de cada mensaje.
        """
        try:
            async for text in self.websocket.iter_text():
                yield text
        finally:
            self.closed = True

    async def _send(self, sending: Awaitable[None]) -> None:
        """Espera un envío y lo traduce al error que espera `NovaServer`.

        Args:
            sending: Envío ya iniciado.

        Raises:
            ConnectionError: Si la pantalla ya se desconectó, como en aiohttp.
        """
        try:
            await sending
        except (WebSocketDisconnect, RuntimeError) as error:
            self.closed = True
            raise ConnectionError("socket closed") from error

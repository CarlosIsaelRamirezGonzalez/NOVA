"""Creación de los clientes HTTP que comparten los servicios."""

import ssl

import certifi
from aiohttp import ClientSession, TCPConnector
from anthropic import AsyncAnthropic

CLAUDE_TIMEOUT_SECONDS = 60.0


def create_http_session() -> ClientSession:
    """Crea una sesión HTTP que verifica los certificados con `certifi`.

    El Python de python.org en macOS no trae certificados raíz propios, y sin
    esto las conexiones HTTPS fallan.

    Returns:
        Una sesión HTTP lista para usarse.
    """
    tls_context = ssl.create_default_context(cafile=certifi.where())
    return ClientSession(connector=TCPConnector(ssl=tls_context))


def create_anthropic_client(api_key: str) -> AsyncAnthropic:
    """Crea el cliente de la API de Anthropic.

    Args:
        api_key: Clave secreta de Anthropic.

    Returns:
        Un cliente listo para usarse; hay que cerrarlo al apagar.
    """
    return AsyncAnthropic(api_key=api_key, timeout=CLAUDE_TIMEOUT_SECONDS)

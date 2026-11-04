"""Creación de la sesión HTTP que comparten los servicios."""

import ssl

import certifi
from aiohttp import ClientSession, TCPConnector


def create_http_session() -> ClientSession:
    """Crea una sesión HTTP que verifica los certificados con `certifi`.

    El Python de python.org en macOS no trae certificados raíz propios, y sin
    esto las conexiones HTTPS fallan.

    Returns:
        Una sesión HTTP lista para usarse.
    """
    tls_context = ssl.create_default_context(cafile=certifi.where())
    return ClientSession(connector=TCPConnector(ssl=tls_context))

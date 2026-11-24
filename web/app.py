"""Versión web de Nova: la misma Nova que en la Mac, detrás de una contraseña.

Vercel carga `app` desde aquí (ver `pyproject.toml`). La página usa una cookie; la extensión de
Chrome, que es otro sitio, usa un token con la misma firma. Este archivo solo tiene las rutas; el
resto vive aparte:
    settings.py        Qué piezas se encienden y de dónde salen los secretos.
    session.py         Contraseña, cookie firmada y origen del WebSocket.
    socket_adapter.py  El WebSocket de FastAPI con la forma que espera `NovaServer`.

Uso local, para probarla antes de desplegar:
    uvicorn web.app:app --port 8788
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError

from server import NovaServer
from services.schemas import LoginRequest, SessionStatus, SocketAuth
from web.session import SESSION_COOKIE, SESSION_SECONDS, SessionGuard, origin_matches_host
from web.settings import FRONTEND_DIST, WEB_FEATURES, load_config, load_secrets
from web.socket_adapter import StarletteSocket

# Frena a quien intente adivinar la contraseña, sin delatar si estuvo cerca.
FAILED_LOGIN_DELAY_SECONDS = 1.5
# Código de cierre del WebSocket cuando falta la sesión; la interfaz vuelve a pedir la contraseña.
UNAUTHORIZED_CLOSE_CODE = 4401
EXTENSION_ORIGIN_PREFIX = "chrome-extension://"
# La extensión manda su token como primer mensaje; si no llega pronto, se cierra.
AUTH_TIMEOUT_SECONDS = 10
BEARER_PREFIX = "Bearer "


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Arranca Nova con la instancia y la apaga con ella.

    Args:
        application: Aplicación de FastAPI.

    Yields:
        El control mientras la instancia atiende peticiones.
    """
    config = load_config()
    application.state.guard = SessionGuard(load_secrets(config))
    application.state.nova = NovaServer(config, WEB_FEATURES)
    await application.state.nova.start()
    yield
    await application.state.nova.stop()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def is_https(request: Request) -> bool:
    """Indica si el navegador llegó por HTTPS, también detrás del proxy de Vercel.

    Args:
        request: Petición del navegador.

    Returns:
        Si la conexión es segura.
    """
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def request_session(request: Request) -> str | None:
    """Saca la sesión de la cookie de la página o del token de la extensión.

    Args:
        request: Petición del navegador.

    Returns:
        El valor firmado, si vino alguno.
    """
    authorization = request.headers.get("authorization", "")
    if authorization.startswith(BEARER_PREFIX):
        return authorization.removeprefix(BEARER_PREFIX)
    return request.cookies.get(SESSION_COOKIE)


async def extension_is_authenticated(websocket: WebSocket, guard: SessionGuard) -> bool:
    """Lee el token que la extensión manda como primer mensaje y lo comprueba.

    Args:
        websocket: Conexión ya aceptada.
        guard: Comprueba la firma y el vencimiento.

    Returns:
        Si el token es auténtico y sigue vigente.
    """
    try:
        first = await asyncio.wait_for(websocket.receive_text(), AUTH_TIMEOUT_SECONDS)
        return guard.is_valid(SocketAuth.model_validate_json(first).token)
    except (TimeoutError, ValidationError, WebSocketDisconnect, KeyError):
        return False


@app.get("/api/session")
async def session(request: Request) -> SessionStatus:
    """Le dice a la interfaz si ya puede conectarse o debe pedir la contraseña.

    Args:
        request: Petición del navegador.

    Returns:
        El estado de la sesión.
    """
    guard: SessionGuard = request.app.state.guard
    return SessionStatus(required=True, authenticated=guard.is_valid(request_session(request)))


@app.post("/api/login")
async def login(body: LoginRequest, request: Request, response: Response) -> SessionStatus:
    """Abre una sesión si la contraseña es correcta.

    Args:
        body: Contraseña escrita.
        request: Petición del navegador.
        response: Respuesta, donde se pone la cookie.

    Returns:
        El estado de la sesión.
    """
    guard: SessionGuard = request.app.state.guard
    if not guard.password_matches(body.password):
        await asyncio.sleep(FAILED_LOGIN_DELAY_SECONDS)
        response.status_code = status.HTTP_401_UNAUTHORIZED
        return SessionStatus(required=True, authenticated=False)

    # HttpOnly: ningún script de la página puede leerla. Strict: otra web no puede usarla.
    session_value = guard.create()
    response.set_cookie(
        SESSION_COOKIE,
        session_value,
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=is_https(request),
        samesite="strict",
        path="/",
    )
    # La extensión no recibe la cookie: guarda el mismo valor firmado como token.
    token = session_value if body.want_token else None
    return SessionStatus(required=True, authenticated=True, token=token)


@app.post("/api/logout")
async def logout(response: Response) -> SessionStatus:
    """Cierra la sesión de este navegador.

    Args:
        response: Respuesta, donde se borra la cookie.

    Returns:
        El estado de la sesión.
    """
    response.delete_cookie(SESSION_COOKIE, path="/")
    return SessionStatus(required=True, authenticated=False)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Atiende una pantalla con el mismo protocolo que la Mac.

    Args:
        websocket: Conexión que pide abrirse.
    """
    # Sin esto, cualquier otra web abierta en el navegador podría usar la cookie para hablar con Nova.
    origin = websocket.headers.get("origin") or ""
    hosts = [websocket.headers.get("host"), websocket.headers.get("x-forwarded-host")]
    from_page = origin_matches_host(origin, hosts)
    from_extension = origin.startswith(EXTENSION_ORIGIN_PREFIX)
    if not from_page and not from_extension:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Se acepta para poder cerrar con un código propio: el navegador no ve el motivo de un rechazo.
    await websocket.accept()
    guard: SessionGuard = websocket.app.state.guard
    # La extensión nunca usa la cookie: solo el token que guardó al entrar.
    authenticated = (
        guard.is_valid(websocket.cookies.get(SESSION_COOKIE))
        if from_page
        else await extension_is_authenticated(websocket, guard)
    )
    if not authenticated:
        await websocket.close(code=UNAUTHORIZED_CLOSE_CODE)
        return

    nova: NovaServer = websocket.app.state.nova
    socket = StarletteSocket(websocket)
    try:
        await nova.serve(socket, socket.texts())
    finally:
        # Después de cerrar, Vercel puede congelar la instancia: lo pendiente se sube ya.
        await nova.flush()


# La interfaz compilada; las rutas de arriba tienen prioridad sobre estos archivos.
app.frontend("/", directory=FRONTEND_DIST, check_dir=False)

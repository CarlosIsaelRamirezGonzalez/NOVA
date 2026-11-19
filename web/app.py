"""Versión web de Nova: la misma Nova que en la Mac, detrás de una contraseña.

Vercel carga `app` desde aquí (ver `pyproject.toml`). Usa el mismo `NovaServer` y el mismo
WebSocket que la Mac, pero sin las piezas que solo existen ahí: el micrófono del servidor, escribir
en otras apps, las caras y la búsqueda por significado. La voz se dicta con el navegador.

Las claves viven solo en las variables de entorno de Vercel. El navegador recibe una cookie
firmada que no contiene ningún secreto.

Uso local, para probarla antes de desplegar:
    uvicorn web.app:app --port 8788
"""

import asyncio
import hashlib
import hmac
import tempfile
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, SecretStr

from config import Config
from server import NovaServer
from services.schemas import LoginRequest, ServerFeatures, SessionStatus

# En Vercel solo se puede escribir en la carpeta temporal; ahí vive la copia de la memoria.
RUNTIME_FOLDER = Path(tempfile.gettempdir()) / "nova"
FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
WEB_FEATURES = ServerFeatures(
    microphone=False,
    desktop=False,
    faces=False,
    semantic_search=False,
    vault=False,
    serverless=True,
)
SESSION_COOKIE = "nova_session"
SESSION_SECONDS = 30 * 24 * 3600
MIN_PASSWORD_LENGTH = 12
MIN_SECRET_LENGTH = 32
# Frena a quien intente adivinar la contraseña, sin delatar si estuvo cerca.
FAILED_LOGIN_DELAY_SECONDS = 1.5
# Código de cierre del WebSocket cuando falta la sesión; la interfaz vuelve a pedir la contraseña.
UNAUTHORIZED_CLOSE_CODE = 4401


class WebSecrets(BaseModel):
    """Contraseña y clave de firma de la versión web.

    Attributes:
        password: Contraseña que se pide en la pantalla de acceso.
        session_secret: Clave para firmar la cookie de sesión.
    """

    password: SecretStr
    session_secret: SecretStr


def load_config() -> Config:
    """Lee la configuración y acomoda la memoria en la carpeta temporal.

    Returns:
        La configuración de la versión web.
    """
    base = Config()
    if base.turso_database_url and base.turso_auth_token:
        return Config(
            synced_memory_path=RUNTIME_FOLDER / "nova_synced.db",
            vault_path=RUNTIME_FOLDER / "obsidian",
        )
    # Sin Turso, la memoria se borra cada vez que Vercel recicla la instancia.
    print("[Web] TURSO_DATABASE_URL is missing: memory will not survive restarts", flush=True)
    return Config(memory_path=RUNTIME_FOLDER / "nova.db", vault_path=RUNTIME_FOLDER / "obsidian")


def load_secrets(config: Config) -> WebSecrets:
    """Valida que la contraseña y la clave de firma existan y sean largas.

    Args:
        config: Configuración leída del entorno.

    Returns:
        Los secretos de la versión web.

    Raises:
        RuntimeError: Si falta alguno o es demasiado corto. El mensaje nunca incluye su valor.
    """
    if len(config.nova_web_password) < MIN_PASSWORD_LENGTH:
        raise RuntimeError(f"NOVA_WEB_PASSWORD must have at least {MIN_PASSWORD_LENGTH} characters")
    if len(config.nova_session_secret) < MIN_SECRET_LENGTH:
        raise RuntimeError(f"NOVA_SESSION_SECRET must have at least {MIN_SECRET_LENGTH} characters")
    return WebSecrets(
        password=SecretStr(config.nova_web_password),
        session_secret=SecretStr(config.nova_session_secret),
    )


def _signing_key(secrets: WebSecrets) -> bytes:
    """Deriva la clave que firma las sesiones.

    Incluye la contraseña: al cambiarla, todas las sesiones abiertas dejan de servir.

    Args:
        secrets: Secretos de la versión web.

    Returns:
        La clave de firma.
    """
    material = f"{secrets.session_secret.get_secret_value()}\0{secrets.password.get_secret_value()}"
    return hashlib.sha256(material.encode()).digest()


def create_session(secrets: WebSecrets, now: float | None = None) -> str:
    """Crea el valor de la cookie: su vencimiento y una firma, sin ningún secreto.

    Args:
        secrets: Secretos de la versión web.
        now: Momento actual en segundos; se puede fijar en las pruebas.

    Returns:
        El valor de la cookie.
    """
    expires = int((now if now is not None else time.time()) + SESSION_SECONDS)
    signature = hmac.new(_signing_key(secrets), str(expires).encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{signature}"


def session_is_valid(secrets: WebSecrets, value: str | None, now: float | None = None) -> bool:
    """Comprueba la firma y el vencimiento de una cookie.

    Args:
        secrets: Secretos de la versión web.
        value: Valor de la cookie, si el navegador la mandó.
        now: Momento actual en segundos; se puede fijar en las pruebas.

    Returns:
        Si la sesión es auténtica y sigue vigente.
    """
    if not value or "." not in value:
        return False
    expires, signature = value.split(".", 1)
    if not expires.isdigit():
        return False
    expected = hmac.new(_signing_key(secrets), expires.encode(), hashlib.sha256).hexdigest()
    current = now if now is not None else time.time()
    return hmac.compare_digest(signature, expected) and int(expires) > current


def password_matches(secrets: WebSecrets, attempt: str) -> bool:
    """Compara la contraseña en tiempo constante.

    Args:
        secrets: Secretos de la versión web.
        attempt: Lo que escribió el usuario.

    Returns:
        Si coincide.
    """
    expected = secrets.password.get_secret_value().encode()
    return hmac.compare_digest(attempt.encode(), expected)


def origin_matches_host(origin: str | None, hosts: list[str | None]) -> bool:
    """Acepta el WebSocket solo si lo abre la propia página de Nova.

    Args:
        origin: Encabezado `Origin` del navegador.
        hosts: Dominios con los que llegó la petición (`Host` y el reenviado por Vercel).

    Returns:
        Si el origen es este mismo sitio.
    """
    if not origin:
        return False
    origin_host = urlsplit(origin).netloc
    return any(host and origin_host == host for host in hosts)


class StarletteSocket:
    """Adapta el WebSocket de FastAPI a lo que espera `NovaServer`."""

    def __init__(self, websocket: WebSocket) -> None:
        """Guarda la conexión.

        Args:
            websocket: Conexión ya aceptada.
        """
        self.websocket = websocket
        self.is_closed = False

    @property
    def closed(self) -> bool:
        """Si la conexión ya se cerró.

        Returns:
            `True` después de una desconexión o de un envío fallido.
        """
        return self.is_closed

    async def send_str(self, data: str) -> None:
        """Envía un evento en JSON.

        Args:
            data: Evento serializado.

        Raises:
            ConnectionError: Si la pantalla ya se desconectó, como en aiohttp.
        """
        try:
            await self.websocket.send_text(data)
        except (WebSocketDisconnect, RuntimeError) as error:
            self.is_closed = True
            raise ConnectionError("socket closed") from error

    async def send_bytes(self, data: bytes) -> None:
        """Envía un fragmento de audio.

        Args:
            data: Audio en MP3.

        Raises:
            ConnectionError: Si la pantalla ya se desconectó.
        """
        try:
            await self.websocket.send_bytes(data)
        except (WebSocketDisconnect, RuntimeError) as error:
            self.is_closed = True
            raise ConnectionError("socket closed") from error

    async def texts(self) -> AsyncIterator[str]:
        """Entrega el texto de cada mensaje hasta que la pantalla se desconecta.

        Yields:
            El contenido de cada mensaje.
        """
        try:
            async for text in self.websocket.iter_text():
                yield text
        finally:
            self.is_closed = True


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Arranca Nova con la instancia y la apaga con ella.

    Args:
        application: Aplicación de FastAPI.

    Yields:
        El control mientras la instancia atiende peticiones.
    """
    config = load_config()
    application.state.secrets = load_secrets(config)
    application.state.nova = NovaServer(config, WEB_FEATURES)
    await application.state.nova.start()
    yield
    await application.state.nova.stop()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/api/session")
async def session(request: Request) -> SessionStatus:
    """Le dice a la interfaz si ya puede conectarse o debe pedir la contraseña.

    Args:
        request: Petición del navegador.

    Returns:
        El estado de la sesión.
    """
    valid = session_is_valid(request.app.state.secrets, request.cookies.get(SESSION_COOKIE))
    return SessionStatus(required=True, authenticated=valid)


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
    secrets: WebSecrets = request.app.state.secrets
    if not password_matches(secrets, body.password):
        await asyncio.sleep(FAILED_LOGIN_DELAY_SECONDS)
        response.status_code = status.HTTP_401_UNAUTHORIZED
        return SessionStatus(required=True, authenticated=False)

    # HttpOnly: ningún script de la página puede leerla. Strict: otra web no puede usarla.
    response.set_cookie(
        SESSION_COOKIE,
        create_session(secrets),
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https",
        samesite="strict",
        path="/",
    )
    return SessionStatus(required=True, authenticated=True)


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
    # Sin esto, cualquier otra web abierta en el navegador podría hablar con Nova.
    hosts = [websocket.headers.get("host"), websocket.headers.get("x-forwarded-host")]
    if not origin_matches_host(websocket.headers.get("origin"), hosts):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Se acepta para poder cerrar con un código propio: el navegador no ve el motivo de un rechazo.
    await websocket.accept()
    if not session_is_valid(websocket.app.state.secrets, websocket.cookies.get(SESSION_COOKIE)):
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

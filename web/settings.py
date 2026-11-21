"""Configuración de la versión web: qué piezas de Nova se encienden y de dónde salen los secretos.

Las claves viven solo en las variables de entorno de Vercel; aquí se leen y se validan.
"""

import tempfile
from pathlib import Path

from pydantic import BaseModel, SecretStr

from config import Config
from services.schemas import ServerFeatures

# En Vercel solo se puede escribir en la carpeta temporal; ahí vive la copia de la memoria.
RUNTIME_FOLDER = Path(tempfile.gettempdir()) / "nova"
FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
MIN_PASSWORD_LENGTH = 12
MIN_SECRET_LENGTH = 32

# En la web no hay micrófono del servidor, escritorio, caras ni búsqueda por significado.
WEB_FEATURES = ServerFeatures(
    microphone=False,
    desktop=False,
    faces=False,
    semantic_search=False,
    vault=False,
    serverless=True,
)


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

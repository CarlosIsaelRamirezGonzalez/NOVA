"""Configuración de Nova, leída y validada desde el archivo `.env`."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from services.schemas import SyncSettings
from services.voice.tts_service import DEFAULT_VOICE_ID


DEFAULT_MEMORY_PATH = Path(__file__).with_name("data") / "nova.db"


WHISPER_FOLDER = Path(__file__).with_name("data") / "models" / "whisper"
# De mejor a más ligero: se usa el primero que esté descargado.
WHISPER_MODELS = ("ggml-small.bin", "ggml-base.bin")


def _whisper_model() -> Path:
    """Elige el modelo de Whisper más fuerte que haya en el equipo.

    Returns:
        La ruta del modelo; si no hay ninguno, la del más ligero, para que el error lo diga.
    """
    for name in WHISPER_MODELS:
        if (WHISPER_FOLDER / name).exists():
            return WHISPER_FOLDER / name
    return WHISPER_FOLDER / WHISPER_MODELS[-1]


class Config(BaseSettings):
    """Variables de entorno que necesita Nova.

    Attributes:
        anthropic_api_key: Clave secreta de la API de Anthropic.
        elevenlabs_api_key: Clave secreta de la API de ElevenLabs.
        elevenlabs_voice_id: Voz de Nova en ElevenLabs.
        turso_database_url: Base en la nube; sin ella, la memoria se queda en este equipo.
        turso_auth_token: Clave secreta de esa base.
        memory_path: Memoria que se queda solo en este equipo.
        synced_memory_path: Copia local de la memoria sincronizada con la nube.
        vector_path: Carpeta del índice de Qdrant; se puede reconstruir desde la memoria.
        models_path: Carpeta del modelo local de embeddings.
        wake_model_path: Modelo de Vosk que detecta "Oye Nova".
        whisper_model_path: Modelo de Whisper que transcribe las peticiones.
        vault_path: Bóveda de Obsidian que se genera desde la memoria.
        nova_web_password: Contraseña de la versión web; en la Mac no se usa.
        nova_session_secret: Clave con la que la versión web firma la sesión del navegador.
        gmail_address: Cuenta de Gmail desde la que Nova manda los reportes.
        gmail_app_password: Contraseña de aplicación de esa cuenta; no es la contraseña normal.
        nova_email_to: A quién llegan los reportes; si falta, a la misma cuenta. Nunca lo decide
            el modelo.
        nova_ambient_camera: Si Nova mira por su cuenta al oír otra voz, un ruido raro o de rutina.
        nova_glance_minutes: Cada cuánto da un vistazo de rutina; 0 lo apaga.
    """

    # `hide_input_in_errors` evita que un error de validación imprima las claves.
    # `extra="ignore"` tolera otras variables del `.env` que Nova no usa todavía.
    model_config = SettingsConfigDict(
        env_file=Path(__file__).with_name(".env"),
        extra="ignore",
        hide_input_in_errors=True,
    )

    anthropic_api_key: str = Field(min_length=1)
    elevenlabs_api_key: str = Field(min_length=1)
    elevenlabs_voice_id: str = DEFAULT_VOICE_ID
    turso_database_url: str = ""
    turso_auth_token: str = ""
    memory_path: Path = DEFAULT_MEMORY_PATH
    synced_memory_path: Path = Path(__file__).with_name("data") / "nova_synced.db"
    vector_path: Path = Path(__file__).with_name("data") / "qdrant"
    models_path: Path = Path(__file__).with_name("data") / "models"
    wake_model_path: Path = Path(__file__).with_name("data") / "models" / "vosk-model-small-es-0.42"
    whisper_model_path: Path = Field(default_factory=lambda: _whisper_model())
    vault_path: Path = Path(__file__).with_name("data") / "obsidian"
    nova_web_password: str = ""
    nova_session_secret: str = ""
    gmail_address: str = ""
    gmail_app_password: str = ""
    nova_email_to: str = ""
    nova_ambient_camera: bool = True
    nova_glance_minutes: int = Field(default=20, ge=0)

    @property
    def sync_settings(self) -> SyncSettings | None:
        """Devuelve la base en la nube, si hay que usarla.

        Elegir otra memoria con `MEMORY_PATH` la desactiva: así, una prueba con datos temporales
        nunca toca tus datos reales en la nube.

        Returns:
            Los datos de conexión, o `None` si la memoria se queda en este equipo.
        """
        configured = self.turso_database_url and self.turso_auth_token
        if not configured or self.memory_path != DEFAULT_MEMORY_PATH:
            return None
        return SyncSettings(database_url=self.turso_database_url, auth_token=self.turso_auth_token)

    @property
    def active_memory_path(self) -> Path:
        """Devuelve el archivo de memoria que corresponde usar.

        Returns:
            La copia sincronizada si hay nube; si no, la memoria local.
        """
        return self.synced_memory_path if self.sync_settings else self.memory_path

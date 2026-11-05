"""Configuración de Nova, leída y validada desde el archivo `.env`."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from services.schemas import SyncSettings
from services.voice.tts_service import DEFAULT_VOICE_ID


DEFAULT_MEMORY_PATH = Path(__file__).with_name("data") / "nova.db"


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
    whisper_model_path: Path = Path(__file__).with_name("data") / "models" / "whisper" / "ggml-base.bin"
    vault_path: Path = Path(__file__).with_name("data") / "obsidian"

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

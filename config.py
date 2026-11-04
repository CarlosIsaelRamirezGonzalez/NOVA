"""Configuración de Nova, leída y validada desde el archivo `.env`."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Variables de entorno que necesita Nova.

    Attributes:
        xai_api_key: Clave secreta de las APIs de xAI.
        chat_api_url: Dirección de la API de chat.
        tts_api_url: Dirección de la API de voz.
        memory_path: Archivo de la memoria persistente.
        vector_path: Carpeta del índice de Qdrant; se puede reconstruir desde la memoria.
        models_path: Carpeta del modelo local de embeddings.
        vault_path: Bóveda de Obsidian que se genera desde la memoria.
    """

    # `hide_input_in_errors` evita que un error de validación imprima las claves.
    # `extra="ignore"` tolera otras variables del `.env` que Nova no usa todavía.
    model_config = SettingsConfigDict(
        env_file=Path(__file__).with_name(".env"),
        extra="ignore",
        hide_input_in_errors=True,
    )

    xai_api_key: str = Field(min_length=1)
    chat_api_url: str = Field(min_length=1)
    tts_api_url: str = Field(min_length=1)
    memory_path: Path = Path(__file__).with_name("data") / "nova.db"
    vector_path: Path = Path(__file__).with_name("data") / "qdrant"
    models_path: Path = Path(__file__).with_name("data") / "models"
    vault_path: Path = Path(__file__).with_name("data") / "obsidian"

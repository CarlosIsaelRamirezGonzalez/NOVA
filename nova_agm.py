"""Versión de consola de Nova: se escribe por teclado y responde por los altavoces."""

import asyncio

from audio_manager import AudioManager
from config import Config
from nova.prompts.nova_prompts import NOVA_SYSTEM_PROMPT
from services.agents.agm import AgentManager
from services.agents.llms_service import LLMService
from services.context.conversation_service import ConversationService
from services.http_client import create_anthropic_client, create_http_session
from services.schemas import EmotionBlend, PhotoResult
from services.voice.tts_service import TTSService


async def print_token(token: str) -> None:
    """Muestra un fragmento de la respuesta en cuanto llega.

    Args:
        token: Texto recibido.
    """
    print(token, end="", flush=True)


async def ignore_emotion(_blend: EmotionBlend) -> None:
    """Descarta las emociones, porque la consola no tiene personaje.

    Args:
        _blend: Mezcla de emociones recibida.
    """


async def no_camera() -> PhotoResult:
    """Responde que no hay cámara, porque la consola no tiene acceso a ella.

    Returns:
        El resultado sin foto.
    """
    return PhotoResult(status="camera_off")


async def main() -> None:
    """Conversa con Nova hasta que se cierre la entrada o se pulse Ctrl+C."""
    # Prepara los servicios que componen un turno de conversación.
    config = Config()
    audio = AudioManager()
    agent = AgentManager(
        ConversationService(NOVA_SYSTEM_PROMPT),
        LLMService(create_anthropic_client(config.anthropic_api_key)),
        TTSService(config.elevenlabs_api_key, config.elevenlabs_voice_id),
    )

    async with create_http_session() as session:
        while True:
            # `input` bloquea, así que se ejecuta en otro hilo para no congelar el programa.
            try:
                text = (await asyncio.to_thread(input, "\nYou: ")).strip()
            except EOFError:
                return
            if not text:
                continue

            # Un fallo de red o de la API no debe terminar la conversación.
            print("NOVA: ", end="", flush=True)
            try:
                await agent.run_turn(
                    session, text, print_token, audio.play, ignore_emotion, no_camera
                )
            except Exception as error:
                print(f"\n[Error: {error}]")
            print()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

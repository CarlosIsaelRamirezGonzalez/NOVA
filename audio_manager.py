"""Reproducción local de audio para la versión de consola de Nova."""

import asyncio
import io

import pygame

POLL_SECONDS = 0.03


class AudioManager:
    """Reproduce fragmentos de audio en los altavoces, sin escribir a disco."""

    def __init__(self) -> None:
        """Inicializa el mezclador de audio de pygame."""
        pygame.mixer.init()

    async def play(self, audio: bytes) -> None:
        """Reproduce un fragmento y espera a que termine.

        Esperar aquí es lo que mantiene las frases en orden, una tras otra.

        Args:
            audio: Contenido del archivo de audio.
        """
        try:
            channel = pygame.mixer.Sound(io.BytesIO(audio)).play()
            while channel.get_busy():
                await asyncio.sleep(POLL_SECONDS)
        except pygame.error as error:
            # Un fragmento dañado no debe interrumpir el resto de la respuesta.
            print(f"[Playback error: {error}]")

import pygame
import asyncio


class AudioManager:
    def __init__(self, config):
        self.config = config

    async def audio_player(self, resultados, total_chunks, eventos):
        """Reproduce los fragmentos EN ORDEN, esperando a que cada índice esté listo
        aunque los TTS hayan terminado en otro orden. Reproduce en memoria (sin disco).
        """
        pygame.mixer.init()

        for i in range(total_chunks):
            await eventos[i].wait()
            audio_io = resultados.get(i)
            if audio_io is None:
                continue
            try:
                sonido = pygame.mixer.Sound(audio_io)
                canal = sonido.play()
                while canal.get_busy():
                    await asyncio.sleep(0.03)
            except Exception as e:
                print(f"\n[Error de reproducción chunk {i}: {e}]")


import asyncio


class AudioPlayerService:
    def __init__(self, audio_manager):
        self.audio_manager = audio_manager

    async def play_in_order(
        self, results: dict, total_chunks: int, events: list[asyncio.Event]
    ):
        """Espera que cada chunk esté listo y lo reproduce en orden."""
        for i in range(total_chunks):
            await events[i].wait()  # Espera a que el TTS termine
            if results.get(i):
                self.audio_manager.play_audio(results[i])  # Reproduce
            # Si es None, saltar o manejar error

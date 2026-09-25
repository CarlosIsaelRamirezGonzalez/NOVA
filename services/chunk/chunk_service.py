import re


class ChunkingService:
    def __init__(self, max_first_chunk_words: int = 6):
        self.delimiters = r"([,.!?]|\n|</whisper>|</soft>|</slow>|\[pause\]|\[laugh\]|\[sigh\]|\[long-pause\]|\[chuckle\]|\[giggle\]|\[cry\]|\[breath\]|\[inhale\]|\[exhale\]|\[tsk\]|\[tongue-click\]|\[lip-smack\])"
        self.max_first_chunk_words = max_first_chunk_words
        self.buffer = ""
        self.word_count = 0
        self.chunk_count = 0

    def add_token(self, token: str) -> list[str]:
        """Procesa un token y devuelve una lista de fragmentos listos para TTS."""
        self.buffer += token
        self.word_count += len(token.split())
        chunks = []

        # Regla 1: Delimiters
        if re.search(self.delimiters, self.buffer):
            chunks.append(self.buffer.strip())
            self._reset_buffer()

        # Regla 2: Primer fragmento temprano
        elif self.chunk_count == 0 and self.word_count >= self.max_first_chunk_words:
            chunks.append(self.buffer.strip())
            self._reset_buffer()

        return chunks

    def flush(self) -> str | None:
        """Devuelve el buffer restante al final del stream."""
        if self.buffer.strip():
            text = self.buffer.strip()
            self._reset_buffer()
            return text
        return None

    def _reset_buffer(self):
        self.buffer = ""
        self.word_count = 0
        self.chunk_count += 1

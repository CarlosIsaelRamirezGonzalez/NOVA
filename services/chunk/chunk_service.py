"""División de la respuesta del modelo en frases para la voz.

La entonación se genera por fragmento: cuanto más completo es, más natural suena. Por eso se
corta por oraciones y no en cada coma.
"""

import re

# Fin de oración: el signo debe ir seguido de un espacio, para no partir "3.14" a la mitad.
SENTENCE_END = re.compile(r"[.!?…]+[\"')\]]*\s")
OPENING_TAG = re.compile(r"<[a-z-]+>")
CLOSING_TAG = re.compile(r"</[a-z-]+>")


class ChunkingService:
    """Acumula tokens y los libera como frases listas para pronunciar."""

    def __init__(self, first_chunk_words: int = 6, max_chunk_words: int = 45) -> None:
        """Inicia el acumulador vacío.

        Args:
            first_chunk_words: Palabras tras las que la primera frase se puede cortar en una
                coma, para que Nova empiece a hablar antes.
            max_chunk_words: Palabras tras las que se corta en una coma aunque la oración siga,
                para que un párrafo sin puntos no retrase demasiado la voz.
        """
        self.first_chunk_words = first_chunk_words
        self.max_chunk_words = max_chunk_words
        self.buffer = ""
        self.chunk_count = 0

    def add_token(self, token: str) -> list[str]:
        """Procesa un token nuevo.

        Args:
            token: Fragmento de texto recibido del modelo.

        Returns:
            Las frases que quedaron completas; vacía si aún no hay ninguna.
        """
        self.buffer += token
        chunks: list[str] = []

        while (cut := self._find_cut()) is not None:
            chunks.append(self.buffer[:cut].strip())
            self.buffer = self.buffer[cut:]
            self.chunk_count += 1

        return [chunk for chunk in chunks if chunk]

    def flush(self) -> str | None:
        """Libera lo que quedó acumulado al terminar la respuesta.

        Returns:
            El texto restante, o `None` si no queda nada.
        """
        text = self.buffer.strip()
        self.buffer = ""
        if not text:
            return None
        self.chunk_count += 1
        return text

    def _find_cut(self) -> int | None:
        """Busca dónde cortar el texto acumulado.

        Returns:
            La posición del corte, o `None` si todavía hay que esperar.
        """
        # Prefiere el final de una oración.
        for match in SENTENCE_END.finditer(self.buffer):
            if self._tags_are_balanced(self.buffer[: match.end()]):
                return match.end()

        # Si no hay oración completa, la coma sirve para no hacer esperar demasiado.
        words_needed = self.first_chunk_words if self.chunk_count == 0 else self.max_chunk_words
        if len(self.buffer.split()) < words_needed:
            return None

        comma = self.buffer.rfind(", ")
        if comma != -1 and self._tags_are_balanced(self.buffer[: comma + 1]):
            return comma + 1
        return None

    @staticmethod
    def _tags_are_balanced(text: str) -> bool:
        """Comprueba que no quede abierta una marca de voz como `<emphasis>`.

        Args:
            text: Fragmento que se quiere liberar.

        Returns:
            Si cada marca abierta ya se cerró.
        """
        return len(OPENING_TAG.findall(text)) <= len(CLOSING_TAG.findall(text))

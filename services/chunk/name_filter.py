"""Quita mi nombre cuando Nova lo usa para dirigirse a mí, como en "Ay, Carlos" o "Carlos, mira"."""

import re

NAME = "Carlos"
# ", Carlos" antes de un signo o un espacio: "Gracias, Carlos." queda "Gracias."
TRAILING_NAME = re.compile(rf",\s*{NAME}\b(?=\s*[.,!?…:;\-)]|\s|$)")
# "Carlos, ..." al inicio de una frase: se quita y la siguiente letra va en mayúscula.
LEADING_NAME = re.compile(rf"(^|[.!?¡¿…]\s*|\n)\s*{NAME},\s*(\S)")
# Lo que se retiene al final mientras llega el resto: podría ser el inicio de un vocativo.
HOLD_CHARS = len(NAME) + 4


def strip_name(text: str) -> str:
    """Quita los vocativos de un texto completo.

    Args:
        text: Texto de Nova.

    Returns:
        El texto sin los vocativos; si mi nombre va en otra función, como "Carlos tiene", se queda.
    """
    without_trailing = TRAILING_NAME.sub("", text)
    return LEADING_NAME.sub(lambda match: match.group(1) + match.group(2).upper(), without_trailing)


class NameFilter:
    """Aplica `strip_name` mientras el texto llega en pedazos."""

    def __init__(self) -> None:
        """Inicia sin texto pendiente."""
        self.pending = ""
        self.at_start = True

    def feed(self, token: str) -> str:
        """Procesa un fragmento.

        Args:
            token: Fragmento recibido del modelo.

        Returns:
            El texto que ya se puede liberar.
        """
        self.pending += token
        cleaned = self._clean(self.pending)

        # Se retiene una cola corta si podría ser el principio de ", Carlos" o "Carlos, ".
        tail_start = max(0, len(cleaned) - HOLD_CHARS)
        tail = cleaned[tail_start:]
        holds = any(marker in tail for marker in (",", NAME[:1]))
        cut = tail_start + min(index for index in (tail.find(","), tail.find(NAME[:1])) if index >= 0) if holds else len(cleaned)
        released, self.pending = cleaned[:cut], cleaned[cut:]
        if released:
            self.at_start = released.rstrip()[-1:] in ".!?¡¿…\n" if released.strip() else self.at_start
        return released

    def flush(self) -> str:
        """Libera lo pendiente al terminar.

        Returns:
            El resto del texto, ya limpio.
        """
        text = self._clean(self.pending)
        self.pending = ""
        return text

    def _clean(self, text: str) -> str:
        """Limpia un pedazo, recordando si va al inicio de una frase.

        Args:
            text: Texto pendiente.

        Returns:
            El texto sin vocativos.
        """
        # Un marcador al frente deja ver si el pedazo empieza una frase, sin dejarlo en el resultado.
        marker = "\n" if self.at_start else ""
        cleaned = strip_name(marker + text)
        return cleaned[len(marker) :] if marker and cleaned.startswith(marker) else cleaned

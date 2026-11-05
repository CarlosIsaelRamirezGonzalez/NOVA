"""Separación de las etiquetas que el modelo incluye en sus respuestas."""

import re
from typing import get_args

from services.schemas import Emotion, EmotionBlend, EmotionComponent, FilteredText

VALID_EMOTIONS = frozenset(get_args(Emotion))
CALM_EMOTION = "neutral"
PHOTO_TAG = "photo"
FORGET_TAG = "forget"
DEFAULT_INTENSITY = 1.0

# Admite `[[search: clima en Monterrey]]`; va antes que las emociones por el `:` de su formato.
SEARCH_PATTERN = re.compile(r"\[\[\s*search\s*:\s*([^\[\]]{1,200}?)\s*\]\]", re.IGNORECASE)
# Admite `[[sad]]` y mezclas como `[[sad:0.6, worried:0.4]]`.
_COMPONENT = r"[a-zA-Z]+(?:\s*:\s*\d*\.?\d+)?"
TAG_PATTERN = re.compile(rf"\[\[\s*({_COMPONENT}(?:\s*,\s*{_COMPONENT})*)\s*\]\]")
TAG_OPENING = "[["
TAG_CLOSING = "]]"
MAX_TAG_LENGTH = 240


def parse_blend(body: str) -> EmotionBlend | None:
    """Convierte el contenido de una etiqueta en una mezcla de emociones.

    Args:
        body: Texto entre los corchetes, por ejemplo `sad:0.6, worried:0.4`.

    Returns:
        La mezcla, o `None` si no contiene ninguna emoción conocida.
    """
    blend = EmotionBlend()
    recognized = False

    for part in body.split(","):
        # Separa el nombre de la intensidad, que es opcional.
        name, _, raw_intensity = part.partition(":")
        name = name.strip().lower()
        if name not in VALID_EMOTIONS:
            continue
        recognized = True

        # La calma no ocupa lugar en la mezcla: es la ausencia de otras emociones.
        if name == CALM_EMOTION:
            continue
        intensity = float(raw_intensity) if raw_intensity.strip() else DEFAULT_INTENSITY
        blend.components.append(EmotionComponent(name=name, intensity=min(intensity, 1.0)))

    return blend if recognized else None


def strip_tags(text: str) -> str:
    """Quita las etiquetas de un texto ya completo, por ejemplo para mostrarlo en el historial.

    Args:
        text: Respuesta guardada, con sus etiquetas.

    Returns:
        El texto sin etiquetas de control.
    """
    tag_filter = EmotionTagFilter()
    return (tag_filter.feed(text).text + tag_filter.flush()).strip()


class EmotionTagFilter:
    """Separa `[[emoción]]`, `[[photo]]`, `[[forget]]` y `[[search: ...]]`, aunque lleguen en varios tokens."""

    def __init__(self) -> None:
        """Inicia sin texto pendiente."""
        self.pending = ""

    def feed(self, token: str) -> FilteredText:
        """Procesa un token nuevo.

        Args:
            token: Fragmento de texto recibido del modelo.

        Returns:
            El texto que ya se puede liberar y las mezclas encontradas.
        """
        self.pending += token
        result = FilteredText()

        while self.pending:
            start = self.pending.find(TAG_OPENING)

            # Sin apertura de etiqueta: se libera todo menos un posible "[" a medias.
            if start == -1:
                held = 1 if self.pending.endswith("[") else 0
                cut = len(self.pending) - held
                result.text += self.pending[:cut]
                self.pending = self.pending[cut:]
                break

            # Libera lo anterior a la apertura y analiza desde ahí.
            result.text += self.pending[:start]
            self.pending = self.pending[start:]

            # Búsqueda: su contenido es texto libre, no una lista de emociones.
            search = SEARCH_PATTERN.match(self.pending)
            if search:
                result.search_query = result.search_query or search.group(1)
                self.pending = self.pending[search.end() :]
                continue

            match = TAG_PATTERN.match(self.pending)

            # Etiqueta completa: se retira del texto; si es desconocida, se descarta.
            if match:
                self._apply_tag(match.group(1), result)
                self.pending = self.pending[match.end() :]
                continue

            # Se cerró sin formato válido, o nunca cerrará: era texto normal.
            if TAG_CLOSING in self.pending or len(self.pending) > MAX_TAG_LENGTH:
                result.text += self.pending[: len(TAG_OPENING)]
                self.pending = self.pending[len(TAG_OPENING) :]
                continue

            # Etiqueta aún incompleta: se espera al siguiente token.
            break

        return result

    @staticmethod
    def _apply_tag(body: str, result: FilteredText) -> None:
        """Registra el contenido de una etiqueta en el resultado.

        Args:
            body: Texto entre los corchetes.
            result: Resultado que se está construyendo.
        """
        tag = body.strip().lower()
        if tag == PHOTO_TAG:
            result.photo_requested = True
            return
        if tag == FORGET_TAG:
            result.forget_requested = True
            return

        blend = parse_blend(body)
        if blend is not None:
            result.blends.append(blend)

    def flush(self) -> str:
        """Libera lo pendiente al terminar la respuesta.

        Returns:
            El texto retenido que resultó no ser una etiqueta.
        """
        text = self.pending
        self.pending = ""
        return text

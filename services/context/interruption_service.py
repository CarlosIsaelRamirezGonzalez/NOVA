"""Cuenta las interrupciones recientes y decide cuánto frustran a Nova.

Se calcula en código para que la reacción sea fiable y no dependa de lo que elija Grok.
"""

import time
from collections.abc import Callable

from services.schemas import EmotionBlend, EmotionComponent

MEMORY_SECONDS = 120.0

# Las interrupciones se olvidan con el tiempo; cuantas más seguidas, mayor la reacción.
ANNOYED_AT = 2
FRUSTRATED_AT = 3
ANGRY_AT = 4


class InterruptionService:
    """Lleva la cuenta de cuántas veces interrumpieron a Nova hace poco."""

    def __init__(
        self,
        memory_seconds: float = MEMORY_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Inicia sin interrupciones.

        Args:
            memory_seconds: Segundos que tarda en olvidarse una interrupción.
            clock: Reloj en segundos; se puede sustituir en las pruebas.
        """
        self.memory_seconds = memory_seconds
        self.clock = clock
        self.moments: list[float] = []

    def count(self) -> int:
        """Cuenta las interrupciones que aún recuerda.

        Returns:
            El número de interrupciones recientes.
        """
        now = self.clock()
        self.moments = [moment for moment in self.moments if now - moment < self.memory_seconds]
        return len(self.moments)

    def record(self) -> EmotionBlend:
        """Registra una interrupción.

        Returns:
            Las emociones que provoca, según cuántas lleva.
        """
        self.moments.append(self.clock())
        count = self.count()

        # La primera se tolera: cualquiera interrumpe alguna vez.
        if count < ANNOYED_AT:
            return EmotionBlend(components=[EmotionComponent(name="surprised", intensity=0.25)])
        if count < FRUSTRATED_AT:
            return EmotionBlend(components=[EmotionComponent(name="frustrated", intensity=0.4)])
        if count < ANGRY_AT:
            return EmotionBlend(components=[EmotionComponent(name="frustrated", intensity=0.7)])

        # A partir de aquí ya no es solo frustración, y sigue subiendo si no para.
        anger = min(0.9, 0.35 + (count - ANGRY_AT) * 0.15)
        return EmotionBlend(
            components=[
                EmotionComponent(name="frustrated", intensity=0.9),
                EmotionComponent(name="angry", intensity=anger),
            ]
        )

    def clear(self) -> None:
        """Olvida las interrupciones, por ejemplo cuando Carlos la calma."""
        self.moments = []

    def describe(self) -> str | None:
        """Redacta las interrupciones recientes para incluirlas en la petición a Grok.

        Returns:
            La nota en inglés, o `None` si no hay ninguna reciente.
        """
        count = self.count()
        if count == 0:
            return None
        return (
            f"Carlos has interrupted you {count} time(s) in the last couple of minutes. "
            "Let that show as described in your instructions."
        )

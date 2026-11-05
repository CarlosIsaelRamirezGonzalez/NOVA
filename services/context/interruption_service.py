"""Cuenta las interrupciones recientes y calcula su efecto en Nova.

Nova está para Carlos: que la interrumpa no la enoja, apenas la toma por sorpresa. Se calcula en
código para que la reacción sea fiable y no dependa de lo que elija el modelo.
"""

import time
from collections.abc import Callable

from services.schemas import EmotionBlend, EmotionComponent

MEMORY_SECONDS = 120.0
SURPRISE_INTENSITY = 0.15


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
            Las emociones que provoca: siempre una sorpresa leve, sin importar cuántas lleve.
        """
        self.moments.append(self.clock())
        return EmotionBlend(
            components=[EmotionComponent(name="surprised", intensity=SURPRISE_INTENSITY)]
        )

    def clear(self) -> None:
        """Olvida las interrupciones, por ejemplo cuando Carlos la calma."""
        self.moments = []

    def describe(self) -> str | None:
        """Redacta las interrupciones recientes para incluirlas en la petición al modelo.

        Returns:
            La nota en inglés, o `None` si no hay ninguna reciente.
        """
        count = self.count()
        if count == 0:
            return None
        return (
            f"Carlos has interrupted you {count} time(s) in the last couple of minutes. "
            "That's fine: it doesn't bother you, and there is no need to mention it."
        )

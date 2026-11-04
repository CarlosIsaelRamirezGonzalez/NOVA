"""Estado emocional de Nova: lo que siente perdura y se desvanece con el tiempo."""

import time
from collections.abc import Callable

from services.context.memory_store import MemoryStore
from services.schemas import EmotionBlend, EmotionComponent

DEFAULT_HALF_LIFE_SECONDS = 60.0
MIN_INTENSITY = 0.08
UNMENTIONED_RETENTION = 0.55
REACTION_WEIGHT = 0.75


class EmotionalStateService:
    """Acumula emociones entre turnos para que Nova no empiece cada respuesta desde cero.

    Es una simulación: números que influyen en cómo se muestra y responde Nova.
    """

    def __init__(
        self,
        half_life_seconds: float = DEFAULT_HALF_LIFE_SECONDS,
        clock: Callable[[], float] = time.time,
        store: MemoryStore | None = None,
    ) -> None:
        """Recupera el último ánimo guardado, o inicia en calma.

        Args:
            half_life_seconds: Segundos en que una emoción pierde la mitad de su fuerza.
            clock: Reloj en segundos reales, para que el ánimo también se desvanezca mientras
                Nova está apagada; se puede sustituir en las pruebas.
            store: Memoria persistente; sin ella, el ánimo se pierde al cerrar.
        """
        self.half_life_seconds = half_life_seconds
        self.clock = clock
        self.store = store
        self.components: list[EmotionComponent] = []
        self.updated_at = clock()

        saved = store.load_mood() if store else None
        if saved:
            self.components = saved.blend.components
            self.updated_at = saved.updated_at

    def current(self) -> EmotionBlend:
        """Calcula lo que siente Nova en este momento.

        Returns:
            La mezcla actual, de la emoción más fuerte a la más débil.
        """
        # Aplica el desvanecimiento acumulado desde la última actualización.
        now = self.clock()
        factor = 0.5 ** ((now - self.updated_at) / self.half_life_seconds)
        self.updated_at = now

        # Reduce cada emoción y olvida las que ya casi no se sienten.
        faded = [
            EmotionComponent(name=item.name, intensity=item.intensity * factor)
            for item in self.components
        ]
        self.components = [item for item in faded if item.intensity >= MIN_INTENSITY]
        return EmotionBlend(components=self.components)

    def absorb(self, blend: EmotionBlend) -> EmotionBlend:
        """Actualiza lo que siente Nova con su reacción al momento actual.

        La reacción manda, porque Grok la elige sabiendo lo que Nova ya sentía: así un
        perdón puede aliviarla. Lo anterior no desaparece de golpe, sino que deja un resto.

        Args:
            blend: Emociones que Nova indica sentir ahora.

        Returns:
            La mezcla resultante, de la emoción más fuerte a la más débil.
        """
        self.current()
        mentioned = {item.name for item in blend.components}

        # Lo que dejó de mencionar se alivia, aunque no se borra de inmediato.
        for item in self.components:
            if item.name not in mentioned:
                item.intensity *= UNMENTIONED_RETENTION

        for incoming in blend.components:
            existing = next((item for item in self.components if item.name == incoming.name), None)

            # Una emoción nueva entra con su fuerza; una que ya existía se acerca al valor indicado.
            if existing is None:
                self.components.append(incoming.model_copy())
            else:
                existing.intensity += (incoming.intensity - existing.intensity) * REACTION_WEIGHT

        # Olvida lo que ya casi no se siente y ordena de mayor a menor.
        self.components = [item for item in self.components if item.intensity >= MIN_INTENSITY]
        self.components.sort(key=lambda item: item.intensity, reverse=True)
        return self._save()

    def intensify(self, blend: EmotionBlend) -> EmotionBlend:
        """Suma una reacción sin aliviar lo que Nova ya sentía.

        A diferencia de `absorb`, sirve para sucesos que no vienen de una respuesta de Grok.

        Args:
            blend: Emociones que provocó el suceso.

        Returns:
            La mezcla resultante, de la emoción más fuerte a la más débil.
        """
        self.current()

        for incoming in blend.components:
            existing = next((item for item in self.components if item.name == incoming.name), None)
            if existing is None:
                self.components.append(incoming.model_copy())
            else:
                existing.intensity = max(existing.intensity, incoming.intensity)

        self.components.sort(key=lambda item: item.intensity, reverse=True)
        return self._save()

    def calm(self) -> None:
        """Devuelve a Nova a la calma de inmediato."""
        self.components = []
        self.updated_at = self.clock()
        self._save()

    def _save(self) -> EmotionBlend:
        """Guarda el ánimo actual en la memoria persistente, si la hay.

        Returns:
            El ánimo actual.
        """
        blend = EmotionBlend(components=self.components)
        if self.store:
            self.store.save_mood(blend)
        return blend

    def describe(self) -> str | None:
        """Redacta el estado actual para incluirlo en la petición a Grok.

        Returns:
            La descripción en inglés, o `None` si Nova está en calma.
        """
        components = self.current().components
        if not components:
            return None

        feelings = ", ".join(f"{item.name} {item.intensity:.2f}" for item in components)
        return (
            f"Your feelings still lingering from before this message: {feelings} (0 to 1). "
            "Your tag must state what you feel now: keep what still hurts, lower what has eased, "
            "and leave out what has passed. Do not mention these numbers."
        )

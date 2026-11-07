"""Memoria visual: lo que Nova nota de cómo me veo, como datos y nunca como fotos."""

import asyncio
import re
import time
import traceback
from collections.abc import Callable

from services.agents.llms_service import LLMService
from services.context.memory_store import MemoryStore
from services.schemas import (
    ChatMessage,
    ChatRequest,
    ImagePart,
    ImageUrl,
    TextPart,
    FaceCheck,
    VisualObservation,
    VisualProfileEvent,
    VisualRecord,
    VisualTrend,
)

# Solo se guarda si hablo de mí; "mira esta planta" no dice nada de cómo me visto.
SELF_LOOK = re.compile(
    r"\b(me|mi|mis|traigo|llevo|visto|vestido|vestida|ando|estoy|vengo|puesto|puesta)\b",
    re.IGNORECASE,
)
# Si hablo de otra persona, lo que se ve en la foto no es mío, aunque diga "mi".
ABOUT_SOMEONE_ELSE = re.compile(
    r"\b(te presento|presentar|conozcas|conoce a|sal[uú]da\w*|mi (?:mam|pap|herman|prim|t[ií][oa]|amig|novi|"
    r"espos|hij|abuel|compa|jef|sobrin|cu[nñ]ad|suegr|vecin))",
    re.IGNORECASE,
)
# Campos que forman tendencias. Solo existen estos: el esquema no deja guardar otra cosa.
TREND_FIELDS = ("top_type", "top_color", "headwear", "glasses", "hair_length", "facial_hair")
UNKNOWN = "unknown"
# Antes de esto son casualidades, no tendencias.
MIN_OBSERVATIONS = 5
MIN_SHARE = 0.5
HALF_LIFE_DAYS = 30
SECONDS_PER_DAY = 86400
# Con estas fotos seguidas iguales, y distintas a la costumbre, se nota el cambio.
RECENT_CHANGE_COUNT = 3

OBSERVE_PROMPT = """
You record how a person looks in a photo, using only the fields of the schema.
Count the people visible in person_count. Describe the person closest to the camera. Use "unknown"
whenever something isn't clearly visible; don't guess. Describe only what is plainly there.
"""
OBSERVE_INSTRUCTION = "Fill in the fields from this photo."

PROFILE_NOTE = (
    "What you have noticed about how Carlos usually looks, from photos he asked you to take. These are "
    "habits, not what he has on today. Mention them only when it comes up naturally. Never comment on "
    "his body, weight, skin, age, or health, even if he seems to invite it with a joke.\n{lines}"
)


def _recent_change(values: list[str], usual: str) -> str | None:
    """Busca un cambio reciente respecto a la costumbre.

    Args:
        values: Valores conocidos, del más antiguo al más nuevo.
        usual: Valor de costumbre.

    Returns:
        El valor nuevo, si las últimas observaciones coinciden en otro distinto.
    """
    latest = values[-RECENT_CHANGE_COUNT:]
    is_consistent = len(latest) == RECENT_CHANGE_COUNT and len(set(latest)) == 1
    return latest[0] if is_consistent and latest[0] != usual else None


def compute_trends(records: list[VisualRecord], now: float) -> list[VisualTrend]:
    """Cuenta las observaciones. Lo calcula el código: así el modelo no inventa costumbres.

    Args:
        records: Observaciones, de la más antigua a la más nueva.
        now: Momento actual, en segundos.

    Returns:
        Las tendencias con evidencia suficiente; lo reciente pesa más.
    """
    trends: list[VisualTrend] = []
    for field in TREND_FIELDS:
        known = [
            (getattr(record.observation, field), record.created_at)
            for record in records
            if getattr(record.observation, field) != UNKNOWN
        ]
        if len(known) < MIN_OBSERVATIONS:
            continue

        weights: list[tuple[str, float]] = []
        for value in {value for value, _ in known}:
            weight = sum(
                0.5 ** ((now - created_at) / (HALF_LIFE_DAYS * SECONDS_PER_DAY))
                for candidate, created_at in known
                if candidate == value
            )
            weights.append((value, weight))
        usual, usual_weight = max(weights, key=lambda item: item[1])
        if usual_weight / sum(weight for _, weight in weights) < MIN_SHARE:
            continue

        values = [value for value, _ in known]
        trends.append(
            VisualTrend(
                field=field,
                value=usual,
                count=values.count(usual),
                total=len(values),
                recent_value=_recent_change(values, usual),
            )
        )
    return trends


class VisualMemoryService:
    """Extrae lo que se ve en las fotos que pido y lleva la cuenta de mis costumbres."""

    def __init__(
        self,
        store: MemoryStore,
        llm: LLMService,
        model: str,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Guarda los servicios.

        Args:
            store: Memoria persistente.
            llm: Cliente del modelo de lenguaje.
            model: Modelo que describe las fotos.
            clock: Reloj en segundos; se puede sustituir en las pruebas.
        """
        self.store = store
        self.llm = llm
        self.model = model
        self.clock = clock
        self.pending: set[asyncio.Task[None]] = set()

    def observe_later(self, photo_url: str, user_input: str, face: FaceCheck | None = None) -> None:
        """Registra una foto en segundo plano, para no retrasar la respuesta.

        Args:
            photo_url: Foto como data URL; no se conserva.
            user_input: Mensaje con el que pedí la foto.
            face: Si ya aprendió mi cara, a quién reconoció en la foto.
        """
        if ABOUT_SOMEONE_ELSE.search(user_input):
            return

        # Si conoce mi cara, ella decide; si no, solo cuenta si hablo de mí.
        is_him = face.carlos_present and face.face_count == 1 if face else SELF_LOOK.search(user_input)
        if not is_him:
            return
        task = asyncio.create_task(self._observe(photo_url))
        self.pending.add(task)
        task.add_done_callback(self.pending.discard)

    async def _observe(self, photo_url: str) -> None:
        """Describe la foto y guarda el resultado si solo aparece una persona.

        Los errores no se propagan: perder una observación no debe afectar la conversación.

        Args:
            photo_url: Foto como data URL.
        """
        request = ChatRequest(
            purpose="memory",
            model=self.model,
            output_schema=VisualObservation.model_json_schema(),
            messages=[
                ChatMessage(role="system", content=OBSERVE_PROMPT),
                ChatMessage(
                    role="user",
                    content=[
                        ImagePart(image_url=ImageUrl(url=photo_url)),
                        TextPart(text=OBSERVE_INSTRUCTION),
                    ],
                ),
            ],
        )
        try:
            completion = await self.llm.complete(request)
            observation = VisualObservation.model_validate_json(completion)

            # Con otra gente en la foto no se sabe de quién es qué, y de ellos no se guarda nada.
            if observation.person_count != 1:
                print(f"[Visual] not saved: {observation.person_count} people", flush=True)
                return
            self.store.add_visual_observation(observation)
            print("[Visual] observation saved", flush=True)
        except Exception:
            traceback.print_exc()

    def describe_for_model(self) -> str | None:
        """Redacta lo que Nova sabe de cómo me veo.

        Returns:
            La nota para el modelo, o `None` si aún no hay tendencias.
        """
        trends = compute_trends(self.store.visual_observations(), self.clock())
        if not trends:
            return None
        lines = []
        for trend in trends:
            line = f"- {trend.field}: usually {trend.value} ({trend.count} of {trend.total} photos)"
            if trend.recent_value:
                line += f", lately {trend.recent_value}"
            lines.append(line)
        return PROFILE_NOTE.format(lines="\n".join(lines))

    def report(self) -> VisualProfileEvent:
        """Junta lo que muestra la vista de la memoria visual.

        Returns:
            Las tendencias y las observaciones, de la más nueva a la más antigua.
        """
        records = self.store.visual_observations()
        return VisualProfileEvent(
            trends=compute_trends(records, self.clock()),
            observations=list(reversed(records)),
            min_observations=MIN_OBSERVATIONS,
        )

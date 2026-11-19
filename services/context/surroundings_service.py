"""Lo que Nova nota del entorno de Carlos por su cuenta: quién está, qué pasa, si algo anda mal.

Cada vistazo es una foto que Claude mira junto con el motivo (otra voz, un golpe, un vistazo de
rutina) y lo reciente de la plática. Claude decide si vale la pena hablar; casi siempre no. Lo que
vio queda solo en memoria, unas horas, como contexto para los siguientes turnos. La foto no se guarda.
"""

import time
from collections.abc import Callable
from datetime import datetime

from pydantic import ValidationError

from services.agents.llms_service import LLMService
from services.chunk.name_filter import strip_name
from services.schemas import (
    ChatMessage,
    ChatRequest,
    FaceCheck,
    GlanceDecision,
    GlanceKind,
    ImagePart,
    ImageUrl,
    SurroundingsNote,
    TextPart,
)

GLANCE_MODEL = "claude-haiku-5-5"
MAX_NOTES = 6
NOTE_LIFETIME_SECONDS = 3 * 3600
MAX_SAY_CHARS = 200

GLANCE_PROMPT = """
You are Nova, Carlos's AI companion. You live on his Mac and you care about him. You just took one
photo with his camera on your own, without him asking, for this reason: {reason}.

Decide two things from the photo:
1. observation: one short, factual English sentence about what matters to understand his situation:
   whether he is there, what he seems to be doing, his apparent state, who else is there, and
   anything wrong. Don't describe other people's bodies, and don't guess who a stranger is.
2. speak: whether this is worth interrupting him for. Almost always it is not. Speak only if he
   seems hurt, unwell, upset or in danger, something broke or fell, an alarm or smoke suggests an
   emergency, or someone just arrived whom he might want to introduce. Never speak about his looks
   unless he was just talking about them, and never just to say what you see.

If speak is true, say is one short spoken line in Mexican Spanish, warm and direct, without his
name and without describing the photo in detail ("Oí un golpe, ¿estás bien?").

{context}
"""

FaceCheckProvider = Callable[[str], FaceCheck | None]


class SurroundingsService:
    """Interpreta los vistazos y guarda lo reciente para los siguientes turnos."""

    def __init__(self, llm: LLMService, clock: Callable[[], float] = time.time) -> None:
        """Guarda el cliente.

        Args:
            llm: Cliente de la API de chat.
            clock: Reloj en segundos; se puede sustituir en las pruebas.
        """
        self.llm = llm
        self.clock = clock
        self.notes: list[SurroundingsNote] = []

    async def interpret(
        self,
        photo_data_url: str,
        kind: GlanceKind,
        reason: str,
        conversation: str,
        face: FaceCheck | None,
    ) -> GlanceDecision:
        """Le pide a Claude que entienda un vistazo y decida si hablar.

        Args:
            photo_data_url: Foto recién tomada, como data URL.
            kind: Qué la hizo mirar.
            reason: El motivo en palabras.
            conversation: Lo reciente de la plática, sin etiquetas.
            face: Si una revisión local reconoció a Carlos en la foto.

        Returns:
            Lo que vio y si debe hablar. Si Claude responde algo inválido, no habla.
        """
        context_lines = [f"Current local time: {datetime.now().astimezone():%A %H:%M}."]
        if face and face.carlos_present:
            context_lines.append("A local face check recognized Carlos in the photo (likely, not certain).")
        elif face and face.face_count:
            context_lines.append(f"A local face check found {face.face_count} face(s) but did not recognize Carlos.")
        earlier = self.describe_for_model()
        if earlier:
            context_lines.append(earlier)
        if conversation:
            context_lines.append(f"Recent conversation:\n{conversation}")

        prompt = GLANCE_PROMPT.format(reason=reason, context="\n\n".join(context_lines))
        request = ChatRequest(
            model=GLANCE_MODEL,
            messages=[
                ChatMessage(role="system", content=prompt.strip()),
                ChatMessage(
                    role="user",
                    content=[
                        TextPart(text="This is the photo you just took."),
                        ImagePart(image_url=ImageUrl(url=photo_data_url)),
                    ],
                ),
            ],
            output_schema=GlanceDecision.model_json_schema(),
        )
        try:
            decision = GlanceDecision.model_validate_json(await self.llm.complete(request))
        except ValidationError:
            return GlanceDecision(observation="", speak=False, say="")

        if decision.observation:
            self.remember(kind, reason, decision.observation)
        if not decision.say.strip():
            decision.speak = False
        # Mi nombre como muletilla se quita igual que en el resto de sus respuestas.
        say = strip_name(decision.say).strip()[:MAX_SAY_CHARS]
        # Al quitar "Carlos," la frase puede quedar en minúscula: "¿estás bien?".
        first_letter = next((index for index, character in enumerate(say) if character.isalpha()), None)
        if first_letter is not None:
            say = say[:first_letter] + say[first_letter].upper() + say[first_letter + 1 :]
        decision.say = say
        return decision

    def remember(self, kind: GlanceKind, reason: str, observation: str) -> None:
        """Guarda lo que notó, solo en memoria y solo unas horas.

        Args:
            kind: Qué la hizo mirar.
            reason: El motivo en palabras.
            observation: Lo que vio.
        """
        self.notes.append(SurroundingsNote(at=self.clock(), kind=kind, reason=reason, observation=observation))
        del self.notes[:-MAX_NOTES]

    def describe_for_model(self) -> str | None:
        """Resume lo reciente que notó del entorno, para la siguiente respuesta.

        Returns:
            La nota, o `None` si no notó nada en las últimas horas.
        """
        now = self.clock()
        recent = [note for note in self.notes if now - note.at < NOTE_LIFETIME_SECONDS]
        if not recent:
            return None
        lines = "\n".join(
            f"- {datetime.fromtimestamp(note.at).astimezone():%H:%M} ({note.reason}): {note.observation}"
            for note in recent
        )
        return (
            "What you noticed around Carlos on your own recently, from glances he didn't ask for. "
            "Use it to understand him; bring it up only if it matters:\n" + lines
        )

"""Modelos Pydantic de todos los datos que entran y salen de Nova.

Agrupa los contratos con las APIs de xAI y con el navegador, para que ningún
servicio maneje estructuras sin validar.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, TypeAdapter

MAX_MESSAGE_CHARS = 4000

Emotion = Literal[
    "neutral",
    "happy",
    "sad",
    "angry",
    "surprised",
    "curious",
    "afraid",
    "worried",
    "stressed",
    "frustrated",
]
MessageRole = Literal["system", "user", "assistant"]
Gesture = Literal["middle_finger", "thumbs_up"]
MemoryKind = Literal["fact", "preference", "person", "event", "plan", "moment"]
PhotoStatus = Literal["granted", "camera_off", "daily_limit", "cooldown", "failed"]

# Una foto de 640x480 en JPEG ocupa bastante menos; esto solo frena envíos anómalos.
MAX_PHOTO_DATA_URL_CHARS = 2_000_000


# ---------------------------------------------------------------------------
# Peticiones al modelo de lenguaje
# ---------------------------------------------------------------------------
UsagePurpose = Literal["conversation", "memory", "search", "voice"]


MovePlace = Literal[
    "away",
    "left",
    "right",
    "up",
    "down",
    "top_left",
    "top_right",
    "bottom_left",
    "bottom_right",
    "center",
    "stay",
    "roam",
    "hide",
    "spin",
    "show_back",
    "dance",
]
TypingStatus = Literal["written", "stopped", "app_changed", "secure_field"]
WriteStatus = (
    TypingStatus
    | Literal["blocked_app", "needs_accessibility", "needs_screen", "no_window", "no_field", "failed"]
)


class FrontApp(BaseModel):
    """App que tengo al frente.

    Attributes:
        pid: Proceso de la app.
        bundle_id: Identificador de la app en macOS.
        name: Nombre visible.
    """

    pid: int
    bundle_id: str
    name: str


class WritingDraft(BaseModel):
    """Texto que el redactor propone teclear.

    Attributes:
        existing_draft: Lo que ya estaba escrito en el campo.
        text: Texto para escribir en el cursor.
        problem: `no_field` si no se ve dónde escribir.
    """

    existing_draft: str
    text: str
    problem: Literal["none", "no_field"]


class WriteResult(BaseModel):
    """Cómo terminó un intento de escribir en la app al frente.

    Attributes:
        status: Resultado.
        app_name: App en la que se intentó, si se llegó a saber.
    """

    status: WriteStatus
    app_name: str = "esa app"


class TextPart(BaseModel):
    """Parte de texto de un mensaje con varias partes.

    Attributes:
        type: Discriminador de la parte.
        text: Contenido de texto.
    """

    type: Literal["text"] = "text"
    text: str


class ImageUrl(BaseModel):
    """Referencia a una imagen dentro de un mensaje.

    Attributes:
        url: Imagen como data URL.
        detail: Nivel de detalle; a menor detalle, menor costo.
    """

    url: str
    detail: Literal["low", "high"] = "low"


class ImagePart(BaseModel):
    """Parte de imagen de un mensaje con varias partes.

    Attributes:
        type: Discriminador de la parte.
        image_url: Imagen adjunta.
    """

    type: Literal["image_url"] = "image_url"
    image_url: ImageUrl


class ChatMessage(BaseModel):
    """Un mensaje enviado a la API de chat.

    Attributes:
        role: Quién escribió el mensaje.
        content: Texto del mensaje, o varias partes si incluye una imagen.
    """

    role: MessageRole
    content: str | list[TextPart | ImagePart]


class ToolDefinition(BaseModel):
    """Función que el modelo puede pedir que se ejecute.

    Attributes:
        name: Nombre de la función.
        description: Cuándo debe usarla el modelo.
        parameters: Esquema JSON de sus argumentos, generado desde un modelo Pydantic.
    """

    name: str
    description: str
    parameters: JsonValue


class EmptyArguments(BaseModel):
    """Argumentos de una herramienta que no necesita ninguno."""


class SearchArguments(BaseModel):
    """Argumentos con los que el modelo pide una búsqueda en internet.

    Attributes:
        query: Qué buscar, corto y específico.
    """

    query: str


class MoveArguments(BaseModel):
    """Argumentos con los que el modelo pide moverse por la pantalla.

    Attributes:
        place: A dónde ir, o `stay`, `roam`, `hide`, `spin`, `show_back` y `dance` para quedarse,
            pasear, ocultarse, dar una vuelta completa, enseñar la espalda o bailar.
    """

    place: MovePlace


class WriteArguments(BaseModel):
    """Argumentos con los que el modelo pide escribir en la app al frente.

    Attributes:
        instructions: Qué quiero que se escriba, con los datos que di.
    """

    instructions: str


class ChatRequest(BaseModel):
    """Petición al modelo de lenguaje.

    Attributes:
        purpose: Para qué es la llamada; separa el gasto en la vista de gastos.
        model: Identificador del modelo.
        messages: Historial completo; el primer mensaje es el prompt de sistema.
        output_schema: Esquema JSON de la respuesta, si debe ser estructurada.
        tools: Herramientas que el modelo puede pedir, si tiene alguna en esta llamada.
    """

    purpose: UsagePurpose = "conversation"
    model: str
    messages: list[ChatMessage]
    output_schema: JsonValue | None = None
    tools: list[ToolDefinition] | None = None


# ---------------------------------------------------------------------------
# API de voz (TTS)
# ---------------------------------------------------------------------------
class ElevenLabsHeaders(BaseModel):
    """Cabeceras HTTP que requiere la API de ElevenLabs.

    Attributes:
        xi_api_key: Clave secreta.
        content_type: Valor de la cabecera `Content-Type`.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    xi_api_key: str = Field(alias="xi-api-key")
    content_type: str = Field(default="application/json", alias="Content-Type")


class VoiceSettings(BaseModel):
    """Cómo suena la voz de Nova.

    Attributes:
        stability: Menos estabilidad da más rango emocional.
        similarity_boost: Qué tanto se apega a la voz original.
        style: Qué tanto exagera el estilo de la voz.
        speed: Multiplicador de la velocidad de habla.
    """

    stability: float = 0.35
    similarity_boost: float = 0.75
    style: float = 0.45
    speed: float = 1.05


class TtsRequest(BaseModel):
    """Cuerpo de una petición a la API de voz.

    Attributes:
        text: Texto que se va a pronunciar.
        model_id: Modelo de voz.
        voice_settings: Cómo suena la voz.
    """

    text: str
    model_id: str
    voice_settings: VoiceSettings


# ---------------------------------------------------------------------------
# Procesamiento interno
# ---------------------------------------------------------------------------
class EmotionComponent(BaseModel):
    """Una emoción dentro de una mezcla.

    Attributes:
        name: Emoción sentida.
        intensity: Fuerza de la emoción, de 0 a 1.
    """

    name: Emotion
    intensity: float = Field(ge=0, le=1)


class EmotionBlend(BaseModel):
    """Mezcla de emociones sentidas al mismo tiempo.

    Attributes:
        components: Emociones presentes; vacía significa calma.
    """

    components: list[EmotionComponent] = Field(default_factory=list)


class FilteredText(BaseModel):
    """Resultado de separar las etiquetas del texto.

    Attributes:
        text: Texto limpio que se puede mostrar y pronunciar.
        blends: Mezclas encontradas, en orden de aparición.
        photo_requested: Si Nova pidió ver la cámara.
        forget_requested: Si Nova decidió olvidar algo porque se lo pedí.
        search_query: Lo que Nova quiere buscar en internet, si pidió hacerlo.
        write_instructions: Lo que Nova debe escribir en la app al frente, si pidió hacerlo.
        move_place: A dónde quiere moverse Nova en la pantalla, si pidió hacerlo.
        learn_face_requested: Si Nova debe aprender mi cara porque se lo pedí.
    """

    text: str = ""
    blends: list[EmotionBlend] = Field(default_factory=list)
    photo_requested: bool = False
    forget_requested: bool = False
    search_query: str | None = None
    write_instructions: str | None = None
    move_place: MovePlace | None = None
    learn_face_requested: bool = False


class VisualObservation(BaseModel):
    """Lo que se puede guardar de una foto. Son valores fijos a propósito: no existe un campo
    donde quepan peso, cuerpo, piel, edad, salud o estado de ánimo.

    Attributes:
        person_count: Cuántas personas se ven.
        top_type: Prenda superior.
        top_color: Color principal de esa prenda.
        headwear: Qué lleva en la cabeza.
        glasses: Si usa lentes.
        hair_length: Largo del cabello.
        facial_hair: Vello facial.
    """

    model_config = ConfigDict(extra="forbid")

    person_count: int
    top_type: Literal["t_shirt", "shirt", "polo", "hoodie", "sweater", "jacket", "tank_top", "other", "unknown"]
    top_color: Literal[
        "black", "white", "gray", "blue", "red", "green", "yellow", "orange", "purple", "pink",
        "brown", "beige", "patterned", "unknown",
    ]
    headwear: Literal["none", "cap", "beanie", "hood", "other", "unknown"]
    glasses: Literal["yes", "no", "unknown"]
    hair_length: Literal["shaved", "short", "medium", "long", "unknown"]
    facial_hair: Literal["none", "stubble", "beard", "mustache", "unknown"]


class FaceDetection(BaseModel):
    """Una cara encontrada en una imagen.

    Attributes:
        box: Rectángulo: izquierda, arriba, derecha y abajo.
        score: Confianza del detector.
        points: Ojos, nariz y comisuras.
    """

    box: list[float]
    score: float
    points: list[list[float]]


class FaceCheck(BaseModel):
    """Resultado de buscarme en una foto.

    Attributes:
        face_count: Cuántas caras hay.
        carlos_present: Si una de ellas es la mía.
    """

    face_count: int
    carlos_present: bool


class FaceEnrollment(BaseModel):
    """Resultado de aprender mi cara.

    Attributes:
        status: Si la aprendió o por qué no.
        photos_used: Cuántas fotos sirvieron.
    """

    status: Literal["learned", "many_faces", "no_clear_face", "no_camera"]
    photos_used: int = 0


class VisualRecord(BaseModel):
    """Una observación guardada.

    Attributes:
        id: Identificador.
        created_at: Momento de la foto, en segundos.
        observation: Lo que se vio.
    """

    id: int
    created_at: float
    observation: VisualObservation


class VisualTrend(BaseModel):
    """Una costumbre calculada a partir de las observaciones.

    Attributes:
        field: Campo de la observación.
        value: Valor de costumbre.
        count: Fotos en que aparece.
        total: Fotos en que ese campo se pudo ver.
        recent_value: Valor distinto en las últimas fotos, si cambió.
    """

    field: str
    value: str
    count: int
    total: int
    recent_value: str | None = None


class ForgetDecision(BaseModel):
    """Lo que decide el modelo que resuelve qué quiero olvidar.

    Attributes:
        memory_ids: Recuerdos que hay que borrar.
        search_terms: Palabras muy específicas, como nombres, para borrar los mensajes que las
            mencionan.
    """

    model_config = ConfigDict(extra="forbid")

    memory_ids: list[int]
    search_terms: list[str]


class StoredMessage(BaseModel):
    """Un mensaje leído de la memoria persistente.

    Attributes:
        role: Quién lo escribió.
        content: Texto del mensaje.
        created_at: Momento en que se guardó, en segundos.
    """

    role: MessageRole
    content: str
    created_at: float


class StoredMood(BaseModel):
    """Estado emocional leído de la memoria persistente.

    Attributes:
        blend: Emociones que sentía Nova.
        updated_at: Momento en que se guardó, en segundos.
    """

    blend: EmotionBlend
    updated_at: float


class ExtractedMemory(BaseModel):
    """Un recuerdo propuesto por el modelo extractor.

    Attributes:
        content: El recuerdo, en una frase en español.
        kind: Tipo de recuerdo.
        importance: Qué tanto importa, de 0 a 1.
        replaces: Identificador del recuerdo que corrige o actualiza, si alguno.
    """

    model_config = ConfigDict(extra="forbid")

    content: str
    kind: MemoryKind
    importance: float
    replaces: int | None


class ExtractionResult(BaseModel):
    """Respuesta del modelo extractor.

    Attributes:
        memories: Recuerdos nuevos; vacía si no hay nada que valga la pena guardar.
    """

    model_config = ConfigDict(extra="forbid")

    memories: list[ExtractedMemory]


class Memory(BaseModel):
    """Un recuerdo guardado.

    Attributes:
        id: Identificador en la base de datos.
        kind: Tipo de recuerdo.
        content: El recuerdo, en una frase en español.
        importance: Qué tanto importa, de 0 a 1.
        emotions: Lo que sentía Nova cuando se formó.
        source_message_id: Mensaje de donde salió.
        created_at: Momento en que se guardó, en segundos.
    """

    id: int
    kind: MemoryKind
    content: str
    importance: float
    emotions: EmotionBlend
    source_message_id: int | None
    created_at: float

    @property
    def intensity(self) -> float:
        """Calcula qué tan intensa fue la emoción de este recuerdo.

        Returns:
            La intensidad de la emoción más fuerte, o 0 si Nova estaba en calma.
        """
        return max((item.intensity for item in self.emotions.components), default=0.0)


class VectorHit(BaseModel):
    """Un resultado de la búsqueda por significado.

    Attributes:
        memory_id: Identificador del recuerdo encontrado.
        score: Parecido con lo que se buscó, de 0 a 1 aproximadamente.
    """

    memory_id: int
    score: float


class WebSearchResult(BaseModel):
    """Lo que encontró una búsqueda en internet.

    Attributes:
        text: Resumen de lo encontrado.
        sources: Enlaces de donde salió la información.
    """

    text: str
    sources: list[str] = Field(default_factory=list)


class StreamedReply(BaseModel):
    """Resultado de una llamada completa al modelo.

    Attributes:
        raw_text: Respuesta tal como llegó, con sus etiquetas.
        photo_requested: Si Nova pidió ver la cámara.
        forget_requested: Si Nova decidió olvidar algo.
        search_query: Lo que Nova quiere buscar en internet, si pidió hacerlo.
        write_instructions: Lo que Nova debe escribir en la app al frente, si pidió hacerlo.
        move_place: A dónde quiere moverse Nova en la pantalla, si pidió hacerlo.
        learn_face_requested: Si Nova debe aprender mi cara porque se lo pedí.
    """

    raw_text: str = ""
    photo_requested: bool = False
    forget_requested: bool = False
    search_query: str | None = None
    write_instructions: str | None = None
    move_place: MovePlace | None = None
    learn_face_requested: bool = False


class PhotoResult(BaseModel):
    """Resultado de intentar tomar una foto para Nova.

    Attributes:
        status: Si se obtuvo la foto o por qué no.
        data_url: La imagen como data URL, si se obtuvo.
    """

    status: PhotoStatus
    data_url: str | None = None


class PhotoUsage(BaseModel):
    """Fotos tomadas en un día; se guarda en disco para que reiniciar no borre el límite.

    Attributes:
        day: Fecha en formato ISO.
        count: Fotos tomadas ese día.
    """

    day: str
    count: int = 0


# ---------------------------------------------------------------------------
# WebSocket con el navegador
# ---------------------------------------------------------------------------
class ListenRequest(BaseModel):
    """Petición del navegador para encender o apagar el micrófono.

    Attributes:
        type: Discriminador de la petición.
        enabled: Si el micrófono debe quedar escuchando.
    """

    type: Literal["listen"] = "listen"
    enabled: bool


class MicGateRequest(BaseModel):
    """Aviso del navegador de si se puede escuchar: mientras Nova habla, no.

    Attributes:
        type: Discriminador de la petición.
        open: Si se puede escuchar ahora.
        camera_on: Si la cámara está encendida, para el turno que se inicie por voz.
    """

    type: Literal["mic_gate"] = "mic_gate"
    open: bool
    camera_on: bool = False


class UsageRequest(BaseModel):
    """Petición del navegador para ver los gastos de las APIs.

    Attributes:
        type: Discriminador de la petición.
    """

    type: Literal["usage"] = "usage"


class BrainRequest(BaseModel):
    """Petición del navegador para ver el cerebro de Nova.

    Attributes:
        type: Discriminador de la petición.
    """

    type: Literal["brain"] = "brain"


class VisualProfileRequest(BaseModel):
    """Petición del navegador para ver la memoria visual.

    Attributes:
        type: Discriminador de la petición.
    """

    type: Literal["visual_profile"] = "visual_profile"


class ForgetVisualRequest(BaseModel):
    """Petición del navegador para borrar observaciones visuales.

    Attributes:
        type: Discriminador de la petición.
        observation_id: Observación que se va a borrar; sin ella, se borran todas.
    """

    type: Literal["forget_visual"] = "forget_visual"
    observation_id: int | None = None


class ForgetFaceRequest(BaseModel):
    """Petición del navegador para borrar la huella de la cara.

    Attributes:
        type: Discriminador de la petición.
    """

    type: Literal["forget_face"] = "forget_face"


class ForgetMemoryRequest(BaseModel):
    """Petición del navegador para borrar un recuerdo concreto.

    Attributes:
        type: Discriminador de la petición.
        memory_id: Recuerdo que se va a borrar.
    """

    type: Literal["forget_memory"] = "forget_memory"
    memory_id: int


class PhotoResponse(BaseModel):
    """Respuesta del navegador a una petición de foto.

    Attributes:
        type: Discriminador de la petición.
        request_id: Identificador de la petición que se responde.
        data_url: Foto en JPEG, o `None` si la cámara está apagada.
    """

    type: Literal["photo"] = "photo"
    request_id: str
    data_url: (
        Annotated[
            str,
            StringConstraints(
                pattern=r"^data:image/jpeg;base64,[A-Za-z0-9+/=]+$",
                max_length=MAX_PHOTO_DATA_URL_CHARS,
            ),
        ]
        | None
    ) = None


class GestureRequest(BaseModel):
    """Aviso del navegador de que detectó un gesto de la mano en la cámara.

    Attributes:
        type: Discriminador de la petición.
        name: Gesto detectado.
    """

    type: Literal["gesture"] = "gesture"
    name: Gesture


class InterruptRequest(BaseModel):
    """Petición del navegador para interrumpir a Nova mientras responde o habla.

    Attributes:
        type: Discriminador de la petición.
    """

    type: Literal["interrupt"] = "interrupt"


class CalmRequest(BaseModel):
    """Petición del navegador para calmar a Nova.

    Attributes:
        type: Discriminador de la petición.
    """

    type: Literal["calm"] = "calm"


class ChatRequestMessage(BaseModel):
    """Mensaje que el usuario le envía a Nova desde el navegador.

    Attributes:
        type: Discriminador de la petición.
        text: Lo que escribió o dictó el usuario, ya sin espacios sobrantes.
        camera_on: Si la cámara está encendida en este momento.
    """

    type: Literal["chat"] = "chat"
    camera_on: bool = False
    text: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_CHARS),
    ]


class TokenEvent(BaseModel):
    """Fragmento de la respuesta de Nova para mostrar en pantalla.

    Attributes:
        type: Discriminador del evento.
        text: Texto del fragmento.
    """

    type: Literal["token"] = "token"
    text: str


class EmotionEvent(BaseModel):
    """Estado emocional actual de Nova.

    Attributes:
        type: Discriminador del evento.
        components: Emociones que debe mostrar el personaje; vacía significa calma.
    """

    type: Literal["emotion"] = "emotion"
    components: list[EmotionComponent]


class VoiceQuota(BaseModel):
    """Créditos de voz según ElevenLabs.

    Attributes:
        tier: Plan contratado.
        used: Créditos usados en el periodo.
        limit: Créditos incluidos en el periodo.
        resets_at: Cuándo se renuevan, en segundos; `None` si no se conoce.
    """

    tier: str
    used: int
    limit: int
    resets_at: int | None = None


class ClaudeUsage(BaseModel):
    """Tokens que reportó Claude en una llamada.

    Attributes:
        input_tokens: Entrada sin caché.
        cache_write_tokens: Entrada guardada en caché.
        cache_read_tokens: Entrada leída de la caché.
        output_tokens: Salida.
        searches: Búsquedas web que hizo la API.
    """

    input_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0
    searches: int = 0


class SyncSettings(BaseModel):
    """Datos de conexión de la base en la nube.

    Attributes:
        database_url: Dirección de la base en Turso.
        auth_token: Clave secreta de esa base.
    """

    model_config = ConfigDict(frozen=True)

    database_url: str
    auth_token: str = Field(repr=False)


class UsageRecord(BaseModel):
    """Una llamada a una API, como se guarda en la memoria.

    Attributes:
        purpose: Para qué fue.
        input_tokens: Tokens de entrada, con y sin caché.
        output_tokens: Tokens de salida.
        searches: Búsquedas web.
        credits: Créditos de voz.
        cost_usd: Costo estimado en dólares; no incluye planes fijos.
    """

    purpose: UsagePurpose
    input_tokens: int = 0
    output_tokens: int = 0
    searches: int = 0
    credits: int = 0
    cost_usd: float = 0.0


class UsageDayRow(UsageRecord):
    """Gasto acumulado de un servicio en un día.

    Attributes:
        day: Fecha local en formato `YYYY-MM-DD`.
        calls: Número de llamadas.
    """

    day: str
    calls: int


class UsageDay(BaseModel):
    """Gasto de un día, para la gráfica.

    Attributes:
        day: Fecha local en formato `YYYY-MM-DD`.
        conversation: Dólares en conversación.
        memory: Dólares en recuerdos.
        search: Dólares en búsquedas.
    """

    day: str
    conversation: float
    memory: float
    search: float


class UsageServiceTotal(UsageRecord):
    """Gasto del mes de un servicio.

    Attributes:
        calls: Número de llamadas.
    """

    calls: int


class VisualProfileEvent(BaseModel):
    """Lo que muestra la vista de la memoria visual.

    Attributes:
        type: Discriminador del evento.
        trends: Costumbres con evidencia suficiente.
        observations: Observaciones, de la más nueva a la más antigua.
        min_observations: Cuántas se necesitan para hablar de una costumbre.
        face_enrolled: Si ya aprendió mi cara.
    """

    type: Literal["visual_profile"] = "visual_profile"
    trends: list[VisualTrend]
    observations: list[VisualRecord]
    min_observations: int
    face_enrolled: bool = False


class UsageEvent(BaseModel):
    """Todo lo que muestra la vista de gastos.

    Attributes:
        type: Discriminador del evento.
        today_usd: Gasto de hoy en Claude.
        month_usd: Gasto del mes en Claude.
        month_name: Mes del desglose, en formato `YYYY-MM`.
        days: Gasto de cada día reciente.
        services: Desglose del mes por servicio.
        voice: Créditos de voz, si se pudieron consultar.
    """

    type: Literal["usage"] = "usage"
    today_usd: float
    month_usd: float
    month_name: str
    days: list[UsageDay]
    services: list[UsageServiceTotal]
    voice: VoiceQuota | None = None


class ListenStateEvent(BaseModel):
    """En qué va la escucha del micrófono.

    Attributes:
        type: Discriminador del evento.
        state: Apagada, cargando, esperando que la llamen, oyendo, en plena conversación,
            transcribiendo o con error.
    """

    type: Literal["listen_state"] = "listen_state"
    state: Literal["off", "loading", "waiting", "hearing", "conversing", "transcribing", "error"]


class GreetingEvent(BaseModel):
    """Aviso de que Nova saluda porque la llamaron; empieza un turno y alza la mano.

    Attributes:
        type: Discriminador del evento.
    """

    type: Literal["greeting"] = "greeting"


class HeardEvent(BaseModel):
    """Lo que le pedí con la voz; empieza un turno.

    Attributes:
        type: Discriminador del evento.
        text: Petición transcrita.
    """

    type: Literal["heard"] = "heard"
    text: str


class SearchStartEvent(BaseModel):
    """Aviso de que Nova empezó a buscar en internet.

    Attributes:
        type: Discriminador del evento.
        query: Qué está buscando.
    """

    type: Literal["search_start"] = "search_start"
    query: str


class MoveEvent(BaseModel):
    """Pedido para que la ventana flotante se mueva.

    Attributes:
        type: Discriminador del evento.
        place: A dónde ir.
    """

    type: Literal["move"] = "move"
    place: MovePlace


class WriteStartEvent(BaseModel):
    """Aviso de que Nova empezó a escribir en la app al frente.

    Attributes:
        type: Discriminador del evento.
    """

    type: Literal["write_start"] = "write_start"


class WriteDoneEvent(BaseModel):
    """Aviso de que Nova dejó de escribir en la app al frente.

    Attributes:
        type: Discriminador del evento.
    """

    type: Literal["write_done"] = "write_done"


class SearchDoneEvent(BaseModel):
    """Aviso de que Nova terminó de buscar en internet.

    Attributes:
        type: Discriminador del evento.
        sources: Enlaces de donde salió la información; vacía si la búsqueda falló.
    """

    type: Literal["search_done"] = "search_done"
    sources: list[str] = Field(default_factory=list)


class PhotoRequestEvent(BaseModel):
    """Petición al navegador para que tome una foto.

    Attributes:
        type: Discriminador del evento.
        request_id: Identificador que debe devolver la respuesta.
        remaining: Fotos disponibles hoy, contando esta.
    """

    type: Literal["photo_request"] = "photo_request"
    request_id: str
    remaining: int


class GestureReactionEvent(BaseModel):
    """Aviso de que Nova empezó a reaccionar a un gesto, sin mensaje de por medio.

    Attributes:
        type: Discriminador del evento.
        gesture: Gesto al que reacciona.
    """

    type: Literal["gesture_reaction"] = "gesture_reaction"
    gesture: Gesture


class BrainLink(BaseModel):
    """Conexión entre dos recuerdos con significado parecido.

    Attributes:
        source: Identificador de un recuerdo.
        target: Identificador del otro recuerdo.
        strength: Qué tanto se parecen, de 0 a 1 aproximadamente.
    """

    source: int
    target: int
    strength: float


class BrainEvent(BaseModel):
    """Todo lo que muestra la vista del cerebro de Nova.

    Attributes:
        type: Discriminador del evento.
        memories: Recuerdos vigentes.
        links: Conexiones entre recuerdos.
        mood: Lo que siente Nova ahora.
    """

    type: Literal["brain"] = "brain"
    memories: list[Memory]
    links: list[BrainLink]
    mood: list[EmotionComponent]


class RecallEvent(BaseModel):
    """Aviso de qué recuerdos vinieron a la mente de Nova en este turno.

    Attributes:
        type: Discriminador del evento.
        memory_ids: Recuerdos que recuperó.
    """

    type: Literal["recall"] = "recall"
    memory_ids: list[int]


class HistoryMessage(BaseModel):
    """Un mensaje anterior para mostrar en el chat.

    Attributes:
        role: Quién lo escribió.
        text: Texto ya listo para mostrarse.
    """

    role: Literal["user", "assistant"]
    text: str


class HistoryEvent(BaseModel):
    """Conversación anterior, que se envía al navegador al conectarse.

    Attributes:
        type: Discriminador del evento.
        messages: Mensajes del más antiguo al más reciente.
        replace: Si debe sustituir lo que hay en pantalla, por ejemplo tras olvidar algo.
    """

    type: Literal["history"] = "history"
    messages: list[HistoryMessage]
    replace: bool = False


class InterruptedEvent(BaseModel):
    """Confirmación de que el turno se detuvo; lo que llegue después ya es de otro turno.

    Attributes:
        type: Discriminador del evento.
    """

    type: Literal["interrupted"] = "interrupted"


class DoneEvent(BaseModel):
    """Aviso de que el turno terminó correctamente.

    Attributes:
        type: Discriminador del evento.
    """

    type: Literal["done"] = "done"


class ErrorEvent(BaseModel):
    """Error que se le muestra al usuario.

    Attributes:
        type: Discriminador del evento.
        message: Texto del error, en español porque aparece en la interfaz.
    """

    type: Literal["error"] = "error"
    message: str


ServerEvent = (
    TokenEvent
    | BrainEvent
    | RecallEvent
    | HistoryEvent
    | EmotionEvent
    | PhotoRequestEvent
    | UsageEvent
    | ListenStateEvent
    | HeardEvent
    | GreetingEvent
    | SearchStartEvent
    | SearchDoneEvent
    | MoveEvent
    | VisualProfileEvent
    | WriteStartEvent
    | WriteDoneEvent
    | GestureReactionEvent
    | InterruptedEvent
    | DoneEvent
    | ErrorEvent
)

# Valida lo que llega del navegador y elige el modelo según el campo `type`.
CLIENT_REQUEST = TypeAdapter(
    Annotated[
        ChatRequestMessage
        | CalmRequest
        | PhotoResponse
        | InterruptRequest
        | GestureRequest
        | BrainRequest
        | UsageRequest
        | ListenRequest
        | MicGateRequest
        | ForgetMemoryRequest
        | VisualProfileRequest
        | ForgetVisualRequest
        | ForgetFaceRequest,
        Field(discriminator="type"),
    ]
)

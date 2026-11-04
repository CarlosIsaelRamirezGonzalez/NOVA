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
# Contrato común con las APIs de xAI
# ---------------------------------------------------------------------------
class AuthHeaders(BaseModel):
    """Cabeceras HTTP que requieren las APIs de xAI.

    Attributes:
        authorization: Valor de la cabecera `Authorization`.
        content_type: Valor de la cabecera `Content-Type`.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    authorization: str = Field(alias="Authorization")
    content_type: str = Field(default="application/json", alias="Content-Type")

    @classmethod
    def from_api_key(cls, api_key: str) -> "AuthHeaders":
        """Crea las cabeceras a partir de una clave de API.

        Args:
            api_key: Clave secreta de xAI.

        Returns:
            Las cabeceras listas para usarse en una petición.
        """
        return cls(authorization=f"Bearer {api_key}")


# ---------------------------------------------------------------------------
# API de chat (Grok)
# ---------------------------------------------------------------------------
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


class JsonSchemaFormat(BaseModel):
    """Esquema JSON al que debe ajustarse una respuesta estructurada.

    Attributes:
        name: Nombre del esquema.
        strict: Si la respuesta debe cumplirlo exactamente.
        json_schema: Esquema generado desde un modelo Pydantic.
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str
    strict: bool = True
    json_schema: JsonValue = Field(alias="schema")


class ResponseFormat(BaseModel):
    """Formato pedido para la respuesta del modelo.

    Attributes:
        type: Tipo de formato.
        json_schema: Esquema que debe cumplir.
    """

    type: Literal["json_schema"] = "json_schema"
    json_schema: JsonSchemaFormat


class ChatRequest(BaseModel):
    """Cuerpo de una petición a la API de chat.

    Attributes:
        model: Identificador del modelo de lenguaje.
        messages: Historial completo que recibirá el modelo.
        temperature: Grado de variación de las respuestas.
        stream: Si la respuesta debe llegar token por token.
        response_format: Formato estructurado de la respuesta, si se necesita.
    """

    model: str
    messages: list[ChatMessage]
    temperature: float
    stream: bool = True
    response_format: ResponseFormat | None = None


class CompletionMessage(BaseModel):
    """Mensaje de una respuesta completa de la API de chat.

    Attributes:
        content: Texto de la respuesta.
    """

    content: str = ""


class CompletionChoice(BaseModel):
    """Una alternativa de una respuesta completa.

    Attributes:
        message: Mensaje de esta alternativa.
    """

    message: CompletionMessage


class ChatCompletion(BaseModel):
    """Respuesta completa de la API de chat, sin stream.

    Attributes:
        choices: Alternativas de la respuesta.
    """

    choices: list[CompletionChoice]


class ChatDelta(BaseModel):
    """Fragmento de texto nuevo dentro de un evento del stream.

    Attributes:
        content: Texto generado; puede faltar en eventos de control.
    """

    content: str | None = None


class ChatChoice(BaseModel):
    """Una de las respuestas alternativas de un evento del stream.

    Attributes:
        delta: Fragmento de texto de esta alternativa.
    """

    delta: ChatDelta = Field(default_factory=ChatDelta)


class ChatStreamChunk(BaseModel):
    """Evento recibido del stream de la API de chat.

    Attributes:
        choices: Alternativas del evento; el último puede traer solo métricas.
    """

    choices: list[ChatChoice] = Field(default_factory=list)

    @property
    def text(self) -> str:
        """Devuelve el texto del evento.

        Returns:
            El texto de la primera alternativa, o una cadena vacía si no hay.
        """
        if not self.choices:
            return ""
        return self.choices[0].delta.content or ""


# ---------------------------------------------------------------------------
# API de voz (TTS)
# ---------------------------------------------------------------------------
class TtsOutputFormat(BaseModel):
    """Formato del audio que devuelve la API de voz.

    Attributes:
        container: Contenedor del archivo de audio.
    """

    container: Literal["mp3"] = "mp3"


class TtsRequest(BaseModel):
    """Cuerpo de una petición a la API de voz.

    Attributes:
        text: Texto que se va a pronunciar.
        voice_id: Identificador de la voz.
        language: Código del idioma.
        speed: Multiplicador de la velocidad de habla.
        output_format: Formato del audio de salida.
    """

    text: str
    voice_id: str
    language: str
    speed: float = Field(default=1.0, ge=0.7, le=1.5)
    output_format: TtsOutputFormat = Field(default_factory=TtsOutputFormat)


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
        forget_requested: Si Nova decidió olvidar algo porque Carlos se lo pidió.
    """

    text: str = ""
    blends: list[EmotionBlend] = Field(default_factory=list)
    photo_requested: bool = False
    forget_requested: bool = False


class ForgetDecision(BaseModel):
    """Lo que decide el modelo que resuelve qué quiere olvidar Carlos.

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


class StreamedReply(BaseModel):
    """Resultado de una llamada completa a Grok.

    Attributes:
        raw_text: Respuesta tal como llegó, con sus etiquetas.
        photo_requested: Si Nova pidió ver la cámara.
        forget_requested: Si Nova decidió olvidar algo.
    """

    raw_text: str = ""
    photo_requested: bool = False
    forget_requested: bool = False


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
class BrainRequest(BaseModel):
    """Petición del navegador para ver el cerebro de Nova.

    Attributes:
        type: Discriminador de la petición.
    """

    type: Literal["brain"] = "brain"


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
        | ForgetMemoryRequest,
        Field(discriminator="type"),
    ]
)

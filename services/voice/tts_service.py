"""Cliente de la API de voz de ElevenLabs."""

import re

from aiohttp import ClientSession

from services.context.usage_service import UsageService
from services.schemas import ElevenLabsHeaders, TtsRequest, VoiceQuota, VoiceSettings

API_URL = "https://api.elevenlabs.io/v1/text-to-speech"
OUTPUT_FORMAT = "mp3_44100_128"
SUBSCRIPTION_URL = "https://api.elevenlabs.io/v1/user/subscription"
# El modelo en vivo gasta medio crédito por carácter; se usa si la API no reporta el costo.
CREDITS_PER_CHARACTER = 0.5

# Gabriela: mexicana, de mediana edad, cálida. Se puede cambiar con `ELEVENLABS_VOICE_ID`.
DEFAULT_VOICE_ID = "hHjbwzYZW17oh0p05AKv"
# Baja latencia, para conversar en vivo, y admite etiquetas de audio.
DEFAULT_MODEL_ID = "eleven_v4_turbo"

# Solo pasan etiquetas de voz: otras podrían sonar como efectos, y el resto se leería en voz alta.
AUDIO_TAGS = frozenset(
    {"laughs", "sighs", "exhales", "whispers", "curious", "excited", "sarcastic", "crying"}
)
# El historial aún trae las marcas de la voz anterior: el modelo las puede imitar.
LEGACY_TAGS = (
    ("laugh", "laughs"),
    ("chuckle", "laughs"),
    ("giggle", "laughs"),
    ("sigh", "sighs"),
    ("exhale", "exhales"),
    ("cry", "crying"),
)
BRACKET_TAG = re.compile(r"\[([a-z -]+)\]")
ANGLE_TAG = re.compile(r"</?[a-z-]+>")
MARKDOWN = re.compile(r"[*#_`]+")


def _translate_tag(match: re.Match[str]) -> str:
    """Decide qué hacer con una etiqueta entre corchetes.

    Args:
        match: Etiqueta encontrada.

    Returns:
        La etiqueta válida, una pausa, o nada si no se puede pronunciar.
    """
    name = match.group(1)
    if name in ("pause", "long-pause"):
        return "..."
    name = next((new for old, new in LEGACY_TAGS if old == name), name)
    return f"[{name}]" if name in AUDIO_TAGS else ""


def prepare_speech(text: str) -> str:
    """Limpia un texto para que la voz no pronuncie marcas.

    Args:
        text: Frase tal como la escribió el modelo.

    Returns:
        La frase lista para la API de voz.
    """
    clean = ANGLE_TAG.sub("", text)
    clean = BRACKET_TAG.sub(_translate_tag, clean)
    return MARKDOWN.sub("", clean).strip()


def has_spoken_words(text: str) -> bool:
    """Comprueba que una frase tenga algo que pronunciar además de etiquetas.

    Args:
        text: Frase ya preparada para la voz.

    Returns:
        Si queda alguna letra o número fuera de las etiquetas.
    """
    return any(character.isalnum() for character in BRACKET_TAG.sub("", text))


class TTSService:
    """Convierte frases de texto en audio."""

    def __init__(
        self,
        api_key: str,
        voice_id: str = DEFAULT_VOICE_ID,
        model_id: str = DEFAULT_MODEL_ID,
        usage: UsageService | None = None,
    ) -> None:
        """Guarda los datos de conexión y la voz.

        Args:
            api_key: Clave secreta de ElevenLabs.
            voice_id: Identificador de la voz de Nova.
            model_id: Modelo de voz.
            usage: Registro de gastos; sin él, no se lleva la cuenta.
        """
        self.headers = ElevenLabsHeaders(xi_api_key=api_key)
        self.voice_id = voice_id
        self.model_id = model_id
        self.usage = usage

    async def text_to_audio(self, session: ClientSession, text: str, index: int) -> bytes | None:
        """Genera el audio de una frase.

        Los errores no se propagan: perder una frase es mejor que cortar la respuesta.

        Args:
            session: Sesión HTTP compartida.
            text: Frase que se va a pronunciar.
            index: Posición de la frase en la respuesta; solo se usa en los registros.

        Returns:
            El audio en MP3, o `None` si no se pudo generar.
        """
        request = TtsRequest(text=text, model_id=self.model_id, voice_settings=VoiceSettings())

        try:
            # aiohttp exige un mapping en las cabeceras: se convierte solo en este punto.
            async with session.post(
                f"{API_URL}/{self.voice_id}?output_format={OUTPUT_FORMAT}",
                data=request.model_dump_json(),
                headers=self.headers.model_dump(by_alias=True),
            ) as response:
                if response.status == 200:
                    audio = await response.read()
                    if self.usage:
                        reported = response.headers.get("character-cost", "")
                        estimated = round(len(text) * CREDITS_PER_CHARACTER)
                        self.usage.record_voice(int(reported) if reported.isdigit() else estimated)
                    return audio
                print(f"[TTS {response.status} on chunk {index}: {await response.text()}]")
        except Exception as error:
            print(f"[TTS failed on chunk {index}: {error}]")
        return None

    async def quota(self, session: ClientSession) -> VoiceQuota | None:
        """Consulta los créditos de voz en ElevenLabs.

        Args:
            session: Sesión HTTP compartida.

        Returns:
            Los créditos, o `None` si no se pudieron consultar.
        """
        try:
            # aiohttp exige un mapping en las cabeceras: se convierte solo en este punto.
            async with session.get(
                SUBSCRIPTION_URL, headers=self.headers.model_dump(by_alias=True)
            ) as response:
                if response.status != 200:
                    print(f"[TTS] quota error {response.status}", flush=True)
                    return None
                subscription = await response.json()
            return VoiceQuota(
                tier=subscription["tier"],
                used=subscription["character_count"],
                limit=subscription["character_limit"],
                resets_at=subscription.get("next_character_count_reset_unix"),
            )
        except Exception as error:
            print(f"[TTS] quota failed: {error}", flush=True)
            return None

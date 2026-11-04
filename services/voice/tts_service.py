"""Cliente de la API de voz de xAI."""

from aiohttp import ClientSession

from services.schemas import AuthHeaders, TtsRequest


class TTSService:
    """Convierte frases de texto en audio."""

    def __init__(
        self,
        api_key: str,
        api_url: str,
        voice_id: str = "aurora",
        language: str = "es-MX",
        speed: float = 1.15,
    ) -> None:
        """Guarda los datos de conexión y la voz.

        Args:
            api_key: Clave secreta de xAI.
            api_url: Dirección de la API de voz.
            voice_id: Identificador de la voz de Nova.
            language: Código del idioma en que habla.
            speed: Multiplicador de velocidad; a 1.0 esta voz suena a audiolibro.
        """
        self.headers = AuthHeaders.from_api_key(api_key)
        self.api_url = api_url
        self.voice_id = voice_id
        self.language = language
        self.speed = speed

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
        request = TtsRequest(
            text=text, voice_id=self.voice_id, language=self.language, speed=self.speed
        )

        try:
            # aiohttp exige un mapping en las cabeceras: se convierte solo en este punto.
            async with session.post(
                self.api_url,
                data=request.model_dump_json(),
                headers=self.headers.model_dump(by_alias=True),
            ) as response:
                if response.status == 200:
                    return await response.read()
                print(f"[TTS {response.status} on chunk {index}: {await response.text()}]")
        except Exception as error:
            print(f"[TTS failed on chunk {index}: {error}]")
        return None

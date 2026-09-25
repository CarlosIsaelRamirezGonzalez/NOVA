import io


class TTSService:
    def __init__(
        self, api_key: str, api_url: str, voice_id: str = "iris", language: str = "es"
    ):
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self.api_url = api_url
        self.voice_id = voice_id
        self.language = language

    async def text_to_audio(
        self, session, text: str, index: int
    ) -> tuple[int, io.BytesIO | None]:
        payload = {
            "text": text,
            "voice_id": self.voice_id,
            "language": self.language,
            "output_format": {"container": "mp3"},
        }

        try:
            async with session.post(
                self.api_url, json=payload, headers=self.headers
            ) as resp:
                if resp.status == 200:
                    audio_bytes = await resp.read()
                    return index, io.BytesIO(audio_bytes)
                else:
                    return index, None
        except Exception:
            return index, None

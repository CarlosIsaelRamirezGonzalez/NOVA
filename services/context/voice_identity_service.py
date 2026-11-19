"""Reconoce mi voz dentro del equipo. Las voces de otras personas no se guardan.

Usa WeSpeaker (ResNet34, entrenado con VoxCeleb) a través de sherpa-onnx. De cada petición dicha
en voz alta se saca una huella de la voz, se compara con la mía y se descarta. El audio nunca se
guarda; la huella de mi voz se queda en un archivo local, fuera de la base que va a la nube.
"""

import os
import threading
from pathlib import Path

import numpy as np
import sherpa_onnx

from services.schemas import VoiceCheck, VoiceEnrollment

MODEL_FILE = "wespeaker_en_voxceleb_resnet34_LM.onnx"
SAMPLE_RATE = 16000
# Con menos de esto la huella no es confiable: "sí" o "va" no dicen quién habla.
MIN_CHECK_SECONDS = 0.8
MIN_CLIP_SECONDS = 0.8
# Para aprenderla hace falta voz suficiente, repartida en una o varias frases.
MIN_ENROLL_SECONDS = 4.0
# Por encima de esto es la misma persona. Con mi voz real, las peticiones dieron 0.63 y 0.71 sin
# quitar silencios; otras voces humanas suelen quedar por debajo de 0.4. Como Nova solo me responde a
# mí, un umbral alto haría que me ignorara seguido. Cada comprobación registra su parecido.
SAME_SPEAKER_SIMILARITY = 0.5
# Los silencios antes y después de hablar no dicen nada de la voz y bajan el parecido. Se comparan
# contra el ruido del cuarto, no contra el pico de la frase: con el micrófono real, un golpe de voz
# dejaba fuera casi todo lo demás y Nova no alcanzaba a reconocerme.
FRAME_SAMPLES = 320
SILENCE_FLOOR = 0.003
NOISE_PERCENTILE = 20
NOISE_MARGIN = 3.0
# Se conservan unos tramos alrededor de la voz, donde van las consonantes suaves.
PADDING_FRAMES = 3
OWNER_ONLY = 0o600


class VoiceIdentityService:
    """Aprende y comprueba mi voz con un modelo que corre en la Mac."""

    def __init__(self, models_path: Path, profile_path: Path) -> None:
        """Guarda las rutas; el modelo se carga hasta que hace falta.

        Args:
            models_path: Carpeta con el modelo ONNX.
            profile_path: Archivo local con la huella de la voz.
        """
        self.models_path = models_path
        self.profile_path = profile_path
        self.extractor: sherpa_onnx.SpeakerEmbeddingExtractor | None = None
        # El micrófono y el servidor corren en hilos distintos: el modelo se usa de uno en uno.
        self.lock = threading.Lock()

    @property
    def is_available(self) -> bool:
        """Indica si el modelo está descargado.

        Returns:
            Si se pueden reconocer voces en este equipo.
        """
        return (self.models_path / MODEL_FILE).exists()

    @property
    def is_enrolled(self) -> bool:
        """Indica si ya aprendió mi voz.

        Returns:
            Si existe la huella.
        """
        return self.profile_path.exists()

    def load(self) -> None:
        """Carga el modelo la primera vez; tarda menos de un segundo."""
        with self.lock:
            if self.extractor is None:
                config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                    model=str(self.models_path / MODEL_FILE), num_threads=2, provider="cpu"
                )
                self.extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)

    @staticmethod
    def voiced(samples: np.ndarray) -> np.ndarray:
        """Se queda solo con los tramos donde alguien habla.

        Args:
            samples: Audio de 16 kHz, mono, en flotantes de -1 a 1.

        Returns:
            El audio sin los tramos de silencio, en 20 ms por tramo.
        """
        frames = samples[: samples.size // FRAME_SAMPLES * FRAME_SAMPLES].reshape(-1, FRAME_SAMPLES)
        if not frames.size:
            return samples
        levels = np.sqrt(np.mean(frames**2, axis=1))
        noise = float(np.percentile(levels, NOISE_PERCENTILE))
        loud = levels >= max(SILENCE_FLOOR, noise * NOISE_MARGIN)
        window = np.ones(2 * PADDING_FRAMES + 1)
        keep = np.convolve(loud.astype(float), window, mode="same") > 0
        return frames[keep].reshape(-1)

    def speech(self, samples: np.ndarray) -> np.ndarray:
        """Elige qué audio comparar: sin silencios si queda suficiente, o completo si no.

        Args:
            samples: Audio de la frase.

        Returns:
            El audio que se va a comparar.
        """
        voiced = self.voiced(samples)
        return voiced if voiced.size >= MIN_CLIP_SECONDS * SAMPLE_RATE else samples

    def embed(self, samples: np.ndarray) -> np.ndarray | None:
        """Calcula la huella de una voz. Solo vive en memoria mientras se compara.

        Args:
            samples: Audio de 16 kHz, mono, en flotantes de -1 a 1.

        Returns:
            El vector normalizado, o `None` si hay muy poca voz.
        """
        samples = self.speech(samples)
        if samples.size < MIN_CLIP_SECONDS * SAMPLE_RATE:
            return None
        self.load()
        with self.lock:
            stream = self.extractor.create_stream()
            stream.accept_waveform(sample_rate=SAMPLE_RATE, waveform=samples.astype(np.float32))
            stream.input_finished()
            if not self.extractor.is_ready(stream):
                return None
            vector = np.asarray(self.extractor.compute(stream), dtype=np.float32)
        return vector / np.linalg.norm(vector)

    def enroll(self, clips: list[np.ndarray]) -> VoiceEnrollment:
        """Aprende mi voz a partir de frases que dije en voz alta.

        Args:
            clips: Audio de cada frase.

        Returns:
            Si la aprendió y con cuántos segundos de voz.
        """
        if not self.is_available:
            return VoiceEnrollment(status="unavailable")
        vectors: list[np.ndarray] = []
        seconds = 0.0
        for clip in clips:
            vector = self.embed(clip)
            if vector is not None:
                vectors.append(vector)
                seconds += self.speech(clip).size / SAMPLE_RATE
        if seconds < MIN_ENROLL_SECONDS:
            return VoiceEnrollment(status="too_short", seconds_used=round(seconds, 1))

        mean = np.mean(vectors, axis=0)
        self._save(mean / np.linalg.norm(mean))
        return VoiceEnrollment(status="learned", seconds_used=round(seconds, 1))

    def _save(self, vector: np.ndarray) -> None:
        """Guarda la huella en un archivo que solo puede leer tu usuario.

        Args:
            vector: Huella normalizada.
        """
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.profile_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, OWNER_ONLY)
        with os.fdopen(descriptor, "wb") as file:
            np.save(file, vector)

    def check(self, samples: np.ndarray) -> VoiceCheck | None:
        """Comprueba si soy yo quien habla. La huella de esa voz no se conserva.

        Args:
            samples: Audio de la petición.

        Returns:
            Si soy yo, o `None` si no conoce mi voz o la frase fue muy corta para saberlo.
        """
        if not self.is_enrolled or not self.is_available:
            return None
        heard = samples.size / SAMPLE_RATE
        voiced = self.voiced(samples).size / SAMPLE_RATE
        if self.speech(samples).size < MIN_CHECK_SECONDS * SAMPLE_RATE:
            print(f"[Voice] too short to tell: {voiced:.1f} s of voice in {heard:.1f} s", flush=True)
            return None
        vector = self.embed(samples)
        if vector is None:
            return None
        similarity = float(np.dot(np.load(self.profile_path), vector))
        print(f"[Voice] compared {voiced:.1f} s of voice in {heard:.1f} s", flush=True)
        return VoiceCheck(
            carlos_speaking=similarity >= SAME_SPEAKER_SIMILARITY, similarity=round(similarity, 3)
        )

    def forget(self) -> bool:
        """Borra la huella de la voz para siempre.

        Returns:
            Si había una.
        """
        if not self.is_enrolled:
            return False
        self.profile_path.unlink()
        return True

"""Reconoce sonidos del cuarto que merecen un vistazo: golpes, vidrios, gritos, alarmas.

Usa CED-tiny (AudioSet, 527 sonidos) a través de sherpa-onnx, dentro de la Mac. Cada segundo revisa
los dos últimos segundos del micrófono. El audio no se guarda ni sale del equipo: solo se avisa el
nombre del sonido.
"""

from collections.abc import Callable
from pathlib import Path

import numpy as np
import sherpa_onnx

from services.schemas import SoundEvent

MODEL_FILE = "model.int8.onnx"
LABELS_FILE = "class_labels_indices.csv"
SAMPLE_RATE = 16000
WINDOW_SAMPLES = 2 * SAMPLE_RATE
HOP_SAMPLES = SAMPLE_RATE
TOP_K = 5
MIN_PROBABILITY = 0.4
# Solo estos ameritan mirar. La voz, la música o el teclado son parte de un día normal.
ALERT_SOUNDS = frozenset(
    {
        "Shout",
        "Yell",
        "Screaming",
        "Crying, sobbing",
        "Bark",
        "Car alarm",
        "Doorbell",
        "Slam",
        "Knock",
        "Alarm",
        "Siren",
        "Smoke detector, smoke alarm",
        "Fire alarm",
        "Explosion",
        "Gunshot, gunfire",
        "Glass",
        "Shatter",
        "Thump, thud",
        "Bang",
        "Smash, crash",
        "Breaking",
    }
)

SoundHandler = Callable[[SoundEvent], None]


class SoundEventService:
    """Escucha el audio del micrófono y avisa cuando oye algo fuera de lo normal."""

    def __init__(self, models_path: Path, on_event: SoundHandler) -> None:
        """Guarda la ruta; el modelo se carga hasta que llega el primer audio.

        Args:
            models_path: Carpeta con el modelo y sus etiquetas.
            on_event: Recibe cada sonido de alerta, desde el hilo del micrófono.
        """
        self.models_path = models_path
        self.on_event = on_event
        self.tagger: sherpa_onnx.AudioTagging | None = None
        self.buffer = np.zeros(0, dtype=np.float32)
        self.pending_samples = 0

    @property
    def is_available(self) -> bool:
        """Indica si el modelo está descargado.

        Returns:
            Si se pueden reconocer sonidos en este equipo.
        """
        return (self.models_path / MODEL_FILE).exists() and (self.models_path / LABELS_FILE).exists()

    def _load(self) -> None:
        """Carga el modelo la primera vez; tarda una fracción de segundo."""
        if self.tagger is None:
            config = sherpa_onnx.AudioTaggingConfig(
                model=sherpa_onnx.AudioTaggingModelConfig(
                    ced=str(self.models_path / MODEL_FILE), num_threads=1
                ),
                labels=str(self.models_path / LABELS_FILE),
                top_k=TOP_K,
            )
            self.tagger = sherpa_onnx.AudioTagging(config)

    def reset(self) -> None:
        """Olvida el audio acumulado, por ejemplo mientras Nova habla."""
        self.buffer = np.zeros(0, dtype=np.float32)
        self.pending_samples = 0

    def feed(self, pcm: bytes) -> None:
        """Recibe un bloque del micrófono y, cada segundo, revisa lo último que se oyó.

        Args:
            pcm: Audio de 16 kHz, mono, en enteros de 16 bits.
        """
        if not self.is_available:
            return
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        self.buffer = np.concatenate([self.buffer, samples])[-WINDOW_SAMPLES:]
        self.pending_samples += samples.size
        if self.buffer.size < WINDOW_SAMPLES or self.pending_samples < HOP_SAMPLES:
            return
        self.pending_samples = 0
        event = self.classify(self.buffer)
        if event:
            self.on_event(event)

    def classify(self, samples: np.ndarray) -> SoundEvent | None:
        """Busca el sonido de alerta más probable en un tramo de audio.

        Args:
            samples: Audio de 16 kHz en flotantes de -1 a 1.

        Returns:
            El sonido, o `None` si no hay nada fuera de lo normal.
        """
        self._load()
        stream = self.tagger.create_stream()
        stream.accept_waveform(SAMPLE_RATE, samples)
        alerts = [
            event
            for event in self.tagger.compute(stream)
            if event.name in ALERT_SOUNDS and event.prob >= MIN_PROBABILITY
        ]
        if not alerts:
            return None
        best = max(alerts, key=lambda event: event.prob)
        return SoundEvent(label=best.name, probability=round(float(best.prob), 2))

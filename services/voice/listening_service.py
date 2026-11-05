"""Escucha cuando llaman a Nova con el micrófono y transcribe lo que Carlos pide, todo dentro del equipo.

El audio nunca sale de la computadora ni se guarda: solo el texto transcrito llega al modelo.
"""

import json
import queue
import re
import threading
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import numpy as np
import sounddevice
import vosk
from pywhispercpp.model import Model as WhisperModel

SAMPLE_RATE = 16000
BYTES_PER_SECOND = SAMPLE_RATE * 2
BLOCK_SAMPLES = 1600

# Con solo la frase, Vosk la "oía" en casi cualquier cosa: las palabras parecidas le dan otra opción.
WAKE_GRAMMAR = json.dumps(
    ["oye nova", "oye", "nova", "nueva", "nuevo", "noah", "no", "va", "hoy", "hoy no va", "o", "y",
     "a", "la", "el", "que", "me", "voy", "se", "es", "de", "en", "un", "una", "no va", "nada",
     "onda", "[unk]"]
)
MIN_WORD_CONFIDENCE = 0.5
# Basta su nombre, siempre que sea lo primero que se dice; "la bossa nova" no la llama.
MIN_NAME_CONFIDENCE = 0.5
MAX_GAP_BETWEEN_WORDS_SECONDS = 0.35

# Cuándo se da por terminado lo que Carlos dice.
END_SILENCE_SECONDS = 1.0
NO_SPEECH_TIMEOUT_SECONDS = 6.0
# Después de que Nova responde, se puede seguir hablando sin volver a llamarla.
CONVERSATION_SECONDS = 20.0
MAX_COMMAND_SECONDS = 20.0
MIN_COMMAND_SECONDS = 0.4
# El umbral sigue al ruido de la habitación, para no confundirlo con voz.
NOISE_MARGIN = 3.0
MIN_SPEECH_LEVEL = 300.0
NOISE_ADAPTATION = 0.05

# Whisper reconoce mejor el nombre si se lo anticipan.
WHISPER_HINT = "Conversación con Nova, una asistente mexicana."
# Whisper inventa estas frases cuando en realidad no se dijo nada.
PHANTOM_PHRASES = ("gracias por ver", "suscríbete", "subtítulos", "amara.org", "[música]", "(música)")
# Whisper escribe "Nova" de varias formas; se quita la frase del inicio para quedarse con la petición.
WAKE_IN_TEXT = re.compile(
    r"^\W*(?:(?:oye|hoy|y)\b[\s,]*(?:es\s+|en\s+)?)?(?:no\s?va|nueva|nova)\b[\s.,:;!?¡¿-]*",
    re.IGNORECASE,
)
# En plena conversación solo se quita si es claro: "hoy no va a llover" es una frase normal.
CLEAR_WAKE_IN_TEXT = re.compile(r"^\W*(?:oye\b[\s,]*)?nova\b[\s.,:;!?¡¿-]*", re.IGNORECASE)

ListenState = Literal["off", "loading", "waiting", "hearing", "conversing", "transcribing", "error"]
StateHandler = Callable[[ListenState], None]
TextHandler = Callable[[str], None]


def is_phantom(text: str) -> bool:
    """Reconoce una transcripción vacía o inventada a partir de silencio o ruido.

    Args:
        text: Texto transcrito.

    Returns:
        Si hay que descartarla, para no gastar un turno en algo que no se dijo.
    """
    clean = text.strip().lower()
    has_letters = any(character.isalpha() for character in clean)
    return not has_letters or any(phrase in clean for phrase in PHANTOM_PHRASES)


def remove_wake_phrase(text: str) -> str | None:
    """Quita "Oye Nova" del inicio de una transcripción.

    Args:
        text: Lo que transcribió Whisper.

    Returns:
        La petición, o `None` si en realidad decía "oye, no va a...", que Vosk confunde con la frase.
    """
    match = WAKE_IN_TEXT.match(text)
    if not match:
        return text.strip()
    rest = text[match.end() :]
    return None if rest.lower().startswith("a ") else rest.strip()


class ListeningService:
    """Máquina de estados: esperar que la llamen, oír, transcribir y seguir la conversación."""

    def __init__(
        self,
        wake_model_path: Path,
        whisper_model_path: Path,
        on_state: StateHandler,
        on_text: TextHandler,
    ) -> None:
        """Guarda la configuración; los modelos se cargan hasta que se encienda.

        Args:
            wake_model_path: Carpeta del modelo de Vosk.
            whisper_model_path: Archivo del modelo de Whisper.
            on_state: Recibe cada cambio de estado, desde otro hilo.
            on_text: Recibe cada petición transcrita, desde otro hilo.
        """
        self.wake_model_path = wake_model_path
        self.whisper_model_path = whisper_model_path
        self.on_state = on_state
        self.on_text = on_text
        self.state: ListenState = "off"
        self.gate_open = True
        self.audio: queue.Queue[bytes | None] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.wake_model: vosk.Model | None = None
        self.whisper: WhisperModel | None = None
        self.conversation_pending = False
        self.silence_limit = NO_SPEECH_TIMEOUT_SECONDS
        self.noise_level = MIN_SPEECH_LEVEL / NOISE_MARGIN
        self._reset()

    def _reset(self) -> None:
        """Olvida el audio acumulado y vuelve a esperar la frase desde cero."""
        self.recognizer: vosk.KaldiRecognizer | None = None
        self.stream_audio = bytearray()
        self.command = bytearray()
        self.heard_speech = False
        self.silent_bytes = 0

    def _set_state(self, state: ListenState) -> None:
        """Cambia de estado y avisa.

        Args:
            state: Estado nuevo.
        """
        if state != self.state:
            self.state = state
            self.on_state(state)

    def load_models(self) -> None:
        """Carga los modelos, una sola vez: tardan unos segundos."""
        if self.wake_model is None:
            vosk.SetLogLevel(-1)
            self.wake_model = vosk.Model(str(self.wake_model_path))
        if self.whisper is None:
            self.whisper = WhisperModel(
                str(self.whisper_model_path),
                print_realtime=False,
                print_progress=False,
                redirect_whispercpp_logs_to=None,
            )

    def start(self) -> None:
        """Enciende el micrófono en otro hilo. No hace nada si ya está encendido."""
        if self.worker and self.worker.is_alive():
            return
        self.worker = threading.Thread(target=self._run, name="nova-listening", daemon=True)
        self.worker.start()

    def stop(self) -> None:
        """Apaga el micrófono y descarta el audio pendiente."""
        if self.worker and self.worker.is_alive():
            self.audio.put(None)
            self.worker.join(timeout=5)
        self.worker = None

    def set_gate(self, is_open: bool) -> None:
        """Abre o cierra el paso del audio; se cierra mientras Nova habla, para que no se oiga.

        Args:
            is_open: Si se puede escuchar ahora.
        """
        self.gate_open = is_open

    def feed(self, pcm: bytes) -> None:
        """Procesa un bloque de audio. Las pruebas lo usan sin tocar el micrófono.

        Args:
            pcm: Audio de 16 kHz, mono, en enteros de 16 bits.
        """
        if not self.gate_open or self.state == "transcribing":
            # Lo que se oyó mientras Nova hablaba no debe contar como parte de la petición.
            if self.state in ("hearing", "conversing", "waiting"):
                # Si estaban platicando, la conversación sigue cuando ella termine de responder.
                self.conversation_pending = self.conversation_pending or self.state == "conversing"
                self._reset()
                self._set_state("waiting")
            return

        # Nova acaba de responder: ya no hace falta llamarla para seguir platicando.
        if self.conversation_pending:
            self.conversation_pending = False
            self._reset()
            self.silence_limit = CONVERSATION_SECONDS
            self._set_state("conversing")

        if self.state in ("hearing", "conversing"):
            self._hear_command(pcm)
        else:
            self._wait_for_wake(pcm)

    def _wait_for_wake(self, pcm: bytes) -> None:
        """Busca la frase en el audio.

        Args:
            pcm: Bloque de audio.
        """
        if self.recognizer is None:
            self.recognizer = vosk.KaldiRecognizer(self.wake_model, SAMPLE_RATE, WAKE_GRAMMAR)
            self.recognizer.SetWords(True)
            self.stream_audio = bytearray()
        self.stream_audio += pcm

        # El reconocedor avisa al detectar una pausa; solo entonces hay palabras con su confianza.
        if not self.recognizer.AcceptWaveform(pcm):
            # Solo se conserva lo necesario para recortar una petición dicha de corrido.
            limit = int(MAX_COMMAND_SECONDS * BYTES_PER_SECOND)
            if len(self.stream_audio) > limit:
                self.recognizer = None
            return

        words = json.loads(self.recognizer.Result()).get("result", [])
        wake_end = self._wake_end(words)
        heard = bytes(self.stream_audio)
        self.recognizer = None
        if wake_end is None:
            return

        # Si dijo la petición de corrido, se transcribe todo: recortar por tiempo se comía palabras.
        command = heard[int(wake_end * BYTES_PER_SECOND) & ~1 :]
        if self._has_speech(command):
            self._finish_command(heard, includes_wake_phrase=True)
        else:
            self.command = bytearray()
            self.heard_speech = False
            self.silent_bytes = 0
            self.silence_limit = NO_SPEECH_TIMEOUT_SECONDS
            self._set_state("hearing")

    @staticmethod
    def _wake_end(words: list[object]) -> float | None:
        """Busca la frase entre las palabras reconocidas.

        Args:
            words: Palabras con su confianza y sus tiempos, tal como las entrega Vosk.

        Returns:
            El segundo en que termina la frase, o `None` si no se dijo.
        """
        # Solo el nombre, al inicio de lo que se dijo: "la bossa nova" no la llama.
        if words and words[0]["word"] == "nova" and words[0]["conf"] >= MIN_NAME_CONFIDENCE:
            return words[0]["end"]

        for first, second in zip(words, words[1:]):
            is_phrase = first["word"] == "oye" and second["word"] == "nova"
            is_sure = min(first["conf"], second["conf"]) >= MIN_WORD_CONFIDENCE
            is_together = second["start"] - first["end"] < MAX_GAP_BETWEEN_WORDS_SECONDS
            if is_phrase and is_sure and is_together:
                return second["end"]
        return None

    def _is_speech(self, pcm: bytes) -> bool:
        """Decide si un bloque tiene voz y ajusta el nivel de ruido de la habitación.

        Args:
            pcm: Bloque de audio.

        Returns:
            Si el volumen supera claramente el ruido.
        """
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        level = float(np.sqrt(np.mean(samples**2))) if samples.size else 0.0
        threshold = max(MIN_SPEECH_LEVEL, self.noise_level * NOISE_MARGIN)
        if level < threshold:
            self.noise_level += (level - self.noise_level) * NOISE_ADAPTATION
            return False
        return True

    def _has_speech(self, pcm: bytes) -> bool:
        """Revisa si un audio contiene suficiente voz para ser una petición.

        Args:
            pcm: Audio completo.

        Returns:
            Si dura lo mínimo con voz.
        """
        block = BLOCK_SAMPLES * 2
        blocks = [pcm[index : index + block] for index in range(0, len(pcm), block)]
        voiced = sum(block_size == block and self._is_speech(part)
                     for part, block_size in ((part, len(part)) for part in blocks))
        return voiced * block / BYTES_PER_SECOND >= MIN_COMMAND_SECONDS

    def _hear_command(self, pcm: bytes) -> None:
        """Graba la petición hasta que Carlos deje de hablar.

        Args:
            pcm: Bloque de audio.
        """
        self.command += pcm
        if self._is_speech(pcm):
            self.heard_speech = True
            self.silent_bytes = 0
        else:
            self.silent_bytes += len(pcm)

        seconds = len(self.command) / BYTES_PER_SECOND
        silence = self.silent_bytes / BYTES_PER_SECOND

        # Nadie dijo nada: no se gasta nada, y hay que volver a llamarla.
        if not self.heard_speech and seconds >= self.silence_limit:
            self._reset()
            self._set_state("waiting")
        elif self.heard_speech and (silence >= END_SILENCE_SECONDS or seconds >= MAX_COMMAND_SECONDS):
            self._finish_command(bytes(self.command))

    def _finish_command(self, pcm: bytes, includes_wake_phrase: bool = False) -> None:
        """Transcribe la petición y la entrega, si de verdad se dijo algo.

        Args:
            pcm: Audio de la petición.
            includes_wake_phrase: Si el audio empieza con "Oye Nova".
        """
        self._set_state("transcribing")
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments = self.whisper.transcribe(samples, language="es", initial_prompt=WHISPER_HINT)
        text: str | None = " ".join(segment.text.strip() for segment in segments).strip()
        if includes_wake_phrase:
            text = remove_wake_phrase(text)
        else:
            text = CLEAR_WAKE_IN_TEXT.sub("", text).strip()
        self._reset()
        self._set_state("waiting")
        if not text or is_phantom(text):
            print("[Listen] nothing clear was said", flush=True)
            return
        self.conversation_pending = True
        self.on_text(text)

    def _run(self) -> None:
        """Abre el micrófono y procesa su audio hasta que se apague."""
        self.audio = queue.Queue()
        self._reset()
        try:
            self._set_state("loading")
            self.load_models()

            def capture(data: object, _frames: int, _time: object, _status: object) -> None:
                """Recibe audio del sistema; solo lo encola para no retrasar la captura.

                Args:
                    data: Bloque de audio.
                    _frames: Muestras del bloque.
                    _time: Marcas de tiempo.
                    _status: Avisos del sistema de audio.
                """
                self.audio.put(bytes(data))

            with sounddevice.RawInputStream(
                samplerate=SAMPLE_RATE,
                blocksize=BLOCK_SAMPLES,
                dtype="int16",
                channels=1,
                callback=capture,
            ):
                self._set_state("waiting")
                while (block := self.audio.get()) is not None:
                    self.feed(block)
            self._set_state("off")
        except Exception:
            traceback.print_exc()
            self._set_state("error")

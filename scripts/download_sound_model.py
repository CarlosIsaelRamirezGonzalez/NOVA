"""Descarga el modelo que reconoce sonidos del cuarto y comprueba que llegó íntegro.

Se ejecuta una vez: `.venv/bin/python scripts/download_sound_model.py`.
Es CED-tiny entrenado con AudioSet (527 sonidos), publicado por sherpa-onnx (licencia Apache 2.0).
Solo se instala la versión cuantizada (6 MB) y la lista de sonidos.
"""

import hashlib
import io
import ssl
import tarfile
import urllib.request
from pathlib import Path

import certifi

MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/audio-tagging-models/"
    "sherpa-onnx-ced-tiny-audio-tagging-2024-04-19.tar.bz2"
)
MODEL_SHA256 = "84baf315b57d61aa69480c4fee878dab54cbc7be3e877db334e65d8b087e23c3"
ARCHIVE_FOLDER = "sherpa-onnx-ced-tiny-audio-tagging-2024-04-19"
MODEL_FILES = ("model.int8.onnx", "class_labels_indices.csv")
TARGET = Path(__file__).resolve().parents[1] / "data" / "models" / "sound"


def main() -> None:
    """Descarga el paquete, revisa su huella y extrae solo el modelo y sus etiquetas.

    Raises:
        SystemExit: Si el archivo no es el esperado.
    """
    # El Python de macOS no trae certificados: se usan los de certifi, como en el resto de Nova.
    context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(MODEL_URL, timeout=180, context=context) as response:
        package = response.read()
    if hashlib.sha256(package).hexdigest() != MODEL_SHA256:
        raise SystemExit("El archivo descargado no coincide con el esperado; no se instaló nada.")

    TARGET.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(package), mode="r:bz2") as archive:
        for name in MODEL_FILES:
            member = archive.extractfile(f"{ARCHIVE_FOLDER}/{name}")
            (TARGET / name).write_bytes(member.read())
    print(f"Modelo instalado en {TARGET}")


if __name__ == "__main__":
    main()

"""Descarga el modelo que reconoce tu voz y comprueba que llegó íntegro.

Se ejecuta una vez: `.venv/bin/python scripts/download_voice_model.py`.
Es WeSpeaker ResNet34 entrenado con VoxCeleb, publicado por sherpa-onnx (licencia Apache 2.0).
"""

import hashlib
import ssl
import urllib.request
from pathlib import Path

import certifi

MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
    "wespeaker_en_voxceleb_resnet34_LM.onnx"
)
MODEL_SHA256 = "e9848563da86f263117134dfd7ad63c92355b37de492b55e325400c9d9c39012"
TARGET = Path(__file__).resolve().parents[1] / "data" / "models" / "voice"
MODEL_FILE = "wespeaker_en_voxceleb_resnet34_LM.onnx"


def main() -> None:
    """Descarga el modelo, revisa su huella y lo guarda.

    Raises:
        SystemExit: Si el archivo no es el esperado.
    """
    # El Python de macOS no trae certificados: se usan los de certifi, como en el resto de Nova.
    context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(MODEL_URL, timeout=120, context=context) as response:
        model = response.read()
    if hashlib.sha256(model).hexdigest() != MODEL_SHA256:
        raise SystemExit("El archivo descargado no coincide con el esperado; no se instaló nada.")

    TARGET.mkdir(parents=True, exist_ok=True)
    (TARGET / MODEL_FILE).write_bytes(model)
    print(f"Modelo instalado en {TARGET}")


if __name__ == "__main__":
    main()

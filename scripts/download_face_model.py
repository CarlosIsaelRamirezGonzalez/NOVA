"""Descarga el modelo que reconoce tu cara y comprueba que llegó íntegro.

Se ejecuta una vez: `.venv/bin/python scripts/download_face_model.py`.
Los modelos preentrenados de InsightFace son solo para uso no comercial.
"""

import hashlib
import io
import urllib.request
import zipfile
from pathlib import Path

MODEL_URL = "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_sc.zip"
MODEL_SHA256 = "57d31b56b6ffa911c8a73cfc1707c73cab76efe7f13b675a05223bf42de47c72"
TARGET = Path(__file__).resolve().parents[1] / "data" / "models" / "face"
MODEL_FILES = ("det_500m.onnx", "w600k_mbf.onnx")


def main() -> None:
    """Descarga el paquete, revisa su huella y extrae solo los dos modelos.

    Raises:
        SystemExit: Si el archivo no es el esperado.
    """
    with urllib.request.urlopen(MODEL_URL, timeout=120) as response:
        package = response.read()
    if hashlib.sha256(package).hexdigest() != MODEL_SHA256:
        raise SystemExit("El archivo descargado no coincide con el esperado; no se instaló nada.")

    TARGET.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        for name in MODEL_FILES:
            (TARGET / name).write_bytes(archive.read(name))
    print(f"Modelos instalados en {TARGET}")


if __name__ == "__main__":
    main()

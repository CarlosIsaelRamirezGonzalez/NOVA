"""Reconoce mi cara dentro del equipo. Las caras de otras personas no se guardan.

La huella de mi cara se queda en un archivo local, fuera de la base que se sincroniza con la nube.
"""

import base64
import io
import os
from pathlib import Path

import numpy as np
import onnxruntime
from PIL import Image

from services.schemas import FaceCheck, FaceDetection, FaceEnrollment

DETECTOR_FILE = "det_500m.onnx"
RECOGNIZER_FILE = "w600k_mbf.onnx"
DETECTOR_SIZE = 640
STRIDES = (8, 16, 32)
ANCHORS_PER_CELL = 2
MIN_DETECTION_SCORE = 0.5
MIN_ENROLL_SCORE = 0.7
NMS_IOU = 0.4
# Por encima de esto es la misma persona. Se prefiere no reconocerlo a confundirlo con otra.
SAME_PERSON_SIMILARITY = 0.4
# Una cara muy pequeña no da una huella confiable para aprenderla.
MIN_ENROLL_FACE_PIXELS = 80
MIN_ENROLL_PHOTOS = 2
# Dónde espera el modelo los ojos, la nariz y las comisuras, en una imagen de 112 × 112.
ALIGNED_SIZE = 112
ALIGNED_POINTS = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)
OWNER_ONLY = 0o600


def decode_photo(data_url: str) -> Image.Image:
    """Convierte una foto recibida en una imagen.

    Args:
        data_url: Foto como data URL.

    Returns:
        La imagen en RGB.
    """
    _, _, encoded = data_url.partition(",")
    return Image.open(io.BytesIO(base64.b64decode(encoded))).convert("RGB")


def similarity_transform(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Calcula la rotación, escala y traslación que mejor lleva unos puntos a otros (Umeyama).

    Args:
        source: Puntos de origen, de forma (N, 2).
        target: Puntos de destino, de forma (N, 2).

    Returns:
        La matriz de 2 × 3.
    """
    source_center = source.mean(axis=0)
    target_center = target.mean(axis=0)
    source_rest = source - source_center
    target_rest = target - target_center
    covariance = target_rest.T @ source_rest / len(source)
    left, singular, right = np.linalg.svd(covariance)
    reflection = np.diag([1.0, float(np.sign(np.linalg.det(left) * np.linalg.det(right)) or 1.0)])
    rotation = left @ reflection @ right
    scale = float(np.sum(singular * np.diag(reflection))) / float(source_rest.var(axis=0).sum())
    translation = target_center - scale * rotation @ source_center
    return np.column_stack([scale * rotation, translation])


class FaceIdentityService:
    """Aprende y comprueba mi cara con modelos que corren en la Mac."""

    def __init__(self, models_path: Path, profile_path: Path) -> None:
        """Guarda las rutas; los modelos se cargan hasta que hacen falta.

        Args:
            models_path: Carpeta con los modelos ONNX.
            profile_path: Archivo local con la huella de la cara.
        """
        self.models_path = models_path
        self.profile_path = profile_path
        self.detector: onnxruntime.InferenceSession | None = None
        self.recognizer: onnxruntime.InferenceSession | None = None

    @property
    def is_available(self) -> bool:
        """Indica si los modelos están descargados.

        Returns:
            Si se puede reconocer caras en este equipo.
        """
        return (self.models_path / DETECTOR_FILE).exists() and (
            self.models_path / RECOGNIZER_FILE
        ).exists()

    @property
    def is_enrolled(self) -> bool:
        """Indica si ya aprendió mi cara.

        Returns:
            Si existe la huella.
        """
        return self.profile_path.exists()

    def _load(self) -> None:
        """Carga los modelos la primera vez que se necesitan."""
        if self.detector is not None:
            return
        providers = ["CPUExecutionProvider"]
        self.detector = onnxruntime.InferenceSession(
            str(self.models_path / DETECTOR_FILE), providers=providers
        )
        self.recognizer = onnxruntime.InferenceSession(
            str(self.models_path / RECOGNIZER_FILE), providers=providers
        )

    def detect(self, image: Image.Image) -> list[FaceDetection]:
        """Busca las caras de una imagen.

        Args:
            image: Imagen en RGB.

        Returns:
            Las caras, en coordenadas de la imagen original.
        """
        self._load()

        # El detector usa un lienzo cuadrado: se reduce la imagen sin deformarla y se rellena.
        scale = DETECTOR_SIZE / max(image.size)
        resized = image.resize((round(image.width * scale), round(image.height * scale)))
        canvas = np.zeros((DETECTOR_SIZE, DETECTOR_SIZE, 3), dtype=np.float32)
        canvas[: resized.height, : resized.width] = np.asarray(resized, dtype=np.float32)
        blob = ((canvas - 127.5) / 128.0).transpose(2, 0, 1)[None]
        outputs = self.detector.run(None, {self.detector.get_inputs()[0].name: blob})

        boxes: list[np.ndarray] = []
        scores: list[np.ndarray] = []
        points: list[np.ndarray] = []
        for index, stride in enumerate(STRIDES):
            size = DETECTOR_SIZE // stride
            rows, columns = np.mgrid[:size, :size]
            centers = np.stack([columns, rows], axis=-1).reshape(-1, 2).astype(np.float32) * stride
            centers = np.repeat(centers, ANCHORS_PER_CELL, axis=0)
            level_scores = outputs[index].reshape(-1)
            keep = level_scores > MIN_DETECTION_SCORE
            distances = outputs[index + len(STRIDES)].reshape(-1, 4)[keep] * stride
            offsets = outputs[index + 2 * len(STRIDES)].reshape(-1, 5, 2)[keep] * stride
            kept_centers = centers[keep]
            boxes.append(
                np.column_stack(
                    [
                        kept_centers[:, 0] - distances[:, 0],
                        kept_centers[:, 1] - distances[:, 1],
                        kept_centers[:, 0] + distances[:, 2],
                        kept_centers[:, 1] + distances[:, 3],
                    ]
                )
            )
            scores.append(level_scores[keep])
            points.append(kept_centers[:, None] + offsets)

        all_boxes = np.concatenate(boxes)
        all_scores = np.concatenate(scores)
        all_points = np.concatenate(points)
        return [
            FaceDetection(
                box=(all_boxes[i] / scale).tolist(),
                score=float(all_scores[i]),
                points=(all_points[i] / scale).tolist(),
            )
            for i in self._suppress_overlaps(all_boxes, all_scores)
        ]

    @staticmethod
    def _suppress_overlaps(boxes: np.ndarray, scores: np.ndarray) -> list[int]:
        """Deja una sola detección por cara.

        Args:
            boxes: Rectángulos candidatos.
            scores: Confianza de cada uno.

        Returns:
            Los índices que se conservan.
        """
        order = list(np.argsort(-scores))
        kept: list[int] = []
        while order:
            best = order.pop(0)
            kept.append(int(best))
            remaining = []
            for other in order:
                top_left = np.maximum(boxes[best][:2], boxes[other][:2])
                bottom_right = np.minimum(boxes[best][2:], boxes[other][2:])
                overlap = float(np.prod(np.clip(bottom_right - top_left, 0, None)))
                area_best = float(np.prod(boxes[best][2:] - boxes[best][:2]))
                area_other = float(np.prod(boxes[other][2:] - boxes[other][:2]))
                if overlap / max(area_best + area_other - overlap, 1e-6) <= NMS_IOU:
                    remaining.append(other)
            order = remaining
        return kept

    def embed(self, image: Image.Image, face: FaceDetection) -> np.ndarray:
        """Calcula la huella de una cara. Solo vive en memoria mientras se compara.

        Args:
            image: Imagen en RGB.
            face: Cara detectada.

        Returns:
            El vector normalizado.
        """
        self._load()
        matrix = similarity_transform(np.array(face.points, dtype=np.float32), ALIGNED_POINTS)

        # Pillow pide la transformación inversa: de la imagen final hacia la original.
        rotation_inverse = np.linalg.inv(matrix[:, :2])
        offset = -rotation_inverse @ matrix[:, 2]
        coefficients = (*rotation_inverse[0], offset[0], *rotation_inverse[1], offset[1])
        aligned = image.transform(
            (ALIGNED_SIZE, ALIGNED_SIZE), Image.Transform.AFFINE, coefficients, Image.Resampling.BILINEAR
        )
        blob = ((np.asarray(aligned, dtype=np.float32) - 127.5) / 127.5).transpose(2, 0, 1)[None]
        vector = self.recognizer.run(None, {self.recognizer.get_inputs()[0].name: blob})[0][0]
        return vector / np.linalg.norm(vector)

    def enroll(self, photos: list[str]) -> FaceEnrollment:
        """Aprende mi cara; solo usa fotos donde aparece una sola persona, clara.

        Args:
            photos: Fotos como data URL.

        Returns:
            Cuántas sirvieron y si ya quedó aprendida.
        """
        vectors: list[np.ndarray] = []
        saw_many = False
        for photo in photos:
            image = decode_photo(photo)
            faces = self.detect(image)
            saw_many = saw_many or len(faces) > 1
            if len(faces) != 1 or faces[0].score < MIN_ENROLL_SCORE:
                continue
            width = faces[0].box[2] - faces[0].box[0]
            if width >= MIN_ENROLL_FACE_PIXELS:
                vectors.append(self.embed(image, faces[0]))

        if len(vectors) < MIN_ENROLL_PHOTOS:
            status = "many_faces" if saw_many else "no_clear_face"
            return FaceEnrollment(status=status, photos_used=len(vectors))

        mean = np.mean(vectors, axis=0)
        self._save(mean / np.linalg.norm(mean))
        return FaceEnrollment(status="learned", photos_used=len(vectors))

    def _save(self, vector: np.ndarray) -> None:
        """Guarda la huella en un archivo que solo puede leer tu usuario.

        Args:
            vector: Huella normalizada.
        """
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.profile_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, OWNER_ONLY)
        with os.fdopen(descriptor, "wb") as file:
            np.save(file, vector)

    def check(self, data_url: str) -> FaceCheck | None:
        """Comprueba si aparezco en una foto. Las huellas de la foto no se conservan.

        Args:
            data_url: Foto como data URL.

        Returns:
            Cuántas caras hay y si una es la suya, o `None` si todavía no la aprendió.
        """
        if not self.is_enrolled or not self.is_available:
            return None
        profile = np.load(self.profile_path)
        image = decode_photo(data_url)
        faces = self.detect(image)
        is_present = any(
            float(np.dot(profile, self.embed(image, face))) >= SAME_PERSON_SIMILARITY for face in faces
        )
        return FaceCheck(face_count=len(faces), carlos_present=is_present)

    def forget(self) -> bool:
        """Borra la huella de la cara para siempre.

        Returns:
            Si había una.
        """
        if not self.is_enrolled:
            return False
        self.profile_path.unlink()
        return True

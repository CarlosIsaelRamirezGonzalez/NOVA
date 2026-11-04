"""Búsqueda de recuerdos por significado, con Qdrant y un modelo local de embeddings.

Qdrant solo guarda vectores y el identificador de cada recuerdo. Los datos viven en SQLite, así
que este índice se puede borrar y reconstruir. Nada de esto sale del equipo.
"""

import threading
from pathlib import Path

from fastembed import TextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointIdsList, PointStruct, VectorParams

from services.schemas import Memory, VectorHit

# Funciona bien en español y entiende "mi mascota" aunque el recuerdo diga "perro".
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
VECTOR_SIZE = 384
COLLECTION = "memories"


class VectorIndex:
    """Índice de recuerdos. Sus métodos bloquean, así que deben llamarse desde otro hilo."""

    def __init__(self, vector_path: Path, models_path: Path) -> None:
        """Guarda las rutas; el modelo se carga después con `open`.

        Args:
            vector_path: Carpeta donde Qdrant guarda el índice.
            models_path: Carpeta del modelo de embeddings.
        """
        self.vector_path = vector_path
        self.models_path = models_path
        self.embedder: TextEmbedding | None = None
        self.client: QdrantClient | None = None
        # El modo local de Qdrant no admite llamadas simultáneas desde varios hilos.
        self.lock = threading.Lock()

    @property
    def is_ready(self) -> bool:
        """Indica si ya se puede buscar.

        Returns:
            Si el modelo y el índice están cargados.
        """
        return self.embedder is not None and self.client is not None

    def open(self, memories: list[Memory]) -> None:
        """Carga el modelo y el índice, y agrega los recuerdos que le falten.

        La primera vez descarga el modelo, unos 240 MB.

        Args:
            memories: Recuerdos vigentes en la base de datos.
        """
        self.embedder = TextEmbedding(EMBEDDING_MODEL, cache_dir=str(self.models_path))
        self.vector_path.mkdir(parents=True, exist_ok=True)
        self.client = QdrantClient(path=str(self.vector_path))
        if not self.client.collection_exists(COLLECTION):
            self.client.create_collection(
                COLLECTION, vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE)
            )
        self._sync(memories)

    def close(self) -> None:
        """Cierra el índice, liberando su carpeta."""
        if self.client:
            self.client.close()
            self.client = None

    def add(self, memory: Memory) -> None:
        """Agrega un recuerdo al índice.

        Args:
            memory: Recuerdo que se va a indexar.
        """
        if self.client:
            point = self._to_point(memory)
            with self.lock:
                self.client.upsert(COLLECTION, [point])

    def remove(self, memory_id: int) -> None:
        """Quita un recuerdo del índice, por ejemplo si quedó obsoleto.

        Args:
            memory_id: Identificador del recuerdo.
        """
        if self.client:
            with self.lock:
                self.client.delete(COLLECTION, PointIdsList(points=[memory_id]))

    def search(self, query: str, limit: int) -> list[VectorHit]:
        """Busca los recuerdos con un significado parecido.

        Args:
            query: Texto de búsqueda.
            limit: Cuántos resultados devolver como máximo.

        Returns:
            Los resultados, del más parecido al menos parecido.
        """
        if not self.client:
            return []
        vector = self._embed(query)
        with self.lock:
            points = self.client.query_points(COLLECTION, query=vector, limit=limit).points
        return [VectorHit(memory_id=point.id, score=point.score) for point in points]

    def neighbors(self, memory_id: int, limit: int) -> list[VectorHit]:
        """Busca los recuerdos con significado más parecido a otro recuerdo.

        Args:
            memory_id: Recuerdo de referencia.
            limit: Cuántos vecinos devolver como máximo.

        Returns:
            Los vecinos, sin incluir el propio recuerdo.
        """
        if not self.client:
            return []
        with self.lock:
            points = self.client.query_points(COLLECTION, query=memory_id, limit=limit).points
        return [VectorHit(memory_id=point.id, score=point.score) for point in points]

    def _sync(self, memories: list[Memory]) -> None:
        """Deja el índice igual a la base de datos, que es la fuente de la verdad.

        Args:
            memories: Recuerdos vigentes en la base de datos.
        """
        points, _ = self.client.scroll(COLLECTION, limit=1_000_000, with_payload=False)
        indexed = {point.id for point in points}
        active = {memory.id for memory in memories}

        for memory in memories:
            if memory.id not in indexed:
                self.add(memory)
        for memory_id in indexed - active:
            self.remove(memory_id)

    def _to_point(self, memory: Memory) -> PointStruct:
        """Convierte un recuerdo en un punto de Qdrant, sin copiar su contenido.

        Args:
            memory: Recuerdo que se va a indexar.

        Returns:
            El punto con su vector.
        """
        return PointStruct(id=memory.id, vector=self._embed(memory.content))

    def _embed(self, text: str) -> list[float]:
        """Convierte un texto en su vector.

        Args:
            text: Texto de entrada.

        Returns:
            El vector.
        """
        return [float(value) for value in next(iter(self.embedder.embed([text])))]

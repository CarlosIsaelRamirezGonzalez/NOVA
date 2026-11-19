"""Contrato del índice que busca recuerdos por significado, y su versión apagada.

En la Mac lo cumple `VectorIndex` (fastembed y Qdrant). En la web no caben esos modelos, así que
se usa `DisabledSearchIndex`: la memoria sigue funcionando con el perfil, solo sin la búsqueda por
significado. `MemoryService` ya sabe trabajar así mientras el índice carga.
"""

from typing import Protocol

from services.schemas import Memory, VectorHit


class SearchIndex(Protocol):
    """Lo que `MemoryService` necesita de un índice de recuerdos."""

    @property
    def is_ready(self) -> bool:
        """Si ya se puede buscar."""
        ...

    def open(self, memories: list[Memory]) -> None:
        """Carga el índice con los recuerdos vigentes."""
        ...

    def close(self) -> None:
        """Libera el índice."""
        ...

    def add(self, memory: Memory) -> None:
        """Agrega o actualiza un recuerdo."""
        ...

    def remove(self, memory_id: int) -> None:
        """Quita un recuerdo."""
        ...

    def search(self, query: str, limit: int) -> list[VectorHit]:
        """Busca los recuerdos más parecidos a un texto."""
        ...

    def neighbors(self, memory_id: int, limit: int) -> list[VectorHit]:
        """Busca los recuerdos más parecidos a otro recuerdo."""
        ...


class DisabledSearchIndex:
    """Índice que nunca está listo; se usa donde no se pueden cargar los modelos locales."""

    @property
    def is_ready(self) -> bool:
        """Nunca está listo.

        Returns:
            Siempre `False`.
        """
        return False

    def open(self, memories: list[Memory]) -> None:
        """No carga nada.

        Args:
            memories: Recuerdos vigentes; se ignoran.
        """

    def close(self) -> None:
        """No hay nada que cerrar."""

    def add(self, memory: Memory) -> None:
        """No guarda nada.

        Args:
            memory: Recuerdo; se ignora.
        """

    def remove(self, memory_id: int) -> None:
        """No hay nada que quitar.

        Args:
            memory_id: Recuerdo; se ignora.
        """

    def search(self, query: str, limit: int) -> list[VectorHit]:
        """No encuentra nada.

        Args:
            query: Texto buscado; se ignora.
            limit: Máximo de resultados; se ignora.

        Returns:
            Una lista vacía.
        """
        return []

    def neighbors(self, memory_id: int, limit: int) -> list[VectorHit]:
        """No encuentra nada.

        Args:
            memory_id: Recuerdo de referencia; se ignora.
            limit: Máximo de resultados; se ignora.

        Returns:
            Una lista vacía.
        """
        return []

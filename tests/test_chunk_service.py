"""Pruebas de la división de respuestas en frases para la voz."""

from services.chunk.chunk_service import ChunkingService


def test_cuts_at_the_end_of_a_sentence() -> None:
    """Una oración completa se libera y el resto espera."""
    chunker = ChunkingService()
    assert chunker.add_token("Hola, ¿cómo estás? Bien") == ["Hola, ¿cómo estás?"]
    assert chunker.flush() == "Bien"


def test_does_not_split_decimal_numbers() -> None:
    """Un punto sin espacio después, como en 3.14, no corta la frase."""
    chunker = ChunkingService()
    assert chunker.add_token("Pi vale 3.14 más o menos") == []
    assert chunker.flush() == "Pi vale 3.14 más o menos"


def test_first_chunk_can_cut_at_a_comma() -> None:
    """La primera frase se corta en una coma tras pocas palabras, para empezar a hablar antes."""
    chunker = ChunkingService(first_chunk_words=6)
    chunks = chunker.add_token("uno dos tres cuatro cinco seis, siete ocho")
    assert chunks == ["uno dos tres cuatro cinco seis,"]


def test_later_chunks_wait_for_more_words_before_a_comma() -> None:
    """Después de la primera frase, una coma no basta si hay pocas palabras."""
    chunker = ChunkingService(first_chunk_words=2, max_chunk_words=45)
    assert chunker.add_token("Primero. ") == ["Primero."]
    assert chunker.add_token("uno dos tres, cuatro") == []


def test_keeps_voice_tags_together() -> None:
    """No corta dentro de una marca de voz abierta como <emphasis>."""
    chunker = ChunkingService()
    assert chunker.add_token("<emphasis>Hola. Adiós</emphasis>. Fin ") == ["<emphasis>Hola. Adiós</emphasis>."]
    assert chunker.flush() == "Fin"


def test_flush_returns_none_when_empty() -> None:
    """Si no queda texto, no hay nada que pronunciar."""
    chunker = ChunkingService()
    assert chunker.flush() is None
    chunker.add_token("   ")
    assert chunker.flush() is None


def test_counts_released_chunks() -> None:
    """Cada frase liberada cuenta, incluida la del final."""
    chunker = ChunkingService()
    chunker.add_token("Una. Dos. ")
    chunker.flush()
    chunker.add_token("Tres")
    chunker.flush()
    assert chunker.chunk_count == 3

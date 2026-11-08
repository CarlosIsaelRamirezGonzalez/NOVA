"""Pruebas de los nombres de las notas que se generan en la bóveda de Obsidian."""

from services.context.obsidian_vault import emotion_label, kind_label, note_name
from services.schemas import EmotionBlend, EmotionComponent, Memory


def make_memory(memory_id: int, content: str) -> Memory:
    """Crea un recuerdo de prueba.

    Args:
        memory_id: Identificador del recuerdo.
        content: Texto del recuerdo.

    Returns:
        El recuerdo.
    """
    return Memory(
        id=memory_id,
        kind="fact",
        content=content,
        importance=0.5,
        emotions=EmotionBlend(components=[EmotionComponent(name="happy", intensity=0.7)]),
        source_message_id=None,
        created_at=0.0,
    )


def test_note_name_removes_characters_invalid_in_filenames() -> None:
    """El nombre no lleva caracteres que rompan el archivo o los enlaces de Obsidian."""
    memory = make_memory(7, 'Le gusta el café: "negro" [sin azúcar] #1')
    assert note_name(memory) == "0007 Le gusta el café negro sin azúcar 1"


def test_note_name_is_truncated_and_trimmed() -> None:
    """Los títulos largos se recortan sin dejar espacios ni puntos al final."""
    name = note_name(make_memory(12, "a" * 59 + ". más texto"))
    assert name == "0012 " + "a" * 59


def test_note_name_keeps_ids_unique() -> None:
    """Dos recuerdos con el mismo texto no comparten nota."""
    assert note_name(make_memory(1, "Igual")) != note_name(make_memory(2, "Igual"))


def test_labels_are_in_spanish() -> None:
    """Los tipos y las emociones se muestran en español."""
    assert kind_label("preference") == "Gustos"
    assert emotion_label("worried") == "Preocupación"


def test_memory_intensity_is_the_strongest_emotion() -> None:
    """La intensidad de un recuerdo es la de su emoción más fuerte; en calma es 0."""
    memory = make_memory(3, "Algo")
    assert memory.intensity == 0.7
    calm = memory.model_copy(update={"emotions": EmotionBlend()})
    assert calm.intensity == 0.0

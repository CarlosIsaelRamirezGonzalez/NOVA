"""Pruebas de la separación de etiquetas en las respuestas del modelo."""

from services.chunk.emotion_filter import EmotionTagFilter, parse_blend, strip_tags
from services.schemas import FilteredText


def feed_all(tokens: list[str]) -> tuple[FilteredText, str]:
    """Pasa varios tokens por un filtro nuevo y junta el resultado.

    Args:
        tokens: Fragmentos de texto en el orden en que llegan del modelo.

    Returns:
        El último resultado del filtro y todo el texto liberado, incluido lo pendiente al final.
    """
    tag_filter = EmotionTagFilter()
    text = ""
    combined = FilteredText()
    for token in tokens:
        result = tag_filter.feed(token)
        text += result.text
        combined.blends += result.blends
        combined.photo_requested = combined.photo_requested or result.photo_requested
        combined.forget_requested = combined.forget_requested or result.forget_requested
        combined.search_query = combined.search_query or result.search_query
        combined.write_instructions = combined.write_instructions or result.write_instructions
        combined.move_place = combined.move_place or result.move_place
        combined.learn_face_requested = combined.learn_face_requested or result.learn_face_requested
    return combined, text + tag_filter.flush()


def test_parse_blend_uses_full_intensity_by_default() -> None:
    """Una emoción sin número cuenta con intensidad 1."""
    blend = parse_blend("happy")
    assert blend is not None
    assert [(item.name, item.intensity) for item in blend.components] == [("happy", 1.0)]


def test_parse_blend_reads_mixes_and_ignores_unknown_names() -> None:
    """Las mezclas conservan su intensidad y los nombres desconocidos se descartan."""
    blend = parse_blend("Sad:0.6, worried:0.4, hungry:0.9")
    assert blend is not None
    assert [(item.name, item.intensity) for item in blend.components] == [("sad", 0.6), ("worried", 0.4)]


def test_parse_blend_caps_intensity_at_one() -> None:
    """Una intensidad mayor que 1 se recorta."""
    blend = parse_blend("angry:3")
    assert blend is not None
    assert blend.components[0].intensity == 1.0


def test_parse_blend_treats_calm_as_an_empty_blend() -> None:
    """La calma se reconoce, pero no ocupa lugar en la mezcla."""
    blend = parse_blend("neutral")
    assert blend is not None
    assert blend.components == []


def test_parse_blend_returns_none_without_known_emotions() -> None:
    """Sin ninguna emoción conocida no hay mezcla."""
    assert parse_blend("hungry, sleepy") is None


def test_tag_split_across_tokens_is_removed_from_text() -> None:
    """Una etiqueta que llega partida en varios tokens no aparece en el texto."""
    result, text = feed_all(["Hola [[ha", "ppy:0.", "8]] ¿cómo", " estás?"])
    assert text == "Hola  ¿cómo estás?"
    assert [(item.name, item.intensity) for blend in result.blends for item in blend.components] == [("happy", 0.8)]


def test_control_tags_are_detected() -> None:
    """Las etiquetas de foto, olvido, búsqueda, escritura, movimiento y cara se reconocen."""
    result, text = feed_all(
        [
            "Listo. [[photo]] [[forget]] [[search: clima en Guadalajara]] ",
            "[[write: dile que llego a las cinco]] [[move: top_left]] [[learn_face]]",
        ]
    )
    assert result.photo_requested
    assert result.forget_requested
    assert result.search_query == "clima en Guadalajara"
    assert result.write_instructions == "dile que llego a las cinco"
    assert result.move_place == "top_left"
    assert result.learn_face_requested
    assert "[[" not in text


def test_brackets_that_are_not_a_tag_stay_in_the_text() -> None:
    """Unos corchetes dobles sin formato de etiqueta son texto normal."""
    _, text = feed_all(["a [[x y]] b"])
    assert text == "a [[x y]] b"


def test_half_open_bracket_is_held_until_flush() -> None:
    """Un "[" al final se retiene por si empieza una etiqueta, y se libera al terminar."""
    tag_filter = EmotionTagFilter()
    assert tag_filter.feed("precio [").text == "precio "
    assert tag_filter.flush() == "["


def test_strip_tags_cleans_a_finished_reply() -> None:
    """El historial se muestra sin etiquetas de control."""
    assert strip_tags("[[happy]] ¡Qué gusto! [[photo]]") == "¡Qué gusto!"

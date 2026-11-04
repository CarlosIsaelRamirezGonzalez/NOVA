"""Genera una bóveda de Obsidian para leer la memoria de Nova.

Solo se escribe desde SQLite hacia aquí: cualquier cambio manual se pierde al regenerar.
"""

import re
from datetime import datetime
from pathlib import Path

from services.schemas import BrainLink, Emotion, EmotionComponent, Memory, MemoryKind

MEMORIES_FOLDER = "Recuerdos"
KINDS_FOLDER = "Tipos"
EMOTIONS_FOLDER = "Emociones"
MANAGED_FOLDERS = (MEMORIES_FOLDER, KINDS_FOLDER, EMOTIONS_FOLDER)
HOME_NOTE = "Nova.md"
UNSAFE_FILENAME = re.compile(r"[\\/:*?\"<>|#^\[\]]")
MAX_TITLE_CHARS = 60

KIND_LABELS: tuple[tuple[MemoryKind, str], ...] = (
    ("fact", "Hechos"),
    ("preference", "Gustos"),
    ("person", "Personas"),
    ("event", "Sucesos"),
    ("plan", "Planes"),
    ("moment", "Momentos"),
)
EMOTION_LABELS: tuple[tuple[Emotion, str], ...] = (
    ("neutral", "Calma"),
    ("happy", "Alegría"),
    ("sad", "Tristeza"),
    ("angry", "Enojo"),
    ("surprised", "Sorpresa"),
    ("curious", "Curiosidad"),
    ("afraid", "Miedo"),
    ("worried", "Preocupación"),
    ("stressed", "Estrés"),
    ("frustrated", "Frustración"),
)


def kind_label(kind: MemoryKind) -> str:
    """Traduce el tipo de un recuerdo.

    Args:
        kind: Tipo del recuerdo.

    Returns:
        El nombre de su nota en la bóveda.
    """
    return next(label for name, label in KIND_LABELS if name == kind)


def emotion_label(emotion: Emotion) -> str:
    """Traduce una emoción.

    Args:
        emotion: Emoción de un recuerdo.

    Returns:
        El nombre de su nota en la bóveda.
    """
    return next(label for name, label in EMOTION_LABELS if name == emotion)


def note_name(memory: Memory) -> str:
    """Construye el nombre de la nota de un recuerdo.

    Args:
        memory: Recuerdo de la nota.

    Returns:
        Un nombre único y válido como archivo, sin extensión.
    """
    title = UNSAFE_FILENAME.sub("", memory.content).strip()[:MAX_TITLE_CHARS].rstrip(" .")
    return f"{memory.id:04d} {title}"


class ObsidianVault:
    """Escribe los recuerdos como notas enlazadas por tipo, emoción y parecido."""

    def __init__(self, path: Path) -> None:
        """Guarda la ubicación de la bóveda.

        Args:
            path: Carpeta de la bóveda.
        """
        self.path = path

    def export(
        self, memories: list[Memory], links: list[BrainLink], mood: list[EmotionComponent]
    ) -> None:
        """Regenera las notas para que coincidan con la memoria actual.

        Args:
            memories: Recuerdos vigentes.
            links: Conexiones entre recuerdos.
            mood: Lo que siente Nova ahora.
        """
        # Borra solo lo que esta clase genera; la configuración de Obsidian no se toca.
        for folder in MANAGED_FOLDERS:
            directory = self.path / folder
            directory.mkdir(parents=True, exist_ok=True)
            for note in directory.glob("*.md"):
                note.unlink()

        # Una nota por recuerdo, una por cada tipo y una por cada emoción.
        names = [(memory.id, note_name(memory)) for memory in memories]
        for memory in memories:
            (self.path / MEMORIES_FOLDER / f"{note_name(memory)}.md").write_text(
                self._memory_note(memory, links, names), encoding="utf-8"
            )
        self._write_hubs(memories)
        (self.path / HOME_NOTE).write_text(self._home_note(memories, mood), encoding="utf-8")

    @staticmethod
    def _memory_note(
        memory: Memory, links: list[BrainLink], names: list[tuple[int, str]]
    ) -> str:
        """Redacta la nota de un recuerdo.

        Args:
            memory: Recuerdo de la nota.
            links: Conexiones entre recuerdos.
            names: Pares de identificador y nombre de nota.

        Returns:
            El contenido en Markdown.
        """
        date = datetime.fromtimestamp(memory.created_at).strftime("%Y-%m-%d %H:%M")
        felt = [
            f"[[{emotion_label(item.name)}]] ({item.intensity:.0%})"
            for item in memory.emotions.components
        ]

        # Busca los recuerdos con significado parecido, en cualquier dirección del enlace.
        related_ids = [
            link.target if link.source == memory.id else link.source
            for link in links
            if memory.id in (link.source, link.target)
        ]
        related = [f"- [[{name}]]" for memory_id, name in names if memory_id in related_ids]

        lines = [
            "---",
            f"tipo: {memory.kind}",
            f"importancia: {memory.importance:.2f}",
            f"fecha: {date}",
            "---",
            "",
            memory.content,
            "",
            f"**Tipo:** [[{kind_label(memory.kind)}]]",
            f"**Sintió:** {', '.join(felt) if felt else 'calma'}",
        ]
        if related:
            lines += ["", "## Relacionado", *related]
        return "\n".join(lines) + "\n"

    def _write_hubs(self, memories: list[Memory]) -> None:
        """Escribe las notas de tipos y emociones, que agrupan los recuerdos en el grafo.

        Args:
            memories: Recuerdos vigentes.
        """
        for kind, label in KIND_LABELS:
            members = [memory for memory in memories if memory.kind == kind]
            lines = [f"# {label}", "", *(f"- [[{note_name(memory)}]]" for memory in members)]
            (self.path / KINDS_FOLDER / f"{label}.md").write_text(
                "\n".join(lines) + "\n", encoding="utf-8"
            )

        for emotion, label in EMOTION_LABELS:
            members = [
                memory
                for memory in memories
                if any(item.name == emotion for item in memory.emotions.components)
            ]
            lines = [f"# {label}", "", *(f"- [[{note_name(memory)}]]" for memory in members)]
            (self.path / EMOTIONS_FOLDER / f"{label}.md").write_text(
                "\n".join(lines) + "\n", encoding="utf-8"
            )

    @staticmethod
    def _home_note(memories: list[Memory], mood: list[EmotionComponent]) -> str:
        """Redacta la nota principal de la bóveda.

        Args:
            memories: Recuerdos vigentes.
            mood: Lo que siente Nova ahora.

        Returns:
            El contenido en Markdown.
        """
        feelings = ", ".join(f"{emotion_label(item.name)} {item.intensity:.0%}" for item in mood)
        kinds = [f"- [[{label}]]" for _, label in KIND_LABELS]
        return "\n".join(
            [
                "# Memoria de Nova",
                "",
                "> Estas notas se generan solas desde la memoria de Nova. No las edites: tus cambios",
                "> se perderían. Para corregir algo, díselo a Nova o usa su vista del cerebro.",
                "",
                f"**Recuerdos:** {len(memories)}",
                f"**Siente ahora:** {feelings or 'calma'}",
                "",
                "## Por tipo",
                *kinds,
            ]
        ) + "\n"

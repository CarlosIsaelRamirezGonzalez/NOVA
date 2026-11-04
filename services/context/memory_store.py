"""Memoria persistente de Nova en SQLite: conversación, ánimo y recuerdos.

Es la fuente de la verdad; se guarda en un archivo local que no entra a git.
"""

import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from services.schemas import (
    EmotionBlend,
    Memory,
    MemoryKind,
    MessageRole,
    StoredMessage,
    StoredMood,
)

SCHEMA_VERSION = 2
OWNER_ONLY = 0o600

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS mood (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    blend TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    importance REAL NOT NULL,
    emotions TEXT NOT NULL,
    source_message_id INTEGER REFERENCES messages (id),
    created_at REAL NOT NULL,
    superseded_by INTEGER REFERENCES memories (id)
);
"""

MEMORY_COLUMNS = "id, kind, content, importance, emotions, source_message_id, created_at"


class MemoryStore:
    """Guarda y recupera lo que debe sobrevivir a un reinicio."""

    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        """Abre la base de datos y la crea si no existe.

        Args:
            path: Archivo de la base de datos.
            clock: Reloj en segundos reales; se puede sustituir en las pruebas.
        """
        self.clock = clock
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)

        # Al borrar, sobrescribe los bytes: un recuerdo olvidado no queda oculto en el archivo.
        self.connection.execute("PRAGMA secure_delete = ON")

        # Crea las tablas y deja el archivo legible solo para tu usuario.
        with self.connection:
            self.connection.executescript(SCHEMA)
            self.connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        path.chmod(OWNER_ONLY)

    def add_message(self, role: MessageRole, content: str) -> None:
        """Guarda un mensaje de la conversación.

        Args:
            role: Quién lo escribió.
            content: Texto del mensaje.
        """
        with self.connection:
            self.connection.execute(
                "INSERT INTO messages (role, content, created_at) VALUES (?, ?, ?)",
                (role, content, self.clock()),
            )

    def last_message_id(self) -> int | None:
        """Busca el mensaje más reciente.

        Returns:
            Su identificador, o `None` si no hay mensajes.
        """
        return self.connection.execute("SELECT MAX(id) FROM messages").fetchone()[0]

    def delete_last_message(self) -> None:
        """Borra el último mensaje, por ejemplo el de un turno que falló."""
        with self.connection:
            self.connection.execute("DELETE FROM messages WHERE id = (SELECT MAX(id) FROM messages)")

    def recent_messages(self, limit: int) -> list[StoredMessage]:
        """Lee los mensajes más recientes.

        Args:
            limit: Cuántos mensajes leer como máximo.

        Returns:
            Los mensajes, del más antiguo al más reciente.
        """
        rows = self.connection.execute(
            "SELECT role, content, created_at FROM messages ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            StoredMessage(role=role, content=content, created_at=created_at)
            for role, content, created_at in reversed(rows)
        ]

    def last_user_message_at(self) -> float | None:
        """Busca cuándo escribió Carlos por última vez.

        Returns:
            El momento en segundos, o `None` si nunca ha escrito.
        """
        row = self.connection.execute(
            "SELECT created_at FROM messages WHERE role = 'user' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None

    def save_mood(self, blend: EmotionBlend) -> None:
        """Guarda el estado emocional actual.

        Args:
            blend: Emociones que siente Nova ahora.
        """
        with self.connection:
            self.connection.execute(
                "INSERT INTO mood (id, blend, updated_at) VALUES (1, ?, ?) "
                "ON CONFLICT (id) DO UPDATE SET blend = excluded.blend, "
                "updated_at = excluded.updated_at",
                (blend.model_dump_json(), self.clock()),
            )

    def load_mood(self) -> StoredMood | None:
        """Lee el último estado emocional guardado.

        Returns:
            El estado y cuándo se guardó, o `None` si no hay o está dañado.
        """
        row = self.connection.execute("SELECT blend, updated_at FROM mood").fetchone()
        if row is None:
            return None
        try:
            return StoredMood(blend=EmotionBlend.model_validate_json(row[0]), updated_at=row[1])
        except ValidationError:
            return None

    def add_memory(
        self,
        kind: MemoryKind,
        content: str,
        importance: float,
        emotions: EmotionBlend,
        source_message_id: int | None,
        replaces: int | None = None,
    ) -> Memory:
        """Guarda un recuerdo nuevo. Si corrige otro, el anterior se conserva como obsoleto.

        Args:
            kind: Tipo de recuerdo.
            content: El recuerdo, en una frase.
            importance: Qué tanto importa, de 0 a 1.
            emotions: Lo que sentía Nova en ese momento.
            source_message_id: Mensaje de donde salió.
            replaces: Identificador del recuerdo que queda obsoleto, si alguno.

        Returns:
            El recuerdo guardado.
        """
        now = self.clock()
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO memories (kind, content, importance, emotions, source_message_id, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (kind, content, importance, emotions.model_dump_json(), source_message_id, now),
            )
            memory_id = cursor.lastrowid
            if replaces is not None:
                self.connection.execute(
                    "UPDATE memories SET superseded_by = ? WHERE id = ? AND superseded_by IS NULL",
                    (memory_id, replaces),
                )
        return Memory(
            id=memory_id,
            kind=kind,
            content=content,
            importance=importance,
            emotions=emotions,
            source_message_id=source_message_id,
            created_at=now,
        )

    def delete_memories(self, memory_ids: list[int]) -> list[Memory]:
        """Borra recuerdos para siempre, junto con sus versiones obsoletas y su origen.

        Args:
            memory_ids: Recuerdos que se van a borrar.

        Returns:
            Los recuerdos vigentes que se borraron.
        """
        memories = self.memories_by_id(memory_ids)
        if not memories:
            return []

        ids = [memory.id for memory in memories]
        marks = ", ".join("?" for _ in ids)
        with self.connection:
            # Incluye las versiones anteriores: "trabaja en Atom" no debe sobrevivir a su corrección.
            sources = self.connection.execute(
                f"SELECT source_message_id FROM memories WHERE id IN ({marks}) "
                f"OR superseded_by IN ({marks})",
                [*ids, *ids],
            ).fetchall()
            self.connection.execute(
                f"DELETE FROM memories WHERE id IN ({marks}) OR superseded_by IN ({marks})",
                [*ids, *ids],
            )
            for (source_id,) in sources:
                if source_id is not None:
                    self._delete_exchange(source_id)
        return memories

    def delete_messages_containing(self, term: str) -> int:
        """Borra de la conversación los mensajes que mencionan un término.

        Args:
            term: Palabra específica que hay que eliminar.

        Returns:
            Cuántos mensajes se borraron.
        """
        with self.connection:
            cursor = self.connection.execute(
                "DELETE FROM messages WHERE content LIKE ? ESCAPE '\\'",
                ("%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",),
            )
        return cursor.rowcount

    def _delete_exchange(self, message_id: int) -> None:
        """Borra un mensaje y la respuesta que le siguió.

        Args:
            message_id: Mensaje de donde salió un recuerdo.
        """
        next_row = self.connection.execute(
            "SELECT id, role FROM messages WHERE id > ? ORDER BY id LIMIT 1", (message_id,)
        ).fetchone()
        self.connection.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        if next_row and next_row[1] == "assistant":
            self.connection.execute("DELETE FROM messages WHERE id = ?", (next_row[0],))

    def active_memories(self) -> list[Memory]:
        """Lee todos los recuerdos vigentes.

        Returns:
            Los recuerdos que no han sido reemplazados.
        """
        rows = self.connection.execute(
            f"SELECT {MEMORY_COLUMNS} FROM memories WHERE superseded_by IS NULL ORDER BY id"
        ).fetchall()
        return [self._to_memory(row) for row in rows]

    def memories_by_id(self, memory_ids: list[int]) -> list[Memory]:
        """Lee recuerdos vigentes por su identificador.

        Args:
            memory_ids: Identificadores buscados.

        Returns:
            Los recuerdos encontrados; omite los que ya fueron reemplazados.
        """
        if not memory_ids:
            return []
        marks = ", ".join("?" for _ in memory_ids)
        rows = self.connection.execute(
            f"SELECT {MEMORY_COLUMNS} FROM memories "
            f"WHERE superseded_by IS NULL AND id IN ({marks})",
            memory_ids,
        ).fetchall()
        return [self._to_memory(row) for row in rows]

    def profile_memories(self, minimum: float, limit: int) -> list[Memory]:
        """Lee el perfil: lo que Nova debe tener siempre presente, venga o no al caso.

        Incluye sus gustos y las personas de su vida, porque buscar por significado no los
        encuentra: una cena no se parece en nada a "no soporta el cilantro".

        Args:
            minimum: Importancia mínima de los demás recuerdos para entrar al perfil.
            limit: Cuántos leer como máximo.

        Returns:
            Los recuerdos, del más importante al menos importante.
        """
        rows = self.connection.execute(
            f"SELECT {MEMORY_COLUMNS} FROM memories WHERE superseded_by IS NULL "
            "AND (importance >= ? OR kind IN ('preference', 'person')) "
            "ORDER BY importance DESC, id DESC LIMIT ?",
            (minimum, limit),
        ).fetchall()
        return [self._to_memory(row) for row in rows]

    @staticmethod
    def _to_memory(row: tuple[int, MemoryKind, str, float, str, int | None, float]) -> Memory:
        """Convierte una fila de la base de datos en un recuerdo.

        Args:
            row: Fila con las columnas de `MEMORY_COLUMNS`.

        Returns:
            El recuerdo.
        """
        memory_id, kind, content, importance, emotions, source_message_id, created_at = row
        return Memory(
            id=memory_id,
            kind=kind,
            content=content,
            importance=importance,
            emotions=EmotionBlend.model_validate_json(emotions),
            source_message_id=source_message_id,
            created_at=created_at,
        )

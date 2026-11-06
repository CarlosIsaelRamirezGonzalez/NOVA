"""Memoria persistente de Nova en SQLite: conversación, ánimo y recuerdos.

Es la fuente de la verdad; se guarda en un archivo local que no entra a git.
"""

import functools
import os
import sqlite3
import threading
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Concatenate, ParamSpec, TypeVar

import certifi
import turso.sync

from pydantic import ValidationError

from services.schemas import (
    EmotionBlend,
    Memory,
    MemoryKind,
    MessageRole,
    StoredMessage,
    StoredMood,
    SyncSettings,
    UsageDayRow,
    UsageRecord,
    VisualObservation,
    VisualRecord,
)

SCHEMA_VERSION = 3
OWNER_ONLY = 0o600

# Sin llaves foráneas a propósito: SQLite no las aplicaba aquí, pero la nube sí, y al repetir los
# cambios en otro orden rechazaba recuerdos válidos y detenía toda la sincronización.
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
    source_message_id INTEGER,
    created_at REAL NOT NULL,
    superseded_by INTEGER
);
CREATE TABLE IF NOT EXISTS visual_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS api_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purpose TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    searches INTEGER NOT NULL,
    credits INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    created_at REAL NOT NULL
);
"""

MEMORY_COLUMNS = "id, kind, content, importance, emotions, source_message_id, created_at"


Params = ParamSpec("Params")
Result = TypeVar("Result")


def _serialized(
    method: Callable[Concatenate["MemoryStore", Params], Result],
) -> Callable[Concatenate["MemoryStore", Params], Result]:
    """Hace que un método espere si la base se está sincronizando en otro hilo.

    Args:
        method: Método que usa la conexión.

    Returns:
        El mismo método, protegido con el candado de la base.
    """

    @functools.wraps(method)
    def locked(self: "MemoryStore", *args: Params.args, **kwargs: Params.kwargs) -> Result:
        """Ejecuta el método con el candado tomado.

        Args:
            self: Memoria persistente.
            *args: Argumentos del método.
            **kwargs: Argumentos con nombre del método.

        Returns:
            Lo que devuelva el método.
        """
        with self.lock:
            return method(self, *args, **kwargs)

    return locked


class MemoryStore:
    """Guarda y recupera lo que debe sobrevivir a un reinicio."""

    def __init__(
        self,
        path: Path,
        clock: Callable[[], float] = time.time,
        sync: SyncSettings | None = None,
    ) -> None:
        """Abre la base de datos y la crea si no existe.

        Args:
            path: Archivo de la base de datos.
            clock: Reloj en segundos reales; se puede sustituir en las pruebas.
            sync: Base en la nube que se mantiene al día; sin ella, todo se queda en este equipo.
        """
        self.clock = clock
        self.lock = threading.RLock()
        self.traces_pending = False
        self.path = path
        self.sync_settings = sync
        self.is_synced = sync is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = self._open(path, sync)

        # Al borrar, sobrescribe los bytes: un recuerdo olvidado no queda oculto en el archivo.
        self.connection.execute("PRAGMA secure_delete = ON")

        # Crea las tablas y deja el archivo legible solo para tu usuario.
        with self.connection:
            self.connection.executescript(SCHEMA)
            self.connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._restrict_files()

    @staticmethod
    def _open(path: Path, sync: SyncSettings | None) -> object:
        """Abre la conexión, local o sincronizada con la nube.

        Args:
            path: Archivo de la base de datos.
            sync: Base en la nube, si hay.

        Returns:
            Una conexión con la interfaz de `sqlite3`.
        """
        if sync is None:
            return sqlite3.connect(path)

        # La librería usa los certificados del sistema, y el Python de macOS no trae ninguno.
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        return turso.sync.connect(str(path), sync.database_url, auth_token=sync.auth_token)

    def _restrict_files(self) -> None:
        """Deja la base y sus archivos auxiliares legibles solo para tu usuario."""
        for file in self.path.parent.glob(f"{self.path.name}*"):
            file.chmod(OWNER_ONLY)

    def sync(self, erase_local_traces: bool = False) -> None:
        """Sube los cambios pendientes a la nube. Sin red, quedan guardados para el siguiente intento.

        Args:
            erase_local_traces: Rehace la copia local; se usa después de olvidar algo, porque el
                registro de cambios de la sincronización guarda el texto aunque se borre la fila.
        """
        if not self.is_synced:
            return
        with self.lock:
            self.traces_pending = self.traces_pending or erase_local_traces
            try:
                if self.connection.stats().cdc_operations > 0:
                    self.connection.push()
                if self.traces_pending:
                    self._rebuild_local_copy()
                self._restrict_files()
            except Exception:
                # Sin confirmar la subida no se borra nada: se reintenta en la siguiente vuelta.
                traceback.print_exc()

    def _rebuild_local_copy(self) -> None:
        """Borra la copia local y la vuelve a bajar de la nube, ya sin lo olvidado.

        Solo se llama después de una subida exitosa, así que no se pierde nada.
        """
        self.connection.close()
        for file in self.path.parent.glob(f"{self.path.name}*"):
            file.unlink()
        self.connection = self._open(self.path, self.sync_settings)
        self.traces_pending = False

    @_serialized
    def add_usage(self, record: UsageRecord) -> None:
        """Guarda lo que gastó una llamada a una API.

        Args:
            record: Registro de la llamada.
        """
        with self.connection:
            self.connection.execute(
                "INSERT INTO api_usage (purpose, input_tokens, output_tokens, searches, credits, "
                "cost_usd, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record.purpose,
                    record.input_tokens,
                    record.output_tokens,
                    record.searches,
                    record.credits,
                    record.cost_usd,
                    self.clock(),
                ),
            )

    @_serialized
    def usage_by_day(self, first_day: str) -> list[UsageDayRow]:
        """Suma el gasto por día y servicio.

        Args:
            first_day: Primer día que se incluye, en formato `YYYY-MM-DD`.

        Returns:
            Una fila por cada día y servicio que tuvieron gasto.
        """
        rows = self.connection.execute(
            "SELECT date(created_at, 'unixepoch', 'localtime') AS day, purpose, COUNT(*), "
            "SUM(input_tokens), SUM(output_tokens), SUM(searches), SUM(credits), SUM(cost_usd) "
            "FROM api_usage WHERE day >= ? GROUP BY day, purpose",
            (first_day,),
        ).fetchall()
        return [
            UsageDayRow(
                day=row[0],
                purpose=row[1],
                calls=row[2],
                input_tokens=row[3],
                output_tokens=row[4],
                searches=row[5],
                credits=row[6],
                cost_usd=row[7],
            )
            for row in rows
        ]

    @_serialized
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

    @_serialized
    def last_message_id(self) -> int | None:
        """Busca el mensaje más reciente.

        Returns:
            Su identificador, o `None` si no hay mensajes.
        """
        return self.connection.execute("SELECT MAX(id) FROM messages").fetchone()[0]

    @_serialized
    def delete_last_message(self) -> None:
        """Borra el último mensaje, por ejemplo el de un turno que falló."""
        with self.connection:
            self.connection.execute("DELETE FROM messages WHERE id = (SELECT MAX(id) FROM messages)")

    @_serialized
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

    @_serialized
    def last_user_message_at(self) -> float | None:
        """Busca cuándo escribió Carlos por última vez.

        Returns:
            El momento en segundos, o `None` si nunca ha escrito.
        """
        row = self.connection.execute(
            "SELECT created_at FROM messages WHERE role = 'user' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None

    @_serialized
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

    @_serialized
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

    @_serialized
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
            where = f"id IN ({marks}) OR superseded_by IN ({marks})"
            self._overwrite("memories", where, [*ids, *ids])
            self.connection.execute(f"DELETE FROM memories WHERE {where}", [*ids, *ids])
            for (source_id,) in sources:
                if source_id is not None:
                    self._delete_exchange(source_id)
        return memories

    @_serialized
    def delete_messages_containing(self, term: str) -> int:
        """Borra de la conversación los mensajes que mencionan un término.

        Args:
            term: Palabra específica que hay que eliminar.

        Returns:
            Cuántos mensajes se borraron.
        """
        pattern = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        with self.connection:
            # Primero anota cuáles son: al sobrescribirlos ya no contendrían el término.
            rows = self.connection.execute(
                "SELECT id FROM messages WHERE content LIKE ? ESCAPE '\\'", [pattern]
            ).fetchall()
            for (message_id,) in rows:
                self._overwrite("messages", "id = ?", [message_id])
                self.connection.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        return len(rows)

    @_serialized
    def add_visual_observation(self, observation: VisualObservation) -> None:
        """Guarda lo que se vio en una foto; la foto en sí nunca llega aquí.

        Args:
            observation: Campos permitidos de la foto.
        """
        with self.connection:
            self.connection.execute(
                "INSERT INTO visual_observations (content, created_at) VALUES (?, ?)",
                (observation.model_dump_json(), self.clock()),
            )

    @_serialized
    def visual_observations(self) -> list[VisualRecord]:
        """Lee las observaciones visuales.

        Returns:
            Las observaciones, de la más antigua a la más nueva.
        """
        rows = self.connection.execute(
            "SELECT id, content, created_at FROM visual_observations ORDER BY created_at, id"
        ).fetchall()
        return [
            VisualRecord(
                id=row[0],
                created_at=row[2],
                observation=VisualObservation.model_validate_json(row[1]),
            )
            for row in rows
        ]

    @_serialized
    def delete_visual_observations(self, observation_id: int | None = None) -> int:
        """Borra observaciones visuales para siempre.

        Args:
            observation_id: Observación que se va a borrar; sin ella, se borran todas.

        Returns:
            Cuántas se borraron.
        """
        where = "id = ?" if observation_id is not None else "1 = 1"
        parameters: list[object] = [observation_id] if observation_id is not None else []
        count = self.connection.execute(
            f"SELECT COUNT(*) FROM visual_observations WHERE {where}", parameters
        ).fetchone()[0]
        with self.connection:
            self._overwrite("visual_observations", where, parameters)
            self.connection.execute(f"DELETE FROM visual_observations WHERE {where}", parameters)
        return count

    def _overwrite(self, table: str, where: str, parameters: list[object]) -> None:
        """Sustituye un texto por relleno del mismo tamaño antes de borrar su fila.

        El motor sincronizado no limpia el espacio que libera al borrar: sin esto, el texto
        olvidado seguiría en el archivo y en las copias que se bajen de la nube.

        Args:
            table: Tabla con la columna `content`; siempre es un nombre fijo de este archivo.
            where: Condición de las filas, con marcadores `?`.
            parameters: Valores de los marcadores.
        """
        self.connection.execute(
            f"UPDATE {table} SET content = "
            f"replace(hex(zeroblob(length(CAST(content AS BLOB)))), '00', 'x') WHERE {where}",
            parameters,
        )

    def _delete_exchange(self, message_id: int) -> None:
        """Borra un mensaje y la respuesta que le siguió.

        Args:
            message_id: Mensaje de donde salió un recuerdo.
        """
        next_row = self.connection.execute(
            "SELECT id, role FROM messages WHERE id > ? ORDER BY id LIMIT 1", (message_id,)
        ).fetchone()
        self._overwrite("messages", "id = ?", [message_id])
        self.connection.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        if next_row and next_row[1] == "assistant":
            self._overwrite("messages", "id = ?", [next_row[0]])
            self.connection.execute("DELETE FROM messages WHERE id = ?", (next_row[0],))

    @_serialized
    def active_memories(self) -> list[Memory]:
        """Lee todos los recuerdos vigentes.

        Returns:
            Los recuerdos que no han sido reemplazados.
        """
        rows = self.connection.execute(
            f"SELECT {MEMORY_COLUMNS} FROM memories WHERE superseded_by IS NULL ORDER BY id"
        ).fetchall()
        return [self._to_memory(row) for row in rows]

    @_serialized
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

    @_serialized
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

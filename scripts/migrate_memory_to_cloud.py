"""Copia una sola vez la memoria local a la base en la nube y comprueba que llegó completa.

Se ejecuta con Nova apagada: `.venv/bin/python scripts/migrate_memory_to_cloud.py`.
"""

import hashlib
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import DEFAULT_MEMORY_PATH, Config  # noqa: E402
from services.context.memory_store import MemoryStore  # noqa: E402

TABLES = ("messages", "mood", "memories", "api_usage")
TIME_DECIMALS = 4


def table_fingerprint(connection: object, table: str) -> tuple[int, str]:
    """Resume el contenido de una tabla para compararlo con otra copia.

    Args:
        connection: Conexión con la interfaz de `sqlite3`.
        table: Nombre de la tabla.

    Returns:
        El número de filas y una huella de todo su contenido.
    """
    rows = connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()

    # Las fechas pueden variar en el último decimal al viajar; eso es menos de un microsegundo.
    rounded = [
        tuple(round(value, TIME_DECIMALS) if isinstance(value, float) else value for value in row)
        for row in rows
    ]
    digest = hashlib.sha256(repr(rounded).encode()).hexdigest()
    return len(rows), digest


def main() -> None:
    """Copia las tablas y falla sin tocar nada más si algo no coincide."""
    config = Config()
    settings = config.sync_settings
    if settings is None:
        sys.exit("Faltan TURSO_DATABASE_URL y TURSO_AUTH_TOKEN en el .env.")

    source = sqlite3.connect(f"file:{DEFAULT_MEMORY_PATH}?mode=ro", uri=True)
    cloud = MemoryStore(config.synced_memory_path, sync=settings)

    # Nunca mezcla: si la nube ya tiene datos, no sabría cuáles conservar.
    for table in TABLES:
        count = cloud.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if count:
            sys.exit(f"La nube ya tiene {count} filas en {table}. No copio nada.")

    # Copia cada tabla conservando sus identificadores.
    with cloud.connection:
        for table in TABLES:
            rows = source.execute(f"SELECT * FROM {table}").fetchall()
            if rows:
                marks = ", ".join("?" * len(rows[0]))
                for row in rows:
                    cloud.connection.execute(f"INSERT INTO {table} VALUES ({marks})", row)
    cloud.sync(erase_local_traces=True)

    # Comprueba con una copia nueva, bajada de la nube, que no se perdió nada.
    with tempfile.TemporaryDirectory() as folder:
        fresh = MemoryStore(Path(folder) / "check.db", sync=settings)
        for table in TABLES:
            expected = table_fingerprint(source, table)
            found = table_fingerprint(fresh.connection, table)
            if expected != found:
                sys.exit(f"{table} NO coincide: local {expected[0]} filas, nube {found[0]}.")
            print(f"{table}: {found[0]} filas, huella idéntica")
    print("Migración comprobada.")


if __name__ == "__main__":
    main()

"""Límites de uso de la cámara, aplicados en código para que Nova no pueda saltárselos."""

import time
from collections.abc import Callable
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from services.schemas import PhotoStatus, PhotoUsage

DEFAULT_DAILY_LIMIT = 20
DEFAULT_COOLDOWN_SECONDS = 10.0
DEFAULT_USAGE_PATH = Path(__file__).resolve().parents[2] / "data" / "photo_usage.json"


class PhotoBudgetService:
    """Controla cuántas fotos puede tomar Nova y con qué frecuencia."""

    def __init__(
        self,
        usage_path: Path = DEFAULT_USAGE_PATH,
        daily_limit: int = DEFAULT_DAILY_LIMIT,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        today: Callable[[], date] = date.today,
    ) -> None:
        """Carga el uso guardado.

        Args:
            usage_path: Archivo donde se conserva el conteo del día.
            daily_limit: Fotos permitidas por día.
            cooldown_seconds: Espera mínima entre dos fotos.
            clock: Reloj en segundos; se puede sustituir en las pruebas.
            today: Fecha actual; se puede sustituir en las pruebas.
        """
        self.usage_path = usage_path
        self.daily_limit = daily_limit
        self.cooldown_seconds = cooldown_seconds
        self.clock = clock
        self.today = today
        self.last_photo_at: float | None = None
        self.usage = self._load()

    def check(self) -> PhotoStatus:
        """Comprueba si se puede tomar una foto ahora.

        Returns:
            `granted` si se puede, o el motivo por el que no.
        """
        self._roll_over_day()
        if self.usage.count >= self.daily_limit:
            return "daily_limit"

        is_cooling_down = (
            self.last_photo_at is not None
            and self.clock() - self.last_photo_at < self.cooldown_seconds
        )
        return "cooldown" if is_cooling_down else "granted"

    def remaining(self) -> int:
        """Calcula las fotos que quedan hoy.

        Returns:
            El número de fotos disponibles.
        """
        self._roll_over_day()
        return max(0, self.daily_limit - self.usage.count)

    def record(self) -> None:
        """Cuenta una foto tomada y guarda el conteo en disco."""
        self._roll_over_day()
        self.usage.count += 1
        self.last_photo_at = self.clock()
        self.usage_path.parent.mkdir(parents=True, exist_ok=True)
        self.usage_path.write_text(self.usage.model_dump_json())

    def _roll_over_day(self) -> None:
        """Reinicia el conteo cuando cambia el día."""
        current_day = self.today().isoformat()
        if self.usage.day != current_day:
            self.usage = PhotoUsage(day=current_day)

    def _load(self) -> PhotoUsage:
        """Lee el conteo guardado.

        Returns:
            El uso guardado, o uno vacío si no existe o está dañado.
        """
        current_day = self.today().isoformat()
        try:
            return PhotoUsage.model_validate_json(self.usage_path.read_text())
        except (OSError, ValidationError):
            return PhotoUsage(day=current_day)

"""Registro de lo que gasta Nova en las APIs: tokens de Claude, búsquedas y voz."""

import traceback
from datetime import date, datetime, timedelta

from services.context.memory_store import MemoryStore
from services.schemas import (
    ClaudeUsage,
    UsageDay,
    UsageEvent,
    UsagePurpose,
    UsageRecord,
    UsageServiceTotal,
    VoiceQuota,
)

# Precios de Claude Haiku 5.5 en dólares por millón de tokens, para prompts de hasta 100 mil tokens.
# Si cambias de modelo o de precio, actualízalos: el costo de cada llamada se guarda al registrarla.
INPUT_PRICE = 0.10
CACHE_WRITE_PRICE = 0.125
CACHE_READ_PRICE = 0.01
OUTPUT_PRICE = 0.50
SEARCH_PRICE = 0.01
TOKENS_PER_PRICE_UNIT = 1_000_000

DAYS_SHOWN = 30


class UsageService:
    """Calcula y guarda el costo de cada llamada. Un fallo aquí nunca afecta la conversación."""

    def __init__(self, store: MemoryStore) -> None:
        """Guarda la base de datos.

        Args:
            store: Memoria persistente.
        """
        self.store = store

    def record_claude(self, purpose: UsagePurpose, usage: ClaudeUsage) -> None:
        """Registra una llamada a Claude.

        Args:
            purpose: Para qué fue la llamada.
            usage: Tokens y búsquedas que reportó la API.
        """
        tokens_cost = (
            usage.input_tokens * INPUT_PRICE
            + usage.cache_write_tokens * CACHE_WRITE_PRICE
            + usage.cache_read_tokens * CACHE_READ_PRICE
            + usage.output_tokens * OUTPUT_PRICE
        ) / TOKENS_PER_PRICE_UNIT
        self._save(
            UsageRecord(
                purpose=purpose,
                input_tokens=usage.input_tokens + usage.cache_write_tokens + usage.cache_read_tokens,
                output_tokens=usage.output_tokens,
                searches=usage.searches,
                cost_usd=tokens_cost + usage.searches * SEARCH_PRICE,
            )
        )

    def record_voice(self, credits: int) -> None:
        """Registra una frase de voz. Su costo es cero porque la cubre el plan mensual.

        Args:
            credits: Créditos de ElevenLabs que consumió.
        """
        self._save(UsageRecord(purpose="voice", credits=credits))

    def report(self, voice: VoiceQuota | None) -> UsageEvent:
        """Reúne lo que muestra la vista de gastos.

        Args:
            voice: Créditos de la voz según ElevenLabs, si se pudieron consultar.

        Returns:
            Los totales de hoy y del mes, cada día reciente y el desglose por servicio.
        """
        today = date.today()
        first_shown = today - timedelta(days=DAYS_SHOWN - 1)
        rows = self.store.usage_by_day(first_shown.isoformat())
        month_prefix = today.strftime("%Y-%m")

        # Convierte cada día, incluidos los que no tuvieron gasto, para no dejar huecos en la gráfica.
        days: list[UsageDay] = []
        for offset in range(DAYS_SHOWN):
            day = (first_shown + timedelta(days=offset)).isoformat()
            of_day = [row for row in rows if row.day == day]
            days.append(
                UsageDay(
                    day=day,
                    conversation=sum(row.cost_usd for row in of_day if row.purpose == "conversation"),
                    memory=sum(row.cost_usd for row in of_day if row.purpose == "memory"),
                    search=sum(row.cost_usd for row in of_day if row.purpose == "search"),
                )
            )

        # Desglose del mes en curso: los días anteriores de la gráfica pueden ser de otro mes.
        month_rows = [row for row in rows if row.day.startswith(month_prefix)]
        services = [
            UsageServiceTotal(
                purpose=purpose,
                calls=sum(row.calls for row in month_rows if row.purpose == purpose),
                input_tokens=sum(row.input_tokens for row in month_rows if row.purpose == purpose),
                output_tokens=sum(row.output_tokens for row in month_rows if row.purpose == purpose),
                searches=sum(row.searches for row in month_rows if row.purpose == purpose),
                credits=sum(row.credits for row in month_rows if row.purpose == purpose),
                cost_usd=sum(row.cost_usd for row in month_rows if row.purpose == purpose),
            )
            for purpose in ("conversation", "memory", "search", "voice")
        ]

        return UsageEvent(
            today_usd=sum(row.cost_usd for row in rows if row.day == today.isoformat()),
            month_usd=sum(row.cost_usd for row in month_rows),
            month_name=datetime.now().astimezone().strftime("%Y-%m"),
            days=days,
            services=services,
            voice=voice,
        )

    def _save(self, record: UsageRecord) -> None:
        """Guarda un registro, sin dejar que un error interrumpa a Nova.

        Args:
            record: Registro que se va a guardar.
        """
        try:
            self.store.add_usage(record)
        except Exception:
            traceback.print_exc()

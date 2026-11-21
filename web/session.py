"""Acceso a la versión web: contraseña, cookie de sesión firmada y origen del WebSocket.

La cookie solo lleva su vencimiento y una firma; no contiene ningún secreto.
"""

import hashlib
import hmac
import time
from urllib.parse import urlsplit

from web.settings import WebSecrets

SESSION_COOKIE = "nova_session"
SESSION_SECONDS = 30 * 24 * 3600


class SessionGuard:
    """Abre y comprueba sesiones con los secretos de la versión web."""

    def __init__(self, secrets: WebSecrets) -> None:
        """Deriva la clave que firma las sesiones.

        Incluye la contraseña: al cambiarla, todas las sesiones abiertas dejan de servir.

        Args:
            secrets: Secretos de la versión web.
        """
        self.password = secrets.password.get_secret_value().encode()
        material = f"{secrets.session_secret.get_secret_value()}\0{secrets.password.get_secret_value()}"
        self.signing_key = hashlib.sha256(material.encode()).digest()

    def password_matches(self, attempt: str) -> bool:
        """Compara la contraseña en tiempo constante.

        Args:
            attempt: Lo que escribió el usuario.

        Returns:
            Si coincide.
        """
        return hmac.compare_digest(attempt.encode(), self.password)

    def create(self, now: float | None = None) -> str:
        """Crea el valor de la cookie: su vencimiento y una firma.

        Args:
            now: Momento actual en segundos; se puede fijar en las pruebas.

        Returns:
            El valor de la cookie.
        """
        expires = str(int(_current_time(now) + SESSION_SECONDS))
        return f"{expires}.{self._sign(expires)}"

    def is_valid(self, value: str | None, now: float | None = None) -> bool:
        """Comprueba la firma y el vencimiento de una cookie.

        Args:
            value: Valor de la cookie, si el navegador la mandó.
            now: Momento actual en segundos; se puede fijar en las pruebas.

        Returns:
            Si la sesión es auténtica y sigue vigente.
        """
        expires, _, signature = (value or "").partition(".")
        if not expires.isdigit():
            return False
        if not hmac.compare_digest(signature, self._sign(expires)):
            return False
        return int(expires) > _current_time(now)

    def _sign(self, expires: str) -> str:
        """Firma el vencimiento de una sesión.

        Args:
            expires: Vencimiento en segundos, como texto.

        Returns:
            La firma en hexadecimal.
        """
        return hmac.new(self.signing_key, expires.encode(), hashlib.sha256).hexdigest()


def origin_matches_host(origin: str | None, hosts: list[str | None]) -> bool:
    """Acepta el WebSocket solo si lo abre la propia página de Nova.

    Args:
        origin: Encabezado `Origin` del navegador.
        hosts: Dominios con los que llegó la petición (`Host` y el reenviado por Vercel).

    Returns:
        Si el origen es este mismo sitio.
    """
    if not origin:
        return False
    origin_host = urlsplit(origin).netloc
    return origin_host in [host for host in hosts if host]


def _current_time(now: float | None) -> float:
    """Devuelve el momento fijado o el actual.

    Args:
        now: Momento fijado en las pruebas, o `None` para usar el reloj.

    Returns:
        Segundos desde la época.
    """
    return time.time() if now is None else now

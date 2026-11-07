"""Acceso a la Mac con sus librerías del sistema: la app al frente, su captura y el tecleo."""

import base64
import ctypes
import subprocess
import tempfile
import threading
import time
from ctypes import byref, c_bool, c_int, c_int64, c_long, c_uint16, c_void_p
from pathlib import Path

from services.schemas import FrontApp, TypingStatus

FRAMEWORKS = "/System/Library/Frameworks"
UTF8_ENCODING = 0x08000100
CF_NUMBER_INT64 = 4
ON_SCREEN_WINDOWS = 1 | 16
NORMAL_WINDOW_LAYER = 0
HID_STATE = 1
SESSION_EVENT_TAP = 1
ESCAPE_KEY = 53
# Clic izquierdo, clic derecho, mover, arrastrar y rueda.
USER_MOUSE_EVENTS = (1, 3, 5, 6, 22)
SECONDS_PER_CHARACTER = 0.025
# Preguntar por la app al frente lanza un proceso: se hace cada pocas letras, no en cada una.
CHARACTERS_PER_APP_CHECK = 8
CAPTURE_MAX_PIXELS = "1280"
COMMAND_TIMEOUT_SECONDS = 10

_core_foundation = ctypes.CDLL(f"{FRAMEWORKS}/CoreFoundation.framework/CoreFoundation")
_core_graphics = ctypes.CDLL(f"{FRAMEWORKS}/CoreGraphics.framework/CoreGraphics")
_application_services = ctypes.CDLL(
    f"{FRAMEWORKS}/ApplicationServices.framework/ApplicationServices"
)
_carbon = ctypes.CDLL(f"{FRAMEWORKS}/Carbon.framework/Carbon")

# Sin declarar los tipos, ctypes corta los apuntadores a 32 bits y la app truena.
_core_foundation.CFArrayGetCount.argtypes = [c_void_p]
_core_foundation.CFArrayGetCount.restype = c_long
_core_foundation.CFArrayGetValueAtIndex.argtypes = [c_void_p, c_long]
_core_foundation.CFArrayGetValueAtIndex.restype = c_void_p
_core_foundation.CFDictionaryGetValue.argtypes = [c_void_p, c_void_p]
_core_foundation.CFDictionaryGetValue.restype = c_void_p
_core_foundation.CFDictionaryCreate.argtypes = [
    c_void_p,
    c_void_p,
    c_void_p,
    c_long,
    c_void_p,
    c_void_p,
]
_core_foundation.CFDictionaryCreate.restype = c_void_p
_core_foundation.CFNumberGetValue.argtypes = [c_void_p, c_int, c_void_p]
_core_foundation.CFNumberGetValue.restype = c_bool
_core_foundation.CFRelease.argtypes = [c_void_p]
_core_graphics.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
_core_graphics.CGWindowListCopyWindowInfo.restype = c_void_p
_core_graphics.CGPreflightScreenCaptureAccess.restype = c_bool
_core_graphics.CGRequestScreenCaptureAccess.restype = c_bool
_core_graphics.CGEventSourceSecondsSinceLastEventType.argtypes = [c_int, ctypes.c_uint32]
_core_graphics.CGEventSourceSecondsSinceLastEventType.restype = ctypes.c_double
_core_graphics.CGEventSourceKeyState.argtypes = [c_int, ctypes.c_uint16]
_core_graphics.CGEventSourceKeyState.restype = c_bool
_core_graphics.CGEventCreateKeyboardEvent.argtypes = [c_void_p, ctypes.c_uint16, c_bool]
_core_graphics.CGEventCreateKeyboardEvent.restype = c_void_p
_core_graphics.CGEventSetFlags.argtypes = [c_void_p, ctypes.c_uint64]
_core_graphics.CGEventKeyboardSetUnicodeString.argtypes = [c_void_p, c_long, c_void_p]
_core_graphics.CGEventPost.argtypes = [c_int, c_void_p]
_application_services.AXIsProcessTrustedWithOptions.argtypes = [c_void_p]
_application_services.AXIsProcessTrustedWithOptions.restype = c_bool
_carbon.IsSecureEventInputEnabled.restype = c_bool


def _lsappinfo_value(output: str, key: str) -> str:
    """Extrae un valor de la salida de `lsappinfo`.

    Args:
        output: Texto con líneas `"clave"="valor"` o `"clave"=123`.
        key: Clave buscada.

    Returns:
        El valor, o una cadena vacía si no aparece.
    """
    for line in output.splitlines():
        name, _, value = line.partition("=")
        if name.strip().strip('"') == key:
            return value.strip().strip('"')
    return ""


def front_app() -> FrontApp | None:
    """Pregunta qué app está al frente. No requiere permisos del sistema.

    Returns:
        La app, o `None` si no se pudo saber.
    """
    try:
        front = subprocess.run(
            ["lsappinfo", "front"],
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=True,
        ).stdout.strip()
        info = subprocess.run(
            ["lsappinfo", "info", "-only", "name", "-only", "bundleid", "-only", "pid", front],
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=True,
        ).stdout
        return FrontApp(
            pid=int(_lsappinfo_value(info, "pid")),
            bundle_id=_lsappinfo_value(info, "CFBundleIdentifier"),
            name=_lsappinfo_value(info, "LSDisplayName"),
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def secure_input_active() -> bool:
    """Comprueba si hay un campo de contraseña activo.

    Returns:
        Si el sistema está protegiendo lo que se teclea.
    """
    return _carbon.IsSecureEventInputEnabled()


def has_accessibility_permission(prompt: bool) -> bool:
    """Comprueba el permiso de Accesibilidad, necesario para teclear.

    Args:
        prompt: Si, de no tenerlo, macOS debe mostrar su aviso para concederlo.

    Returns:
        Si ya está concedido.
    """
    key = c_void_p.in_dll(_application_services, "kAXTrustedCheckOptionPrompt")
    value = c_void_p.in_dll(
        _core_foundation, "kCFBooleanTrue" if prompt else "kCFBooleanFalse"
    )
    # La función exige un diccionario del sistema: solo se construye en este punto.
    options = _core_foundation.CFDictionaryCreate(
        None,
        byref(key),
        byref(value),
        1,
        ctypes.addressof(ctypes.c_char.in_dll(_core_foundation, "kCFTypeDictionaryKeyCallBacks")),
        ctypes.addressof(
            ctypes.c_char.in_dll(_core_foundation, "kCFTypeDictionaryValueCallBacks")
        ),
    )
    try:
        return _application_services.AXIsProcessTrustedWithOptions(options)
    finally:
        _core_foundation.CFRelease(options)


def has_screen_permission(prompt: bool) -> bool:
    """Comprueba el permiso de Grabación de pantalla, necesario para ver la ventana.

    Args:
        prompt: Si, de no tenerlo, macOS debe mostrar su aviso para concederlo.

    Returns:
        Si ya está concedido.
    """
    if _core_graphics.CGPreflightScreenCaptureAccess():
        return True
    return _core_graphics.CGRequestScreenCaptureAccess() if prompt else False


def _window_number(window: int, key_name: str) -> int | None:
    """Lee un número de la descripción de una ventana.

    Args:
        window: Descripción que entrega el sistema.
        key_name: Nombre de la constante del sistema con la clave.

    Returns:
        El valor, o `None` si no aparece.
    """
    key = c_void_p.in_dll(_core_graphics, key_name)
    number = _core_foundation.CFDictionaryGetValue(window, key)
    if not number:
        return None
    value = c_int64()
    _core_foundation.CFNumberGetValue(number, CF_NUMBER_INT64, byref(value))
    return value.value


def front_window_id(pid: int) -> int | None:
    """Busca la ventana normal que está más al frente de una app.

    Args:
        pid: Proceso de la app.

    Returns:
        El número de ventana, o `None` si no tiene ninguna en pantalla.
    """
    windows = _core_graphics.CGWindowListCopyWindowInfo(ON_SCREEN_WINDOWS, 0)
    if not windows:
        return None
    try:
        # La lista viene ordenada de la ventana de más al frente a la de más atrás.
        for index in range(_core_foundation.CFArrayGetCount(windows)):
            window = _core_foundation.CFArrayGetValueAtIndex(windows, index)
            is_owned = _window_number(window, "kCGWindowOwnerPID") == pid
            if is_owned and _window_number(window, "kCGWindowLayer") == NORMAL_WINDOW_LAYER:
                return _window_number(window, "kCGWindowNumber")
    finally:
        _core_foundation.CFRelease(windows)
    return None


def capture_window(window_id: int) -> str | None:
    """Toma una captura de una sola ventana, sin dejar el archivo en disco.

    Args:
        window_id: Número de la ventana.

    Returns:
        La imagen como data URL, o `None` si no se pudo capturar.
    """
    with tempfile.TemporaryDirectory(prefix="nova-window-") as folder:
        path = Path(folder) / "window.jpg"
        try:
            subprocess.run(
                ["screencapture", "-x", "-o", "-t", "jpg", f"-l{window_id}", str(path)],
                capture_output=True,
                timeout=COMMAND_TIMEOUT_SECONDS,
                check=True,
            )
            subprocess.run(
                ["sips", "-Z", CAPTURE_MAX_PIXELS, str(path)],
                capture_output=True,
                timeout=COMMAND_TIMEOUT_SECONDS,
                check=True,
            )
            encoded = base64.b64encode(path.read_bytes()).decode()
        except (OSError, subprocess.SubprocessError):
            return None
    return f"data:image/jpeg;base64,{encoded}"


def _user_took_over(started_at: float) -> bool:
    """Comprueba si moví el mouse o presioné Esc desde que empezó a teclear.

    Args:
        started_at: Momento en que empezó, de `time.monotonic`.

    Returns:
        Si hay que detenerse.
    """
    if _core_graphics.CGEventSourceKeyState(HID_STATE, ESCAPE_KEY):
        return True
    elapsed = time.monotonic() - started_at
    return any(
        _core_graphics.CGEventSourceSecondsSinceLastEventType(HID_STATE, event) < elapsed
        for event in USER_MOUSE_EVENTS
    )


def _post_character(character: str) -> None:
    """Teclea un carácter sin importar la distribución del teclado.

    Args:
        character: Carácter ya revisado; nunca un salto de línea.
    """
    encoded = character.encode("utf-16-le")
    units = (c_uint16 * (len(encoded) // 2)).from_buffer_copy(encoded)
    for is_down in (True, False):
        event = _core_graphics.CGEventCreateKeyboardEvent(None, 0, is_down)
        # Sin esto, una tecla que yo tenga presionada podría convertirse en un atajo.
        _core_graphics.CGEventSetFlags(event, 0)
        _core_graphics.CGEventKeyboardSetUnicodeString(event, len(units), units)
        _core_graphics.CGEventPost(SESSION_EVENT_TAP, event)
        _core_foundation.CFRelease(event)


def type_text(text: str, app: FrontApp, stop: threading.Event) -> TypingStatus:
    """Teclea un texto. Se detiene si tomo el control o si cambia la app al frente.

    Args:
        text: Texto ya revisado; debe venir sin caracteres de control, para que no exista Enter.
        app: App donde debe escribirse.
        stop: Permite cortar desde afuera, por ejemplo si interrumpen a Nova.

    Returns:
        Cómo terminó.
    """
    started_at = time.monotonic()
    for index, character in enumerate(text):
        if stop.is_set() or _user_took_over(started_at):
            return "stopped"
        if index % CHARACTERS_PER_APP_CHECK == 0:
            current = front_app()
            if current is None or current.pid != app.pid:
                return "app_changed"
            if secure_input_active():
                return "secure_field"
        _post_character(character)
        time.sleep(SECONDS_PER_CHARACTER)
    return "written"

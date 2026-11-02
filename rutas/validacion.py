"""Funciones de limpieza y validación de campos.

Se usan igual desde los gestores (alta manual) y desde la carga por lote,
para que una misma regla no tenga dos implementaciones distintas.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

from rutas.excepciones import DatoInvalidoError

FORMATOS_ID: dict[str, re.Pattern[str]] = {
    "id_cliente": re.compile(r"^CLI-\d{3,}$"),
    "id_transportista": re.compile(r"^TRA-\d{2,}$"),
    "id_ruta": re.compile(r"^RUTA-\d{2,}$"),
    "folio_pedido": re.compile(r"^PED-\d{4,}$"),
}

_ENTERO = re.compile(r"^\d+$")


def limpiar_texto(valor: object, campo: str, obligatorio: bool = True) -> str:
    """Quita espacios sobrantes; rechaza vacío si el campo es obligatorio."""
    texto = "" if valor is None else " ".join(str(valor).split())
    if obligatorio and not texto:
        raise DatoInvalidoError(campo, valor, "campo obligatorio vacío")
    return texto


def normalizar_id(valor: object, campo: str) -> str:
    """Pasa el id a mayúsculas sin espacios y valida su formato.

    ``" cli-010 "`` se limpia a ``"CLI-010"``; ``"CLIENTE-1"`` se rechaza.
    """
    texto = limpiar_texto(valor, campo).replace(" ", "").upper()
    if not FORMATOS_ID[campo].match(texto):
        raise DatoInvalidoError(campo, valor, "formato de identificador inválido")
    return texto


def clave_lugar(lugar: str) -> str:
    """Clave de comparación de lugares: sin acentos ni mayúsculas.

    Así ``"León"`` y ``"leon"`` se consideran el mismo lugar al comparar
    trayectos, aunque en el CSV se conserve el texto original.
    """
    sin_acentos = unicodedata.normalize("NFKD", lugar)
    sin_acentos = "".join(c for c in sin_acentos if not unicodedata.combining(c))
    return sin_acentos.casefold().strip()


def a_entero_positivo(valor: object, campo: str = "cantidad") -> int:
    """Convierte a ``int`` > 0 sin redondear decimales.

    Acepta ``int`` o texto de solo dígitos (lo que llega del CSV).
    Rechaza ``bool``, ``float``, ``"12.5"``, ``"abc"``, ``0`` y negativos.
    """
    if isinstance(valor, bool):
        raise DatoInvalidoError(campo, valor, "debe ser un entero, no booleano")
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        raise DatoInvalidoError(campo, valor, "campo obligatorio vacío")
    if isinstance(valor, int):
        numero = valor
    elif isinstance(valor, str) and _ENTERO.match(valor.strip()):
        numero = int(valor.strip())
    else:
        raise DatoInvalidoError(campo, valor, "debe ser un número entero")
    if numero <= 0:
        raise DatoInvalidoError(campo, valor, "debe ser mayor que cero")
    return numero


def a_decimal_positivo(valor: object, campo: str) -> float:
    """Convierte a ``float`` > 0 (distancia y tiempo de la ruta)."""
    if isinstance(valor, bool):
        raise DatoInvalidoError(campo, valor, "debe ser numérico")
    try:
        numero = float(str(valor).strip()) if isinstance(valor, str) else float(valor)
    except (TypeError, ValueError):
        raise DatoInvalidoError(campo, valor, "debe ser numérico") from None
    if not numero > 0:  # también descarta NaN
        raise DatoInvalidoError(campo, valor, "debe ser mayor que cero")
    return numero


def a_fecha(valor: object, campo: str = "fecha_pedido") -> date:
    """Convierte texto ``AAAA-MM-DD`` (ISO 8601) o ``date`` a ``date``."""
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(limpiar_texto(valor, campo))
    except ValueError:
        raise DatoInvalidoError(campo, valor, "fecha inválida, se espera AAAA-MM-DD") from None


def validar_trayecto(origen: object, destino: object) -> tuple[str, str]:
    """Limpia origen y destino y exige que sean distintos (INT-10, INT-11)."""
    o = limpiar_texto(origen, "origen")
    d = limpiar_texto(destino, "destino")
    if clave_lugar(o) == clave_lugar(d):
        raise DatoInvalidoError("destino", destino, "origen y destino no pueden ser iguales")
    return o, d

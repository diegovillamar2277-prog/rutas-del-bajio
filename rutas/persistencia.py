"""Lectura y escritura de los archivos CSV.

Un solo lugar decide la codificación y el modo de apertura, para que
acentos y campos con comas sobrevivan el ciclo guardar -> reabrir (INT-17).
"""

from __future__ import annotations

import csv
import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

CODIFICACION_LECTURA = "utf-8-sig"  # tolera el BOM que agrega Excel
CODIFICACION_ESCRITURA = "utf-8"


def leer_csv(ruta: Path) -> list[tuple[int, dict[str, str]]]:
    """Devuelve ``(numero_de_linea, fila)`` por registro.

    Si el archivo no existe o está vacío devuelve ``[]``: el sistema arranca
    sin datos en lugar de fallar.
    """
    if not ruta.exists() or ruta.stat().st_size == 0:
        return []
    with ruta.open(encoding=CODIFICACION_LECTURA, newline="") as f:
        lector = csv.DictReader(f)
        return [(lector.line_num, dict(fila)) for fila in lector]


def escribir_csv(ruta: Path, columnas: Sequence[str],
                 filas: Iterable[Mapping[str, object]]) -> None:
    """Escribe el archivo completo de forma atómica.

    Primero se escribe un temporal y luego se reemplaza el original con
    ``os.replace``: si algo falla a la mitad, el CSV anterior queda intacto.
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(ruta.suffix + ".tmp")
    with temporal.open("w", encoding=CODIFICACION_ESCRITURA, newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=list(columnas))
        escritor.writeheader()
        escritor.writerows(filas)
    os.replace(temporal, ruta)

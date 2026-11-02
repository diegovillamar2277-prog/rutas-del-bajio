"""Carga por lote de pedidos desde un CSV externo.

Dos niveles de problema:

* **Problema de archivo** (no existe, no es UTF-8, vacío, encabezados
  duplicados o faltantes): no se puede confiar en ninguna fila, así que se
  lanza ``ArchivoLoteError`` y no se guarda nada.
* **Problema de fila** (un dato inválido): solo se rechaza esa fila, se
  documenta en el archivo de rechazos y las demás filas sí se cargan.

El archivo de entrada solo se abre en modo lectura: nunca se modifica.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from rutas.estados import EstadoPedido
from rutas.excepciones import ArchivoLoteError, DatoInvalidoError
from rutas.persistencia import CODIFICACION_LECTURA, escribir_csv
from rutas.sistema import SistemaRutas
from rutas.validacion import (
    a_entero_positivo,
    a_fecha,
    limpiar_texto,
    normalizar_id,
    validar_trayecto,
)

COLUMNAS_OBLIGATORIAS = ("folio_pedido", "id_cliente", "producto", "cantidad",
                         "origen", "destino", "fecha_pedido")
COLUMNAS_OPCIONALES = ("id_ruta", "estado")
COLUMNAS_RECHAZOS = ("linea", "folio_pedido", "campo", "valor_original", "motivo")


@dataclass(frozen=True)
class Rechazo:
    """Un problema detectado en una fila del lote."""

    linea: int
    folio_pedido: str
    campo: str
    valor_original: str
    motivo: str

    def to_dict(self) -> dict[str, object]:
        return {c: getattr(self, c) for c in COLUMNAS_RECHAZOS}


@dataclass
class ResultadoLote:
    """Resumen de la importación."""

    filas_leidas: int = 0
    aceptados: list[str] = field(default_factory=list)
    rechazos: list[Rechazo] = field(default_factory=list)

    @property
    def filas_rechazadas(self) -> int:
        return len({r.linea for r in self.rechazos})


def _leer_encabezado(archivo: Path) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """Valida el archivo como un todo y devuelve encabezado y filas crudas."""
    if not archivo.is_file():
        raise ArchivoLoteError(f"no existe el archivo {archivo}")
    try:
        texto = archivo.read_bytes().decode(CODIFICACION_LECTURA)
    except UnicodeDecodeError as error:
        raise ArchivoLoteError(f"el archivo no está en UTF-8: {error}") from None
    lector = csv.reader(io.StringIO(texto, newline=""))
    encabezado = next(lector, None)
    if not encabezado or not any(c.strip() for c in encabezado):
        raise ArchivoLoteError("archivo vacío o sin encabezado")
    encabezado = [c.strip().lower() for c in encabezado]
    repetidas = sorted({c for c in encabezado if encabezado.count(c) > 1})
    if repetidas:
        raise ArchivoLoteError(f"encabezados duplicados: {repetidas}")
    faltantes = [c for c in COLUMNAS_OBLIGATORIAS if c not in encabezado]
    if faltantes:
        raise ArchivoLoteError(f"faltan columnas obligatorias: {faltantes}")
    filas = [(lector.line_num, fila) for fila in lector if any(c.strip() for c in fila)]
    return encabezado, filas


def importar_pedidos(sistema: SistemaRutas, archivo_lote: Path | str,
                     archivo_rechazos: Optional[Path | str] = None) -> ResultadoLote:
    """Importa pedidos válidos y escribe ``rechazos_pedidos.csv`` con los inválidos."""
    archivo_lote = Path(archivo_lote)
    archivo_rechazos = Path(archivo_rechazos or archivo_lote.with_name("rechazos_pedidos.csv"))
    encabezado, filas = _leer_encabezado(archivo_lote)

    resultado = ResultadoLote(filas_leidas=len(filas))
    validos = []
    vistos: dict[str, int] = {}  # folio -> línea donde apareció primero

    for linea, valores in filas:
        folio_crudo = valores[0].strip() if valores else ""
        if len(valores) != len(encabezado):
            resultado.rechazos.append(Rechazo(
                linea, folio_crudo, "(fila)", ",".join(valores),
                f"tiene {len(valores)} columnas, se esperaban {len(encabezado)}"))
            continue
        fila = dict(zip(encabezado, valores))
        folio_crudo = fila["folio_pedido"]
        errores: list[Rechazo] = []

        def revisar(funcion: Callable[[], object]) -> object:
            """Ejecuta una validación y registra el error sin detener la fila."""
            try:
                return funcion()
            except DatoInvalidoError as error:
                errores.append(Rechazo(linea, folio_crudo, error.campo,
                                       fila.get(error.campo, ""), error.motivo))
                return None

        folio = revisar(lambda: normalizar_id(fila["folio_pedido"], "folio_pedido"))
        id_cliente = revisar(lambda: normalizar_id(fila["id_cliente"], "id_cliente"))
        revisar(lambda: limpiar_texto(fila["producto"], "producto"))
        revisar(lambda: a_entero_positivo(fila["cantidad"]))
        trayecto = revisar(lambda: validar_trayecto(fila["origen"], fila["destino"]))
        revisar(lambda: a_fecha(fila["fecha_pedido"]))
        revisar(lambda: _estado_inicial(fila.get("estado", "")))

        if folio is not None:
            if sistema.pedidos.buscar(folio) is not None:
                errores.append(Rechazo(linea, folio_crudo, "folio_pedido", folio_crudo,
                                       "el folio ya existe en pedidos.csv"))
            elif folio in vistos:
                errores.append(Rechazo(linea, folio_crudo, "folio_pedido", folio_crudo,
                                       f"folio repetido en el lote (línea {vistos[folio]})"))
            vistos.setdefault(folio, linea)
        if id_cliente is not None and sistema.clientes.buscar(id_cliente) is None:
            errores.append(Rechazo(linea, folio_crudo, "id_cliente", fila["id_cliente"],
                                   "el cliente no existe"))
        id_ruta = fila.get("id_ruta", "").strip()
        if id_ruta and trayecto is not None:
            ruta = sistema.rutas.buscar(id_ruta)
            if ruta is None:
                errores.append(Rechazo(linea, folio_crudo, "id_ruta", id_ruta, "la ruta no existe"))
            elif not ruta.cubre(*trayecto):
                errores.append(Rechazo(linea, folio_crudo, "id_ruta", id_ruta,
                                       "origen/destino no coinciden con la ruta"))

        if errores:
            resultado.rechazos.extend(errores)
            continue
        validos.append(sistema.pedidos.construir_pedido(
            folio, id_cliente, fila["producto"], fila["cantidad"], fila["origen"],
            fila["destino"], fila["fecha_pedido"], id_ruta or None))

    if validos:
        sistema.pedidos.agregar_lote(validos)
    resultado.aceptados = [p.folio_pedido for p in validos]
    escribir_csv(archivo_rechazos, COLUMNAS_RECHAZOS, (r.to_dict() for r in resultado.rechazos))
    return resultado


def _estado_inicial(valor: str) -> EstadoPedido:
    """Un pedido importado solo puede entrar como ``pendiente``.

    Importar un pedido ``en_transito`` o ``entregado`` saltaría la máquina
    de estados, así que se rechaza.
    """
    texto = valor.strip().lower()
    if texto in ("", EstadoPedido.PENDIENTE.value):
        return EstadoPedido.PENDIENTE
    raise DatoInvalidoError("estado", valor, "un pedido importado solo puede ser pendiente")

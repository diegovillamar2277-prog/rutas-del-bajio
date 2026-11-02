"""Máquina de estados del pedido.

Las transiciones permitidas viven en un solo diccionario. Ninguna otra
parte del código decide si un cambio de estado es válido.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from rutas.excepciones import TransicionInvalidaError

if TYPE_CHECKING:
    from rutas.modelos import Pedido


class EstadoPedido(str, Enum):
    """Estados del ciclo de vida de un pedido."""

    PENDIENTE = "pendiente"
    EN_TRANSITO = "en_transito"
    ENTREGADO = "entregado"
    CANCELADO = "cancelado"


TRANSICIONES: dict[EstadoPedido, frozenset[EstadoPedido]] = {
    EstadoPedido.PENDIENTE: frozenset({EstadoPedido.EN_TRANSITO, EstadoPedido.CANCELADO}),
    EstadoPedido.EN_TRANSITO: frozenset({EstadoPedido.ENTREGADO}),
    EstadoPedido.ENTREGADO: frozenset(),   # estado final
    EstadoPedido.CANCELADO: frozenset(),   # estado final
}

ESTADOS_ACTIVOS = frozenset({EstadoPedido.PENDIENTE, EstadoPedido.EN_TRANSITO})


def validar_transicion(pedido: Pedido, destino: EstadoPedido) -> None:
    """Lanza ``TransicionInvalidaError`` si ``pedido`` no puede pasar a ``destino``.

    Además de la tabla, aplica la guarda de negocio: no se despacha
    (``en_transito``) un pedido sin ruta asignada (INT-05).
    """
    actual = pedido.estado
    if destino not in TRANSICIONES[actual]:
        raise TransicionInvalidaError(
            f"{pedido.folio_pedido}: no se permite {actual.value} -> {destino.value}"
        )
    if destino is EstadoPedido.EN_TRANSITO and pedido.ruta is None:
        raise TransicionInvalidaError(
            f"{pedido.folio_pedido}: no se puede despachar sin ruta asignada"
        )

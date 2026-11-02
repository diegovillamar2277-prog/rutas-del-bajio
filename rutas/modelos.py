"""Entidades del dominio: Cliente, Transportista, Ruta y Pedido.

Composición: en memoria, ``Ruta`` guarda el objeto ``Transportista`` y
``Pedido`` guarda los objetos ``Cliente`` y ``Ruta``. En el CSV solo se
escriben sus identificadores (``to_dict``). Los gestores resuelven los ids
a objetos al cargar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from rutas.estados import EstadoPedido
from rutas.validacion import (
    a_decimal_positivo,
    a_entero_positivo,
    a_fecha,
    clave_lugar,
    limpiar_texto,
    normalizar_id,
    validar_trayecto,
)


@dataclass
class Cliente:
    """Cliente que solicita pedidos."""

    COLUMNAS = ("id_cliente", "nombre", "ciudad", "telefono")

    id_cliente: str
    nombre: str
    ciudad: str
    telefono: str  # str: conserva ceros a la izquierda y formato

    def __post_init__(self) -> None:
        self.id_cliente = normalizar_id(self.id_cliente, "id_cliente")
        self.nombre = limpiar_texto(self.nombre, "nombre")
        self.ciudad = limpiar_texto(self.ciudad, "ciudad")
        self.telefono = limpiar_texto(self.telefono, "telefono")

    def to_dict(self) -> dict[str, str]:
        """Fila para ``clientes.csv``."""
        return {c: getattr(self, c) for c in self.COLUMNAS}


@dataclass
class Transportista:
    """Transportista responsable de una o varias rutas."""

    COLUMNAS = ("id_transportista", "nombre")

    id_transportista: str
    nombre: str

    def __post_init__(self) -> None:
        self.id_transportista = normalizar_id(self.id_transportista, "id_transportista")
        self.nombre = limpiar_texto(self.nombre, "nombre")

    def to_dict(self) -> dict[str, str]:
        """Fila para ``transportistas.csv``."""
        return {c: getattr(self, c) for c in self.COLUMNAS}


@dataclass
class Ruta:
    """Trayecto origen-destino operado por un transportista."""

    COLUMNAS = ("id_ruta", "origen", "destino", "distancia_km",
                "tiempo_estimado_horas", "id_transportista")

    id_ruta: str
    origen: str
    destino: str
    distancia_km: float
    tiempo_estimado_horas: float
    transportista: Transportista

    def __post_init__(self) -> None:
        self.id_ruta = normalizar_id(self.id_ruta, "id_ruta")
        self.origen, self.destino = validar_trayecto(self.origen, self.destino)
        self.distancia_km = a_decimal_positivo(self.distancia_km, "distancia_km")
        self.tiempo_estimado_horas = a_decimal_positivo(
            self.tiempo_estimado_horas, "tiempo_estimado_horas")

    def cubre(self, origen: str, destino: str) -> bool:
        """``True`` si la ruta va exactamente de ``origen`` a ``destino``."""
        return (clave_lugar(self.origen) == clave_lugar(origen)
                and clave_lugar(self.destino) == clave_lugar(destino))

    def to_dict(self) -> dict[str, object]:
        """Fila para ``rutas.csv``; del transportista solo guarda el id."""
        return {
            "id_ruta": self.id_ruta,
            "origen": self.origen,
            "destino": self.destino,
            "distancia_km": self.distancia_km,
            "tiempo_estimado_horas": self.tiempo_estimado_horas,
            "id_transportista": self.transportista.id_transportista,
        }


@dataclass
class Pedido:
    """Pedido de un cliente; su estado solo cambia vía ``GestorPedidos``."""

    COLUMNAS = ("folio_pedido", "id_cliente", "producto", "cantidad", "origen",
                "destino", "fecha_pedido", "estado", "id_ruta")

    folio_pedido: str
    cliente: Cliente
    producto: str
    cantidad: int
    origen: str
    destino: str
    fecha_pedido: date = field(default_factory=date.today)
    ruta: Optional[Ruta] = None
    _estado: EstadoPedido = field(default=EstadoPedido.PENDIENTE, repr=False)

    def __post_init__(self) -> None:
        self.folio_pedido = normalizar_id(self.folio_pedido, "folio_pedido")
        self.producto = limpiar_texto(self.producto, "producto")
        self.cantidad = a_entero_positivo(self.cantidad)
        self.origen, self.destino = validar_trayecto(self.origen, self.destino)
        self.fecha_pedido = a_fecha(self.fecha_pedido)
        self._estado = EstadoPedido(self._estado)

    @property
    def estado(self) -> EstadoPedido:
        """Estado actual. Es de solo lectura: no tiene *setter*."""
        return self._estado

    def to_dict(self) -> dict[str, object]:
        """Fila para ``pedidos.csv``; cliente y ruta se guardan como ids."""
        return {
            "folio_pedido": self.folio_pedido,
            "id_cliente": self.cliente.id_cliente,
            "producto": self.producto,
            "cantidad": self.cantidad,
            "origen": self.origen,
            "destino": self.destino,
            "fecha_pedido": self.fecha_pedido.isoformat(),
            "estado": self._estado.value,
            "id_ruta": self.ruta.id_ruta if self.ruta else "",
        }

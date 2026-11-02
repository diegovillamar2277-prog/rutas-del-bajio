"""Punto de entrada: arma los gestores, los conecta y los carga en orden."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from rutas.estados import EstadoPedido
from rutas.gestores import (
    Descarte,
    GestorClientes,
    GestorPedidos,
    GestorRutas,
    GestorTransportistas,
)
from rutas.modelos import Pedido, Ruta


class SistemaRutas:
    """Fachada del sistema Rutas del Bajío sobre un directorio de CSV."""

    def __init__(self, directorio: Path | str, cargar: bool = True) -> None:
        self.directorio = Path(directorio)
        self.transportistas = GestorTransportistas(self.directorio)
        self.clientes = GestorClientes(self.directorio)
        self.rutas = GestorRutas(self.directorio, self.transportistas)
        self.pedidos = GestorPedidos(self.directorio, self.clientes, self.rutas)
        self._conectar_dependencias()
        if cargar:
            self.cargar()

    def _conectar_dependencias(self) -> None:
        """Ganchos de eliminación restrictiva (INT-16) e integridad de rutas (INT-06)."""
        self.transportistas.dependientes = lambda id_t: [
            r.id_ruta for r in self.rutas.listar()
            if r.transportista.id_transportista == id_t]
        self.clientes.dependientes = lambda id_c: [
            p.folio_pedido for p in self.pedidos.de_cliente(id_c)]
        # Cualquier pedido que apunte a la ruta la bloquea: si se borrara con
        # pedidos entregados, su id_ruta quedaría roto en pedidos.csv.
        self.rutas.dependientes = lambda id_r: [
            p.folio_pedido for p in self.pedidos.de_ruta(id_r)]
        self.rutas.pedidos_activos = lambda id_r: self.pedidos.de_ruta(id_r, solo_activos=True)

    def cargar(self) -> None:
        """Carga en el orden de dependencias (INT-18).

        Transportistas y clientes no dependen de nadie; rutas necesitan a los
        transportistas y pedidos necesitan clientes y rutas.
        """
        for gestor in (self.transportistas, self.clientes, self.rutas, self.pedidos):
            gestor.cargar()

    @property
    def descartadas(self) -> list[Descarte]:
        """Filas de los CSV del sistema que no pasaron la validación al cargar."""
        return [d for g in (self.transportistas, self.clientes, self.rutas, self.pedidos)
                for d in g.descartadas]

    # ---------- consultas de composición ----------
    def pedidos_de_cliente(self, id_cliente: str) -> list[Pedido]:
        """INT-12: todos los pedidos del cliente, con cualquier destino."""
        cliente = self.clientes.obtener(id_cliente)
        return self.pedidos.de_cliente(cliente.id_cliente)

    def pedidos_por_entregar(self, id_transportista: str) -> list[Pedido]:
        """INT-13: pendientes con ruta + en tránsito de las rutas del transportista."""
        transportista = self.transportistas.obtener(id_transportista)
        return [p for p in self.pedidos.listar()
                if p.ruta is not None
                and p.ruta.transportista is transportista
                and p.estado in (EstadoPedido.PENDIENTE, EstadoPedido.EN_TRANSITO)]

    def detalle_pedido(self, folio_pedido: str) -> dict[str, object]:
        """INT-14: pedido con su cliente, ruta y transportista."""
        pedido = self.pedidos.obtener(folio_pedido)
        ruta: Optional[Ruta] = pedido.ruta
        return {
            "pedido": pedido,
            "cliente": pedido.cliente,
            "ruta": ruta,
            "transportista": ruta.transportista if ruta else None,
        }

    def rutas_compatibles(self, folio_pedido: str) -> list[Ruta]:
        """INT-15: rutas con el mismo origen y destino que un pedido pendiente."""
        pedido = self.pedidos.obtener(folio_pedido)
        if pedido.estado is not EstadoPedido.PENDIENTE:
            return []
        return [r for r in self.rutas.listar() if r.cubre(pedido.origen, pedido.destino)]

"""Gestores CRUD de las cuatro entidades.

Regla común a todos los métodos que modifican datos:
1. Se valida todo sobre una copia (``dataclasses.replace`` vuelve a correr
   las validaciones de ``__post_init__``).
2. Solo si todo es válido se aplica el cambio en memoria.
3. Se guarda el CSV; si el guardado falla se revierte el cambio en memoria.
Así una operación rechazada nunca deja datos a medias (INT-09).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Generic, Optional, TypeVar

from rutas.estados import ESTADOS_ACTIVOS, EstadoPedido, validar_transicion
from rutas.excepciones import (
    DatoInvalidoError,
    DependenciaError,
    EntidadNoEncontradaError,
    IdentificadorDuplicadoError,
    ReferenciaInvalidaError,
    RutasError,
    TransicionInvalidaError,
    TrayectoIncompatibleError,
)
from rutas.modelos import Cliente, Pedido, Ruta, Transportista
from rutas.persistencia import escribir_csv, leer_csv
from rutas.validacion import normalizar_id

T = TypeVar("T", Cliente, Transportista, Ruta, Pedido)


@dataclass(frozen=True)
class Descarte:
    """Fila de un CSV del sistema que no se pudo cargar."""

    archivo: str
    linea: int
    clave: str
    motivo: str


class _GestorBase(Generic[T]):
    """Comportamiento compartido: registro en memoria, búsqueda y guardado."""

    ARCHIVO: str = ""
    CLAVE: str = ""
    CLASE: type

    def __init__(self, directorio: Path | str) -> None:
        self.archivo = Path(directorio) / self.ARCHIVO
        self._registros: dict[str, T] = {}
        self.descartadas: list[Descarte] = []
        # El sistema conecta este gancho: devuelve ids que impiden borrar.
        self.dependientes: Callable[[str], list[str]] = lambda _clave: []

    # ---------- consulta (INT-20) ----------
    def listar(self) -> list[T]:
        """Todos los registros en orden de alta."""
        return list(self._registros.values())

    def buscar(self, clave: str) -> Optional[T]:
        """Registro por id, o ``None`` si no existe o el id es inválido."""
        try:
            return self._registros.get(normalizar_id(clave, self.CLAVE))
        except DatoInvalidoError:
            return None

    def obtener(self, clave: str) -> T:
        """Como ``buscar`` pero lanza ``EntidadNoEncontradaError``."""
        registro = self.buscar(clave)
        if registro is None:
            raise EntidadNoEncontradaError(f"{self.CLAVE} {clave!r} no existe")
        return registro

    def __len__(self) -> int:
        return len(self._registros)

    # ---------- persistencia ----------
    def guardar(self) -> None:
        """Reescribe el CSV completo con el estado actual en memoria."""
        escribir_csv(self.archivo, self.CLASE.COLUMNAS,
                     (r.to_dict() for r in self._registros.values()))

    def cargar(self) -> None:
        """Lee el CSV; las filas inválidas van a ``descartadas`` sin detener la carga."""
        self._registros.clear()
        self.descartadas.clear()
        for linea, fila in leer_csv(self.archivo):
            clave = (fila.get(self.CLAVE) or "").strip()
            try:
                registro = self._desde_fila(fila)
                if getattr(registro, self.CLAVE) in self._registros:
                    raise IdentificadorDuplicadoError("id repetido dentro del archivo")
            except (RutasError, KeyError, TypeError) as error:
                self.descartadas.append(Descarte(self.ARCHIVO, linea, clave, str(error)))
                continue
            self._registros[getattr(registro, self.CLAVE)] = registro

    def _desde_fila(self, fila: dict[str, str]) -> T:
        raise NotImplementedError

    # ---------- escritura con reversión ----------
    def _agregar(self, registro: T) -> T:
        clave = getattr(registro, self.CLAVE)
        if clave in self._registros:
            raise IdentificadorDuplicadoError(f"{self.CLAVE} {clave} ya existe")
        self._registros[clave] = registro
        try:
            self.guardar()
        except OSError:
            del self._registros[clave]
            raise
        return registro

    def _aplicar(self, original: T, candidato: T, campos: Iterable[str]) -> T:
        """Copia los campos validados del candidato al original y guarda.

        Se modifica el objeto original (no se reemplaza) para que los
        objetos que lo componen -por ejemplo, un pedido que apunta a esta
        ruta- vean el cambio.
        """
        respaldo = replace(original)
        campos = list(campos)
        for campo in campos:
            setattr(original, campo, getattr(candidato, campo))
        try:
            self.guardar()
        except OSError:
            for campo in campos:
                setattr(original, campo, getattr(respaldo, campo))
            raise
        return original

    def _eliminar(self, clave: str) -> bool:
        registro = self.buscar(clave)
        if registro is None:
            return False
        bloqueos = self.dependientes(getattr(registro, self.CLAVE))
        if bloqueos:
            raise DependenciaError(
                f"no se elimina {getattr(registro, self.CLAVE)}: lo usan {', '.join(bloqueos)}")
        del self._registros[getattr(registro, self.CLAVE)]
        try:
            self.guardar()
        except OSError:
            self._registros[getattr(registro, self.CLAVE)] = registro
            raise
        return True


class GestorTransportistas(_GestorBase[Transportista]):
    """CRUD de ``transportistas.csv``."""

    ARCHIVO, CLAVE, CLASE = "transportistas.csv", "id_transportista", Transportista

    def _desde_fila(self, fila: dict[str, str]) -> Transportista:
        return Transportista(fila["id_transportista"], fila["nombre"])

    def crear_transportista(self, id_transportista: str, nombre: str) -> Transportista:
        """Da de alta y guarda; ``IdentificadorDuplicadoError`` si el id existe."""
        return self._agregar(Transportista(id_transportista, nombre))

    def actualizar_transportista(self, id_transportista: str, nombre: str) -> Transportista:
        """Cambia el nombre; el id no se modifica."""
        original = self.obtener(id_transportista)
        return self._aplicar(original, replace(original, nombre=nombre), ["nombre"])

    def eliminar_transportista(self, id_transportista: str) -> bool:
        """``True`` si se borró, ``False`` si no existía; ``DependenciaError`` si tiene rutas."""
        return self._eliminar(id_transportista)


class GestorClientes(_GestorBase[Cliente]):
    """CRUD de ``clientes.csv``."""

    ARCHIVO, CLAVE, CLASE = "clientes.csv", "id_cliente", Cliente
    EDITABLES = ("nombre", "ciudad", "telefono")

    def _desde_fila(self, fila: dict[str, str]) -> Cliente:
        return Cliente(fila["id_cliente"], fila["nombre"], fila["ciudad"], fila["telefono"])

    def crear_cliente(self, id_cliente: str, nombre: str, ciudad: str, telefono: str) -> Cliente:
        """Da de alta y guarda; ``IdentificadorDuplicadoError`` si el id existe."""
        return self._agregar(Cliente(id_cliente, nombre, ciudad, telefono))

    def actualizar_cliente(self, id_cliente: str, **cambios: str) -> Cliente:
        """Modifica ``nombre``, ``ciudad`` o ``telefono``."""
        _solo_editables(cambios, self.EDITABLES)
        original = self.obtener(id_cliente)
        return self._aplicar(original, replace(original, **cambios), cambios)

    def eliminar_cliente(self, id_cliente: str) -> bool:
        """``DependenciaError`` si el cliente tiene pedidos (INT-16)."""
        return self._eliminar(id_cliente)


class GestorRutas(_GestorBase[Ruta]):
    """CRUD de ``rutas.csv``; cada ruta compone a su ``Transportista``."""

    ARCHIVO, CLAVE, CLASE = "rutas.csv", "id_ruta", Ruta
    EDITABLES = ("origen", "destino", "distancia_km", "tiempo_estimado_horas")

    def __init__(self, directorio: Path | str, transportistas: GestorTransportistas) -> None:
        super().__init__(directorio)
        self.transportistas = transportistas
        self.pedidos_activos: Callable[[str], list[Pedido]] = lambda _id: []

    def _resolver_transportista(self, id_transportista: str) -> Transportista:
        transportista = self.transportistas.buscar(id_transportista)
        if transportista is None:
            raise ReferenciaInvalidaError(f"id_transportista {id_transportista!r} no existe")
        return transportista

    def _desde_fila(self, fila: dict[str, str]) -> Ruta:
        return Ruta(fila["id_ruta"], fila["origen"], fila["destino"], fila["distancia_km"],
                    fila["tiempo_estimado_horas"],
                    self._resolver_transportista(fila["id_transportista"]))

    def crear_ruta(self, id_ruta: str, origen: str, destino: str, distancia_km: float,
                   tiempo_estimado_horas: float, id_transportista: str) -> Ruta:
        """Alta de ruta; ``ReferenciaInvalidaError`` si el transportista no existe (INT-02)."""
        transportista = self._resolver_transportista(id_transportista)
        return self._agregar(Ruta(id_ruta, origen, destino, distancia_km,
                                  tiempo_estimado_horas, transportista))

    def actualizar_ruta(self, id_ruta: str, **cambios: object) -> Ruta:
        """Modifica datos de la ruta.

        Si cambia el trayecto y hay pedidos activos asignados que ya no
        coincidirían, se rechaza con ``TrayectoIncompatibleError`` (INT-06).
        """
        _solo_editables(cambios, self.EDITABLES)
        original = self.obtener(id_ruta)
        candidato = replace(original, **cambios)
        afectados = [p.folio_pedido for p in self.pedidos_activos(original.id_ruta)
                     if not candidato.cubre(p.origen, p.destino)]
        if afectados:
            raise TrayectoIncompatibleError(
                f"{original.id_ruta}: el nuevo trayecto no coincide con {', '.join(afectados)}")
        return self._aplicar(original, candidato, cambios)

    def eliminar_ruta(self, id_ruta: str) -> bool:
        """``DependenciaError`` si la ruta tiene pedidos no entregados."""
        return self._eliminar(id_ruta)


class GestorPedidos(_GestorBase[Pedido]):
    """CRUD de ``pedidos.csv`` y único punto que cambia el estado de un pedido."""

    ARCHIVO, CLAVE, CLASE = "pedidos.csv", "folio_pedido", Pedido
    EDITABLES = ("producto", "cantidad", "origen", "destino", "fecha_pedido")
    ELIMINABLES = frozenset({EstadoPedido.PENDIENTE, EstadoPedido.CANCELADO})

    def __init__(self, directorio: Path | str, clientes: GestorClientes,
                 rutas: GestorRutas) -> None:
        super().__init__(directorio)
        self.clientes = clientes
        self.rutas = rutas

    # ---------- resolución de llaves foráneas ----------
    def _resolver_cliente(self, id_cliente: str) -> Cliente:
        cliente = self.clientes.buscar(id_cliente)
        if cliente is None:
            raise ReferenciaInvalidaError(f"id_cliente {id_cliente!r} no existe")
        return cliente

    def _resolver_ruta(self, id_ruta: Optional[str], origen: str, destino: str) -> Optional[Ruta]:
        if id_ruta is None or not str(id_ruta).strip():
            return None
        ruta = self.rutas.buscar(id_ruta)
        if ruta is None:
            raise ReferenciaInvalidaError(f"id_ruta {id_ruta!r} no existe")
        if not ruta.cubre(origen, destino):
            raise TrayectoIncompatibleError(
                f"{ruta.id_ruta} va de {ruta.origen} a {ruta.destino}, "
                f"el pedido de {origen} a {destino}")
        return ruta

    def _desde_fila(self, fila: dict[str, str]) -> Pedido:
        """Reconstruye un pedido guardado, con el estado que tenía.

        Es el único lugar donde el estado se asigna sin pasar por una
        transición: se restaura lo que ya se había validado al guardarlo.
        Aun así se rechaza una fila incoherente (en tránsito sin ruta).
        """
        estado = EstadoPedido(fila["estado"].strip())
        pedido = Pedido(fila["folio_pedido"], self._resolver_cliente(fila["id_cliente"]),
                        fila["producto"], fila["cantidad"], fila["origen"], fila["destino"],
                        fila["fecha_pedido"], _estado=estado)
        pedido.ruta = self._resolver_ruta(fila.get("id_ruta"), pedido.origen, pedido.destino)
        if estado in (EstadoPedido.EN_TRANSITO, EstadoPedido.ENTREGADO) and pedido.ruta is None:
            raise TransicionInvalidaError(f"{pedido.folio_pedido}: {estado.value} sin ruta")
        return pedido

    # ---------- CRUD ----------
    def construir_pedido(self, folio_pedido: str, id_cliente: str, producto: str,
                         cantidad: object, origen: str, destino: str,
                         fecha_pedido: object = None, id_ruta: Optional[str] = None) -> Pedido:
        """Crea y valida un ``Pedido`` sin registrarlo (lo reutiliza la carga por lote)."""
        cliente = self._resolver_cliente(id_cliente)
        pedido = Pedido(folio_pedido, cliente, producto, cantidad, origen, destino,
                        **({"fecha_pedido": fecha_pedido} if fecha_pedido else {}))
        pedido.ruta = self._resolver_ruta(id_ruta, pedido.origen, pedido.destino)
        return pedido

    def crear_pedido(self, *args: object, **kwargs: object) -> Pedido:
        """Alta de pedido en estado ``pendiente``; mismos parámetros que ``construir_pedido``."""
        return self._agregar(self.construir_pedido(*args, **kwargs))

    def agregar_lote(self, pedidos: list[Pedido]) -> None:
        """Registra varios pedidos ya validados con un solo guardado."""
        nuevos = {p.folio_pedido: p for p in pedidos}
        repetidos = nuevos.keys() & self._registros.keys()
        if repetidos or len(nuevos) != len(pedidos):
            raise IdentificadorDuplicadoError(f"folios repetidos: {sorted(repetidos)}")
        self._registros.update(nuevos)
        try:
            self.guardar()
        except OSError:
            for folio in nuevos:
                del self._registros[folio]
            raise

    def actualizar_pedido(self, folio_pedido: str, **cambios: object) -> Pedido:
        """Edita datos de un pedido ``pendiente``; el estado NO se edita aquí.

        Si el pedido ya tiene ruta y cambia el trayecto, se vuelve a validar
        la coincidencia (INT-06).
        """
        if "estado" in cambios or "_estado" in cambios:
            raise TransicionInvalidaError("el estado solo cambia con cambiar_estado()")
        _solo_editables(cambios, self.EDITABLES)
        original = self.obtener(folio_pedido)
        if original.estado is not EstadoPedido.PENDIENTE:
            raise TransicionInvalidaError(
                f"{original.folio_pedido}: solo se edita un pedido pendiente")
        candidato = replace(original, **cambios)
        if original.ruta and not original.ruta.cubre(candidato.origen, candidato.destino):
            raise TrayectoIncompatibleError(
                f"{original.folio_pedido}: el nuevo trayecto no coincide con {original.ruta.id_ruta}")
        return self._aplicar(original, candidato, cambios)

    def asignar_ruta(self, folio_pedido: str, id_ruta: str) -> Pedido:
        """Asigna una ruta existente y compatible a un pedido pendiente (INT-04)."""
        pedido = self.obtener(folio_pedido)
        if pedido.estado is not EstadoPedido.PENDIENTE:
            raise TransicionInvalidaError(f"{pedido.folio_pedido}: ya no está pendiente")
        ruta = self._resolver_ruta(id_ruta, pedido.origen, pedido.destino)
        if ruta is None:
            raise DatoInvalidoError("id_ruta", id_ruta, "campo obligatorio vacío")
        candidato = replace(pedido, ruta=ruta)
        return self._aplicar(pedido, candidato, ["ruta"])

    def cambiar_estado(self, folio_pedido: str, destino: EstadoPedido | str) -> Pedido:
        """Único método que modifica el estado; valida con la máquina de estados."""
        pedido = self.obtener(folio_pedido)
        try:
            destino = EstadoPedido(destino)
        except ValueError:
            raise DatoInvalidoError("estado", destino, "estado desconocido") from None
        validar_transicion(pedido, destino)
        candidato = replace(pedido, _estado=destino)
        return self._aplicar(pedido, candidato, ["_estado"])

    def despachar(self, folio_pedido: str) -> Pedido:
        """``pendiente`` -> ``en_transito`` (requiere ruta)."""
        return self.cambiar_estado(folio_pedido, EstadoPedido.EN_TRANSITO)

    def entregar(self, folio_pedido: str) -> Pedido:
        """``en_transito`` -> ``entregado``."""
        return self.cambiar_estado(folio_pedido, EstadoPedido.ENTREGADO)

    def cancelar(self, folio_pedido: str) -> Pedido:
        """``pendiente`` -> ``cancelado`` (INT-08)."""
        return self.cambiar_estado(folio_pedido, EstadoPedido.CANCELADO)

    def eliminar_pedido(self, folio_pedido: str) -> bool:
        """Borra un pedido ``pendiente`` o ``cancelado``; los demás se conservan como historial."""
        pedido = self.buscar(folio_pedido)
        if pedido is not None and pedido.estado not in self.ELIMINABLES:
            raise DependenciaError(
                f"{pedido.folio_pedido}: no se elimina un pedido {pedido.estado.value}")
        return self._eliminar(folio_pedido)

    # ---------- consultas por relación ----------
    def de_cliente(self, id_cliente: str) -> list[Pedido]:
        """Pedidos de un cliente, sin importar destino (INT-12)."""
        return [p for p in self._registros.values() if p.cliente.id_cliente == id_cliente]

    def de_ruta(self, id_ruta: str, solo_activos: bool = False) -> list[Pedido]:
        """Pedidos asignados a una ruta; opcionalmente solo pendientes/en tránsito."""
        return [p for p in self._registros.values()
                if p.ruta is not None and p.ruta.id_ruta == id_ruta
                and (not solo_activos or p.estado in ESTADOS_ACTIVOS)]


def _solo_editables(cambios: dict[str, object], permitidos: tuple[str, ...]) -> None:
    """Rechaza campos que no se pueden editar (por ejemplo, el id)."""
    extra = set(cambios) - set(permitidos)
    if extra:
        raise DatoInvalidoError(", ".join(sorted(extra)), None, "campo no editable")

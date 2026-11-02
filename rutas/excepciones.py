"""Excepciones propias del sistema Rutas del Bajío.

Todas heredan de ``RutasError`` para que el código cliente pueda atrapar
cualquier error de negocio con un solo ``except``, y a la vez distinguir
el motivo exacto cuando lo necesita (por ejemplo, en las pruebas).
"""


class RutasError(Exception):
    """Error base de todas las reglas de negocio del sistema."""


class DatoInvalidoError(RutasError, ValueError):
    """Un campo no cumple su tipo, formato o regla (cantidad, fecha, id...)."""

    def __init__(self, campo: str, valor: object, motivo: str) -> None:
        self.campo = campo
        self.valor = valor
        self.motivo = motivo
        super().__init__(f"{campo}={valor!r}: {motivo}")


class IdentificadorDuplicadoError(RutasError):
    """Se intentó crear un registro con un identificador que ya existe."""


class EntidadNoEncontradaError(RutasError, LookupError):
    """Se pidió operar sobre un identificador que no existe."""


class ReferenciaInvalidaError(RutasError):
    """Una llave foránea apunta a un registro inexistente."""


class TrayectoIncompatibleError(RutasError):
    """El origen/destino de la ruta no coincide con el del pedido."""


class TransicionInvalidaError(RutasError):
    """Cambio de estado del pedido no permitido por la máquina de estados."""


class DependenciaError(RutasError):
    """Eliminación rechazada porque otros registros dependen del que se borra."""


class ArchivoLoteError(RutasError):
    """El archivo de lote no se puede procesar como un todo (problema de archivo)."""

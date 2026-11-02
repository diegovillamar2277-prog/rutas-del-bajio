# Rutas del Bajío — backend (Parcial 2)

CRUD de Cliente, Transportista, Ruta y Pedido con composición, persistencia en CSV,
máquina de estados del pedido y carga por lote con archivo de rechazos.

Requiere Python 3.10+. Sin dependencias externas.

## Uso rápido

```python
from rutas import SistemaRutas, importar_pedidos

s = SistemaRutas("datos")                 # carga Transportista -> Cliente -> Ruta -> Pedido
s.pedidos.crear_pedido("PED-0005", "CLI-010", "Hormas", 20, "León", "Silao")
s.pedidos.asignar_ruta("PED-0005", "RUTA-02")
s.pedidos.despachar("PED-0005")           # pendiente -> en_transito
resultado = importar_pedidos(s, "ejemplos/lote_pedidos.csv")
```

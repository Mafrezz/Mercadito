# Cambios sobre el proyecto recibido

## Alcance

Se implementaron los seis puntos de programación del apartado final de
`Instrucciones.txt`, correspondiente a la fotografía compartida. La propuesta
original define Python, Django y PostgreSQL; estos se mantienen. El alcance
no agrega pagos en línea ni funciones de geolocalización.

El proyecto recibido ya tenía las entidades, una migración inicial, el
catálogo, tarifas por mercado/zona y los datos iniciales. Faltaba conectar
esas entidades con formularios y operaciones de compra del cliente.

## Dónde está cada parte

| Archivo | Responsabilidad |
|---|---|
| `tienda/models.py` | Entidades originales, métodos de cálculo y restricciones de cantidades/importes. |
| `tienda/forms.py` | `RegistroForm`, `IngresoForm`, `CantidadForm` y `ConfirmarPedidoForm`. |
| `tienda/validaciones.py` | `validar_cantidad()` y `dinero()`; uso de `Decimal` y redondeo a centavos. |
| `tienda/servicios.py` | Agregar, actualizar, quitar, vaciar y confirmar compras. Transacciones y comprobación de confirmaciones. |
| `tienda/views.py` | Recepción de solicitudes, autorización por usuario, mensajes y navegación. |
| `tienda/urls.py` | Rutas públicas, cuentas, carritos y pedidos. |
| `tienda/middleware.py` | Respuesta 503 legible cuando falla una consulta de una vista por la base de datos. |
| `tienda/templates/tienda/` | Formularios, catálogo con compras, carrito, resumen, historial y detalle. |
| `tienda/static/tienda/css/estilos.css` | Se conserva el CSS original y se añaden estilos de cuentas/compras adaptables al ancho. |
| `tienda/admin.py` | Administración del catálogo y protección de campos históricos de los pedidos. |
| `mercadito/settings.py` | URLs de autenticación, middleware y ajustes compatibles con la configuración usada por el proyecto. |
| `mercadito/settings_pruebas.py` | Configuración opcional e independiente para pruebas en SQLite. |
| `tienda/migrations/0002_completar_compra.py` | Nueva columna de confirmación y validadores/restricciones. |
| `tienda/tests.py` | 88 pruebas de formularios, modelos, vistas, permisos, importes, excepciones y concurrencia. |

## Métodos en las clases

- `Mercado.obtener_cobertura(zona)`: comprueba actividad y cobertura del mercado.
- `Producto.permite_fracciones`, `paso_cantidad` y `maximo_cantidad`: reglas de
  cantidad que utilizan el formulario y los controles del catálogo.
- `ProductoMercado.calcular_importe(cantidad)`: cantidad validada por precio
  del mercado, redondeada a dos decimales.
- `Carrito.esta_vacio()`, `detalle_items()`, `calcular_subtotal()`,
  `calcular_envio(zona)` y `calcular_total(zona)`: consulta y cálculo de compra.
- `ItemCarrito.clean()`, `precio_unitario` y `subtotal`: validación y cálculo
  del renglón a precio actual.
- `Pedido.clean()`, `calcular_subtotal()`, `calcular_total()` y
  `actualizar_totales()`: reglas de pedido y total a partir de los renglones
  históricos. La validación de fecha pasada se aplica al crear el pedido;
  no impide actualizar posteriormente su estado.
- `ItemPedido.subtotal`: cantidad por precio guardado al comprar, con redondeo.

Los importes se calculan en Python. PostgreSQL almacena los resultados y las
restricciones comprueban que no haya cantidades/importes inválidos. No se
agregaron procedimientos almacenados ni disparadores para calcular precios.

## Consistencia al confirmar

`confirmar_compra()` verifica la firma del formulario, el propietario del
carrito, la cobertura, la disponibilidad, los precios y las cantidades.
Genera el pedido y sus renglones en una transacción y vacía el carrito solo
como parte de esa misma operación. Ante un error dentro de la transacción,
los cambios se revierten.

El formulario contiene una confirmación firmada con una huella de lo que
se mostró al cliente, no un precio editable como fuente de verdad. El campo
`Pedido.token_confirmacion` permite reconocer el reenvío de la misma compra.
Las operaciones del carrito toman bloqueos de filas para PostgreSQL; las dos
pruebas simultáneas asociadas quedan pendientes de ejecutar en ese motor.

No se pretende resolver aquí una caída del servidor de base de datos durante
un resultado de confirmación incierto: el mensaje solicita revisar el
historial antes de reintentar. Tampoco se agrega un control de inventario
numérico que el proyecto original no tenía.

## Base de datos y compatibilidad

Se conserva `0001_initial.py` byte por byte. `0002_completar_compra.py` añade
un identificador de confirmación nullable/único y restricciones de datos.
Los pedidos anteriores pueden conservar un valor nulo en la columna nueva.
Se comprobó una actualización desde 0001 con catálogo, usuario, carrito y
pedido anterior en una base SQLite aislada, sin pérdida de esos registros.
La aplicación normal continúa configurada para PostgreSQL.

Si existieran registros antiguos con precios cero/negativos, cantidades no
positivas o totales inconsistentes, las nuevas restricciones pueden impedir
la migración hasta que esos registros se revisen. No se corrigieron ni
borraron datos del usuario automáticamente.

`requirements.txt`, el fixture `datos_iniciales.json`, la migración inicial,
la configuración de conexión por `.env` y las clases base se conservan. No
se distribuye el entorno virtual de Windows dentro de esta actualización.

## Referencias técnicas consultadas

Documentación oficial de Django 5.2: autenticación, validación de formularios,
transacciones y restricciones de modelos. Referencias para el lector:

```text
https://docs.djangoproject.com/en/5.2/topics/auth/default/
https://docs.djangoproject.com/en/5.2/ref/forms/validation/
https://docs.djangoproject.com/en/5.2/topics/db/transactions/
https://docs.djangoproject.com/en/5.2/ref/models/constraints/
```

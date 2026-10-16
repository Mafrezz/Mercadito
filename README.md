# Mercadito

Actualización del proyecto recibido en `Mercadito.rar`: registro e inicio de
sesión, carrito, confirmación de pedidos, métodos de cálculo, validaciones y
manejo de excepciones. Conserva el catálogo, los modelos base, el diseño y
PostgreSQL como base de datos normal.

**Para actualizar tu instalación actual, empieza por `LEEME_ACTUALIZACION.txt`.**
No reemplaces `.env`, `venv` ni `.git`. La migración nueva ya está incluida.

## Ejecución en la instalación existente

En PowerShell, dentro de la carpeta que contiene `manage.py`:

```powershell
.\venv\Scripts\Activate.ps1
$env:PYTHONUTF8 = "1"
python manage.py check
python manage.py migrate
python manage.py runserver
```

Abre `http://127.0.0.1:8000/`.

No vuelvas a cargar los datos iniciales sobre una base que ya tiene cambios.
No se modificó `requirements.txt` ni se añadieron dependencias.

## Funciones implementadas

| Área | Funcionamiento |
|---|---|
| Cuentas | Registro con nombres, apellidos, correo, usuario y confirmación de contraseña. Ingreso y salida de sesión. |
| Carrito | Agregar, sumar un producto repetido, modificar su cantidad, quitar y vaciar. Un carrito por usuario y mercado. |
| Pedido | Dirección y fecha, comprobación de cobertura, importe de envío, revisión del total y confirmación con pago contra entrega. |
| Historial | Lista y detalle de los pedidos del usuario conectado. |
| Cálculos | Cantidad por precio; redondeo por renglón; subtotal, envío y total. Precio guardado en el pedido al confirmar. |
| Validaciones | Cantidades, unidades de venta, fechas, dirección, credenciales, disponibilidad y pertenencia del carrito. |
| Excepciones | Mensajes para errores previstos, registro técnico del error y transacción para la compra. |
| Administración | Catálogo y tarifas editables. En pedidos se cambia el estado sin alterar importes históricos desde el formulario. |

## Reglas de esta implementación

Estas decisiones concretan puntos que las instrucciones no detallaban:

- Se permite explorar sin cuenta; para agregar y confirmar se inicia sesión.
  El ingreso usa **nombre de usuario**, no correo. El registro no verifica
  la propiedad del correo ni incorpora recuperación de contraseña.
- Libras y litros permiten hasta dos decimales. Unidades y docenas se compran
  completas. Cantidad mínima: 0.01 para fracciones o 1 para enteros; máximo
  9999.99 para fracciones o 9999 para enteros. No se agregó inventario por
  existencias: se conserva la disponibilidad booleana del modelo original.
- La zona del pedido es la seleccionada en la página inicial. Se puede cambiar
  desde el carrito o la confirmación. La tarifa sale de `MercadoZona` y no
  de un valor enviado por el navegador.
- La dirección, luego de limpiar espacios, debe tener entre 8 y 300 caracteres.
  La fecha puede ser hoy o posterior, según `America/Guatemala`; no se agregaron
  restricciones por día de semana ni franjas horarias.
- El único método es **pago contra entrega**, ya previsto en los modelos.
  No hay pasarela de pago, cobros reales, geolocalización ni cálculo de rutas.
- Un cambio de cantidades, precios, zona o tarifa después de abrir la
  confirmación obliga a revisar el resumen. El formulario conserva dirección
  y fecha al mostrar errores; nunca vuelve a mostrar las contraseñas escritas.
- La misma confirmación reenviada no genera otro pedido. Los formularios de
  confirmación tienen una vigencia de dos horas. Los precios y las tarifas
  históricas del pedido no cambian al editar el catálogo después de comprar.
- La clase `Direccion` original se conserva y se administra desde Django;
  esta actualización captura la dirección directamente en cada pedido, sin
  crear una libreta de direcciones del cliente.

## Comprobación de un importe

Con los datos de demostración originales: Mercado El Guarda, zona 3 de
Guatemala, 3 libras de manzana a Q8.00 producen Q24.00 de productos. La tarifa
incluida para esa cobertura es Q15.00, por lo que el total es Q39.00. Son datos
del fixture del proyecto, no cotizaciones de precios reales.

## Pruebas

Con tu PostgreSQL:

```powershell
python manage.py test tienda --verbosity 2
```

Para la suite sin servidor PostgreSQL, exclusivamente en modo de pruebas:

```powershell
python manage.py test tienda --settings=mercadito.settings_pruebas --verbosity 2
```

La configuración de pruebas usa SQLite en memoria y un hash rápido solo para
acelerar las pruebas; **no la uses para servir el sitio**. La ejecución normal
mantiene PostgreSQL y los mecanismos de contraseña configurados por Django.

Resultado de esta entrega: 88 pruebas descubiertas, 86 aprobadas y 2 omitidas
por requerir PostgreSQL real. No se ha verificado aquí la ejecución contra
tu servidor PostgreSQL. Consulta `docs/PRUEBAS.md` y los registros adjuntos.

## Estructura y cambios

Consulta `docs/CAMBIOS.md` para ubicar los métodos, formularios, servicios y
pantallas, y `docs/ARCHIVOS_CAMBIADOS.txt` para comparar con el RAR recibido.
Esta guía acompaña al código; no sustituye los manuales, el algoritmo ni el
diagrama de flujo de la entrega académica.

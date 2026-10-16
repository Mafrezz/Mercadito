# Verificación de la actualización

## Entorno y resultado

Se usó Python 3.13 en Linux y el código de Django 5.2.18 incluido en el entorno
virtual del RAR proporcionado. La base utilizada para las pruebas fue SQLite.
No había un servidor PostgreSQL operativo en este entorno.

La suite descubrió **88 pruebas**: **86 aprobadas**, **2 omitidas**, sin fallos
ni errores. Las omitidas requieren PostgreSQL real y verifican dos adiciones
simultáneas al carrito y dos confirmaciones simultáneas de la misma compra.
El registro está en `RESULTADO_PRUEBAS.txt`.

Se ejecutó `manage.py check` con la configuración normal de PostgreSQL sin
incidencias. Ese comando no demuestra que haya una conexión con la base ni
que la migración se haya ejecutado en PostgreSQL. Se comprobó también que
no faltaran migraciones con `makemigrations --check --dry-run`.

## Cobertura de las pruebas ejecutadas

Se probaron registro y contraseñas, inicio/salida de sesión, nombres de usuario
repetidos, navegación pública, zonas inválidas, categorías y agrupación,
carritos separados por usuario/mercado, cantidades inválidas o fraccionarias,
actualización y eliminación de productos, cobertura y disponibilidad.

En los pedidos se comprobaron dirección y fecha, cálculos decimales,
redondeo, importes históricos, precios manipulados en solicitudes,
confirmaciones repetidas/alteradas/vencidas, cambios entre la revisión y la
confirmación, límites de importe, permisos, historial y administración.
Se simuló un error al guardar el segundo renglón para comprobar que no se
conservara un pedido parcial y que el carrito no quedara vacío.

También se ejecutó un recorrido adicional mediante Django Client con CSRF
activo: registro, ingreso, zona, compra, modificación de cantidad,
confirmación, historial, salida y nuevo ingreso con persistencia del pedido.
Está resumido en `RECORRIDO_CSRF.txt`.

## Actualización con datos anteriores

En otra base SQLite aislada se migró primero hasta `0001_initial`, se cargaron
los 118 objetos del fixture original y se crearon un usuario, un carrito y
un pedido anterior. Luego se aplicó `0002_completar_compra` y se verificó que
esos datos permanecieran, incluyendo el importe del pedido y su dirección.
Registro: `ACTUALIZACION_CON_DATOS.txt`.

Esta verificación no sustituye una prueba de migración en tu PostgreSQL ni
una copia de respaldo antes de aplicar cambios en la base real del proyecto.

## Revisión visual

Se renderizó con Django el HTML de registro, catálogo, carrito, confirmación,
detalle e historial. El HTML y el CSS se visualizaron sin red en Chromium a
1280, 390 y 320 píxeles de ancho. No se detectó desborde horizontal en esas
18 combinaciones. Se inspeccionaron capturas de catálogo y confirmación,
incluida la versión para celular. Se utilizaron fuentes de respaldo del CSS
porque las fuentes externas no se descargaron.

No se completó una automatización del recorrido en un navegador conectado
al servidor: el navegador de este entorno bloqueó la navegación local. El
recorrido funcional se comprobó con Django Client y la revisión del navegador
fue de renderizado estático. No se probaron dispositivos móviles físicos.

## Comprobación pendiente en tu equipo

Dentro del entorno virtual y con tu PostgreSQL iniciado:

```powershell
python manage.py check
python manage.py migrate
python manage.py test tienda --verbosity 2
```

El usuario de base de datos debe poder crear la base separada de pruebas,
como prevé el permiso `CREATEDB` de las instrucciones originales. No debes
cambiar la conexión normal a SQLite para ejecutar la página. El archivo
`settings_pruebas.py` es una alternativa limitada a pruebas.

La verificación aquí realizada no implica una auditoría de seguridad, una
prueba de carga, certificación para producción ni una nota garantizada según
la rúbrica del curso.

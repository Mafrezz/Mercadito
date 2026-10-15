from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from tienda.models import (
    Categoria,
    Mercado,
    MercadoZona,
    Producto,
    ProductoMercado,
    Zona,
)

G = Zona.Municipio.GUATEMALA
M = Zona.Municipio.MIXCO
U = Producto.Unidad

# Zonas: (numero, municipio)
ZONAS = [(3, G), (7, G), (8, G), (11, G), (12, G), (19, G),
         (4, M), (6, M), (7, M), (11, M)]

# Mercados: nombre, zona donde se ubica, zonas de entrega con tarifa (valores de ejemplo)
MERCADOS = {
    "Mercado El Guarda": {
        "ubicacion": (11, G),
        "direccion": "Colonia El Progreso, zona 11",
        "entrega": {(3, G): "15.00", (7, G): "15.00", (8, G): "12.00",
                    (11, G): "10.00", (12, G): "12.00"},
    },
    "Mercado La Florida": {
        "ubicacion": (19, G),
        "direccion": "Zona 19",
        "entrega": {(19, G): "10.00", (7, G): "15.00", (4, M): "15.00",
                    (6, M): "15.00", (7, M): "15.00", (11, M): "18.00"},
    },
}

# Categoria -> [(producto, unidad, precio El Guarda, precio La Florida)]
# Los precios son solo de ejemplo; cámbialos desde el panel de administración.
CATALOGO = {
    "Frutas": [
        ("Manzana", U.LIBRA, "8.00", "9.00"),
        ("Banano", U.LIBRA, "3.00", "3.50"),
        ("Naranja", U.DOCENA, "12.00", "10.00"),
        ("Mandarina", U.DOCENA, "15.00", "16.00"),
        ("Papaya", U.UNIDAD, "12.00", "11.00"),
        ("Piña", U.UNIDAD, "10.00", "12.00"),
        ("Sandía", U.UNIDAD, "20.00", "18.00"),
    ],
    "Verduras": [
        ("Tomate", U.LIBRA, "4.00", "4.50"),
        ("Cebolla", U.LIBRA, "3.50", "3.00"),
        ("Papa", U.LIBRA, "3.00", "3.25"),
        ("Zanahoria", U.LIBRA, "2.50", "3.00"),
        ("Chile pimiento", U.LIBRA, "5.00", "4.50"),
        ("Brócoli", U.LIBRA, "6.00", "6.50"),
    ],
    "Carnes": [
        ("Carne de res", U.LIBRA, "32.00", "34.00"),
        ("Carne molida", U.LIBRA, "30.00", "28.00"),
        ("Carne de cerdo", U.LIBRA, "24.00", "25.00"),
        ("Pollo", U.LIBRA, "14.00", "15.00"),
        ("Costilla de cerdo", U.LIBRA, "26.00", "27.00"),
    ],
    "Granos": [
        ("Frijol negro", U.LIBRA, "7.00", "7.50"),
        ("Frijol rojo", U.LIBRA, "8.00", "7.50"),
        ("Arroz", U.LIBRA, "4.50", "4.00"),
        ("Maíz", U.LIBRA, "2.50", "2.75"),
        ("Garbanzos", U.LIBRA, "9.00", "9.50"),
    ],
    "Abarrotes": [
        ("Aceite", U.LITRO, "22.00", "24.00"),
        ("Azúcar", U.LIBRA, "4.00", "4.25"),
        ("Sal", U.LIBRA, "2.00", "2.25"),
        ("Harina", U.LIBRA, "4.00", "3.75"),
        ("Café", U.LIBRA, "25.00", "27.00"),
        ("Leche", U.LITRO, "10.00", "9.50"),
        ("Huevos", U.DOCENA, "22.00", "24.00"),
    ],
}


class Command(BaseCommand):
    help = "Carga datos de prueba: zonas, 2 mercados, categorías, productos y precios."

    @transaction.atomic
    def handle(self, *args, **options):
        zonas = {}
        for numero, municipio in ZONAS:
            zonas[(numero, municipio)], _ = Zona.objects.get_or_create(
                numero=numero, municipio=municipio
            )

        mercados = {}
        for nombre, datos in MERCADOS.items():
            mercado, _ = Mercado.objects.get_or_create(
                nombre=nombre,
                defaults={
                    "zona": zonas[datos["ubicacion"]],
                    "direccion": datos["direccion"],
                },
            )
            mercados[nombre] = mercado
            for clave, tarifa in datos["entrega"].items():
                MercadoZona.objects.update_or_create(
                    mercado=mercado,
                    zona=zonas[clave],
                    defaults={"tarifa_envio": Decimal(tarifa)},
                )

        guarda = mercados["Mercado El Guarda"]
        florida = mercados["Mercado La Florida"]

        for orden, (nombre_cat, productos) in enumerate(CATALOGO.items(), start=1):
            categoria, _ = Categoria.objects.get_or_create(
                nombre=nombre_cat, defaults={"orden": orden}
            )
            for nombre, unidad, precio_g, precio_f in productos:
                producto, _ = Producto.objects.get_or_create(
                    nombre=nombre,
                    defaults={"categoria": categoria, "unidad": unidad},
                )
                for mercado, precio in ((guarda, precio_g), (florida, precio_f)):
                    ProductoMercado.objects.update_or_create(
                        producto=producto,
                        mercado=mercado,
                        defaults={"precio": Decimal(precio)},
                    )

        self.stdout.write(self.style.SUCCESS("Datos de prueba cargados."))
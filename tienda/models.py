from django.conf import settings
from django.db import models


class Zona(models.Model):
    """Zona de entrega. El municipio evita confundir, por ejemplo,
    la zona 11 de Guatemala con la zona 11 de Mixco."""

    class Municipio(models.TextChoices):
        GUATEMALA = "GUATEMALA", "Guatemala"
        MIXCO = "MIXCO", "Mixco"

    numero = models.PositiveSmallIntegerField()
    municipio = models.CharField(max_length=20, choices=Municipio.choices)

    class Meta:
        unique_together = ("numero", "municipio")
        ordering = ["municipio", "numero"]

    def __str__(self):
        return f"Zona {self.numero} de {self.get_municipio_display()}"


class Mercado(models.Model):
    nombre = models.CharField(max_length=100)
    direccion = models.CharField(max_length=200, blank=True)
    zona = models.ForeignKey(
        Zona, on_delete=models.PROTECT, related_name="mercados_ubicados"
    )
    horario = models.CharField(max_length=100, blank=True)
    activo = models.BooleanField(default=True)
    zonas_entrega = models.ManyToManyField(
        Zona, through="MercadoZona", related_name="mercados_que_entregan"
    )

    def __str__(self):
        return self.nombre


class MercadoZona(models.Model):
    """Zonas a las que entrega un mercado y la tarifa fija de envío."""

    mercado = models.ForeignKey(Mercado, on_delete=models.CASCADE)
    zona = models.ForeignKey(Zona, on_delete=models.CASCADE)
    tarifa_envio = models.DecimalField(max_digits=6, decimal_places=2)

    class Meta:
        unique_together = ("mercado", "zona")

    def __str__(self):
        return f"{self.mercado} -> {self.zona} (Q{self.tarifa_envio})"


class Categoria(models.Model):
    nombre = models.CharField(max_length=50, unique=True)
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre


class Producto(models.Model):
    class Unidad(models.TextChoices):
        LIBRA = "LIBRA", "libra"
        UNIDAD = "UNIDAD", "unidad"
        DOCENA = "DOCENA", "docena"
        LITRO = "LITRO", "litro"

    nombre = models.CharField(max_length=100)
    categoria = models.ForeignKey(
        Categoria, on_delete=models.PROTECT, related_name="productos"
    )
    unidad = models.CharField(max_length=10, choices=Unidad.choices)
    descripcion = models.TextField(blank=True)

    class Meta:
        ordering = ["categoria", "nombre"]

    def __str__(self):
        return self.nombre


class ProductoMercado(models.Model):
    """Precio y disponibilidad de un producto en un mercado concreto."""

    producto = models.ForeignKey(
        Producto, on_delete=models.CASCADE, related_name="ofertas"
    )
    mercado = models.ForeignKey(
        Mercado, on_delete=models.CASCADE, related_name="ofertas"
    )
    precio = models.DecimalField(max_digits=8, decimal_places=2)
    disponible = models.BooleanField(default=True)

    class Meta:
        unique_together = ("producto", "mercado")

    def __str__(self):
        return f"{self.producto} en {self.mercado}: Q{self.precio}"


class Direccion(models.Model):
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="direcciones"
    )
    alias = models.CharField(max_length=50, help_text="Ej.: Casa, Trabajo")
    zona = models.ForeignKey(Zona, on_delete=models.PROTECT)
    direccion = models.CharField(max_length=200)
    referencias = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name_plural = "direcciones"

    def __str__(self):
        return f"{self.alias}: {self.direccion}, {self.zona}"


class Carrito(models.Model):
    """Un carrito pertenece a un mercado, porque los precios dependen de él."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="carritos"
    )
    mercado = models.ForeignKey(Mercado, on_delete=models.CASCADE)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("usuario", "mercado")

    def __str__(self):
        return f"Carrito de {self.usuario} en {self.mercado}"


class ItemCarrito(models.Model):
    carrito = models.ForeignKey(Carrito, on_delete=models.CASCADE, related_name="items")
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE)
    cantidad = models.DecimalField(max_digits=6, decimal_places=2, default=1)

    class Meta:
        unique_together = ("carrito", "producto")


class Pedido(models.Model):
    class Estado(models.TextChoices):
        RECIBIDO = "RECIBIDO", "Recibido"
        PREPARACION = "PREPARACION", "En preparación"
        EN_CAMINO = "EN_CAMINO", "En camino"
        ENTREGADO = "ENTREGADO", "Entregado"
        CANCELADO = "CANCELADO", "Cancelado"

    class MetodoPago(models.TextChoices):
        CONTRA_ENTREGA = "CONTRA_ENTREGA", "Pago contra entrega"

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pedidos"
    )
    mercado = models.ForeignKey(Mercado, on_delete=models.PROTECT)
    zona = models.ForeignKey(Zona, on_delete=models.PROTECT)
    direccion_entrega = models.CharField(max_length=300)
    fecha_entrega = models.DateField()
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    costo_envio = models.DecimalField(max_digits=6, decimal_places=2)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    metodo_pago = models.CharField(
        max_length=20, choices=MetodoPago.choices, default=MetodoPago.CONTRA_ENTREGA
    )
    estado = models.CharField(
        max_length=20, choices=Estado.choices, default=Estado.RECIBIDO
    )
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado"]

    def __str__(self):
        return f"Pedido #{self.pk} ({self.get_estado_display()})"


class ItemPedido(models.Model):
    """Guarda el precio al momento de la compra para no alterar pedidos
    antiguos si el precio cambia después."""

    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="items")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    cantidad = models.DecimalField(max_digits=6, decimal_places=2)
    precio_unitario = models.DecimalField(max_digits=8, decimal_places=2)

    @property
    def subtotal(self):
        return self.cantidad * self.precio_unitario
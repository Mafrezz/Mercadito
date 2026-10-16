"""Entidades originales de Mercadito y sus operaciones de cálculo."""
from decimal import Decimal
from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.functions import Round
from django.utils import timezone

from .validaciones import dinero, validar_cantidad


class Zona(models.Model):
    """Zona de entrega, diferenciada por municipio."""

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
    zona = models.ForeignKey(Zona, on_delete=models.PROTECT, related_name="mercados_ubicados")
    horario = models.CharField(max_length=100, blank=True)
    activo = models.BooleanField(default=True)
    zonas_entrega = models.ManyToManyField(
        Zona, through="MercadoZona", related_name="mercados_que_entregan"
    )

    def __str__(self):
        return self.nombre

    def obtener_cobertura(self, zona):
        if not self.activo:
            raise ValidationError("Este mercado no está activo en este momento.")
        cobertura = MercadoZona.objects.filter(mercado=self, zona=zona).first()
        if cobertura is None:
            raise ValidationError("Este mercado no entrega en la zona seleccionada.")
        return cobertura


class MercadoZona(models.Model):
    """Cobertura de un mercado y su tarifa fija de envío."""
    mercado = models.ForeignKey(Mercado, on_delete=models.CASCADE)
    zona = models.ForeignKey(Zona, on_delete=models.CASCADE)
    tarifa_envio = models.DecimalField(
        max_digits=6, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))]
    )

    class Meta:
        unique_together = ("mercado", "zona")
        constraints = [
            models.CheckConstraint(condition=models.Q(tarifa_envio__gte=0), name="envio_no_negativo")
        ]

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
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT, related_name="productos")
    unidad = models.CharField(max_length=10, choices=Unidad.choices)
    descripcion = models.TextField(blank=True)

    class Meta:
        ordering = ["categoria", "nombre"]

    def __str__(self):
        return self.nombre

    @property
    def permite_fracciones(self):
        return self.unidad in (self.Unidad.LIBRA, self.Unidad.LITRO)

    @property
    def paso_cantidad(self):
        # Cadenas con punto: los atributos numéricos de HTML no usan coma decimal.
        return "0.01" if self.permite_fracciones else "1"

    @property
    def maximo_cantidad(self):
        return "9999.99" if self.permite_fracciones else "9999"


class ProductoMercado(models.Model):
    """Precio y disponibilidad de un producto en un mercado concreto."""
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name="ofertas")
    mercado = models.ForeignKey(Mercado, on_delete=models.CASCADE, related_name="ofertas")
    precio = models.DecimalField(
        max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    disponible = models.BooleanField(default=True)

    class Meta:
        unique_together = ("producto", "mercado")
        constraints = [
            models.CheckConstraint(condition=models.Q(precio__gt=0), name="precio_oferta_positivo")
        ]

    def __str__(self):
        return f"{self.producto} en {self.mercado}: Q{self.precio}"

    def calcular_importe(self, cantidad):
        return dinero(Decimal(self.precio) * validar_cantidad(cantidad, self.producto))


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
    """Se conserva un carrito por usuario y mercado, como en el modelo original."""
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="carritos"
    )
    mercado = models.ForeignKey(Mercado, on_delete=models.CASCADE)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("usuario", "mercado")

    def __str__(self):
        return f"Carrito de {self.usuario} en {self.mercado}"

    def esta_vacio(self):
        return not self.items.exists()

    def detalle_items(self):
        """Consulta los precios actuales en bloque y señala ofertas retiradas."""
        items = list(self.items.select_related("producto").order_by("id"))
        ofertas = {
            oferta.producto_id: oferta
            for oferta in ProductoMercado.objects.filter(
                mercado_id=self.mercado_id, producto_id__in=[i.producto_id for i in items]
            )
        }
        detalle = []
        for item in items:
            oferta = ofertas.get(item.producto_id)
            error = ""
            importe = None
            if oferta is None or not oferta.disponible:
                error = "Producto no disponible; quítalo para continuar."
            else:
                try:
                    cantidad = validar_cantidad(item.cantidad, item.producto)
                    importe = dinero(cantidad * oferta.precio)
                except ValidationError as exc:
                    error = " ".join(exc.messages)
            detalle.append({
                "item": item,
                "producto": item.producto,
                "cantidad": item.cantidad,
                "precio_unitario": oferta.precio if oferta else None,
                "subtotal": importe,
                "disponible": not bool(error),
                "error": error,
            })
        return detalle

    def calcular_subtotal(self):
        detalle = self.detalle_items()
        if any(not linea["disponible"] for linea in detalle):
            raise ValidationError("Revisa los productos no disponibles o las cantidades del carrito.")
        return dinero(sum((linea["subtotal"] for linea in detalle), Decimal("0.00")))

    def calcular_envio(self, zona):
        return self.mercado.obtener_cobertura(zona).tarifa_envio

    def calcular_total(self, zona):
        return dinero(self.calcular_subtotal() + self.calcular_envio(zona))


class ItemCarrito(models.Model):
    carrito = models.ForeignKey(Carrito, on_delete=models.CASCADE, related_name="items")
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE)
    cantidad = models.DecimalField(
        max_digits=6, decimal_places=2, default=1,
        validators=[MinValueValidator(Decimal("0.01"))],
    )

    class Meta:
        unique_together = ("carrito", "producto")
        constraints = [
            models.CheckConstraint(condition=models.Q(cantidad__gt=0), name="cantidad_carrito_positiva")
        ]

    def __str__(self):
        return f"{self.cantidad} de {self.producto}"

    def clean(self):
        super().clean()
        if self.cantidad is not None and self.producto_id:
            try:
                producto = self.producto
            except Producto.DoesNotExist:
                return  # full_clean ya informa la referencia inválida en el campo.
            try:
                self.cantidad = validar_cantidad(self.cantidad, producto)
            except ValidationError as exc:
                raise ValidationError({"cantidad": exc.messages}) from exc

    @property
    def precio_unitario(self):
        oferta = ProductoMercado.objects.filter(
            mercado_id=self.carrito.mercado_id, producto_id=self.producto_id, disponible=True
        ).first()
        if oferta is None:
            raise ValidationError("El producto ya no está disponible en este mercado.")
        return oferta.precio

    @property
    def subtotal(self):
        return dinero(validar_cantidad(self.cantidad, self.producto) * self.precio_unitario)


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
    subtotal = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))]
    )
    costo_envio = models.DecimalField(
        max_digits=6, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))]
    )
    total = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))]
    )
    metodo_pago = models.CharField(
        max_length=20, choices=MetodoPago.choices, default=MetodoPago.CONTRA_ENTREGA
    )
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.RECIBIDO)
    creado = models.DateTimeField(auto_now_add=True)
    # Nulo para los pedidos antiguos. Cada confirmación nueva tiene una clave única.
    token_confirmacion = models.UUIDField(null=True, blank=True, unique=True, editable=False)

    class Meta:
        ordering = ["-creado"]
        constraints = [
            models.CheckConstraint(condition=models.Q(subtotal__gte=0), name="pedido_subtotal_no_negativo"),
            models.CheckConstraint(condition=models.Q(costo_envio__gte=0), name="pedido_envio_no_negativo"),
            models.CheckConstraint(condition=models.Q(total__gte=0), name="pedido_total_no_negativo"),
            models.CheckConstraint(
                condition=models.Q(total=Round(models.F("subtotal") + models.F("costo_envio"), precision=2)),
                name="pedido_total_consistente",
            ),
        ]

    def __str__(self):
        return f"Pedido #{self.pk} ({self.get_estado_display()})"

    def clean(self):
        super().clean()
        self.direccion_entrega = " ".join((self.direccion_entrega or "").split())
        if not self.direccion_entrega:
            raise ValidationError({"direccion_entrega": "Ingresa la dirección de entrega."})
        # Un pedido antiguo sí puede cambiar de estado después de su fecha de entrega.
        if self._state.adding and isinstance(self.fecha_entrega, date) and self.fecha_entrega < timezone.localdate():
            raise ValidationError({"fecha_entrega": "La fecha de entrega no puede estar en el pasado."})

    def calcular_subtotal(self):
        return dinero(sum((item.subtotal for item in self.items.all()), Decimal("0.00")))

    def calcular_total(self):
        return dinero(self.calcular_subtotal() + Decimal(self.costo_envio))

    def actualizar_totales(self):
        """Se usa dentro de la transacción que crea el pedido y sus renglones."""
        self.subtotal = self.calcular_subtotal()
        self.total = dinero(self.subtotal + self.costo_envio)
        self.full_clean()
        self.save(update_fields=["subtotal", "total"])


class ItemPedido(models.Model):
    """Precio guardado al comprar: los cambios del catálogo no alteran el importe."""
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="items")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    cantidad = models.DecimalField(
        max_digits=6, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    precio_unitario = models.DecimalField(
        max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(cantidad__gt=0), name="cantidad_pedido_positiva"),
            models.CheckConstraint(condition=models.Q(precio_unitario__gt=0), name="precio_pedido_positivo"),
        ]

    def __str__(self):
        return f"{self.cantidad} de {self.producto} en pedido #{self.pedido_id}"

    @property
    def subtotal(self):
        return dinero(Decimal(self.cantidad) * Decimal(self.precio_unitario))

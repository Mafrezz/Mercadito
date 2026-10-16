"""Catálogo administrable y consulta de pedidos sin alterar sus importes históricos."""
from django.contrib import admin
from .models import (
    Carrito, Categoria, Direccion, ItemCarrito, ItemPedido, Mercado,
    MercadoZona, Pedido, Producto, ProductoMercado, Zona,
)


class MercadoZonaInline(admin.TabularInline):
    model = MercadoZona
    extra = 1


class ProductoMercadoInline(admin.TabularInline):
    model = ProductoMercado
    extra = 0


class ItemPedidoInline(admin.TabularInline):
    model = ItemPedido
    extra = 0
    fields = ("producto", "cantidad", "precio_unitario", "subtotal")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Mercado)
class MercadoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "zona", "activo")
    inlines = [MercadoZonaInline]


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "categoria", "unidad")
    list_filter = ("categoria",)
    search_fields = ("nombre",)
    inlines = [ProductoMercadoInline]


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ("id", "usuario", "mercado", "zona", "total", "estado", "creado")
    list_filter = ("estado", "mercado")
    search_fields = ("usuario__username", "direccion_entrega")
    inlines = [ItemPedidoInline]
    readonly_fields = (
        "usuario", "mercado", "zona", "direccion_entrega", "fecha_entrega",
        "subtotal", "costo_envio", "total", "metodo_pago", "creado", "token_confirmacion",
    )

    def has_add_permission(self, request):
        # Los pedidos se crean por el flujo de compra, con sus totales calculados.
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Zona)
admin.site.register(Categoria)
admin.site.register(ProductoMercado)
admin.site.register(Direccion)
admin.site.register(Carrito)
admin.site.register(ItemCarrito)
admin.site.site_header = "Administración de Mercadito"
admin.site.site_title = "Mercadito"

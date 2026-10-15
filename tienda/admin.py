from django.contrib import admin

from .models import (
    Carrito,
    Categoria,
    Direccion,
    ItemCarrito,
    ItemPedido,
    Mercado,
    MercadoZona,
    Pedido,
    Producto,
    ProductoMercado,
    Zona,
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


@admin.register(Mercado)
class MercadoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "zona", "activo")
    inlines = [MercadoZonaInline]


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "categoria", "unidad")
    list_filter = ("categoria",)
    inlines = [ProductoMercadoInline]


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ("id", "usuario", "mercado", "zona", "total", "estado", "creado")
    list_filter = ("estado", "mercado")
    inlines = [ItemPedidoInline]


admin.site.register(Zona)
admin.site.register(Categoria)
admin.site.register(ProductoMercado)
admin.site.register(Direccion)
admin.site.register(Carrito)
admin.site.register(ItemCarrito)
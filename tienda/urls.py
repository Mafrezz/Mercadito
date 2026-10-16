from django.urls import path
from . import views

app_name = "tienda"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("mercados/", views.mercados, name="mercados"),
    path("mercado/<int:mercado_id>/", views.catalogo, name="catalogo"),
    path("registro/", views.registro, name="registro"),
    path("ingresar/", views.IngresarView.as_view(), name="ingresar"),
    path("salir/", views.cerrar_sesion, name="salir"),
    path("carritos/", views.carritos, name="carritos"),
    path("carrito/mercado/<int:mercado_id>/", views.ver_carrito, name="ver_carrito"),
    path("carrito/agregar/<int:oferta_id>/", views.agregar, name="agregar"),
    path("carrito/item/<int:item_id>/cantidad/", views.cambiar_cantidad, name="cambiar_cantidad"),
    path("carrito/item/<int:item_id>/quitar/", views.quitar, name="quitar"),
    path("carrito/<int:carrito_id>/vaciar/", views.vaciar, name="vaciar"),
    path("carrito/<int:carrito_id>/confirmar/", views.confirmar, name="confirmar"),
    path("pedidos/", views.pedidos, name="pedidos"),
    path("pedido/<int:pedido_id>/", views.detalle_pedido, name="detalle_pedido"),
]

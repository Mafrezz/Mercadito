from django.urls import path

from . import views

app_name = "tienda"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("mercados/", views.mercados, name="mercados"),
    path("mercado/<int:mercado_id>/", views.catalogo, name="catalogo"),
]
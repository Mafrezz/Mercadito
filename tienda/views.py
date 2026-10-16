"""Navegación pública, cuentas, carrito y pedidos de cada usuario."""
import logging
from itertools import groupby
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import DatabaseError, IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from .forms import CantidadForm, ConfirmarPedidoForm, IngresoForm, RegistroForm
from .models import Carrito, Categoria, ItemCarrito, Mercado, MercadoZona, Pedido, ProductoMercado, Zona
from .servicios import (
    actualizar_item, agregar_producto, confirmar_compra, crear_confirmacion,
    quitar_item, resumen_carrito, vaciar_carrito,
)

logger = logging.getLogger(__name__)


def _id_valido(valor):
    try:
        texto = str(valor)
        if not texto.isascii() or not texto.isdecimal() or len(texto) > 19:
            return None
        numero = int(texto)
        return numero if 0 < numero <= 9223372036854775807 else None
    except (ValueError, TypeError):
        return None


def _zona_seleccionada(request):
    pk = _id_valido(request.session.get("zona_id"))
    return Zona.objects.filter(pk=pk).first() if pk else None


def _destino_seguro(request):
    destino = request.POST.get("next", request.GET.get("next", ""))
    if url_has_allowed_host_and_scheme(
        destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return destino
    return reverse("tienda:inicio")


def inicio(request):
    grupos = {}
    for zona in Zona.objects.all():
        grupos.setdefault(zona.get_municipio_display(), []).append(zona)
    return render(request, "tienda/inicio.html", {
        "grupos": grupos, "categorias": Categoria.objects.all(),
        "zona_actual": _zona_seleccionada(request),
    })


def mercados(request):
    zona_id = _id_valido(request.GET.get("zona", request.session.get("zona_id")))
    zona = Zona.objects.filter(pk=zona_id).first() if zona_id else None
    if zona is None:
        messages.error(request, "Selecciona una zona válida para buscar mercados.")
        return redirect("tienda:inicio")
    request.session["zona_id"] = zona.pk
    coberturas = (
        MercadoZona.objects.filter(zona=zona, mercado__activo=True)
        .select_related("mercado").order_by("tarifa_envio", "mercado__nombre")
    )
    return render(request, "tienda/mercados.html", {"zona": zona, "coberturas": coberturas})


def _render_catalogo(request, mercado, cobertura, formulario_error=None, oferta_error_id=None):
    ofertas = (
        ProductoMercado.objects.filter(mercado=mercado, disponible=True)
        .select_related("producto__categoria")
        .order_by("producto__categoria__orden", "producto__categoria_id", "producto__nombre")
    )
    categoria_activa = _id_valido(request.GET.get("cat"))
    if categoria_activa:
        ofertas = ofertas.filter(producto__categoria_id=categoria_activa)
    ofertas = list(ofertas)
    for oferta in ofertas:
        oferta.formulario = (
            formulario_error if oferta.pk == oferta_error_id else
            CantidadForm(producto=oferta.producto, initial={"cantidad": "1"},
                         auto_id=f"oferta_{oferta.pk}_%s")
        )
    secciones = [
        (categoria, list(items))
        for categoria, items in groupby(ofertas, key=lambda o: o.producto.categoria)
    ]
    return render(request, "tienda/catalogo.html", {
        "mercado": mercado, "cobertura": cobertura, "categorias": Categoria.objects.all(),
        "categoria_activa": categoria_activa, "secciones": secciones,
    })


def catalogo(request, mercado_id):
    zona = _zona_seleccionada(request)
    if zona is None:
        messages.info(request, "Primero selecciona tu zona de entrega.")
        return redirect("tienda:inicio")
    mercado = get_object_or_404(Mercado, pk=mercado_id, activo=True)
    cobertura = MercadoZona.objects.filter(mercado=mercado, zona=zona).select_related("zona").first()
    if cobertura is None:
        messages.warning(request, "Ese mercado no entrega en tu zona. Selecciona otro.")
        return redirect("tienda:mercados")
    return _render_catalogo(request, mercado, cobertura)


@require_http_methods(["GET", "POST"])
def registro(request):
    if request.user.is_authenticated:
        return redirect("tienda:inicio")
    destino = _destino_seguro(request)
    form = RegistroForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                form.save()
        except IntegrityError:
            form.add_error("username", "Ese nombre de usuario ya está registrado. Elige otro.")
        except DatabaseError:
            logger.exception("No se pudo guardar el registro.")
            form.add_error(None, "No se pudo guardar la cuenta. Inténtalo de nuevo en unos momentos.")
        else:
            messages.success(request, "Cuenta creada correctamente. Ya puedes iniciar sesión.")
            # Redirigir evita volver a registrar al actualizar; las contraseñas no se conservan.
            return redirect(reverse("tienda:ingresar") + "?" + urlencode({"next": destino}))
    return render(request, "tienda/registro.html", {"form": form, "next": destino})


class IngresarView(LoginView):
    template_name = "tienda/ingresar.html"
    authentication_form = IngresoForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        respuesta = super().form_valid(form)
        messages.success(self.request, "Sesión iniciada. Ya puedes realizar tus compras.")
        return respuesta


@require_POST
def cerrar_sesion(request):
    logout(request)
    messages.success(request, "Cerraste sesión. Tus carritos y pedidos siguen guardados.")
    return redirect("tienda:inicio")


@login_required
def carritos(request):
    zona = _zona_seleccionada(request)
    guardados = (
        Carrito.objects.filter(usuario=request.user, items__isnull=False)
        .select_related("mercado").distinct().order_by("mercado__nombre")
    )
    resumenes = [resumen_carrito(carrito, zona) for carrito in guardados]
    return render(request, "tienda/carritos.html", {"resumenes": resumenes, "zona": zona})


def _render_carrito(request, mercado, carrito, formulario_error=None, item_error_id=None):
    zona = _zona_seleccionada(request)
    contexto = {"mercado": mercado, "carrito": carrito, "zona": zona, "lineas": []}
    if carrito is not None:
        contexto.update(resumen_carrito(carrito, zona))
        for linea in contexto["lineas"]:
            item = linea["item"]
            linea["formulario"] = (
                formulario_error if item.pk == item_error_id else
                CantidadForm(producto=item.producto, initial={"cantidad": item.cantidad},
                             auto_id=f"item_{item.pk}_%s")
            )
    return render(request, "tienda/carrito.html", contexto)


@login_required
def ver_carrito(request, mercado_id):
    mercado = get_object_or_404(Mercado, pk=mercado_id)
    carrito = Carrito.objects.filter(usuario=request.user, mercado=mercado).select_related("mercado").first()
    return _render_carrito(request, mercado, carrito)


@login_required
@require_POST
def agregar(request, oferta_id):
    oferta = get_object_or_404(ProductoMercado.objects.select_related("mercado", "producto"), pk=oferta_id)
    zona = _zona_seleccionada(request)
    if zona is None:
        messages.error(request, "Selecciona primero tu zona de entrega.")
        return redirect("tienda:inicio")
    cobertura = MercadoZona.objects.filter(mercado=oferta.mercado, zona=zona).select_related("zona").first()
    if cobertura is None or not oferta.mercado.activo:
        messages.error(request, "El mercado no está activo o no entrega en tu zona.")
        return redirect("tienda:mercados")
    form = CantidadForm(request.POST, producto=oferta.producto, auto_id=f"oferta_{oferta.pk}_%s")
    if form.is_valid():
        try:
            agregar_producto(request.user, oferta.pk, form.cleaned_data["cantidad"], zona)
        except ValidationError as exc:
            form.add_error("cantidad", exc)
        except DatabaseError:
            logger.exception("No se pudo agregar un producto al carrito.")
            form.add_error(None, "No se pudo guardar el cambio. Inténtalo de nuevo.")
        else:
            messages.success(request, f"{oferta.producto.nombre} se agregó al carrito.")
            return redirect(reverse("tienda:catalogo", args=[oferta.mercado_id]) + f"#producto-{oferta.pk}")
    if not oferta.disponible:
        messages.error(request, "Este producto ya no está disponible.")
        return redirect("tienda:catalogo", mercado_id=oferta.mercado_id)
    return _render_catalogo(request, oferta.mercado, cobertura, form, oferta.pk)


@login_required
@require_POST
def cambiar_cantidad(request, item_id):
    item = get_object_or_404(
        ItemCarrito.objects.select_related("producto", "carrito__mercado"),
        pk=item_id, carrito__usuario=request.user,
    )
    form = CantidadForm(request.POST, producto=item.producto, auto_id=f"item_{item.pk}_%s")
    if form.is_valid():
        try:
            actualizar_item(request.user, item.pk, form.cleaned_data["cantidad"])
        except ValidationError as exc:
            form.add_error("cantidad", exc)
        except DatabaseError:
            logger.exception("No se pudo modificar la cantidad del carrito.")
            form.add_error(None, "No se pudo guardar la cantidad. Inténtalo de nuevo.")
        else:
            messages.success(request, "Cantidad actualizada.")
            return redirect("tienda:ver_carrito", mercado_id=item.carrito.mercado_id)
    return _render_carrito(request, item.carrito.mercado, item.carrito, form, item.pk)


@login_required
@require_POST
def quitar(request, item_id):
    item = get_object_or_404(ItemCarrito.objects.select_related("carrito"), pk=item_id, carrito__usuario=request.user)
    mercado_id = item.carrito.mercado_id
    try:
        quitar_item(request.user, item.pk)
    except DatabaseError:
        logger.exception("No se pudo quitar un producto del carrito.")
        messages.error(request, "No se pudo quitar el producto. Inténtalo de nuevo.")
    else:
        messages.success(request, "Producto eliminado del carrito.")
    return redirect("tienda:ver_carrito", mercado_id=mercado_id)


@login_required
@require_POST
def vaciar(request, carrito_id):
    carrito = get_object_or_404(Carrito, pk=carrito_id, usuario=request.user)
    try:
        vaciar_carrito(request.user, carrito.pk)
    except DatabaseError:
        logger.exception("No se pudo vaciar el carrito.")
        messages.error(request, "No se pudo vaciar el carrito. Inténtalo de nuevo.")
    else:
        messages.success(request, "Carrito vaciado.")
    return redirect("tienda:ver_carrito", mercado_id=carrito.mercado_id)


@login_required
@require_http_methods(["GET", "POST"])
def confirmar(request, carrito_id):
    carrito = get_object_or_404(Carrito.objects.select_related("mercado"), pk=carrito_id, usuario=request.user)
    zona = _zona_seleccionada(request)
    form = ConfirmarPedidoForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            pedido, creado = confirmar_compra(
                usuario=request.user, carrito_id=carrito.pk, zona=zona,
                direccion=form.cleaned_data["direccion_entrega"],
                fecha=form.cleaned_data["fecha_entrega"],
                confirmacion=form.cleaned_data["confirmacion"],
            )
        except ValidationError as exc:
            form.add_error(None, " ".join(exc.messages))
        except DatabaseError:
            logger.exception("No se pudo completar la confirmación del pedido.")
            form.add_error(None, "No se pudo completar la operación. Revisa Mis pedidos antes de reintentar.")
        else:
            messages.success(request, "Pedido confirmado. Pagarás al recibirlo." if creado else "Este pedido ya estaba confirmado.")
            return redirect("tienda:detalle_pedido", pedido_id=pedido.pk)
    # Después de un error volvemos a consultar: precios y disponibilidad pueden haber cambiado.
    carrito.refresh_from_db()
    contexto = resumen_carrito(carrito, zona)
    if not contexto["puede_confirmar"]:
        messages.error(request, contexto["aviso"] or "Agrega productos disponibles al carrito antes de confirmar.")
        return redirect("tienda:ver_carrito", mercado_id=carrito.mercado_id)
    token = crear_confirmacion(carrito, contexto)
    if form.is_bound:
        # Se conservan dirección y fecha, pero el nuevo resumen obtiene una confirmación nueva.
        form.data = form.data.copy()
        form.data["confirmacion"] = token
    else:
        form.initial["confirmacion"] = token
    contexto["form"] = form
    return render(request, "tienda/confirmar.html", contexto)


@login_required
def pedidos(request):
    consulta = Pedido.objects.filter(usuario=request.user).select_related("mercado", "zona")
    pagina = Paginator(consulta, 10).get_page(request.GET.get("pagina"))
    return render(request, "tienda/pedidos.html", {"pagina": pagina})


@login_required
def detalle_pedido(request, pedido_id):
    pedido = get_object_or_404(
        Pedido.objects.select_related("mercado", "zona").prefetch_related("items__producto"),
        pk=pedido_id, usuario=request.user,
    )
    return render(request, "tienda/detalle_pedido.html", {"pedido": pedido})

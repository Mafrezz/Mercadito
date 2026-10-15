from itertools import groupby

from django.shortcuts import get_object_or_404, redirect, render

from .models import Categoria, Mercado, MercadoZona, ProductoMercado, Zona


def inicio(request):
    """Pantalla de inicio: el usuario elige su zona."""
    grupos = {}
    for zona in Zona.objects.all():
        grupos.setdefault(zona.get_municipio_display(), []).append(zona)
    contexto = {"grupos": grupos, "categorias": Categoria.objects.all()}
    return render(request, "tienda/inicio.html", contexto)


def mercados(request):
    """Muestra los mercados que entregan en la zona elegida."""
    zona_id = request.GET.get("zona") or request.session.get("zona_id")
    if not zona_id or not str(zona_id).isdigit():
        return redirect("tienda:inicio")

    zona = get_object_or_404(Zona, pk=zona_id)
    request.session["zona_id"] = zona.id  # recordamos la zona del usuario

    coberturas = (
        MercadoZona.objects.filter(zona=zona, mercado__activo=True)
        .select_related("mercado")
        .order_by("tarifa_envio", "mercado__nombre")
    )
    return render(request, "tienda/mercados.html", {"zona": zona, "coberturas": coberturas})


def catalogo(request, mercado_id):
    """Productos de un mercado, con los precios de ese mercado."""
    zona_id = request.session.get("zona_id")
    if not zona_id:
        return redirect("tienda:inicio")

    mercado = get_object_or_404(Mercado, pk=mercado_id, activo=True)

    # El mercado solo se puede abrir si entrega en la zona del usuario.
    cobertura = (
        MercadoZona.objects.filter(mercado=mercado, zona_id=zona_id)
        .select_related("zona")
        .first()
    )
    if cobertura is None:
        return redirect("tienda:mercados")

    ofertas = (
        ProductoMercado.objects.filter(mercado=mercado, disponible=True)
        .select_related("producto__categoria")
        .order_by("producto__categoria__orden", "producto__nombre")
    )

    categoria_activa = None
    cat = request.GET.get("cat", "")
    if cat.isdigit():
        categoria_activa = int(cat)
        ofertas = ofertas.filter(producto__categoria_id=categoria_activa)

    # Agrupamos las ofertas por categoría: [(categoria, [ofertas...]), ...]
    secciones = [
        (categoria, list(items))
        for categoria, items in groupby(ofertas, key=lambda o: o.producto.categoria)
    ]

    contexto = {
        "mercado": mercado,
        "cobertura": cobertura,
        "categorias": Categoria.objects.all(),
        "categoria_activa": categoria_activa,
        "secciones": secciones,
    }
    return render(request, "tienda/catalogo.html", contexto)
"""Operaciones de compra. No se aceptan precios ni totales enviados por el navegador.

Todas las escrituras del carrito bloquean primero su fila. En PostgreSQL esto
serializa las operaciones simultáneas de un mismo carrito. El pedido y sus
renglones se confirman juntos, o se revierte toda la operación.
"""
import hashlib
import json
from decimal import Decimal
from uuid import UUID, uuid4

from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404

from .models import Carrito, ItemCarrito, ItemPedido, Mercado, MercadoZona, Pedido, ProductoMercado
from .validaciones import dinero, validar_cantidad

SAL_CONFIRMACION = "tienda.confirmar-pedido.v1"
VIGENCIA_CONFIRMACION = 2 * 60 * 60


def resumen_carrito(carrito, zona):
    """Se utiliza tanto para mostrar el resumen como para verificarlo al comprar."""
    lineas = carrito.detalle_items()
    productos_validos = bool(lineas) and all(linea["disponible"] for linea in lineas)
    subtotal = (
        dinero(sum((linea["subtotal"] for linea in lineas), Decimal("0.00")))
        if productos_validos else None
    )
    cobertura = None
    aviso = ""
    if not carrito.mercado.activo:
        aviso = "El mercado está inactivo. Puedes quitar los productos o vaciar el carrito."
    elif zona is None:
        aviso = "Selecciona tu zona para calcular el envío."
    else:
        cobertura = MercadoZona.objects.filter(mercado=carrito.mercado, zona=zona).first()
        if cobertura is None:
            aviso = "Este mercado no entrega en tu zona. Cambia de zona o elige otro mercado."
    envio = cobertura.tarifa_envio if cobertura else None
    total = dinero(subtotal + envio) if subtotal is not None and envio is not None else None
    return {
        "carrito": carrito, "mercado": carrito.mercado, "zona": zona, "lineas": lineas,
        "subtotal": subtotal, "costo_envio": envio, "total": total, "aviso": aviso,
        "puede_confirmar": productos_validos and cobertura is not None and carrito.mercado.activo,
    }


def _huella(resumen):
    # Incluye precios, cantidades, productos, zona y tarifa. Un cambio exige revisar de nuevo.
    datos = {
        "zona": resumen["zona"].pk,
        "envio": str(resumen["costo_envio"]),
        "items": [
            [linea["item"].pk, linea["producto"].pk, str(linea["cantidad"]), str(linea["precio_unitario"])]
            for linea in resumen["lineas"]
        ],
    }
    return hashlib.sha256(json.dumps(datos, sort_keys=True).encode("utf-8")).hexdigest()


def crear_confirmacion(carrito, resumen):
    if not resumen["puede_confirmar"]:
        raise ValidationError("El carrito todavía no se puede confirmar.")
    return signing.dumps({
        "usuario": carrito.usuario_id, "carrito": carrito.pk,
        "token": str(uuid4()), "huella": _huella(resumen),
    }, salt=SAL_CONFIRMACION)


def _leer_confirmacion(confirmacion, usuario, carrito_id):
    try:
        datos = signing.loads(confirmacion, salt=SAL_CONFIRMACION, max_age=VIGENCIA_CONFIRMACION)
        if not isinstance(datos, dict):
            raise ValueError
        if datos.get("usuario") != usuario.pk or datos.get("carrito") != carrito_id:
            raise ValueError
        datos["token"] = UUID(datos["token"])
        if not isinstance(datos.get("huella"), str):
            raise ValueError
        return datos
    except (signing.BadSignature, ValueError, KeyError, TypeError, AttributeError):
        raise ValidationError("La confirmación venció o no es válida. Revisa el resumen e inténtalo de nuevo.") from None


@transaction.atomic
def agregar_producto(usuario, oferta_id, cantidad, zona):
    oferta_inicial = get_object_or_404(ProductoMercado, pk=oferta_id)
    # get_or_create respeta la unicidad (usuario, mercado); después se toma el bloqueo.
    carrito, _ = Carrito.objects.get_or_create(usuario=usuario, mercado_id=oferta_inicial.mercado_id)
    carrito = Carrito.objects.select_for_update().get(pk=carrito.pk)
    mercado = get_object_or_404(Mercado.objects.select_for_update(), pk=carrito.mercado_id)
    if zona is None:
        raise ValidationError("Selecciona tu zona de entrega antes de agregar productos.")
    mercado.obtener_cobertura(zona)
    oferta = get_object_or_404(
        ProductoMercado.objects.select_for_update(of=("self",)).select_related("producto"),
        pk=oferta_id,
    )
    if oferta.mercado_id != mercado.pk:
        raise ValidationError("La oferta cambió de mercado. Actualiza el catálogo.")
    if not oferta.disponible:
        raise ValidationError("Este producto ya no está disponible.")
    cantidad = validar_cantidad(cantidad, oferta.producto)
    item = ItemCarrito.objects.filter(carrito=carrito, producto=oferta.producto).first()
    if item is None:
        item = ItemCarrito(carrito=carrito, producto=oferta.producto, cantidad=cantidad)
    else:
        item.cantidad = validar_cantidad(item.cantidad + cantidad, oferta.producto)
    item.full_clean()
    item.save()
    return item


@transaction.atomic
def actualizar_item(usuario, item_id, cantidad):
    referencia = get_object_or_404(ItemCarrito, pk=item_id, carrito__usuario=usuario)
    carrito = Carrito.objects.select_for_update().get(pk=referencia.carrito_id, usuario=usuario)
    item = get_object_or_404(ItemCarrito.objects.select_related("producto"), pk=item_id, carrito=carrito)
    item.cantidad = validar_cantidad(cantidad, item.producto)
    item.full_clean()
    item.save(update_fields=["cantidad"])
    return carrito.mercado_id


@transaction.atomic
def quitar_item(usuario, item_id):
    referencia = get_object_or_404(ItemCarrito, pk=item_id, carrito__usuario=usuario)
    carrito = Carrito.objects.select_for_update().get(pk=referencia.carrito_id, usuario=usuario)
    item = get_object_or_404(ItemCarrito, pk=item_id, carrito=carrito)
    item.delete()
    return carrito.mercado_id


@transaction.atomic
def vaciar_carrito(usuario, carrito_id):
    carrito = get_object_or_404(Carrito.objects.select_for_update(), pk=carrito_id, usuario=usuario)
    carrito.items.all().delete()
    return carrito.mercado_id


@transaction.atomic
def confirmar_compra(*, usuario, carrito_id, zona, direccion, fecha, confirmacion):
    """Devuelve (pedido, creado). Reenviar la misma confirmación no duplica el pedido."""
    datos = _leer_confirmacion(confirmacion, usuario, carrito_id)
    carrito = get_object_or_404(Carrito.objects.select_for_update(), pk=carrito_id, usuario=usuario)
    existente = Pedido.objects.filter(usuario=usuario, token_confirmacion=datos["token"]).first()
    if existente is not None:
        return existente, False
    # Mismo orden de bloqueo que agregar_producto: carrito -> mercado -> ofertas.
    mercado = get_object_or_404(Mercado.objects.select_for_update(), pk=carrito.mercado_id)
    carrito.mercado = mercado
    if zona is not None:
        list(MercadoZona.objects.select_for_update().filter(mercado=mercado, zona=zona))
    list(ProductoMercado.objects.select_for_update().filter(
        mercado=mercado, producto_id__in=carrito.items.values("producto_id")
    ).order_by("pk"))
    resumen = resumen_carrito(carrito, zona)
    if not resumen["lineas"]:
        raise ValidationError("El carrito está vacío. Agrega productos antes de confirmar.")
    if not resumen["puede_confirmar"]:
        raise ValidationError(resumen["aviso"] or "Revisa los productos no disponibles del carrito.")
    if datos["huella"] != _huella(resumen):
        raise ValidationError("El carrito, los precios o el envío cambiaron. Revisa el resumen y vuelve a confirmar.")
    if resumen["total"] > Decimal("99999999.99"):
        raise ValidationError("El total excede el máximo permitido. Reduce las cantidades del pedido.")
    pedido = Pedido(
        usuario=usuario, mercado=mercado, zona=zona,
        direccion_entrega=direccion, fecha_entrega=fecha,
        subtotal=resumen["subtotal"], costo_envio=resumen["costo_envio"], total=resumen["total"],
        token_confirmacion=datos["token"],
    )
    pedido.full_clean()
    pedido.save()
    for linea in resumen["lineas"]:
        item = ItemPedido(
            pedido=pedido, producto=linea["producto"], cantidad=linea["cantidad"],
            precio_unitario=linea["precio_unitario"],
        )
        item.full_clean()
        item.save()
    pedido.actualizar_totales()
    # La fila del carrito se conserva para que otras peticiones puedan bloquearla.
    carrito.items.all().delete()
    return pedido, True

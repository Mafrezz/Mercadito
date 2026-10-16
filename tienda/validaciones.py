"""Validaciones compartidas por formularios, modelos y operaciones de compra."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.core.validators import DecimalValidator

CENTAVO = Decimal("0.01")
CANTIDAD_MAXIMA = Decimal("9999.99")


def dinero(valor):
    """Redondea cada importe a centavos, sin convertirlo a float."""
    return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def validar_cantidad(valor, producto=None):
    """Libras/litros admiten fracciones; unidades/docenas se compran completas."""
    try:
        cantidad = Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError("Ingresa una cantidad numérica válida.") from None
    if not cantidad.is_finite() or not Decimal("0") < cantidad <= CANTIDAD_MAXIMA:
        raise ValidationError("La cantidad debe ser mayor que cero y no exceder 9999.99.")
    DecimalValidator(max_digits=6, decimal_places=2)(cantidad)
    if producto is not None and not producto.permite_fracciones:
        if cantidad != cantidad.to_integral_value():
            raise ValidationError("Este producto se vende por unidades o docenas completas.")
    return cantidad

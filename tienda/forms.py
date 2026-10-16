"""Entradas de usuario: mensajes en español y validación en el servidor."""
from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.utils import timezone

from .validaciones import validar_cantidad


class RegistroForm(UserCreationForm):
    first_name = forms.CharField(label="Nombres", max_length=150)
    last_name = forms.CharField(label="Apellidos", max_length=150)
    email = forms.EmailField(label="Correo electrónico", max_length=254)

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username", "first_name", "last_name", "email", "password1", "password2")
        labels = {"username": "Nombre de usuario"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        autocompletar = {"first_name": "given-name", "last_name": "family-name", "email": "email"}
        for nombre, valor in autocompletar.items():
            self.fields[nombre].widget.attrs["autocomplete"] = valor

    def clean_first_name(self):
        return " ".join(self.cleaned_data["first_name"].split())

    def clean_last_name(self):
        return " ".join(self.cleaned_data["last_name"].split())

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


class IngresoForm(AuthenticationForm):
    error_messages = {
        "invalid_login": "El nombre de usuario o la contraseña no son correctos.",
        "inactive": "Esta cuenta no está activa.",
    }


class CantidadForm(forms.Form):
    cantidad = forms.DecimalField(
        label="Cantidad", max_digits=6, decimal_places=2,
        min_value=Decimal("0.01"), max_value=Decimal("9999.99"),
        error_messages={
            "required": "Ingresa una cantidad.",
            "invalid": "Ingresa una cantidad numérica válida.",
            "min_value": "La cantidad debe ser mayor que cero.",
            "max_value": "La cantidad no puede exceder 9999.99.",
            "max_decimal_places": "Utiliza como máximo dos decimales.",
        },
    )

    def __init__(self, *args, producto, **kwargs):
        super().__init__(*args, **kwargs)
        self.producto = producto
        self.fields["cantidad"].widget.attrs.update({
            "min": producto.paso_cantidad,
            "step": producto.paso_cantidad,
            "max": producto.maximo_cantidad,
            "aria-label": f"Cantidad de {producto.nombre}",
        })

    def clean_cantidad(self):
        return validar_cantidad(self.cleaned_data["cantidad"], self.producto)


class ConfirmarPedidoForm(forms.Form):
    direccion_entrega = forms.CharField(
        label="Dirección completa de entrega", max_length=300,
        widget=forms.Textarea(attrs={"rows": 3, "autocomplete": "street-address"}),
        help_text="Incluye calle, avenida, número de casa y referencias. Máximo 300 caracteres.",
        error_messages={"required": "Ingresa la dirección de entrega."},
    )
    fecha_entrega = forms.DateField(
        label="Fecha de entrega", input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        error_messages={
            "required": "Selecciona una fecha de entrega.",
            "invalid": "Selecciona una fecha válida.",
        },
    )
    confirmacion = forms.CharField(widget=forms.HiddenInput, max_length=2000)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fecha_entrega"].widget.attrs["min"] = timezone.localdate().isoformat()

    def clean_direccion_entrega(self):
        direccion = " ".join(self.cleaned_data["direccion_entrega"].split())
        if len(direccion) < 8:
            raise forms.ValidationError("Escribe una dirección más completa (al menos 8 caracteres).")
        return direccion

    def clean_fecha_entrega(self):
        fecha = self.cleaned_data["fecha_entrega"]
        if fecha < timezone.localdate():
            raise forms.ValidationError("La fecha de entrega no puede estar en el pasado.")
        return fecha

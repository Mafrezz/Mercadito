"""Pruebas del flujo completo y de entradas incorrectas.

Normal (PostgreSQL): python manage.py test tienda
Sin PostgreSQL: python manage.py test tienda --settings=mercadito.settings_pruebas
Las dos pruebas de concurrencia se ejecutan únicamente en PostgreSQL.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, OperationalError, connection, connections, transaction
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .forms import CantidadForm, ConfirmarPedidoForm
from .models import Carrito, Categoria, ItemCarrito, ItemPedido, Mercado, MercadoZona, Pedido, Producto, ProductoMercado, Zona
from .servicios import agregar_producto, confirmar_compra, crear_confirmacion, resumen_carrito
from .validaciones import dinero

CLAVE = "Prueba-Mercadito_2026!"


def crear_datos(cls):
    cls.usuario = get_user_model().objects.create_user(username="cliente", password=CLAVE, first_name="Ana")
    cls.otro = get_user_model().objects.create_user(username="otro", password=CLAVE)
    cls.zona = Zona.objects.create(numero=1, municipio="GUATEMALA")
    cls.zona2 = Zona.objects.create(numero=1, municipio="MIXCO")
    cls.sin_cobertura = Zona.objects.create(numero=2, municipio="MIXCO")
    cls.mercado = Mercado.objects.create(nombre="Mercado de prueba", zona=cls.zona)
    cls.mercado2 = Mercado.objects.create(nombre="Segundo mercado", zona=cls.zona)
    cls.cobertura = MercadoZona.objects.create(mercado=cls.mercado, zona=cls.zona, tarifa_envio="10.00")
    MercadoZona.objects.create(mercado=cls.mercado, zona=cls.zona2, tarifa_envio="12.50")
    MercadoZona.objects.create(mercado=cls.mercado2, zona=cls.zona, tarifa_envio="8.00")
    cls.categoria = Categoria.objects.create(nombre="Verduras", orden=1)
    cls.producto = Producto.objects.create(nombre="Tomate", categoria=cls.categoria, unidad="LIBRA")
    cls.unidad = Producto.objects.create(nombre="Jabón", categoria=cls.categoria, unidad="UNIDAD")
    cls.oferta = ProductoMercado.objects.create(producto=cls.producto, mercado=cls.mercado, precio="8.50")
    cls.oferta_unidad = ProductoMercado.objects.create(producto=cls.unidad, mercado=cls.mercado, precio="7.25")
    cls.oferta2 = ProductoMercado.objects.create(producto=cls.producto, mercado=cls.mercado2, precio="9.00")


class DatosTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        crear_datos(cls)

    def entrar(self, usuario=None):
        self.client.force_login(usuario or self.usuario)
        self.elegir_zona(self.zona)

    def elegir_zona(self, zona):
        sesion = self.client.session
        sesion["zona_id"] = zona.pk
        sesion.save()

    def preparar_carrito(self, cantidad="2.00", usuario=None, oferta=None):
        item = agregar_producto(usuario or self.usuario, (oferta or self.oferta).pk, Decimal(cantidad), self.zona)
        return item.carrito

    def datos_pedido(self, carrito):
        respuesta = self.client.get(reverse("tienda:confirmar", args=[carrito.pk]))
        self.assertEqual(respuesta.status_code, 200)
        return {
            "direccion_entrega": "  5a avenida    10-20, casa verde  ",
            "fecha_entrega": (timezone.localdate() + timedelta(days=1)).isoformat(),
            "confirmacion": respuesta.context["form"].initial["confirmacion"],
        }

    def comprar(self, carrito=None):
        carrito = carrito or self.preparar_carrito()
        datos = self.datos_pedido(carrito)
        respuesta = self.client.post(reverse("tienda:confirmar", args=[carrito.pk]), datos)
        self.assertEqual(respuesta.status_code, 302, getattr(respuesta, "context", None))
        return Pedido.objects.get(usuario=self.usuario), datos


class FormulariosTest(SimpleTestCase):
    def setUp(self):
        self.producto = Producto(nombre="Tomate", unidad="LIBRA")

    def test_cantidades_invalidas(self):
        for valor in ("", "0", "-2", "abc", "NaN", "Infinity", "1.234", "10000", "1e999999"):
            with self.subTest(valor=valor):
                form = CantidadForm({"cantidad": valor}, producto=self.producto)
                self.assertFalse(form.is_valid())

    def test_fracciones_libras_y_litros(self):
        for unidad in ("LIBRA", "LITRO"):
            with self.subTest(unidad=unidad):
                self.producto.unidad = unidad
                form = CantidadForm({"cantidad": "1.25"}, producto=self.producto)
                self.assertTrue(form.is_valid())
                self.assertEqual(form.cleaned_data["cantidad"], Decimal("1.25"))

    def test_no_fracciones_unidades_y_docenas(self):
        for unidad in ("UNIDAD", "DOCENA"):
            with self.subTest(unidad=unidad):
                self.producto.unidad = unidad
                self.assertFalse(CantidadForm({"cantidad": "1.50"}, producto=self.producto).is_valid())
                self.assertTrue(CantidadForm({"cantidad": "2"}, producto=self.producto).is_valid())

    def test_importes_redondeados_a_centavos(self):
        self.assertEqual(dinero(Decimal("1.005")), Decimal("1.01"))
        self.assertEqual(dinero(Decimal("1.004")), Decimal("1.00"))

    def test_direccion_vacia_corta_y_larga(self):
        for direccion in ("", "     ", "Casa", "x" * 301):
            with self.subTest(direccion=direccion[:10]):
                form = ConfirmarPedidoForm({"direccion_entrega": direccion,
                    "fecha_entrega": timezone.localdate().isoformat(), "confirmacion": "prueba"})
                self.assertFalse(form.is_valid())
                self.assertIn("direccion_entrega", form.errors)

    def test_fecha_pasada_o_inexistente(self):
        for fecha in ((timezone.localdate() - timedelta(days=1)).isoformat(), "2026-02-30", "texto", ""):
            with self.subTest(fecha=fecha):
                form = ConfirmarPedidoForm({"direccion_entrega": "Calle de prueba, casa 10",
                    "fecha_entrega": fecha, "confirmacion": "prueba"})
                self.assertFalse(form.is_valid())
                self.assertIn("fecha_entrega", form.errors)

    def test_acepta_hoy_y_limpia_direccion(self):
        form = ConfirmarPedidoForm({"direccion_entrega": "  Calle   central, casa 10  ",
            "fecha_entrega": timezone.localdate().isoformat(), "confirmacion": "prueba"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["direccion_entrega"], "Calle central, casa 10")


class NavegacionTest(DatosTest):
    def test_inicio_publico(self):
        self.assertContains(self.client.get(reverse("tienda:inicio")), "El mercado de tu zona")

    def test_seleccion_zona_y_catalogo_publico(self):
        respuesta = self.client.get(reverse("tienda:mercados"), {"zona": self.zona.pk})
        self.assertContains(respuesta, self.mercado.nombre)
        self.assertEqual(self.client.session["zona_id"], self.zona.pk)
        respuesta = self.client.get(reverse("tienda:catalogo", args=[self.mercado.pk]))
        self.assertContains(respuesta, "Tomate")
        self.assertContains(respuesta, "Iniciar sesión")

    def test_zonas_invalidas_no_producen_error_interno(self):
        for zona in ("", "texto", "-1", "99999999999999999999999999999", "²", "0"):
            with self.subTest(zona=zona):
                self.assertRedirects(self.client.get(reverse("tienda:mercados"), {"zona": zona}), reverse("tienda:inicio"))

    def test_zona_sin_cobertura(self):
        respuesta = self.client.get(reverse("tienda:mercados"), {"zona": self.sin_cobertura.pk})
        self.assertContains(respuesta, "Todavía ningún mercado")

    def test_catalogo_sin_zona_redirige(self):
        self.assertRedirects(self.client.get(reverse("tienda:catalogo", args=[self.mercado.pk])), reverse("tienda:inicio"))

    def test_catalogo_no_entrega_en_zona(self):
        self.elegir_zona(self.sin_cobertura)
        self.assertRedirects(self.client.get(reverse("tienda:catalogo", args=[self.mercado.pk])), reverse("tienda:mercados"))

    def test_categoria_invalida_no_produce_error(self):
        self.elegir_zona(self.zona)
        for valor in ("texto", "²", "9" * 50):
            with self.subTest(valor=valor):
                self.assertEqual(self.client.get(reverse("tienda:catalogo", args=[self.mercado.pk]), {"cat": valor}).status_code, 200)

    def test_categorias_mismo_orden_se_agrupan_correctamente(self):
        otra = Categoria.objects.create(nombre="Frutas", orden=1)
        fruta = Producto.objects.create(nombre="Manzana", categoria=otra, unidad="LIBRA")
        ProductoMercado.objects.create(producto=fruta, mercado=self.mercado, precio="5.00")
        self.elegir_zona(self.zona)
        respuesta = self.client.get(reverse("tienda:catalogo", args=[self.mercado.pk]))
        self.assertEqual(len(respuesta.context["secciones"]), 2)


class CuentasTest(DatosTest):
    def datos_registro(self, **cambios):
        datos = {"username": "compradora", "first_name": "  Maria   Fernanda  ",
            "last_name": "Alvarez", "email": "  EJEMPLO@example.com ", "password1": CLAVE, "password2": CLAVE}
        datos.update(cambios)
        return datos

    def test_registro_crea_usuario_con_hash_y_limpia_campos(self):
        respuesta = self.client.post(reverse("tienda:registro"), self.datos_registro(), follow=True)
        usuario = get_user_model().objects.get(username="compradora")
        self.assertTrue(usuario.check_password(CLAVE))
        self.assertNotEqual(usuario.password, CLAVE)
        self.assertEqual(usuario.first_name, "Maria Fernanda")
        self.assertEqual(usuario.email, "ejemplo@example.com")
        self.assertTemplateUsed(respuesta, "tienda/ingresar.html")
        self.assertFalse(respuesta.context["form"].is_bound)

    def test_usuario_duplicado(self):
        for nombre in ("cliente", "CLIENTE"):
            with self.subTest(nombre=nombre):
                respuesta = self.client.post(reverse("tienda:registro"), self.datos_registro(username=nombre))
                self.assertIn("username", respuesta.context["form"].errors)
        self.assertEqual(get_user_model().objects.count(), 2)

    def test_registro_rechaza_campos_vacios(self):
        respuesta = self.client.post(reverse("tienda:registro"), {})
        self.assertIn("username", respuesta.context["form"].errors)
        self.assertEqual(get_user_model().objects.count(), 2)

    def test_registro_rechaza_email_invalido(self):
        respuesta = self.client.post(reverse("tienda:registro"), self.datos_registro(email="no-correo"))
        self.assertIn("email", respuesta.context["form"].errors)

    def test_registro_rechaza_contrasenas_diferentes(self):
        respuesta = self.client.post(reverse("tienda:registro"), self.datos_registro(password2="Otra clave"))
        self.assertIn("password2", respuesta.context["form"].errors)

    def test_registro_rechaza_contrasena_debil(self):
        respuesta = self.client.post(reverse("tienda:registro"), self.datos_registro(password1="123", password2="123"))
        self.assertIn("password2", respuesta.context["form"].errors)

    def test_registro_con_colision_de_escritura(self):
        with patch("tienda.views.RegistroForm.save", side_effect=IntegrityError("simulada")):
            respuesta = self.client.post(reverse("tienda:registro"), self.datos_registro())
        self.assertIn("username", respuesta.context["form"].errors)
        self.assertEqual(get_user_model().objects.count(), 2)

    def test_login_correcto_y_conserva_zona(self):
        self.elegir_zona(self.zona)
        respuesta = self.client.post(reverse("tienda:ingresar"), {"username": "cliente", "password": CLAVE})
        self.assertRedirects(respuesta, reverse("tienda:inicio"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.usuario.pk)
        self.assertEqual(self.client.session["zona_id"], self.zona.pk)

    def test_login_incorrecto(self):
        respuesta = self.client.post(reverse("tienda:ingresar"), {"username": "cliente", "password": "incorrecta"})
        self.assertContains(respuesta, "no son correctos")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_usuario_inactivo(self):
        self.usuario.is_active = False
        self.usuario.save()
        self.client.post(reverse("tienda:ingresar"), {"username": "cliente", "password": CLAVE})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_no_redirige_a_dominio_externo(self):
        respuesta = self.client.post(reverse("tienda:ingresar"), {"username": "cliente", "password": CLAVE, "next": "https://example.invalid/"})
        self.assertRedirects(respuesta, reverse("tienda:inicio"))

    def test_registro_no_redirige_a_dominio_externo(self):
        respuesta = self.client.post(reverse("tienda:registro"), self.datos_registro(next="https://example.invalid/"))
        self.assertNotIn("example.invalid", respuesta.url)

    def test_logout_solo_post_y_conserva_carrito(self):
        self.entrar()
        carrito = self.preparar_carrito()
        self.assertEqual(self.client.get(reverse("tienda:salir")).status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)
        self.assertRedirects(self.client.post(reverse("tienda:salir")), reverse("tienda:inicio"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(carrito.items.count(), 1)


class CarritoTest(DatosTest):
    def setUp(self):
        self.entrar()

    def test_agregar_y_repetir_suma_sin_duplicar_fila(self):
        url = reverse("tienda:agregar", args=[self.oferta.pk])
        self.assertEqual(self.client.post(url, {"cantidad": "1.25"}).status_code, 302)
        self.client.post(url, {"cantidad": "2.50"})
        self.assertEqual(ItemCarrito.objects.count(), 1)
        self.assertEqual(ItemCarrito.objects.get().cantidad, Decimal("3.75"))

    def test_agregar_invalido_mantiene_formulario_y_no_guarda(self):
        respuesta = self.client.post(reverse("tienda:agregar", args=[self.oferta.pk]), {"cantidad": "-1"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "La cantidad debe ser mayor que cero")
        self.assertEqual(ItemCarrito.objects.count(), 0)

    def test_agregar_unidades_fraccionarias_falla(self):
        self.client.post(reverse("tienda:agregar", args=[self.oferta_unidad.pk]), {"cantidad": "0.5"})
        self.assertFalse(ItemCarrito.objects.exists())

    def test_suma_supera_maximo_no_modifica(self):
        carrito = self.preparar_carrito("9999.00")
        respuesta = self.client.post(reverse("tienda:agregar", args=[self.oferta.pk]), {"cantidad": "1.00"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(carrito.items.get().cantidad, Decimal("9999.00"))

    def test_mercados_tienen_carritos_independientes(self):
        uno = self.preparar_carrito("1")
        dos = self.preparar_carrito("1", oferta=self.oferta2)
        self.assertNotEqual(uno.pk, dos.pk)
        self.assertEqual(uno.calcular_subtotal(), Decimal("8.50"))
        self.assertEqual(dos.calcular_subtotal(), Decimal("9.00"))

    def test_metodos_de_calculo(self):
        carrito = self.preparar_carrito("2.50")
        self.assertFalse(carrito.esta_vacio())
        self.assertEqual(carrito.items.get().subtotal, Decimal("21.25"))
        self.assertEqual(carrito.calcular_subtotal(), Decimal("21.25"))
        self.assertEqual(carrito.calcular_envio(self.zona), Decimal("10.00"))
        self.assertEqual(carrito.calcular_total(self.zona), Decimal("31.25"))

    def test_actualizar_reemplaza_cantidad(self):
        carrito = self.preparar_carrito()
        item = carrito.items.get()
        respuesta = self.client.post(reverse("tienda:cambiar_cantidad", args=[item.pk]), {"cantidad": "4.50"})
        self.assertEqual(respuesta.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.cantidad, Decimal("4.50"))

    def test_actualizar_invalido_conserva_valor_guardado(self):
        item = self.preparar_carrito().items.get()
        respuesta = self.client.post(reverse("tienda:cambiar_cantidad", args=[item.pk]), {"cantidad": "0"})
        self.assertContains(respuesta, "La cantidad debe ser mayor que cero")
        item.refresh_from_db()
        self.assertEqual(item.cantidad, Decimal("2.00"))

    def test_quitar_producto(self):
        carrito = self.preparar_carrito()
        self.client.post(reverse("tienda:quitar", args=[carrito.items.get().pk]))
        self.assertTrue(carrito.esta_vacio())

    def test_vaciar_no_borra_otro_carrito(self):
        uno = self.preparar_carrito()
        dos = self.preparar_carrito(oferta=self.oferta2)
        self.client.post(reverse("tienda:vaciar", args=[uno.pk]))
        self.assertTrue(uno.esta_vacio())
        self.assertFalse(dos.esta_vacio())

    def test_ver_carrito_vacio_no_crea_objetos(self):
        respuesta = self.client.get(reverse("tienda:ver_carrito", args=[self.mercado.pk]))
        self.assertContains(respuesta, "Este carrito está vacío")
        self.assertFalse(Carrito.objects.exists())

    def test_producto_retirado_se_muestra_y_se_puede_quitar(self):
        carrito = self.preparar_carrito()
        self.oferta.delete()
        respuesta = self.client.get(reverse("tienda:ver_carrito", args=[self.mercado.pk]))
        self.assertContains(respuesta, "Producto no disponible")
        self.assertNotContains(respuesta, "Continuar pedido")
        self.client.post(reverse("tienda:quitar", args=[carrito.items.get().pk]))
        self.assertTrue(carrito.esta_vacio())

    def test_oferta_no_disponible_no_se_agrega(self):
        self.oferta.disponible = False
        self.oferta.save()
        self.client.post(reverse("tienda:agregar", args=[self.oferta.pk]), {"cantidad": "1"})
        self.assertFalse(ItemCarrito.objects.exists())

    def test_no_agrega_sin_cobertura(self):
        self.elegir_zona(self.sin_cobertura)
        self.client.post(reverse("tienda:agregar", args=[self.oferta.pk]), {"cantidad": "1"})
        self.assertFalse(ItemCarrito.objects.exists())

    def test_no_agrega_mercado_inactivo(self):
        self.mercado.activo = False
        self.mercado.save()
        self.client.post(reverse("tienda:agregar", args=[self.oferta.pk]), {"cantidad": "1"})
        self.assertFalse(ItemCarrito.objects.exists())

    def test_operaciones_get_no_modifican_carrito(self):
        carrito = self.preparar_carrito()
        item = carrito.items.get()
        for nombre, pk in (("agregar", self.oferta.pk), ("cambiar_cantidad", item.pk), ("quitar", item.pk), ("vaciar", carrito.pk)):
            with self.subTest(nombre=nombre):
                self.assertEqual(self.client.get(reverse("tienda:" + nombre, args=[pk])).status_code, 405)
        self.assertEqual(carrito.items.count(), 1)

    def test_lista_carritos_es_privada(self):
        self.preparar_carrito(usuario=self.otro)
        respuesta = self.client.get(reverse("tienda:carritos"))
        self.assertContains(respuesta, "Todavía no tienes productos")

    def test_csrf_obligatorio(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.usuario)
        respuesta = cliente.post(reverse("tienda:agregar", args=[self.oferta.pk]), {"cantidad": "1"})
        self.assertEqual(respuesta.status_code, 403)
        self.assertFalse(ItemCarrito.objects.exists())

    def test_csrf_valido_permite_comprar(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.usuario)
        sesion = cliente.session
        sesion["zona_id"] = self.zona.pk
        sesion.save()
        cliente.get(reverse("tienda:catalogo", args=[self.mercado.pk]))
        csrf = cliente.cookies["csrftoken"].value
        respuesta = cliente.post(reverse("tienda:agregar", args=[self.oferta.pk]), {"cantidad": "1", "csrfmiddlewaretoken": csrf})
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(ItemCarrito.objects.count(), 1)


class PedidosTest(DatosTest):
    def setUp(self):
        self.entrar()

    def test_get_no_confirma_y_envio_esta_en_resumen(self):
        carrito = self.preparar_carrito()
        respuesta = self.client.get(reverse("tienda:confirmar", args=[carrito.pk]))
        self.assertContains(respuesta, "Q27.00")
        self.assertFalse(Pedido.objects.exists())
        self.assertFalse(carrito.esta_vacio())

    def test_confirmacion_completa_y_carrito_vaciado(self):
        carrito = self.preparar_carrito()
        pedido, _ = self.comprar(carrito)
        self.assertEqual(pedido.subtotal, Decimal("17.00"))
        self.assertEqual(pedido.costo_envio, Decimal("10.00"))
        self.assertEqual(pedido.total, Decimal("27.00"))
        self.assertEqual(pedido.direccion_entrega, "5a avenida 10-20, casa verde")
        self.assertEqual(pedido.fecha_entrega, timezone.localdate() + timedelta(days=1))
        self.assertEqual(pedido.metodo_pago, "CONTRA_ENTREGA")
        self.assertEqual(pedido.estado, "RECIBIDO")
        self.assertEqual(pedido.items.count(), 1)
        self.assertTrue(carrito.esta_vacio())

    def test_precios_y_tarifas_posteriores_no_alteran_pedido(self):
        pedido, _ = self.comprar()
        self.oferta.precio = Decimal("99.99")
        self.oferta.save()
        self.cobertura.tarifa_envio = Decimal("50.00")
        self.cobertura.save()
        pedido.refresh_from_db()
        self.assertEqual(pedido.items.get().precio_unitario, Decimal("8.50"))
        self.assertEqual(pedido.calcular_subtotal(), Decimal("17.00"))
        self.assertEqual(pedido.calcular_total(), Decimal("27.00"))

    def test_precio_y_total_del_navegador_se_ignoran(self):
        carrito = self.preparar_carrito()
        datos = self.datos_pedido(carrito)
        datos.update(total="0.01", subtotal="0", precio="0.01", costo_envio="0")
        self.client.post(reverse("tienda:confirmar", args=[carrito.pk]), datos)
        self.assertEqual(Pedido.objects.get().total, Decimal("27.00"))

    def test_misma_confirmacion_no_duplica_y_no_consume_nueva_compra(self):
        carrito = self.preparar_carrito()
        pedido, datos = self.comprar(carrito)
        agregar_producto(self.usuario, self.oferta_unidad.pk, Decimal("1"), self.zona)
        respuesta = self.client.post(reverse("tienda:confirmar", args=[carrito.pk]), datos)
        self.assertRedirects(respuesta, reverse("tienda:detalle_pedido", args=[pedido.pk]))
        self.assertEqual(Pedido.objects.count(), 1)
        self.assertEqual(carrito.items.get().producto_id, self.unidad.pk)

    def test_carrito_vacio_no_se_confirma(self):
        carrito = Carrito.objects.create(usuario=self.usuario, mercado=self.mercado)
        respuesta = self.client.get(reverse("tienda:confirmar", args=[carrito.pk]))
        self.assertEqual(respuesta.status_code, 302)
        self.assertFalse(Pedido.objects.exists())

    def test_fecha_pasada_y_direccion_vacia_no_guardan(self):
        carrito = self.preparar_carrito()
        datos = self.datos_pedido(carrito)
        datos.update(direccion_entrega="   ", fecha_entrega=(timezone.localdate() - timedelta(days=1)).isoformat())
        respuesta = self.client.post(reverse("tienda:confirmar", args=[carrito.pk]), datos)
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("fecha_entrega", respuesta.context["form"].errors)
        self.assertIn("direccion_entrega", respuesta.context["form"].errors)
        self.assertFalse(Pedido.objects.exists())
        self.assertFalse(carrito.esta_vacio())

    def test_cambio_precio_exige_revisar_y_permite_reintentar(self):
        carrito = self.preparar_carrito()
        datos = self.datos_pedido(carrito)
        self.oferta.precio = Decimal("9.00")
        self.oferta.save()
        respuesta = self.client.post(reverse("tienda:confirmar", args=[carrito.pk]), datos)
        self.assertContains(respuesta, "cambiaron")
        self.assertFalse(Pedido.objects.exists())
        self.assertEqual(respuesta.context["total"], Decimal("28.00"))
        self.assertEqual(respuesta.context["form"]["direccion_entrega"].value(), datos["direccion_entrega"])
        datos["confirmacion"] = respuesta.context["form"]["confirmacion"].value()
        self.client.post(reverse("tienda:confirmar", args=[carrito.pk]), datos)
        self.assertEqual(Pedido.objects.get().total, Decimal("28.00"))

    def test_cambio_tarifa_exige_revisar(self):
        carrito = self.preparar_carrito()
        datos = self.datos_pedido(carrito)
        self.cobertura.tarifa_envio = Decimal("20.00")
        self.cobertura.save()
        respuesta = self.client.post(reverse("tienda:confirmar", args=[carrito.pk]), datos)
        self.assertContains(respuesta, "cambiaron")
        self.assertFalse(Pedido.objects.exists())

    def test_cambio_cantidad_exige_revisar(self):
        carrito = self.preparar_carrito()
        datos = self.datos_pedido(carrito)
        agregar_producto(self.usuario, self.oferta.pk, Decimal("1"), self.zona)
        respuesta = self.client.post(reverse("tienda:confirmar", args=[carrito.pk]), datos)
        self.assertContains(respuesta, "cambiaron")
        self.assertFalse(Pedido.objects.exists())

    def test_cambio_zona_exige_revisar(self):
        carrito = self.preparar_carrito()
        datos = self.datos_pedido(carrito)
        self.elegir_zona(self.zona2)
        respuesta = self.client.post(reverse("tienda:confirmar", args=[carrito.pk]), datos)
        self.assertContains(respuesta, "cambiaron")
        self.assertFalse(Pedido.objects.exists())

    def test_oferta_retirada_impide_confirmar(self):
        carrito = self.preparar_carrito()
        datos = self.datos_pedido(carrito)
        self.oferta.disponible = False
        self.oferta.save()
        respuesta = self.client.post(reverse("tienda:confirmar", args=[carrito.pk]), datos)
        self.assertEqual(respuesta.status_code, 302)
        self.assertFalse(Pedido.objects.exists())
        self.assertFalse(carrito.esta_vacio())

    def test_mercado_inactivo_impide_confirmar(self):
        carrito = self.preparar_carrito()
        datos = self.datos_pedido(carrito)
        self.mercado.activo = False
        self.mercado.save()
        self.client.post(reverse("tienda:confirmar", args=[carrito.pk]), datos)
        self.assertFalse(Pedido.objects.exists())

    def test_cobertura_eliminada_impide_confirmar(self):
        carrito = self.preparar_carrito()
        datos = self.datos_pedido(carrito)
        self.cobertura.delete()
        self.client.post(reverse("tienda:confirmar", args=[carrito.pk]), datos)
        self.assertFalse(Pedido.objects.exists())

    def test_token_modificado_no_confirma(self):
        carrito = self.preparar_carrito()
        datos = self.datos_pedido(carrito)
        datos["confirmacion"] += "alterado"
        respuesta = self.client.post(reverse("tienda:confirmar", args=[carrito.pk]), datos)
        self.assertContains(respuesta, "no es válida")
        self.assertFalse(Pedido.objects.exists())

    def test_token_vencido_no_confirma(self):
        carrito = self.preparar_carrito()
        datos = self.datos_pedido(carrito)
        with patch("tienda.servicios.VIGENCIA_CONFIRMACION", -1):
            respuesta = self.client.post(reverse("tienda:confirmar", args=[carrito.pk]), datos)
        self.assertContains(respuesta, "venció")
        self.assertFalse(Pedido.objects.exists())

    def test_error_en_segundo_item_revierte_pedido_completo(self):
        carrito = self.preparar_carrito()
        agregar_producto(self.usuario, self.oferta_unidad.pk, Decimal("1"), self.zona)
        datos = self.datos_pedido(carrito)
        guardar = ItemPedido.save
        contador = {"veces": 0}

        def guardar_o_fallar(instancia, *args, **kwargs):
            contador["veces"] += 1
            if contador["veces"] == 2:
                raise DatabaseError("Fallo simulado en el segundo renglón")
            return guardar(instancia, *args, **kwargs)

        with self.assertLogs("tienda.views", level="ERROR"):
            with patch.object(ItemPedido, "save", guardar_o_fallar):
                respuesta = self.client.post(reverse("tienda:confirmar", args=[carrito.pk]), datos)
        self.assertContains(respuesta, "No se pudo completar la operación")
        self.assertFalse(Pedido.objects.exists())
        self.assertFalse(ItemPedido.objects.exists())
        self.assertEqual(carrito.items.count(), 2)

    def test_redondeo_individual_coincide_con_total(self):
        self.oferta.precio = Decimal("0.05")
        self.oferta.save()
        carrito = self.preparar_carrito("0.10")
        pedido, _ = self.comprar(carrito)
        self.assertEqual(pedido.items.get().subtotal, Decimal("0.01"))
        self.assertEqual(pedido.subtotal, Decimal("0.01"))
        self.assertEqual(pedido.total, Decimal("10.01"))

    def test_centavos_en_envio_y_subtotal_no_producen_error(self):
        self.oferta.precio = Decimal("0.10")
        self.oferta.save()
        self.cobertura.tarifa_envio = Decimal("0.20")
        self.cobertura.save()
        pedido, _ = self.comprar(self.preparar_carrito("1"))
        self.assertEqual(pedido.total, Decimal("0.30"))

    def test_importe_mayor_que_capacidad_de_pedido_no_se_guarda(self):
        self.oferta.precio = Decimal("999999.99")
        self.oferta.save()
        carrito = self.preparar_carrito("9999.99")
        datos = self.datos_pedido(carrito)
        respuesta = self.client.post(reverse("tienda:confirmar", args=[carrito.pk]), datos)
        self.assertContains(respuesta, "excede el máximo permitido")
        self.assertFalse(Pedido.objects.exists())
        self.assertFalse(carrito.esta_vacio())

    def test_historial_y_detalle(self):
        pedido, _ = self.comprar()
        self.assertContains(self.client.get(reverse("tienda:pedidos")), f"Pedido #{pedido.pk}")
        self.assertContains(self.client.get(reverse("tienda:detalle_pedido", args=[pedido.pk])), "Pago contra entrega")

    def test_pedido_antiguo_puede_cambiar_estado(self):
        pedido, _ = self.comprar()
        Pedido.objects.filter(pk=pedido.pk).update(fecha_entrega=timezone.localdate() - timedelta(days=2))
        pedido.refresh_from_db()
        pedido.estado = Pedido.Estado.ENTREGADO
        pedido.full_clean()
        pedido.save()
        self.assertEqual(Pedido.objects.get().estado, "ENTREGADO")


class PermisosTest(DatosTest):
    def test_anonimo_no_usa_carrito(self):
        respuesta = self.client.post(reverse("tienda:agregar", args=[self.oferta.pk]), {"cantidad": "1"})
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse("tienda:ingresar"), respuesta.url)
        self.assertFalse(ItemCarrito.objects.exists())

    def test_no_se_modifican_items_ajenos(self):
        self.entrar()
        carrito = self.preparar_carrito(usuario=self.otro)
        item = carrito.items.get()
        for nombre in ("cambiar_cantidad", "quitar"):
            with self.subTest(nombre=nombre):
                respuesta = self.client.post(reverse("tienda:" + nombre, args=[item.pk]), {"cantidad": "99"})
                self.assertEqual(respuesta.status_code, 404)
        self.assertEqual(carrito.items.get().cantidad, Decimal("2.00"))

    def test_no_se_vacia_o_confirma_carrito_ajeno(self):
        self.entrar()
        carrito = self.preparar_carrito(usuario=self.otro)
        self.assertEqual(self.client.post(reverse("tienda:vaciar", args=[carrito.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("tienda:confirmar", args=[carrito.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("tienda:confirmar", args=[carrito.pk]), {}).status_code, 404)
        self.assertFalse(carrito.esta_vacio())

    def test_pedidos_solo_visibles_al_propietario(self):
        self.entrar()
        pedido, _ = self.comprar()
        self.entrar(self.otro)
        self.assertEqual(self.client.get(reverse("tienda:detalle_pedido", args=[pedido.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("tienda:pedidos")), f"Pedido #{pedido.pk}")

    def test_confirmacion_de_otro_carrito_no_funciona(self):
        self.entrar()
        carrito = self.preparar_carrito()
        datos = self.datos_pedido(carrito)
        otro_carrito = self.preparar_carrito(oferta=self.oferta2)
        respuesta = self.client.post(reverse("tienda:confirmar", args=[otro_carrito.pk]), datos)
        self.assertContains(respuesta, "no es válida")
        self.assertFalse(Pedido.objects.exists())

    def test_texto_del_usuario_se_escapa(self):
        self.entrar()
        carrito = self.preparar_carrito()
        datos = self.datos_pedido(carrito)
        datos["direccion_entrega"] = "<script>alert(1)</script> Calle 10"
        self.client.post(reverse("tienda:confirmar", args=[carrito.pk]), datos)
        pedido = Pedido.objects.get()
        respuesta = self.client.get(reverse("tienda:detalle_pedido", args=[pedido.pk]))
        self.assertNotContains(respuesta, "<script>alert(1)</script>")
        self.assertContains(respuesta, "&lt;script&gt;")


class IntegridadTest(DatosTest):
    def test_base_rechaza_cantidad_cero(self):
        carrito = Carrito.objects.create(usuario=self.usuario, mercado=self.mercado)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ItemCarrito.objects.create(carrito=carrito, producto=self.producto, cantidad=0)

    def test_base_rechaza_precio_negativo(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductoMercado.objects.filter(pk=self.oferta.pk).update(precio=-1)

    def test_base_rechaza_envio_negativo(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            MercadoZona.objects.filter(pk=self.cobertura.pk).update(tarifa_envio=-1)

    def test_modelo_rechaza_fracciones_de_unidades(self):
        carrito = Carrito.objects.create(usuario=self.usuario, mercado=self.mercado)
        item = ItemCarrito(carrito=carrito, producto=self.unidad, cantidad=Decimal("1.50"))
        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_modelo_rechaza_total_inconsistente(self):
        pedido = Pedido(usuario=self.usuario, mercado=self.mercado, zona=self.zona,
            direccion_entrega="Calle central, casa 10", fecha_entrega=timezone.localdate(),
            subtotal=Decimal("1.00"), costo_envio=Decimal("10.00"), total=Decimal("3.00"))
        with self.assertRaises(ValidationError):
            pedido.full_clean()

    def test_error_de_conexion_muestra_503_sin_consultar_otra_vez(self):
        with self.assertLogs("tienda.middleware", level="ERROR"):
            with patch("tienda.views.MercadoZona.objects.filter", side_effect=OperationalError("simulado")):
                respuesta = self.client.get(reverse("tienda:mercados"), {"zona": self.zona.pk})
        self.assertContains(respuesta, "No pudimos conectar", status_code=503)
        self.assertNotContains(respuesta, "simulado", status_code=503)

    def test_modelo_fecha_invalida_da_validacion_no_typeerror(self):
        pedido = Pedido(usuario=self.usuario, mercado=self.mercado, zona=self.zona,
            direccion_entrega="Calle central, casa 10", fecha_entrega="no-es-fecha",
            subtotal=Decimal("1.00"), costo_envio=Decimal("10.00"), total=Decimal("11.00"))
        with self.assertRaises(ValidationError):
            pedido.full_clean()

    def test_metodo_de_oferta_acepta_atributo_decimal_aun_sin_recargar(self):
        self.assertEqual(self.oferta.calcular_importe(Decimal("2.50")), Decimal("21.25"))

    def test_admin_puede_abrir_pedido_confirmado(self):
        self.entrar()
        pedido, _ = self.comprar()
        admin = get_user_model().objects.create_superuser(username="admin_prueba", email="admin@example.test", password=CLAVE)
        self.client.force_login(admin)
        respuesta = self.client.get(reverse("admin:tienda_pedido_change", args=[pedido.pk]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "precio_unitario")

    def test_admin_pedido_solo_permite_cambiar_estado(self):
        from django.contrib import admin
        configuracion = admin.site._registry[Pedido]
        self.assertIn("total", configuracion.readonly_fields)
        self.assertIn("direccion_entrega", configuracion.readonly_fields)
        self.assertNotIn("estado", configuracion.readonly_fields)
        self.assertFalse(configuracion.has_add_permission(None))
        self.assertFalse(configuracion.has_delete_permission(None))


class DatosInicialesTest(TestCase):
    fixtures = ["datos_iniciales"]

    def test_fixture_original_y_catalogos(self):
        self.assertEqual(Zona.objects.count(), 10)
        self.assertEqual(Mercado.objects.count(), 2)
        self.assertEqual(Producto.objects.count(), 30)
        self.assertEqual(ProductoMercado.objects.count(), 60)
        for cobertura in MercadoZona.objects.select_related("mercado", "zona"):
            with self.subTest(mercado=cobertura.mercado_id, zona=cobertura.zona_id):
                self.client.get(reverse("tienda:mercados"), {"zona": cobertura.zona_id})
                self.assertContains(self.client.get(reverse("tienda:catalogo", args=[cobertura.mercado_id])), cobertura.mercado.nombre)


@skipUnless(connection.vendor == "postgresql", "Requiere PostgreSQL real para probar bloqueos concurrentes.")
class ConcurrenciaPostgreSQLTest(TransactionTestCase):
    def setUp(self):
        crear_datos(self)
        self.carrito = agregar_producto(self.usuario, self.oferta.pk, Decimal("1"), self.zona).carrito

    def ejecutar_dos(self, operacion):
        barrera = Barrier(2)

        def trabajador():
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                barrera.wait(timeout=10)
                return operacion()
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=2) as ejecutor:
            futuros = [ejecutor.submit(trabajador) for _ in range(2)]
            return [futuro.result(timeout=15) for futuro in futuros]

    def test_dos_confirmaciones_simultaneas_generan_un_pedido(self):
        token = crear_confirmacion(self.carrito, resumen_carrito(self.carrito, self.zona))

        def comprar():
            pedido, creado = confirmar_compra(usuario=self.usuario, carrito_id=self.carrito.pk,
                zona=self.zona, direccion="Calle central, casa 10", fecha=timezone.localdate(), confirmacion=token)
            return pedido.pk, creado

        resultados = self.ejecutar_dos(comprar)
        self.assertEqual(Pedido.objects.count(), 1)
        self.assertEqual(len({pk for pk, _ in resultados}), 1)
        self.assertEqual(sum(creado for _, creado in resultados), 1)

    def test_dos_adiciones_simultaneas_no_pierden_cantidades(self):
        self.ejecutar_dos(lambda: agregar_producto(self.usuario, self.oferta.pk, Decimal("1"), self.zona).pk)
        self.assertEqual(self.carrito.items.get().cantidad, Decimal("3.00"))

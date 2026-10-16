"""Respuesta legible si una consulta de una vista falla por la base de datos."""
import logging
from django.db import DatabaseError
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)


class ErroresBaseDatosMiddleware(MiddlewareMixin):
    def process_exception(self, request, exception):
        if isinstance(exception, DatabaseError):
            logger.exception("Falló una operación de base de datos en %s", request.path)
            # La página de error no consulta usuario, sesión ni catálogo para poder mostrarse.
            if hasattr(request, "session"):
                request.session.modified = False
            return HttpResponse(render_to_string("tienda/error_base_datos.html"), status=503)
        return None

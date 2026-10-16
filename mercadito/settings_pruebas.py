"""Configuración opcional SOLO para pruebas sin servidor PostgreSQL.

Uso: python manage.py test tienda --settings=mercadito.settings_pruebas
La ejecución normal conserva PostgreSQL en settings.py. SQLite no reproduce
los bloqueos de filas ni todas las particularidades de PostgreSQL.
"""
from .settings import *  # noqa: F403

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
# El hash rápido se limita a esta configuración de pruebas, no al sitio real.
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
SECRET_KEY = "solo-pruebas-automatizadas-no-usar-para-servir-el-sitio"

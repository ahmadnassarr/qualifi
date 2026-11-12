"""Entry point for production servers, e.g.  gunicorn wsgi:app"""
from qualifi import create_app

app = create_app()
